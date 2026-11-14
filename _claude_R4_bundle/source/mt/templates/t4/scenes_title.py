"""mt.templates.t4.scenes_title - Template 4 scenes: widget 'title_block' (refs R5 portrait / R6 landscape, measured in T4_P14_ADDENDUM).
[ </> icon (in a hex-cut badge on portrait) ]  TWO-TONE TITLE        row centred on the icon, text left-aligned (RTL: mirrored)
                                               T R A C K E D   S U B T I T L E
spec keys (all optional): title 'Web Development', subtitle 'Building Digital Solutions', accent '' (word(s) of the title to colour; ''
  = the last word, a one-word title = all of it), icon 'code' (kit icon name, ''/'none' = no icon), color '#14F1FA' (accent + icon + badge),
  text_color '#FFFFFF', badge None (auto: portrait yes / landscape no) | True | False, panel False (dark glass plate over the whole slot,
  R5), font '' (path; '' = project default), caps True, size None (title font px at short side 1080; None = from the slot height),
  tracking 'auto' (subtitle tracking in em; 'auto' = fit the subtitle to 0.95 x the title width, as R5 / R6) | a number, rtl None (auto).
Everything is derived from the slot box: icon ~ 0.62 h (badge 0.65 h), title font ~ 0.39 h (badge) / 0.64 h (bare), shrunk to fit the
width left of the icon (min 55 %, then cut with an ellipsis), subtitle font 0.465 x title. Arabic / RTL: no tracking, words shaped one by one.
One static sprite per (spec, size), cached. Public: T4_TITLE_BLOCK, t4_title_block(spec, box, ctx), t4_ask_title_block()."""
import os

from PIL import Image, ImageColor, ImageDraw, ImageFilter

from mt.common import ask, ask_choice, c_color, yn
from mt.draw import t2_rgb
from mt.fonts import default_font, is_rtl_text, load_font, shape
from mt.templates.t4.kit import glass_panel, icon, kit_paste, neon_icon
from mt.templates.t4.nameplate import _cached, _flt
from mt.templates.t4.nameplate_tags import _is_bold
from mt.templates.t4.scenes_reg import register_widget
from mt.templates.t4.warn import t4_warn

T4_TITLE_BLOCK = {"title": "Web Development", "subtitle": "Building Digital Solutions", "accent": "", "icon": "code", "color": "#14F1FA",
                  "text_color": "#FFFFFF", "badge": None, "panel": False, "font": "", "caps": True, "size": None, "tracking": "auto", "rtl": None}
GAP_ICON, GAP_LINES, PANEL_PAD, BARE_PAD, GLOW_PAD = 32.0, 20.0, 21.0, 4.0, 40.0      # px at short side 1080
ICON_H = {True: 0.65, False: 0.62}          # icon block height / slot height (badge / bare glyph)
TITLE_K = {True: 0.39, False: 0.64}         # title font px / slot height: 86 / 220 (R5), 74 / 116 (R6)
SUB_K, SUB_FIT = 0.465, 0.95                # subtitle font = 0.465 x title; subtitle width = 0.95 x title width
BADGE_ASPECT, GLYPH_IN_BADGE = 175 / 143.0, (0.82, 0.60)     # R5 badge 175 x 143; glyph 144 x 86 inside it (share of the badge w / h)
TINT_BADGE, TINT_PANEL = (4, 10, 26, 235), (5, 12, 30, 200)
_TB = {}


# ---- spec -------------------------------------------------------------------------------------------------------------------
def _yes(v, default):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower() if isinstance(v, str) else ""
    return True if s in ("1", "true", "yes", "y", "on") else False if s in ("0", "false", "no", "n", "off") else default


def _color(v, default):
    """'#rrggbb' / name / (r, g, b) -> kept; anything Pillow cannot read -> default (t2_rgb would fall back to the poster lime)."""
    try:
        if isinstance(v, (tuple, list)) and len(v) >= 3:
            return tuple(int(c) for c in v[:3])
        return v if isinstance(v, str) and ImageColor.getrgb(v.strip()) else default
    except (ValueError, TypeError):
        return default


def _spec(raw):
    """Complete, clean spec (never raises; junk -> defaults)."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(T4_TITLE_BLOCK)
    for k in ("title", "subtitle", "accent", "font"):
        v = raw.get(k, out[k])
        out[k] = str(v).strip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else out[k]
    ic = raw.get("icon", out["icon"])
    ic = str(ic).strip().lower() if isinstance(ic, str) else out["icon"]
    out["icon"] = "" if ic in ("", "none", "off", "-", "false") else ic
    for k in ("color", "text_color"):
        out[k] = _color(raw.get(k), out[k])
    b = raw.get("badge")
    out["badge"] = None if b is None or (isinstance(b, str) and b.strip().lower() in ("", "auto")) else _yes(b, False)
    out["panel"], out["caps"] = _yes(raw.get("panel"), False), _yes(raw.get("caps"), True)
    sz = raw.get("size")
    out["size"] = _flt(sz, 8, 600, 0.0) or None if sz is not None else None
    tr = raw.get("tracking", "auto")
    out["tracking"] = "auto" if isinstance(tr, str) and tr.strip().lower() in ("", "auto") else _flt(tr, -0.1, 1.0, 0.21)
    r = raw.get("rtl")
    out["rtl"] = None if r is None else _yes(r, False)
    return out


def _tokens(title, accent):
    """[(word, is_accent)]: accent = the given word(s) (case-insensitive, must match whole consecutive words), else the last word."""
    words = title.split()
    flags = [False] * len(words)
    acc = accent.split() if accent else []
    if acc:
        low, n = [w.casefold() for w in words], len(acc)
        for i in range(len(words) - n + 1):
            if low[i:i + n] == [a.casefold() for a in acc]:
                flags[i:i + n] = [True] * n
                break
        else:
            t4_warn("title_block: accent '%s' is not a word of the title - using the last word." % accent)
    if not any(flags) and words:
        flags[-1] = True                       # default: the last word (a one-word title = all of it)
    return list(zip(words, flags))


# ---- text -------------------------------------------------------------------------------------------------------------------
def _put(d, x, y, text, font, fill, track, rtl, stroke):
    """Draw text with its baseline at y, left edge x. track (px) > 0 / < 0 and LTR -> char by char; otherwise one run (kerning / shaping kept)."""
    kw = {"font": font, "fill": fill, "anchor": "ls", "stroke_width": stroke, "stroke_fill": fill}
    if track and not rtl:
        for ch in text:
            d.text((x, y), ch, **kw)
            x += font.getlength(ch) + track
    else:
        d.text((x, y), text, **kw)


def _words(tokens, font, track, rtl):
    """-> ([(shaped word, accent, offset from the start edge, width)], total width). RTL words run right to left (offset from the right edge)."""
    gap, out, off = font.getlength(" ") + track, [], 0.0
    for word, acc in tokens:
        if track and not rtl:
            sh, ww = word, sum(font.getlength(c) for c in word) + track * (len(word) - 1)
        else:
            sh = shape(word)
            ww = font.getlength(sh)
        out.append((sh, acc, off, ww))
        off += ww + gap
    return out, (off - gap if out else 0.0)


def _fit_title(tokens, fp, base, avail, track_em, rtl):
    """Shrink the font (down to 55 %), then cut the last word with an ellipsis. -> (font, size, words, width, tokens)."""
    k, tokens = 1.0, list(tokens)
    while True:
        fs = max(8, int(round(base * k)))
        font = load_font(fp, fs)
        words, tw = _words(tokens, font, track_em * fs, rtl)
        if tw <= avail or k <= 0.55 + 1e-9:
            break
        k = max(0.55, k - 0.05)
    for _ in range(200):
        if tw <= avail or not tokens:
            break
        w, a = tokens[-1]
        tokens[-1] = (w.rstrip("…")[:-1] + "…", a) if len(w.rstrip("…")) > 1 else None
        if tokens[-1] is None:
            tokens.pop()
        words, tw = _words(tokens, font, track_em * fs, rtl)
    return font, fs, words, tw, tokens


def _sub_metrics(text, font, fs, tw, track_em, rtl):
    """-> (shaped text, tracking px, width). Tracking: given em, else fitted so the width = SUB_FIT x the title width (0.04 .. 0.45 em)."""
    if rtl or len(text) < 2:
        sh = shape(text)
        return sh, 0.0, font.getlength(sh)
    if track_em is None and tw <= 0:
        track_em = 0.21                                    # no title to fit to
    adv, n = sum(font.getlength(c) for c in text), len(text) - 1
    tr = track_em * fs if track_em is not None else min(max((tw * SUB_FIT - adv) / n, 0.04 * fs), 0.45 * fs)
    return text, tr, adv + tr * n


def _fit_sub(text, fp, base, avail, tw, track_em, rtl):
    """Subtitle font shrinks (55 %) and the text is cut with an ellipsis until it fits `avail`. -> (font, fs, shaped, tracking px, width)."""
    k = 1.0
    while True:
        fs = max(8, int(round(base * k)))
        font = load_font(fp, fs)
        sh, tr, w = _sub_metrics(text, font, fs, tw, track_em, rtl)
        if w <= avail or k <= 0.55 + 1e-9:
            break
        k = max(0.55, k - 0.05)
    for _ in range(200):
        if w <= avail or len(text) <= 2:
            break
        text = text.rstrip("…")[:-1] + "…"
        sh, tr, w = _sub_metrics(text, font, fs, tw, track_em, rtl)
    return font, fs, sh, tr, w


def _cap(font):
    return float(-font.getbbox("H", anchor="ls")[1])


def _text_block(spr, sp, g, x0, x1, cy, avail, h, s, rtl, fp, col, txt):
    """Title (two-tone, faint glow on the accent) + tracked subtitle. x0 / x1 = text area left / right edge in slot coords."""
    caps = sp["caps"] and not rtl
    title, sub = (sp["title"].upper() if caps else sp["title"]), (sp["subtitle"].upper() if caps else sp["subtitle"])
    base = sp["size"] * s if sp["size"] else TITLE_K[sp["_badge"]] * h
    font, fs, words, tw, _ = _fit_title(_tokens(title, sp["accent"]), fp, base, avail, 0.0, rtl)
    sfont, sfs, ssh, tr, sw = _fit_sub(sub, fp, SUB_K * fs, avail, tw, None if sp["tracking"] == "auto" else sp["tracking"], rtl) if sub else (None,) * 5
    ct = _cap(font)
    cs = _cap(sfont) if sub else 0.0
    gap = GAP_LINES * s if sub else 0.0
    top = cy - (ct + gap + cs) / 2.0
    by, sy = g + top + ct, g + top + ct + gap + cs
    stroke = 0 if _is_bold(fp) else max(1, int(round(fs * 0.025)))
    xa, xb = g + x0, g + x1
    if title:
        m = Image.new("L", spr.size, 0)
        _draw_words(ImageDraw.Draw(m), words, font, xa, xb, by, rtl, 0.0, (255, 255), stroke, True)
        k = max(2.0, fs * 0.12)
        gl = m.filter(ImageFilter.GaussianBlur(k)).point(lambda v: int(min(255, v * 0.8)))
        glow = Image.new("RGBA", spr.size, col + (0,))
        glow.putalpha(gl)
        spr.alpha_composite(glow)
        _draw_words(ImageDraw.Draw(spr), words, font, xa, xb, by, rtl, 0.0, (txt + (255,), col + (255,)), stroke, False)
    if sub:
        sstroke = 0 if _is_bold(fp) else (1 if sfs >= 28 else 0)
        _put(ImageDraw.Draw(spr), (xb - sw) if rtl else xa, sy, ssh, sfont, txt + (255,), tr, rtl, sstroke)
    return tw


def _draw_words(d, words, font, x0, x1, base_y, rtl, track, fills, stroke, only_accent):
    for sh, acc, off, ww in words:
        if only_accent and not acc:
            continue
        _put(d, (x1 - off - ww) if rtl else (x0 + off), base_y, sh, font, fills[1 if acc else 0], track, rtl, stroke)


# ---- icon / badge / panel ---------------------------------------------------------------------------------------------------
def _glyph(name, th, mw, col, glow):
    """Neon icon sized so its VISIBLE glyph is th high (and at most mw wide). -> (sprite, (glyph centre x, y) from the icon's top-left, glyph w, glyph h)
    or None (unknown icon: the kit already warned)."""
    bb = icon(name, 100, (255, 255, 255)).getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    if not bb or bb[2] <= bb[0] or bb[3] <= bb[1]:
        return None
    gw, gh = bb[2] - bb[0], bb[3] - bb[1]
    size = max(8, int(round(100.0 * min(th / gh, mw / gw))))
    k = size / 100.0
    return neon_icon(name, size, col, max(4.0, size * 0.10)), ((bb[0] + bb[2]) / 2.0 * k, (bb[1] + bb[3]) / 2.0 * k), gw * k, gh * k


def _icon_block(spr, sp, g, left, right, cy, h, s, col, badge, rtl):
    """Badge (portrait) or bare glyph, centred on cy. Block is placed at `left` (LTR) or ends at `right` (RTL), slot coords.
    -> (block width, block left edge); width 0 = no icon."""
    ih = ICON_H[badge] * h
    if not sp["icon"]:
        return 0.0, (right if rtl else left)
    if badge:
        bh = ih
        bw = bh * BADGE_ASPECT
        gl = _glyph(sp["icon"], GLYPH_IN_BADGE[1] * bh, GLYPH_IN_BADGE[0] * bw, col, 8 * s)
    else:
        gl = _glyph(sp["icon"], ih, ih * 1.8, col, 8 * s)
        bw = gl[2] if gl else 0.0
    if gl is None:
        return 0.0, (right if rtl else left)
    x = (right - bw) if rtl else left
    if badge:
        cut = 0.28 * bh
        kit_paste(spr, glass_panel((int(round(bw)), int(round(bh))), 0, TINT_BADGE, col, (cut,) * 4, 2.2 * s, 9 * s), g + x, g + cy - bh / 2.0)
    ic, (gcx, gcy), _, _ = gl
    kit_paste(spr, ic, g + x + bw / 2.0 - gcx, g + cy - gcy)
    return bw, x


# ---- build ------------------------------------------------------------------------------------------------------------------
def _build(sp, w, h, s, badge, fp, rtl):
    g = int(round(GLOW_PAD * s))
    col, txt = t2_rgb(sp["color"]), t2_rgb(sp["text_color"])
    spr = Image.new("RGBA", (w + 2 * g, h + 2 * g), (0, 0, 0, 0))
    pad = (PANEL_PAD if (sp["panel"] or badge) else BARE_PAD) * s          # R5: badge 21 px in from the slot edge; R6: glyph 4 px
    if sp["panel"]:
        kit_paste(spr, glass_panel((w, h), 0, TINT_PANEL, col, (20 * s,) * 4, 2.2 * s, 10 * s), g, g)
    cy, pad_i = h / 2.0, (PANEL_PAD if (sp["panel"] or badge) else BARE_PAD) * s            # RTL: the icon sits pad in from the right edge
    iw, ix = _icon_block(spr, sp, g, pad, w - pad_i, cy, h, s, col, badge, rtl)
    gap = GAP_ICON * s if iw else 0.0
    pad_r = PANEL_PAD * s if sp["panel"] else 0.0                          # right inset only inside a plate
    x0, x1 = (pad_r, ix - gap) if rtl else (ix + iw + gap, w - pad_r)    # text area, slot coords
    avail = max(40.0, x1 - x0)
    _text_block(spr, dict(sp, _badge=badge), g, x0, x1, cy, avail, h, s, rtl, fp, col, txt)
    spr.info["origin"], spr.info["rtl"] = (g, g), rtl
    return spr


def t4_title_block(spec, box, ctx):
    """Widget function: title block sprite for the slot `box` = (x, y, w, h) canvas px. None when title and subtitle are both empty.
    sprite.info['origin'] = the slot's top-left inside the sprite; the sprite is cached (do not draw into it)."""
    sp = _spec(spec)
    ctx = ctx if isinstance(ctx, dict) else {}
    if not sp["title"] and not sp["subtitle"]:
        t4_warn("title_block: no title and no subtitle - skipped.")
        return None
    s = float(ctx.get("s") or 1.0)
    w, h = max(40, int(round(box[2]))), max(30, int(round(box[3])))
    badge = sp["badge"] if sp["badge"] is not None else ctx.get("aspect") == "portrait"
    if sp["font"] and not os.path.isfile(sp["font"]):
        t4_warn("title_block: font '%s' not found - using the default font." % os.path.basename(sp["font"]))
    fp = sp["font"] if sp["font"] and os.path.isfile(sp["font"]) else default_font()
    rtl = sp["rtl"] if sp["rtl"] is not None else is_rtl_text(sp["title"] + " " + sp["subtitle"])
    key = (tuple(sorted((k, str(v)) for k, v in sp.items())), w, h, round(s, 3), badge, str(fp), rtl)
    return _cached(_TB, key, lambda: _build(sp, w, h, s, badge, fp, rtl), 8)


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_ask_title_block():
    """Question group of the widget (called by t4_ask_scenes) -> spec dict. Badge / panel / font / tracking: edit the job file."""
    d = T4_TITLE_BLOCK
    out = {"title": ask("Title (the last word is coloured)", default=d["title"], key="t4_scene_title"),
           "subtitle": ask("Subtitle (Enter = none)", default=d["subtitle"], key="t4_scene_subtitle", allow_empty=True) or ""}
    out["accent"] = ask("Word(s) to colour (Enter = the last word)", key="t4_scene_accent", allow_empty=True) or ""
    out["color"] = ask("Accent colour", default=d["color"], key="t4_scene_color", cast=c_color)
    b = ask_choice("Hex badge behind the icon", ["Automatic (portrait yes, landscape no)", "Always", "Never"], default=1, key="t4_scene_badge")
    out["badge"] = [None, True, False][b - 1]
    out["panel"] = yn("Dark glass plate behind the whole title block?", default=False)
    return out


register_widget("title_block", t4_title_block, ask=t4_ask_title_block, slot="title")