"""mt.templates.t4.kit - Template 4 neon / glass primitives (look of R1 / R5 / R10).
Masks are mt.draw masks ((L image, (ox, oy))). Every sprite function returns an RGBA image whose glow margin is included;
sprite.info["origin"] = (ox, oy) is where the shape's local (0, 0) sits inside the image -> use kit_paste(base, sprite, x, y).
Public: PALETTE, chamfer_rect, neon_stroke, glass_panel, connector, hex_badge, hazard_stripes, icon, neon_icon, kit_paste, kit_sheet.
All shapes are built at 4x and shrunk (crisp edges); sprites never raise on bad input."""
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from mt.draw import (_t2_alpha_paste, t2_darken, t2_draw_mask, t2_glow, t2_grad, t2_lighten, t2_line_mask, t2_paint,
                     t2_poly_mask, t2_rgb, t2_rrect_mask)
from mt.templates.t4.kit_icons import ICON_NAMES, SS, icon_mask, soft_erode

PALETTE = {"cyan": (25, 211, 255), "blue": (30, 107, 255), "yellow": (255, 194, 26),
           "glass": (6, 16, 40, 199), "white": (255, 255, 255)}      # glass = rgba(6,16,40,0.78)


# ---- small internals ------------------------------------------------------------------------------------------------
def _tag(im, origin):
    im.info["origin"] = (int(origin[0]), int(origin[1]))
    return im


def _origin(sp):
    return sp.info.get("origin", (0, 0))


def _shift(mask, dx, dy):
    return mask[0], (mask[1][0] + int(dx), mask[1][1] + int(dy))


def kit_paste(base, sprite, x=0, y=0):
    """Alpha-composite a kit sprite so that its local (0, 0) lands on canvas (x, y). Clips at the canvas edge."""
    ox, oy = _origin(sprite)
    _t2_alpha_paste(base, sprite, int(round(x)) - ox, int(round(y)) - oy)
    return base


def _pad_for(glow):
    return int(max(0.0, glow) * 2.6) + 4


def _edge_bands(mask, specs, pad):
    """Inner edge bands of a filled mask: specs = [(d0, d1)] (px inside the edge) -> ([L sprite-size], (W, H), origin)."""
    m, (ox, oy) = mask
    W, H = m.width + 2 * pad, m.height + 2 * pad
    cv = Image.new("L", (W, H), 0)
    cv.paste(m, (pad, pad))
    big = cv.resize((W * SS, H * SS), Image.BICUBIC)
    cache = {0: big}

    def E(d):
        if d not in cache:
            cache[d] = soft_erode(big, d * SS)
        return cache[d]
    out = [ImageChops.subtract(E(a), E(b)).resize((W, H), Image.BOX) for a, b in specs]
    return out, (W, H), (pad - ox, pad - oy)


def _halo(band, sigma, peak, width):
    """Gaussian halo of a thin band whose peak alpha is `peak` (gain compensates the band's thinness)."""
    gain = peak * sigma * 2.5066 / max(1.0, width)
    return t2_glow((band, (0, 0)), sigma, gain)


def _neon(size, band, core, color, glow, width):
    """glow (wide + tight) + saturated band + near-white core on a transparent sprite of `size`."""
    sp = Image.new("RGBA", size, (0, 0, 0, 0))
    c = t2_rgb(color)
    if glow > 0:
        t2_paint(sp, _halo(band, glow, 0.42, width), c)
        t2_paint(sp, _halo(band, max(1.0, glow / 3.0), 0.55, width), c)
    t2_paint(sp, (band, (0, 0)), c)
    if core is not None:
        t2_paint(sp, (core, (0, 0)), t2_lighten(c, 0.78))
    return sp


# ---- shapes ---------------------------------------------------------------------------------------------------------
def chamfer_rect(size, cut):
    """Mask of a w x h rectangle with cut corners. cut = px for all corners or (tl, tr, br, bl). Local origin = top-left."""
    w, h = float(size[0]), float(size[1])
    cs = list(cut) if isinstance(cut, (tuple, list)) and len(cut) == 4 else [cut] * 4
    tl, tr, br, bl = [max(0.0, min(float(v or 0), w / 2.0, h / 2.0)) for v in cs]
    pts = [(tl, 0), (w - tr, 0), (w, tr), (w, h - br), (w - br, h), (bl, h), (0, h - bl), (0, tl)]
    clean = [p for i, p in enumerate(pts) if p != pts[i - 1]]
    return t2_poly_mask(clean)


def neon_stroke(mask, color=None, width=2.0, glow=10):
    """Neon outline of a filled mask: glow + coloured band (inside the edge) + bright core. -> RGBA sprite."""
    color = PALETTE["cyan"] if color is None else color
    bw = max(1.0, float(width))
    bands, size, org = _edge_bands(mask, [(0, bw), (0.3 * bw, 0.7 * bw)], _pad_for(glow))
    return _tag(_neon(size, bands[0], bands[1], color, glow, bw), org)


# ---- panels ---------------------------------------------------------------------------------------------------------
def _glass_sprite(mask, tint, color, bw, glow):
    """Shared by glass_panel / hex_badge: gradient dark-glass fill + inner edge glow + sheen + neon border."""
    c = t2_rgb(color)
    bands, size, org = _edge_bands(mask, [(0, bw), (0.3 * bw, 0.7 * bw), (0, 11)], _pad_for(glow))
    sp = Image.new("RGBA", size, (0, 0, 0, 0))
    a = tint[3] if len(tint) > 3 else 199
    rgb = t2_rgb(tint)
    sm = _shift(mask, org[0], org[1])
    t2_paint(sp, sm, t2_grad([(0, t2_lighten(rgb, 0.10) + (a,)), (0.55, rgb + (a,)), (1, t2_darken(rgb, 0.25) + (a,))], 90))
    t2_paint(sp, sm, t2_grad([(0, (190, 230, 255, 34)), (0.35, (190, 230, 255, 0))], 90))
    inner = bands[2].filter(ImageFilter.GaussianBlur(3.5)).point(lambda v: min(255, int(v * 1.5)))
    t2_paint(sp, (inner, (0, 0)), c, 0.30)
    stroke = _neon(size, bands[0], bands[1], c, glow, bw)
    sp.alpha_composite(stroke)
    return _tag(sp, org)


def glass_panel(size, radius=18, tint=None, border=None, cut=0, border_w=2.0, glow=10):
    """Dark-glass HUD panel (rgba(6,16,40,0.78) by default) with a neon border. cut > 0 / (tl,tr,br,bl) -> chamfered corners."""
    w, h = max(8, int(size[0])), max(8, int(size[1]))
    mask = chamfer_rect((w, h), cut) if cut else t2_rrect_mask((0, 0, w, h), radius)
    return _glass_sprite(mask, tint or PALETTE["glass"], PALETTE["cyan"] if border is None else border, border_w, glow)


def _hex_pts(cx, cy, R):
    return [(cx + R * math.cos(math.radians(60 * i)), cy + R * math.sin(math.radians(60 * i))) for i in range(6)]


def hex_badge(size, icon_name="code", color=None, glow=10):
    """Hexagon badge (pointy left / right, as in R1 / R10): glass fill, neon border, thin inner ring, glowing icon. size = width."""
    color = PALETTE["cyan"] if color is None else color
    R = max(8.0, float(size)) / 2.0
    cx, cy = R, R * 0.866
    bw = max(2.0, R * 0.07)
    sp = _glass_sprite(t2_poly_mask(_hex_pts(cx, cy, R), round_r=R * 0.07), PALETTE["glass"], color, bw, glow)
    ring = t2_poly_mask(_hex_pts(cx, cy, R * 0.80), round_r=R * 0.05)
    rb, _, ro = _edge_bands(ring, [(0, max(1.0, bw * 0.45))], 2)
    ox, oy = _origin(sp)
    t2_paint(sp, (rb[0], (ox - ro[0], oy - ro[1])), t2_rgb(color), 0.45)
    if icon_name:
        isz = int(R * 1.05)
        ic = neon_icon(icon_name, isz, t2_lighten(t2_rgb(color), 0.35), glow=max(3.0, R * 0.16))
        kit_paste(sp, ic, cx - isz / 2.0 + ox, cy - isz / 2.0 + oy)
    return sp


# ---- connectors / stripes ---------------------------------------------------------------------------------------------
def _disc(cx, cy, r):
    def fn(d, L, s):
        a, b = L(cx - r, cy - r), L(cx + r, cy + r)
        d.ellipse((a[0], a[1], b[0] - 1, b[1] - 1), fill=255)
    return t2_draw_mask((cx - r, cy - r, cx + r, cy + r), fn)


def connector(points, color=None, end_dot=True, width=2.5, glow=9):
    """Thin neon line through `points` (local px) with round joints; end_dot True | 'both' | 'start' | False. Local = given coords."""
    color = PALETTE["cyan"] if color is None else color
    try:
        pts = [(float(x), float(y)) for x, y in points]
    except (TypeError, ValueError):
        pts = []
    if len(pts) < 2:
        return _tag(Image.new("RGBA", (2, 2), (0, 0, 0, 0)), (0, 0))
    c, dr = t2_rgb(color), max(3.0, width * 2.2)
    pad = _pad_for(glow) + int(dr)
    minx, miny = min(p[0] for p in pts), min(p[1] for p in pts)
    ox, oy = int(math.floor(-minx)) + pad, int(math.floor(-miny)) + pad
    size = (int(math.ceil(max(p[0] for p in pts) - minx)) + 2 * pad, int(math.ceil(max(p[1] for p in pts) - miny)) + 2 * pad)
    sp = Image.new("RGBA", size, (0, 0, 0, 0))
    line = _shift(t2_line_mask(pts, width), ox, oy)
    core = _shift(t2_line_mask(pts, max(1.0, width * 0.4)), ox, oy)
    t2_paint(sp, _shift(t2_glow(line, glow, 0.42 * glow * 2.5066 / width), 0, 0), c)
    t2_paint(sp, _shift(t2_glow(line, max(1.0, glow / 3.0), 0.55 * max(1.0, glow / 3.0) * 2.5066 / width), 0, 0), c)
    t2_paint(sp, line, c)
    t2_paint(sp, core, t2_lighten(c, 0.78))
    ends = [pts[-1]] if end_dot is True else [pts[0], pts[-1]] if end_dot == "both" else [pts[0]] if end_dot == "start" else []
    for ex, ey in ends:
        d = _shift(_disc(ex, ey, dr), ox, oy)
        t2_paint(sp, t2_glow(d, dr * 1.2, 1.1), c, 0.7)
        t2_paint(sp, d, c)
        t2_paint(sp, _shift(_disc(ex, ey, dr * 0.45), ox, oy), t2_lighten(c, 0.85))
    return _tag(sp, (ox, oy))


def hazard_stripes(size, angle=30.0, color=None, glow=6, stripe=None, gap=None):
    """Slanted dash bar like the yellow / blue '////' marks in R1 / R10. angle = lean from vertical (+ = '/'). Local origin = top-left."""
    color = PALETTE["yellow"] if color is None else color
    w, h = max(4, int(size[0])), max(4, int(size[1]))
    sw = float(stripe or h * 0.45)
    off = h * math.tan(math.radians(max(-70.0, min(70.0, angle))))
    gp = float(gap if gap is not None else sw * 0.62)
    n = max(1, int((w - abs(off) + gp) // (sw + gp)))
    if n > 1:
        gp = (w - abs(off) - n * sw) / (n - 1)                    # whole dashes only, evenly spread, no clipped ends
    else:
        sw = max(2.0, w - abs(off))

    def fn(d, L, s):
        for k in range(n):
            x = k * (sw + gp) + (0 if off >= 0 else -off)
            q = [(x + off, 0), (x + off + sw, 0), (x + sw, h), (x, h)]
            d.polygon([L(px, py) for px, py in q], fill=255)
    mask = t2_draw_mask((0, 0, w, h), fn, pad=0)
    pad = _pad_for(glow)
    sp = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    m = _shift(mask, pad, pad)
    if glow > 0:
        t2_paint(sp, t2_glow(m, glow, 1.0), t2_rgb(color), 0.55)
    t2_paint(sp, m, t2_rgb(color))
    return _tag(sp, (pad, pad))


# ---- icons ----------------------------------------------------------------------------------------------------------
def icon(name, size, color=None):
    """Flat anti-aliased icon (size x size RGBA) in `color` (default white). Names: kit_icons.ICON_NAMES."""
    color = PALETTE["white"] if color is None else color
    m = icon_mask(name, size)
    sp = Image.new("RGBA", m.size, (0, 0, 0, 0))
    t2_paint(sp, (m, (0, 0)), t2_rgb(color))
    return _tag(sp, (0, 0))


def neon_icon(name, size, color=None, glow=None):
    """Icon with a soft neon halo + near-white core (local (0, 0) = icon's top-left)."""
    color = PALETTE["cyan"] if color is None else color
    size = max(4, int(size))
    glow = size * 0.12 if glow is None else glow
    pad = _pad_for(glow)
    m = icon_mask(name, size)
    sp = Image.new("RGBA", (size + 2 * pad, size + 2 * pad), (0, 0, 0, 0))
    mk = (m, (pad, pad))
    c = t2_rgb(color)
    if glow > 0:
        t2_paint(sp, t2_glow(mk, glow, 1.5), c, 0.75)
    t2_paint(sp, mk, c)
    t2_paint(sp, mk, t2_lighten(c, 0.55), 0.45)
    return _tag(sp, (pad, pad))


# ---- contact sheet ----------------------------------------------------------------------------------------------------
def _sheet_bg(W, H):
    bg = Image.new("RGBA", (W, H), (4, 9, 24, 255))
    bg.alpha_composite(t2_grad([(0, (3, 8, 22, 255)), (1, (9, 24, 58, 255))], 90)((W, H), (0, 0)))
    d = ImageDraw.Draw(bg)
    for x in range(0, W, 60):
        d.line([(x, 0), (x, H)], fill=(40, 90, 150, 22))
    for y in range(0, H, 60):
        d.line([(0, y), (W, y)], fill=(40, 90, 150, 22))
    return bg


def _label(base, xy, text, size=20, fill=(150, 195, 230)):
    from mt.fonts import default_font, load_font
    try:
        f = load_font(default_font(), size)
    except Exception:
        from PIL import ImageFont
        f = ImageFont.load_default()
    ImageDraw.Draw(base).text(xy, text, font=f, fill=fill)


def _sec_palette(bg, y):
    _label(bg, (40, y), "PALETTE  (cyan / blue / yellow / glass over a video-like patch / white)")
    patch = t2_grad([(0, (170, 130, 105, 255)), (1, (55, 85, 120, 255))], 20)((330, 90), (0, 0))
    for i, k in enumerate(("cyan", "blue", "yellow", "white")):
        x = 40 + i * 120
        t2_paint(bg, t2_rrect_mask((x, y + 36, x + 100, y + 126), 10), PALETTE[k])
        _label(bg, (x, y + 132), k, 16)
    bg.paste(patch, (540, y + 36))
    kit_paste(bg, glass_panel((200, 90), 14, glow=0, border=PALETTE["blue"]), 600, y + 36)
    _label(bg, (600, y + 132), "glass 0.78 on video", 16)


def _sec_strokes(bg, y):
    _label(bg, (40, y), "neon_stroke  /  chamfer_rect  (cut 14, glow 6 / 10 / 18, widths 1.5 / 2 / 3.5)")
    for i, (g, w, col) in enumerate(((6, 1.5, "cyan"), (10, 2.0, "cyan"), (18, 3.5, "blue"), (10, 2.0, "yellow"))):
        m = chamfer_rect((250, 110), (14, 14, 14, 14) if i != 3 else (30, 0, 30, 0))
        kit_paste(bg, neon_stroke(m, PALETTE[col], w, g), 60 + i * 300, y + 50)
    m = t2_rrect_mask((0, 0, 110, 110), 55)
    kit_paste(bg, neon_stroke(m, PALETTE["cyan"], 2.5, 12), 1290, y + 50)


def _sec_panels(bg, y):
    _label(bg, (40, y), "glass_panel  (rounded r=18 | R1 name card cuts | R10 name tag cuts)  over a video-like patch")
    bg.paste(t2_grad([(0, (190, 150, 120, 255)), (0.5, (110, 130, 150, 255)), (1, (50, 70, 110, 255))], 25)((1540, 190), (0, 0)), (40, y + 34))
    kit_paste(bg, glass_panel((420, 150), 18), 70, y + 54)
    kit_paste(bg, glass_panel((520, 150), 0, cut=(0, 36, 0, 36), border=PALETTE["cyan"], border_w=2.5, glow=12), 560, y + 54)
    kit_paste(bg, glass_panel((420, 90), 0, cut=(0, 22, 0, 22), border_w=2), 1130, y + 54)
    kit_paste(bg, glass_panel((200, 60), 12, border=PALETTE["yellow"], glow=8), 1130, y + 160)


def _sec_conn(bg, y):
    _label(bg, (40, y), "connector  (end_dot True / both / False, elbow + diagonal)")
    kit_paste(bg, connector([(60, y + 80), (260, y + 80), (330, y + 40), (520, y + 40)], PALETTE["cyan"]))
    kit_paste(bg, connector([(600, y + 40), (700, y + 100), (900, y + 100)], PALETTE["cyan"], "both"))
    kit_paste(bg, connector([(980, y + 90), (1300, y + 90)], PALETTE["blue"], False, 3, 12))
    kit_paste(bg, connector([(1380, y + 100), (1480, y + 40), (1560, y + 40)], PALETTE["yellow"], True, 2, 7))


def _sec_badges(bg, y):
    _label(bg, (40, y), "hex_badge  (code / gear / globe)   hazard_stripes  (yellow 30 deg, blue 30 deg, yellow -30 deg, thin)")
    for i, nm in enumerate(("code", "gear", "globe")):
        kit_paste(bg, hex_badge(130, nm), 60 + i * 190, y + 40)
    kit_paste(bg, hazard_stripes((110, 26), 30), 700, y + 70)
    kit_paste(bg, hazard_stripes((110, 26), 30, PALETTE["blue"]), 860, y + 70)
    kit_paste(bg, hazard_stripes((110, 26), -30), 1020, y + 70)
    kit_paste(bg, hazard_stripes((300, 12), 45, PALETTE["cyan"], 4, stripe=14, gap=9), 1180, y + 77)


def _sec_icons(bg, y):
    _label(bg, (40, y), "icon / neon_icon  (96 px, then 48 / 32 / 24 px flat for jaggies)")
    for i, nm in enumerate(ICON_NAMES):
        x = 40 + i * 140
        kit_paste(bg, neon_icon(nm, 96, PALETTE["cyan"]), x, y + 34)
        for j, s in enumerate((48, 32, 24)):
            kit_paste(bg, icon(nm, s, PALETTE["white"]), x + (0, 52, 90)[j], y + 150)
        _label(bg, (x, y + 190), nm, 15)


def kit_sheet(out_png):
    """Contact sheet of every primitive on a dark background -> out_png (returns the path)."""
    W, H = 1700, 1300
    bg = _sheet_bg(W, H)
    for fn, y in ((_sec_palette, 20), (_sec_strokes, 200), (_sec_panels, 400), (_sec_conn, 680), (_sec_badges, 820),
                  (_sec_icons, 1030)):
        fn(bg, y)
    _label(bg, (40, 1265), "kit_sheet - mt/templates/t4/kit.py", 18, (90, 130, 170))
    import os
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    bg.convert("RGB").save(out_png)
    return out_png


if __name__ == "__main__":
    import sys
    print(kit_sheet(sys.argv[1] if len(sys.argv) > 1 else "out/t4/kit_sheet.png"))
