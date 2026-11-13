"""mt.templates.t4.scenes_charts - Template 4 scenes: widgets 'bar_chart', 'progress_list', 'badge' (refs R5 / R6 look).
bar_chart     neon gradient bars on thin axis lines. spec (px at short side 1080): values [..] (<= 12, missing = demo), labels [..] (x labels),
  color '#19D3FF' (bar top) / color2 '#1E6BFF' (bar bottom), axis_color, text_color, glow 8, bar_w 0.58 (fraction of the slot), axis_w 2, size 24
  (label px), max None (= largest value), show_values True, steps 8 (growth steps 1..8), line_step 0.1, line_dur 0.2, font '', rtl 'auto'
  (Arabic labels: first bar on the right, y axis on the right). Growth = the plot is cut into <= 8 horizontal bands (bottom to top); each band is ONE
  pre-built Item (sprite.info['lines'], staggered by the engine, fades in) - nothing is drawn per frame. The value labels are the last Item.
progress_list rows [{icon, label, pct}] (<= 8; also 'label|pct' or 'icon|label|pct' strings; missing = demo): icon (kit name | PNG | '-'), label,
  track + gradient fill of pct %. keys: color, color2, text_color, track_color, glow 6, size 30, bar_h 14, gap 26, icon_size 0.9 (x row height),
  show_pct True, align auto|left|right (Arabic = right: icon + text right, fill grows leftward), font, anim fade|reveal|pop, line_step 0.25, line_dur 0.4.
  Rows are staggered Items (lines_only sprite, like bullet_list).
badge         small glass pill: icon (kit name | PNG | '-') + text. keys: text 'Python', icon 'code', color, text_color, fill, fill_alpha 0.7, glow 8,
  border 2, size 30, pad_x 24, pad_y 12, gap 12, icon_size 1.15 (x font size), align auto|left|center|right (auto: Arabic = right), font. One cached sprite.
Public: T4_BAR_CHART, T4_PROGRESS, T4_BADGE, t4_bar_chart / t4_progress_list / t4_badge(spec, box, ctx), t4_ask_bar_chart / t4_ask_progress / t4_ask_badge."""
import math
import re

from PIL import Image, ImageDraw

from mt.common import ask
from mt.draw import t2_glow, t2_grad, t2_paint, t2_rgb, t2_rrect_mask
from mt.fonts import is_rtl_text, load_font, shape
from mt.templates.t4.kit import glass_panel, kit_paste
from mt.templates.t4.nameplate import _bool, _cached, _flt
from mt.templates.t4.scenes_bullets import _font
from mt.templates.t4.scenes_reg import register_widget
from mt.templates.t4.scenes_ring import _icon
from mt.templates.t4.scenes_title import _color
from mt.templates.t4.scenes_widgets import _baseline
from mt.templates.t4.warn import t4_warn

T4_BAR_CHART = {"values": [35, 55, 42, 78, 95], "labels": ["Jan", "Feb", "Mar", "Apr", "May"], "color": "#19D3FF", "color2": "#1E6BFF",
                "axis_color": "#5C7FB0", "text_color": "#FFFFFF", "glow": 8.0, "bar_w": 0.58, "axis_w": 2.0, "size": 24.0, "max": None,
                "show_values": True, "steps": 8, "line_step": 0.1, "line_dur": 0.2, "font": "", "rtl": "auto"}
T4_PROGRESS = {"rows": [{"icon": "code", "label": "Python", "pct": 90}, {"icon": "database", "label": "SQL", "pct": 75},
                        {"icon": "globe", "label": "Web design", "pct": 60}],
               "color": "#19D3FF", "color2": "#1E6BFF", "text_color": "#FFFFFF", "track_color": "#12264A", "glow": 6.0, "size": 30.0,
               "bar_h": 14.0, "gap": 26.0, "icon_size": 0.9, "show_pct": True, "align": "auto", "font": "", "anim": "fade",
               "line_step": 0.25, "line_dur": 0.4}
T4_BADGE = {"text": "Python", "icon": "code", "color": "#19D3FF", "text_color": "#FFFFFF", "fill": "#0B1A3A", "fill_alpha": 0.7, "glow": 8.0,
            "border": 2.0, "size": 30.0, "pad_x": 24.0, "pad_y": 12.0, "gap": 12.0, "icon_size": 1.15, "align": "auto", "font": ""}
MAX_BARS, MAX_ROWS = 12, 8
_ICON_OFF = ("", "-", "none")
_CB, _CP, _CG = {}, {}, {}


# ---- shared helpers ---------------------------------------------------------------------------------------------------------
def _numbers(v):
    v = [x for x in re.split(r"[|;,\s]+", v) if x] if isinstance(v, str) else v if isinstance(v, (list, tuple)) else []
    out = []
    for x in v:
        if isinstance(x, bool):
            continue
        try:
            f = float(x)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(max(0.0, f))
    if len(out) > MAX_BARS:
        t4_warn("bar_chart: %d values - only the first %d are used." % (len(out), MAX_BARS))
        out = out[:MAX_BARS]
    return out


def _strs(v):
    v = v.split("|") if isinstance(v, str) else v if isinstance(v, (list, tuple)) else []
    return [str(x).strip() if x is not None else "" for x in v]


def _text(v, default=""):
    if v is None:
        return default
    return v.strip() if isinstance(v, str) else str(v).strip() if isinstance(v, (int, float)) and not isinstance(v, bool) else ""


def _rtl(v, texts):
    if isinstance(v, bool):
        return v
    first = next((t for t in texts if t), "")
    return bool(first) and is_rtl_text(first)


def _cut(f, text, maxw):
    """Shaped text, cut with an ellipsis when wider than maxw (f must be the font loaded last: shape() reads it)."""
    if f.getlength(shape(text)) <= maxw:
        return shape(text)
    while len(text) > 1 and f.getlength(shape(text + "\u2026")) > maxw:
        text = text[:-1]
    return shape(text + "\u2026")


def _txt_fit(path, size, texts, maxw):
    """-> (font, [shaped]): font shrinks to 70 % while the widest text is wider than maxw, then texts are cut with an ellipsis."""
    lo, sz = max(8, int(size * 0.7)), max(8, int(size))
    f = load_font(path, sz)
    while sz > lo and max([f.getlength(shape(t)) for t in texts] or [0]) > maxw:
        sz -= 1
        f = load_font(path, sz)
    return f, [_cut(f, t, maxw) for t in texts]


# ---- bar_chart: spec --------------------------------------------------------------------------------------------------------
def _bar_spec(raw):
    raw = raw if isinstance(raw, dict) else {}
    d, demo = T4_BAR_CHART, "values" not in raw
    vals = list(d["values"]) if demo else _numbers(raw["values"])
    labs = _strs(raw["labels"]) if "labels" in raw else (list(d["labels"]) if demo else [])
    labs = (labs + [""] * len(vals))[:len(vals)]
    mx = raw.get("max")
    mx = _flt(mx, 1e-6, 1e12, 0.0) if mx is not None else 0.0
    try:
        steps = max(1, min(8, int(raw.get("steps", d["steps"]))))
    except (TypeError, ValueError, OverflowError):
        steps = d["steps"]
    fo = raw.get("font")
    return {"values": vals, "labels": labs, "color": _color(raw.get("color"), d["color"]), "color2": _color(raw.get("color2"), d["color2"]),
            "axis_color": _color(raw.get("axis_color"), d["axis_color"]), "text_color": _color(raw.get("text_color"), d["text_color"]),
            "glow": _flt(raw.get("glow"), 0, 40, d["glow"]), "bar_w": _flt(raw.get("bar_w"), 0.15, 1.0, d["bar_w"]),
            "axis_w": _flt(raw.get("axis_w"), 0.5, 12, d["axis_w"]), "size": _flt(raw.get("size"), 8, 100, d["size"]), "max": mx or None,
            "show_values": _bool(raw.get("show_values"), True), "steps": steps,
            "line_step": _flt(raw.get("line_step"), 0.0, 2.0, d["line_step"]), "line_dur": _flt(raw.get("line_dur"), 0.03, 3.0, d["line_dur"]),
            "font": fo.strip() if isinstance(fo, str) else "", "_rtl": _rtl(raw.get("rtl"), labs)}


# ---- bar_chart: drawing -----------------------------------------------------------------------------------------------------
def _bar_layout(sp, w, h, s, path):
    """All chart numbers in sprite px: margins, axes, bar slots / heights, label fonts."""
    vals, n = sp["values"], len(sp["values"])
    aw, glow = max(1.0, sp["axis_w"] * s), sp["glow"] * s
    m = int(glow * 2.6 + aw + 6)
    px0, px1, inner = m + 6 * s, m + w - 6 * s, 14 * s
    slot = max(8.0, (px1 - px0 - 2 * inner) / n)
    has_lab = any(sp["labels"])
    lf, lab = _txt_fit(path, sp["size"] * s, sp["labels"], slot * 0.96) if has_lab else (None, [])
    lsz = int(getattr(lf, "size", sp["size"] * s)) if lf else 0
    vsize = max(8, int(round(sp["size"] * s * 0.95)))
    base = m + h - (lsz * 1.5 if lf else 0.0) - 4 * s - aw / 2.0
    top = m + (vsize * 1.7 if sp["show_values"] else 8 * s)
    avail = max(8.0, base - aw / 2.0 - top)
    vmax = sp["max"] or max(vals) or 1.0
    bars = []
    for i, v in enumerate(vals):
        idx = n - 1 - i if sp["_rtl"] else i
        bh = 0.0 if v <= 0 else max(3.0, min(1.0, v / vmax) * avail)
        bars.append((px0 + inner + (idx + 0.5) * slot, base - aw / 2.0 - bh, bh))
    bw = max(4.0, min(slot * sp["bar_w"], slot))
    return {"m": m, "W": int(round(w)) + 2 * m, "H": int(round(h)) + 2 * m, "px0": px0, "px1": px1, "base": base, "top": top, "aw": aw,
            "bars": bars, "bw": bw, "rad": min(bw * 0.3, 12 * s), "lf": lf, "lab": lab, "lsz": lsz, "vsize": vsize, "s": s}


def _bar_static(sp, g):
    """Axes (thin) + x labels: the part that is visible from the first frame."""
    im = Image.new("RGBA", (g["W"], g["H"]), (0, 0, 0, 0))
    aw, s, ac = g["aw"], g["s"], t2_rgb(sp["axis_color"])
    ax = g["px1"] if sp["_rtl"] else g["px0"]
    for box in ((g["px0"] - aw / 2.0, g["base"] - aw / 2.0, g["px1"] + aw / 2.0, g["base"] + aw / 2.0),
                (ax - aw / 2.0, g["top"] - 4 * s, ax + aw / 2.0, g["base"] + aw / 2.0)):
        t2_paint(im, t2_rrect_mask(box, aw / 2.0), ac, 0.9)
    if g["lf"]:
        dr, y = ImageDraw.Draw(im), g["base"] + aw / 2.0 + 4 * s + g["lsz"] * 0.95
        for (cx, _y0, _bh), t in zip(g["bars"], g["lab"]):
            dr.text((cx, y), t, font=g["lf"], fill=t2_rgb(sp["text_color"]) + (230,), anchor="ms")
    return im


def _bar_plot(sp, g):
    """All bars (glow + vertical neon gradient, rounded top) on one transparent sprite-size layer; everything under the axis is cleared."""
    plot = Image.new("RGBA", (g["W"], g["H"]), (0, 0, 0, 0))
    c1, c2, glow = t2_rgb(sp["color"]), t2_rgb(sp["color2"]), sp["glow"] * g["s"]
    masks = []
    for cx, y0, bh in g["bars"]:
        if bh > 0:
            box = (cx - g["bw"] / 2.0, y0, cx + g["bw"] / 2.0, y0 + bh + g["rad"] * 2)      # bottom corners hide under the axis
            masks.append((t2_rrect_mask(box, g["rad"]), box))
    if glow > 0:
        for mk, _b in masks:
            t2_paint(plot, t2_glow(mk, glow * 0.7, 1.0), c1, 0.5)
    for mk, box in masks:
        t2_paint(plot, mk, t2_grad([(0, c1), (1, c2)], 90, box))
    cut = int(round(g["base"] - g["aw"] / 2.0))
    plot.paste((0, 0, 0, 0), (0, cut, plot.width, plot.height))
    return plot


def _bar_values(sp, g, path):
    """Value labels above the bars (one layer, shown as the LAST item)."""
    im = Image.new("RGBA", (g["W"], g["H"]), (0, 0, 0, 0))
    f, dr, col = load_font(path, g["vsize"]), None, t2_rgb(sp["text_color"]) + (255,)
    dr = ImageDraw.Draw(im)
    for v, (cx, y0, bh) in zip(sp["values"], g["bars"]):
        y = (y0 if bh > 0 else g["base"] - g["aw"] / 2.0) - 8 * g["s"]
        dr.text((cx, y), "%g" % v, font=f, fill=col, anchor="ms")
    return im


def _bands(plot, steps):
    """Cut the plot into <= steps horizontal bands, bottom first -> [(sprite, x, y)] (top-left in sprite coords); empty bands are skipped."""
    bb = plot.getbbox()
    if not bb:
        return []
    top, bot, out = bb[1], bb[3], []
    edges = [int(round(bot - j * (bot - top) / float(steps))) for j in range(steps + 1)]
    edges[-1] = top
    for j in range(steps):
        y0, y1 = edges[j + 1], edges[j]
        if y1 <= y0:
            continue
        part = plot.crop((0, y0, plot.width, y1))
        pb = part.getbbox()
        if pb:
            out.append((part.crop(pb), pb[0], y0 + pb[1]))
    return out


def _build_bars(sp, w, h, s):
    if not sp["values"]:
        t4_warn("bar_chart: no values - skipped.")
        return None
    path = _font(sp["font"])
    g = _bar_layout(sp, w, h, s, path)
    spr = _bar_static(sp, g)
    parts = _bands(_bar_plot(sp, g), sp["steps"])
    if sp["show_values"]:
        vim = _bar_values(sp, g, path)
        vb = vim.getbbox()
        if vb:
            parts.append((vim.crop(vb), vb[0], vb[1]))
    spr.info.update({"origin": (g["m"], g["m"]), "lines": parts, "line_step": sp["line_step"], "line_dur": sp["line_dur"], "line_anim": "fade"})
    return spr


def t4_bar_chart(spec, box, ctx):
    """Widget function: neon bar chart in the slot `box` = (x, y, w, h) canvas px. Static sprite = axes + x labels (origin = the box's top-left);
    the growth bands + value labels are in sprite.info['lines'] (the engine adds one staggered Item each). Cached."""
    sp = _bar_spec(spec)
    s = float(ctx.get("s", 1.0)) if isinstance(ctx, dict) else 1.0
    w, h = max(120, int(round(box[2]))), max(80, int(round(box[3])))
    return _cached(_CB, (repr(sp), w, h, round(s, 3)), lambda: _build_bars(sp, w, h, s), 6)


# ---- progress_list ----------------------------------------------------------------------------------------------------------
def _pct(v):
    try:
        f = 0.0 if isinstance(v, bool) else float(str(v).strip().rstrip("%").strip())
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, f)) if math.isfinite(f) else 0.0


def _prog_rows(raw):
    if "rows" not in raw:
        return [dict(r) for r in T4_PROGRESS["rows"]]
    v = raw["rows"]
    v = [x for x in re.split(r"[\n;]", v) if x.strip()] if isinstance(v, str) else v if isinstance(v, (list, tuple)) else []
    out = []
    for r in v:
        if isinstance(r, str):
            p = [t.strip() for t in r.split("|")]
            r = ({"icon": p[0], "label": p[1], "pct": p[2]} if len(p) >= 3 else {"label": p[0], "pct": p[1]} if len(p) == 2 else {"label": p[0]})
        if not isinstance(r, dict):
            continue
        label, ic = _text(r.get("label")), _text(r.get("icon"))
        if label or ic:
            out.append({"icon": "" if ic.lower() in _ICON_OFF else ic, "label": label, "pct": _pct(r.get("pct"))})
    if len(out) > MAX_ROWS:
        t4_warn("progress_list: %d rows - only the first %d are used." % (len(out), MAX_ROWS))
        out = out[:MAX_ROWS]
    return out


def _prog_spec(raw):
    raw = raw if isinstance(raw, dict) else {}
    d, rows = T4_PROGRESS, _prog_rows(raw)
    al = raw.get("align")
    al = {"left": "left", "l": "left", "ltr": "left", "right": "right", "r": "right", "rtl": "right"}.get(al.strip().lower() if isinstance(al, str) else "", "auto")
    if al == "auto":
        al = "right" if rows and is_rtl_text(rows[0]["label"]) else "left"
    an, fo = raw.get("anim"), raw.get("font")
    an = an.strip().lower() if isinstance(an, str) else "fade"
    return {"rows": rows, "color": _color(raw.get("color"), d["color"]), "color2": _color(raw.get("color2"), d["color2"]),
            "text_color": _color(raw.get("text_color"), d["text_color"]), "track_color": _color(raw.get("track_color"), d["track_color"]),
            "glow": _flt(raw.get("glow"), 0, 40, d["glow"]), "size": _flt(raw.get("size"), 8, 200, d["size"]),
            "bar_h": _flt(raw.get("bar_h"), 3, 80, d["bar_h"]), "gap": _flt(raw.get("gap"), 0, 200, d["gap"]),
            "icon_size": _flt(raw.get("icon_size"), 0.2, 1.5, d["icon_size"]), "show_pct": _bool(raw.get("show_pct"), True), "_rtl": al == "right",
            "font": fo.strip() if isinstance(fo, str) else "", "anim": an if an in ("fade", "reveal", "pop") else "fade",
            "line_step": _flt(raw.get("line_step"), 0.0, 5.0, d["line_step"]), "line_dur": _flt(raw.get("line_dur"), 0.05, 5.0, d["line_dur"])}


def _prog_layout(sp, w, h, s, path):
    """Row geometry; everything x k (>= 0.6) when the rows are taller than the box."""
    n, k = len(sp["rows"]), 1.0
    for _ in range(2):
        size = max(8, int(round(sp["size"] * s * k)))
        bar_h, gap, lh = max(4.0, sp["bar_h"] * s * k), sp["gap"] * s * k, size * 1.25
        rh = lh + size * 0.25 + bar_h
        total = n * rh + (n - 1) * gap
        if total <= h or k < 1.0:
            break
        k = max(0.6, h / total)
    if total > h * 1.02:
        t4_warn("progress_list: the rows are taller than the box (%d > %d px) - give it a taller box / fewer rows." % (total, h))
    isz = int(round(rh * sp["icon_size"])) if any(r["icon"] for r in sp["rows"]) else 0
    return {"size": size, "bar_h": bar_h, "gap": gap, "lh": lh, "rh": rh, "isz": isz, "gx": max(8.0, size * 0.45), "path": path, "total": total}


def _prog_row(sp, row, g, w, pad, s):
    """One row sprite: [icon] label ........ pct  /  track + gradient fill. Local coords = sprite px (content offset = pad)."""
    right, rh, bh = sp["_rtl"], g["rh"], g["bar_h"]
    im = Image.new("RGBA", (int(w) + 2 * pad, int(math.ceil(rh)) + 2 * pad), (0, 0, 0, 0))
    icw = g["isz"] + g["gx"] if g["isz"] else 0
    tx0, tx1 = pad + (0 if right else icw), pad + w - (icw if right else 0)
    f = load_font(g["path"], g["size"])
    pct_t = "%d%%" % int(round(row["pct"])) if sp["show_pct"] else ""
    lab = _cut(f, row["label"], (tx1 - tx0) - (f.getlength(pct_t) if pct_t else 0) - g["gx"])
    dr, by = ImageDraw.Draw(im), pad + _baseline(f, g["lh"])
    c1, c2 = t2_rgb(sp["color"]), t2_rgb(sp["color2"])
    dr.text((tx1 if right else tx0, by), lab, font=f, fill=t2_rgb(sp["text_color"]) + (255,), anchor="rs" if right else "ls")
    if pct_t:
        dr.text((tx0 if right else tx1, by), pct_t, font=f, fill=c1 + (255,), anchor="ls" if right else "rs")
    yb = pad + g["lh"] + g["size"] * 0.25
    t2_paint(im, t2_rrect_mask((tx0, yb, tx1, yb + bh), bh / 2.0), t2_rgb(sp["track_color"]), 0.9)
    if row["pct"] > 0:
        fw = max(bh, (tx1 - tx0) * row["pct"] / 100.0)
        fx0, fx1 = (tx1 - fw, tx1) if right else (tx0, tx0 + fw)
        mk = t2_rrect_mask((fx0, yb, fx1, yb + bh), bh / 2.0)
        if sp["glow"] > 0:
            t2_paint(im, t2_glow(mk, max(2.0, sp["glow"] * s * 0.6), 1.0), c1, 0.5)
        t2_paint(im, mk, t2_grad([(0, c1), (1, c2)] if right else [(0, c2), (1, c1)], 0, (fx0, yb, fx1, yb + bh)))
    if g["isz"] and row["icon"]:
        ic = _icon({"icon": row["icon"]}, g["isz"], g["isz"] * 0.12, sp["color"])
        if ic is not None:
            kit_paste(im, ic, (pad + w - g["isz"]) if right else pad, pad + (rh - g["isz"]) / 2.0)
    return im


def _build_prog(sp, w, h, s):
    if not sp["rows"]:
        t4_warn("progress_list: no rows - skipped.")
        return None
    g = _prog_layout(sp, w, h, s, _font(sp["font"]))
    pad = int(sp["glow"] * s * 2.6) + 4
    parts, y = [], 0.0
    for row in sp["rows"]:
        parts.append((_prog_row(sp, row, g, w, pad, s), 0, int(round(y))))
        y += g["rh"] + g["gap"]
    total = int(math.ceil(y - g["gap"]))
    spr = Image.new("RGBA", (int(w) + 2 * pad, max(int(h), total) + 2 * pad), (0, 0, 0, 0))      # empty: the rows are the items
    spr.info.update({"origin": (pad, pad), "ink": (pad, pad, pad + int(w), pad + total), "lines_only": True, "lines": parts,
                     "line_step": sp["line_step"], "line_dur": sp["line_dur"], "line_anim": {"pop": "t4_pop"}.get(sp["anim"], sp["anim"])})
    return spr


def t4_progress_list(spec, box, ctx):
    """Widget function: rows of icon + label + progress bar in the slot `box`. Empty static sprite, one staggered Item per row (info['lines'])."""
    sp = _prog_spec(spec)
    s = float(ctx.get("s", 1.0)) if isinstance(ctx, dict) else 1.0
    w, h = max(120, int(round(box[2]))), max(40, int(round(box[3])))
    return _cached(_CP, (repr(sp), w, h, round(s, 3)), lambda: _build_prog(sp, w, h, s), 6)


# ---- badge ------------------------------------------------------------------------------------------------------------------
def _badge_spec(raw):
    raw = raw if isinstance(raw, dict) else {}
    d = T4_BADGE
    text = _text(raw.get("text", d["text"]))
    ic = _text(raw.get("icon", d["icon"]))
    al = raw.get("align")
    al = {"left": "left", "l": "left", "center": "center", "centre": "center", "c": "center", "right": "right", "r": "right"}.get(
        al.strip().lower() if isinstance(al, str) else "", "auto")
    if al == "auto":
        al = "right" if text and is_rtl_text(text) else "left"
    fo = raw.get("font")
    return {"text": text, "icon": "" if ic.lower() in _ICON_OFF else ic, "color": _color(raw.get("color"), d["color"]),
            "text_color": _color(raw.get("text_color"), d["text_color"]), "fill": _color(raw.get("fill"), d["fill"]),
            "fill_alpha": _flt(raw.get("fill_alpha"), 0.0, 1.0, d["fill_alpha"]), "glow": _flt(raw.get("glow"), 0, 40, d["glow"]),
            "border": _flt(raw.get("border"), 0, 12, d["border"]), "size": _flt(raw.get("size"), 8, 150, d["size"]),
            "pad_x": _flt(raw.get("pad_x"), 0, 120, d["pad_x"]), "pad_y": _flt(raw.get("pad_y"), 0, 80, d["pad_y"]),
            "gap": _flt(raw.get("gap"), 0, 80, d["gap"]), "icon_size": _flt(raw.get("icon_size"), 0.3, 2.5, d["icon_size"]),
            "align": al, "font": fo.strip() if isinstance(fo, str) else ""}


def _build_badge(sp, w, h, s):
    if not (sp["text"] or sp["icon"]):
        t4_warn("badge: no text and no icon - skipped.")
        return None
    path = _font(sp["font"])
    has_icon = bool(sp["icon"]) and _icon({"icon": sp["icon"]}, 16, 2.0, sp["color"]) is not None
    for k in (1.0, 0.9, 0.8, 0.7, 0.6):                                            # shrink until the pill fits the box width
        size = max(8, int(round(sp["size"] * s * k)))
        f = load_font(path, size)
        tw = f.getlength(shape(sp["text"])) if sp["text"] else 0.0
        isz = int(round(size * sp["icon_size"])) if has_icon else 0
        px, gx = sp["pad_x"] * s * k, sp["gap"] * s * k
        pw = 2 * px + isz + (gx if isz and tw else 0.0) + tw
        if pw <= w:
            break
    if pw > w * 1.02:
        t4_warn("badge: the pill is wider than its box (%d > %d px) - give it a wider box / shorter text." % (pw, w))
    ph = max(size * 1.25, isz) + 2 * sp["pad_y"] * s * k
    tint = t2_rgb(sp["fill"]) + (int(round(255 * sp["fill_alpha"])),)
    pill = glass_panel((int(round(pw)), int(round(ph))), ph / 2.0 - 0.5, tint, sp["color"], 0, sp["border"] * s, sp["glow"] * s)
    ox, oy = pill.info["origin"]
    right, f = sp["align"] == "right" or (sp["align"] == "auto" and is_rtl_text(sp["text"])), load_font(path, size)
    icon_x = (ox + pw - px - isz) if right else ox + px
    tx = (icon_x - gx if isz else ox + pw - px) if right else (icon_x + isz + gx if isz else ox + px)
    if sp["text"]:
        ImageDraw.Draw(pill).text((tx, oy + _baseline(f, ph)), shape(sp["text"]), font=f, fill=t2_rgb(sp["text_color"]) + (255,), anchor="rs" if right else "ls")
    if isz:
        ic = _icon({"icon": sp["icon"]}, isz, isz * 0.12, sp["color"])
        if ic is not None:
            kit_paste(pill, ic, icon_x, oy + (ph - isz) / 2.0)
    dx = {"left": 0.0, "center": (w - pw) / 2.0, "right": w - pw}.get(sp["align"], w - pw if right else 0.0)
    pill.info["origin"] = (int(round(ox - dx)), int(round(oy - (h - ph) / 2.0)))      # box top-left relative to the pill sprite
    return pill


def t4_badge(spec, box, ctx):
    """Widget function: small glass pill (icon or PNG + text) placed inside the slot `box` (left / centre / right, vertically centred). Cached."""
    sp = _badge_spec(spec)
    s = float(ctx.get("s", 1.0)) if isinstance(ctx, dict) else 1.0
    w, h = max(60, int(round(box[2]))), max(30, int(round(box[3])))
    return _cached(_CG, (repr(sp), w, h, round(s, 3)), lambda: _build_badge(sp, w, h, s), 8)


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_ask_bar_chart():
    """Question group of 'bar_chart' (called by t4_ask_scenes) -> spec dict. Colours / steps / timing: edit the job file."""
    d = T4_BAR_CHART
    vals = ask("Bar values, separated by |  (Enter = the demo)", default=" | ".join("%g" % v for v in d["values"]), key="t4_bc_values")
    labs = ask("Bar labels, separated by |", default=" | ".join(d["labels"]), key="t4_bc_labels", allow_empty=True) or ""
    return {"values": [t.strip() for t in str(vals).split("|") if t.strip()], "labels": [t.strip() for t in str(labs).split("|")]}


def t4_ask_progress():
    """Question group of 'progress_list' -> spec dict. Rows as  icon|label|pct ; icon|label|pct  (icon optional)."""
    d = "; ".join("%s|%s|%d" % (r["icon"], r["label"], r["pct"]) for r in T4_PROGRESS["rows"])
    return {"rows": ask("Rows  icon|label|pct ; ...  (icon optional, '-' = none)", default=d, key="t4_pl_rows")}


def t4_ask_badge():
    """Question group of 'badge' -> spec dict."""
    d = T4_BADGE
    return {"text": ask("Badge text", default=d["text"], key="t4_bg_text"),
            "icon": ask("Badge icon (kit name or PNG path, '-' = none)", default=d["icon"], key="t4_bg_icon")}


register_widget("bar_chart", t4_bar_chart, ask=t4_ask_bar_chart, slot="chart")
register_widget("progress_list", t4_progress_list, ask=t4_ask_progress, slot="progress")
register_widget("badge", t4_badge, ask=t4_ask_badge, slot="badge")