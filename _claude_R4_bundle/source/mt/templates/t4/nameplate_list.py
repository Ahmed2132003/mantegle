"""mt.templates.t4.nameplate_list - Template 4: the two sprites of the 'corner_list' module (ref R10, bottom corners).
  laptop  a thin neon laptop (screen outline + keyboard deck) with a glowing '</>' on the screen. Any other kit icon name gives
          that icon as a plain neon icon instead.
  list    up to 5 rows: neon icon + small white text (soft dark shadow so it reads on a bright video). R10 has 3 rows.
Public: LIST_ICONS, T4_LIST, t4_laptop_sprite(icon, width, color, scale), t4_list_sprite(rows, size, color, font, scale, max_w).
Authored in px at short side 1080 (scale = short side / 1080); each sprite has a ~14-26 px glow margin that the placement code
ignores (it measures the visible ink). Arabic / RTL rows are mirrored: icon on the right, text right-aligned."""
import os

from PIL import Image, ImageDraw, ImageFilter

from mt.draw import t2_paint, t2_poly_mask, t2_rgb
from mt.fonts import default_font, is_rtl_text, load_font, shape
from mt.templates.t4.kit import connector, kit_paste, neon_icon

LIST_ICONS = ("globe", "phone", "gear", "database", "cloud")           # row icon by position when a row names none
T4_LIST = {"size": 22, "laptop_w": 172, "pitch": 1.75, "icon": 1.38, "gap": 0.72, "pad": 14}   # pitch / icon / gap in font sizes


def _closed(pts):
    return pts + [pts[0]]


def t4_laptop_sprite(icon="laptop", width=172, color="#19D3FF", scale=1.0):
    """Neon laptop of the given width (px at short side 1080) with '</>' on its screen. icon != 'laptop' -> that kit icon, neon, as is."""
    s = max(0.2, float(scale))
    W, col = max(24, int(round(float(width) * s))), t2_rgb(color)
    if icon != "laptop":
        return neon_icon(icon or "code", max(16, int(W * 0.7)), col)
    g, Hh = int(round(26 * s)), int(round(W * 0.68))
    spr = Image.new("RGBA", (W + 2 * g, Hh + 2 * g), (0, 0, 0, 0))

    def P(pts):
        return [(g + x * W, g + y * Hh) for x, y in pts]
    c = 0.035
    screen = [(0.10 + c, 0.0), (0.90 - c, 0.0), (0.90, 0.045), (0.90, 0.66), (0.10, 0.66), (0.10, 0.045)]
    t2_paint(spr, t2_poly_mask(P(screen)), (4, 12, 30), 0.60)                                   # dark glass behind the glyph
    deck = [(0.13, 0.72), (0.87, 0.72), (1.0, 1.0), (0.0, 1.0)]
    for pts, w in ((_closed(screen), 3.4), (_closed(deck), 3.0), ([(0.22, 0.80), (0.78, 0.80)], 1.8), ([(0.17, 0.88), (0.83, 0.88)], 1.8),
                   ([(0.42, 0.945), (0.58, 0.945)], 2.4)):
        kit_paste(spr, connector(P(pts), col, False, w * s, 9 * s), 0, 0)
    isz = int(round(W * 0.34))
    kit_paste(spr, neon_icon("code", isz, col, 6 * s), g + W * 0.5 - isz / 2.0, g + Hh * 0.33 - isz / 2.0)
    return spr


def _fit_rows(rows, fp, size, avail):
    """Shrink the text size (down to 60 %) then cut the longest row with '...' until icon + gap + text fit `avail`. -> (font, shaped, widths, size)."""
    texts, k = [r["text"] for r in rows], 1.0
    for _ in range(120):
        f = load_font(fp, max(8, int(round(size * k))))
        shaped = [shape(t) for t in texts]
        ws = [f.getlength(t) for t in shaped]
        room = avail - (size * k * (T4_LIST["icon"] + T4_LIST["gap"]))
        if max(ws) <= room or max(len(t) for t in texts) <= 2:
            break
        if k > 0.6:
            k -= 0.05
        else:
            i = ws.index(max(ws))
            texts[i] = texts[i][:-2].rstrip() + "…"
    return f, shaped, ws, size * k


def t4_list_sprite(rows, size=22, color="#19D3FF", font=None, scale=1.0, max_w=None):
    """rows = [{'icon': kit icon name | '', 'text': str}] -> RGBA sprite, or None for no rows. max_w = widest allowed block (px).
    sprite.info: rows (int), rtl (any row is RTL). Never raises on odd values."""
    rows = [r for r in (rows or []) if isinstance(r, dict) and str(r.get("text", "")).strip()]
    if not rows:
        return None
    s = max(0.2, float(scale))
    fp = font if font and os.path.isfile(str(font)) else default_font()
    col = t2_rgb(color)
    f, shaped, ws, sz = _fit_rows(rows, fp, float(size) * s, float(max_w) if max_w else 10.0 ** 6)
    isz, gap, pitch, pad = int(round(sz * T4_LIST["icon"])), sz * T4_LIST["gap"], sz * T4_LIST["pitch"], int(round(T4_LIST["pad"] * s))
    bw = int(max(w + isz + gap for w in ws))
    spr = Image.new("RGBA", (bw + 2 * pad, int(pitch * (len(rows) - 1) + isz) + 2 * pad), (0, 0, 0, 0))
    ink = Image.new("L", spr.size, 0)
    d = ImageDraw.Draw(ink)
    asc, desc = f.getmetrics()
    anyrtl = False
    for i, (r, t, w) in enumerate(zip(rows, shaped, ws)):
        cy = pad + isz / 2.0 + i * pitch
        rtl = is_rtl_text(str(r["text"]))
        anyrtl = anyrtl or rtl
        if r.get("icon"):
            ic = neon_icon(r["icon"], isz, col, max(3.0, isz * 0.16))
            kit_paste(spr, ic, pad + (bw - isz if rtl else 0), cy - isz / 2.0)
        x = pad + (bw - isz - gap if rtl else isz + gap)
        d.text((x, cy + (asc - desc) / 2.0), t, font=f, fill=255, anchor="rs" if rtl else "ls")
    t2_paint(spr, (ink.filter(ImageFilter.GaussianBlur(max(1.5, sz * 0.11))).point(lambda v: min(255, int(v * 1.8))), (0, 0)), (0, 0, 0), 0.7)
    t2_paint(spr, (ink, (0, 0)), (255, 255, 255))
    spr.info["rows"], spr.info["rtl"] = len(rows), anyrtl
    return spr
