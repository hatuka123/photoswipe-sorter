"""Draw the small 'Loading...' picture shown while the single-file .exe unpacks itself."""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

out = sys.argv[1]
os.makedirs(os.path.dirname(out), exist_ok=True)
img = Image.new("RGB", (360, 120), (240, 240, 240))
d = ImageDraw.Draw(img)
d.rectangle((0, 0, 359, 119), outline=(160, 160, 160))
d.text((24, 28), "PhotoSwipe", fill=(0, 0, 0), font=ImageFont.load_default(size=32))
d.text((24, 76), "Loading...", fill=(90, 90, 90), font=ImageFont.load_default(size=18))
img.save(out)
