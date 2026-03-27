# 构建与下板说明

## 仿真

- 工作目录需包含 `image_in.txt`（`$readmemh`，每行 6 位十六进制 `rrggbb`）。可用 `python/img_to_hex.py` 从 BMP/JPG 生成。
- `tb_img_process.v` 中 `IMG_WIDTH` / `IMG_HEIGHT` 必须与激励尺寸一致；`ROI_OUT_W` / `ROI_OUT_H` 须与 `image_process_wrapper` 的 `ROI_OUT_W` / `ROI_OUT_H` 及 `python/roi_hex_to_img.py` 参数一致。

## 资源与限制

- `roi_crop_scale` 使用 `MAX_ROI_W * MAX_ROI_H` 深度 BRAM；若检测框超过该范围会截断采样区域。
- ROI 缩放结果在每帧最后一个有效像素后的若干周期内以 `roi_de` 连续输出 `ROI_OUT_W * ROI_OUT_H` 个像素；垂直消隐需足够长以免与下一帧冲突（testbench 已加大 `V_BACK`）。

## 队友下板时

- 统一顶层 `IMG_WIDTH` / `IMG_HEIGHT`、行 FIFO 深度（`fifo_line_buf` 地址位宽）、`projection_extractor` 中 `MIN_AREA` 与宽高比门限，以及颜色阈值参数。
- 无板阶段以 ModelSim/Vivado 仿真 + Python 可视化闭环为主；下板后再根据实况微调寄存器初值。
