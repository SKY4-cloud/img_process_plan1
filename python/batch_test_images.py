#!/usr/bin/env python3
"""
对指定的 test<N>.jpg 依次跑完整仿真与出图流程（img_to_hex → iverilog+vvp → 三张结果图）。

默认从 plan1 根目录读取 test<N>.jpg（与 python/ 同级指：图片在 plan1 下，不在子文件夹里）。
仿真与中间文件、结果图均在 plan1 根目录。

用法示例（在 plan1 根目录执行）:
  python python\\batch_test_images.py 5 6 7
  python python\\batch_test_images.py --range 2-9
  python python\\batch_test_images.py --range 2-9 -j 4       # 4 路并行
  python python\\batch_test_images.py --range 2-9 --parallel  # CPU 核数并行
  python python\\batch_test_images.py --range 2-9 --image-dir Y_Cb_Cr_Args_Training/dataset_root --output-dir Y_Cb_Cr_Args_Training/dataset_result

并行模式说明:
  每张图在 <root>/sim_worker_<N>/ 独立子目录内完成 iverilog+vvp，互不干扰。
  结束后自动合并结果图到 --output-dir，并清理临时目录。
  vvp 占用 CPU 最多，并行路数建议 ≤ 物理核心数。

依赖: PATH 中可用 iverilog、vvp；与 run_sim.bat 使用相同的源文件列表。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
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
    "binary_median_3x3.v",
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


def compile_sim(root: Path, work_dir: Path) -> None:
    """在 work_dir 内编译；源文件用相对于 root 的绝对路径避免路径问题。"""
    out_vvp = work_dir / "sim.vvp"
    src_abs = [str(root / s) for s in IVERILOG_SOURCES]
    cmd = ["iverilog", "-g2012", "-Wall", "-o", str(out_vvp)] + src_abs
    run(cmd, cwd=work_dir)


def run_vvp(work_dir: Path) -> None:
    subprocess.run(
        ["vvp", str(work_dir / "sim.vvp")],
        cwd=work_dir,
        input="finish\n",
        text=True,
        check=True,
    )


# ---------------------------------------------------------------------------
# 串行：单张图在 root 目录就地运行（与旧版行为完全一致）
# ---------------------------------------------------------------------------

def process_one_serial(
    root: Path,
    image_dir: Path,
    out_dir: Path,
    n: int,
    skip_compile: bool,
) -> None:
    jpg = image_dir / f"test{n}.jpg"
    if not jpg.is_file():
        raise FileNotFoundError(f"找不到输入图: {jpg}")

    py = sys.executable
    scripts = root / "python"

    print(f"\n========== test{n} ({jpg}) ==========")

    run(
        [py, str(scripts / "img_to_hex.py"),
         "-i", str(jpg),
         "-o", str(root / "image_in.txt"),
         "--width", str(IMG_W), "--height", str(IMG_H),
         "--resize", "letterbox"],
        cwd=root,
    )

    if not skip_compile:
        compile_sim(root, root)
    run_vvp(root)

    out_dir.mkdir(parents=True, exist_ok=True)
    _dump_results(py, scripts, root, root, out_dir, n)
    print(f"[ok] test{n} -> result_post{n}.jpg, result_osd{n}.jpg, result_roi{n}.jpg")


# ---------------------------------------------------------------------------
# 并行：每张图在独立 work_dir 内运行，结束后复制结果
# ---------------------------------------------------------------------------

def _dump_results(
    py: str,
    scripts: Path,
    root: Path,
    work_dir: Path,
    out_dir: Path,
    n: int,
) -> None:
    run(
        [py, str(scripts / "hex_to_img.py"),
         "-i", str(work_dir / "image_out.txt"),
         "-o", str(out_dir / f"result_post{n}.jpg"),
         "--width", str(IMG_W), "--height", str(IMG_H)],
        cwd=root,
    )
    run(
        [py, str(scripts / "show_box.py"),
         "-i", str(work_dir / "image_out_rgb.txt"),
         "-o", str(out_dir / f"result_osd{n}.jpg"),
         "--width", str(IMG_W), "--height", str(IMG_H)],
        cwd=root,
    )
    run(
        [py, str(scripts / "roi_hex_to_img.py"),
         "-i", str(work_dir / "image_out_roi.txt"),
         "-o", str(out_dir / f"result_roi{n}.jpg"),
         "--width", str(ROI_W), "--height", str(ROI_H)],
        cwd=root,
    )


def _worker(
    root_str: str,
    image_dir_str: str,
    out_dir_str: str,
    n: int,
    keep_workdir: bool,
) -> tuple[int, str]:
    """在子进程内完整处理一张图；返回 (n, 'ok'|错误信息)。"""
    root = Path(root_str)
    image_dir = Path(image_dir_str)
    out_dir = Path(out_dir_str)

    work_dir = root / f"sim_worker_{n}"
    try:
        work_dir.mkdir(parents=True, exist_ok=True)

        jpg = image_dir / f"test{n}.jpg"
        if not jpg.is_file():
            return n, f"找不到输入图: {jpg}"

        py = sys.executable
        scripts = root / "python"

        # 1) img → hex（写入 work_dir/image_in.txt）
        subprocess.run(
            [py, str(scripts / "img_to_hex.py"),
             "-i", str(jpg),
             "-o", str(work_dir / "image_in.txt"),
             "--width", str(IMG_W), "--height", str(IMG_H),
             "--resize", "letterbox"],
            cwd=work_dir, check=True,
        )

        # 2) 编译（每个 worker 独立编译，产物放 work_dir/sim.vvp）
        compile_sim(root, work_dir)

        # 3) vvp 仿真（cwd=work_dir，所有 txt 输出落在 work_dir）
        subprocess.run(
            ["vvp", str(work_dir / "sim.vvp")],
            cwd=work_dir,
            input="finish\n",
            text=True,
            check=True,
        )

        # 4) hex → 结果图
        out_dir.mkdir(parents=True, exist_ok=True)
        _dump_results(py, scripts, root, work_dir, out_dir, n)

        return n, "ok"
    except subprocess.CalledProcessError as e:
        return n, f"命令退出码 {e.returncode}"
    except Exception as e:
        return n, str(e)
    finally:
        if not keep_workdir and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

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
        help="【串行模式】每张图都重新 iverilog（默认只在第一张前编译一次）",
    )
    p.add_argument(
        "--image-dir",
        metavar="DIR",
        default=None,
        help="testN.jpg 所在目录；默认 plan1 根目录。相对路径相对 plan1 根",
    )
    p.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="result_post/osd/roi 输出目录；默认 plan1 根目录。相对路径相对 plan1 根",
    )
    p.add_argument(
        "-j", "--jobs",
        type=int,
        default=1,
        metavar="N",
        help="并行 worker 数（默认 1 = 串行）。-j 0 自动取 CPU 核心数",
    )
    p.add_argument(
        "--parallel",
        action="store_true",
        help="等同于 -j 0（自动核心数并行）",
    )
    p.add_argument(
        "--keep-workdir",
        action="store_true",
        help="并行模式：保留 sim_worker_N/ 临时目录（默认自动删除）",
    )
    args = p.parse_args()
    tests = parse_tests(args)
    root = repo_root()
    image_dir = resolve_image_dir(root, args.image_dir)
    out_dir = resolve_image_dir(root, args.output_dir) if args.output_dir else root
    if not image_dir.is_dir():
        print(f"[!] 输入图目录不存在: {image_dir}", file=sys.stderr)
        sys.exit(2)

    jobs = args.jobs
    if args.parallel:
        jobs = 0
    if jobs == 0:
        jobs = os.cpu_count() or 4

    # 单任务时退化为串行（避免 ProcessPoolExecutor 开销）
    if jobs == 1 or len(tests) == 1:
        for i, n in enumerate(tests):
            skip_compile = not (args.recompile_each or i == 0)
            try:
                process_one_serial(root, image_dir, out_dir, n, skip_compile=skip_compile)
            except subprocess.CalledProcessError as e:
                print(f"[fail] test{n}: 命令退出码 {e.returncode}", file=sys.stderr)
                sys.exit(e.returncode)
            except FileNotFoundError as e:
                print(f"[fail] {e}", file=sys.stderr)
                sys.exit(1)
        return

    # 并行模式
    jobs = min(jobs, len(tests))
    print(f"[parallel] {len(tests)} 张图，{jobs} 路并行 (workers: {tests})")
    t0 = time.time()

    failed = []
    with ProcessPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(
                _worker,
                str(root), str(image_dir), str(out_dir),
                n, args.keep_workdir,
            ): n
            for n in tests
        }
        for fut in as_completed(futures):
            n_done, msg = fut.result()
            elapsed = time.time() - t0
            if msg == "ok":
                print(f"[ok  {elapsed:6.1f}s] test{n_done} -> result_post/osd/roi{n_done}.jpg")
            else:
                print(f"[fail {elapsed:6.1f}s] test{n_done}: {msg}", file=sys.stderr)
                failed.append(n_done)

    total = time.time() - t0
    print(f"\n[done] 共 {len(tests)} 张，耗时 {total:.1f}s")
    if failed:
        print(f"[!] 失败: {sorted(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
