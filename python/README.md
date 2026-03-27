# 离线工具链（仿真 / 调参）

## 依赖

```bash
pip install opencv-python numpy matplotlib
```

## 脚本

| 脚本 | 说明 |
|------|------|
| `pick_roi.py` | 鼠标拖框交互选取 ROI，终端打印 `x,y,w,h`（供 `--roi` / `img_to_hex --crop`） |
| `plate_ycbcr_stats.py` | `--mode rtl` 与 FPGA RGB565+YCbCr 一致；用于统计 Cb/Cr/Y 分位数与直方图 |
| `img_to_hex.py` | 将图转为 `image_in.txt`（`$readmemh`），`--width/--height` 须与 `tb_img_process` 一致 |
| `hex_to_img.py` | `image_out.txt`（二值后单通道）→ 灰度图 |
| `show_box.py` | `image_out_rgb.txt`（OSD）→ 彩色图 |
| `roi_hex_to_img.py` | `image_out_roi.txt`（模板 ROI）→ 彩色图 |

## 典型流程

1. （可选）框车牌 ROI：`python .\python\pick_roi.py -i your.bmp`，将打印的 `--roi` 用于下一步  
2. 统计阈值：`python .\python\plate_ycbcr_stats.py -i your.bmp --mode rtl --roi x,y,w,h -o stats`
3. 生成激励：`python img_to_hex.py -i test1.bmp -o ../image_in.txt --width 640 --height 480 --resize letterbox`（宽高须与 `tb_img_process` 一致）
4. 运行仿真，在工程目录得到 `image_out.txt`、`image_out_rgb.txt`、`image_out_roi.txt`
5. 可视化：`python hex_to_img.py -i image_out.txt -o post.jpg` 等

## 与 RTL 参数对应

`image_process_wrapper` 中 `CB_MIN/MAX`、`CR_MIN/MAX`、`Y_MIN/MAX` 应与 `plate_ycbcr_stats.py --mode rtl` 在**车牌 ROI** 上的统计一致；`PROJ_MIN_AREA` 与宽高比参数需与画面分辨率匹配。
