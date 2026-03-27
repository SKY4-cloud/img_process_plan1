#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plate_ycbcr_stats.py — Y/Cb/Cr statistics for blue-plate FPGA threshold tuning.

Default --mode rtl matches image_process_wrapper RGB565 truncation + RGB2YCbCr_1 integer math.

Usage:
  python plate_ycbcr_stats.py -i test1.bmp --mode rtl -o ./stats_out
  python plate_ycbcr_stats.py -i test1.bmp --mode rtl --roi 100,80,120,40 -o ./stats_out
  python plate_ycbcr_stats.py -i ./frames/ --glob "*.bmp" --mode rtl
"""

from __future__ import annotations

import argparse
import glob as glob_mod
import sys
from pathlib import Path

import cv2
import numpy as np


def bgr_to_rgb565_style(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Match Verilog: r_in[7:3], g_in[7:2], b_in[7:3]"""
    b, g, r = cv2.split(bgr)
    r5 = (r.astype(np.uint16) >> 3) & 0x1F
    g6 = (g.astype(np.uint16) >> 2) & 0x3F
    b5 = (b.astype(np.uint16) >> 3) & 0x1F
    rgb888_r = (r5 << 3) | (r5 >> 2)
    rgb888_g = (g6 << 2) | (g6 >> 4)
    rgb888_b = (b5 << 3) | (b5 >> 2)
    return rgb888_r.astype(np.uint8), rgb888_g.astype(np.uint8), rgb888_b.astype(np.uint8)


def ycbcr_from_rgb888_rtl(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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


def ycbcr_opencv(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    y, cr, cb = cv2.split(ycc)
    return y, cb, cr


def apply_roi(img: np.ndarray, roi: tuple[int, int, int, int] | None) -> np.ndarray:
    if roi is None:
        return img
    x, y, w, h = roi
    H, W = img.shape[:2]
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(1, min(w, W - x))
    h = max(1, min(h, H - y))
    return img[y : y + h, x : x + w]


def parse_roi(s: str | None) -> tuple[int, int, int, int] | None:
    if not s or not str(s).strip():
        return None
    parts = [int(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("ROI must be x,y,w,h")
    return tuple(parts)  # type: ignore[return-value]


def collect_paths(input_path: str, pattern: str) -> list[Path]:
    p = Path(input_path)
    if p.is_file():
        return [p]
    if p.is_dir():
        paths = sorted(Path(x) for x in glob_mod.glob(str(p / pattern)))
        return [x for x in paths if x.is_file()]
    raise FileNotFoundError(input_path)


def stats_one(name: str, y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> None:
    flat = {"Y": y.ravel(), "Cb": cb.ravel(), "Cr": cr.ravel()}
    print(f"\n=== {name}  (pixels={y.size}) ===")
    for ch, arr in flat.items():
        mean = float(arr.mean())
        p5, p10, p50, p90, p95 = np.percentile(arr, [5, 10, 50, 90, 95])
        mn, mx = int(arr.min()), int(arr.max())
        print(
            f"  {ch}: min={mn} max={mx} mean={mean:.2f} | "
            f"P5={p5:.1f} P10={p10:.1f} P50={p50:.1f} P90={p90:.1f} P95={p95:.1f}"
        )
    cb_p10 = float(np.percentile(flat["Cb"], 10))
    cr_lo = float(np.percentile(flat["Cr"], 10))
    cr_hi = float(np.percentile(flat["Cr"], 90))
    print(
        f"  [heuristic] Cb floor try > {cb_p10:.0f}; Cr band ~[{cr_lo:.0f}, {cr_hi:.0f}] — refine on plate ROI"
    )


def try_plot_hist(
    out_dir: Path,
    tag: str,
    y: np.ndarray,
    cb: np.ndarray,
    cr: np.ndarray,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("[!] matplotlib not installed; skip plots. pip install matplotlib")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(12, 3))
    for ax, arr, title in zip(axes, (y, cb, cr), ("Y", "Cb", "Cr"), strict=True):
        ax.hist(arr.ravel(), bins=256, range=(0, 256), color="steelblue", alpha=0.8)
        ax.set_title(f"{tag} {title}")
        ax.set_xlim(0, 255)
    fig.tight_layout()
    png = out_dir / f"{tag}_ycbcr_hist.png"
    fig.savefig(png, dpi=150)
    plt.close(fig)
    print(f"[+] Histogram saved: {png}")


def process_image(
    bgr: np.ndarray,
    mode: str,
    roi: tuple[int, int, int, int] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bgr = apply_roi(bgr, roi)
    if mode == "rtl":
        r, g, b = bgr_to_rgb565_style(bgr)
        return ycbcr_from_rgb888_rtl(r, g, b)
    if mode == "opencv":
        return ycbcr_opencv(bgr)
    raise ValueError(mode)


def main() -> None:
    ap = argparse.ArgumentParser(description="Y/Cb/Cr histograms for plate threshold tuning")
    ap.add_argument("-i", "--input", required=True, help="Image file or directory")
    ap.add_argument("--glob", default="*", help="Glob when input is a directory")
    ap.add_argument("--mode", choices=("rtl", "opencv"), default="rtl", help="rtl=match FPGA (default)")
    ap.add_argument("--roi", default="", help="Optional ROI: x,y,w,h")
    ap.add_argument("-o", "--output", default="", help="Output directory for PNG histograms")
    args = ap.parse_args()

    try:
        roi = parse_roi(args.roi.strip() if args.roi else None)
    except ValueError as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)

    paths = collect_paths(args.input, args.glob)
    if not paths:
        print("[!] No images found", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.output) if args.output else None

    for path in paths:
        bgr = cv2.imread(str(path))
        if bgr is None:
            print(f"[!] Cannot read: {path}", file=sys.stderr)
            continue
        y, cb, cr = process_image(bgr, args.mode, roi)
        tag = path.stem + ("_roi" if roi else "")
        stats_one(f"{path.name} [{args.mode}]", y, cb, cr)
        if out_dir is not None:
            try_plot_hist(out_dir, tag, y, cb, cr)

    print("\nDone. Use --mode rtl stats for Verilog parameters.")


if __name__ == "__main__":
    main()
