"""Render a screen's current state from its skin XML into a PNG (approximate preview)."""
import time
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

from Components.Label import Label
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_fonts = {}


def font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT, size)
    return _fonts[size]


def color(value, default=(0, 0, 0, 0)):
    if not value:
        return default
    v = value.lstrip("#")
    if len(v) == 6:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), 255)
    a = int(v[0:2], 16)
    return (int(v[2:4], 16), int(v[4:6], 16), int(v[6:8], 16), 255 - a)


def icolor(n):
    return ((n >> 16) & 255, (n >> 8) & 255, n & 255, 255)


def xy(text):
    a, b = text.split(",")
    return int(a), int(b)


def wrap(text, fnt, width, nowrap=False):
    lines = []
    for para in text.split("\n"):
        if nowrap:
            lines.append(para)
            continue
        cur = ""
        for word in para.split(" "):
            trial = (cur + " " + word).strip()
            if fnt.getlength(trial) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def draw_text(layer, box, text, size, fg, halign="left", valign="top", nowrap=False, shadow=None):
    if not text:
        return
    x, y, w, h = box
    fnt = font(size)
    lh = int(size * 1.22)
    lines = wrap(text, fnt, w, nowrap)
    max_lines = max(1, h // lh) if not nowrap else 1
    lines = lines[:max_lines]
    total = len(lines) * lh
    ty = y + (h - total) // 2 if valign == "center" else y
    clip = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(clip)
    for i, line in enumerate(lines):
        lw = fnt.getlength(line)
        lx = {"left": 0, "center": (w - lw) / 2, "right": w - lw}[halign]
        ly = ty - y + i * lh + (lh - size) // 2 - 2
        if shadow:
            d.text((lx + 2, ly + 2), line, font=fnt, fill=(0, 0, 0, 200))
        d.text((lx, ly), line, font=fnt, fill=fg)
    layer.alpha_composite(clip, (x, y))


def paste_png(layer, path, box, scale=False):
    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        return
    x, y, w, h = box
    if scale or im.size != (w, h):
        im = im.resize((w, h), Image.LANCZOS) if scale else im.crop((0, 0, w, h))
    layer.alpha_composite(im, (x, y))


def render(screen, out_path, video=None, size=(1920, 1080), backdrop=(0, 0, 0, 255)):
    root = ET.fromstring(screen.skin)
    sw, sh = xy(root.get("size"))
    pos = root.get("position")
    ox, oy = ((size[0] - sw) // 2, (size[1] - sh) // 2) if pos == "center,center" else xy(pos)
    canvas = Image.new("RGBA", size, backdrop)
    if video is not None:
        frame = Image.open(video).convert("RGBA").resize((size[1] * 9 // 16, size[1]), Image.LANCZOS)
        canvas.alpha_composite(frame, ((size[0] - frame.width) // 2, 0))
    win = Image.new("RGBA", (sw, sh), color(root.get("backgroundColor")))
    canvas.alpha_composite(win, (ox, oy))
    elements = [el for el in root if el.tag in ("widget", "eLabel", "ePixmap")]
    elements.sort(key=lambda el: int(el.get("zPosition", "0")))
    for el in elements:
        x, y = xy(el.get("position"))
        w, h = xy(el.get("size"))
        box = (ox + x, oy + y, w, h)
        fsize = int(el.get("font", "Regular;20").split(";")[1])
        halign = el.get("halign", "left")
        valign = el.get("valign", "top")
        transparent = el.get("transparent") == "1"
        fg = color(el.get("foregroundColor"), (255, 255, 255, 255))
        bg = color(el.get("backgroundColor"))
        shadow = el.get("shadowColor") is not None
        nowrap = el.get("noWrap") == "1"
        name = el.get("name")
        if el.tag == "eLabel":
            if not transparent and bg[3]:
                canvas.alpha_composite(Image.new("RGBA", (w, h), bg), box[:2])
            draw_text(canvas, box, el.get("text", ""), fsize, fg, halign, valign, nowrap, shadow)
            continue
        if el.get("source") == "global.CurrentTime":
            draw_text(canvas, box, time.strftime("%H:%M"), fsize, fg, halign, valign, True)
            continue
        comp = screen.get(name)
        if comp is None or not comp.visible:
            continue
        if comp.__class__.__name__ == "ScrollLabel":
            draw_text(canvas, box, comp.getText(), fsize, fg, halign, valign, False, shadow)
            continue
        if isinstance(comp, Label):
            moved = getattr(comp.instance, "moved_to", None) if comp.instance is not None else None
            if moved:
                box = (ox + moved[0], oy + moved[1], w, h)
            if not transparent and bg[3]:
                canvas.alpha_composite(Image.new("RGBA", (w, h), bg), box[:2])
            if comp.instance is not None and comp.instance.halign == 2:
                halign = "right"
            draw_text(canvas, box, comp.getText(), fsize, fg, halign, valign, nowrap, shadow)
        elif isinstance(comp, ProgressBar):
            canvas.alpha_composite(Image.new("RGBA", (w, h), bg), box[:2])
            fw = int(w * comp.value / 100)
            if fw:
                canvas.alpha_composite(Image.new("RGBA", (fw, h), fg), box[:2])
        elif isinstance(comp, Pixmap):
            ptr = comp.instance.pixmap if comp.instance is not None else None
            path = ptr[1] if ptr else el.get("pixmap")
            if path:
                paste_png(canvas, path, box, scale=el.get("scale") == "1")
        elif isinstance(comp, MenuList):
            render_list(canvas, comp, box, el)
    canvas.convert("RGB").save(out_path)


def render_list(canvas, comp, box, el):
    x0, y0, w, h = box
    ih = comp.l.item_height or 40
    sel_bg = color(el.get("backgroundColorSelected"))
    for i, entry in enumerate(comp.list):
        top = y0 + i * ih
        if top + ih > y0 + h:
            break
        if i == comp.index and sel_bg[3] and sel_bg != color(el.get("backgroundColor")):
            canvas.alpha_composite(Image.new("RGBA", (w, ih), sel_bg), (x0, top))
        for cell in entry[1:]:
            kind, kw = cell
            cx, cy = kw["pos"]
            cw, ch = kw["size"]
            if kind == "pix":
                paste_png(canvas, kw["png"][1], (x0 + cx, top + cy, cw, ch), scale=True)
                continue
            flags = kw["flags"]
            halign = "right" if flags & 2 else ("center" if flags & 4 else "left")
            valign = "center" if flags & 8 else "top"
            size = comp.l.fonts[kw["font"]][1]
            draw_text(canvas, (x0 + cx, top + cy, cw, ch), kw["text"], size, icolor(kw.get("color", 0xFFFFFF)),
                      halign, valign, nowrap=not flags & 32)
