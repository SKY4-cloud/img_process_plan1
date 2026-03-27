"""
将 image_out_roi.txt（每行 rrggbb）还原为 BGR 图，尺寸默认 ROI_OUT_W x ROI_OUT_H（须与 tb 一致）。
用法:
  python roi_hex_to_img.py -i image_out_roi.txt -o result_roi.jpg --width 64 --height 32
"""
import argparse
import numpy as np
import cv2


def main(input_txt, output_img, width, height):
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
    cv2.imwrite(output_img, img)
    print(f"[+] ROI image: {output_img}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="image_out_roi.txt")
    p.add_argument("-o", "--output", default="result_roi.jpg")
    p.add_argument("--width", type=int, default=64)
    p.add_argument("--height", type=int, default=32)
    args = p.parse_args()
    main(args.input, args.output, args.width, args.height)
