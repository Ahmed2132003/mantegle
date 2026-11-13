"""mt.templates.t4.scenes_card - Template 4 scenes: widget 'info_card' (glass panel: icon + title + subtitle).
spec keys (all optional; px at short side 1080): icon 'globe' (kit name | PNG path | ''/'-'/'none'), title, subtitle,
  color (accent: icon + border), icon_color / border_color ('' = color), glow 10, border 3, fill '#0B1A3A', fill_alpha 0.55,
  title_size 44, sub_size 26, title_color, sub_color, radius 26 | cut 0 (chamfer px, overrides radius), pad 28, gap 24,
  icon_size 0.62 (fraction of inner box height), icon_glow None (auto), align auto|left|right (auto: Arabic -> right), font ''.
Title wraps to <= 2 lines; everything shrinks to 60 % when the panel is taller than the box. Panel is centred vertically in the slot.
Public: T4_CARD, t4_info_card(spec, box, ctx), t4_ask_card()."""
import math

from PIL import Image, ImageDraw

from mt.common import ask, ask_choice
from mt.draw import t2_draw_mask, t2_glow, t2_paint, t2_rgb
from mt.fonts import is_rtl_text, load_font, shape
from mt.templates.t4.kit import kit_paste
from mt.templates.t4.nameplate import _cached, _flt
from mt.templates.t4.scenes_bullets import _cap, _font, _wrap
from mt.templates.t4.scenes_reg import register_widget
from mt.templates.t4.scenes_ring import _icon
from mt.templates.t4.scenes_title import _color
from mt.templates.t4.warn import t4_warn

T4_CARD = {"icon": "globe", "title": "Web Technology", "subtitle": "Build \u2022 Develop \u2022 Deploy",
           "color": "#19D3FF", "glow": 10.0, "border": 3.0, "fill": "#0B1A3A", "fill_alpha": 0.55,
           "title_size": 44.0, "sub_size": 26.0, "title_color": "#FFFFFF", "sub_color": "#9FB8DD",
           "radius": 26.0, "cut": 0.0, "pad": 28.0, "gap": 24.0, "icon_size": 0.62}
_CC = {}


# ---- spec ----------------------------------------------------------------------
def _spec(raw):
    """Complete, clean spec (never raises; junk -> defaults)."""
    raw, d = raw if isinstance(raw, dict) else {}, T4_CARD

    def txt(k):
        v = raw.get(k, d.get(k, ""))
        return v.strip() if isinstance(v, str) else ""
    title, sub, ic = txt("title"), txt("subtitle"), txt("icon")
    al = raw.get("align")
    al = {"left": "left", "l": "left", "ltr": "left", "right": "right", "r": "right", "rtl": "right"}.get(
        al.strip().lower() if isinstance(al, str) else "", "auto")
    if al == "auto":
        al = "right" if (title or sub) and is_rtl_text(title or sub) else "left"
    col = _color(raw.get("color"), d["color"])
    fo = raw.get("font")
    return {"icon": "" if ic.lower() in ("-", "none") else ic, "title": title, "subtitle": sub, "color": col,
            "icon_color": _color(raw.get("icon_color"), col), "border_color": _color(raw.get("border_color"), col),
            "glow": _flt(raw.get("glow"), 0, 60, d["glow"]), "border": _flt(raw.get("border"), 0, 20, d["border"]),
            "fill": _color(raw.get("fill"), d["fill"]), "fill_alpha": _flt(raw.get("fill_alpha"), 0.0, 1.0, d["fill_alpha"]),
            "title_size": _flt(raw.get("title_size"), 8, 200, d["title_size"]),
            "sub_size": _flt(raw.get("sub_size"), 8, 200, d["sub_size"]),
            "title_color": _color(raw.get("title_color"), d["title_color"]),
            "sub_color": _color(raw.get("sub_color"), d["sub_color"]),
            "radius": _flt(raw.get("radius"), 0, 80, d["radius"]), "cut": _flt(raw.get("cut"), 0, 80, d["cut"]),
            "pad": _flt(raw.get("pad"), 0, 120, d["pad"]), "gap": _flt(raw.get("gap"), 0, 120, d["gap"]),
            "icon_size": _flt(raw.get("icon_size"), 0.1, 1.0, d["icon_size"]),
            "icon_glow": None if raw.get("icon_glow") is None else _flt(raw.get("icon_glow"), 0, 60, 8.0),
            "align": al, "font": fo.strip() if isinstance(fo, str) else ""}


# ---- drawing -------------------------------------------------------------------
def _pts(x0, y0, x1, y1, r, cut):
    """Outline polygon: chamfered corners if cut > 0, else rounded corners (r), else a plain rectangle."""
    hw, hh = (x1 - x0) / 2.0, (y1 - y0) / 2.0
    r, c = max(0.0, min(r, hw, hh)), max(0.0, min(cut, hw, hh))
    if c > 0:
        return [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c), (x1 - c, y1), (x0 + c, y1), (x0, y1 - c), (x0, y0 + c)]
    if r < 1:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    out = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for k in range(9):
            a = math.radians(a0 + 90.0 * k / 8)
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def _mask(bb, outer, inner=None, clip_y=None):
    """Polygon mask in sprite pixel coords; `inner` is cut out (border ring); below clip_y is cleared (top highlight)."""
    def fn(d, L, s):
        d.polygon([L(x, y) for x, y in outer], fill=255)
        if inner:
            d.polygon([L(x, y) for x, y in inner], fill=0)
        if clip_y is not None:
            a, b = L(bb[0] - 1, clip_y), L(bb[2] + 1, bb[3] + 1)
            d.rectangle((a[0], a[1], b[0], b[1]), fill=0)
    return t2_draw_mask(bb, fn)


def _text(path, txt, size, maxw):
    """-> (font, shaped lines, widths). Wrap + shape right after loading the font (shape() depends on the last loaded font)."""
    f = load_font(path, size)
    shaped = [shape(t) for t in _cap(_wrap(txt, f, maxw), f, maxw)] if txt else []
    return f, shaped, [f.getlength(t) for t in shaped]


def _build(sp, w, h, s):
    if not (sp["title"] or sp["subtitle"] or sp["icon"]):
        t4_warn("info_card: no icon, title or subtitle - skipped.")
        return None
    right, path = sp["align"] == "right", _font(sp["font"])
    pad, gap, bw, glow = sp["pad"] * s, sp["gap"] * s, sp["border"] * s, sp["glow"] * s
    m = int(glow * 2.6 + bw + 6)
    for k in (1.0, 0.85, 0.7, 0.6):
        iw = int(round(sp["icon_size"] * max(8.0, h - 2 * pad) * k)) if sp["icon"] else 0
        avail = max(30.0, w - 2 * pad - (iw + gap if iw else 0))
        tsz, ssz = max(8, int(round(sp["title_size"] * s * k))), max(8, int(round(sp["sub_size"] * s * k)))
        tf, tl, tw = _text(path, sp["title"], tsz, avail)
        sf, sl, sw = _text(path, sp["subtitle"], ssz, avail)
        lht, lhs, sgap = tsz * 1.2, ssz * 1.25, tsz * 0.25
        bh = len(tl) * lht + (len(sl) * lhs + (sgap if tl else 0) if sl else 0)
        ph = max(bh, iw) + 2 * pad
        if ph <= h:
            break
    if ph > h * 1.02:
        t4_warn("info_card: the card is taller than its box (%d > %d px) - give it a bigger slot or less text." % (ph, h))
    ph = min(ph, float(h))
    x0, y0 = float(m), m + (h - ph) / 2.0
    x1, y1 = x0 + w, y0 + ph
    bb = (x0 - 2, y0 - 2, x1 + 2, y1 + 2)
    outer = _pts(x0, y0, x1, y1, sp["radius"] * s, sp["cut"] * s)
    inner = _pts(x0 + bw, y0 + bw, x1 - bw, y1 - bw, max(0.0, sp["radius"] * s - bw), max(0.0, sp["cut"] * s - bw * 0.41))
    spr = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    ring, fill, cb = _mask(bb, outer, inner), _mask(bb, outer), t2_rgb(sp["border_color"])
    if glow > 0 and bw > 0:
        t2_paint(spr, t2_glow(ring, max(2.0, glow * 0.6), 1.1), cb, 0.6)           # glow under the glass
    t2_paint(spr, fill, t2_rgb(sp["fill"]), sp["fill_alpha"])                      # glass body
    t2_paint(spr, _mask(bb, inner, clip_y=y0 + ph * 0.45), (255, 255, 255), 0.07)  # top sheen
    if bw > 0:
        t2_paint(spr, ring, cb)
    if iw:
        ig = iw * 0.12 if sp["icon_glow"] is None else sp["icon_glow"] * s
        ic = _icon({"icon": sp["icon"]}, iw, ig, sp["icon_color"])
        if ic is not None:
            kit_paste(spr, ic, (x1 - pad - iw) if right else (x0 + pad), y0 + ph / 2.0 - iw / 2.0)
    tx, rx = x0 + pad + (iw + gap if iw else 0), x1 - pad - (iw + gap if iw else 0)
    dr, top = ImageDraw.Draw(spr), y0 + (ph - bh) / 2.0
    for f, lines, widths, lh, y, col in ((tf, tl, tw, lht, top, sp["title_color"]),
                                         (sf, sl, sw, lhs, top + len(tl) * lht + (sgap if tl else 0), sp["sub_color"])):
        asc, desc = f.getmetrics()
        for i, (t, wd) in enumerate(zip(lines, widths)):
            base = y + i * lh + (lh - (asc + desc)) / 2.0 + asc
            dr.text(((rx - wd) if right else tx, base), t, font=f, fill=t2_rgb(col) + (255,), anchor="ls")
    spr.info["origin"] = (m, m)
    return spr


def t4_info_card(spec, box, ctx):
    """Widget function: glass panel (icon + title + subtitle) in the slot `box` = (x, y, w, h) -> RGBA sprite (origin = box top-left)."""
    sp = _spec(spec)
    s = float(ctx.get("s", 1.0)) if isinstance(ctx, dict) else 1.0
    w, h = max(120, int(round(box[2]))), max(60, int(round(box[3])))
    return _cached(_CC, (repr(sp), w, h, round(s, 3)), lambda: _build(sp, w, h, s))


# ---- questions -----------------------------------------------------------------
def t4_ask_card():
    """Question group of the widget (called by t4_ask_scenes) -> spec dict."""
    d = T4_CARD
    out = {"icon": ask("Card icon (kit name or PNG path, '-' = none)", default=d["icon"], key="t4_card_icon"),
           "title": ask("Card title", default=d["title"], key="t4_card_title"),
           "subtitle": ask("Card subtitle (empty = none)", default=d["subtitle"], key="t4_card_subtitle")}
    out["align"] = ["auto", "left", "right"][ask_choice("Alignment", ["Auto (Arabic = right)", "Left", "Right"], default=0)]
    return out


register_widget("info_card", t4_info_card, ask=t4_ask_card, slot="card")