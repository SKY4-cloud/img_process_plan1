"""
将 image_out_roi.txt（每行 rrggbb）还原为 BGR 图。
--width/--height 必须与仿真输出的 ROI 像素数一致（由 tb/RTL 决定），不是“想要多大图就填多大”；
若填得比实际像素多，会用黑色 padding，看起来几乎全黑。

放大显示：保持 width/height 为真实 ROI（如 64x32），再用 --scale 或 --out-width/--out-height 做插值放大。

用法:
  python roi_hex_to_img.py -i image_out_roi.txt -o result_roi.jpg --width 64 --height 32
  python roi_hex_to_img.py -i image_out_roi.txt -o result_big.jpg --width 64 --height 32 --scale 10
"""
import argparse
import numpy as np
import cv2


def main(input_txt, output_img, width, height, scale=1, out_width=None, out_height=None):
    with open(input_txt, "r", encoding="utf-8") as f:
        lines = f.readlines()

    pixels = []
    for line in lines:
        line = line.strip()
        if len(line) == 6:
            r = int(line[0:2], 16)
            g = int(line[2:4], 16)
            b = int(line[4:6], 16)
            pixels.append([b, g, r])

    expected = width * height
    if len(pixels) < expected:
        print(f"[!] Only {len(pixels)} pixels, expected {expected}; padding")
        while len(pixels) < expected:
            pixels.append([0, 0, 0])
    elif len(pixels) > expected:
        pixels = pixels[:expected]

    img = np.array(pixels, dtype=np.uint8).reshape((height, width, 3))

    if out_width is not None and out_height is not None:
        img = cv2.resize(
            img, (out_width, out_height), interpolation=cv2.INTER_LINEAR
        )
    elif scale != 1:
        img = cv2.resize(
            img, (width * scale, height * scale), interpolation=cv2.INTER_NEAREST
        )

    cv2.imwrite(output_img, img)
    print(f"[+] ROI image: {output_img} ({img.shape[1]}x{img.shape[0]})")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="image_out_roi.txt")
    p.add_argument("-o", "--output", default="result_roi.jpg")
    p.add_argument("--width", type=int, default=64)
    p.add_argument("--height", type=int, default=32)
    p.add_argument(
        "--scale",
        type=int,
        default=1,
        help="整数放大倍数（在正确 width/height 解码后再 resize，如 10 得到 640x320）",
    )
    p.add_argument(
        "--out-width",
        type=int,
        default=None,
        help="输出宽（与 --out-height 同时指定则优先于 --scale，使用双线性插值）",
    )
    p.add_argument("--out-height", type=int, default=None)
    args = p.parse_args()
    ow, oh = args.out_width, args.out_height
    if (ow is None) ^ (oh is None):
        p.error("--out-width 与 --out-height 须同时指定或同时省略")
    main(args.input, args.output, args.width, args.height, args.scale, ow, oh)
