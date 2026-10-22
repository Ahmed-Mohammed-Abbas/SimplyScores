#!/usr/bin/env python3
"""Draw the plugin's PNG icons (FHD + HD sets and the plugin menu icons) with Pillow."""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SS = 8  # supersampling factor
RED = (254, 44, 85, 255)
CYAN = (37, 244, 238, 255)
WHITE = (255, 255, 255, 255)


def canvas(size):
    return Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))


def finish(img, size, shadow=True):
    small = img.resize((size, size), Image.LANCZOS)
    if not shadow:
        return small
    alpha = small.split()[3]
    sh = Image.new("RGBA", small.size, (0, 0, 0, 0))
    sh.putalpha(alpha.point(lambda a: int(a * 0.55)))
    sh = sh.filter(ImageFilter.GaussianBlur(max(1, size // 30)))
    out = Image.new("RGBA", small.size, (0, 0, 0, 0))
    out.alpha_composite(sh, (max(1, size // 40), max(1, size // 40)))
    out.alpha_composite(small)
    return out


def heart(size):
    img = canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    pts = []
    for i in range(240):
        t = 2 * math.pi * i / 240
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((S / 2 + x * S / 37, S * 0.46 - y * S / 37))
    d.polygon(pts, fill=WHITE)
    return finish(img, size)


def comment(size):
    img = canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    d.ellipse((S * 0.08, S * 0.12, S * 0.92, S * 0.80), fill=WHITE)
    d.polygon([(S * 0.24, S * 0.68), (S * 0.18, S * 0.93), (S * 0.46, S * 0.76)], fill=WHITE)
    r = S * 0.055
    for cx in (0.32, 0.50, 0.68):
        d.ellipse((S * cx - r, S * 0.46 - r, S * cx + r, S * 0.46 + r), fill=(0, 0, 0, 0))
    return finish(img, size)


def share(size):
    img = canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    w = S * 0.17
    p0, c, p1 = (0.12, 0.86), (0.16, 0.42), (0.58, 0.42)
    prev = None
    for i in range(41):
        t = i / 40.0
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1]
        pt = (x * S, y * S)
        if prev:
            d.line([prev, pt], fill=WHITE, width=int(w))
        d.ellipse((pt[0] - w / 2, pt[1] - w / 2, pt[0] + w / 2, pt[1] + w / 2), fill=WHITE)
        prev = pt
    d.polygon([(S * 0.94, S * 0.42), (S * 0.52, S * 0.10), (S * 0.52, S * 0.74)], fill=WHITE)
    return finish(img, size)


def views(size):
    img = canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    d.polygon([(S * 0.26, S * 0.16), (S * 0.86, S * 0.50), (S * 0.26, S * 0.84)], fill=WHITE)
    d.polygon([(S * 0.38, S * 0.36), (S * 0.62, S * 0.50), (S * 0.38, S * 0.64)], fill=(0, 0, 0, 0))
    return finish(img, size)


def follow(size):
    img = canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    d.ellipse((0, 0, S - 1, S - 1), fill=RED)
    t = S * 0.11
    d.rectangle((S / 2 - t / 2, S * 0.25, S / 2 + t / 2, S * 0.75), fill=WHITE)
    d.rectangle((S * 0.25, S / 2 - t / 2, S * 0.75, S / 2 + t / 2), fill=WHITE)
    return finish(img, size, shadow=False)


def disc(size):
    img = canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    d.ellipse((S * 0.04, S * 0.04, S * 0.96, S * 0.96), fill=(26, 26, 26, 255))
    for r in (0.40, 0.34, 0.28):
        d.ellipse((S * (0.5 - r), S * (0.5 - r), S * (0.5 + r), S * (0.5 + r)),
                  outline=(60, 60, 60, 255), width=int(S * 0.012))
    d.ellipse((S * 0.30, S * 0.30, S * 0.70, S * 0.70), fill=RED)
    d.pieslice((S * 0.30, S * 0.30, S * 0.70, S * 0.70), 200, 340, fill=CYAN)
    d.ellipse((S * 0.45, S * 0.45, S * 0.55, S * 0.55), fill=(26, 26, 26, 255))
    return finish(img, size)


def music(size):
    img = canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    d.ellipse((S * 0.08, S * 0.62, S * 0.40, S * 0.90), fill=WHITE)
    d.rectangle((S * 0.31, S * 0.10, S * 0.40, S * 0.76), fill=WHITE)
    d.polygon([(S * 0.31, S * 0.10), (S * 0.86, S * 0.22), (S * 0.86, S * 0.38), (S * 0.40, S * 0.27)],
              fill=WHITE)
    return finish(img, size)


def play_big(size):
    img = canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    d.polygon([(S * 0.26, S * 0.14), (S * 0.88, S * 0.50), (S * 0.26, S * 0.86)],
              fill=(255, 255, 255, 190))
    return finish(img, size)


def avatar(size):
    img = canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    d.ellipse((0, 0, S - 1, S - 1), fill=(58, 58, 58, 255))
    d.ellipse((S * 0.33, S * 0.18, S * 0.67, S * 0.52), fill=(150, 150, 150, 255))
    body = Image.new("L", img.size, 0)
    ImageDraw.Draw(body).ellipse((S * 0.16, S * 0.58, S * 0.84, S * 1.20), fill=255)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, S - 1, S - 1), fill=255)
    from PIL import ImageChops
    gray = Image.new("RGBA", img.size, (150, 150, 150, 255))
    img.paste(gray, (0, 0), ImageChops.multiply(body, mask))
    d = ImageDraw.Draw(img)
    d.ellipse((S * 0.02, S * 0.02, S * 0.98, S * 0.98), outline=WHITE, width=int(S * 0.04))
    return finish(img, size, shadow=False)


# --------------------------------------------------------------------------- plugin menu icon
# An original football in the TikTok look: black tile, white ball with cyan and
# pink offset copies ("glitch"), speed streaks and the SimplyScores wordmark.
# No TikTok logo or wordmark is used, only the colour scheme and the offset effect.
INK = (8, 8, 8, 255)
FONT_DIRS = ("/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/google-fonts",
             "/usr/share/fonts/truetype/dejavu")


def _font(names, size):
    for folder in FONT_DIRS:
        for name in names:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _polygon(cx, cy, r, start_deg, n=5):
    return [(cx + r * math.cos(math.radians(start_deg + 360.0 * k / n)),
             cy + r * math.sin(math.radians(start_deg + 360.0 * k / n))) for k in range(n)]


def ball_layer(size, cx, cy, R, body=WHITE, ink=INK, centre_r=0.34, rim_d=0.95, rim_r=0.28,
               seam_w=0.06, ring=0.88):
    """A football: a centre pentagon, five seams and five pentagons cut by the rim.
    The patches stop short of the edge so a white ring keeps the ball round on black."""
    from PIL import ImageChops
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((cx - R, cy - R, cx + R, cy + R), fill=body)
    patches = Image.new("RGBA", size, (0, 0, 0, 0))
    p = ImageDraw.Draw(patches)
    centre = _polygon(cx, cy, R * centre_r, -90)
    p.polygon(centre, fill=ink)
    seam = max(1, int(round(R * seam_w)))
    outer = []
    for k in range(5):
        ang = math.radians(-90 + 72 * k)
        ox, oy = cx + R * rim_d * math.cos(ang), cy + R * rim_d * math.sin(ang)
        pent = _polygon(ox, oy, R * rim_r, -90 + 72 * k + 180)
        outer.append(pent)
        p.polygon(pent, fill=ink)
        p.line([centre[k], pent[0]], fill=ink, width=seam)
    for k in range(5):
        a, b = outer[k], outer[(k + 1) % 5]
        pa = min(a, key=lambda v: min(math.hypot(v[0] - w[0], v[1] - w[1]) for w in b))
        pb = min(b, key=lambda v: math.hypot(v[0] - pa[0], v[1] - pa[1]))
        mx, my = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
        p.line([pa, (mx, my), pb], fill=ink, width=seam)
        dx, dy = mx - cx, my - cy
        n = math.hypot(dx, dy) or 1
        p.line([(mx, my), (cx + dx / n * R * 1.1, cy + dy / n * R * 1.1)], fill=ink, width=seam)
    clip = Image.new("L", size, 0)
    rr = R * ring
    ImageDraw.Draw(clip).ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=255)
    patches.putalpha(ImageChops.multiply(patches.split()[3], clip))
    layer.alpha_composite(patches)
    return layer


def _tinted(layer, color, alpha=1.0):
    out = Image.new("RGBA", layer.size, color)
    out.putalpha(layer.split()[3].point(lambda a: int(a * alpha)))
    return out


def glitch(base, layer, offset):
    """Paste a white shape with a cyan copy up-left and a pink copy down-right."""
    o = int(round(offset))
    base.alpha_composite(_tinted(layer, CYAN), (-o, -o))
    base.alpha_composite(_tinted(layer, RED), (o, o))
    base.alpha_composite(layer)


def text_layer(size, xy, text, font, fill=WHITE):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=font, fill=fill)
    return layer


def brand_icon(W, H):
    """Plugin icon at W x H (100x40 for HD skins, 150x60 for FHD skins)."""
    k = W / 100.0 * SS                      # design units are HD pixels
    size = (int(W * SS), int(H * SS))
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=6 * k, fill=(0, 0, 0, 255))
    # speed streaks behind the ball
    streaks = Image.new("RGBA", size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(streaks)
    for y, x0, col in ((13.0, 3.5, CYAN), (20.0, 1.5, WHITE), (27.0, 3.5, RED)):
        sd.rounded_rectangle((x0 * k, (y - 1.1) * k, 17 * k, (y + 1.1) * k), radius=1.1 * k, fill=col)
    img.alpha_composite(streaks)
    cx, cy, R = 24.5 * k, 20 * k, 13.6 * k
    ball = ball_layer(size, cx, cy, R)
    glitch(img, ball, 1.25 * k)
    # wordmark
    small = _font(("InterDisplay-SemiBold.otf", "Poppins-Medium.ttf", "DejaVuSans.ttf"), int(9.5 * k))
    big = _font(("InterDisplay-Black.otf", "Poppins-Bold.ttf", "DejaVuSans-Bold.ttf"), int(15.5 * k))
    x = 43.5 * k
    img.alpha_composite(text_layer(size, (x + 0.4 * k, 4.6 * k), "Simply", small, (225, 225, 225, 255)))
    glitch(img, text_layer(size, (x, 15.0 * k), "Scores", big), 0.75 * k)
    return img.resize((W, H), Image.LANCZOS)


def plugin_icon(path, W=100, H=40):
    brand_icon(W, H).save(path)


def nav_key(direction):
    """A remote-control arrow key: dark key cap with a white arrow."""
    def draw(size):
        img = canvas(size)
        d = ImageDraw.Draw(img)
        S = size * SS
        d.rounded_rectangle((S * 0.04, S * 0.04, S * 0.96, S * 0.96), radius=S * 0.22,
                            fill=(52, 52, 52, 255), outline=(120, 120, 120, 255), width=int(S * 0.04))
        tri = [(0.50, 0.26), (0.76, 0.64), (0.24, 0.64)]          # pointing up
        turn = {"up": 0, "right": 90, "down": 180, "left": 270}[direction]
        a = math.radians(turn)
        pts = []
        for x, y in tri:
            x, y = x - 0.5, y - 0.5
            pts.append((S * (0.5 + x * math.cos(a) - y * math.sin(a)),
                        S * (0.5 + x * math.sin(a) + y * math.cos(a))))
        d.polygon(pts, fill=WHITE)
        return finish(img, size, shadow=False)
    return draw


ICONS = {
    "nav_up": (nav_key("up"), 40), "nav_down": (nav_key("down"), 40),
    "nav_left": (nav_key("left"), 40), "nav_right": (nav_key("right"), 40),
    "like": (heart, 60), "comment": (comment, 60), "share": (share, 60), "views": (views, 60),
    "follow": (follow, 36), "disc": (disc, 70), "music": (music, 30), "play_big": (play_big, 120),
    "avatar": (avatar, 100),
}


def main(plugin_dir):
    for res, scale in (("fhd", 1.0), ("hd", 2.0 / 3.0)):
        out = os.path.join(plugin_dir, "icons", res)
        os.makedirs(out, exist_ok=True)
        for name, (fn, size) in ICONS.items():
            fn(int(round(size * scale))).save(os.path.join(out, name + ".png"))
    plugin_icon(os.path.join(plugin_dir, "plugin.png"), 100, 40)        # HD skins
    plugin_icon(os.path.join(plugin_dir, "plugin_fhd.png"), 150, 60)    # FHD skins


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "SimplyScores")
