#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 FPGA 一致链路（RGB565 → RGB888 → 可选 WB → RTL YCbCr）下，
从正/负样本像素学习三维轴对齐盒子: Y∈[Y_MIN,Y_MAX], Cb∈[...], Cr∈[...]（联合 AND 约束）。

Manifest 两种形式:
  - folder: positive_files + negative_files（独立图列表）
  - full_image_bbox: 整图路径 + bbox；整图 WB 后框内=正、框外=负（子采样）

方法:
  1) 用正样本分位数得到初始盒（覆盖大部分车牌像素）
  2) 若负样本落入盒内比例过高，则在保持正样本覆盖率 ≥ 阈值的前提下，贪心收紧六条边界

输出: JSON + 控制台打印 Verilog parameter 片段（供 image_process_wrapper 替换）。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

from fpga_color_chain import bgr_through_fpga_chain, bgr_to_ycbcr_planes_rtl


def is_full_image_bbox_manifest(m: dict) -> bool:
    if m.get("format") == "full_image_bbox":
        return True
    samples = m.get("samples")
    if isinstance(samples, list) and samples and isinstance(samples[0], dict) and "bbox" in samples[0]:
        return True
    return False


def load_manifest_bbox_dict(m: dict) -> tuple[Path, list[dict]]:
    root = Path(m["dataset_root"]).resolve()
    samples = m["samples"]
    if not isinstance(samples, list) or not samples:
        raise ValueError("full_image_bbox manifest needs non-empty samples[]")
    return root, samples


def load_manifest_folder_dict(m: dict) -> tuple[Path, list[Path], list[Path]]:
    root = Path(m["dataset_root"]).resolve()
    pos = [root / x for x in m["positive_files"]]
    neg = [root / x for x in m["negative_files"]]
    return root, pos, neg


def collect_pixels_bbox_mode(
    root: Path,
    samples: list[dict],
    *,
    wb: str,
    max_pos_per_image: int,
    max_neg_per_image: int,
    max_images: int | None,
    seed: int,
    neg_mode: str,
    neg_cb_min: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    每张图：整图 RGB565→RGB888→WB→RTL YCbCr；bbox 内采正样本，bbox 外采负样本。
    """
    rng = np.random.default_rng(seed)
    pos_chunks: list[np.ndarray] = []
    neg_chunks: list[np.ndarray] = []
    use = samples[:]
    if max_images is not None and max_images > 0:
        perm = rng.permutation(len(use))[:max_images]
        use = [use[i] for i in perm]

    for item in use:
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

        H, W = bgr.shape[:2]
        bx, by, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        x0 = max(0, min(bx, W - 1))
        y0 = max(0, min(by, H - 1))
        x1 = min(W, bx + max(0, bw))
        y1 = min(H, by + max(0, bh))
        if x1 <= x0 or y1 <= y0:
            print(f"[!] skip empty bbox after clip: {path} bbox={bbox}", file=sys.stderr)
            continue

        y_plane, cb_plane, cr_plane = bgr_to_ycbcr_planes_rtl(bgr, wb=wb)
        inside = np.zeros((H, W), dtype=bool)
        inside[y0:y1, x0:x1] = True

        flat_y = y_plane.ravel()
        flat_cb = cb_plane.ravel()
        flat_cr = cr_plane.ravel()
        flat_in = inside.ravel()

        pos_idx = np.flatnonzero(flat_in)
        neg_idx = np.flatnonzero(~flat_in)
        if pos_idx.size == 0:
            print(f"[!] skip no positive pixels: {path}", file=sys.stderr)
            continue

        if pos_idx.size > max_pos_per_image:
            sel = rng.choice(pos_idx.size, size=max_pos_per_image, replace=False)
            pos_idx = pos_idx[sel]

        pos_pix = np.stack([flat_y[pos_idx], flat_cb[pos_idx], flat_cr[pos_idx]], axis=1).astype(np.uint8)
        pos_chunks.append(pos_pix)

        if neg_mode == "blue_biased":
            blue_out = neg_idx[flat_cb[neg_idx] >= neg_cb_min]
            if blue_out.size >= max(1, max_neg_per_image // 4):
                pool = blue_out
            else:
                pool = neg_idx
        else:
            pool = neg_idx

        if pool.size == 0:
            continue
        n_take = min(max_neg_per_image, pool.size)
        sel = rng.choice(pool.size, size=n_take, replace=False)
        neg_sel = pool[sel]
        neg_pix = np.stack([flat_y[neg_sel], flat_cb[neg_sel], flat_cr[neg_sel]], axis=1).astype(np.uint8)
        neg_chunks.append(neg_pix)

    if not pos_chunks:
        raise RuntimeError("No positive pixels collected (check bbox / paths)")
    if not neg_chunks:
        raise RuntimeError("No negative pixels collected")

    return np.vstack(pos_chunks), np.vstack(neg_chunks)


def collect_pixels_from_images(
    paths: list[Path],
    *,
    wb: str,
    max_pixels_per_image: int,
    max_images: int | None,
    seed: int,
) -> np.ndarray:
    rng = random.Random(seed)
    rows: list[np.ndarray] = []
    use_paths = paths[:]
    if max_images is not None:
        rng.shuffle(use_paths)
        use_paths = use_paths[:max_images]
    for p in use_paths:
        if not p.is_file():
            print(f"[!] skip missing: {p}", file=sys.stderr)
            continue
        bgr = cv2.imread(str(p))
        if bgr is None:
            print(f"[!] skip unreadable: {p}", file=sys.stderr)
            continue
        y, cb, cr = bgr_through_fpga_chain(bgr, wb=wb)
        pix = np.stack([y.ravel(), cb.ravel(), cr.ravel()], axis=1).astype(np.uint8)
        n = pix.shape[0]
        if n > max_pixels_per_image:
            idx = rng.sample(range(n), max_pixels_per_image)
            pix = pix[np.array(idx, dtype=np.int64)]
        rows.append(pix)
    if not rows:
        raise RuntimeError("No pixels collected; check dataset paths and cv2.imread")
    return np.vstack(rows)


def box_from_percentiles(
    pos: np.ndarray,
    q_lo: float,
    q_hi: float,
) -> tuple[int, int, int, int, int, int]:
    y_lo, y_hi = np.percentile(pos[:, 0], [q_lo, q_hi])
    cb_lo, cb_hi = np.percentile(pos[:, 1], [q_lo, q_hi])
    cr_lo, cr_hi = np.percentile(pos[:, 2], [q_lo, q_hi])
    return (
        int(np.floor(y_lo)),
        int(np.ceil(y_hi)),
        int(np.floor(cb_lo)),
        int(np.ceil(cb_hi)),
        int(np.floor(cr_lo)),
        int(np.ceil(cr_hi)),
    )


def clip_box(
    y_lo: int,
    y_hi: int,
    cb_lo: int,
    cb_hi: int,
    cr_lo: int,
    cr_hi: int,
) -> tuple[int, int, int, int, int, int]:
    def c(x: int) -> int:
        return int(np.clip(x, 0, 255))

    y_lo, y_hi = c(y_lo), c(y_hi)
    cb_lo, cb_hi = c(cb_lo), c(cb_hi)
    cr_lo, cr_hi = c(cr_lo), c(cr_hi)
    if y_lo > y_hi:
        y_lo, y_hi = y_hi, y_lo
    if cb_lo > cb_hi:
        cb_lo, cb_hi = cb_hi, cb_lo
    if cr_lo > cr_hi:
        cr_lo, cr_hi = cr_hi, cr_lo
    return y_lo, y_hi, cb_lo, cb_hi, cr_lo, cr_hi


def in_box(p: np.ndarray, b: tuple[int, int, int, int, int, int]) -> np.ndarray:
    y_lo, y_hi, cb_lo, cb_hi, cr_lo, cr_hi = b
    return (
        (p[:, 0] >= y_lo)
        & (p[:, 0] <= y_hi)
        & (p[:, 1] >= cb_lo)
        & (p[:, 1] <= cb_hi)
        & (p[:, 2] >= cr_lo)
        & (p[:, 2] <= cr_hi)
    )


def pos_coverage(pos: np.ndarray, b: tuple[int, int, int, int, int, int]) -> float:
    return float(np.mean(in_box(pos, b)))


def neg_fraction(neg: np.ndarray, b: tuple[int, int, int, int, int, int]) -> float:
    return float(np.mean(in_box(neg, b)))


def refine_box_greedy(
    pos: np.ndarray,
    neg: np.ndarray,
    initial: tuple[int, int, int, int, int, int],
    *,
    min_pos_coverage: float,
    max_neg_fraction: float,
    max_iterations: int,
) -> tuple[tuple[int, int, int, int, int, int], dict]:
    b = clip_box(*initial)
    hist: dict[str, float | int] = {
        "iterations": 0,
        "initial_neg_frac": neg_fraction(neg, b),
        "initial_pos_cov": pos_coverage(pos, b),
    }
    for it in range(max_iterations):
        nf = neg_fraction(neg, b)
        pc = pos_coverage(pos, b)
        if nf <= max_neg_fraction:
            hist["final_neg_frac"] = nf
            hist["final_pos_cov"] = pc
            hist["iterations"] = it
            return b, hist
        if pc < min_pos_coverage:
            break
        y_lo, y_hi, cb_lo, cb_hi, cr_lo, cr_hi = b
        candidates: list[tuple[tuple[int, int, int, int, int, int], float, float]] = []
        # tighten: raise mins / lower maxes by 1
        for name, nb in [
            ("y_lo+1", (y_lo + 1, y_hi, cb_lo, cb_hi, cr_lo, cr_hi)),
            ("y_hi-1", (y_lo, y_hi - 1, cb_lo, cb_hi, cr_lo, cr_hi)),
            ("cb_lo+1", (y_lo, y_hi, cb_lo + 1, cb_hi, cr_lo, cr_hi)),
            ("cb_hi-1", (y_lo, y_hi, cb_lo, cb_hi - 1, cr_lo, cr_hi)),
            ("cr_lo+1", (y_lo, y_hi, cb_lo, cb_hi, cr_lo + 1, cr_hi)),
            ("cr_hi-1", (y_lo, y_hi, cb_lo, cb_hi, cr_lo, cr_hi - 1)),
        ]:
            nb = clip_box(*nb)
            if nb == b:
                continue
            pc2 = pos_coverage(pos, nb)
            if pc2 < min_pos_coverage:
                continue
            nf2 = neg_fraction(neg, nb)
            candidates.append((nb, nf2, pc2))
        if not candidates:
            break
        # pick largest reduction in neg fraction
        candidates.sort(key=lambda t: (t[1], -t[2]))
        b = candidates[0][0]
    hist["final_neg_frac"] = neg_fraction(neg, b)
    hist["final_pos_cov"] = pos_coverage(pos, b)
    hist["iterations"] = max_iterations
    return b, hist


def verilog_snippet(
    y_lo: int,
    y_hi: int,
    cb_lo: int,
    cb_hi: int,
    cr_lo: int,
    cr_hi: int,
) -> str:
    return f"""    parameter CB_MIN     = 8'd{cb_lo},
    parameter CB_MAX     = 8'd{cb_hi},
    parameter CR_MIN     = 8'd{cr_lo},
    parameter CR_MAX     = 8'd{cr_hi},
    parameter Y_MIN      = 8'd{y_lo},
    parameter Y_MAX      = 8'd{y_hi},"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Train Y/Cb/Cr axis-aligned box (FPGA-consistent chain)")
    ap.add_argument(
        "-m",
        "--manifest",
        type=Path,
        required=True,
        help="YAML: folder mode (positive_files/negative_files) or full_image_bbox (samples+bbox)",
    )
    ap.add_argument("--wb", choices=("none", "gray_world"), default="none", help="WB before YCbCr (scheme C)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-pixels-per-image", type=int, default=8000, help="folder mode: max pixels per image per class")
    ap.add_argument("--max-pos-per-image", type=int, default=6000, help="bbox mode: max positive pixels per frame")
    ap.add_argument("--max-neg-per-image", type=int, default=20000, help="bbox mode: max negative pixels per frame")
    ap.add_argument(
        "--neg-mode",
        choices=("uniform", "blue_biased"),
        default="uniform",
        help="bbox mode: negative sampling outside bbox",
    )
    ap.add_argument(
        "--neg-cb-min",
        type=int,
        default=135,
        help="blue_biased: prefer bbox-outside pixels with Cb>=this (fallback to uniform if too few)",
    )
    ap.add_argument("--max-images", type=int, default=None, help="Cap images (folder: per class; bbox: sample count)")
    ap.add_argument("--q-lo", type=float, default=2.0, help="Low percentile on positive pixels per axis")
    ap.add_argument("--q-hi", type=float, default=98.0, help="High percentile on positive pixels per axis")
    ap.add_argument("--min-pos-coverage", type=float, default=0.88, help="Min fraction of pos samples inside box while refining")
    ap.add_argument("--max-neg-fraction", type=float, default=0.002, help="Target max fraction of neg samples inside box")
    ap.add_argument("--refine-iters", type=int, default=2000)
    ap.add_argument(
        "--max-total-samples",
        type=int,
        default=120000,
        help="Subsample cap per class before refine; use 0 for no cap (may be slow)",
    )
    ap.add_argument("-o", "--output-json", type=Path, default=Path("trained_color_box.json"))
    args = ap.parse_args()

    with open(args.manifest.resolve(), encoding="utf-8") as f:
        manifest_raw = yaml.safe_load(f)

    if is_full_image_bbox_manifest(manifest_raw):
        root, samples = load_manifest_bbox_dict(manifest_raw)
        print("[*] manifest mode: full_image_bbox (WB on full frame; pos inside bbox, neg outside)")
        print("[*] collecting pixels...")
        pos, neg = collect_pixels_bbox_mode(
            root,
            samples,
            wb=args.wb,
            max_pos_per_image=args.max_pos_per_image,
            max_neg_per_image=args.max_neg_per_image,
            max_images=args.max_images,
            seed=args.seed,
            neg_mode=args.neg_mode,
            neg_cb_min=args.neg_cb_min,
        )
        print(f"    N_pos = {pos.shape[0]}  N_neg = {neg.shape[0]}")
    else:
        _, pos_paths, neg_paths = load_manifest_folder_dict(manifest_raw)
        print("[*] manifest mode: folder (separate positive/negative image lists)")
        print("[*] collecting positive pixels...")
        pos = collect_pixels_from_images(
            pos_paths,
            wb=args.wb,
            max_pixels_per_image=args.max_pixels_per_image,
            max_images=args.max_images,
            seed=args.seed,
        )
        print(f"    N_pos = {pos.shape[0]}")
        print("[*] collecting negative pixels...")
        neg = collect_pixels_from_images(
            neg_paths,
            wb=args.wb,
            max_pixels_per_image=args.max_pixels_per_image,
            max_images=args.max_images,
            seed=args.seed + 1,
        )
        print(f"    N_neg = {neg.shape[0]}")

    cap = args.max_total_samples
    if cap is not None and cap > 0:
        rng = np.random.default_rng(args.seed)
        if pos.shape[0] > cap:
            idx = rng.choice(pos.shape[0], size=cap, replace=False)
            pos = pos[idx]
        if neg.shape[0] > cap:
            idx = rng.choice(neg.shape[0], size=cap, replace=False)
            neg = neg[idx]
        print(f"[*] after max_total_samples cap ({cap}): N_pos={pos.shape[0]} N_neg={neg.shape[0]}")

    init = box_from_percentiles(pos, args.q_lo, args.q_hi)
    init = clip_box(*init)
    print("[*] initial box (pos percentiles):", init)
    print(f"    pos_cov={pos_coverage(pos, init):.4f} neg_frac={neg_fraction(neg, init):.4f}")

    final, rh = refine_box_greedy(
        pos,
        neg,
        init,
        min_pos_coverage=args.min_pos_coverage,
        max_neg_fraction=args.max_neg_fraction,
        max_iterations=args.refine_iters,
    )
    y_lo, y_hi, cb_lo, cb_hi, cr_lo, cr_hi = final
    print("[*] refined box:", final)
    print(f"    pos_cov={rh.get('final_pos_cov'):.4f} neg_frac={rh.get('final_neg_frac'):.4f} iters={rh.get('iterations')}")

    mode_tag = "full_image_bbox" if is_full_image_bbox_manifest(manifest_raw) else "folder"
    out = {
        "wb": args.wb,
        "manifest": str(args.manifest.resolve()),
        "manifest_mode": mode_tag,
        "q_lo": args.q_lo,
        "q_hi": args.q_hi,
        "min_pos_coverage": args.min_pos_coverage,
        "max_neg_fraction": args.max_neg_fraction,
        "refine_history": rh,
        "verilog": {
            "Y_MIN": y_lo,
            "Y_MAX": y_hi,
            "CB_MIN": cb_lo,
            "CB_MAX": cb_hi,
            "CR_MIN": cr_lo,
            "CR_MAX": cr_hi,
        },
    }
    if mode_tag == "full_image_bbox":
        out["bbox_train_options"] = {
            "max_pos_per_image": args.max_pos_per_image,
            "max_neg_per_image": args.max_neg_per_image,
            "neg_mode": args.neg_mode,
            "neg_cb_min": args.neg_cb_min,
        }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[+] JSON: {args.output_json.resolve()}")

    print("\n--- paste into image_process_wrapper.v (replace CB/CR/Y parameters) ---\n")
    print(verilog_snippet(y_lo, y_hi, cb_lo, cb_hi, cr_lo, cr_hi))
    print()


if __name__ == "__main__":
    main()
