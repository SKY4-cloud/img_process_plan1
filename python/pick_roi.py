#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互框选 ROI，终端打印 plate_ycbcr_stats / img_to_hex 可用的 x,y,w,h。

用法:
  python pick_roi.py -i ../test1.bmp
  python pick_roi.py -i test1.bmp -o roi.txt

操作: 窗口打开后鼠标拖框，空格或回车确认，ESC 取消。
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2


def main() -> None:
    p = argparse.ArgumentParser(description="Interactive ROI -> x,y,w,h for --roi")
    p.add_argument("-i", "--input", required=True, help="Input image (bmp/jpg/png)")
    p.add_argument(
        "-o",
        "--output",
        default="",
        help="Optional: append line to text file (e.g. roi.txt)",
    )
    args = p.parse_args()

    path = args.input
    if not os.path.isfile(path):
        print(f"[!] File not found: {path}", file=sys.stderr)
        sys.exit(1)

    img = cv2.imread(path)
    if img is None:
        print(f"[!] Cannot read image: {path}", file=sys.stderr)
        sys.exit(1)

    h, w = img.shape[:2]
    print(f"[*] Image size: {w} x {h} (width x height)")

    # selectROI returns (x, y, w, h) in pixels; fromCenter=False uses corner drag
    r = cv2.selectROI("pick_roi: drag box, SPACE/ENTER confirm, ESC cancel", img, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()

    x, y, rw, rh = map(int, r)
    if rw <= 0 or rh <= 0:
        print("[!] Empty selection or cancelled.")
        sys.exit(1)

    roi_str = f"{x},{y},{rw},{rh}"
    print(f"\n[*] ROI (x,y,w,h) = {roi_str}")
    print(f"\n    plate_ycbcr_stats.py:\n      --roi {roi_str}")
    print(f"\n    img_to_hex.py:\n      --crop {roi_str}")

    if args.output.strip():
        out_path = args.output.strip()
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"{path}\t{roi_str}\n")
        print(f"\n[+] Appended to {out_path}")


if __name__ == "__main__":
    main()
