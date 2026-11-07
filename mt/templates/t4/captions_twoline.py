"""mt.templates.t4.captions_twoline - Template 4 caption style 'twoline' (ref R9): two stacked lines.
Line 1 = white bold text with a dark outline + drop shadow, the keyword in cyan and larger. Line 2 = the rest of the phrase inside a
dark rounded pill with a cyan glowing border. Decor around the pill: three fading triangles (bottom-left) with a thin line, three
slanted hash marks (bottom-right) and a cyan bar under the pill (centred).
Split rule: a phrase of N words goes to line 1 = the first `words1` words (stream key, default 3; 0 = half of the words), line 2 = the
rest. A phrase with <= words1 words (or one word) is one line: the pill only (decor kept, no line 1).
Reuses: captions._layout (wrap / shrink), visual_order + shape (word-level bidi, Arabic), kit.glass_panel / hazard_stripes / connector.
Public: t4_split_words(tokens, words1), t4_twoline_sprite(...), t4_twoline_items(c, groups, duration, W, H, idx), T4_TWO.
Selected by a caption stream with c["t4_style"] == "twoline" (captions.py dispatches; render.py skips it, like 'pill' / 'glow')."""
import math
import os

from PIL import Image, ImageDraw

from mt.captions import visual_order
from mt.draw import Item, t2_glow, t2_paint, t2_poly_mask
from mt.fonts import default_font, is_rtl_text, shape
from mt.templates.t4.captions import T4_CAP, _canvas_kind, _is_bold, _layout, _num, _ramp_alpha, _stream_font
from mt.templates.t4.captions_glow import _c3
from mt.templates.t4.kit import connector, glass_panel, hazard_stripes, kit_paste

T4_TWO = {
    "y_pct": {"reels": 86.0, "youtube": 90.0},   # % of the canvas height where the PILL'S BOTTOM EDGE sits (R9); the bar hangs below it
    "size": 64, "size_sub": 48,                  # line-1 font px at short side 1080 (scaled for other canvases)
    "line2": 0.92,                               # pill text size = line-1 size x this
    "hl_scale": 1.30, "words1": 3, "min_size_frac": 0.4,
    "pad_x": 0.90, "pad_y": 0.27, "min_w": 4.5,  # pill padding / minimum width, in pill-text sizes
    "text": "#ffffff", "hl": "#1FE3FF", "neon": "#19D3FF",
    "tint": (6, 9, 16, 232),                     # pill fill (dark, nearly opaque)
}


# ---- split ------------------------------------------------------------------------------------------------------------------
def t4_split_words(tokens, words1=3):
    """tokens [[word, hl]] -> (line1, line2). Line 1 = first `words1` words; <= words1 words (or 1 word) -> ([], all) = pill only.
    words1 = 0 -> half of the words (rounded up); junk -> the default 3. Never raises."""
    toks = [[str(t), bool(h)] for t, h in (tokens or []) if str(t).strip()]
    try:
        w1 = int(words1)
    except (TypeError, ValueError, OverflowError):
        w1 = T4_TWO["words1"]
    if w1 < 0:
        w1 = T4_TWO["words1"]
    if w1 == 0:
        w1 = (len(toks) + 1) // 2
    if len(toks) < 2 or len(toks) <= w1:
        return [], toks
    return toks[:w1], toks[w1:]


# ---- text -------------------------------------------------------------------------------------------------------------------
def _fit_line(tokens, font_path, size, avail, hl_scale, min_size):
    """One-line layout (shrinks until the line fits `avail`) -> the captions._layout dict, lines = [all words]."""
    lay = _layout(tokens, font_path, size, avail, 1, hl_scale, min_size)
    if len(lay["lines"]) > 1:                                    # only at the absolute minimum size: keep it on one line anyway
        lay["lines"] = [list(range(len(tokens)))]
        lay["line_w"] = [sum(lay["widths"]) + lay["sp"] * (len(tokens) - 1)]
    return lay


def _jobs(tokens, lay, x_mid, yb):
    """[(x, baseline, shaped, hl, font)] in visual (bidi) order, centred on x_mid."""
    items = [(tokens[i][0], tokens[i][1], lay["widths"][i], lay["fonts"][i]) for i in lay["lines"][0]]
    x, out = x_mid - lay["line_w"][0] / 2.0, []
    for t, hl, wd, ft in visual_order(items, is_rtl_text(" ".join(t for t, _ in tokens))):
        out.append((x, yb, shape(t), hl, ft))
        x += wd + lay["sp"]
    return out


def _draw_line1(spr, jobs, size, col, hlc, bold):
    """Outlined text + hard drop shadow + soft shadow; keyword = hlc with a faint halo. In place on the RGBA sprite."""
    sw = 0 if bold else max(1, int(round(size * 0.028)))        # a regular font gets a thin same-colour stroke = faux bold
    spread = max(2, int(round(size * 0.06)))
    allm, kwm = Image.new("L", spr.size, 0), Image.new("L", spr.size, 0)
    ad, kd = ImageDraw.Draw(allm), ImageDraw.Draw(kwm)
    for x, yb, s, hl, ft in jobs:
        ad.text((x, yb), s, font=ft, fill=255, anchor="ls", stroke_width=sw + spread, stroke_fill=255)
        if hl:
            kd.text((x, yb), s, font=ft, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
    dx, dy = int(round(size * 0.045)), int(round(size * 0.065))
    t2_paint(spr, t2_glow((allm, (0, 0)), size * 0.10, 1.5), (0, 0, 0), 0.55)                 # wide soft shadow
    t2_paint(spr, t2_glow((allm, (dx, dy)), size * 0.03, 2.4), (0, 0, 0), 1.0)                # tight offset shadow + outline
    if kwm.getbbox():
        t2_paint(spr, t2_glow((kwm, (0, 0)), size * 0.14, 1.3), hlc, 0.40)
    d = ImageDraw.Draw(spr)
    for x, yb, s, hl, ft in jobs:
        c = (hlc if hl else col) + (255,)
        d.text((x, yb), s, font=ft, fill=c, anchor="ls", stroke_width=sw, stroke_fill=c)


def _draw_pill_text(spr, jobs, size, col, hlc, bold):
    sw = 0 if bold else max(1, int(round(size * 0.028)))
    d = ImageDraw.Draw(spr)
    for x, yb, s, hl, ft in jobs:
        c = (hlc if hl else col) + (255,)
        d.text((x, yb), s, font=ft, fill=c, anchor="ls", stroke_width=sw, stroke_fill=c)


# ---- decor ------------------------------------------------------------------------------------------------------------------
def _triangles(spr, x, y_base, tri, neon):
    """Three upward triangles, each fainter than the last (R9), each with a soft glow."""
    for i, a in enumerate((1.0, 0.5, 0.22)):
        x0 = x + i * tri * 1.5
        m = t2_poly_mask([(x0, y_base), (x0 + tri * 1.15, y_base), (x0 + tri * 0.575, y_base - tri)])
        t2_paint(spr, t2_glow(m, tri * 0.35, 1.2), neon, 0.6 * a)
        t2_paint(spr, m, neon, a)


def _thin_line(spr, x0, x1, y, size, neon):
    ln = connector([(x0, y), (x1, y)], neon, False, max(1.5, size * 0.03), size * 0.10)
    _ramp_alpha(ln, x0, x1)
    kit_paste(spr, ln, 0, 0)


def _hash_marks(spr, x_right, y_top, hh, neon):
    """Three slanted '///' marks, right edge at x_right, top at y_top."""
    sw, gp, ang = hh * 0.40, hh * 0.22, 32.0
    off = hh * math.tan(math.radians(ang))
    w = off + 3 * sw + 2 * gp + 1.0                              # +1: float-safe so exactly three stripes fit
    kit_paste(spr, hazard_stripes((w, hh), ang, neon, max(3.0, hh * 0.22), sw, gp), x_right - w, y_top)


def _bar(spr, cx, y_mid, bw, bh, neon):
    """Cyan bar with slanted ends (hazard_stripes with a single stripe)."""
    ang = 55.0
    off = bh * math.tan(math.radians(ang))
    kit_paste(spr, hazard_stripes((bw + off, bh), ang, neon, max(4.0, bh * 0.9), bw, bw), cx - (bw + off) / 2.0, y_mid - bh / 2.0)


def _decor(spr, left, right, bottom, ph, size, neon):
    """Decor below the pill (pill = [left, right] x [.., bottom], height ph)."""
    _triangles(spr, left + ph * 0.12, bottom + ph * 0.38, ph * 0.28, neon)
    _thin_line(spr, left + ph * 0.12, left + (right - left) * 0.34, bottom + ph * 0.385, size, neon)
    _hash_marks(spr, right + ph * 0.10, bottom + ph * 0.0, ph * 0.40, neon)
    _bar(spr, (left + right) / 2.0, bottom + ph * 0.17, (right - left) * 0.36, max(5.0, ph * 0.10), neon)


# ---- sprite -----------------------------------------------------------------------------------------------------------------
def t4_twoline_sprite(tokens, font_path, size=64, color="#ffffff", hl="#1FE3FF", neon="#19D3FF", max_w=907, scale=1.0, words1=3):
    """tokens [[word, highlighted]] -> RGBA sprite or None. max_w = the widest allowed pill / line (px).
    sprite.info: lines (1 | 2), pill_h, pill_top / pill_bottom (local y), ink_bottom (lowest decor px), ink_top, pad. Never raises on junk."""
    G = T4_TWO
    l1, l2 = t4_split_words(tokens, words1)
    if not l2:
        return None
    if not font_path or not os.path.isfile(str(font_path)):
        font_path = default_font()
    size = max(10.0, float(size) * scale)
    col, hlc, neon_c = _c3(color, G["text"]), _c3(hl, G["hl"]), _c3(neon, G["neon"])
    max_w = max(80.0, float(max_w))
    s2 = size * G["line2"]
    lay2 = _fit_line(l2, font_path, s2, max(40.0, max_w - 2 * G["pad_x"] * s2), 1.0, 10.0)
    s2 = lay2["size"]
    lay1 = _fit_line(l1, font_path, size, max_w, G["hl_scale"], max(10.0, size * G["min_size_frac"])) if l1 else None
    lh2, bold = lay2["asc"] + lay2["desc"], _is_bold(font_path)
    ph = int(lh2 + 2 * G["pad_y"] * s2)
    pw = int(min(max_w, max(lay2["line_w"][0] + 2 * G["pad_x"] * s2, G["min_w"] * s2)))
    g, ext = int(size * 0.6) + 4, int(ph * 0.4)                  # glow margin, decor overhang left / right of the pill
    lh1 = (lay1["asc"] + lay1["desc"]) if lay1 else 0
    gap = int(size * 0.04) if lay1 else 0
    below = int(ph * 0.46)
    W = int(max(pw, max(lay1["line_w"]) if lay1 else 0) + 2 * (g + ext))
    H = int(lh1 + gap + ph + below + 2 * g)
    spr = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx, pt = W / 2.0, g + lh1 + gap
    if lay1:
        _draw_line1(spr, _jobs(l1, lay1, cx, g + lay1["asc"]), size, col, hlc, bold)
    panel = glass_panel((pw, ph), ph * 0.46, G["tint"], neon_c, 0, max(2.0, size * 0.04), max(6.0, size * 0.16))
    kit_paste(spr, panel, cx - pw / 2.0, pt)
    _draw_pill_text(spr, _jobs(l2, lay2, cx, pt + G["pad_y"] * s2 + lay2["asc"]), s2, col, hlc, bold)
    _decor(spr, cx - pw / 2.0, cx + pw / 2.0, pt + ph, ph, size, neon_c)
    spr.info.update({"lines": 2 if lay1 else 1, "pill_h": ph, "pill_top": pt, "pill_bottom": pt + ph, "ink_top": g,
                     "ink_bottom": pt + ph + below, "pad": g})
    return spr


# ---- items ------------------------------------------------------------------------------------------------------------------
def t4_twoline_items(c, groups, duration, W, H, idx):
    """Items of one 'twoline' caption stream (groups from stream_groups). Canvas-relative; y_pct = the pill's bottom edge."""
    s = min(W, H) / 1080.0
    font = _stream_font(c)
    size = _num(c.get("size"), 8, 400, T4_TWO["size"] if idx == 0 else T4_TWO["size_sub"])
    yp = _num(c.get("y_pct"), 0, 100, T4_TWO["y_pct"][_canvas_kind(W, H)])
    words1 = c.get("words1", T4_TWO["words1"])
    safe = T4_CAP["safe"] * s
    anim, adur = c.get("anim") or "fade", _num(c.get("anim_dur"), 0.0, 5.0, 0.2)
    cache, items = {}, []
    for st, en, toks in groups:
        if st >= duration:
            continue
        key = tuple((t, bool(h)) for t, h in toks)
        if key not in cache:
            cache[key] = t4_twoline_sprite([list(k) for k in key], font, size, c.get("color") or T4_TWO["text"],
                                           c.get("hl_color") or T4_TWO["hl"], c.get("neon") or T4_TWO["neon"],
                                           int(W * T4_CAP["max_w_frac"]), s, words1)
        spr = cache[key]
        if spr is None:
            continue
        i = spr.info
        bottom = min(H * yp / 100.0, H - safe - (i["ink_bottom"] - i["pill_bottom"]))      # the bar / decor stays inside the margin
        bottom = max(bottom, safe + (i["pill_bottom"] - i["ink_top"]))                      # line 1 stays inside the top margin
        cy = bottom - i["pill_bottom"] + spr.height / 2.0
        items.append(Item(spr, st, en, W / 2.0, cy, anim, adur, out=False, rtl=is_rtl_text(" ".join(t for t, _ in toks))))
    return items
