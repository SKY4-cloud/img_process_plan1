#!/usr/bin/env python3
"""
批量将工程内仿真分辨率（IMG_WIDTH × IMG_HEIGHT）及相关默认参数对齐到指定宽高。

典型用法：720×1160 全帧仿真前，将 tb / wrapper / 子模块默认 / Python 可视化默认值一并更新。

注意：不修改 TESTING.md 等文档（避免误替换）；改完分辨率后请自行重新生成 image_in.txt。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def auto_max_roi_h(height: int) -> int:
    """与原先 480 行高时 MAX_ROI_H=240 成比例放大，且不小于 240。"""
    return max(240, height * 240 // 480)


def auto_v_back(height: int) -> int:
    """垂直消隐行数：随帧增高略增，保证 ROI drain 等仍有足够空白（保守估计）。"""
    return max(40, (40 * height + 479) // 480)


def auto_proj_min_area(w: int, h: int, base_w: int = 640, base_h: int = 480, base_area: int = 2000) -> int:
    """按像素总数比例缩放 tb 中 PROJ_MIN_AREA（与 640×480@2000 可比）。"""
    return max(500, base_area * w * h // (base_w * base_h))


def auto_proj_threshold(w: int) -> int:
    """投影 THRESHOLD：行/列投影中计数 >= 此值才纳入 bbox。随画幅增大适当提高以滤噪。"""
    return max(5, w // 25)


def replace_in_text(text: str, rules: list[tuple[str, str]], path: str) -> str:
    out = text
    for pat, repl in rules:
        new_out, n = re.subn(pat, repl, out, count=1, flags=re.MULTILINE)
        if n == 0:
            print(f"[!] {path}: pattern not found: {pat!r}", file=sys.stderr)
            sys.exit(1)
        out = new_out
    return out


def patch_tb(content: str, w: int, h: int, v_back: int, proj_min_area: int, proj_threshold: int) -> str:
    rules = [
        (r"parameter IMG_WIDTH\s*=\s*\d+;", f"parameter IMG_WIDTH  = {w};"),
        (r"parameter IMG_HEIGHT\s*=\s*\d+;", f"parameter IMG_HEIGHT = {h};"),
        (r"parameter V_BACK\s*=\s*\d+;", f"parameter V_BACK  = {v_back};"),
        (r"\.PROJ_MIN_AREA\s*\(\s*\d+\s*\)", f".PROJ_MIN_AREA  ( {proj_min_area} )"),
        (r"\.PROJ_THRESHOLD\s*\(\s*\d+\s*\)", f".PROJ_THRESHOLD ( {proj_threshold} )"),
    ]
    return replace_in_text(content, rules, "tb_img_process.v")


def patch_wrapper(content: str, w: int, h: int, max_roi_w: int, max_roi_h: int) -> str:
    rules = [
        (r"parameter IMG_WIDTH\s*=\s*\d+,", f"parameter IMG_WIDTH  = {w},"),
        (r"parameter IMG_HEIGHT\s*=\s*\d+,", f"parameter IMG_HEIGHT = {h},"),
        (r"parameter MAX_ROI_W\s*=\s*\d+,", f"parameter MAX_ROI_W  = {max_roi_w},"),
        (r"parameter MAX_ROI_H\s*=\s*\d+", f"parameter MAX_ROI_H  = {max_roi_h}"),
    ]
    return replace_in_text(content, rules, "image_process_wrapper.v")


def patch_roi_crop_scale(content: str, w: int, h: int, max_roi_w: int, max_roi_h: int) -> str:
    rules = [
        (r"parameter IMG_WIDTH\s*=\s*\d+,", f"parameter IMG_WIDTH   = {w},"),
        (r"parameter IMG_HEIGHT\s*=\s*\d+,", f"parameter IMG_HEIGHT  = {h},"),
        (r"parameter MAX_ROI_W\s*=\s*\d+,", f"parameter MAX_ROI_W   = {max_roi_w},"),
        (r"parameter MAX_ROI_H\s*=\s*\d+", f"parameter MAX_ROI_H   = {max_roi_h}"),
    ]
    return replace_in_text(content, rules, "roi_crop_scale.v")


def patch_projection_extractor(content: str, w: int, h: int) -> str:
    rules = [
        (r"parameter IMG_WIDTH\s*=\s*\d+,", f"parameter IMG_WIDTH  = {w},"),
        (r"parameter IMG_HEIGHT\s*=\s*\d+", f"parameter IMG_HEIGHT = {h}"),
    ]
    return replace_in_text(content, rules, "projection_extractor.v")


def patch_python_arg_defaults(content: str, w: int, h: int, label: str) -> str:
    """替换 --width / --height 的 default= 数字（保留行尾 help= 或括号）。"""
    out = content
    pat_w = r'(p\.add_argument\("--width",[^\n]*default=)\d+'
    pat_h = r'(p\.add_argument\("--height",[^\n]*default=)\d+'
    new_out, n = re.subn(pat_w, rf"\g<1>{w}", out, count=1)
    if n == 0:
        print(f"[!] {label}: --width default= not found", file=sys.stderr)
        sys.exit(1)
    out = new_out
    new_out, n = re.subn(pat_h, rf"\g<1>{h}", out, count=1)
    if n == 0:
        print(f"[!] {label}: --height default= not found", file=sys.stderr)
        sys.exit(1)
    return new_out


def write_state(root: Path, data: dict) -> None:
    p = root / "python" / ".sim_resolution.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="批量对齐仿真分辨率（Verilog + Python 默认宽高）。"
    )
    ap.add_argument("--width", type=int, required=True, help="IMG_WIDTH，例如 720")
    ap.add_argument("--height", type=int, required=True, help="IMG_HEIGHT，例如 1160")
    ap.add_argument(
        "--max-roi-w",
        type=int,
        default=None,
        help="MAX_ROI_W，默认与 --width 相同",
    )
    ap.add_argument(
        "--max-roi-h",
        type=int,
        default=None,
        help="MAX_ROI_H，默认按 480p 时 240 与高度成比例: max(240, height*240//480)",
    )
    ap.add_argument(
        "--v-back",
        type=int,
        default=None,
        help="tb_img_process.v 中 V_BACK，默认随高度缩放 auto_v_back(height)",
    )
    ap.add_argument(
        "--proj-min-area",
        type=int,
        default=None,
        help="tb 中 PROJ_MIN_AREA，默认按帧面积相对 640×480×2000 缩放",
    )
    ap.add_argument(
        "--proj-threshold",
        type=int,
        default=None,
        help="投影行/列计数门限 PROJ_THRESHOLD，默认 max(5, width//25)",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="写入文件；省略则仅打印计划（dry-run）",
    )
    ap.add_argument(
        "--backup",
        action="store_true",
        help="写入前将每个目标文件复制为同目录下 .bak（仅 --apply 时）",
    )
    args = ap.parse_args()

    w, h = args.width, args.height
    if w < 16 or h < 16 or w > 4096 or h > 4096:
        print("[!] width/height 超出合理范围（16..4096），请确认。", file=sys.stderr)
        sys.exit(1)

    max_roi_w = args.max_roi_w if args.max_roi_w is not None else w
    max_roi_h = args.max_roi_h if args.max_roi_h is not None else auto_max_roi_h(h)
    v_back = args.v_back if args.v_back is not None else auto_v_back(h)
    proj_min = args.proj_min_area if args.proj_min_area is not None else auto_proj_min_area(w, h)
    proj_thr = args.proj_threshold if args.proj_threshold is not None else auto_proj_threshold(w)

    root = repo_root()
    targets = [
        (root / "tb_img_process.v", lambda c: patch_tb(c, w, h, v_back, proj_min, proj_thr)),
        (root / "image_process_wrapper.v", lambda c: patch_wrapper(c, w, h, max_roi_w, max_roi_h)),
        (root / "roi_crop_scale.v", lambda c: patch_roi_crop_scale(c, w, h, max_roi_w, max_roi_h)),
        (root / "projection_extractor.v", lambda c: patch_projection_extractor(c, w, h)),
        (root / "python" / "img_to_hex.py", lambda c: patch_python_arg_defaults(c, w, h, "img_to_hex.py")),
        (root / "python" / "hex_to_img.py", lambda c: patch_python_arg_defaults(c, w, h, "hex_to_img.py")),
        (root / "python" / "show_box.py", lambda c: patch_python_arg_defaults(c, w, h, "show_box.py")),
    ]

    print(f"[*] Target resolution: {w} × {h}")
    print(f"[*] MAX_ROI_W/H: {max_roi_w} × {max_roi_h}")
    print(f"[*] V_BACK: {v_back}  |  PROJ_MIN_AREA (tb): {proj_min}  |  PROJ_THRESHOLD: {proj_thr}")
    print()

    for path, patcher in targets:
        rel = path.relative_to(root)
        if not path.is_file():
            print(f"[!] Missing file: {path}", file=sys.stderr)
            sys.exit(1)
        old = path.read_text(encoding="utf-8")
        new = patcher(old)
        if old == new:
            print(f"[=] {rel} (unchanged)")
        else:
            print(f"[~] {rel} (will update)")

    if not args.apply:
        print("\n[*] Dry-run only. Pass --apply to write files.")
        sys.exit(0)

    for path, patcher in targets:
        rel = path.relative_to(root)
        old = path.read_text(encoding="utf-8")
        new = patcher(old)
        if args.backup and old != new:
            bak = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, bak)
            print(f"[+] Backup: {bak.relative_to(root)}")
        path.write_text(new, encoding="utf-8")
        print(f"[+] Wrote {rel}")

    write_state(
        root,
        {
            "IMG_WIDTH": w,
            "IMG_HEIGHT": h,
            "MAX_ROI_W": max_roi_w,
            "MAX_ROI_H": max_roi_h,
            "V_BACK": v_back,
            "PROJ_MIN_AREA": proj_min,
            "PROJ_THRESHOLD": proj_thr,
        },
    )
    print(f"[+] State: python/.sim_resolution.json")
    print("\n[+] 下一步：重新生成激励并仿真，例如：")
    print(f"    python python/img_to_hex.py -i your.jpg -o image_in.txt --width {w} --height {h} --resize letterbox")
    print("    run_sim.bat")
    print(f"    python python/hex_to_img.py -i image_out.txt -o result_post.jpg --width {w} --height {h}")


if __name__ == "__main__":
    main()
