#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据集准备与校验：检查目录结构、图片可读性，生成 manifest YAML 供 train_color_box.py 使用。

不修改原始图片，只写清单文件。

bbox-annotate：依次弹出图片，鼠标拖框 + Enter 写入 YAML（坐标为原图像素 x,y,w,h）。
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

import yaml

IMG_EXT = {".bmp", ".png", ".jpg", ".jpeg", ".webp"}


def list_images(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMG_EXT:
            out.append(p.resolve())
    return out


def collect_paths_bbox_scan(root: Path, glob_pat: str) -> list[Path]:
    """与 bbox-template 相同的枚举规则。"""
    root = root.resolve()
    if not root.is_dir():
        print(f"[!] dataset-root is not a directory or does not exist: {root}", file=sys.stderr)
        sys.exit(1)
    paths: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMG_EXT and fnmatch.fnmatch(p.name, glob_pat):
            paths.append(p)
    if not paths:
        print(f"[!] No images under {root} matching filename pattern {glob_pat!r}", file=sys.stderr)
        print(f"    Supported extensions: {sorted(IMG_EXT)}.", file=sys.stderr)
        sys.exit(1)
    return paths


def rel_to_root(r: Path, p: Path) -> str:
    try:
        return str(p.relative_to(r))
    except ValueError:
        return str(p)


def write_bbox_template(root: Path, out_path: Path, glob_pat: str) -> None:
    root = root.resolve()
    paths = collect_paths_bbox_scan(root, glob_pat)
    samples = [{"image": rel_to_root(root, p), "bbox": [0, 0, 1, 1]} for p in paths]
    manifest = {
        "format": "full_image_bbox",
        "dataset_root": str(root),
        "samples": samples,
        "notes": "Replace bbox [x,y,w,h] per image; coordinates: top-left x,y width height (OpenCV).",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"[+] bbox-template: {len(samples)} images -> {out_path}")


def interactive_pick_roi(
    image_path: Path,
    *,
    max_display_dim: int = 960,
) -> tuple[int, int, int, int] | str:
    """
    弹窗：左键拖矩形，Enter 确认 -> (x,y,w,h) 原图像素；
    'r' 重画；'s' 跳过（返回 'skip'）；ESC 放弃本张（返回 'abort'）。
    """
    try:
        import cv2
    except ImportError:
        print("[!] bbox-annotate needs opencv-python. pip install opencv-python", file=sys.stderr)
        sys.exit(1)

    img = cv2.imread(str(image_path))
    if img is None:
        print(f"[!] cannot read: {image_path}", file=sys.stderr)
        return "skip"

    H, W = img.shape[:2]
    scale = min(1.0, float(max_display_dim) / max(float(W), float(H), 1.0))
    disp_w = max(1, int(round(W * scale)))
    disp_h = max(1, int(round(H * scale)))
    disp = cv2.resize(img, (disp_w, disp_h), interpolation=cv2.INTER_AREA)

    state: dict = {
        "down": False,
        "x0": 0,
        "y0": 0,
        "x1": 0,
        "y1": 0,
    }

    win = "bbox-annotate | drag LMB | Enter=confirm | R=reset | S=skip | ESC=abort all"

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            state["down"] = True
            state["x0"] = state["x1"] = x
            state["y0"] = state["y1"] = y
        elif event == cv2.EVENT_MOUSEMOVE and state["down"]:
            state["x1"] = x
            state["y1"] = y
        elif event == cv2.EVENT_LBUTTONUP:
            state["down"] = False
            state["x1"] = x
            state["y1"] = y

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, min(1280, disp_w + 80), min(900, disp_h + 80))
    cv2.setMouseCallback(win, on_mouse)

    help_lines = [
        image_path.name,
        "Drag rectangle on plate, then Enter",
        "R=reset  S=skip  ESC=abort entire run",
    ]

    while True:
        canvas = disp.copy()
        xa, ya = min(state["x0"], state["x1"]), min(state["y0"], state["y1"])
        xb, yb = max(state["x0"], state["x1"]), max(state["y0"], state["y1"])
        if (xb - xa) >= 2 and (yb - ya) >= 2:
            cv2.rectangle(canvas, (xa, ya), (xb, yb), (0, 255, 0), 2)

        y0t = 24
        for i, t in enumerate(help_lines):
            cv2.putText(
                canvas,
                t,
                (10, y0t + i * 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )

        cv2.imshow(win, canvas)
        k = cv2.waitKey(20) & 0xFF

        if k == 27:  # ESC
            cv2.destroyWindow(win)
            return "abort"
        if k in (ord("r"), ord("R")):
            state["down"] = False
            state["x0"] = state["y0"] = state["x1"] = state["y1"] = 0
        if k in (ord("s"), ord("S")):
            cv2.destroyWindow(win)
            return "skip"
        if k in (13, 10):  # Enter / linefeed
            xa, ya = min(state["x0"], state["x1"]), min(state["y0"], state["y1"])
            xb, yb = max(state["x0"], state["x1"]), max(state["y0"], state["y1"])
            if (xb - xa) < 2 or (yb - ya) < 2:
                continue
            # 显示坐标 -> 原图坐标（与 plate_ycbcr_stats ROI 语义一致：整数 x,y,w,h）
            ox0 = int(xa / scale)
            oy0 = int(ya / scale)
            ox1 = min(W, int(round(xb / scale)))
            oy1 = min(H, int(round(yb / scale)))
            ow = max(1, ox1 - ox0)
            oh = max(1, oy1 - oy0)
            ox0 = max(0, min(ox0, W - 1))
            oy0 = max(0, min(oy0, H - 1))
            ow = min(ow, W - ox0)
            oh = min(oh, H - oy0)
            cv2.destroyWindow(win)
            return (ox0, oy0, ow, oh)

    cv2.destroyWindow(win)
    return "abort"


def run_bbox_annotate(
    root: Path,
    out_path: Path,
    glob_pat: str,
    *,
    max_display_dim: int,
) -> None:
    root = root.resolve()
    paths = collect_paths_bbox_scan(root, glob_pat)
    samples: list[dict] = []

    print(f"[*] {len(paths)} image(s). Interactive ROI: Enter=confirm, S=skip, ESC=abort.\n")

    for i, p in enumerate(paths, start=1):
        rel = rel_to_root(root, p)
        print(f"--- [{i}/{len(paths)}] {rel} ---")
        r = interactive_pick_roi(p, max_display_dim=max_display_dim)
        if r == "abort":
            print("[!] Aborted by user. No YAML written.", file=sys.stderr)
            sys.exit(1)
        if r == "skip":
            samples.append({"image": rel, "bbox": [0, 0, 1, 1]})
            print("    [skip] bbox left as [0,0,1,1] — edit YAML later or re-run.")
        else:
            x, y, w, h = r
            samples.append({"image": rel, "bbox": [x, y, w, h]})
            print(f"    bbox = [{x}, {y}, {w}, {h}]")

    manifest = {
        "format": "full_image_bbox",
        "dataset_root": str(root),
        "samples": samples,
        "notes": "bbox [x,y,w,h] in original image pixels (OpenCV: top-left, width, height).",
    }
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"\n[+] bbox-annotate: wrote {len(samples)} samples -> {out_path}")

    try:
        import cv2

        cv2.destroyAllWindows()
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate dataset dirs and write manifest YAML")
    ap.add_argument(
        "--mode",
        choices=("folder", "bbox-template", "bbox-annotate"),
        default="folder",
        help="folder | bbox-template (placeholder bbox) | bbox-annotate (interactive ROI)",
    )
    ap.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("data"),
        help="folder: root with positive/negative. bbox-*: root to scan for images",
    )
    ap.add_argument(
        "--glob",
        dest="glob_pat",
        default="*.*",
        help="bbox-template / bbox-annotate: filename glob, e.g. '*.jpg'",
    )
    ap.add_argument(
        "--max-display",
        type=int,
        default=960,
        help="bbox-annotate: max long edge (px) of preview window for large images",
    )
    ap.add_argument(
        "--positive-subdir",
        default="positive",
        help="folder mode: positive subdir name",
    )
    ap.add_argument(
        "--negative-subdir",
        default="negative",
        help="folder mode: negative subdir name",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("dataset_manifest.yaml"),
        help="Output manifest path",
    )
    args = ap.parse_args()

    if args.mode == "bbox-template":
        write_bbox_template(args.dataset_root, args.output.resolve(), args.glob_pat)
        return

    if args.mode == "bbox-annotate":
        run_bbox_annotate(
            args.dataset_root,
            args.output.resolve(),
            args.glob_pat,
            max_display_dim=args.max_display,
        )
        return

    root = args.dataset_root.resolve()
    pos_dir = root / args.positive_subdir
    neg_dir = root / args.negative_subdir

    errors: list[str] = []
    if not pos_dir.is_dir():
        errors.append(f"missing positive dir: {pos_dir}")
    if not neg_dir.is_dir():
        errors.append(f"missing negative dir: {neg_dir}")
    if errors:
        for e in errors:
            print(f"[!] {e}", file=sys.stderr)
        print(
            "\nCreate folders, e.g.:\n"
            f"  {pos_dir}/   # plate crops or plate-dominant patches\n"
            f"  {neg_dir}/   # road, body, sky, etc.\n"
            "See README.md for content requirements.",
            file=sys.stderr,
        )
        sys.exit(1)

    pos_files = list_images(pos_dir)
    neg_files = list_images(neg_dir)
    if not pos_files:
        print(f"[!] No images under {pos_dir}", file=sys.stderr)
        sys.exit(1)
    if not neg_files:
        print(f"[!] No images under {neg_dir}", file=sys.stderr)
        sys.exit(1)

    out_path = args.output.resolve()

    rel_pos = [rel_to_root(root, p) for p in pos_files]
    rel_neg = [rel_to_root(root, p) for p in neg_files]

    manifest = {
        "dataset_root": str(root),
        "positive_files": rel_pos,
        "negative_files": rel_neg,
        "notes": "positive_files / negative_files paths are relative to dataset_root.",
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"[+] positive images: {len(pos_files)}")
    print(f"[+] negative images: {len(neg_files)}")
    print(f"[+] manifest written: {out_path}")


if __name__ == "__main__":
    main()
