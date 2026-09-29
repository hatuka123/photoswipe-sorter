"""Create a messy nested folder of numbered dummy photos for testing.

Usage: python tests/make_test_images.py <folder> [count]
"""

import os
import random
import sys

from PIL import Image, ImageDraw, ImageFont

FORMATS = [("jpg", "JPEG"), ("png", "PNG"), ("webp", "WEBP"), ("gif", "GIF"),
           ("bmp", "BMP"), ("tif", "TIFF"), ("heic", "HEIF")]


def make(root, count=240, seed=1):
    import pillow_heif
    pillow_heif.register_heif_opener()
    rnd = random.Random(seed)
    font = ImageFont.load_default(size=120)
    subdirs = ["", "2019", "2019/summer", "2019/summer/beach", "phone/WhatsApp Images",
               "phone/DCIM/Camera", "misc/תמונות"]  # includes a Hebrew folder name
    made = []
    for i in range(count):
        ext, fmt = FORMATS[i % len(FORMATS)]
        big = i % 25 == 0
        size = (6000, 4000) if big else (rnd.randint(400, 2400), rnd.randint(300, 1800))
        img = Image.new("RGB", size, tuple(rnd.randint(0, 255) for _ in range(3)))
        ImageDraw.Draw(img).text((20, 20), f"#{i}", fill="white", font=font, stroke_width=4, stroke_fill="black")
        folder = os.path.join(root, subdirs[i % len(subdirs)])
        os.makedirs(folder, exist_ok=True)
        # Same names in different folders on purpose (IMG_0001.jpg everywhere).
        path = os.path.join(folder, f"IMG_{i // len(subdirs):04d}_{i}.{ext}")
        kwargs = {}
        if fmt == "JPEG" and i % 3 == 0:
            exif = Image.Exif()
            exif[0x0112] = 6  # "rotate 90" orientation tag
            kwargs["exif"] = exif
        img.save(path, fmt, **kwargs)
        made.append(path)
    with open(os.path.join(root, "broken.jpg"), "wb") as f:
        f.write(b"this is not an image")
    with open(os.path.join(root, "notes.txt"), "w") as f:
        f.write("not a photo")
    return made


if __name__ == "__main__":
    out = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 240
    print(len(make(out, n)), "images created in", out)
