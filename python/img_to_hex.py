"""
将图片缩放为 WxH，导出 Verilog $readmemh 可用的 RGB HEX（每行 rrggbb）。

720x1160 等竖图若直接拉伸到 200x100，宽高比被严重扭曲，车牌竖笔画会被压扁，
Sobel 二值图上车牌与格栅/地面往往「看起来一样」——这是算法+缩放的正常结果，不是单点 bug。

示例:
  python img_to_hex.py -i test4.jpg -o image_in.txt
  python img_to_hex.py -i test4.jpg -o image_in.txt --resize letterbox   # 推荐：保持宽高比，黑边填充
  python img_to_hex.py -i test4.jpg -o image_in.txt --resize cover        # 居中裁切填满 200x100
  python img_to_hex.py -i test4.jpg -o image_in.txt --crop 400,200,800,350
"""
import argparse
import cv2
import numpy as np
import os


def parse_crop(s):
    if not s:
        return None
    parts = [int(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("crop must be x,y,w,h")
    return parts


def resize_to_target(img, tw, th, mode):
    """mode: stretch | letterbox | cover"""
    h, w = img.shape[:2]
    if mode == "stretch":
        return cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
    if mode == "letterbox":
        scale = min(tw / w, th / h)
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        out = np.zeros((th, tw, 3), dtype=np.uint8)
        y0 = (th - nh) // 2
        x0 = (tw - nw) // 2
        out[y0 : y0 + nh, x0 : x0 + nw] = small
        return out
    if mode == "cover":
        scale = max(tw / w, th / h)
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        big = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        x0 = max(0, (nw - tw) // 2)
        y0 = max(0, (nh - th) // 2)
        return big[y0 : y0 + th, x0 : x0 + tw].copy()
    raise ValueError(f"unknown resize mode: {mode}")


def generate_fpga_stimulus(
    input_img_path,
    output_txt_path,
    target_width=200,
    target_height=100,
    crop_rect=None,
    resize_mode="letterbox",
):
    print(f"[*] Reading: {input_img_path}")
    img = cv2.imread(input_img_path)
    if img is None:
        print(f"[!] Failed to read image: {input_img_path}")
        return False

    if crop_rect is not None:
        x, y, w, h = crop_rect
        H0, W0 = img.shape[:2]
        x = max(0, min(x, W0 - 1))
        y = max(0, min(y, H0 - 1))
        w = max(1, min(w, W0 - x))
        h = max(1, min(h, H0 - y))
        img = img[y : y + h, x : x + w]
        print(f"[*] Crop ROI: x={x} y={y} w={w} h={h}")

    print(f"[*] Resize mode: {resize_mode} -> {target_width}x{target_height}")
    resized = resize_to_target(img, target_width, target_height, resize_mode)
    rgb_img = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

    out_dir = os.path.dirname(os.path.abspath(output_txt_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_txt_path, "w", encoding="utf-8") as f:
        for yy in range(target_height):
            for xx in range(target_width):
                r, g, b = rgb_img[yy, xx]
                f.write(f"{r:02x}{g:02x}{b:02x}\n")

    print(f"[+] Wrote {target_width}x{target_height} = {target_width * target_height} pixels -> {output_txt_path}")
    return True


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Image to readmemh hex for tb_img_process")
    p.add_argument("-i", "--input", default="test1.bmp", help="Source image")
    p.add_argument("-o", "--output", default="image_in.txt", help="Output hex file")
    p.add_argument("--width", type=int, default=640, help="Must match tb_img_process IMG_WIDTH")
    p.add_argument("--height", type=int, default=480, help="Must match tb_img_process IMG_HEIGHT")
    p.add_argument(
        "--crop",
        default="",
        help="Optional crop before resize: x,y,w,h in source pixels (e.g. 400,200,520,180)",
    )
    p.add_argument(
        "--resize",
        choices=("stretch", "letterbox", "cover"),
        default="letterbox",
        help="stretch=直接拉满(易变形); letterbox=等比缩放黑边(推荐竖图); cover=等比放大后居中裁剪",
    )
    args = p.parse_args()
    crop = None
    if args.crop.strip():
        try:
            crop = parse_crop(args.crop)
        except ValueError as e:
            print(f"[!] {e}")
            exit(1)
    ok = generate_fpga_stimulus(
        args.input, args.output, args.width, args.height, crop, args.resize
    )
    exit(0 if ok else 1)
