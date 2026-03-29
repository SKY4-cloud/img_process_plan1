#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
与 FPGA 输入链路一致的彩色处理（用于离线标定，须与 RTL 对齐）。

顺序（方案 C）:
  BGR 读入 → RGB565 截断 → 展开为 RGB888（与 Verilog 相同）→ 可选灰世界 WB → RGB2YCbCr_1 整数公式

注意: WB 在 RGB888 上完成后再转 YCbCr；不得先用 OpenCV 默认 YCbCr 再调阈值。
"""

from __future__ import annotations

import numpy as np


def bgr_to_rgb565_style(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Match image_process_wrapper + RGB2YCbCr_1: r_in[7:3], g_in[7:2], b_in[7:3]"""
    b, g, r = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]
    r5 = (r.astype(np.uint16) >> 3) & 0x1F
    g6 = (g.astype(np.uint16) >> 2) & 0x3F
    b5 = (b.astype(np.uint16) >> 3) & 0x1F
    rgb888_r = ((r5 << 3) | (r5 >> 2)).astype(np.uint8)
    rgb888_g = ((g6 << 2) | (g6 >> 4)).astype(np.uint8)
    rgb888_b = ((b5 << 3) | (b5 >> 2)).astype(np.uint8)
    return rgb888_r, rgb888_g, rgb888_b


def ycbcr_from_rgb888_rtl(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """与 RGB2YCbCr_1.v 相同的定点公式（>>8，Cb/Cr +32768）。"""
    rr = r.astype(np.int32)
    gg = g.astype(np.int32)
    bb = b.astype(np.int32)
    y0 = 77 * rr + 150 * gg + 29 * bb
    cb0 = -43 * rr - 85 * gg + 128 * bb + 32768
    cr0 = 128 * rr - 107 * gg - 21 * bb + 32768
    y = (y0 >> 8).astype(np.uint8)
    cb = (cb0 >> 8).astype(np.uint8)
    cr = (cr0 >> 8).astype(np.uint8)
    return y, cb, cr


def gray_world_wb(
    r: np.ndarray,
    g: np.ndarray,
    b: np.ndarray,
    eps: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    灰世界: 使 R/G/B 均值趋于一致。在 uint8 RGB888 上运算，输出饱和到 [0,255]。
    与常见 ISP 一致；若需与将来 Verilog 完全一致，应对增益做 Q 格式与限幅对齐。
    """
    rf = r.astype(np.float64)
    gf = g.astype(np.float64)
    bf = b.astype(np.float64)
    mr = float(rf.mean())
    mg = float(gf.mean())
    mb = float(bf.mean())
    m = (mr + mg + mb) / 3.0
    kr = m / (mr + eps)
    kg = m / (mg + eps)
    kb = m / (mb + eps)
    r2 = np.clip(np.round(rf * kr), 0, 255).astype(np.uint8)
    g2 = np.clip(np.round(gf * kg), 0, 255).astype(np.uint8)
    b2 = np.clip(np.round(bf * kb), 0, 255).astype(np.uint8)
    return r2, g2, b2


def bgr_through_fpga_chain(
    bgr: np.ndarray,
    *,
    wb: str = "none",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    wb:
      none — 仅 RGB565→RGB888→YCbCr
      gray_world — 在 RGB888 上做灰世界后再 YCbCr
    """
    r, g, b = bgr_to_rgb565_style(bgr)
    if wb == "gray_world":
        r, g, b = gray_world_wb(r, g, b)
    elif wb != "none":
        raise ValueError(f"unknown wb mode: {wb}")
    return ycbcr_from_rgb888_rtl(r, g, b)


def bgr_to_ycbcr_planes_rtl(
    bgr: np.ndarray,
    *,
    wb: str = "none",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """整图 Y/Cb/Cr 平面（整图 WB 后按 bbox 采样时使用）。"""
    return bgr_through_fpga_chain(bgr, wb=wb)


def stack_ycbcr(y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> np.ndarray:
    """(H,W,3) uint8, order Y, Cb, Cr"""
    return np.stack([y, cb, cr], axis=-1)
