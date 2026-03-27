"""
将仿真输出的 OSD 全彩 HEX（每行 rrggbb）还原为 JPG。
用法:
  python show_box.py -i ../image_out_rgb.txt -o result_osd.jpg
"""
import argparse
import numpy as np
import cv2


def main(input_txt, output_img, width=200, height=100):
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

    if len(pixels) < width * height:
        print(f"[!] Only {len(pixels)} pixels, padding with black")
        while len(pixels) < width * height:
            pixels.append([0, 0, 0])
    elif len(pixels) > width * height:
        pixels = pixels[: width * height]

    img = np.array(pixels, dtype=np.uint8).reshape((height, width, 3))
    cv2.imwrite(output_img, img)
    print(f"[+] OSD image: {output_img}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="image_out_rgb.txt")
    p.add_argument("-o", "--output", default="result_osd.jpg")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    args = p.parse_args()
    main(args.input, args.output, args.width, args.height)
