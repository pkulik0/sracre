import argparse
import os
from PIL import Image

ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "webp"]

def parse_args():
    parser = argparse.ArgumentParser(description="sracre")
    parser.add_argument("--text", type=str, default="text.txt")
    parser.add_argument("--images", type=str, default="input")
    parser.add_argument("--output", type=str, default="output.mp4")
    parser.add_argument("--fps", type=int, default=30)
    return parser.parse_args()


def load_data(text_file, images_dir):
    lines = []
    with open(text_file, "r") as f:
        lines_raw = f.readlines()
        for line in lines_raw:
            stripped = line.strip()
            if stripped:
                lines.append(stripped)

    images = []
    for i in range(len(lines)):
        was_found = False
        for ext in ALLOWED_EXTENSIONS:
            filename = os.path.join(images_dir, f"{i}.{ext}")
            if os.path.exists(filename):
                was_found = True
                images.append(Image.open(filename))
                break
        if not was_found:
            raise FileNotFoundError(f"Image {i} was not found")
    return lines, images


def main():
    args = parse_args()
    lines, images = load_data(args.text, args.images)
    print(lines)
    print(images)


if __name__ == "__main__":
    main()
