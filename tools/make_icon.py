"""Draw the app icon (two photo cards being sorted) into assets/photoswipe.ico and .png.

Usage: python tools/make_icon.py
"""

import os

from PIL import Image, ImageDraw, ImageFilter

S = 1024  # drawn large, then scaled down for each icon size
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def gradient(size, top, bottom):
    im = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        im.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return im.resize(size)


def card(w, h, landscape):
    """A white-framed photo; the front one shows sky, sun and hills."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=w // 14, fill=(255, 255, 255, 255))
    m = w // 13
    inner = (m, m, w - m, h - m)
    if landscape:
        sky = gradient((inner[2] - inner[0], inner[3] - inner[1]), (125, 200, 255), (200, 235, 255))
        mask = Image.new("L", sky.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, *[v - 1 for v in sky.size]), radius=w // 22, fill=255)
        im.paste(sky, inner[:2], mask)
        iw, ih = sky.size
        x0, y0 = inner[:2]
        d.ellipse((x0 + iw * .62, y0 + ih * .14, x0 + iw * .86, y0 + ih * .14 + iw * .24), fill=(255, 200, 60))
        d.polygon([(x0, y0 + ih), (x0, y0 + ih * .62), (x0 + iw * .32, y0 + ih * .30),
                   (x0 + iw * .62, y0 + ih * .72), (x0 + iw * .62, y0 + ih)], fill=(46, 160, 110))
        d.polygon([(x0 + iw * .38, y0 + ih), (x0 + iw * .70, y0 + ih * .46),
                   (x0 + iw, y0 + ih * .78), (x0 + iw, y0 + ih)], fill=(30, 125, 90))
        # keep the photo's rounded corners at the bottom
        cut = Image.new("L", (w, h), 0)
        ImageDraw.Draw(cut).rounded_rectangle(inner, radius=w // 22, fill=255)
        frame = Image.new("L", (w, h), 0)
        ImageDraw.Draw(frame).rounded_rectangle((0, 0, w - 1, h - 1), radius=w // 14, fill=255)
        white = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        im = Image.composite(im, white, cut)
        im.putalpha(frame)
    else:
        d.rounded_rectangle(inner, radius=w // 22, fill=(214, 222, 240, 255))
    return im


def shadowed(layer, blur, alpha):
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sh.putalpha(layer.getchannel("A").point(lambda a: a * alpha // 255))
    return sh.filter(ImageFilter.GaussianBlur(blur))


def draw():
    bg = gradient((S, S), (88, 76, 220), (30, 150, 200)).convert("RGBA")
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((32, 32, S - 32, S - 32), radius=210, fill=255)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), mask)

    cw, ch = 560, 450
    for landscape, angle, dx, dy in ((False, 14, -70, -40), (True, -8, 40, 30)):
        c = card(cw, ch, landscape).rotate(angle, expand=True, resample=Image.BICUBIC)
        pos = ((S - c.width) // 2 + dx, (S - c.height) // 2 + dy)
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        layer.paste(c, pos, c)
        icon.alpha_composite(shadowed(layer, 18, 110), (0, 14))
        icon.alpha_composite(layer)

    # "sorted" badge: green circle with a white check mark
    d = ImageDraw.Draw(icon)
    cx, cy, r = 760, 745, 150
    badge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(badge).ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 255))
    icon.alpha_composite(shadowed(badge, 16, 90), (0, 10))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(34, 197, 94), outline=(255, 255, 255), width=22)
    d.line([(cx - 72, cy + 2), (cx - 18, cy + 58), (cx + 78, cy - 52)], fill=(255, 255, 255), width=44,
           joint="curve")
    for x, y in ((cx - 72, cy + 2), (cx + 78, cy - 52)):
        d.ellipse((x - 22, y - 22, x + 22, y + 22), fill=(255, 255, 255))
    return icon


def main():
    os.makedirs(OUT, exist_ok=True)
    icon = draw()
    icon.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "photoswipe.png"))
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    icon.save(os.path.join(OUT, "photoswipe.ico"), sizes=[(s, s) for s in sizes])
    print("assets/photoswipe.ico written")


if __name__ == "__main__":
    main()
