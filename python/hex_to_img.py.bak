"""
将仿真输出的单通道 HEX（每行 1~2 个十六进制字节）还原为灰度图。
用法:
  python hex_to_img.py -i ../image_out.txt -o result_post.jpg
"""
import argparse
import cv2
import numpy as np
import os


def generate_image_from_hex(input_txt_path, output_img_path, target_width=200, target_height=100):
    if not os.path.exists(input_txt_path):
        print(f"[!] Missing: {input_txt_path}")
        return False

    with open(input_txt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    hex_data = [line.strip() for line in lines if line.strip()]

    expected = target_width * target_height
    print(f"[*] Expected pixels: {expected}, got: {len(hex_data)}")
    if len(hex_data) < expected:
        hex_data.extend(["00"] * (expected - len(hex_data)))
    elif len(hex_data) > expected:
        hex_data = hex_data[:expected]

    pixel_list = [int(val, 16) for val in hex_data]
    img_array = np.array(pixel_list, dtype=np.uint8).reshape((target_height, target_width))
    cv2.imwrite(output_img_path, img_array)
    print(f"[+] Saved: {output_img_path}")
    return True


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="image_out.txt")
    p.add_argument("-o", "--output", default="result_post.jpg")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    args = p.parse_args()
    ok = generate_image_from_hex(args.input, args.output, args.width, args.height)
    exit(0 if ok else 1)
