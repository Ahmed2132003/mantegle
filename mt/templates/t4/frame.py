"""mt.templates.t4.frame - Template 4 module 'frame' (ref R10, the frame only): a full-canvas neon HUD frame drawn as ONE transparent
foreground plate (the video underneath is never touched). Parts: thin rails, thick double-line corner brackets (TL / TR / BL / BR),
side tick marks, a small neon icon top-right, and a bottom tab (dark glass trapezoid on the bottom rail) with centred TRACKED text
and '////' hazard stripes at both ends of it.
Config cfg['t4']['frame'] = {on, text, color, icon, show_ticks} (+ optional 'font' = a font file; default = the project's default font).
  text   '' (or '-') = no tab and no stripes (rails + brackets only); Arabic / RTL text is drawn untracked (tracking would break joining).
  icon   a kit icon name (code laptop phone gear globe database server cloud bulb chip shield) or '' / 'none' = no icon.
Public: T4_FRAME, t4_frame_cfg(raw), t4_ask_frame(), t4_frame_plate(W, H, fcfg) -> RGBA W x H (cached), t4_frame_part(W, H, t4) -> plate | None
(the part builder registered in t4/__init__.T4_FG_PARTS). Authored in px at short side 1080 (scaled for other sizes); rails sit 30 px
from the edge (decoration), the tab text stays well inside the 48 px safe margin."""
import os

from PIL import Image, ImageDraw

from mt.common import ask, ask_choice, c_color, yn
from mt.draw import t2_glow, t2_lighten, t2_paint, t2_poly_mask, t2_rgb
from mt.fonts import default_font, is_rtl_text, load_font, shape
from mt.templates.t4.cfg import _hex
from mt.templates.t4.kit import _glass_sprite, connector, hazard_stripes, kit_paste, neon_icon
from mt.templates.t4.kit_icons import ICON_NAMES
from mt.templates.t4.warn import t4_warn

T4_FRAME = {"on": False, "text": "CODE • BUILD • INSPIRE", "color": "#19D3FF", "icon": "code", "show_ticks": True}
INSET = 30                                                    # rail distance from the canvas edge (px at short side 1080)
ARMS = {"tl": (78, 100), "tr": (90, 140), "bl": (70, 84), "br": (70, 84)}      # bracket arms (horizontal, vertical) as in R10
TICKS = {"l": ((0.285, 0.385), (0.64, 0.665)), "r": ((0.27, 0.43), (0.60, 0.64))}   # tick groups: y ranges as fractions of H
_OFF = ("", "none", "off", "false", "no", "0", "-")
_CACHE = {}


# ---- config -----------------------------------------------------------------------------------------------------------------
def _bool(v, default):
    if isinstance(v, str):
        return default if not v.strip() else v.strip().lower() not in _OFF
    return default if v is None else bool(v)


def t4_frame_cfg(raw):
    """Normalise cfg['t4']['frame'] -> {on, text, color, icon, show_ticks, ...extra keys}. Never raises; junk -> defaults."""
    out = dict(T4_FRAME)
    if not isinstance(raw, dict):
        return out
    try:
        out.update({k: v for k, v in raw.items() if k not in out})            # extras (font ...) survive
        out["on"] = _bool(raw.get("on"), False)
        t = raw.get("text")
        if isinstance(t, str):
            out["text"] = "" if t.strip().lower() in ("-", "none") else t.strip()[:60]
        out["color"] = _hex(raw.get("color"), T4_FRAME["color"])
        ic = raw.get("icon")
        out["icon"] = "" if (ic is False or (isinstance(ic, str) and ic.strip().lower() in _OFF)) \
            else (ic.strip().lower() if isinstance(ic, str) else T4_FRAME["icon"])
        out["show_ticks"] = _bool(raw.get("show_ticks"), True)
    except Exception:
        return dict(T4_FRAME)
    return out


def t4_ask_frame(gate=True):
    """Question group 'frame' (called by t4_ask_config). -> the frame dict for cfg['t4']['frame']."""
    if gate and not yn("Add the neon HUD frame (corner brackets, side ticks, bottom bar)?", default=False):
        return {"on": False}
    text = ask("Bottom bar text ('-' = no bar; Arabic works too)", default=T4_FRAME["text"], key="t4_frame_text",
               cast=lambda s: "" if s.strip() in ("-", "none") else s.strip())
    color = ask("Frame colour (hex or name)", default=T4_FRAME["color"], key="t4_frame_color", cast=c_color)
    ic = ask_choice("Small icon in the top-right corner:", ["None"] + list(ICON_NAMES), default=2, key="t4_frame_icon")
    return {"on": True, "text": text, "color": color, "icon": "" if ic == 1 else ICON_NAMES[ic - 2],
            "show_ticks": yn("Side tick marks?", default=True)}


# ---- rails, brackets, ticks, icon -------------------------------------------------------------------------------------------
def _bracket(pl, cx, cy, sx, sy, arms, col, s):
    """One corner: thick chamfered L (outer) + a shorter thin line inside it. (cx, cy) = the corner, (sx, sy) = inward direction."""
    ah, av, c, d = arms[0] * s, arms[1] * s, 20 * s, 12 * s
    c2 = max(4.0, c * 0.65)

    def P(pts):
        return [(cx + sx * x, cy + sy * y) for x, y in pts]
    kit_paste(pl, connector(P([(ah, 0), (c, 0), (0, c), (0, av)]), col, False, 9.0 * s, 15 * s), 0, 0)
    kit_paste(pl, connector(P([(d + ah * 0.55, d), (d + c2, d), (d, d + c2), (d, d + av * 0.55)]), col, False, 3.0 * s, 7 * s), 0, 0)


def _rails(pl, W, H, col, s):
    m = INSET * s
    a = {k: (v[0] * s, v[1] * s) for k, v in ARMS.items()}
    for pts in ([(m + a["tl"][0], m), (W - m - a["tr"][0], m)], [(m + a["bl"][0], H - m), (W - m - a["br"][0], H - m)],
                [(m, m + a["tl"][1]), (m, H - m - a["bl"][1])], [(W - m, m + a["tr"][1]), (W - m, H - m - a["br"][1])]):
        kit_paste(pl, connector(pts, col, False, 2.8 * s, 9 * s), 0, 0)
    for key, cx, cy, sx, sy in (("tl", m, m, 1, 1), ("tr", W - m, m, -1, 1), ("bl", m, H - m, 1, -1), ("br", W - m, H - m, -1, -1)):
        _bracket(pl, cx, cy, sx, sy, ARMS[key], col, s)


def _tick_group(pl, x_edge, y0, y1, right, col, s):
    """A column of short horizontal dashes (alternating long / short, fading at both ends) hugging a side rail."""
    pad, step, th = int(10 * s), 12.0 * s, max(2, int(round(4 * s)))
    n = max(1, int((y1 - y0) // step))
    w, h = int(24 * s) + 2 * pad, int(y1 - y0) + 2 * pad
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    for i in range(n):
        ln = int((21 if i % 2 == 0 else 11) * s)
        fade = min(1.0, 0.35 + 1.3 * min(i, n - 1 - i) / max(1.0, n / 2.0))
        y = pad + int(i * step)
        x0 = (w - pad - ln) if right else pad
        d.rectangle((x0, y, x0 + ln, y + th), fill=int(255 * fade))
    sp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    c = t2_rgb(col)
    t2_paint(sp, t2_glow((m, (0, 0)), 4 * s, 1.1), c, 0.55)
    t2_paint(sp, (m, (0, 0)), c)
    t2_paint(sp, (m, (0, 0)), t2_lighten(c, 0.6), 0.35)
    kit_paste(pl, sp, (x_edge - (w - pad) if right else x_edge - pad), y0 - pad)


def _ticks(pl, W, H, col, s):
    m = INSET * s
    for side, groups in TICKS.items():
        for a, b in groups:
            _tick_group(pl, (W - m - 14 * s) if side == "r" else (m + 14 * s), H * a, H * b, side == "r", col, s)


def _corner_icon(pl, W, name, col, s):
    sz = int(84 * s)
    ic = neon_icon(name, sz, col)
    kit_paste(pl, ic, W - (INSET + 100) * s - sz / 2.0, (INSET + 98) * s - sz / 2.0)


# ---- bottom bar -------------------------------------------------------------------------------------------------------------
def _fit_text(text, fp, size, track, avail):
    """Shrink size, then tracking, then truncate until the run fits `avail` px -> (font, text, track_px, width). RTL: untracked."""
    rtl = is_rtl_text(text)
    for _ in range(60):
        f = load_font(fp, max(8, int(round(size))))
        t = shape(text) if rtl else text
        tp = 0.0 if rtl else track * size
        w = f.getlength(t) if rtl else sum(f.getlength(ch) for ch in t) + tp * max(0, len(t) - 1)
        if w <= avail or len(text) <= 1:
            return f, t, tp, w
        if size > 14:
            size -= 1.5
        elif track > 0.04 and not rtl:
            track -= 0.05
        else:
            text = text[:-2].rstrip() + "…"
    return f, t, tp, w


def _draw_tab_text(pl, f, t, tp, w, cx, base_y, rtl, col, s):
    """White text (tracked per character for LTR) with a faint neon halo."""
    m = Image.new("L", pl.size, 0)
    d = ImageDraw.Draw(m)
    if rtl:
        d.text((cx - w / 2.0, base_y), t, font=f, fill=255, anchor="ls")
    else:
        x = cx - w / 2.0
        for ch in t:
            d.text((x, base_y), ch, font=f, fill=255, anchor="ls")
            x += f.getlength(ch) + tp
    bb = m.getbbox()
    if not bb:
        return
    pad = int(14 * s)
    crop = m.crop((bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad))
    box = (bb[0] - pad, bb[1] - pad)
    t2_paint(pl, t2_glow((crop, box), 5 * s, 1.0), t2_rgb(col), 0.45)
    t2_paint(pl, (crop, box), (255, 255, 255))


def _hazards(pl, xl, xr, y, hw, hh, col):
    """'////' marks: the group ending at xl (left of the tab) and the one starting at xr (right of it)."""
    for x in (xl - hw, xr):
        kit_paste(pl, hazard_stripes((hw, hh), 32.0, col, 8, hh * 0.52, hh * 0.40), x, y)


def _bottom_bar(pl, W, H, text, fp, col, s):
    m, th, sl = INSET * s, 60 * s, 34 * s
    rtl = is_rtl_text(text)
    bw_max = min(0.64 * W, 860 * s)
    f, t, tp, tw = _fit_text(text, fp, 26 * s, 0.30, bw_max - 2 * sl - 80 * s)
    top_w = tw + 80 * s
    bw = top_w + 2 * sl
    x0, yb = (W - bw) / 2.0, H - m
    yt = yb - th
    mask = t2_poly_mask([(sl, 0), (bw - sl, 0), (bw, th), (0, th)], round_r=5 * s)
    kit_paste(pl, _glass_sprite(mask, (6, 14, 34, 218), col, max(2.0, 2.4 * s), 12 * s), x0, yt)
    asc, desc = f.getmetrics()
    _draw_tab_text(pl, f, t, tp, tw, W / 2.0, (yt + yb) / 2.0 + (asc - desc) / 2.0, rtl, col, s)
    hw = min(108 * s, x0 - 40 * s - (m + 14 * s))
    if hw >= 40 * s:
        _hazards(pl, x0 - 40 * s, x0 + bw + 40 * s, yb - 44 * s, hw, 26 * s, col)


# ---- plate ------------------------------------------------------------------------------------------------------------------
def t4_frame_plate(W, H, fcfg):
    """The transparent W x H RGBA frame plate for a normalised frame dict (cached per size + look; returns a private copy)."""
    W, H = int(W), int(H)
    fp = fcfg.get("font")
    if isinstance(fp, str) and fp.strip() and not os.path.isfile(fp):
        t4_warn("frame: font '%s' not found - using the default font." % os.path.basename(fp))
    fp = fp if isinstance(fp, str) and os.path.isfile(fp) else default_font()
    ic = fcfg["icon"] if fcfg["icon"] in ICON_NAMES else ""
    key = (W, H, fcfg["color"], fcfg["text"], ic, bool(fcfg["show_ticks"]), fp)
    if key not in _CACHE:
        s, col = min(W, H) / 1080.0, fcfg["color"]
        pl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _rails(pl, W, H, col, s)
        if fcfg["show_ticks"]:
            _ticks(pl, W, H, col, s)
        if ic:
            _corner_icon(pl, W, ic, col, s)
        if fcfg["text"]:
            _bottom_bar(pl, W, H, fcfg["text"], fp, col, s)
        if len(_CACHE) >= 4:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = pl
    return _CACHE[key].copy()


def t4_frame_part(W, H, t4):
    """Part builder for t4_compose_fg: the frame plate, or None when the module is off. Warns once for an unknown icon."""
    f = t4_frame_cfg((t4 or {}).get("frame"))
    if not f["on"]:
        return None
    if f["icon"] and f["icon"] not in ICON_NAMES:
        t4_warn(f"frame icon '{f['icon']}' unknown (use one of: {', '.join(ICON_NAMES)}) - no icon")
    return t4_frame_plate(W, H, f)
