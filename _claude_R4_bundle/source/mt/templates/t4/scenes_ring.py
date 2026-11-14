"""mt.templates.t4.scenes_ring - Template 4 scenes: widget 'ring' (neon concentric arcs around a centre icon, refs R5 / R6).
spec keys (all optional; px at short side 1080): rings 3 | [ {arcs, gap, width, glow, color, rotate}, ... ] (a list = one dict per ring, overrides
  the global keys), arcs 2 (arcs per ring: 2 = halves; int | list per ring), gap 28 (deg between arcs; int | list), width 4, glow 10,
  color / colors (a list cycles per ring), rotate (start angle in deg, clockwise from the top; default 20 + 55 * ring), spacing 20 (px between rings),
  icon 'code' (kit icon name | PNG path | ''/'-'/'none'), icon_color '' (= colour of ring 1), icon_size 0.6 (share of the inner diameter),
  icon_glow None (auto). Rings fit min(box.w, box.h); sprite = box + glow margin, info['origin'] = the box's top-left. Cached.
Public: T4_RING, t4_ring(spec, box, ctx), t4_ask_ring()."""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

from mt.common import ask, ask_choice
from mt.draw import t2_draw_mask, t2_rgb
from mt.templates.t4.kit import PALETTE, kit_paste, neon_icon, neon_stroke
from mt.templates.t4.nameplate import _cached, _flt
from mt.templates.t4.scenes_reg import register_widget
from mt.templates.t4.scenes_title import _color
from mt.templates.t4.warn import t4_warn

T4_RING = {"rings": 3, "arcs": 2, "gap": 28.0, "width": 4.0, "glow": 10.0, "spacing": 20.0, "icon": "code", "icon_color": "",
           "icon_size": 0.6, "icon_glow": None}
DEFAULT_COLORS = ("#19D3FF", "#1E6BFF", "#19D3FF")
MAX_RINGS = 8
_PNG_EXT = (".png", ".jpg", ".jpeg", ".webp")
_RC, _BAD = {}, set()


# ---- spec -------------------------------------------------------------------------------------------------------------------
def _pick(v, i, default):
    if isinstance(v, (list, tuple)):
        return v[i % len(v)] if v else default
    return default if v is None else v


def _val(rd, raw, key, i, default, alt=None):
    """Value of ring i: the ring's own dict first, then the global key (scalar or per-ring list)."""
    for src in (rd, raw):
        for k in (key, alt):
            if k and src.get(k) is not None:
                return _pick(src[k], i, default)
    return default


def _ring(rd, raw, i):
    arcs = int(_flt(_val(rd, raw, "arcs", i, 2), 1, 12, 2))
    gap = min(_flt(_val(rd, raw, "gap", i, 28.0), 0, 180, 28.0), max(0.0, 360.0 / arcs - 6.0))
    rot, col = 20.0 + 55.0 * i, DEFAULT_COLORS[i % 3]
    return {"arcs": arcs, "gap": gap, "width": _flt(_val(rd, raw, "width", i, 4.0), 0.5, 30, 4.0),
            "glow": _flt(_val(rd, raw, "glow", i, 10.0), 0, 60, 10.0), "rotate": _flt(_val(rd, raw, "rotate", i, rot), -720, 720, rot),
            "color": _color(_val(rd, raw, "color", i, col, "colors"), col)}


def _spec(raw):
    """Complete, clean spec (never raises; junk -> defaults); out['_rings'] = one dict per ring."""
    raw = raw if isinstance(raw, dict) else {}
    rg = raw.get("rings", T4_RING["rings"])
    if isinstance(rg, (list, tuple)):
        rds = [r if isinstance(r, dict) else {} for r in rg][:MAX_RINGS]
    else:
        rds = [{}] * int(round(_flt(rg, 0, MAX_RINGS, 3)))
    ic = raw.get("icon", T4_RING["icon"])
    ic = ic.strip() if isinstance(ic, str) else ""
    ig = raw.get("icon_glow")
    col = raw.get("icon_color")
    return {"_rings": [_ring(rd, raw, i) for i, rd in enumerate(rds)], "spacing": _flt(raw.get("spacing"), 0, 200, 20.0),
            "icon": "" if ic.lower() in ("-", "none") else ic, "icon_color": col if isinstance(col, str) else "",
            "icon_size": _flt(raw.get("icon_size"), 0.1, 1.0, 0.6), "icon_glow": None if ig is None else _flt(ig, 0, 60, 0.0)}


# ---- drawing ----------------------------------------------------------------------------------------------------------------
def _arc_mask(R, a0, a1, wd):
    """Filled arc band (thickness wd, round ends) centred on local (0, 0); angles in deg, clockwise from the top."""
    ro, ri, full = R + wd / 2.0, max(0.5, R - wd / 2.0), a1 - a0 >= 359.9
    n = max(6, int(abs(a1 - a0) / 1.5))
    angs = [a0 + (a1 - a0) * k / n for k in range(n + 1)]

    def P(r, a):
        t = math.radians(a)
        return r * math.sin(t), -r * math.cos(t)
    poly = [P(ro, a) for a in angs] + [P(ri, a) for a in reversed(angs)]
    ends = [] if full else [P(R, a0), P(R, a1)]
    bb = (min(p[0] for p in poly) - wd - 1, min(p[1] for p in poly) - wd - 1, max(p[0] for p in poly) + wd + 1, max(p[1] for p in poly) + wd + 1)

    def fn(d, L, s):
        if full:
            for r, v in ((ro, 255), (ri, 0)):
                a, b = L(-r, -r), L(r, r)
                d.ellipse((a[0], a[1], b[0] - 1, b[1] - 1), fill=v)
            return
        d.polygon([L(x, y) for x, y in poly], fill=255)
        for ex, ey in ends:
            a, b = L(ex - wd / 2.0, ey - wd / 2.0), L(ex + wd / 2.0, ey + wd / 2.0)
            d.ellipse((a[0], a[1], b[0] - 1, b[1] - 1), fill=255)
    return t2_draw_mask(bb, fn)


def _plan(rings, spacing, w, h, s):
    """-> ([(radius, ring)], inner radius free for the icon). Rings that no longer fit are dropped (one warning)."""
    half, out, R = min(w, h) / 2.0, [], 0.0
    for i, r in enumerate(rings):
        wd = r["width"] * s
        R = half - wd / 2.0 - 1 if i == 0 else R - (rings[i - 1]["width"] * s + wd) / 2.0 - spacing * s
        if R < wd * 2 + 4:
            t4_warn("ring: only %d of %d rings fit the box - the inner ones are dropped." % (len(out), len(rings)))
            break
        out.append((R, r))
    inner = out[-1][0] - out[-1][1]["width"] * s / 2.0 - spacing * s * 0.6 if out else half
    return out, max(4.0, inner)


def _png_icon(path, px, glow, color):
    """PNG fitted into px x px with a soft halo (kit sprite convention: origin = the icon box's top-left). Missing file -> gray placeholder."""
    try:
        im = Image.open(path).convert("RGBA")
        im.thumbnail((px, px), Image.LANCZOS)
    except Exception:
        if path not in _BAD:
            _BAD.add(path)
            t4_warn("ring: icon '%s' could not be read - gray placeholder." % os.path.basename(path))
        im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle((0, 0, px - 1, px - 1), radius=px // 5, fill=(120, 130, 140, 200))
    pad = int(glow * 2.6) + 4
    sp = Image.new("RGBA", (px + 2 * pad, px + 2 * pad), (0, 0, 0, 0))
    pos = (pad + (px - im.width) // 2, pad + (px - im.height) // 2)
    if glow > 0:
        a = Image.new("L", sp.size, 0)
        a.paste(im.getchannel("A"), pos)
        halo = Image.new("RGBA", sp.size, t2_rgb(color) + (0,))
        halo.putalpha(a.filter(ImageFilter.GaussianBlur(glow)).point(lambda v: min(255, int(v * 1.2))))
        sp.alpha_composite(halo)
    sp.alpha_composite(im, pos)
    sp.info["origin"] = (pad, pad)
    return sp


def _icon(sp, px, glow, color):
    v = sp["icon"]
    if not v:
        return None
    if os.path.isfile(v) or v.lower().endswith(_PNG_EXT) or "/" in v or "\\" in v:
        return _png_icon(v, px, glow, color)
    return neon_icon(v, px, color, glow)                      # unknown kit name -> kit warns + empty icon


def _build(sp, w, h, s):
    plan, r_in = _plan(sp["_rings"], sp["spacing"], w, h, s)
    first = sp["_rings"][0]["color"] if sp["_rings"] else PALETTE["cyan"]
    px = max(8, int(round(sp["icon_size"] * 2 * r_in)))
    ig = (px * 0.12 if sp["icon_glow"] is None else sp["icon_glow"] * s)
    m = int(max([r["glow"] * s for _, r in plan] + [ig]) * 2.6 + max([r["width"] * s for _, r in plan] + [0]) + 8)
    spr, cx, cy = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0)), m + w / 2.0, m + h / 2.0
    for R, r in plan:                                          # outer -> inner
        span, wd = 360.0 / r["arcs"], r["width"] * s
        for k in range(r["arcs"]):
            a0 = r["rotate"] + k * span + r["gap"] / 2.0
            kit_paste(spr, neon_stroke(_arc_mask(R, a0, a0 + span - r["gap"], wd), r["color"], wd, r["glow"] * s), cx, cy)
    ic = _icon(sp, px, ig, sp["icon_color"] or first)
    if ic is not None:
        kit_paste(spr, ic, cx - px / 2.0, cy - px / 2.0)
    if not plan and ic is None:
        t4_warn("ring: no rings and no icon - skipped.")
        return None
    spr.info["origin"] = (m, m)
    return spr


def t4_ring(spec, box, ctx):
    """Widget function: concentric neon arcs + centre icon in the slot `box` = (x, y, w, h) canvas px. sprite.info['origin'] = the box's top-left."""
    sp = _spec(spec)
    s = float(ctx.get("s", 1.0)) if isinstance(ctx, dict) else 1.0
    w, h = max(40, int(round(box[2]))), max(40, int(round(box[3])))
    return _cached(_RC, (repr(sp), w, h, round(s, 3)), lambda: _build(sp, w, h, s), 6)


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_ask_ring():
    """Question group of the widget (called by t4_ask_scenes) -> spec dict. Colours / widths / gaps / per-ring lists: edit the job file."""
    d = T4_RING
    out = {"icon": ask("Ring icon (kit: code laptop phone gear globe database server cloud bulb chip shield | PNG path | - = none)",
                        default=d["icon"], key="t4_ring_icon")}
    try:
        out["rings"] = max(0, min(MAX_RINGS, int(ask("Number of rings (1-6)", default=str(d["rings"]), key="t4_ring_n"))))
    except (TypeError, ValueError):
        out["rings"] = d["rings"]
    out["arcs"] = [2, 3, 4, 1][ask_choice("Arcs per ring", ["2 (halves)", "3", "4", "1 (closed ring)"], default=1, key="t4_ring_arcs") - 1]
    return out


register_widget("ring", t4_ring, ask=t4_ask_ring, slot="ring")