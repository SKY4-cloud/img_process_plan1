#!/usr/bin/env python3
"""
对指定的 test<N>.jpg 依次跑完整仿真与出图流程（img_to_hex → iverilog+vvp → 三张结果图）。

默认从 plan1 根目录读取 test<N>.jpg（与 python/ 同级指：图片在 plan1 下，不在子文件夹里）。
仿真与中间文件、结果图均在 plan1 根目录。

用法示例（在 plan1 根目录执行）:
  python python\\batch_test_images.py 5 6 7
  python python\\batch_test_images.py --range 2-9
  python python\\batch_test_images.py --image-dir subfolder 3 4   # 若改放到子目录可指定

依赖: PATH 中可用 iverilog、vvp；与 run_sim.bat 使用相同的源文件列表。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


# 须与 run_sim.bat 中 iverilog 源文件列表一致
IVERILOG_SOURCES = [
    "tb_img_process.v",
    "video_xy_counter.v",
    "image_process_wrapper.v",
    "gray_world_wb.v",
    "roi_crop_scale.v",
    "projection_extractor.v",
    "osd_draw_box.v",
    "matrix_3x3.v",
    "fifo_line_buf.v",
    "morphology.v",
    "RGB2YCbCr_1.v",
]

IMG_W, IMG_H = 720, 1160
ROI_W, ROI_H = 128, 64


def repo_root() -> Path:
    """plan1 工程根目录（python 的上一级）。"""
    return Path(__file__).resolve().parent.parent


def resolve_image_dir(repo: Path, image_dir_arg: str | None) -> Path:
    """默认同 plan1 根目录；--image-dir 为相对路径时相对 repo 解析。"""
    if not image_dir_arg or not image_dir_arg.strip():
        return repo
    p = Path(image_dir_arg)
    if not p.is_absolute():
        p = (repo / p).resolve()
    return p


def parse_tests(args: argparse.Namespace) -> list[int]:
    if args.range:
        a, b = args.range.split("-", 1)
        lo, hi = int(a.strip()), int(b.strip())
        if lo > hi:
            lo, hi = hi, lo
        return list(range(lo, hi + 1))
    nums = list(args.tests or [])
    if not nums:
        print("请指定要测试的编号，例如: python python/batch_test_images.py 5 6 7", file=sys.stderr)
        print("或: python python/batch_test_images.py --range 2-9", file=sys.stderr)
        sys.exit(2)
    return sorted(set(nums))


def run(cmd: list[str], cwd: Path, **kwargs) -> None:
    print(f"[cmd] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True, **kwargs)


def compile_sim(root: Path) -> None:
    out_vvp = root / "sim.vvp"
    cmd = ["iverilog", "-g2012", "-Wall", "-o", str(out_vvp)] + IVERILOG_SOURCES
    run(cmd, cwd=root)


def run_vvp(root: Path) -> None:
    # tb 使用 $stop，须在标准输入送入 finish 以结束交互
    subprocess.run(
        ["vvp", str(root / "sim.vvp")],
        cwd=root,
        input="finish\n",
        text=True,
        check=True,
    )


def process_one(root: Path, image_dir: Path, n: int, skip_compile: bool) -> None:
    jpg = image_dir / f"test{n}.jpg"
    if not jpg.is_file():
        raise FileNotFoundError(f"找不到输入图: {jpg}")

    py = sys.executable
    scripts = root / "python"

    print(f"\n========== test{n} ({jpg}) ==========")

    run(
        [
            py,
            str(scripts / "img_to_hex.py"),
            "-i",
            str(jpg),
            "-o",
            str(root / "image_in.txt"),
            "--width",
            str(IMG_W),
            "--height",
            str(IMG_H),
            "--resize",
            "letterbox",
        ],
        cwd=root,
    )

    if not skip_compile:
        compile_sim(root)
    run_vvp(root)

    run(
        [
            py,
            str(scripts / "hex_to_img.py"),
            "-i",
            str(root / "image_out.txt"),
            "-o",
            str(root / f"result_post{n}.jpg"),
            "--width",
            str(IMG_W),
            "--height",
            str(IMG_H),
        ],
        cwd=root,
    )
    run(
        [
            py,
            str(scripts / "show_box.py"),
            "-i",
            str(root / "image_out_rgb.txt"),
            "-o",
            str(root / f"result_osd{n}.jpg"),
            "--width",
            str(IMG_W),
            "--height",
            str(IMG_H),
        ],
        cwd=root,
    )
    run(
        [
            py,
            str(scripts / "roi_hex_to_img.py"),
            "-i",
            str(root / "image_out_roi.txt"),
            "-o",
            str(root / f"result_roi{n}.jpg"),
            "--width",
            str(ROI_W),
            "--height",
            str(ROI_H),
        ],
        cwd=root,
    )
    print(f"[ok] test{n} -> result_post{n}.jpg, result_osd{n}.jpg, result_roi{n}.jpg")


def main() -> None:
    p = argparse.ArgumentParser(description="批量对 testN.jpg 跑仿真并生成 post/osd/roi 图")
    p.add_argument(
        "tests",
        nargs="*",
        type=int,
        help="测试编号，如 5 6 7（对应 test5.jpg …）",
    )
    p.add_argument(
        "--range",
        metavar="A-B",
        help="连续区间，如 2-9 等价于 2 3 … 9",
    )
    p.add_argument(
        "--recompile-each",
        action="store_true",
        help="每张图都重新 iverilog（默认只在第一张前编译一次）",
    )
    p.add_argument(
        "--image-dir",
        metavar="DIR",
        default=None,
        help="testN.jpg 所在目录；默认 plan1 根目录。相对路径相对 plan1 根",
    )
    args = p.parse_args()
    tests = parse_tests(args)
    root = repo_root()
    image_dir = resolve_image_dir(root, args.image_dir)
    if not image_dir.is_dir():
        print(f"[!] 输入图目录不存在: {image_dir}", file=sys.stderr)
        sys.exit(2)

    for i, n in enumerate(tests):
        if args.recompile_each or i == 0:
            skip_compile = False
        else:
            skip_compile = True
        try:
            process_one(root, image_dir, n, skip_compile=skip_compile)
        except subprocess.CalledProcessError as e:
            print(f"[fail] test{n}: 命令退出码 {e.returncode}", file=sys.stderr)
            sys.exit(e.returncode)
        except FileNotFoundError as e:
            print(f"[fail] {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
