# 仿真分辨率批量对齐说明

## 用途

将工程内 **TB、顶层与子模块默认参数、Python 可视化脚本的默认宽高** 一次性改为目标分辨率（例如 **720×1160**），避免手工改多处漏改。

脚本路径：**`python/set_sim_resolution.py`**

---

## 依赖

- Python 3.8+（仅用标准库，无额外 pip 包）

---

## 基本用法

在项目根目录（与 `tb_img_process.v` 同级）执行：

```bat
cd /d e:\img_process_plan1
python python\set_sim_resolution.py --width 720 --height 1160
```

默认 **只预览（dry-run）**，不修改文件。确认输出中列出的文件无误后，加上 **`--apply`** 真正写入：

```bat
python python\set_sim_resolution.py --width 720 --height 1160 --apply
```

建议首次 **`--apply`** 时同时 **`--backup`**，会在同目录生成 `*.bak` 备份：

```bat
python python\set_sim_resolution.py --width 720 --height 1160 --apply --backup
```

---

## 脚本会自动改什么

| 文件 | 内容 |
|------|------|
| `tb_img_process.v` | `IMG_WIDTH`、`IMG_HEIGHT`、`V_BACK`、`image_process_wrapper` 的 `PROJ_MIN_AREA` |
| `image_process_wrapper.v` | `IMG_WIDTH`、`IMG_HEIGHT`、`MAX_ROI_W`、`MAX_ROI_H` |
| `roi_crop_scale.v` | 同上（与 wrapper 一致） |
| `projection_extractor.v` | 默认 `IMG_WIDTH`、`IMG_HEIGHT`（与 TB 一致） |
| `python/img_to_hex.py` | `--width` / `--height` 的 **default** |
| `python/hex_to_img.py` | 同上 |
| `python/show_box.py` | 同上 |

写入成功后会在 **`python/.sim_resolution.json`** 记录本次宽高及 `V_BACK`、`PROJ_MIN_AREA` 等，便于核对。

---

## 自动推导规则（可调参覆盖）

- **`MAX_ROI_W`**：默认等于 **`--width`**（可用 `--max-roi-w` 覆盖）。
- **`MAX_ROI_H`**：默认 `max(240, height * 240 // 480)`（与原先 480 行高、240 上限成比例；可用 `--max-roi-h` 覆盖）。
- **`V_BACK`**：默认 `max(40, (40 * height + 479) // 480)`，随帧增高略增，给 ROI 在帧末 drain 留空白（可用 `--v-back` 覆盖）。
- **`PROJ_MIN_AREA`（仅 tb）**：默认按像素总数相对 **640×480 且面积门限 2000** 缩放，且 **不小于 500**（可用 `--proj-min-area` 覆盖）。

示例：手动指定 ROI 缓存与投影门限：

```bat
python python\set_sim_resolution.py --width 720 --height 1160 --max-roi-h 600 --proj-min-area 8000 --apply
```

---

## 脚本不会改什么（须自行处理）

1. **`TESTING.md`、`python/README.md` 等文档** — 不自动替换，避免误伤文中举例数字。
2. **`roi_hex_to_img.py`** — ROI 输出尺寸由 **`ROI_OUT_W` / `ROI_OUT_H`**（TB/顶层）决定；改分辨率后 **若未改 ROI 输出大小**，可视化仍用原 `--width 64 --height 32` 即可。
3. **`matrix_3x3.v`** — 由 **`image_process_wrapper` 例化时传入** `IMG_WIDTH`/`IMG_HEIGHT`，一般无需改文件内默认 1920×1080。
4. **`image_in.txt`** — 须用新分辨率 **重新生成**（见下）。

---

## 改分辨率后的推荐流程

1. 执行 `set_sim_resolution.py --apply`（必要时 `--backup`）。
2. 用 **`img_to_hex.py`** 按 **新默认或显式 `--width/--height`** 生成 `image_in.txt`（行数 = `width * height`）：

   ```bat
   python python\img_to_hex.py -i test2.jpg -o image_in.txt --width 720 --height 1160 --resize letterbox
   ```

3. 运行 **`run_sim.bat`**（或等价 `iverilog` + `vvp`）。
4. 用 **`hex_to_img.py` / `show_box.py`** 还原整帧结果（默认已与脚本同步；也可显式写宽高）。
5. **`roi_hex_to_img.py`**：`--width` / `--height` 与 TB 里 **`ROI_OUT_W` / `ROI_OUT_H`** 一致（默认多为 64×32）。

---

## 恢复到 640×480

再次运行脚本，把宽高设回 **640** 和 **480** 并 **`--apply`** 即可，例如：

```bat
python python\set_sim_resolution.py --width 640 --height 480 --apply --backup
```

然后重新生成 **`image_in.txt`**（640×480 行）。

---

## 注意事项

- **仿真时间与内存**：分辨率越大，`tb` 中 `img_mem` 越大（例如 720×1160 ≈ **83 万** 像素），`roi_crop_scale` 中 **`MAX_ROI_W * MAX_ROI_H`** BRAM 也更大，`vvp` 可能明显变慢或占内存升高，属正常现象。
- **门限需重调**：`PROJ_MIN_AREA`、YCbCr 窗口、`PROJ_MAX_WH_*` 等在不同分辨率下表现不同，若检测异常请在 TB/顶层上再微调。
- **若某次 `--apply` 失败**：可用 **`--backup`** 生成的 `*.bak` 手工恢复对应文件。

---

## 故障排除

| 现象 | 处理 |
|------|------|
| 提示 `pattern not found` | 源文件与脚本预期格式不一致（例如手工改过参数行格式），对照报错文件恢复为常规 `parameter ... = 数字` 形式后再运行。 |
| 仿真无输出或行数不对 | 确认 `image_in.txt` 行数等于 **`width * height`**，且与 TB 一致。 |
| ROI 输出截断 | 适当增大 **`--max-roi-w`** / **`--max-roi-h`** 或 **`V_BACK`**（消隐不足时）。 |
