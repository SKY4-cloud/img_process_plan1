# Y_Cb_Cr_Args_Training

在 **与 FPGA 完全一致** 的颜色链路上，用正/负样本像素标定 **`blue_fg` 的三维联合区间**（`Y_MIN/MAX`、`CB_MIN/MAX`、`CR_MIN/MAX`）。适用于方案 **C**（WB 后再进 `RGB2YCbCr_1`）：离线统计须 **先 WB 再算 YCbCr**，且前面必须经过 **RGB565 截断 → RGB888 展开 → RTL 整数 YCbCr**（见 `fpga_color_chain.py`）。

---

## 环境

```bash
cd Y_Cb_Cr_Args_Training
pip install -r requirements.txt
```

依赖：`numpy`、`opencv-python`、`PyYAML`。

---

## 数据集：两种组织方式

### 模式 A：`positive/` + `negative/`（独立图片列表）

所有图片放在本目录下的 **`data/`**（可换路径）。

```
Y_Cb_Cr_Args_Training/
  data/
    positive/     # 正样本：车牌占主体的裁切图或小图
    negative/     # 负样本：非车牌、易与蓝牌混淆的区域裁切（不得含车牌）
```

- **正样本**：蓝底车牌占画面大部分的裁切；多光照、多场景。
- **负样本**：风挡反光、路面、车身等 **整块图内都不含车牌** 的 patch；**禁止**用「含车牌的整帧」当负样本图。
- Manifest 由 `prepare_dataset.py --mode folder` 生成，字段为 `positive_files` / `negative_files`（路径相对 `dataset_root`）。

### 模式 B：整图 + 车牌 `bbox`（推荐与方案 C 一致）

每张样本为 **一张完整分辨率图像** + **车牌矩形框**（OpenCV 约定：`[x, y, w, h]` = 左上角列、行，宽、高，像素整数）。

- **处理顺序**（与训练脚本一致）：对 **整图** 做 RGB565→RGB888→**可选 WB**→RTL YCbCr；**正像素** = 框内所有像素（可子采样）；**负像素** = 框外所有像素（子采样），语义上 **框外整幅背景均为负类**。
- **`dataset_root`**：存放整图的根目录；`samples[].image` 为相对该根的路径（如 `test5.jpg` 或 `raw/test5.jpg`）。
- 示例见 **`dataset_manifest_bbox.example.yaml`**。可用下列命令生成待填 bbox 的模板：

```bash
python prepare_dataset.py --mode bbox-template --dataset-root ../ --glob "*.jpg" -o my_bbox_manifest.yaml
```

生成后请把每条 `bbox: [0, 0, 1, 1]` 改成真实车牌框。

**交互标注 `bbox-annotate`**（免手改 YAML）：按顺序弹出每张图，**按住左键拖动**框住车牌，按 **Enter** 确认写入该图的 `bbox`（原图像素 `x,y,w,h`，与 `plate_ycbcr_stats --roi` 一致）。**R** 清空重画；**S** 跳过（写入占位 `[0,0,1,1]`）；**ESC** 中止整次运行且**不写 YAML**。需本机图形界面与 `opencv-python`，大图可 `--max-display 1200` 控制预览长边。

```bash
python prepare_dataset.py --mode bbox-annotate --dataset-root ./Y_Cb_Cr_Args_Training/dataset_root --glob "*.jpg" -o my_manifest.yaml
```

Manifest 需包含 `format: full_image_bbox`（或仅含带 `bbox` 的 `samples` 列表，脚本亦会识别）。

### 负采样（模式 B）

- **`--neg-mode uniform`**：在 bbox **外** 均匀随机采（默认）。
- **`--neg-mode blue_biased`**：优先采框外且 **`Cb >= neg_cb_min`** 的像素（硬负样本，压风挡/发蓝背景）；若数量不足则退回框外均匀。

---

## 流程 1：准备数据集并生成清单

**模式 A（双文件夹）**

```bash
python prepare_dataset.py --mode folder --dataset-root data -o dataset_manifest.yaml
```

**模式 B（bbox 模板）**

```bash
python prepare_dataset.py --mode bbox-template --dataset-root ../ --glob "*.jpg" -o dataset_manifest_bbox.yaml
```

**模式 B2（bbox 交互标注，直接得到正确 bbox）**

```bash
python prepare_dataset.py --mode bbox-annotate --dataset-root ../ --glob "*.jpg" -o dataset_manifest_bbox.yaml
```

成功后会输出 YAML。模式 A 若目录缺失或无图片则 **非 0 退出**。

---

## 流程 2：三维联合标定（训练阈值盒）

```bash
python train_color_box.py -m dataset_manifest.yaml --wb none -o trained_color_box.json
```

方案 C 与 RTL 对齐、在 **灰世界 WB 后** 再统计时：

```bash
python train_color_box.py -m dataset_manifest.yaml --wb gray_world -o trained_color_box.json
```

**模式 B（整图 bbox）示例**

```bash
python train_color_box.py -m dataset_manifest_bbox.yaml --wb gray_world --neg-mode blue_biased -o trained_color_box.json
```

### 主要参数说明

| 参数 | 含义 |
|------|------|
| `--wb none` / `gray_world` | 是否与 `fpga_color_chain` 一致地做 WB 再转 YCbCr |
| `--q-lo` / `--q-hi` | 仅用 **正样本** 像素定 **初始** 轴对齐盒的分位数（默认 2 / 98） |
| `--min-pos-coverage` | 收紧盒子时，正样本落在盒内的比例 **下限**（默认 0.88） |
| `--max-neg-fraction` | 负样本落在盒内的比例 **目标上限**（默认 0.002） |
| `--max-pixels-per-image` | **模式 A**：每图每类最大采样像素数 |
| `--max-pos-per-image` / `--max-neg-per-image` | **模式 B**：每帧框内 / 框外最大采样数 |
| `--neg-mode` / `--neg-cb-min` | **模式 B**：负样本采样策略（见上） |
| `--max-total-samples` | 每类进入贪心收紧前的像素上限（默认 120000；**0** 表示不截断） |
| `--refine-iters` | 贪心收紧最大迭代次数 |

### 输出

1. **`trained_color_box.json`**：`Y_MIN/MAX`、`CB_*`、`CR_*` 及中间统计。
2. **控制台**：一段可直接对照替换 `image_process_wrapper.v` 里 `CB_MIN`…`Y_MAX` 的 **parameter** 片段。

**联合约束含义**：RTL 中与现网一致，`blue_fg = (Cb∈[CB_MIN,CB_MAX]) && (Cr∈[CR_MIN,CR_MAX]) && (Y∈[Y_MIN,Y_MAX])`，即 **三维轴对齐长方体**；训练脚本在该几何下做 **分位数初始化 + 在保持正样本覆盖率前提下压缩负样本占比**。

---

## 与主工程其它脚本的关系

- 根目录 **`python/plate_ycbcr_stats.py`**：单图/ROI 统计，**不含 WB、不含负样本联合优化**。
- 本目录 **`fpga_color_chain.py`**：训练与 **RTL 方案 C** 对齐的离线链路（RGB565 → RGB888 → `gray_world` → RTL YCbCr）。
- 根目录 RTL：**`gray_world_wb.v`** 插在 **`RGB2YCbCr_1` 之前**；`image_process_wrapper` 参数 **`ENABLE_GRAY_WORLD_WB`**（默认 1）可关断以回退原路径。训练时请使用 **`--wb gray_world`**。

---

## 流程 3（后续）：识别准确率评估

见 **`evaluate_recognition.py`**（当前为占位）。建议后续接入：标注 bbox/车牌字符串、与仿真输出对比 IoU 或字符准确率。

---

## 参考配置

`config.example.yaml` 中整理了常用字段，便于复制为 `config.yaml` 做笔记；**当前训练仍以 `train_color_box.py` 命令行参数为准**。

---

## 常见问题

**Q：为什么必须用 RGB565 截断再展开？**  
A：与 `image_process_wrapper` → `RGB2YCbCr_1` 输入一致，否则离线得到的 Y/Cb/Cr 与综合/仿真 **对不齐**。

**Q：`gray_world` 与将来 Verilog WB 会完全一致吗？**  
A：本脚本为 **浮点灰世界 + 四舍五入到 uint8**；FPGA 多为 **定点增益 + 饱和**。上线前请用少量帧对比或收紧/放宽 1～2 个灰阶。

**Q：负样本很少会怎样？**  
A：盒子可能 **过宽**，整图发蓝时仍易误报；请优先扩充 `negative/`。
