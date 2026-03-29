"""
从仿真 dump 的 image_out.txt（每行一个十六进制字节，光栅行优先：先整行 x=0..W-1，再下一行）
统计指定行 y 或列 x 上「白」像素个数，与 RTL 中 bin_data==8'hFF 对齐。

用法:
  python image_out_row_col_count.py -i ../image_out.txt --y 370
  python image_out_row_col_count.py -i ../image_out.txt --x 256
  python image_out_row_col_count.py -i ../image_out.txt --x 200 --y 510 --width 720 --height 1160
"""
from __future__ import annotations

import argparse
import os
import sys


def load_flat_hex(path: str) -> list[int]:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    out: list[int] = []
    for i, s in enumerate(lines):
        try:
            v = int(s, 16)
        except ValueError as e:
            raise ValueError(f"第 {i + 1} 行非十六进制: {s!r}") from e
        if v < 0 or v > 255:
            raise ValueError(f"第 {i + 1} 行数值越界: {v}")
        out.append(v)
    return out


def is_white(v: int, threshold: int | None) -> bool:
    if threshold is None:
        return v == 255
    return v >= threshold


def main() -> int:
    p = argparse.ArgumentParser(
        description="统计 image_out.txt 中指定行/列的白像素个数（与仿真二值一致建议默认仅 255）"
    )
    p.add_argument("-i", "--input", default="image_out.txt", help="hex 文本路径")
    p.add_argument("--x", type=int, default=None, help="列坐标 0..W-1")
    p.add_argument("--y", type=int, default=None, help="行坐标 0..H-1")
    p.add_argument("--width", type=int, default=720, help="图像宽度")
    p.add_argument("--height", type=int, default=1160, help="图像高度")
    p.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="若指定：灰度 >= 该值视为白；不指定则仅计 255（与 8'hFF 一致）",
    )
    args = p.parse_args()

    if args.x is None and args.y is None:
        p.error("请至少指定 --x 或 --y")

    w, h = args.width, args.height
    expected = w * h

    try:
        flat = load_flat_hex(args.input)
    except (OSError, ValueError) as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1

    if len(flat) < expected:
        print(
            f"[!] 像素数不足: 需要 {expected}, 实际 {len(flat)}（将按缺失补 0 仅用于索引安全演示）",
            file=sys.stderr,
        )
        flat.extend([0] * (expected - len(flat)))
    elif len(flat) > expected:
        print(f"[*] 仅使用前 {expected} 个像素（文件共 {len(flat)} 行）")
        flat = flat[:expected]

    thr_note = f">= {args.threshold}" if args.threshold is not None else "== 255"
    print(f"[*] {args.input}")
    print(f"[*] 尺寸: 宽={w} 高={h}；白色判定: {thr_note}")

    total_white = sum(1 for v in flat if is_white(v, args.threshold))
    print(f"[*] 全图白像素总数: {total_white}")

    if args.x is not None:
        if args.x < 0 or args.x >= w:
            print(f"[!] x={args.x} 超出 [0, {w - 1}]", file=sys.stderr)
            return 1
        c = sum(
            1
            for row in range(h)
            if is_white(flat[row * w + args.x], args.threshold)
        )
        print(f"[*] 列 x={args.x}: 白像素个数 = {c}")

    if args.y is not None:
        if args.y < 0 or args.y >= h:
            print(f"[!] y={args.y} 超出 [0, {h - 1}]", file=sys.stderr)
            return 1
        base = args.y * w
        r = sum(1 for i in range(w) if is_white(flat[base + i], args.threshold))
        print(f"[*] 行 y={args.y}: 白像素个数 = {r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
