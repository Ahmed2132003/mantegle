"""mt.templates.t4.scenes_bullets - Template 4 scenes: widget 'bullet_list' (cyan glow dot + text rows, staggered; refs R5 / R6).
spec keys (all optional; px at short side 1080): items ['..', ..] (<= 12; missing = demo list), color '#19D3FF' (dot), text_color '#FFFFFF',
  dot 12 (diameter), glow 8 (dot glow), size 34 (font px), gap 22 (between rows), align 'auto' | 'left' | 'right' (auto = right when the first item is
  Arabic / RTL: dot on the right, text right-aligned), max_width None (px; wrap width, default = the box width), font '' (path), anim 'fade' | 'reveal' | 'pop',
  line_step 0.3 (s between rows), line_dur 0.35.
Text wraps to <= 2 lines per row (then '...'); everything shrinks to 60 % when the rows are taller than the box. Arabic goes through mt.fonts.shape.
The static sprite is EMPTY: each row is its own sprite in sprite.info['lines'] (+ 'lines_only', 'ink', 'line_anim', 'line_step', 'line_dur') and the engine adds one
staggered Item per row through t4_widget_line_items(). Public: T4_BULLETS, t4_bullet_list(spec, box, ctx), t4_ask_bullets()."""
import math

from PIL import Image

from mt.common import ask, ask_choice
from mt.draw import t2_draw_mask, t2_glow, t2_lighten, t2_paint, t2_rgb
from mt.fonts import default_font, is_rtl_text, load_font, shape
from mt.templates.t4.nameplate import _cached, _flt
from mt.templates.t4.scenes_reg import register_widget
from mt.templates.t4.scenes_title import _color
from mt.templates.t4.scenes_widgets import _baseline
from mt.templates.t4.warn import t4_warn

T4_BULLETS = {"items": ["Responsive websites", "Fast and secure", "Modern UI / UX"], "color": "#19D3FF", "text_color": "#FFFFFF", "dot": 12.0,
              "glow": 8.0, "size": 34.0, "gap": 22.0, "align": "auto", "max_width": None, "font": "", "anim": "fade", "line_step": 0.3, "line_dur": 0.35}
MAX_ITEMS = 12
_BC = {}


# ---- spec -------------------------------------------------------------------------------------------------------------------
def _items(raw):
    if "items" not in raw:
        return list(T4_BULLETS["items"])
    v = raw["items"]
    v = v.replace("\\n", "\n").split("\n") if isinstance(v, str) else v if isinstance(v, (list, tuple)) else []
    out = [str(x).strip() for x in v if x is not None and str(x).strip()]
    if len(out) > MAX_ITEMS:
        t4_warn("bullet_list: %d items - only the first %d are used." % (len(out), MAX_ITEMS))
        out = out[:MAX_ITEMS]
    return out


def _spec(raw):
    """Complete, clean spec (never raises; junk -> defaults)."""
    raw = raw if isinstance(raw, dict) else {}
    d, items = T4_BULLETS, _items(raw)
    al = raw.get("align")
    al = {"left": "left", "l": "left", "ltr": "left", "right": "right", "r": "right", "rtl": "right"}.get(al.strip().lower() if isinstance(al, str) else "", "auto")
    if al == "auto":
        al = "right" if items and is_rtl_text(items[0]) else "left"
    mw, fo, an = raw.get("max_width"), raw.get("font"), raw.get("anim")
    an = an.strip().lower() if isinstance(an, str) else "fade"
    return {"items": items, "color": _color(raw.get("color"), d["color"]), "text_color": _color(raw.get("text_color"), d["text_color"]),
            "dot": _flt(raw.get("dot"), 3, 80, d["dot"]), "glow": _flt(raw.get("glow"), 0, 40, d["glow"]), "size": _flt(raw.get("size"), 8, 200, d["size"]),
            "gap": _flt(raw.get("gap"), 0, 200, d["gap"]), "align": al, "max_width": None if mw is None else _flt(mw, 40, 4000, 400.0),
            "font": fo.strip() if isinstance(fo, str) else "", "anim": an if an in ("fade", "reveal", "pop") else "fade",
            "line_step": _flt(raw.get("line_step"), 0.0, 5.0, d["line_step"]), "line_dur": _flt(raw.get("line_dur"), 0.05, 5.0, d["line_dur"])}


# ---- text -------------------------------------------------------------------------------------------------------------------
def _font(path):
    if path and __import__("os").path.isfile(path):
        return path
    if path:
        t4_warn("bullet_list: font '%s' not found - using the default font." % path.replace("\\", "/").split("/")[-1])
    return default_font()


def _wrap(text, f, maxw):
    """Greedy word wrap (logical order); f must be the font loaded last (shape() reads it)."""
    lines, cur = [], ""
    for wd in text.split():
        t = (cur + " " + wd).strip()
        if cur and f.getlength(shape(t)) > maxw:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    return lines + [cur] if cur else lines or [""]


def _cap(lines, f, maxw):
    """<= 2 lines: the rest of the text is folded into line 2 and cut with an ellipsis."""
    if len(lines) <= 2:
        return lines
    last = " ".join(lines[1:])
    while len(last) > 1 and f.getlength(shape(last + "\u2026")) > maxw:
        last = last[:-1]
    return [lines[0], last + "\u2026"]


def _layout(sp, bw, bh, s, path):
    """-> (size, dot d, dot-text gap, line height, row gap, rows = [[line]]); everything x k (>= 0.6) when the rows are taller than the box."""
    k, maxw = 1.0, min(bw, sp["max_width"] * s) if sp["max_width"] else bw
    for _ in range(2):
        size, d = max(8, int(round(sp["size"] * s * k))), max(4.0, sp["dot"] * s * k)
        gx, f = max(8.0, d * 1.1), load_font(path, max(8, int(round(sp["size"] * s * k))))
        avail = max(20.0, maxw - d - gx)
        rows = [_cap(_wrap(t, f, avail), f, avail) for t in sp["items"]]
        lh, gap = size * 1.25, sp["gap"] * s * k
        total = sum(len(r) for r in rows) * lh + gap * (len(rows) - 1)
        if total <= bh or k < 1.0:
            break
        k = max(0.6, bh / total)
    if total > bh * 1.02:
        t4_warn("bullet_list: the rows are taller than the box (%d > %d px) - give it a taller box / fewer items." % (total, bh))
    return size, d, gx, lh, gap, rows


# ---- drawing ----------------------------------------------------------------------------------------------------------------
def _dot(im, cx, cy, r, color, glow):
    """Filled disc with a light glow + near-white core, drawn straight into `im` (local coords = sprite px)."""
    def disc(rr):
        def fn(d, L, s):
            a, b = L(cx - rr, cy - rr), L(cx + rr, cy + rr)
            d.ellipse((a[0], a[1], b[0] - 1, b[1] - 1), fill=255)
        return t2_draw_mask((cx - rr, cy - rr, cx + rr, cy + rr), fn)
    c, m = t2_rgb(color), disc(r)
    if glow > 0:
        t2_paint(im, t2_glow(m, max(2.0, glow * 0.6), 1.1), c, 0.6)
    t2_paint(im, m, c)
    t2_paint(im, disc(r * 0.45), t2_lighten(c, 0.85))


def _row(sp, f, lines, size, d, gx, lh, glow, pad):
    """One row sprite (dot + text lines) -> (RGBA, content w, content h). f = the font loaded last."""
    from PIL import ImageDraw
    shaped = [shape(t) for t in lines]
    tw = max(f.getlength(t) for t in shaped)
    w, h, right = int(math.ceil(d + gx + tw)), int(math.ceil(len(lines) * lh)), sp["align"] == "right"
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    _dot(im, pad + (w - d / 2.0 if right else d / 2.0), pad + lh / 2.0, d / 2.0, sp["color"], glow)
    dr, fill = ImageDraw.Draw(im), t2_rgb(sp["text_color"]) + (255,)
    x = pad + (w - d - gx if right else d + gx)
    for i, t in enumerate(shaped):
        dr.text((x, pad + i * lh + _baseline(f, lh)), t, font=f, fill=fill, anchor="rs" if right else "ls")
    return im, w, h


def _build(sp, bw, bh, s):
    if not sp["items"]:
        t4_warn("bullet_list: no items - skipped.")
        return None
    path = _font(sp["font"])
    size, d, gx, lh, gap, rows = _layout(sp, bw, bh, s, path)
    f, glow = load_font(path, size), sp["glow"] * s
    pad = int(glow * 2.6) + 4
    parts, y = [], 0.0
    for lines in rows:
        im, w, h = _row(sp, f, lines, size, d, gx, lh, glow, pad)
        x = float(bw - w) if sp["align"] == "right" else 0.0
        parts.append((im, int(round(x)), int(round(y)), w, h))
        y += len(lines) * lh + gap
    spr = Image.new("RGBA", (int(bw) + 2 * pad, int(max(bh, y - gap)) + 2 * pad), (0, 0, 0, 0))
    ink = (pad + min(p[1] for p in parts), pad + min(p[2] for p in parts), pad + max(p[1] + p[3] for p in parts), pad + max(p[2] + p[4] for p in parts))
    spr.info.update({"origin": (pad, pad), "ink": ink, "lines_only": True, "lines": [(p[0], p[1], p[2]) for p in parts], "line_step": sp["line_step"],
                     "line_dur": sp["line_dur"], "line_anim": {"pop": "t4_pop"}.get(sp["anim"], sp["anim"])})
    return spr


def t4_bullet_list(spec, box, ctx):
    """Widget function: staggered dot + text rows in the slot `box` = (x, y, w, h) canvas px. sprite.info['origin'] = the box's top-left;
    the sprite itself is empty, the rows are in sprite.info['lines'] (see t4_widget_line_items). Cached."""
    sp = _spec(spec)
    s = float(ctx.get("s", 1.0)) if isinstance(ctx, dict) else 1.0
    w, h = max(60, int(round(box[2]))), max(40, int(round(box[3])))
    return _cached(_BC, (repr(sp), w, h, round(s, 3)), lambda: _build(sp, w, h, s), 6)


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_ask_bullets():
    """Question group of the widget (called by t4_ask_scenes) -> spec dict. Colours / sizes / timing: edit the job file."""
    d = T4_BULLETS
    raw = ask("Bullet items, separated by | (Enter = the demo list)", default=" | ".join(d["items"]), key="t4_bl_items")
    out = {"items": [t.strip() for t in str(raw).split("|") if t.strip()]}
    out["align"] = ["auto", "left", "right"][ask_choice("Alignment", ["Auto (Arabic = right)", "Left", "Right"], default=1, key="t4_bl_align") - 1]
    return out


register_widget("bullet_list", t4_bullet_list, ask=t4_ask_bullets, slot="bullets")