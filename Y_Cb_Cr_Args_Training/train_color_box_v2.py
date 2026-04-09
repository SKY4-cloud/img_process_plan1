#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2 训练器：在 FPGA 一致链路下，用 **网格搜索 + 精调** 学习 Y/Cb/Cr 阈值盒，
以像素级 **F1-score** 作为优化目标，替代 v1 的贪心收紧策略。

核心改进：
  1) 优化目标改为 F1 = 2·P·R / (P+R)，比 pos_coverage/neg_fraction 更平衡
  2) 粗网格扫描（步长可调）→ 细网格精调（步长 1），全局搜索避免局部最优
  3) 支持三种子空间策略：联合6D / 先Cb-Cr后Y / 先Y后Cb-Cr
  4) 输出诊断散点图（--plot），直观看正/负样本分离度

使用方式与 train_color_box.py 兼容，仅优化核心更强：
  python train_color_box_v2.py -m my_manifest.yaml --wb gray_world -o trained_color_box.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

from fpga_color_chain import bgr_to_ycbcr_planes_rtl

# ──────────────────────────── Numba JIT 加速（可选）────────────────────────────
try:
    from numba import njit, prange
    _NUMBA_OK = True
except ImportError:
    _NUMBA_OK = False


def _make_jit_refine():
    """返回经 Numba JIT 编译的精调函数（仅在 numba 可用时调用）。"""
    from numba import njit, prange

    @njit(parallel=True, cache=True)
    def _refine_jit(
        pos_y: np.ndarray, pos_cb: np.ndarray, pos_cr: np.ndarray,
        neg_y: np.ndarray, neg_cb: np.ndarray, neg_cr: np.ndarray,
        yl_vals: np.ndarray, yh_vals: np.ndarray,
        cl_vals: np.ndarray, ch_vals: np.ndarray,
        rl_vals: np.ndarray, rh_vals: np.ndarray,
    ) -> tuple:
        n_pos = pos_y.shape[0]
        best_f1 = -1.0
        best_yl = yl_vals[0]; best_yh = yh_vals[0]
        best_cl = cl_vals[0]; best_ch = ch_vals[0]
        best_rl = rl_vals[0]; best_rh = rh_vals[0]

        for i in prange(len(yl_vals)):
            y_lo = yl_vals[i]
            for y_hi in yh_vals:
                if y_hi < y_lo:
                    continue
                for cb_lo in cl_vals:
                    for cb_hi in ch_vals:
                        if cb_hi < cb_lo:
                            continue
                        for cr_lo in rl_vals:
                            for cr_hi in rh_vals:
                                if cr_hi < cr_lo:
                                    continue
                                tp = 0
                                for k in range(n_pos):
                                    if (pos_y[k] >= y_lo and pos_y[k] <= y_hi and
                                            pos_cb[k] >= cb_lo and pos_cb[k] <= cb_hi and
                                            pos_cr[k] >= cr_lo and pos_cr[k] <= cr_hi):
                                        tp += 1
                                fp = 0
                                n_neg = neg_y.shape[0]
                                for k in range(n_neg):
                                    if (neg_y[k] >= y_lo and neg_y[k] <= y_hi and
                                            neg_cb[k] >= cb_lo and neg_cb[k] <= cb_hi and
                                            neg_cr[k] >= cr_lo and neg_cr[k] <= cr_hi):
                                        fp += 1
                                fn = n_pos - tp
                                if (tp + fp) == 0 or (tp + fn) == 0:
                                    continue
                                prec = tp / (tp + fp)
                                rec = tp / (tp + fn)
                                denom = prec + rec
                                if denom == 0.0:
                                    continue
                                f1 = 2.0 * prec * rec / denom
                                if f1 > best_f1:
                                    best_f1 = f1
                                    best_yl = y_lo; best_yh = y_hi
                                    best_cl = cb_lo; best_ch = cb_hi
                                    best_rl = cr_lo; best_rh = cr_hi

        return best_f1, best_yl, best_yh, best_cl, best_ch, best_rl, best_rh

    return _refine_jit


_jit_refine_fn = None  # 懒加载，首次调用时编译


# ──────────────────────────── 蓝底预过滤 ────────────────────────────

def blue_prefilter_mask(bgr_patch: np.ndarray) -> np.ndarray:
    """
    在 BGR 原图上用 HSV 色度过滤，返回布尔 mask 标记"看起来是蓝色"的像素。
    用于从 bbox 内剔除白色字符、铆钉、反光、深色边框等非蓝底像素。

    这是一个**宽松**的预过滤器——宁可多留一些蓝偏像素，也不要误删真正的蓝底。
    最终精确阈值由网格搜索在 FPGA YCbCr 空间中确定。

    中国蓝牌底色在 HSV 中大致分布：H ∈ [100, 130], S ∈ [80, 255], V ∈ [40, 255]
    放宽为: H ∈ [90, 140], S ∈ [40, 255], V ∈ [20, 255] 以涵盖暗光/色偏场景
    """
    hsv = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = (h >= 90) & (h <= 140) & (s >= 40) & (v >= 20)
    return mask


def blue_prefilter_mask_adaptive(bgr_patch: np.ndarray) -> np.ndarray:
    """
    自适应蓝底过滤：先做严格过滤，如果保留像素 < 20% 则逐步放宽，
    确保每张图都能采到足够的蓝底样本。
    """
    hsv = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    n_total = h.size

    thresholds = [
        (90, 140, 60, 30),   # 严格
        (85, 145, 40, 20),   # 中等
        (80, 150, 25, 15),   # 宽松
        (75, 155, 15, 10),   # 非常宽松
    ]
    for h_lo, h_hi, s_min, v_min in thresholds:
        mask = (h >= h_lo) & (h <= h_hi) & (s >= s_min) & (v >= v_min)
        ratio = np.count_nonzero(mask) / n_total if n_total > 0 else 0
        if ratio >= 0.20:
            return mask
    return mask


# ──────────────────────────── 数据采集 ────────────────────────────

def collect_pixels_bbox(
    root: Path,
    samples: list[dict],
    *,
    wb: str,
    max_pos_per_image: int,
    max_neg_per_image: int,
    seed: int,
    blue_filter: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    pos_chunks: list[np.ndarray] = []
    neg_chunks: list[np.ndarray] = []
    filter_stats: list[float] = []

    for si, item in enumerate(samples):
        rel = item.get("image")
        bbox = item.get("bbox")
        if not rel or not bbox or len(bbox) != 4:
            print(f"[!] skip bad sample: {item}", file=sys.stderr)
            continue
        path = root / str(rel)
        if not path.is_file():
            print(f"[!] skip missing: {path}", file=sys.stderr)
            continue
        bgr = cv2.imread(str(path))
        if bgr is None:
            print(f"[!] skip unreadable: {path}", file=sys.stderr)
            continue
        print(f"\r    [{si+1}/{len(samples)}] {rel}", end="", flush=True)

        H, W = bgr.shape[:2]
        bx, by, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        x0, y0 = max(0, min(bx, W - 1)), max(0, min(by, H - 1))
        x1, y1 = min(W, bx + max(0, bw)), min(H, by + max(0, bh))
        if x1 <= x0 or y1 <= y0:
            print(f"[!] skip empty bbox: {path}", file=sys.stderr)
            continue

        y_plane, cb_plane, cr_plane = bgr_to_ycbcr_planes_rtl(bgr, wb=wb)

        in_bbox = np.zeros((H, W), dtype=bool)
        in_bbox[y0:y1, x0:x1] = True

        if blue_filter:
            blue_mask = np.zeros((H, W), dtype=bool)
            blue_mask[y0:y1, x0:x1] = blue_prefilter_mask_adaptive(bgr[y0:y1, x0:x1])
            pos_mask = in_bbox & blue_mask
            bbox_total = max(1, (x1 - x0) * (y1 - y0))
            kept = np.count_nonzero(pos_mask)
            filter_stats.append(kept / bbox_total)
            if kept == 0:
                pos_mask = in_bbox
        else:
            pos_mask = in_bbox

        flat_y, flat_cb, flat_cr = y_plane.ravel(), cb_plane.ravel(), cr_plane.ravel()

        pos_idx = np.flatnonzero(pos_mask.ravel())
        neg_idx = np.flatnonzero((~in_bbox).ravel())
        if pos_idx.size == 0:
            continue

        if pos_idx.size > max_pos_per_image:
            sel = rng.choice(pos_idx.size, size=max_pos_per_image, replace=False)
            pos_idx = pos_idx[sel]
        if neg_idx.size > max_neg_per_image:
            sel = rng.choice(neg_idx.size, size=max_neg_per_image, replace=False)
            neg_idx = neg_idx[sel]

        pos_chunks.append(np.stack([flat_y[pos_idx], flat_cb[pos_idx], flat_cr[pos_idx]], axis=1))
        if neg_idx.size > 0:
            neg_chunks.append(np.stack([flat_y[neg_idx], flat_cb[neg_idx], flat_cr[neg_idx]], axis=1))

    print()
    if blue_filter and filter_stats:
        print(f"    Blue filter: kept {np.mean(filter_stats)*100:.1f}% of bbox pixels on avg "
              f"(min {np.min(filter_stats)*100:.1f}%, max {np.max(filter_stats)*100:.1f}%)")
    if not pos_chunks:
        raise RuntimeError("No positive pixels collected")
    if not neg_chunks:
        raise RuntimeError("No negative pixels collected")
    return np.vstack(pos_chunks).astype(np.uint8), np.vstack(neg_chunks).astype(np.uint8)


# ──────────────────────────── 评价指标 ────────────────────────────

def in_box_fast(pix: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """pix: (N,3), lo/hi: (3,) — 向量化判定是否在 [lo, hi] 盒内"""
    return np.all((pix >= lo) & (pix <= hi), axis=1)


def apply_linear_constraints(
    pix: np.ndarray,
    lines: list[dict],
) -> np.ndarray:
    """
    pix: (N,3) uint8, columns = [Y, Cb, Cr]
    lines: list of {"a": int, "b": int, "c": int, "t": int, "op": ">" or "<"}
        => a*Y + b*Cb + c*Cr  op  t
    Returns boolean mask (N,) — True if ALL constraints are satisfied.
    """
    if not lines:
        return np.ones(pix.shape[0], dtype=bool)
    mask = np.ones(pix.shape[0], dtype=bool)
    y = pix[:, 0].astype(np.int32)
    cb = pix[:, 1].astype(np.int32)
    cr = pix[:, 2].astype(np.int32)
    for ln in lines:
        val = ln["a"] * y + ln["b"] * cb + ln["c"] * cr
        if ln["op"] == ">":
            mask &= val > ln["t"]
        else:
            mask &= val < ln["t"]
    return mask


def compute_metrics(
    pos: np.ndarray, neg: np.ndarray, lo: np.ndarray, hi: np.ndarray,
    lines: list[dict] | None = None,
) -> dict:
    pos_box = in_box_fast(pos, lo, hi)
    neg_box = in_box_fast(neg, lo, hi)
    if lines:
        pos_box = pos_box & apply_linear_constraints(pos, lines)
        neg_box = neg_box & apply_linear_constraints(neg, lines)
    tp = int(np.count_nonzero(pos_box))
    fn = pos.shape[0] - tp
    fp = int(np.count_nonzero(neg_box))
    tn = neg.shape[0] - fp
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "pos_coverage": recall,
        "neg_fraction": fp / neg.shape[0] if neg.shape[0] > 0 else 0.0,
    }


# ──────────────────────────── 网格搜索 ────────────────────────────

def grid_search_6d(
    pos: np.ndarray,
    neg: np.ndarray,
    *,
    step: int = 5,
    margin_lo: float = 1.0,
    margin_hi: float = 99.0,
) -> tuple[np.ndarray, np.ndarray, float]:
    """
    在每个轴的 [P(margin_lo), P(margin_hi)] 范围内，按 step 步长穷举 6D 盒子，
    取 F1 最高的组合。
    """
    ranges = []
    for ch in range(3):
        plo = max(0, int(np.percentile(pos[:, ch], margin_lo)) - step)
        phi = min(255, int(np.percentile(pos[:, ch], margin_hi)) + step)
        ranges.append((plo, phi))

    best_f1 = -1.0
    best_lo = np.zeros(3, dtype=np.int32)
    best_hi = np.full(3, 255, dtype=np.int32)

    y_vals = np.arange(ranges[0][0], ranges[0][1] + 1, step)
    cb_vals = np.arange(ranges[1][0], ranges[1][1] + 1, step)
    cr_vals = np.arange(ranges[2][0], ranges[2][1] + 1, step)

    total = len(y_vals)**2 * len(cb_vals)**2 * len(cr_vals)**2
    print(f"[*] Coarse grid: Y {len(y_vals)} × Cb {len(cb_vals)} × Cr {len(cr_vals)} values per axis")
    print(f"    Total combinations (6D): ~{total:,}  (may take a while for step<5)")

    pos_y, pos_cb, pos_cr = pos[:, 0], pos[:, 1], pos[:, 2]
    neg_y, neg_cb, neg_cr = neg[:, 0], neg[:, 1], neg[:, 2]
    n_pos = pos.shape[0]
    n_neg = neg.shape[0]

    checked = 0
    t0 = time.time()

    for y_lo in y_vals:
        pos_y_mask_lo = pos_y >= y_lo
        neg_y_mask_lo = neg_y >= y_lo
        for y_hi in y_vals:
            if y_hi < y_lo:
                continue
            pos_y_ok = pos_y_mask_lo & (pos_y <= y_hi)
            neg_y_ok = neg_y_mask_lo & (neg_y <= y_hi)

            for cb_lo in cb_vals:
                pos_yc_ok = pos_y_ok & (pos_cb >= cb_lo)
                neg_yc_ok = neg_y_ok & (neg_cb >= cb_lo)
                for cb_hi in cb_vals:
                    if cb_hi < cb_lo:
                        continue
                    pos_ycb_ok = pos_yc_ok & (pos_cb <= cb_hi)
                    neg_ycb_ok = neg_yc_ok & (neg_cb <= cb_hi)

                    n_pos_ycb = np.count_nonzero(pos_ycb_ok)
                    if n_pos_ycb == 0:
                        checked += max(1, len(cr_vals) * (len(cr_vals) + 1) // 2)
                        continue

                    for cr_lo in cr_vals:
                        pos_all = pos_ycb_ok & (pos_cr >= cr_lo)
                        neg_all = neg_ycb_ok & (neg_cr >= cr_lo)
                        for cr_hi in cr_vals:
                            if cr_hi < cr_lo:
                                continue
                            checked += 1

                            tp = int(np.count_nonzero(pos_all & (pos_cr <= cr_hi)))
                            fp = int(np.count_nonzero(neg_all & (neg_cr <= cr_hi)))
                            fn = n_pos - tp

                            if (tp + fp) == 0 or (tp + fn) == 0:
                                continue
                            prec = tp / (tp + fp)
                            rec = tp / (tp + fn)
                            if prec + rec == 0:
                                continue
                            f1 = 2 * prec * rec / (prec + rec)

                            if f1 > best_f1:
                                best_f1 = f1
                                best_lo[:] = [y_lo, cb_lo, cr_lo]
                                best_hi[:] = [y_hi, cb_hi, cr_hi]

    elapsed = time.time() - t0
    print(f"    Checked ~{checked:,} combos in {elapsed:.1f}s, best F1={best_f1:.4f}")
    return best_lo.copy(), best_hi.copy(), best_f1


def refine_around(
    pos: np.ndarray,
    neg: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    *,
    radius: int = 6,
    bounds: dict | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """在粗搜结果 ± radius 范围内，步长 1 精调。
    若 numba 可用则使用多核 JIT 加速（~10-30x），否则退回 numpy 嵌套循环。
    """
    b = bounds or {}
    floor = [b.get("y_min", 0), b.get("cb_min", 0), b.get("cr_min", 0)]
    ceil  = [b.get("y_max", 255), b.get("cb_max", 255), b.get("cr_max", 255)]

    def clamp(v: int, lo_b: int, hi_b: int) -> int:
        return max(lo_b, min(hi_b, v))

    ranges_lo = [np.arange(clamp(lo[i] - radius, floor[i], ceil[i]),
                           clamp(lo[i] + radius, floor[i], ceil[i]) + 1, dtype=np.int32)
                 for i in range(3)]
    ranges_hi = [np.arange(clamp(hi[i] - radius, floor[i], ceil[i]),
                           clamp(hi[i] + radius, floor[i], ceil[i]) + 1, dtype=np.int32)
                 for i in range(3)]

    total = 1
    for i in range(3):
        total *= len(ranges_lo[i]) * len(ranges_hi[i])
    print(f"[*] Fine grid: ±{radius} around coarse optimum, ~{total:,} combos")

    pos_y  = pos[:, 0].astype(np.int32)
    pos_cb = pos[:, 1].astype(np.int32)
    pos_cr = pos[:, 2].astype(np.int32)
    neg_y  = neg[:, 0].astype(np.int32)
    neg_cb = neg[:, 1].astype(np.int32)
    neg_cr = neg[:, 2].astype(np.int32)
    n_pos  = pos.shape[0]

    best_lo = lo.copy().astype(np.int32)
    best_hi = hi.copy().astype(np.int32)

    # ── Numba JIT 路径 ────────────────────────────────────────────────────────
    if _NUMBA_OK:
        global _jit_refine_fn
        if _jit_refine_fn is None:
            print("    [jit] Compiling Numba kernel (one-time, ~5s)...")
            _jit_refine_fn = _make_jit_refine()
            # warmup：用极小数组触发编译
            _tiny = np.array([128], dtype=np.int32)
            _jit_refine_fn(_tiny, _tiny, _tiny, _tiny, _tiny, _tiny,
                           _tiny, _tiny, _tiny, _tiny, _tiny, _tiny)
        t0 = time.time()
        result = _jit_refine_fn(
            pos_y, pos_cb, pos_cr, neg_y, neg_cb, neg_cr,
            ranges_lo[0], ranges_hi[0],
            ranges_lo[1], ranges_hi[1],
            ranges_lo[2], ranges_hi[2],
        )
        best_f1, yl, yh, cl, ch, rl, rh = result
        best_lo[:] = [yl, cl, rl]
        best_hi[:] = [yh, ch, rh]
        elapsed = time.time() - t0
        print(f"    Fine search done (numba) in {elapsed:.1f}s, best F1={best_f1:.4f}")
        return best_lo.copy(), best_hi.copy(), float(best_f1)

    # ── 纯 NumPy 回退路径 ─────────────────────────────────────────────────────
    best_f1 = -1.0
    t0 = time.time()

    for y_lo_v in ranges_lo[0]:
        pos_y_lo = pos_y >= y_lo_v
        neg_y_lo = neg_y >= y_lo_v
        for y_hi_v in ranges_hi[0]:
            if y_hi_v < y_lo_v:
                continue
            pos_y_ok = pos_y_lo & (pos_y <= y_hi_v)
            neg_y_ok = neg_y_lo & (neg_y <= y_hi_v)

            for cb_lo_v in ranges_lo[1]:
                pos_yc = pos_y_ok & (pos_cb >= cb_lo_v)
                neg_yc = neg_y_ok & (neg_cb >= cb_lo_v)
                for cb_hi_v in ranges_hi[1]:
                    if cb_hi_v < cb_lo_v:
                        continue
                    pos_ycb = pos_yc & (pos_cb <= cb_hi_v)
                    neg_ycb = neg_yc & (neg_cb <= cb_hi_v)

                    for cr_lo_v in ranges_lo[2]:
                        pos_all = pos_ycb & (pos_cr >= cr_lo_v)
                        neg_all = neg_ycb & (neg_cr >= cr_lo_v)
                        for cr_hi_v in ranges_hi[2]:
                            if cr_hi_v < cr_lo_v:
                                continue

                            tp = int(np.count_nonzero(pos_all & (pos_cr <= cr_hi_v)))
                            fp = int(np.count_nonzero(neg_all & (neg_cr <= cr_hi_v)))
                            fn = n_pos - tp

                            denom_p = tp + fp
                            denom_r = tp + fn
                            if denom_p == 0 or denom_r == 0:
                                continue
                            prec = tp / denom_p
                            rec  = tp / denom_r
                            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

                            if f1 > best_f1:
                                best_f1 = f1
                                best_lo[:] = [y_lo_v, cb_lo_v, cr_lo_v]
                                best_hi[:] = [y_hi_v, cb_hi_v, cr_hi_v]

    elapsed = time.time() - t0
    print(f"    Fine search done in {elapsed:.1f}s, best F1={best_f1:.4f}")
    return best_lo.copy(), best_hi.copy(), best_f1


def search_sequential_2stage(
    pos: np.ndarray,
    neg: np.ndarray,
    *,
    step: int = 3,
    margin_lo: float = 1.0,
    margin_hi: float = 99.0,
    refine_radius: int = 4,
    bounds: dict | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """
    分两阶段降维搜索（对 6D 网格过大时的折中）：
      Stage 1: 固定 Y 全范围 [0,255]，只搜 Cb/Cr 4D → 最优 Cb/Cr
      Stage 2: 固定 Cb/Cr，只搜 Y 2D → 最优 Y
      Stage 3: 联合 6D ± refine_radius 精调

    bounds: optional dict with keys y_max, cr_max, cb_min etc. to clamp search range
    """
    b = bounds or {}
    y_ceil = b.get("y_max", 255)
    y_floor = b.get("y_min", 0)
    cb_ceil = b.get("cb_max", 255)
    cb_floor = b.get("cb_min", 0)
    cr_ceil = b.get("cr_max", 255)
    cr_floor = b.get("cr_min", 0)

    if any(v < 255 for v in [y_ceil, cr_ceil, cb_ceil]) or any(v > 0 for v in [y_floor, cb_floor, cr_floor]):
        print(f"    Bounds: Y=[{y_floor},{y_ceil}] Cb=[{cb_floor},{cb_ceil}] Cr=[{cr_floor},{cr_ceil}]")

    print("[*] Stage 1: Search Cb/Cr (Y fixed at data range)")
    y_lo_init = max(y_floor, int(np.percentile(pos[:, 0], margin_lo)) - 5)
    y_hi_init = min(y_ceil, int(np.percentile(pos[:, 0], margin_hi)) + 5)

    best_f1 = -1.0
    best_cb_lo, best_cb_hi = 0, 255
    best_cr_lo, best_cr_hi = 0, 255

    pos_y, pos_cb, pos_cr = pos[:, 0], pos[:, 1], pos[:, 2]
    neg_y, neg_cb, neg_cr = neg[:, 0], neg[:, 1], neg[:, 2]
    n_pos = pos.shape[0]

    pos_y_ok = (pos_y >= y_lo_init) & (pos_y <= y_hi_init)
    neg_y_ok = (neg_y >= y_lo_init) & (neg_y <= y_hi_init)

    cb_plo = max(cb_floor, int(np.percentile(pos[:, 1], margin_lo)) - 2 * step)
    cb_phi = min(cb_ceil, int(np.percentile(pos[:, 1], margin_hi)) + 2 * step)
    cr_plo = max(cr_floor, int(np.percentile(pos[:, 2], margin_lo)) - 2 * step)
    cr_phi = min(cr_ceil, int(np.percentile(pos[:, 2], margin_hi)) + 2 * step)

    cb_lo_vals = np.arange(cb_plo, int(np.percentile(pos[:, 1], 50)) + 1, step)
    cb_hi_vals = np.arange(int(np.percentile(pos[:, 1], 50)), cb_phi + 1, step)
    cr_lo_vals = np.arange(cr_plo, int(np.percentile(pos[:, 2], 50)) + 1, step)
    cr_hi_vals = np.arange(int(np.percentile(pos[:, 2], 50)), cr_phi + 1, step)

    total_s1 = len(cb_lo_vals) * len(cb_hi_vals) * len(cr_lo_vals) * len(cr_hi_vals)
    print(f"    Cb_lo:[{cb_plo},{int(np.percentile(pos[:,1],50))}] Cb_hi:[{int(np.percentile(pos[:,1],50))},{cb_phi}]")
    print(f"    Cr_lo:[{cr_plo},{int(np.percentile(pos[:,2],50))}] Cr_hi:[{int(np.percentile(pos[:,2],50))},{cr_phi}]")
    print(f"    Stage 1 combos: ~{total_s1:,}")

    t0 = time.time()
    checked_s1 = 0
    for cb_lo in cb_lo_vals:
        pos_c1 = pos_y_ok & (pos_cb >= cb_lo)
        neg_c1 = neg_y_ok & (neg_cb >= cb_lo)
        for cb_hi in cb_hi_vals:
            if cb_hi < cb_lo:
                continue
            pos_c2 = pos_c1 & (pos_cb <= cb_hi)
            neg_c2 = neg_c1 & (neg_cb <= cb_hi)
            for cr_lo in cr_lo_vals:
                pos_c3 = pos_c2 & (pos_cr >= cr_lo)
                neg_c3 = neg_c2 & (neg_cr >= cr_lo)
                for cr_hi in cr_hi_vals:
                    if cr_hi < cr_lo:
                        continue
                    checked_s1 += 1
                    tp = int(np.count_nonzero(pos_c3 & (pos_cr <= cr_hi)))
                    fp = int(np.count_nonzero(neg_c3 & (neg_cr <= cr_hi)))
                    fn_full = n_pos - tp
                    if (tp + fp) == 0:
                        continue
                    prec = tp / (tp + fp)
                    rec = tp / (tp + fn_full)
                    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
                    if f1 > best_f1:
                        best_f1 = f1
                        best_cb_lo, best_cb_hi = cb_lo, cb_hi
                        best_cr_lo, best_cr_hi = cr_lo, cr_hi
    print(f"    Checked {checked_s1:,} combos in {time.time()-t0:.1f}s")

    print(f"    Stage 1 best: Cb=[{best_cb_lo},{best_cb_hi}] Cr=[{best_cr_lo},{best_cr_hi}] F1={best_f1:.4f}")

    print("[*] Stage 2: Search Y (Cb/Cr fixed)")
    y_plo = max(y_floor, int(np.percentile(pos[:, 0], margin_lo)) - 2 * step)
    y_phi = min(y_ceil, int(np.percentile(pos[:, 0], margin_hi)) + 2 * step)
    y_lo_vals = np.arange(y_plo, int(np.percentile(pos[:, 0], 50)) + 1, step)
    y_hi_vals = np.arange(int(np.percentile(pos[:, 0], 50)), y_phi + 1, step)

    pos_cb_ok = (pos_cb >= best_cb_lo) & (pos_cb <= best_cb_hi)
    neg_cb_ok = (neg_cb >= best_cb_lo) & (neg_cb <= best_cb_hi)
    pos_cr_ok = (pos_cr >= best_cr_lo) & (pos_cr <= best_cr_hi)
    neg_cr_ok = (neg_cr >= best_cr_lo) & (neg_cr <= best_cr_hi)
    pos_cbcr = pos_cb_ok & pos_cr_ok
    neg_cbcr = neg_cb_ok & neg_cr_ok

    best_y_lo, best_y_hi = y_lo_init, y_hi_init
    best_f1_y = -1.0
    for y_lo in y_lo_vals:
        p1 = pos_cbcr & (pos_y >= y_lo)
        n1 = neg_cbcr & (neg_y >= y_lo)
        for y_hi in y_hi_vals:
            if y_hi < y_lo:
                continue
            tp = int(np.count_nonzero(p1 & (pos_y <= y_hi)))
            fp = int(np.count_nonzero(n1 & (neg_y <= y_hi)))
            fn = n_pos - tp
            if (tp + fp) == 0:
                continue
            prec = tp / (tp + fp)
            rec = tp / (tp + fn)
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            if f1 > best_f1_y:
                best_f1_y = f1
                best_y_lo, best_y_hi = y_lo, y_hi

    print(f"    Stage 2 best: Y=[{best_y_lo},{best_y_hi}] F1={best_f1_y:.4f}")

    lo = np.array([best_y_lo, best_cb_lo, best_cr_lo], dtype=np.int32)
    hi = np.array([best_y_hi, best_cb_hi, best_cr_hi], dtype=np.int32)

    print("[*] Stage 3: Fine-tune all 6 params jointly")
    lo, hi, f1 = refine_around(pos, neg, lo, hi, radius=refine_radius, bounds=bounds)
    return lo, hi, f1


# ──────────────────────────── 可视化 ────────────────────────────

def plot_distributions(
    pos: np.ndarray,
    neg: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    output_path: Path,
    lines: list[dict] | None = None,
) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches
    except ImportError:
        print("[!] matplotlib not installed, skip plot", file=sys.stderr)
        return

    labels = ["Y", "Cb", "Cr"]
    pairs = [(1, 2, "Cb", "Cr"), (0, 1, "Y", "Cb"), (0, 2, "Y", "Cr")]
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    n_pos_show = min(5000, pos.shape[0])
    n_neg_show = min(5000, neg.shape[0])
    rng = np.random.default_rng(0)
    pos_s = pos[rng.choice(pos.shape[0], n_pos_show, replace=False)] if pos.shape[0] > n_pos_show else pos
    neg_s = neg[rng.choice(neg.shape[0], n_neg_show, replace=False)] if neg.shape[0] > n_neg_show else neg

    # axis index mapping: Y=0, Cb=1, Cr=2
    for ax, (i, j, xl, yl) in zip(axes, pairs):
        ax.scatter(neg_s[:, i], neg_s[:, j], s=1, alpha=0.15, c="gray", label="neg")
        ax.scatter(pos_s[:, i], pos_s[:, j], s=1, alpha=0.4, c="blue", label="pos")
        rect = patches.Rectangle(
            (lo[i], lo[j]),
            hi[i] - lo[i],
            hi[j] - lo[j],
            linewidth=2, edgecolor="red", facecolor="none", linestyle="--",
            label="box",
        )
        ax.add_patch(rect)

        if lines:
            coeffs_map = {0: "a", 1: "b", 2: "c"}  # Y, Cb, Cr
            for li, ln in enumerate(lines):
                ci = ln[coeffs_map[i]]  # coeff for x-axis
                cj = ln[coeffs_map[j]]  # coeff for y-axis
                # remaining axis coeff: we fix it at its midpoint
                remaining = [k for k in range(3) if k != i and k != j][0]
                cr_mid = (int(lo[remaining]) + int(hi[remaining])) // 2
                c_rem = ln[coeffs_map[remaining]]

                if cj == 0:
                    if ci == 0:
                        continue
                    # vertical line: ci * x + c_rem * mid  op  T
                    x_val = (ln["t"] - c_rem * cr_mid) / ci if ci != 0 else 0
                    ax.axvline(x_val, color="green", linewidth=1.5, linestyle="-",
                               label=f"line{li+1}" if li == 0 or True else "")
                else:
                    # y = (T - ci*x - c_rem*mid) / cj
                    x_arr = np.linspace(0, 255, 200)
                    y_arr = (ln["t"] - ci * x_arr - c_rem * cr_mid) / cj
                    ax.plot(x_arr, y_arr, color="green", linewidth=1.5, linestyle="-",
                            label=f"line{li+1}" if True else "")

        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
        ax.set_xlim(0, 255)
        ax.set_ylim(0, 255)
        ax.legend(loc="upper right", markerscale=5)
        ax.set_aspect("equal")

    title = "Positive / Negative pixel distributions in YCbCr (FPGA chain)"
    if lines:
        title += f" + {len(lines)} linear"
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150)
    plt.close(fig)
    print(f"[+] Distribution plot: {output_path}")


def plot_per_image_stats(
    root: Path,
    samples: list[dict],
    lo: np.ndarray,
    hi: np.ndarray,
    wb: str,
    output_path: Path,
    lines: list[dict] | None = None,
) -> None:
    """每张图单独统计 recall/precision/F1，输出柱状图"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[!] matplotlib not installed, skip per-image plot", file=sys.stderr)
        return

    names, recalls, precisions, f1s = [], [], [], []
    for item in samples:
        rel = item.get("image", "")
        bbox = item.get("bbox")
        if not rel or not bbox or len(bbox) != 4:
            continue
        path = root / str(rel)
        if not path.is_file():
            continue
        bgr = cv2.imread(str(path))
        if bgr is None:
            continue
        H, W = bgr.shape[:2]
        bx, by, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        x0, y0 = max(0, bx), max(0, by)
        x1, y1 = min(W, bx + max(0, bw)), min(H, by + max(0, bh))
        if x1 <= x0 or y1 <= y0:
            continue

        y_p, cb_p, cr_p = bgr_to_ycbcr_planes_rtl(bgr, wb=wb)
        inside = np.zeros((H, W), dtype=bool)
        inside[y0:y1, x0:x1] = True

        pix_all = np.stack([y_p.ravel(), cb_p.ravel(), cr_p.ravel()], axis=1)
        flat_in = inside.ravel()
        pos_pix = pix_all[flat_in]
        neg_pix = pix_all[~flat_in]

        m = compute_metrics(pos_pix, neg_pix, lo, hi, lines)
        names.append(Path(rel).stem)
        recalls.append(m["recall"])
        precisions.append(m["precision"])
        f1s.append(m["f1"])

    if not names:
        return

    x = np.arange(len(names))
    w = 0.25
    fig, ax = plt.subplots(figsize=(max(8, len(names) * 0.8), 5))
    ax.bar(x - w, recalls, w, label="Recall", color="steelblue")
    ax.bar(x, precisions, w, label="Precision", color="orange")
    ax.bar(x + w, f1s, w, label="F1", color="green")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title("Per-image pixel-level Recall / Precision / F1")
    ax.legend()
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150)
    plt.close(fig)
    print(f"[+] Per-image stats plot: {output_path}")


# ──────────────────────────── 线性约束搜索 ────────────────────────

def search_linear_constraints(
    pos: np.ndarray,
    neg: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    *,
    max_lines: int = 2,
) -> tuple[list[dict], float]:
    """
    在已有盒子约束的基础上，搜索最多 max_lines 条线性约束来进一步提升 F1。

    FPGA 实现形式: a*Cb + b*Cr ≷ T  (8-bit signed coefficients, 16-bit threshold)
    搜索空间：
      - Cb-Cr 平面: a*Cb + b*Cr > T  (切掉 Cb 低 + Cr 高的负样本角)
      - Cb-Cr 平面: a*Cb - b*Cr > T  (切掉 Cb 低 + Cr 低的负样本角)
      - Cb+Y 关系: a*Cb + b*Y > T

    使用候选模板 + 阈值扫描，避免 3D 搜索爆炸。
    """
    base_f1 = compute_metrics(pos, neg, lo, hi)["f1"]
    print(f"[*] Linear constraint search (base F1={base_f1:.4f})")

    pos_in_box = in_box_fast(pos, lo, hi)
    neg_in_box = in_box_fast(neg, lo, hi)

    pos_y = pos[:, 0].astype(np.int32)
    pos_cb = pos[:, 1].astype(np.int32)
    pos_cr = pos[:, 2].astype(np.int32)
    neg_y = neg[:, 0].astype(np.int32)
    neg_cb = neg[:, 1].astype(np.int32)
    neg_cr = neg[:, 2].astype(np.int32)
    n_pos = pos.shape[0]

    # candidate directions: (a_y, a_cb, a_cr, op)
    # FPGA cost: each line needs 2 multipliers + 1 adder + 1 comparator
    candidates = []
    # Cb - k*Cr > T  (main separator: high Cb, low Cr = blue)
    for kb in range(1, 9):
        for kc in range(1, 6):
            if kb == kc:
                candidates.append((0, kb, -kc, ">"))
            elif kb > kc:
                candidates.append((0, kb, -kc, ">"))
    # Cb + k*Cr > T  (lower-left exclusion)
    for kb in range(1, 5):
        for kc in range(1, 4):
            candidates.append((0, kb, kc, ">"))
    # Y-Cb combined
    for ka in [-1, -2, 1]:
        for kb in range(1, 5):
            candidates.append((ka, kb, 0, ">"))
    # Upper bound variants
    for kb in range(1, 5):
        for kc in range(1, 4):
            candidates.append((0, kb, -kc, "<"))
    # Y-Cr combined
    for ka in [-1, 1]:
        for kc in range(-3, 4):
            if kc == 0:
                continue
            candidates.append((ka, 0, kc, ">"))
    # deduplicate
    candidates = list(set(candidates))

    found_lines: list[dict] = []
    current_pos_mask = pos_in_box.copy()
    current_neg_mask = neg_in_box.copy()

    for line_idx in range(max_lines):
        best_line = None
        best_f1 = compute_metrics(pos, neg, lo, hi, found_lines)["f1"]

        for a_y, a_cb, a_cr, op in candidates:
            pos_val = a_y * pos_y + a_cb * pos_cb + a_cr * pos_cr
            neg_val = a_y * neg_y + a_cb * neg_cb + a_cr * neg_cr

            pos_vals_inbox = pos_val[current_pos_mask]
            neg_vals_inbox = neg_val[current_neg_mask]

            if pos_vals_inbox.size == 0 or neg_vals_inbox.size == 0:
                continue

            if op == ">":
                t_lo = int(np.percentile(pos_vals_inbox, 0.5))
                t_hi = int(np.percentile(pos_vals_inbox, 35))
                t_range = np.arange(t_lo, t_hi + 1, max(1, (t_hi - t_lo) // 150))
            else:
                t_lo = int(np.percentile(pos_vals_inbox, 65))
                t_hi = int(np.percentile(pos_vals_inbox, 99.5))
                t_range = np.arange(t_lo, t_hi + 1, max(1, (t_hi - t_lo) // 150))

            for t in t_range:
                trial = {"a": a_y, "b": a_cb, "c": a_cr, "t": int(t), "op": op}
                trial_lines = found_lines + [trial]

                pos_pass = current_pos_mask.copy()
                neg_pass = current_neg_mask.copy()
                if op == ">":
                    pos_pass &= pos_val > t
                    neg_pass &= neg_val > t
                else:
                    pos_pass &= pos_val < t
                    neg_pass &= neg_val < t

                tp = int(np.count_nonzero(pos_pass))
                fp = int(np.count_nonzero(neg_pass))
                fn = n_pos - tp
                if (tp + fp) == 0 or tp == 0:
                    continue
                prec = tp / (tp + fp)
                rec = tp / n_pos
                f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

                if f1 > best_f1:
                    best_f1 = f1
                    best_line = trial.copy()

        if best_line is None:
            print(f"    Line {line_idx+1}: no improvement found")
            break

        found_lines.append(best_line)
        a, b, c, t, op = best_line["a"], best_line["b"], best_line["c"], best_line["t"], best_line["op"]
        print(f"    Line {line_idx+1}: {a}*Y + {b}*Cb + {c}*Cr {op} {t}  → F1={best_f1:.4f}")

        line_val_pos = a * pos_y + b * pos_cb + c * pos_cr
        line_val_neg = a * neg_y + b * neg_cb + c * neg_cr
        if op == ">":
            current_pos_mask &= line_val_pos > t
            current_neg_mask &= line_val_neg > t
        else:
            current_pos_mask &= line_val_pos < t
            current_neg_mask &= line_val_neg < t

    # fine-tune thresholds with step=1
    if found_lines:
        print("[*] Fine-tuning linear thresholds (±15)...")
        for li in range(len(found_lines)):
            ln = found_lines[li]
            base_t = ln["t"]
            best_t = base_t
            best_f1_t = compute_metrics(pos, neg, lo, hi, found_lines)["f1"]
            for dt in range(-15, 16):
                found_lines[li] = {**ln, "t": base_t + dt}
                m = compute_metrics(pos, neg, lo, hi, found_lines)
                if m["f1"] > best_f1_t:
                    best_f1_t = m["f1"]
                    best_t = base_t + dt
            found_lines[li] = {**ln, "t": best_t}
            print(f"    Line {li+1} threshold: {base_t} → {best_t}, F1={best_f1_t:.4f}")

    final_m = compute_metrics(pos, neg, lo, hi, found_lines)
    print(f"    Final F1 with {len(found_lines)} linear constraint(s): {final_m['f1']:.4f}")
    return found_lines, final_m["f1"]


def plot_blue_filter_preview(
    root: Path,
    samples: list[dict],
    output_path: Path,
    max_show: int = 8,
) -> None:
    """展示每张图 bbox 区域的原图 vs 蓝底 mask，直观验证预过滤质量"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[!] matplotlib not installed, skip filter preview", file=sys.stderr)
        return

    panels: list[tuple[str, np.ndarray, np.ndarray]] = []
    for item in samples:
        rel = item.get("image", "")
        bbox = item.get("bbox")
        if not rel or not bbox or len(bbox) != 4:
            continue
        path = root / str(rel)
        if not path.is_file():
            continue
        bgr = cv2.imread(str(path))
        if bgr is None:
            continue
        bx, by, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        H, W = bgr.shape[:2]
        x0, y0 = max(0, bx), max(0, by)
        x1, y1 = min(W, bx + max(0, bw)), min(H, by + max(0, bh))
        if x1 <= x0 or y1 <= y0:
            continue
        patch = bgr[y0:y1, x0:x1]
        mask = blue_prefilter_mask_adaptive(patch)
        panels.append((Path(rel).stem, patch, mask))
        if len(panels) >= max_show:
            break

    if not panels:
        return

    n = len(panels)
    fig, axes = plt.subplots(2, n, figsize=(n * 2.5, 5))
    if n == 1:
        axes = axes.reshape(2, 1)
    for i, (name, patch, mask) in enumerate(panels):
        rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
        axes[0, i].imshow(rgb)
        axes[0, i].set_title(name, fontsize=8)
        axes[0, i].axis("off")
        overlay = rgb.copy()
        overlay[~mask] = (overlay[~mask].astype(np.int32) * 3 // 10).astype(np.uint8)
        kept_pct = np.count_nonzero(mask) / max(1, mask.size) * 100
        axes[1, i].imshow(overlay)
        axes[1, i].set_title(f"blue: {kept_pct:.0f}%", fontsize=8)
        axes[1, i].axis("off")
    fig.suptitle("Blue pre-filter: top=original bbox, bottom=blue pixels highlighted", fontsize=11)
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150)
    plt.close(fig)
    print(f"[+] Blue filter preview: {output_path}")


# ──────────────────────────── Verilog 输出 ────────────────────────

def verilog_snippet(lo: np.ndarray, hi: np.ndarray) -> str:
    return (
        f"    parameter CB_MIN     = 8'd{lo[1]},\n"
        f"    parameter CB_MAX     = 8'd{hi[1]},\n"
        f"    parameter CR_MIN     = 8'd{lo[2]},\n"
        f"    parameter CR_MAX     = 8'd{hi[2]},\n"
        f"    parameter Y_MIN      = 8'd{lo[0]},\n"
        f"    parameter Y_MAX      = 8'd{hi[0]},"
    )


def verilog_linear_snippet(lines: list[dict]) -> str:
    """Generate Verilog parameter + logic snippets for linear constraints."""
    parts = []
    parts.append("    // --- linear constraints (add to parameter list) ---")
    for i, ln in enumerate(lines):
        idx = i + 1
        parts.append(f"    parameter signed [8:0]  LINE{idx}_A = 9'sd{ln['a']},  // Y coeff")
        parts.append(f"    parameter signed [8:0]  LINE{idx}_B = 9'sd{ln['b']},  // Cb coeff")
        parts.append(f"    parameter signed [8:0]  LINE{idx}_C = 9'sd{ln['c']},  // Cr coeff")
        parts.append(f"    parameter signed [17:0] LINE{idx}_T = 18'sd{ln['t']}, // threshold")
    parts.append("")
    parts.append("    // --- linear constraint logic (add near blue_fg) ---")
    for i, ln in enumerate(lines):
        idx = i + 1
        op_str = ">" if ln["op"] == ">" else "<"
        parts.append(
            f"    wire signed [17:0] line{idx}_val = "
            f"LINE{idx}_A * $signed({{1'b0, y_data}}) + "
            f"LINE{idx}_B * $signed({{1'b0, cb_data}}) + "
            f"LINE{idx}_C * $signed({{1'b0, cr_data}});"
        )
        parts.append(f"    wire line{idx}_ok = (line{idx}_val {op_str} LINE{idx}_T);")

    line_oks = " && ".join(f"line{i+1}_ok" for i in range(len(lines)))
    parts.append(f"    // replace blue_fg with: blue_fg_box && {line_oks}")
    return "\n".join(parts)


# ──────────────────────────── 主函数 ────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="v2: Grid-search Y/Cb/Cr box optimized by F1-score (FPGA-consistent chain)"
    )
    ap.add_argument("-m", "--manifest", type=Path, required=True)
    ap.add_argument("--wb", choices=("none", "gray_world"), default="none")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-pos-per-image", type=int, default=3000)
    ap.add_argument("--max-neg-per-image", type=int, default=8000)
    ap.add_argument("--max-total-samples", type=int, default=80000,
                    help="Per-class cap before search; 0=no cap")
    ap.add_argument("--coarse-step", type=int, default=5,
                    help="Grid step for coarse search (default 5)")
    ap.add_argument("--refine-radius", type=int, default=6,
                    help="±radius for fine-tuning around coarse optimum")
    ap.add_argument("--strategy", choices=("sequential", "full6d"), default="sequential",
                    help="sequential: Cb/Cr first then Y (fast); full6d: brute 6D (slow but thorough)")
    ap.add_argument("--no-blue-filter", action="store_true",
                    help="Disable HSV blue pre-filter on bbox interior (use all bbox pixels as positive)")
    ap.add_argument("--y-max", type=int, default=255, help="Hard upper limit for Y_MAX (prevent over-wide Y range)")
    ap.add_argument("--y-min", type=int, default=0, help="Hard lower limit for Y_MIN")
    ap.add_argument("--cr-max", type=int, default=255, help="Hard upper limit for CR_MAX")
    ap.add_argument("--cr-min", type=int, default=0, help="Hard lower limit for CR_MIN")
    ap.add_argument("--cb-max", type=int, default=255, help="Hard upper limit for CB_MAX")
    ap.add_argument("--cb-min", type=int, default=0, help="Hard lower limit for CB_MIN")
    ap.add_argument("--linear", type=int, default=0, metavar="N",
                    help="Add up to N linear constraints on top of the box (0=box only, 1-2 recommended)")
    ap.add_argument("--plot", action="store_true",
                    help="Output diagnostic scatter plots (requires matplotlib)")
    ap.add_argument("-o", "--output-json", type=Path, default=Path("trained_color_box.json"))
    args = ap.parse_args()

    with open(args.manifest.resolve(), encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    root = Path(manifest["dataset_root"]).resolve()
    samples = manifest["samples"]
    print(f"[*] Manifest: {args.manifest} ({len(samples)} samples)")
    print(f"[*] WB={args.wb}, strategy={args.strategy}, coarse_step={args.coarse_step}")

    use_blue_filter = not args.no_blue_filter
    print(f"[*] Collecting pixels... (blue_filter={'ON' if use_blue_filter else 'OFF'})")
    pos, neg = collect_pixels_bbox(
        root, samples, wb=args.wb,
        max_pos_per_image=args.max_pos_per_image,
        max_neg_per_image=args.max_neg_per_image,
        seed=args.seed,
        blue_filter=use_blue_filter,
    )

    cap = args.max_total_samples
    rng = np.random.default_rng(args.seed)
    if cap > 0:
        if pos.shape[0] > cap:
            pos = pos[rng.choice(pos.shape[0], cap, replace=False)]
        if neg.shape[0] > cap:
            neg = neg[rng.choice(neg.shape[0], cap, replace=False)]
    print(f"    N_pos={pos.shape[0]:,}  N_neg={neg.shape[0]:,}")

    print(f"\n[*] Positive stats (Y, Cb, Cr):")
    for ch, name in enumerate(["Y", "Cb", "Cr"]):
        vals = pos[:, ch]
        print(f"    {name}: min={vals.min()} P5={np.percentile(vals,5):.0f} "
              f"median={np.median(vals):.0f} P95={np.percentile(vals,95):.0f} max={vals.max()}")
    print(f"[*] Negative stats (Y, Cb, Cr):")
    for ch, name in enumerate(["Y", "Cb", "Cr"]):
        vals = neg[:, ch]
        print(f"    {name}: min={vals.min()} P5={np.percentile(vals,5):.0f} "
              f"median={np.median(vals):.0f} P95={np.percentile(vals,95):.0f} max={vals.max()}")

    bounds = {
        "y_min": args.y_min, "y_max": args.y_max,
        "cb_min": args.cb_min, "cb_max": args.cb_max,
        "cr_min": args.cr_min, "cr_max": args.cr_max,
    }
    has_bounds = any(v != 255 for k, v in bounds.items() if "max" in k) or \
                 any(v != 0 for k, v in bounds.items() if "min" in k)
    if has_bounds:
        print(f"[*] Search bounds: Y=[{bounds['y_min']},{bounds['y_max']}] "
              f"Cb=[{bounds['cb_min']},{bounds['cb_max']}] Cr=[{bounds['cr_min']},{bounds['cr_max']}]")

    if args.strategy == "full6d":
        print(f"\n[*] Full 6D grid search (step={args.coarse_step})...")
        lo, hi, f1_coarse = grid_search_6d(
            pos, neg, step=args.coarse_step)
        print(f"[*] Coarse result: Y=[{lo[0]},{hi[0]}] Cb=[{lo[1]},{hi[1]}] Cr=[{lo[2]},{hi[2]}]")
        print(f"[*] Fine-tuning ±{args.refine_radius}...")
        lo, hi, f1_final = refine_around(pos, neg, lo, hi, radius=args.refine_radius, bounds=bounds)
    else:
        print(f"\n[*] Sequential search (Cb/Cr → Y → joint refine)...")
        lo, hi, f1_final = search_sequential_2stage(
            pos, neg,
            step=args.coarse_step,
            refine_radius=args.refine_radius,
            bounds=bounds,
        )

    # ── optional linear constraints ──
    lines: list[dict] = []
    if args.linear > 0:
        lines, f1_with_lines = search_linear_constraints(pos, neg, lo, hi, max_lines=args.linear)

        if lines:
            print("[*] Re-searching box with linear constraints active (wider box + line may beat tight box alone)...")
            best_combo_f1 = f1_with_lines
            best_combo_lo = lo.copy()
            best_combo_hi = hi.copy()
            best_combo_lines = [ln.copy() for ln in lines]

            bnd_lo = np.array([bounds.get("y_min", 0), bounds.get("cb_min", 0), bounds.get("cr_min", 0)])
            bnd_hi = np.array([bounds.get("y_max", 255), bounds.get("cb_max", 255), bounds.get("cr_max", 255)])
            for expand in [3, 5, 8, 12]:
                trial_lo = np.clip(lo - expand, bnd_lo, bnd_hi).astype(np.int32)
                trial_hi = np.clip(hi + expand, bnd_lo, bnd_hi).astype(np.int32)
                trial_lines, trial_f1 = search_linear_constraints(
                    pos, neg, trial_lo, trial_hi, max_lines=args.linear)
                print(f"    expand=±{expand}: F1={trial_f1:.4f} (box {list(trial_lo)}-{list(trial_hi)}, {len(trial_lines)} lines)")
                if trial_f1 > best_combo_f1:
                    best_combo_f1 = trial_f1
                    best_combo_lo = trial_lo.copy()
                    best_combo_hi = trial_hi.copy()
                    best_combo_lines = [ln.copy() for ln in trial_lines]

            if best_combo_f1 > f1_with_lines:
                lo, hi = best_combo_lo, best_combo_hi
                lines = best_combo_lines
                print(f"    => Wider box + linear is better: F1={best_combo_f1:.4f}")
            else:
                print(f"    => Original tight box + linear is best: F1={f1_with_lines:.4f}")

    metrics = compute_metrics(pos, neg, lo, hi, lines if lines else None)
    print(f"\n{'='*60}")
    print(f"[+] FINAL BOX:  Y=[{lo[0]}, {hi[0]}]  Cb=[{lo[1]}, {hi[1]}]  Cr=[{lo[2]}, {hi[2]}]")
    if lines:
        for i, ln in enumerate(lines):
            print(f"    Line {i+1}: {ln['a']}*Y + {ln['b']}*Cb + {ln['c']}*Cr {ln['op']} {ln['t']}")
    print(f"    F1        = {metrics['f1']:.4f}")
    print(f"    Precision = {metrics['precision']:.4f}  (TP={metrics['tp']:,} FP={metrics['fp']:,})")
    print(f"    Recall    = {metrics['recall']:.4f}  (TP={metrics['tp']:,} FN={metrics['fn']:,})")
    print(f"    neg_frac  = {metrics['neg_fraction']:.6f}")
    print(f"{'='*60}")

    out = {
        "wb": args.wb,
        "manifest": str(args.manifest.resolve()),
        "strategy": args.strategy,
        "blue_filter": use_blue_filter,
        "coarse_step": args.coarse_step,
        "refine_radius": args.refine_radius,
        "n_pos": int(pos.shape[0]),
        "n_neg": int(neg.shape[0]),
        "metrics": {
            "f1": metrics["f1"],
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "neg_fraction": metrics["neg_fraction"],
        },
        "verilog": {
            "Y_MIN": int(lo[0]), "Y_MAX": int(hi[0]),
            "CB_MIN": int(lo[1]), "CB_MAX": int(hi[1]),
            "CR_MIN": int(lo[2]), "CR_MAX": int(hi[2]),
        },
    }
    if lines:
        out["linear_constraints"] = lines
        out["verilog"]["linear"] = []
        for ln in lines:
            out["verilog"]["linear"].append({
                "a_Y": ln["a"], "b_Cb": ln["b"], "c_Cr": ln["c"],
                "threshold": ln["t"], "op": ln["op"],
            })
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n[+] JSON: {args.output_json.resolve()}")

    print("\n--- paste into image_process_wrapper.v ---\n")
    print(verilog_snippet(lo, hi))
    if lines:
        print()
        print(verilog_linear_snippet(lines))
    print()

    if args.plot:
        plot_dir = args.output_json.parent
        plot_distributions(pos, neg, lo, hi, plot_dir / "diagnostic_scatter.png",
                           lines=lines if lines else None)
        plot_per_image_stats(root, samples, lo, hi, args.wb, plot_dir / "diagnostic_per_image.png",
                             lines=lines if lines else None)
        if use_blue_filter:
            plot_blue_filter_preview(root, samples, plot_dir / "diagnostic_blue_filter.png")


if __name__ == "__main__":
    main()
