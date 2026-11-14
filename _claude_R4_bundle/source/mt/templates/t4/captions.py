"""mt.templates.t4.captions - Template 4 caption style 'pill' (ref R2): dark rounded pill, thin neon underline with glow, white bold
text, keywords in yellow, slightly larger, with a soft glow.
Reuses mt.captions: stream_groups (parse_markup + keyword matching + grouping), parse_markup / apply_keywords (t4_tokens),
visual_order (word-level bidi). make_rich_sprite cannot be reused as is: it has one font size per sprite and no glow, so the pill
has its own layout (same wrap / balance / shrink idea). Arabic: every word goes through mt.fonts.shape, lines through visual_order.
Public: t4_caption_style(idx, srt_path), t4_pill_sprite(...), t4_tokens(text, keywords), t4_caption_items(cfg, duration), T4_CAP.
cfg: a caption stream with c["t4_style"] == "pill" is drawn by t4_build_items (render.py skips it, like t3_style)."""
import math
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw

from mt.ask import ask_anim, ask_font
from mt.captions import (apply_keywords, ask_caption_style, caption_streams, kw_sequences, parse_markup, parse_srt,
                         split_keywords, stream_groups, visual_order)
from mt.common import D, ask, ask_choice, c_color, c_float, c_int, c_percent
from mt.draw import Item, t2_glow, t2_gradient, t2_grad, t2_mix, t2_paint, t2_rrect_mask
from mt.fonts import default_font, is_rtl_text, load_font, shape, t2_font
from mt.templates.t4.kit import PALETTE, connector, kit_paste
from mt.templates.t4.warn import t4_warn

T4_CAP = {
    "y_pct": {"reels": 84.0, "youtube": 91.5},   # % of the canvas height where the PILL'S BOTTOM EDGE sits (R9 / R2); grows upward
    "max_w_frac": 0.84,                          # pill width <= 84 % of the canvas width
    "safe": 48,                                  # px (short side 1080): the pill + underline never go closer to the canvas edge
    "size": 56, "size_sub": 40,                  # font px at short side 1080 (scaled for other canvases)
    "hl_scale": 1.18, "max_lines": 2, "min_size_frac": 0.5,
    "pad_x": 0.60, "pad_y": 0.17, "min_w": 3.0,  # in font sizes
    "text": "#ffffff", "hl": "#FFC21A", "neon": "#19D3FF",
    "fill_top": (14, 24, 50, 206), "fill_bot": (4, 10, 28, 216),
}


# ---- small helpers ----------------------------------------------------------------------------------------------------------
def _rgb(v, fallback):
    try:
        if isinstance(v, (tuple, list)):
            return tuple(int(x) for x in v[:3])
        return tuple(ImageColor.getrgb(str(v))[:3])
    except (ValueError, TypeError):
        return tuple(ImageColor.getrgb(fallback)[:3])


def _num(v, lo, hi, default):
    try:
        x = float(v)
        return x if lo <= x <= hi else default
    except (TypeError, ValueError):
        return default


def _is_bold(path):
    n = Path(str(path)).stem.lower().replace("-", "").replace(" ", "")
    return any(k in n for k in ("bold", "black", "heavy", "extrabold", "semibold"))


def _canvas_kind(W, H):
    return "reels" if H > W else "youtube"


def t4_tokens(text, keywords=""):
    """'a *b c* d' + 'kw1, kw2' -> [[word, highlighted]]: *stars* via parse_markup, the list via apply_keywords."""
    toks = parse_markup(str(text or ""))
    seqs = kw_sequences(split_keywords(keywords))
    return apply_keywords(toks, seqs) if seqs else toks


# ---- layout -----------------------------------------------------------------------------------------------------------------
def _wrap(widths, sp, limit):
    lines, cur, curw = [], [], 0.0
    for i, wd in enumerate(widths):
        add = wd if not cur else sp + wd
        if cur and curw + add > limit:
            lines.append(cur)
            cur, curw = [i], wd
        else:
            cur.append(i)
            curw += add
    if cur:
        lines.append(cur)
    return lines


def _layout(tokens, font_path, size, avail, max_lines, hl_scale, min_size):
    """Shrink until the text fits `avail` px in <= max_lines lines -> dict(size, fonts, widths, lines, line_w, sp, asc, desc)."""
    while True:
        f, fh = load_font(font_path, int(round(size))), load_font(font_path, int(round(size * hl_scale)))
        sp = f.getlength(" ")
        fonts = [fh if hl else f for _, hl in tokens]
        widths = [ft.getlength(shape(t)) for (t, _), ft in zip(tokens, fonts)]
        lines = _wrap(widths, sp, avail)
        n = len(lines)
        total = sum(widths) + sp * (len(widths) - 1)
        if n > 1:                                               # balance (no tiny last line)
            for target in (total / n * 1.08, total / n * 1.2, avail):
                cand = _wrap(widths, sp, min(target, avail))
                if len(cand) == n:
                    lines = cand
                    break
        line_w = [sum(widths[i] for i in ln) + sp * (len(ln) - 1) for ln in lines]
        if (len(lines) <= max_lines and max(line_w) <= avail) or size <= min_size:
            break
        size = max(min_size, size * 0.92)
    asc = max(f.getmetrics()[0], fh.getmetrics()[0])
    desc = max(f.getmetrics()[1], fh.getmetrics()[1])
    return {"size": size, "fonts": fonts, "widths": widths, "lines": lines, "line_w": line_w, "sp": sp, "asc": asc, "desc": desc}


def _ramp_alpha(sprite, x0, x1):
    """Fade a horizontal neon line out at both ends (bright in the middle, as the underline in R2)."""
    ox = sprite.info.get("origin", (0, 0))[0]
    ramp = t2_gradient(sprite.size, [(0, (255, 255, 255, 0)), (0.22, (255, 255, 255, 255)), (0.78, (255, 255, 255, 255)),
                                     (1, (255, 255, 255, 0))], 0, (ox + x0, 0, ox + x1, 1))
    sprite.putalpha(ImageChops.multiply(sprite.getchannel("A"), ramp.getchannel("A")))
    return sprite


def _underline(spr, x0, x1, y, size, neon):
    """Two stacked neon lines (blue wide + cyan core), faded at the ends, sitting on the pill's bottom edge."""
    wd, gl = max(2.0, size * 0.06), size * 0.16
    base = t2_mix(neon, PALETTE["blue"], 0.55)
    for col, w, g, a, (a0, a1) in ((base, wd * 1.5, gl * 1.3, 0.8, (x0, x1)),
                                   (neon, wd, gl, 1.0, (x0 + (x1 - x0) * 0.12, x1 - (x1 - x0) * 0.12))):
        ln = connector([(a0, y), (a1, y)], col, False, w, g)
        _ramp_alpha(ln, a0, a1)
        if a < 1.0:
            ln.putalpha(ln.getchannel("A").point(lambda v: int(v * a)))
        kit_paste(spr, ln, 0, 0)


def t4_pill_sprite(tokens, font_path, size=56, color="#ffffff", hl="#FFC21A", neon="#19D3FF", max_w=907, scale=1.0):
    """tokens [[word, highlighted]] -> RGBA sprite (pill + underline + text) or None. The pill's own height is in
    sprite.info['pill_h'], the glow margin in sprite.info['pad']; max_w = the widest allowed PILL (px). Never raises on odd tokens."""
    tokens = [[str(t), bool(h)] for t, h in (tokens or []) if str(t).strip()]
    if not tokens:
        return None
    C = T4_CAP
    if not font_path or not os.path.isfile(str(font_path)):
        font_path = default_font()
    size = max(10.0, float(size) * scale)
    col, hlc, neon_c = _rgb(color, C["text"]), _rgb(hl, C["hl"]), _rgb(neon, C["neon"])
    lay = _layout(tokens, font_path, size, max(40.0, max_w - 2 * C["pad_x"] * size), C["max_lines"], C["hl_scale"],
                  max(12.0, size * C["min_size_frac"]))
    size = lay["size"]
    padx, pady = C["pad_x"] * size, C["pad_y"] * size
    lh, gap = lay["asc"] + lay["desc"], int(size * 0.10)
    block = len(lay["lines"]) * lh + (len(lay["lines"]) - 1) * gap
    w = int(min(max_w, max(max(lay["line_w"]) + 2 * padx, C["min_w"] * size)))
    h = int(block + 2 * pady)
    g = int(size * 0.55) + 4
    spr = Image.new("RGBA", (w + 2 * g, h + 2 * g), (0, 0, 0, 0))
    t2_paint(spr, t2_rrect_mask((g, g, g + w, g + h), min(h / 2.0, size * 0.36)), t2_grad([(0, C["fill_top"]), (1, C["fill_bot"])], 90))
    _underline(spr, g + w * 0.10, g + w * 0.90, g + h + 1, size, neon_c)
    _draw_text(spr, tokens, lay, g, w, pady, col, hlc, _is_bold(font_path), size)
    spr.info["pill_h"], spr.info["pad"] = h, g
    return spr


def _draw_text(spr, tokens, lay, g, w, pady, col, hlc, bold, size):
    """Words in visual (bidi) order on a shared baseline per line; keyword glow first, then all text."""
    base_rtl = is_rtl_text(" ".join(t for t, _ in tokens))
    sw = 0 if bold else max(1, int(round(size * 0.028)))        # a regular font gets a thin same-colour stroke = faux bold
    glow = Image.new("L", spr.size, 0)
    text = ImageDraw.Draw(spr)
    gd = ImageDraw.Draw(glow)
    lh, gap = lay["asc"] + lay["desc"], int(size * 0.10)
    jobs = []
    for li, ln in enumerate(lay["lines"]):
        items = [(tokens[i][0], tokens[i][1], lay["widths"][i], lay["fonts"][i]) for i in ln]
        order = visual_order(items, base_rtl)                  # items = (text, hl, width, font); only [0] is read
        x = g + (w - lay["line_w"][li]) / 2.0
        yb = g + pady + lay["asc"] + li * (lh + gap)
        for t, hl, wd, ft in order:
            jobs.append((x, yb, shape(t), hl, ft))
            x += wd + lay["sp"]
    for x, yb, s, hl, ft in jobs:
        if hl:
            gd.text((x, yb), s, font=ft, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
    if glow.getbbox():
        t2_paint(spr, t2_glow((glow, (0, 0)), size * 0.12, 1.9), hlc, 0.85)
    for x, yb, s, hl, ft in jobs:
        c = hlc if hl else col
        text.text((x, yb), s, font=ft, fill=c + (255,), anchor="ls", stroke_width=sw, stroke_fill=c + (255,))


# ---- items ------------------------------------------------------------------------------------------------------------------
def _stream_font(c):
    f = c.get("font")
    if f and os.path.isfile(str(f)):
        return str(f)
    if f:
        t4_warn("t4 captions: font '%s' not found - using the default bold Arabic font." % Path(str(f)).name)
    p = t2_font("arabic", "ع")[0]
    return p if p and os.path.isfile(p) else default_font()


def _stream_items(cfg, c, duration, W, H, idx):
    try:
        groups = stream_groups(parse_srt(c["srt"]), c)
    except Exception as e:
        t4_warn("t4 captions: SRT '%s' could not be read (%s) - those captions are skipped." % (Path(str(c.get("srt"))).name, e))
        return []
    if c.get("t4_style") == "glow":                                                  # style 'glow' = its own sprite builder
        from mt.templates.t4.captions_glow import t4_glow_items
        return t4_glow_items(c, groups, duration, W, H, idx)
    if c.get("t4_style") == "twoline":                                               # style 'twoline' = its own sprite builder (R9)
        from mt.templates.t4.captions_twoline import t4_twoline_items
        return t4_twoline_items(c, groups, duration, W, H, idx)
    s = min(W, H) / 1080.0
    font = _stream_font(c)
    size = _num(c.get("size"), 8, 400, T4_CAP["size"] if idx == 0 else T4_CAP["size_sub"])
    yp = _num(c.get("y_pct"), 0, 100, T4_CAP["y_pct"][_canvas_kind(W, H)])
    safe = T4_CAP["safe"] * s
    anim, adur = c.get("anim") or "fade", _num(c.get("anim_dur"), 0.0, 5.0, 0.2)
    cache, items = {}, []
    for st, en, toks in groups:
        if st >= duration:
            continue
        key = tuple((t, bool(h)) for t, h in toks)
        if key not in cache:
            cache[key] = t4_pill_sprite([list(k) for k in key], font, size, c.get("color") or T4_CAP["text"],
                                        c.get("hl_color") or T4_CAP["hl"], c.get("neon") or T4_CAP["neon"],
                                        int(W * T4_CAP["max_w_frac"]), s)
        spr = cache[key]
        if spr is None:
            continue
        h, g = spr.info["pill_h"], spr.info["pad"]
        bottom = min(H * yp / 100.0, H - safe - 0.16 * size * s)                  # keep the pill + glow inside the safe margin
        bottom = max(bottom, safe + h)
        items.append(Item(spr, st, en, W / 2.0, bottom - h / 2.0, anim, adur, out=False,
                          rtl=is_rtl_text(" ".join(t for t, _ in toks))))
    return items


def t4_caption_items(cfg, duration):
    """Items of every caption stream with t4_style == 'pill' (canvas-relative; the video fills the canvas)."""
    try:
        W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        t4_warn("t4 captions: the job has no canvas - captions skipped.")
        return []
    out = []
    for i, c in enumerate(caption_streams(cfg)):
        if c.get("t4_style") in ("pill", "glow", "twoline"):
            out += _stream_items(cfg, c, duration, W, H, i)
    return out


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_caption_style(idx, srt_path):
    """Questions for one Template 4 caption stream: style (pill | plain), font, size, colours, keywords, word-by-word / phrases."""
    print(f"\n--- Caption style for SRT #{idx + 1}: {Path(srt_path).name} ---")
    k = "t4cap" + str(idx)
    st = ask_choice("Caption style:", ["Pill - dark rounded pill, neon underline, yellow keywords (reference R2)",
                                       "Plain text - the classic captions, no plate",
                                       "Glow - no plate, white text + shadow, blue neon keyword with swoosh and sparks (reference R3)",
                                       "Two lines - shadowed text with a cyan keyword over a dark pill with a glowing border (reference R9)"],
                    default=1, key=k + "_style")
    if st == 2:
        return ask_caption_style(idx, srt_path)
    glow, two = st == 3, st == 4
    kg = k + ("g" if glow else "t" if two else "")                                  # remembered answers are per style
    from mt.templates.t4.captions_glow import T4_GLOW                                # defaults of the glow / twoline styles (own tables)
    from mt.templates.t4.captions_twoline import T4_TWO
    dflt = T4_GLOW if glow else T4_TWO if two else T4_CAP
    if not (D.get("cap_font" + k) and os.path.isfile(D.get("cap_font" + k))):
        D["cap_font" + k] = t2_font("arabic", "ع")[0] or ""
    c = {"srt": srt_path, "t4_style": "glow" if glow else "twoline" if two else "pill", "ref": "canvas"}
    c["font"] = ask_font("Caption font (a bold font: Cairo / Tajawal Bold; it must have Arabic for Arabic text)", "cap_font" + k)
    c["size"] = ask("Caption font size (px, for a 1080 px short side - same look on both canvases%s)" % (
                    "; this is line 1, the pill text is a bit smaller" if two else ""),
                    default=dflt["size"] if idx == 0 else dflt["size_sub"], key=kg + "_size", cast=c_int)
    c["color"] = ask("Text color", default="white", key=k + "_color", cast=c_color)
    c["hl_color"] = ask("Keyword color (%s in the reference)" % ("blue" if glow else "cyan" if two else "yellow"), default=dflt["hl"],
                        key=kg + "_hl", cast=c_color)
    c["neon"] = ask("Glow / swoosh color" if glow else "Pill border + decor glow color" if two else "Underline glow color",
                    default=dflt["neon"], key=kg + "_neon", cast=c_color)
    c["keywords"] = ask("Words to highlight automatically, comma separated "
                        "(Enter = none; you can also put *stars* around words inside the SRT)", allow_empty=True) or ""
    c["stroke_color"], c["stroke_w"], c["shadow"] = "#000000", 0, False
    mode = ask_choice("Show captions as:", ["Word by word", "Whole phrases (auto grouped)"], default=2, key=k + "_mode")
    c["mode"] = "words" if mode == 1 else "phrase"
    if mode == 1:
        c["words_per_group"] = ask("Words shown at the same time (1 = word by word)", default=1, key=k + "_wpg", cast=c_int)
    else:
        c["max_words"] = ask("Max words per phrase (only used when the SRT is word-by-word)", default=8, key=k + "_maxw", cast=c_int)
    if two:
        c["words1"] = ask("Words on line 1 (the rest goes in the pill; a phrase with that many words or fewer is the pill only; "
                          "0 = half of the words)", default=T4_TWO["words1"], key=kg + "_w1", cast=c_int)
    c["y_pct"] = ask(f"Vertical position of the {'text' if glow else 'pill'}'s bottom edge (percent of the canvas height; Enter = "
                     f"{dflt['y_pct']['reels']:g} reels / {dflt['y_pct']['youtube']:g} YouTube)", allow_empty=True, cast=c_percent)
    c["anim"] = ask_anim("Caption animation", default="pop" if mode == 1 else "fade", key=k + "_anim")
    c["anim_dur"] = ask("Animation duration (seconds)", default=0.12 if mode == 1 else 0.25, key=k + "_adur", cast=c_float)
    return c
