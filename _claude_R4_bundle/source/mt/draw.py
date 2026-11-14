"""mt.draw - moved from montage.py by tools/mt_move.py"""
from mt.fonts import has_arabic, load_font, shape, wrap_lines
from mt.common import T2_ACCENT, _warn
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter
from pathlib import Path
import os
import math
from mt.common import AR_DIGITS, T2_ACCENT, _t2_frac, _t2_num_or_none, clean_path
from mt.anim import ANIMS
from PIL import Image, ImageDraw, ImageFilter


def resolve_pos(pos, sw, sh, W, H):
    """Return the sprite CENTER (cx, cy) on the canvas."""
    if isinstance(pos, (list, tuple)):
        def one(v, total):
            v = str(v)
            return float(v[:-1]) / 100.0 * total if v.endswith("%") else float(v)
        return one(pos[0], W), one(pos[1], H)
    mx, my = 0.05 * W, 0.04 * H
    name = pos or "center"
    cx = W / 2
    cy = H / 2
    if "left" in name:
        cx = mx + sw / 2
    elif "right" in name:
        cx = W - mx - sw / 2
    if name.startswith("top"):
        cy = my + sh / 2
    elif name.startswith("bottom"):
        cy = H - my - sh / 2
    return cx, cy


def make_text_sprite(text, font_path, size, fill, stroke_fill=None, stroke_w=0, max_w=10 ** 6):
    stroke_w = int(stroke_w or 0)
    if stroke_w and not stroke_fill:
        stroke_fill = "#000000"
    avail = max_w - 2 * (stroke_w + 6)
    while True:
        font = load_font(font_path, int(size))
        lines = wrap_lines(text, font, avail)
        shaped = [shape(l) for l in lines]
        widths = [font.getlength(s) for s in shaped]
        if max(widths) <= avail or size <= 14:
            break
        size = max(14, int(size * 0.92))
    asc, desc = font.getmetrics()
    lh = asc + desc
    gap = int(size * 0.18)
    pad = stroke_w + int(size * 0.18) + 3
    w = int(max(widths)) + 2 * pad
    h = len(lines) * lh + (len(lines) - 1) * gap + 2 * pad
    img = Image.new("RGBA", (max(w, 4), max(h, 4)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, s in enumerate(shaped):
        y = pad + asc + i * (lh + gap)
        d.text((w / 2, y), s, font=font, fill=fill, anchor="ms",
               stroke_width=stroke_w, stroke_fill=stroke_fill)
    return img


def load_image_sprite(path, width_spec, W):
    im = Image.open(path)
    try:
        im.seek(0)
    except Exception:
        pass
    im = im.convert("RGBA")
    if width_spec:
        ws = str(width_spec).strip()
        if ws.endswith("%"):
            tw = int(float(ws[:-1]) / 100.0 * W)
        else:
            tw = int(float(ws))
        tw = max(2, tw)
        th = max(2, int(round(im.height * tw / im.width)))
        im = im.resize((tw, th), Image.LANCZOS)
    return im


# ----------------------------------------------------------------------------
# HUD cards (icon + two lines, glowing border) - like WEB DEVELOPER / AI AUTOMATION
# ----------------------------------------------------------------------------
CYAN = (30, 170, 255)


CYAN_TXT = (0, 184, 255)


def _draw_icon(img, kind, box, path=None):
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    s = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    wid = max(2, int(s * 0.09))
    white = (255, 255, 255, 255)
    if kind == "code":
        a = s * 0.30
        d.line([(cx - a * 0.55, cy - a * 0.9), (cx - a * 1.45, cy), (cx - a * 0.55, cy + a * 0.9)],
               fill=white, width=wid, joint="curve")
        d.line([(cx + a * 0.55, cy - a * 0.9), (cx + a * 1.45, cy), (cx + a * 0.55, cy + a * 0.9)],
               fill=white, width=wid, joint="curve")
        d.line([(cx + a * 0.25, cy - a * 1.0), (cx - a * 0.25, cy + a * 1.0)], fill=white, width=wid)
    elif kind == "phone":
        d.rounded_rectangle((cx - s * 0.22, y0 + s * 0.02, cx + s * 0.22, y1 - s * 0.02),
                            radius=s * 0.08, outline=white, width=wid)
        d.line([(cx - s * 0.07, y0 + s * 0.12), (cx + s * 0.07, y0 + s * 0.12)], fill=white, width=max(2, wid // 2))
        r = s * 0.035
        d.ellipse((cx - r, y1 - s * 0.14 - r, cx + r, y1 - s * 0.14 + r), fill=white)
    elif kind == "chip":
        q = s * 0.20
        d.rounded_rectangle((cx - q, cy - q, cx + q, cy + q), radius=s * 0.04, outline=white, width=wid)
        r = s * 0.09
        d.rectangle((cx - r, cy - r, cx + r, cy + r), fill=white)
        for off in (-0.11, 0.0, 0.11):
            d.line([(cx + s * off, cy - q), (cx + s * off, cy - q - s * 0.12)], fill=white, width=max(2, wid // 2))
            d.line([(cx + s * off, cy + q), (cx + s * off, cy + q + s * 0.12)], fill=white, width=max(2, wid // 2))
            d.line([(cx - q, cy + s * off), (cx - q - s * 0.12, cy + s * off)], fill=white, width=max(2, wid // 2))
            d.line([(cx + q, cy + s * off), (cx + q + s * 0.12, cy + s * off)], fill=white, width=max(2, wid // 2))
    elif kind == "globe":                       # T3-6
        r = s * 0.40
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=white, width=wid)
        d.ellipse((cx - r * 0.45, cy - r, cx + r * 0.45, cy + r), outline=white, width=max(2, wid * 2 // 3))
        d.line([(cx - r, cy), (cx + r, cy)], fill=white, width=max(2, wid * 2 // 3))
        d.line([(cx, cy - r), (cx, cy + r)], fill=white, width=max(2, wid * 2 // 3))
    elif kind == "cloud":
        yb = cy + s * 0.20
        d.line([(cx - s * 0.30, yb), (cx + s * 0.32, yb)], fill=white, width=wid)
        d.arc((cx - s * 0.42, cy - s * 0.08, cx - s * 0.18, yb), 90, 270, fill=white, width=wid)
        d.arc((cx - s * 0.28, cy - s * 0.34, cx + s * 0.10, cy + s * 0.04), 180, 340, fill=white, width=wid)
        d.arc((cx - s * 0.02, cy - s * 0.22, cx + s * 0.30, cy + s * 0.10), 200, 360, fill=white, width=wid)
        d.arc((cx + s * 0.14, cy - s * 0.08, cx + s * 0.42, yb), 270, 90, fill=white, width=wid)
    elif kind == "shield":
        pts = [(cx - s * 0.30, cy - s * 0.30), (cx, cy - s * 0.42), (cx + s * 0.30, cy - s * 0.30), (cx + s * 0.28, cy + s * 0.06),
               (cx, cy + s * 0.42), (cx - s * 0.28, cy + s * 0.06)]
        d.line(pts + [pts[0]], fill=white, width=wid, joint="curve")
        d.line([(cx - s * 0.12, cy), (cx - s * 0.03, cy + s * 0.10), (cx + s * 0.14, cy - s * 0.10)], fill=white, width=wid,
               joint="curve")
    elif kind == "image" and path:
        try:
            ic = Image.open(path).convert("RGBA")
            ic.thumbnail((int(s), int(s)), Image.LANCZOS)
            img.alpha_composite(ic, (int(cx - ic.width / 2), int(cy - ic.height / 2)))
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Procedural "Tech HUD" background (dark blue, glowing frame, floor grid, divider)
# ----------------------------------------------------------------------------
def _chamfer(x0, y0, x1, y1, c):
    return [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c), (x1 - c, y1), (x0 + c, y1),
            (x0, y1 - c), (x0, y0 + c)]


# ----------------------------------------------------------------------------
# Timeline items
# ----------------------------------------------------------------------------
class Item:
    __slots__ = ("sprite", "start", "end", "cx", "cy", "anim", "dur", "out", "opacity", "rtl")

    def __init__(self, sprite, start, end, cx, cy, anim="fade", dur=0.5, out=True, opacity=1.0, rtl=False):
        self.sprite, self.start, self.end = sprite, start, end
        self.cx, self.cy = cx, cy
        self.anim, self.dur, self.out = anim, dur, out
        self.opacity, self.rtl = opacity, rtl

    def progress(self, t):
        L = self.end - self.start
        d = min(self.dur, L / 2 if self.out else L)
        if d <= 1e-6 or self.anim in (None, "none"):
            return 1.0
        pin = (t - self.start) / d
        if self.out:
            return max(0.0, min(1.0, pin, (self.end - t) / d))
        return max(0.0, min(1.0, pin))


def _paste(canvas, spr, x, y):
    W, H = canvas.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + spr.width), min(H, y + spr.height)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + spr.width, y + spr.height):
        spr = spr.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    canvas.alpha_composite(spr, (x0, y0))


def draw_item(canvas, it, st):
    alpha, dx, dy, scale, rot, reveal = st
    alpha *= it.opacity
    if alpha < 0.004:
        return
    spr = it.sprite
    ox = 0
    if reveal is not None and reveal < 1:
        w = spr.width
        cw = max(1, int(w * reveal))
        if it.rtl:
            spr = spr.crop((w - cw, 0, w, spr.height))
            ox = w - cw
        else:
            spr = spr.crop((0, 0, cw, spr.height))
    base_w, base_h = it.sprite.width, it.sprite.height
    if abs(scale - 1.0) > 1e-3:
        spr = spr.resize((max(1, int(spr.width * scale)), max(1, int(spr.height * scale))), Image.BICUBIC)
        ox = int(ox * scale)
        base_w, base_h = base_w * scale, base_h * scale
    if abs(rot) > 0.05:
        spr = spr.rotate(rot, resample=Image.BICUBIC, expand=True)
    if alpha < 0.996:
        lut = [int(i * alpha) for i in range(256)]
        a = spr.getchannel("A").point(lut)
        spr = spr.copy()
        spr.putalpha(a)
    if rot and abs(rot) > 0.05:
        x = int(it.cx + dx - spr.width / 2)
        y = int(it.cy + dy - spr.height / 2)
    else:
        x = int(it.cx + dx - base_w / 2 + ox)
        y = int(it.cy + dy - base_h / 2)
    _paste(canvas, spr, x, y)


def _img_ok(path, what):
    try:
        if path and os.path.isfile(str(path)):
            with Image.open(str(path)) as im:
                im.verify()
            return True
    except Exception:
        pass
    _warn(f"{what} image '{Path(str(path)).name if path else '(empty path)'}' is missing or not a valid image - skipped")
    return False


T2_SS = 4                                      # supersampling factor of every shape / text mask


# ---- config ---------------------------------------------------------------------------
def t2_rgb(c):
    """'#rrggbb' / name / (r,g,b[,a]) -> (r,g,b). Unknown values fall back to the poster lime."""
    if isinstance(c, (tuple, list)):
        return tuple(int(v) for v in c[:3])
    try:
        return tuple(ImageColor.getrgb(str(c))[:3])
    except ValueError:
        return tuple(ImageColor.getrgb(T2_ACCENT)[:3])


def t2_mix(a, b, f):
    return tuple(int(round(a[i] + (b[i] - a[i]) * f)) for i in range(3))


def t2_lighten(c, f):
    return t2_mix(c, (255, 255, 255), f)


def t2_darken(c, f):
    return t2_mix(c, (0, 0, 0), f)


def t2_size_for_cap(font_path, cap_px):
    """Font size (px) whose capital letters are `cap_px` tall."""
    try:
        f = load_font(font_path, 200)
        bb = f.getbbox("H")
        r = (bb[3] - bb[1]) / 200.0
    except Exception:
        r = 0.7
    return cap_px / (r if r > 0.2 else 0.7)


# ---- masks / paint helpers (reusable) ---------------------------------------------------
# A "mask" is a tuple (L image, (ox, oy)): an anti-aliased coverage mask placed at canvas pos (ox, oy).
def t2_draw_mask(bbox, draw_fn, ss=T2_SS, pad=3, post=None):
    """Generic 4x-supersampled mask. draw_fn(draw, L, ss): L(x, y) maps canvas px to the big mask's px."""
    x0, y0, x1, y1 = bbox
    ox, oy = int(math.floor(x0)) - pad, int(math.floor(y0)) - pad
    w, h = int(math.ceil(x1)) + pad - ox, int(math.ceil(y1)) + pad - oy
    m = Image.new("L", (max(1, w) * ss, max(1, h) * ss), 0)
    draw_fn(ImageDraw.Draw(m), lambda x, y: ((x - ox) * ss, (y - oy) * ss), ss)
    if post:
        m = post(m)
    return m.resize((max(1, w), max(1, h)), Image.LANCZOS), (ox, oy)


def t2_rrect_mask(box, radius, ss=T2_SS):
    """Rounded rectangle (x0, y0, x1, y1) - float coordinates allowed, clean anti-aliased corners."""
    x0, y0, x1, y1 = box

    def fn(d, L, s):
        a, b = L(x0, y0), L(x1, y1)
        d.rounded_rectangle((a[0], a[1], b[0] - 1, b[1] - 1), radius=max(0.0, radius) * s, fill=255)
    return t2_draw_mask(box, fn, ss, pad=2)


def t2_poly_mask(pts, round_r=0.0, ss=T2_SS):
    """Polygon mask; round_r > 0 rounds the corners (blur + threshold at 4x)."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]

    def fn(d, L, s):
        d.polygon([L(x, y) for x, y in pts], fill=255)
    post = None
    if round_r > 0:
        def post(m):
            return m.filter(ImageFilter.GaussianBlur(round_r * ss * 0.6)).point(lambda v: 255 if v >= 128 else 0)
    return t2_draw_mask((min(xs), min(ys), max(xs), max(ys)), fn, ss, pad=int(round_r) + 3, post=post)


def t2_polys_mask(polys, ss=T2_SS):
    """Several polygons in one mask (hatch stripes...)."""
    xs = [p[0] for pl in polys for p in pl]
    ys = [p[1] for pl in polys for p in pl]

    def fn(d, L, s):
        for pl in polys:
            d.polygon([L(x, y) for x, y in pl], fill=255)
    return t2_draw_mask((min(xs), min(ys), max(xs), max(ys)), fn, ss)


def t2_line_mask(pts, width, caps=True, ss=T2_SS):
    """Poly-line with round joints (and round caps)."""
    hw = width / 2.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]

    def fn(d, L, s):
        P = [L(x, y) for x, y in pts]
        d.line(P, fill=255, width=max(1, int(round(width * s))), joint="curve")
        if caps:
            for x, y in P:
                d.ellipse((x - hw * s, y - hw * s, x + hw * s, y + hw * s), fill=255)
    return t2_draw_mask((min(xs) - hw, min(ys) - hw, max(xs) + hw, max(ys) + hw), fn, ss)


def t2_dots_mask(x0, y0, cols, rows, pitch_x, pitch_y, r, ss=T2_SS):
    def fn(d, L, s):
        for i in range(cols):
            for j in range(rows):
                cx, cy = L(x0 + i * pitch_x, y0 + j * pitch_y)
                d.ellipse((cx - r * s, cy - r * s, cx + r * s, cy + r * s), fill=255)
    return t2_draw_mask((x0 - r, y0 - r, x0 + (cols - 1) * pitch_x + r, y0 + (rows - 1) * pitch_y + r), fn, ss)


def t2_mask_sub(a, b):
    """a minus b (result lives in a's frame)."""
    am, (ax, ay) = a
    bm, (bx, by) = b
    layer = Image.new("L", am.size, 0)
    layer.paste(bm, (bx - ax, by - ay))
    return ImageChops.subtract(am, layer), (ax, ay)


def t2_mask_full(mask, size):
    """Mask -> full-canvas 'L' image."""
    m, (ox, oy) = mask
    full = Image.new("L", size, 0)
    full.paste(m, (ox, oy))
    return full


def t2_place(m, x, cy=None, y=None, right=None):
    """Put a 1x mask on the canvas: left edge x (or right edge `right`), vertically centred on cy (or top y)."""
    ox = int(round(right - m.width)) if right is not None else int(round(x))
    oy = int(round(cy - m.height / 2.0)) if cy is not None else int(round(y))
    return m, (ox, oy)


def t2_ramp(stops, n=1024):
    """stops [(pos 0..1, (r,g,b[,a]))...] -> RGBA image n x 2 (two identical rows)."""
    st = sorted(((float(p), tuple(c) if len(c) == 4 else tuple(c) + (255,)) for p, c in stops), key=lambda s: s[0])
    px = []
    for i in range(n):
        t = i / float(n - 1)
        if t <= st[0][0]:
            col = st[0][1]
        elif t >= st[-1][0]:
            col = st[-1][1]
        else:
            col = st[-1][1]
            for (p0, c0), (p1, c1) in zip(st, st[1:]):
                if p0 <= t <= p1:
                    f = (t - p0) / (p1 - p0) if p1 > p0 else 0.0
                    col = tuple(int(round(c0[j] + (c1[j] - c0[j]) * f)) for j in range(4))
                    break
        px.append(col)
    im = Image.new("RGBA", (n, 2))
    im.putdata(px + px)
    return im


def t2_gradient(size, stops, angle=90.0, box=None):
    """Linear gradient image (RGBA). angle: 0 = left->right, 90 = top->bottom, 135 = top-right->bottom-left.
    box = (x0, y0, x1, y1): the area the 0..1 range spans (default: the whole image)."""
    w, h = size
    x0, y0, x1, y1 = box or (0, 0, w, h)
    n = 1024
    ramp = t2_ramp(stops, n)
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    proj = [x * dx + y * dy for x in (x0, x1) for y in (y0, y1)]
    lo, span = min(proj), max(max(proj) - min(proj), 1e-6)
    s = (n - 1) / span
    return ramp.transform((w, h), Image.AFFINE, (dx * s, dy * s, 0.5 - lo * s, 0, 0, 1.0), resample=Image.BILINEAR)


def t2_grad(stops, angle=90.0, box=None):
    """Callable fill for t2_paint: a gradient defined in CANVAS coordinates (box) - or the mask's bounds."""
    def f(size, off):
        b = None if box is None else (box[0] - off[0], box[1] - off[1], box[2] - off[0], box[3] - off[1])
        return t2_gradient(size, stops, angle, b)
    return f


def _t2_alpha_paste(base, layer, ox, oy):
    W, H = base.size
    w, h = layer.size
    sx, sy = max(0, -ox), max(0, -oy)
    ex, ey = min(w, W - ox), min(h, H - oy)
    if ex > sx and ey > sy:
        base.alpha_composite(layer.crop((sx, sy, ex, ey)), (ox + sx, oy + sy))


def t2_paint(base, mask, fill, opacity=1.0):
    """Paint `fill` through `mask` onto the RGBA `base` (in place).
    fill = (r,g,b[,a]) | RGBA image of the mask's size | callable(size, (ox, oy)) -> RGBA image.
    Returns the tight canvas bbox of what was painted (or None)."""
    m, (ox, oy) = mask
    if callable(fill):
        col = fill(m.size, (ox, oy))
    elif isinstance(fill, Image.Image):
        col = fill.convert("RGBA")
    else:
        c = tuple(fill)
        col = Image.new("RGBA", m.size, (c[0], c[1], c[2], c[3] if len(c) > 3 else 255))
    a = ImageChops.multiply(m, col.getchannel("A"))
    if opacity < 1.0:
        a = a.point(lambda v: int(v * opacity + 0.5))
    col = col.copy()
    col.putalpha(a)
    _t2_alpha_paste(base, col, ox, oy)
    bb = m.point(lambda v: 255 if v > 8 else 0).getbbox()
    return None if not bb else (ox + bb[0], oy + bb[1], ox + bb[2], oy + bb[3])


def t2_glow(mask, radius, strength=1.0):
    """Soft glow mask around a mask (paint it with the glow colour)."""
    m, (ox, oy) = mask
    pad = int(radius * 3) + 2
    big = Image.new("L", (m.width + 2 * pad, m.height + 2 * pad), 0)
    big.paste(m, (pad, pad))
    big = big.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, int(v * strength)))
    return big, (ox - pad, oy - pad)


# ---- text -----------------------------------------------------------------------------
def t2_shear_mask(m, k):
    """Fake italic: lean the top of the glyphs to the right by tan = k (works on 'L' / RGBA images)."""
    w, h = m.size
    extra = int(math.ceil(abs(k) * h)) + 1
    return m.transform((w + extra, h), Image.AFFINE, (1, k, -k * h, 0, 1, 0), resample=Image.BICUBIC)


def t2_text_mask(text, font_path, size, tracking_em=0.0, shear=0.0, ss=T2_SS):
    """Ink-cropped 1x 'L' mask of one line of text (4x supersampled). Arabic is shaped as a whole;
    letter-spacing (tracking) and fake italic only apply to Latin text."""
    S = max(4, int(round(size * ss)))
    font = load_font(font_path, S)
    s = shape(text)
    arabic = has_arabic(text)
    tr = 0.0 if arabic else tracking_em * S
    asc, desc = font.getmetrics()
    total = font.getlength(s) + tr * max(0, len(s) - 1)
    pad = int(S * 0.3) + 4
    m = Image.new("L", (int(total) + 2 * pad + 8, asc + desc + 2 * pad), 0)
    d = ImageDraw.Draw(m)
    if tr:
        for i, ch in enumerate(s):
            if ch != " ":
                d.text((pad + font.getlength(s[:i]) + tr * i, pad + asc), ch, font=font, fill=255, anchor="ls")
    else:
        d.text((pad, pad + asc), s, font=font, fill=255, anchor="ls")
    bb = m.getbbox()
    if not bb:
        return Image.new("L", (1, 1), 0)
    m = m.crop(bb)
    if shear and not arabic:
        m = t2_shear_mask(m, shear)
        m = m.crop(m.getbbox() or (0, 0, 1, 1))
    w, h = m.size
    w2, h2 = -(-w // ss) * ss, -(-h // ss) * ss
    if (w2, h2) != (w, h):
        n = Image.new("L", (w2, h2), 0)
        n.paste(m, (0, 0))
        m = n
    return m.resize((w2 // ss, h2 // ss), Image.LANCZOS)


def t2_fit_text(text, font_path, max_w, cap_px, tracking_em=0.0, shear=0.0, min_scale=0.4):
    """Auto-fit: shrink the font until the ink fits max_w (never below min_scale); as a last resort the text
    is cut and '...' added. Returns (mask, shown_text, font_size)."""
    size0 = t2_size_for_cap(font_path, cap_px)
    size = size0
    m = t2_text_mask(text, font_path, size, tracking_em, shear)
    for _ in range(6):
        if m.width <= max_w:
            return m, text, size
        size = max(size0 * min_scale, size * max_w / float(m.width) * 0.99)
        m = t2_text_mask(text, font_path, size, tracking_em, shear)
        if size <= size0 * min_scale + 1e-6:
            break
    t = text
    while m.width > max_w and len(t) > 1:
        t = t[:-max(1, len(t) // 10)].rstrip()
        m = t2_text_mask(t + "...", font_path, size, tracking_em, shear)
    return m, (t + "..." if t != text else text), size


def make_tech_background(W, H, box, divider_pct, out_path):
    k = W / 1080.0
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    stops = [(0.0, (3, 8, 24)), (0.45, (5, 17, 46)), (1.0, (2, 10, 30))]
    for y in range(H):
        p = y / float(max(1, H - 1))
        col = stops[-1][1]
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= p <= p1:
                f = (p - p0) / (p1 - p0)
                col = tuple(int(c0[i] + (c1[i] - c0[i]) * f) for i in range(3))
                break
        d.line([(0, y), (W, y)], fill=col)
    base = img.convert("RGBA")

    def layer():
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    bx, by, bw, bh = box["x"], box["y"], box["w"], box["h"]
    # soft blue light behind the frame + diagonal light streaks
    L = layer()
    ImageDraw.Draw(L).ellipse((bx - 0.35 * W, by + bh * 0.05, bx + bw + 0.35 * W, by + bh * 0.95),
                              fill=(20, 80, 200, 70))
    base.alpha_composite(L.filter(ImageFilter.GaussianBlur(150 * k)))
    L = layer()
    ld = ImageDraw.Draw(L)
    ld.polygon([(W * 0.50, 0), (W * 0.80, 0), (W, H * 0.22), (W, H * 0.34)], fill=(40, 110, 255, 26))
    ld.polygon([(0, H * 0.62), (0, H * 0.78), (W * 0.35, H), (W * 0.10, H)], fill=(40, 110, 255, 22))
    base.alpha_composite(L.filter(ImageFilter.GaussianBlur(22 * k)))
    # dot grids
    L = layer()
    ld = ImageDraw.Draw(L)
    for r in range(4):
        for cc in range(6):
            x, y = 80 * k + cc * 21 * k, 84 * k + r * 21 * k
            ld.ellipse((x - 2 * k, y - 2 * k, x + 2 * k, y + 2 * k), fill=(70, 150, 240, 170))
    for r in range(3):
        for cc in range(4):
            x, y = W - 80 * k - cc * 21 * k, 368 * k + r * 21 * k
            ld.ellipse((x - 2 * k, y - 2 * k, x + 2 * k, y + 2 * k), fill=(70, 150, 240, 150))
    base.alpha_composite(L)

    # floor grid + glowing horizon
    L = layer()
    ld = ImageDraw.Draw(L)
    hz = H - 190 * k
    for i in range(1, 8):
        y = hz + ((i / 7.0) ** 2) * 190 * k
        ld.line([(0, y), (W, y)], fill=(30, 100, 230, 70), width=max(1, int(1.5 * k)))
    for j in range(-14, 15):
        ld.line([(W / 2 + j * W * 0.03, hz), (W / 2 + j * W * 0.11, H)], fill=(30, 100, 230, 60),
                width=max(1, int(1.5 * k)))
    base.alpha_composite(L)
    G = layer()
    ImageDraw.Draw(G).line([(0, hz), (W, hz)], fill=(40, 150, 255, 255), width=max(3, int(5 * k)))
    g = G.filter(ImageFilter.GaussianBlur(10 * k))
    base.alpha_composite(g)
    base.alpha_composite(g)
    L = layer()
    ImageDraw.Draw(L).line([(0, hz), (W, hz)], fill=(110, 205, 255, 230), width=max(2, int(2.5 * k)))
    base.alpha_composite(L)

    # glowing frame around the video box
    G = layer()
    gd = ImageDraw.Draw(G)
    e = 7 * k
    gd.line(_chamfer(bx - e, by - e, bx + bw + e, by + bh + e, 14 * k) + [(bx - e + 14 * k, by - e)],
            fill=(30, 130, 255, 255), width=max(4, int(6 * k)), joint="curve")
    g = G.filter(ImageFilter.GaussianBlur(12 * k))
    base.alpha_composite(g)
    base.alpha_composite(g)
    L = layer()
    ld = ImageDraw.Draw(L)
    ld.line(_chamfer(bx - e, by - e, bx + bw + e, by + bh + e, 14 * k) + [(bx - e + 14 * k, by - e)],
            fill=(35, 150, 255, 255), width=max(3, int(4 * k)), joint="curve")
    e2 = 24 * k
    ld.line(_chamfer(bx - e2, by - e2, bx + bw + e2, by + bh + e2, 40 * k) + [(bx - e2 + 40 * k, by - e2)],
            fill=(40, 110, 230, 120), width=max(1, int(2 * k)), joint="curve")
    ln = 52 * k
    br = (130, 220, 255, 255)
    bwid = max(3, int(6 * k))
    xs0, ys0, xs1, ys1 = bx - e, by - e, bx + bw + e, by + bh + e
    for (px, py, sx, sy) in ((xs0, ys0, 1, 1), (xs1, ys0, -1, 1), (xs0, ys1, 1, -1), (xs1, ys1, -1, -1)):
        ld.line([(px + sx * ln, py), (px, py), (px, py + sy * ln)], fill=br, width=bwid, joint="curve")
    base.alpha_composite(L)

    # divider line under the video
    if divider_pct:
        y = int(H * divider_pct / 100.0)
        x0, x1 = int(W * 0.17), int(W * 0.83)
        G = layer()
        ImageDraw.Draw(G).line([(x0, y), (x1, y)], fill=(30, 130, 255, 255), width=max(3, int(4 * k)))
        g = G.filter(ImageFilter.GaussianBlur(7 * k))
        base.alpha_composite(g)
        L = layer()
        ld = ImageDraw.Draw(L)
        ld.line([(x0, y), (x1, y)], fill=(40, 110, 215, 190), width=max(2, int(3 * k)))
        ld.line([(x0, y), (x0 + (x1 - x0) * 0.26, y)], fill=(70, 185, 255, 255), width=max(3, int(5 * k)))
        base.alpha_composite(L)

    # bottom corner brackets
    L = layer()
    ld = ImageDraw.Draw(L)
    yb = H * 0.752
    ld.line([(98 * k, yb), (66 * k, yb), (66 * k, yb + 36 * k)], fill=(60, 175, 255, 255), width=max(3, int(6 * k)),
            joint="curve")
    yb2 = H * 0.868
    ld.line([(W - 66 * k, yb2 - 36 * k), (W - 66 * k, yb2), (W - 98 * k, yb2)], fill=(60, 175, 255, 255),
            width=max(3, int(6 * k)), joint="curve")
    base.alpha_composite(L)
    base.convert("RGB").save(out_path)
    return out_path


def _draw_frame(base, box, k, W, H):
    bx, by, bw, bh = box["x"], box["y"], box["w"], box["h"]

    def layer():
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    e = 7 * k
    poly = _chamfer(bx - e, by - e, bx + bw + e, by + bh + e, 14 * k)
    poly = poly + [poly[0]]
    G = layer()
    ImageDraw.Draw(G).line(poly, fill=(30, 130, 255, 255), width=max(4, int(6 * k)), joint="curve")
    g = G.filter(ImageFilter.GaussianBlur(12 * k))
    base.alpha_composite(g)
    base.alpha_composite(g)
    L = layer()
    ld = ImageDraw.Draw(L)
    ld.line(poly, fill=(35, 150, 255, 255), width=max(3, int(4 * k)), joint="curve")
    e2 = 24 * k
    p2 = _chamfer(bx - e2, by - e2, bx + bw + e2, by + bh + e2, 40 * k)
    ld.line(p2 + [p2[0]], fill=(40, 110, 230, 120), width=max(1, int(2 * k)), joint="curve")
    ln = 52 * k
    br = (130, 220, 255, 255)
    bwid = max(3, int(6 * k))
    xs0, ys0, xs1, ys1 = bx - e, by - e, bx + bw + e, by + bh + e
    for (px, py, sx, sy) in ((xs0, ys0, 1, 1), (xs1, ys0, -1, 1), (xs0, ys1, 1, -1), (xs1, ys1, -1, -1)):
        ld.line([(px + sx * ln, py), (px, py), (px, py + sy * ln)], fill=br, width=bwid, joint="curve")
    base.alpha_composite(L)


T2_DEFAULT_BOX = {"x": 110, "y": 352, "w": 802, "h": 932, "mode": "fill"}


T2_DEFAULTS = {
    "accent": T2_ACCENT, "logo": "</>", "name": "AHMED IBRAHIM",
    "subtitle": "WEB DEVELOPER · MOBILE DEVELOPER · AI AUTOMATION",
    "pill": "CREATOR SERIES", "line1": "BUILDING DIGITAL", "line2": "EXPERIENCES",
    "radius": 28, "border": 5,                 # video window corner radius / border width (px at 1080 wide)
    "show_bg_shapes": True, "show_dots": True, "show_header": True, "show_pill": True, "show_headline": True,
    "fonts": {},                               # optional overrides {"headline": path, "ui": path, "arabic": path}
    # Part 3A - chapter tag (dynamic): list of {"start","end","trigger","num","label","anim","anim_dur"}
    "chapters": [], "chapters_on": True, "chapter_anim": "slide_up", "chapter_anim_dur": 0.35,
    # Part 3B - floating B-roll cards: list of {"media","label","icon","icon_path","slot","start","trigger","hold"}
    "cards": [], "cards_on": True, "card_rot": 4.0, "card_anim_dur": 0.5,
    # Part 4A - ABOUT ME + features block: list of states {"start","end","trigger","paragraph","title","rows","anim","anim_dur"}
    # ([] = one default state with the poster texts); about_on False = block disabled.
    "about": [], "about_on": True, "about_anim": "fade", "about_anim_dur": 0.4,
    # Part 4B - bottom info panel: {on, layers_title, guide_title, rows:[{label,start,end,color,segs,bar}], guide:[str]}
    # ({} = poster defaults; {"on": False} = panel disabled, nothing drawn).  Static plate + one moving playhead.
    "panel": {},
    # Part 4C - split screen: {on, left_pct, gap_px, margin, bottom_px, merge, radius, border}; off by default.
    # While an element (PNG) / video layer over the box is shown: video left, element right, two lime-framed rounded boxes.
    "split": {},
}


T2_TEXT_KEYS = ("logo", "name", "subtitle", "pill", "line1", "line2")


T2_BOOL_KEYS = ("show_bg_shapes", "show_dots", "show_header", "show_pill", "show_headline", "chapters_on", "cards_on", "about_on")


def t2_cfg(raw=None):
    """Complete, validated cfg["t2"]: every key present (unknown keys are kept for Parts 3-4)."""
    d = dict(T2_DEFAULTS)
    d["fonts"] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if v is not None:
                d[k] = v
    d["accent"] = "#%02x%02x%02x" % t2_rgb(d["accent"])
    for k in T2_TEXT_KEYS:
        d[k] = str(d.get(k, "")).replace("\n", " ")
    for k in T2_BOOL_KEYS:
        d[k] = bool(d.get(k, True))
    for k, lo, hi in (("radius", 0, 90), ("border", 1, 20)):
        try:
            d[k] = max(lo, min(hi, float(d[k])))
        except (TypeError, ValueError):
            d[k] = T2_DEFAULTS[k]
    if not isinstance(d.get("fonts"), dict):
        d["fonts"] = {}
    d["chapters"] = t2_norm_chapters(d.get("chapters"))
    if d.get("chapter_anim") not in ANIMS + ["none"]:
        d["chapter_anim"] = T2_DEFAULTS["chapter_anim"]
    try:
        d["chapter_anim_dur"] = max(0.05, min(3.0, float(d["chapter_anim_dur"])))
    except (TypeError, ValueError):
        d["chapter_anim_dur"] = T2_DEFAULTS["chapter_anim_dur"]
    d["cards"] = t2_norm_cards(d.get("cards"))
    for k, lo, hi in (("card_rot", -25.0, 25.0), ("card_anim_dur", 0.05, 3.0)):
        try:
            d[k] = max(lo, min(hi, float(d[k])))
        except (TypeError, ValueError):
            d[k] = T2_DEFAULTS[k]
    d["about"] = t2_norm_about(d.get("about"))
    if d.get("about_anim") not in ANIMS + ["none"]:
        d["about_anim"] = T2_DEFAULTS["about_anim"]
    try:
        d["about_anim_dur"] = max(0.05, min(3.0, float(d["about_anim_dur"])))
    except (TypeError, ValueError):
        d["about_anim_dur"] = T2_DEFAULTS["about_anim_dur"]
    d["panel"] = t2_norm_panel(d.get("panel"))
    d["split"] = t2_norm_split(d.get("split"))
    return d


def t2_norm_split(raw):
    """Validated cfg['t2']['split'] (see T2_DEFAULTS).  raw may be None / True / False / dict."""
    r = {"on": bool(raw)} if isinstance(raw, bool) else (raw if isinstance(raw, dict) else {})

    def num(k, dflt, lo, hi):
        try:
            return max(lo, min(hi, float(r.get(k, dflt))))
        except (TypeError, ValueError):
            return float(dflt)
    return {"on": bool(r.get("on", False)), "left_pct": num("left_pct", 50, 25, 75), "gap_px": int(round(num("gap_px", 24, 8, 120))),
            "margin": int(round(num("margin", 26, 12, 80))), "bottom_px": int(round(num("bottom_px", 170, 0, 400))),
            "merge": num("merge", 1.6, 0, 10), "radius": num("radius", 20, 0, 60), "border": int(round(num("border", 4, 1, 12)))}


def t2_norm_chapters(raw):
    """Chapter list -> clean list (idempotent). Entry: start (s) | trigger (SRT phrase), num (''=auto), label,
    optional end (s), anim ('' = cfg default), anim_dur (None = cfg default). Entries without num/label are dropped."""
    out = []
    for ch in (raw if isinstance(raw, (list, tuple)) else []):
        if not isinstance(ch, dict):
            continue
        num = str(ch.get("num") if ch.get("num") is not None else "").replace("\n", " ").strip()
        label = str(ch.get("label") if ch.get("label") is not None else "").replace("\n", " ").strip()
        if not num and not label and not str(ch.get("trigger") or "").strip():
            continue
        anim = ch.get("anim") if ch.get("anim") in ANIMS + ["none"] else ""
        out.append({"start": _t2_num_or_none(ch.get("start")), "end": _t2_num_or_none(ch.get("end")),
                    "trigger": str(ch.get("trigger") or "").strip(), "num": num, "label": label,
                    "anim": anim, "anim_dur": _t2_num_or_none(ch.get("anim_dur"))})
    return out


def t2_norm_cards(raw):
    """Floating-card list -> clean list (idempotent). Entry: media (image/video path), label, icon
    (code|phone|chip|none|image + icon_path), slot 1-3, start (s) | trigger (SRT phrase), hold (s).
    Entries without a media path are dropped."""
    out = []
    for c in (raw if isinstance(raw, (list, tuple)) else []):
        if not isinstance(c, dict) or not str(c.get("media") or "").strip():
            continue
        icon = c.get("icon") if c.get("icon") in ("code", "phone", "chip", "none", "image") else "code"
        ip = str(c.get("icon_path") or "") if icon == "image" else ""
        if icon == "image" and not ip:
            icon = "none"
        try:
            slot = int(c.get("slot") or 1)
        except (TypeError, ValueError):
            slot = 1
        hold = _t2_num_or_none(c.get("hold"))
        out.append({"media": str(c["media"]).strip(), "label": str(c.get("label") or "").replace("\n", " ").strip(),
                    "icon": icon, "icon_path": ip, "slot": slot if slot in (1, 2, 3) else 1,
                    "start": _t2_num_or_none(c.get("start")), "trigger": str(c.get("trigger") or "").strip(),
                    "hold": hold if hold and hold > 0.2 else 4.0})
    return out


# ---- Template 2: ABOUT ME + FEATURES block (Part 4A) --------------------------------------------------
# Poster (941 px wide) y 1150-1280, under the video window; x 1.1477 -> 1080 px.  All numbers below are canvas px at
# 1080 wide, y relative to `y_base` = bottom of the video window + 36 (default window: 1284 + 36 = 1320).
# Left column: lime square + "ABOUT ME" (letter-spaced grey) + <=3 light-white paragraph lines.  Thin vertical divider.
# Right column: <=4 rows of  lime line icon + white text.  Several STATES over time (time or SRT trigger phrase).
T2_ABOUT = {"x_left": 98, "col_w": 450, "div_x": 570, "div_y0": 6, "div_y1": 143, "sq": 15, "sq_y": 10,
            "title_dx": 41, "title_cy": 18, "title_cap": 15, "title_tr": 0.30,
            "para_cy": 61, "para_pitch": 33, "para_cap": 20, "para_lines": 3, "min_scale": 0.55,
            "row_cy": 71, "row_pitch": 47, "row_pitch4": 38, "icon": 32, "icon_cx": 671, "text_x": 726, "right": 982,
            "row_cap": 19, "box_gap": 36, "pad_x": 8, "top": -4, "h": 154, "max_rows": 4,
            "muted": (141, 146, 143), "para_col": (232, 234, 232), "div_col": (95, 100, 98, 210)}


T2_ABOUT_DEFAULT_STATE = {
    "paragraph": "Passionate about technology, building scalable solutions, and sharing knowledge.",
    "title": "ABOUT ME",
    "rows": [{"icon": "laptop", "text": "Web Development"}, {"icon": "phone", "text": "Mobile Development"},
             {"icon": "gear", "text": "AI Automation"}]}


T2_ABOUT_ICONS = ("laptop", "phone", "gear", "code", "chip", "image", "none")


def t2_about_icon_spec(v):
    """Icon answer ('laptop' | number 1-6 | path of a PNG/ICO) -> (kind, icon_path). Unknown -> ('none', '')."""
    s = str(v if v is not None else "").strip()
    m = {"1": "laptop", "2": "phone", "3": "gear", "4": "code", "5": "chip", "6": "none", "ai": "gear"}
    s = m.get(s.translate(AR_DIGITS).lower(), s)
    if s in T2_ABOUT_ICONS and s != "image":
        return s, ""
    if s and os.path.isfile(clean_path(s)):
        return "image", clean_path(s)
    return "none", ""


def t2_norm_about(raw):
    """About states -> clean list (idempotent). State: start (s) | trigger (SRT phrase), end (s), paragraph, title
    ('' = no title), rows (<=4 of {icon, icon_path, text}), anim ('' = cfg default), anim_dur (None = cfg default).
    An empty / invalid list means 'one default state (the poster texts) for the whole video'."""
    out = []
    for st in (raw if isinstance(raw, (list, tuple)) else []):
        if not isinstance(st, dict):
            continue
        rows = []
        for r in (st.get("rows") if isinstance(st.get("rows"), (list, tuple)) else [])[:T2_ABOUT["max_rows"]]:
            if isinstance(r, str):
                r = {"text": r}
            if not isinstance(r, dict):
                continue
            txt = str(r.get("text") if r.get("text") is not None else "").replace("\n", " ").strip()
            kind, ipath = t2_about_icon_spec(r.get("icon_path") or r.get("icon") or "none")
            if not txt and kind == "none":
                continue
            rows.append({"icon": kind, "icon_path": ipath, "text": txt})
        title = st.get("title")
        out.append({"start": _t2_num_or_none(st.get("start")), "end": _t2_num_or_none(st.get("end")),
                    "trigger": str(st.get("trigger") or "").strip(),
                    "paragraph": str(st.get("paragraph") if st.get("paragraph") is not None else "").replace("\n", " ").strip(),
                    "title": T2_ABOUT_DEFAULT_STATE["title"] if title is None else str(title).replace("\n", " ").strip(),
                    "rows": rows, "anim": st.get("anim") if st.get("anim") in ANIMS + ["none"] else "",
                    "anim_dur": _t2_num_or_none(st.get("anim_dur"))})
    return out


# ---- Template 2: bottom INFO PANEL (Part 4B) -----------------------------------------------------------------
# Poster px (941 wide).  ONE static plate (baked into the foreground plate, zero per-frame cost) + ONE small
# playhead sprite that FFmpeg moves with an x-expression of the real video time (progress = t / duration).
# Part 4C adds the audio waveform in row 09 (reserved, left empty here) and the pagination dots.
T2_PANEL = {"x0": 22, "y0": 1303, "x1": 918, "y1": 1605, "radius": 24, "outline": (84, 90, 72), "fill": (9, 11, 15),
            "num_x": 40, "label_x": 88, "label_r": 294, "track_x0": 306, "track_x1": 608, "row0": 1366, "pitch": 26.5,
            "bar_h": 15, "bar_r": 3, "label_cap": 11.2, "num_cap": 10.5, "title_cap": 13.5, "title_x": 91, "title_cy": 1330,
            "icon_cx": 55, "icon": 30, "sep": (30, 34, 38), "muted": (150, 154, 152),
            "div_x": 637, "div_y0": 1318, "div_y1": 1592, "g_icon_cx": 672, "g_title_x": 704, "g_circ_x": 670,
            "g_text_x": 695, "g_right": 905, "g_y0": 1371, "g_pitch": 33.1, "circ_r": 9.6, "g_cap": 11.2,
            "ph_top": 1333, "ph_bot": 1590, "ph_w": 2.2, "tri_w": 13, "tri_h": 10, "max_rows": 9, "max_guide": 6}


T2_PANEL_ROWS = [
    ("Main Video Footage", 0.0, 1.0, "#4C95DC", None),
    ("Secondary B-Roll / Image", 0.209, 0.719, "#833B8F", None),
    ("Background Graphics", 0.0, 0.503, "#1B3C2D", None),
    ("Main Headline", 0.0, 0.96, "#ACCF42", None),
    ("Arabic Captions", 0.0, 0.838, "#D4C9B7", [[0.0, 0.22], [0.25, 0.44], [0.47, 0.68], [0.71, 0.838]]),
    ("Active Word Highlight", 0.318, 0.616, "#92D30A", None),
    ("Supporting Text", 0.454, 0.752, "#878686", [[0.454, 0.55], [0.58, 0.752]]),
    ("Motion Graphics", 0.0, 0.51, "#038D74", None),
    ("Sound Effects / Audio", 0.0, 0.0, "#6E7075", None),      # row 09: no bar yet (waveform = Part 4C)
]


T2_PANEL_GUIDE = ["Headline: Slide Up + Fade In", "Captions: Word-by-Word Reveal", "Highlight: Scale + Color Change",
                  "B-Roll: Slide In", "Support Text: Fade In", "Transitions: Smooth Mask"]


def t2_norm_panel(raw):
    """Validated cfg['t2']['panel'] = {on, layers_title, guide_title, rows:[{label,start,end,color,segs,bar}], guide:[str]}.
    raw may be None / True / False / dict; missing rows or guide texts = the poster defaults."""
    r = {"on": bool(raw)} if isinstance(raw, bool) else (raw if isinstance(raw, dict) else {})
    out = {"on": bool(r.get("on", True)),
           "layers_title": str(r.get("layers_title") if r.get("layers_title") is not None else "EDITING LAYERS").replace("\n", " "),
           "guide_title": str(r.get("guide_title") if r.get("guide_title") is not None else "MOTION GUIDE").replace("\n", " "),
           "wave": bool(r.get("wave", True)),      # Part 4C: real audio waveform in row 09 (when that row has no bar)
           "dots": bool(r.get("dots", True)),      # Part 4C: pagination dots, bottom-right of the panel
           # "roadmap" = content-driven panel (one card per chapter, the current one lit) instead of EDITING LAYERS / MOTION GUIDE
           "style": "roadmap" if str(r.get("style") or "").strip().lower() in ("roadmap", "chapters", "map") else "editing",
           "title": str(r.get("title") if r.get("title") is not None else "EPISODE ROADMAP").replace("\n", " "),
           "now_label": str(r.get("now_label") if r.get("now_label") is not None else "NOW").replace("\n", " "),
           "end": _t2_num_or_none(r.get("end"))}   # roadmap only: second at which the panel fades out (None = video end)
    rows_in = r.get("rows")
    if not isinstance(rows_in, list):
        rows_in = [None] * len(T2_PANEL_ROWS)
    rows = []
    for i, x in enumerate(rows_in[:T2_PANEL["max_rows"]]):
        dl, ds, de, dc, dsegs = T2_PANEL_ROWS[i] if i < len(T2_PANEL_ROWS) else ("", 0.0, 0.0, "#8E9094", None)
        x = {"label": x} if isinstance(x, str) else (x if isinstance(x, dict) else {})
        s, e = _t2_frac(x.get("start"), ds), _t2_frac(x.get("end"), de)
        if x.get("start") is None and x.get("end") is None:
            s, e = ds, de
        segs = x.get("segs", dsegs if (x.get("start") is None and x.get("end") is None) else None)
        ns = []
        for sg in (segs or []):
            try:
                a, b = _t2_frac(sg[0], 0.0), _t2_frac(sg[1], 0.0)
                if b > a:
                    ns.append([a, b])
            except (TypeError, IndexError):
                pass
        rows.append({"label": str(x["label"] if x.get("label") is not None else dl).replace("\n", " "),
                     "start": s, "end": e, "color": "#%02x%02x%02x" % t2_rgb(x.get("color") or dc),
                     "segs": ns or None, "bar": bool(x.get("bar", bool(ns) or e > s))})
    out["rows"] = rows
    g = r.get("guide")
    if not isinstance(g, list):
        g = list(T2_PANEL_GUIDE)
    out["guide"] = [str(v).replace("\n", " ") for v in g[:T2_PANEL["max_guide"]]]
    return out


# ---- generic helpers added for Template 3 (editorial look) ---------------------------------
def paper_texture(size, base=(198, 165, 136), seed=1, grain=11.0, fibers=90, fiber_alpha=34):
    """Procedural beige paper: RGB image `size`, low-contrast noise + soft blotches + thin fibers (seeded)."""
    import random
    w, h = max(2, int(size[0])), max(2, int(size[1]))
    rnd = random.Random(seed)
    n1 = Image.effect_noise((w, h), grain * 2.2).filter(ImageFilter.GaussianBlur(0.7))
    n2 = Image.effect_noise((max(2, w // 12), max(2, h // 12)), grain * 3.0).resize((w, h), Image.BICUBIC)
    n = Image.blend(n1, n2, 0.45)
    img = Image.merge("RGB", [n.point(lambda v, b=b: max(0, min(255, int(b + (v - 128) * 0.55)))) for b in base])
    fib = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(fib)
    for _ in range(int(fibers)):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        a, ln = rnd.uniform(0, math.tau), rnd.uniform(8, 38)
        pts, ang = [(x, y)], a
        for _s in range(4):
            ang += rnd.uniform(-0.5, 0.5)
            x, y = x + math.cos(ang) * ln / 4, y + math.sin(ang) * ln / 4
            pts.append((x, y))
        c = (255, 245, 225, fiber_alpha) if rnd.random() < 0.55 else (90, 60, 40, fiber_alpha)
        d.line(pts, fill=c, width=1)
    img = img.convert("RGBA")
    img.alpha_composite(fib)
    return img.convert("RGB")


def paper_fill(size_ox_oy, seed=1):
    """fill callable for t2_paint: paper texture sized to the mask (use with a polygon mask)."""
    def fn(size, origin):
        return paper_texture(size, seed=seed).convert("RGBA")
    return fn


def rotated_mask(m, degrees):
    """Rotate an 'L' mask counter-clockwise by `degrees` (positive = text rises to the right), expand canvas."""
    return m.rotate(degrees, resample=Image.BICUBIC, expand=True)


def draw_dotted_line(base, text, font_path, x0, x1, cy, cap_px, color, dot_color, tracking_em=0.2,
                     align="left", grow=1.3, min_scale=0.45):
    """Letter-spaced caps line whose '•' separators are drawn as round dots in `dot_color`.
    The line is scaled to fill x0..x1 (never bigger than cap_px*grow, never smaller than cap_px*min_scale;
    shorter text stays left/right/centre aligned). Returns the painted bbox (or None for empty text)."""
    parts = [p.strip() for p in str(text or "").split("•") if p.strip()]
    if not parts:
        return None
    width = max(10.0, float(x1 - x0))

    def build(cap):
        size = t2_size_for_cap(font_path, cap)
        ms = [t2_text_mask(p, font_path, size, tracking_em) for p in parts]
        gap = cap * 1.35
        dot_r = max(1.5, cap * 0.28)
        total = sum(m.width for m in ms) + (len(ms) - 1) * (gap + 2 * dot_r)
        return ms, gap, dot_r, total
    cap = cap_px
    ms, gap, dot_r, total = build(cap)
    cap = max(cap_px * min_scale, min(cap_px * grow, cap * width / total * 0.995))
    ms, gap, dot_r, total = build(cap)
    for _ in range(3):                       # still too wide at the minimum scale: shrink anyway (never overflow)
        if total <= width + 0.5:
            break
        cap *= width / total * 0.99
        ms, gap, dot_r, total = build(cap)
    x = {"left": x0, "right": x1 - total, "center": x0 + (width - total) / 2.0}.get(align, x0)
    boxes = []
    for i, m in enumerate(ms):
        bb = t2_paint(base, t2_place(m, x, cy=cy), color)
        if bb:
            boxes.append(bb)
        x += m.width
        if i < len(ms) - 1:
            dcx = x + gap / 2.0 + dot_r
            bb = t2_paint(base, t2_draw_mask((dcx - dot_r, cy - dot_r, dcx + dot_r, cy + dot_r),
                                              lambda d, L, s, cx=dcx: d.ellipse(
                                                  (*L(cx - dot_r, cy - dot_r), *L(cx + dot_r, cy + dot_r)), fill=255)),
                          dot_color)
            if bb:
                boxes.append(bb)
            x += gap + 2 * dot_r
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)) if boxes else None
