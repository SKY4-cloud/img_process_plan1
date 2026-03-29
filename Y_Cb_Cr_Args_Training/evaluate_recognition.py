#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
占位：车牌识别准确率 / 检测框质量量化（后续实现）。

可扩展方向:
  - 若有标注框: 计算 IoU、中心点误差
  - 若有 ground-truth 车牌字符串: 整牌准确率、字符级准确率
  - 与 RTL 仿真输出 result_osd / roi 图像对比

当前仅打印说明，避免与训练脚本混淆。
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Recognition / detection metrics (stub)")
    parser.add_argument("--help-zh", action="store_true", help="print Chinese roadmap")
    args = parser.parse_args()
    if args.help_zh:
        print(
            "后续可接入：\n"
            "  1) 标注 JSON（图路径 + plate_quad 或 bbox）与仿真/算法输出 bbox 算 IoU\n"
            "  2) 识别结果字符串与 GT 编辑距离 / 逐字准确率\n"
            "  3) 固定测试集上统计漏检率、误检率\n"
        )
    else:
        print("Not implemented. Run with --help-zh for roadmap.")


if __name__ == "__main__":
    main()
