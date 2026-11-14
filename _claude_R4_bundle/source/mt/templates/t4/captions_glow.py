"""mt.templates.t4.captions_glow - Template 4 caption style 'glow' (ref R3, bottom caption): no plate.
Big white bold text with a soft black shadow; the keyword in bright blue (vertical gradient) with a neon halo, a short tapered
curved swoosh under it and three small spark lines above its start; a faint horizontal blue glow line behind the whole caption.
Own sprite builder only: layout (_layout / _wrap), colours, font, bidi and the line ramp are reused from t4/captions.py.
Arabic: every word goes through mt.fonts.shape, lines through visual_order (word-level bidi), like the pill style.
Public: t4_glow_sprite(...), t4_glow_items(c, groups, duration, W, H, idx), T4_GLOW.
Selected by a caption stream with c["t4_style"] == "glow" (captions.py dispatches; render.py skips it, like 'pill')."""
import math
import os

from PIL import Image, ImageDraw

from mt.captions import visual_order
from mt.draw import Item, t2_glow, t2_grad, t2_lighten, t2_mix, t2_paint
from mt.fonts import default_font, is_rtl_text, shape
from mt.templates.t4.captions import (T4_CAP, _canvas_kind, _is_bold, _layout, _num, _ramp_alpha, _rgb, _stream_font)
from mt.templates.t4.kit import connector, kit_paste

T4_GLOW = {
    "y_pct": {"reels": 82.0, "youtube": 88.0},   # % of the canvas height where the TEXT BLOCK'S bottom edge sits (swoosh hangs below it)
    "size": 76, "size_sub": 54,                  # font px at short side 1080 (scaled for other canvases)
    "hl_scale": 1.35, "max_lines": 2, "min_size_frac": 0.5,
    "text": "#ffffff", "hl": "#2DB4FF", "neon": "#19B4FF",
    "spark_side": "left",                        # 'left' = visual left edge of the keyword (as R3, also for Arabic) | 'start' = reading start
    "spark_angles": (148, 112, 76), "spark_len": (0.34, 0.44, 0.30),   # degrees (y up) / length in keyword sizes
}


def _c3(v, fallback):
    """Colour -> exactly (r, g, b); a short / odd tuple falls back (the builder never raises)."""
    c = _rgb(v, fallback)
    return c if len(c) == 3 else _rgb(fallback, fallback)


# ---- small drawing helpers ---------------------------------------------------------------------------------------------------
def _soft(spr, mask, color, radius, strength, opacity=1.0):
    """Paint a blurred copy of an 'L' mask (full sprite size) in `color`."""
    if mask.getbbox():
        t2_paint(spr, t2_glow((mask, (0, 0)), radius, strength), color, opacity)


def _h_line(spr, x0, x1, y, size, neon):
    """Faint horizontal glow line behind the caption: blue, bright in the middle, faded out at both ends."""
    ln = connector([(x0, y), (x1, y)], t2_mix(neon, (0, 90, 255), 0.35), False, max(2.0, size * 0.05), size * 0.16)
    _ramp_alpha(ln, x0, x1)
    ln.putalpha(ln.getchannel("A").point(lambda v: int(v * 0.8)))
    kit_paste(spr, ln, 0, 0)


def _swoosh(spr, x0, x1, y, hl_size, neon):
    """Tapered curved underline (thick in the middle, pointed ends, low on the left and rising to the right) with a neon glow."""
    w = max(8.0, x1 - x0)
    rise, tmax, ss = min(hl_size * 0.14, w * 0.10), max(3.0, hl_size * 0.17), 4
    pw, ph = int(w) + 8, int(rise + tmax) + 8
    big = Image.new("L", (pw * ss, ph * ss), 0)
    top, bot = [], []
    for i in range(41):
        t = i / 40.0
        px = (1 - t) ** 2 * 0 + 2 * (1 - t) * t * (0.55 * w) + t * t * w          # quadratic bezier A=(0,rise) C=(.55w,rise) B=(w,0)
        py = (1 - t) ** 2 * rise + 2 * (1 - t) * t * rise + t * t * 0
        th = tmax * math.sin(math.pi * (t ** 0.8)) ** 0.9 / 2.0
        top.append(((4 + px) * ss, (4 + tmax / 2 + py - th) * ss))
        bot.append(((4 + px) * ss, (4 + tmax / 2 + py + th) * ss))
    ImageDraw.Draw(big).polygon(top + bot[::-1], fill=255)
    m = big.resize((pw, ph), Image.LANCZOS)
    ox, oy = int(round(x0)) - 4, int(round(y - tmax / 2 - rise / 2)) - 4
    _soft_at(spr, m, (ox, oy), neon, hl_size * 0.10, 2.2, 0.9)
    core = t2_lighten(neon, 0.55)
    t2_paint(spr, (m, (ox, oy)), t2_grad([(0, t2_mix(neon, (0, 40, 160), 0.25)), (0.5, core), (1, neon)], 0, (x0, 0, x1, 1)))


def _soft_at(spr, m, off, color, radius, strength, opacity):
    t2_paint(spr, t2_glow((m, off), radius, strength), color, opacity)


def _sparks(spr, cx, cy, side, hl_size, neon):
    """Three short round-capped strokes fanning out from (cx, cy): white core, blue glow. side -1 = leaning left, +1 = right."""
    ss, r0 = 4, hl_size * 0.26
    m = Image.new("L", (spr.width * ss, spr.height * ss), 0)
    d = ImageDraw.Draw(m)
    lw = max(2.5, hl_size * 0.07) * ss
    for ang, ln in zip(T4_GLOW["spark_angles"], T4_GLOW["spark_len"]):
        a = math.radians(ang if side < 0 else 180 - ang)
        p0 = (cx + math.cos(a) * r0, cy - math.sin(a) * r0)
        p1 = (cx + math.cos(a) * (r0 + ln * hl_size), cy - math.sin(a) * (r0 + ln * hl_size))
        d.line([(p0[0] * ss, p0[1] * ss), (p1[0] * ss, p1[1] * ss)], fill=255, width=int(lw))
        for p in (p0, p1):
            d.ellipse((p[0] * ss - lw / 2, p[1] * ss - lw / 2, p[0] * ss + lw / 2, p[1] * ss + lw / 2), fill=255)
    m = m.resize(spr.size, Image.LANCZOS)
    _soft(spr, m, neon, hl_size * 0.10, 2.2, 0.95)
    t2_paint(spr, (m, (0, 0)), (255, 255, 255, 255))


# ---- layout of the placed words ----------------------------------------------------------------------------------------------
def _place(tokens, lay, base_rtl, x_mid, y0, gaps):
    """-> (jobs, runs). jobs = [(x, baseline, shaped, hl, font, run_id | None)] in visual order; runs = [dict(x0, x1, yb, top, line)]
    (consecutive highlighted words on one line = one run)."""
    jobs, runs, lh = [], [], lay["asc"] + lay["desc"]
    for li, ln in enumerate(lay["lines"]):
        items = [(tokens[i][0], tokens[i][1], lay["widths"][i], lay["fonts"][i]) for i in ln]
        x = x_mid - lay["line_w"][li] / 2.0
        yb = y0 + lay["asc"] + li * lh + sum(gaps[:li])
        cur = None
        for t, hl, wd, ft in visual_order(items, base_rtl):
            s = shape(t)
            if hl:
                top = yb + ft.getbbox(s, anchor="ls")[1]
                if cur is None:
                    cur = {"x0": x, "x1": x + wd, "yb": yb, "top": top, "line": li}
                    runs.append(cur)
                cur["x1"], cur["top"] = x + wd, min(cur["top"], top)
            else:
                cur = None
            jobs.append((x, yb, s, hl, ft, len(runs) - 1 if hl else None))
            x += wd + lay["sp"]
    return jobs, runs


def _text_masks(shape_size, jobs, sw, spread):
    """'L' masks: every word (shadow source, with extra spread) and the keyword words of each run."""
    allm = Image.new("L", shape_size, 0)
    ad = ImageDraw.Draw(allm)
    kw = {}
    for x, yb, s, hl, ft, rid in jobs:
        ad.text((x, yb), s, font=ft, fill=255, anchor="ls", stroke_width=sw + spread, stroke_fill=255)
        if hl:
            m = kw.setdefault(rid, Image.new("L", shape_size, 0))
            ImageDraw.Draw(m).text((x, yb), s, font=ft, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
    return allm, kw


def t4_glow_sprite(tokens, font_path, size=76, color="#ffffff", hl="#2DB4FF", neon="#19B4FF", max_w=907, scale=1.0, line_w=None):
    """tokens [[word, highlighted]] -> RGBA sprite or None. max_w = the widest text line (px); line_w = length of the glow line behind
    the caption (None = text width + 2.4 sizes). Layout numbers in sprite.info: block_h (text block), above / below (sparks / swoosh
    extent outside the block), pad (soft glow margin), block_top (local y of the block's top). Never raises on odd tokens."""
    tokens = [[str(t), bool(h)] for t, h in (tokens or []) if str(t).strip()]
    if not tokens:
        return None
    G = T4_GLOW
    if not font_path or not os.path.isfile(str(font_path)):
        font_path = default_font()
    size = max(10.0, float(size) * scale)
    col, hlc, neon_c = _c3(color, G["text"]), _c3(hl, G["hl"]), _c3(neon, G["neon"])
    lay = _layout(tokens, font_path, size, max(40.0, float(max_w)), G["max_lines"], G["hl_scale"], max(12.0, size * G["min_size_frac"]))
    size = lay["size"]
    hl_size, has_hl = size * G["hl_scale"], any(h for _, h in tokens)
    lh, n = lay["asc"] + lay["desc"], len(lay["lines"])
    has = [any(tokens[i][1] for i in ln) for ln in lay["lines"]]
    gaps = [int(size * 0.10) + (int(size * 0.24) if has[i] else 0) + (int(hl_size * 0.38) if has[i + 1] else 0)
            for i in range(n - 1)]                              # room for the swoosh under line i and the sparks over line i + 1
    block_h = n * lh + sum(gaps)
    above, below = (int(hl_size * 0.62), int(hl_size * 0.42)) if has_hl else (0, 0)
    g = int(size * 0.55) + 4
    side_pad = g + (int(hl_size * 0.60) if has_hl else 0)
    tw = max(lay["line_w"])
    lw = float(line_w) if line_w else tw + 2.4 * size
    W, H = int(max(tw + 2 * side_pad, lw + 2 * g)), int(block_h + above + below + 2 * g)
    spr = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    y0 = g + above
    base_rtl = is_rtl_text(" ".join(t for t, _ in tokens))
    jobs, runs = _place(tokens, lay, base_rtl, W / 2.0, y0, gaps)
    sw = 0 if _is_bold(font_path) else max(1, int(round(size * 0.028)))   # a regular font gets a thin same-colour stroke = faux bold
    allm, kwm = _text_masks(spr.size, jobs, sw, max(2, int(round(size * 0.05))))
    _h_line(spr, (W - lw) / 2.0, (W + lw) / 2.0, y0 + block_h * 0.56, size, neon_c)
    for m in kwm.values():                                      # neon halo of the keyword (under the shadow: dark rim, blue halo outside)
        _soft(spr, m, neon_c, size * 0.24, 1.7, 0.85)
        _soft(spr, m, neon_c, size * 0.07, 2.0, 0.75)
    _soft(spr, allm.point(lambda v: int(v * 0.9)), (0, 0, 0), size * 0.06, 2.8, 1.0)   # soft black shadow
    for x, yb, s, hl_, ft, rid in jobs:
        if not hl_:
            ImageDraw.Draw(spr).text((x, yb), s, font=ft, fill=col + (255,), anchor="ls", stroke_width=sw, stroke_fill=col + (255,))
    for rid, r in enumerate(runs):
        top_c, bot_c = t2_lighten(hlc, 0.45), t2_mix(hlc, (10, 60, 220), 0.25)
        box = (0, r["top"], 1, r["yb"] + lay["desc"])
        t2_paint(spr, (kwm[rid], (0, 0)), t2_grad([(0, top_c), (0.55, hlc), (1, bot_c)], 90, box))
        _swoosh(spr, r["x0"] - hl_size * 0.04, r["x1"] + hl_size * 0.02, r["yb"] + lay["desc"] * 0.55 + hl_size * 0.10, hl_size, neon_c)
        left = G["spark_side"] != "start" or not base_rtl
        ex = r["x0"] + hl_size * 0.10 if left else r["x1"] - hl_size * 0.10
        _sparks(spr, ex, r["top"] - hl_size * 0.04, -1 if left else 1, hl_size, neon_c)
    spr.info.update({"block_h": block_h, "above": above, "below": below, "pad": g, "block_top": y0})
    return spr


# ---- items --------------------------------------------------------------------------------------------------------------------
def t4_glow_items(c, groups, duration, W, H, idx):
    """Items of one 'glow' caption stream (groups from stream_groups). Canvas-relative; y_pct = the text block's bottom edge."""
    s = min(W, H) / 1080.0
    font = _stream_font(c)
    size = _num(c.get("size"), 8, 400, T4_GLOW["size"] if idx == 0 else T4_GLOW["size_sub"])
    yp = _num(c.get("y_pct"), 0, 100, T4_GLOW["y_pct"][_canvas_kind(W, H)])
    safe = T4_CAP["safe"] * s
    anim, adur = c.get("anim") or "fade", _num(c.get("anim_dur"), 0.0, 5.0, 0.2)
    cache, items = {}, []
    for st, en, toks in groups:
        if st >= duration:
            continue
        key = tuple((t, bool(h)) for t, h in toks)
        if key not in cache:
            cache[key] = t4_glow_sprite([list(k) for k in key], font, size, c.get("color") or T4_GLOW["text"],
                                        c.get("hl_color") or T4_GLOW["hl"], c.get("neon") or T4_GLOW["neon"],
                                        int(W * T4_CAP["max_w_frac"]), s, W - 2 * safe)
        spr = cache[key]
        if spr is None:
            continue
        i = spr.info
        bottom = min(H * yp / 100.0, H - safe - i["below"])                        # swoosh + sparks stay inside the safe margin
        bottom = max(bottom, safe + i["above"] + i["block_h"])
        cy = bottom - (i["block_top"] + i["block_h"]) + spr.height / 2.0
        items.append(Item(spr, st, en, W / 2.0, cy, anim, adur, out=False, rtl=is_rtl_text(" ".join(t for t, _ in toks))))
    return items
