"""
统计二值（或近似二值）图像中：指定列 x 上的白色像素个数，或指定行 y 上的白色像素个数。

白色判定默认：灰度值 >= threshold（适合 0/255 或抗锯齿后的图）。
用法:
  python binary_row_col_count.py -i ../result_post7.jpg --x 200
  python binary_row_col_count.py -i ../result_post7.jpg --y 370
  python binary_row_col_count.py -i ../result_post7.jpg --x 200 --y 370
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np


def load_gray(path: str) -> np.ndarray:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    bgr = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if bgr is None:
        raise ValueError(f"无法读取图像: {path}")
    if bgr.ndim == 2:
        return bgr
    if bgr.ndim == 3 and bgr.shape[2] >= 3:
        return cv2.cvtColor(bgr[:, :, :3], cv2.COLOR_BGR2GRAY)
    raise ValueError(f"不支持的通道数: shape={bgr.shape}")


def white_mask(gray: np.ndarray, threshold: int, strict255: bool) -> np.ndarray:
    if strict255:
        return gray == 255
    return gray >= threshold


def count_column(mask: np.ndarray, x: int) -> int:
    h, w = mask.shape[:2]
    if x < 0 or x >= w:
        raise IndexError(f"x={x} 超出宽度 [0, {w - 1}]")
    return int(np.count_nonzero(mask[:, x]))


def count_row(mask: np.ndarray, y: int) -> int:
    h, w = mask.shape[:2]
    if y < 0 or y >= h:
        raise IndexError(f"y={y} 超出高度 [0, {h - 1}]")
    return int(np.count_nonzero(mask[y, :]))


def main() -> int:
    p = argparse.ArgumentParser(description="统计二值图指定列/行的白色像素个数")
    p.add_argument("-i", "--input", required=True, help="输入图像路径（bmp/png/jpg 等）")
    p.add_argument("--x", type=int, default=None, help="列坐标（0 起，从左到右）")
    p.add_argument("--y", type=int, default=None, help="行坐标（0 起，从上到下）")
    p.add_argument(
        "--threshold",
        type=int,
        default=128,
        help="灰度 >= 该值视为白（默认 128；与 --strict255 互斥）",
    )
    p.add_argument(
        "--strict255",
        action="store_true",
        help="仅将灰度==255 视为白",
    )
    args = p.parse_args()

    if args.x is None and args.y is None:
        p.error("请至少指定 --x 或 --y")

    try:
        gray = load_gray(args.input)
    except (OSError, ValueError, FileNotFoundError) as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1

    h, w = gray.shape[:2]
    mask = white_mask(gray, args.threshold, args.strict255)
    mode = "strict255" if args.strict255 else f">= {args.threshold}"

    print(f"[*] {args.input}")
    print(f"[*] 尺寸: 宽={w} 高={h}；白色判定: {mode}")
    print(f"[*] 全图白像素总数: {int(np.count_nonzero(mask))}")

    if args.x is not None:
        try:
            c = count_column(mask, args.x)
        except IndexError as e:
            print(f"[!] {e}", file=sys.stderr)
            return 1
        print(f"[*] 列 x={args.x}: 白色像素个数 = {c}")

    if args.y is not None:
        try:
            r = count_row(mask, args.y)
        except IndexError as e:
            print(f"[!] {e}", file=sys.stderr)
            return 1
        print(f"[*] 行 y={args.y}: 白色像素个数 = {r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
