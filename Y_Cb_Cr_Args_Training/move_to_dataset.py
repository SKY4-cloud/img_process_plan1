#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 data_choose 中的图片移入 data_set，命名为 test(n).jpg；
n 从 data_set 中已有 test(数字).jpg 的最大数字 + 1 起依次递增。

- 已是 .jpg/.jpeg：直接移动并改名。
- 其它常见格式：用 OpenCV 读入后存为 JPEG，再删除源文件（等价于「移动为 jpg」）。

默认路径相对于**当前工作目录**（建议在仓库根目录执行）。
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

IMG_EXT_IN = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
TEST_RE = re.compile(r"^test(\d+)\.jpg$", re.IGNORECASE)


def max_test_index(data_set: Path) -> int:
    m = 0
    if not data_set.is_dir():
        return m
    for p in data_set.iterdir():
        if not p.is_file():
            continue
        mo = TEST_RE.match(p.name)
        if mo:
            m = max(m, int(mo.group(1)))
    return m


def list_source_images(src: Path) -> list[Path]:
    if not src.is_dir():
        return []
    out = []
    for p in sorted(src.iterdir()):
        if p.is_file() and p.suffix.lower() in IMG_EXT_IN:
            out.append(p)
    return out


def move_as_jpeg(src_file: Path, dest_jpg: Path) -> None:
    suf = src_file.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        shutil.move(str(src_file), str(dest_jpg))
        return
    try:
        import cv2
    except ImportError:
        print("[!] 非 JPEG 源图需要 opencv-python: pip install opencv-python", file=sys.stderr)
        sys.exit(1)
    img = cv2.imread(str(src_file))
    if img is None:
        raise RuntimeError(f"无法读取: {src_file}")
    dest_jpg.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(dest_jpg), img, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
        raise RuntimeError(f"无法写入: {dest_jpg}")
    src_file.unlink()


def main() -> None:
    ap = argparse.ArgumentParser(description="data_choose -> data_set as test(n).jpg")
    ap.add_argument(
        "--source",
        type=Path,
        default=Path("data_choose"),
        help="源目录（默认 ./data_choose）",
    )
    ap.add_argument(
        "--dest",
        type=Path,
        default=Path("data_set"),
        help="目标目录（默认 ./data_set）",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要执行的操作，不移动文件",
    )
    args = ap.parse_args()

    src_dir = args.source.resolve()
    dst_dir = args.dest.resolve()

    if not src_dir.is_dir():
        print(f"[!] 源目录不存在: {src_dir}", file=sys.stderr)
        sys.exit(1)

    files = list_source_images(src_dir)
    if not files:
        print(f"[!] {src_dir} 中没有可识别的图片 ({sorted(IMG_EXT_IN)})", file=sys.stderr)
        sys.exit(1)

    n = max_test_index(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    print(f"[*] data_set 当前 test(n).jpg 最大 n = {n}")
    print(f"[*] 待处理 {len(files)} 个文件\n")

    for p in files:
        n += 1
        dest_name = f"test{n}.jpg"
        dest_path = dst_dir / dest_name
        if dest_path.exists():
            print(f"[!] 目标已存在，跳过: {dest_path}", file=sys.stderr)
            n -= 1
            continue
        if args.dry_run:
            print(f"    [dry-run] {p.name} -> {dest_path}")
            continue
        try:
            move_as_jpeg(p, dest_path)
            print(f"    [+] {p.name} -> {dest_name}")
        except Exception as e:
            print(f"    [!] 失败 {p}: {e}", file=sys.stderr)
            n -= 1
            sys.exit(1)

    if args.dry_run:
        print(f"\n[*] dry-run 结束（未写入）。下一个将使用 test{n}.jpg 起（若上面无跳过）。")
    else:
        print(f"\n[+] 完成。")


if __name__ == "__main__":
    main()
