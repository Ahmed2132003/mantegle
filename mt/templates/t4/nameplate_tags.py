"""mt.templates.t4.nameplate_tags - Template 4: the two name-tag sprites of the 'nameplate' module.
  tag_a  ref R2:  dark glass panel with hexagon-cut ends (big cuts on the left), neon border, '</>' icon | divider | name + role,
                  three slanted stripes inside the bottom-right corner.
  tag_b  ref R10: chamfered panel with a faint second outline, icon | divider | NAME (white) + ROLE (neon colour) in capitals, a bright
                  bar on the bottom edge and five slanted stripes hanging below it.
Public: TAG_STYLES, T4_TAG, t4_tag_sprite(style, name, role, icon, color, font, scale, max_w) -> RGBA sprite | None.
Authored in px at short side 1080 (scale = short side / 1080). The sprite carries its own glow margin (about 30 px); the placement
code (nameplate.py) measures the visible ink, so the margin never counts against the 48 px safe area. Arabic / RTL text is shaped with
mt.fonts.shape and right-aligned in the text area; Latin text is left-aligned."""
import os
from pathlib import Path

from PIL import Image, ImageDraw

from mt.draw import t2_lighten, t2_rgb
from mt.fonts import default_font, is_rtl_text, load_font, shape
from mt.templates.t4.kit import chamfer_rect, connector, glass_panel, hazard_stripes, kit_paste, neon_icon, neon_stroke

TAG_STYLES = ("tag_a", "tag_b")
T4_TAG = {                                    # px at short side 1080; cut = chamfers (top-left, top-right, bottom-right, bottom-left)
    "tag_a": {"h": 124, "min_w": 440, "icon_w": 112, "icon": 58, "name": 38, "role": 26, "right": 104, "cut": (26, 16, 12, 26), "caps": False},
    "tag_b": {"h": 112, "min_w": 520, "icon_w": 108, "icon": 54, "name": 34, "role": 24, "right": 44, "cut": (24, 24, 24, 16), "caps": True},
}
GLOW_PAD = 30                                 # transparent margin around the panel (glow room), px at short side 1080
TINT = (5, 12, 30, 214)                       # panel fill (rgba): darker than the kit's default glass, as R2 / R10


def _is_bold(path):
    n = Path(str(path)).stem.lower().replace("-", "").replace(" ", "")
    return any(k in n for k in ("bold", "black", "heavy", "extrabold", "semibold"))


def _fade(sp, a):
    sp.putalpha(sp.getchannel("A").point(lambda v: int(v * a)))
    return sp


def _fit(lines, fp, sizes, avail):
    """Shrink both font sizes together (down to 55 %), then cut the widest line with '...' until it fits `avail` px.
    -> (fonts, shaped lines, widest width). An empty line is allowed (width 0)."""
    texts, k = [str(t) for t in lines], 1.0
    for _ in range(120):
        fonts = [load_font(fp, max(8, int(round(sz * k)))) for sz in sizes]
        shaped = [shape(t) for t in texts]
        ws = [f.getlength(t) if t else 0.0 for f, t in zip(fonts, shaped)]
        if max(ws) <= avail or max(len(t) for t in texts) <= 2:
            break
        if k > 0.55:
            k -= 0.05
        else:
            i = ws.index(max(ws))
            texts[i] = texts[i][:-2].rstrip() + "…"
    return fonts, shaped, max(ws)


# ---- parts ------------------------------------------------------------------------------------------------------------------
def _panel(spr, style, w, H, g, col, s):
    """Glass panel + the style's extras (tag_a: stripes inside the corner; tag_b: outer outline, bottom bar, hanging stripes)."""
    sp = T4_TAG[style]
    cut = tuple(c * s for c in sp["cut"])
    if style == "tag_b":                                                # faint second outline, 8 px outside (R10's double border)
        d = 8 * s
        outer = neon_stroke(chamfer_rect((w + 2 * d, H + 2 * d), tuple(c + d for c in cut)), col, 1.4 * s, 5 * s)
        kit_paste(spr, _fade(outer, 0.45), g - d, g - d)
        ln = connector([(g + 44 * s, g + H + 9 * s), (g + w * 0.50, g + H + 9 * s)], col, False, 1.5 * s, 5 * s)
        kit_paste(spr, _fade(ln, 0.55), 0, 0)
    kit_paste(spr, glass_panel((w, H), 0, TINT, col, cut, 2.6 * s, 11 * s), g, g)
    if style == "tag_a":
        sw, sh = int(round(62 * s)), int(round(24 * s))
        kit_paste(spr, hazard_stripes((sw, sh), 35.0, col, 5, 10 * s, 6 * s), g + w - 24 * s - sw, g + H - 15 * s - sh)
    else:
        bar = connector([(g + w * 0.24, g + H), (g + w * 0.36, g + H)], t2_lighten(col, 0.30), False, 5 * s, 10 * s)
        kit_paste(spr, bar, 0, 0)
        sw, sh = int(round(116 * s)), int(round(18 * s))
        kit_paste(spr, hazard_stripes((sw, sh), 35.0, col, 5, 12 * s, 7 * s), g + w * 0.53, g + H - 4 * s)


def _emblem(spr, icon, left, H, g, col, s):
    """Neon icon centred in the left block + the thin vertical divider on its right edge. No icon -> nothing."""
    if not icon:
        return
    isz = int(round(T4_TAG["tag_a"]["icon"] * s))
    ic = neon_icon(icon, isz, col, 8 * s)
    kit_paste(spr, ic, g + left / 2.0 - isz / 2.0, g + H / 2.0 - isz / 2.0)
    x = g + left
    kit_paste(spr, connector([(x, g + H * 0.24), (x, g + H * 0.76)], t2_lighten(col, 0.15), False, 2.0 * s, 5 * s), 0, 0)


def _texts(spr, fonts, shaped, x0, x1, ymid, rtl, bold, fills, s):
    """Lines stacked and centred on ymid. LTR: left edge x0; RTL: right edge x1. Non-bold fonts get a thin same-colour stroke."""
    d = ImageDraw.Draw(spr)
    gap = 7 * s
    lines = [(f, t, c) for f, t, c in zip(fonts, shaped, fills) if t]
    total = sum(f.getmetrics()[0] + f.getmetrics()[1] for f, _, _ in lines) + gap * (len(lines) - 1)
    y = ymid - total / 2.0
    for i, (f, t, c) in enumerate(lines):
        asc, desc = f.getmetrics()
        sw = 1 if (i == 0 and not bold and f.size >= 24) else 0
        d.text((x1 if rtl else x0, y + asc), t, font=f, fill=c + (255,), anchor="rs" if rtl else "ls", stroke_width=sw, stroke_fill=c + (255,))
        y += asc + desc + gap


# ---- public -----------------------------------------------------------------------------------------------------------------
def t4_tag_sprite(style, name, role="", icon="code", color="#19D3FF", font=None, scale=1.0, max_w=None):
    """RGBA sprite of a name tag, or None when name and role are both empty. Unknown style -> 'tag_a'. max_w = widest allowed PANEL (px):
    text shrinks, then is cut with '...'. sprite.info: panel (w, h in px), rtl. Never raises on odd text / colour / font values."""
    style = style if style in T4_TAG else "tag_a"
    sp = T4_TAG[style]
    name, role = str(name or "").strip(), str(role or "").strip()
    if not name and not role:
        return None
    if sp["caps"]:
        name, role = name.upper(), role.upper()
    s = max(0.2, float(scale))
    fp = font if font and os.path.isfile(str(font)) else default_font()
    col = t2_rgb(color)
    H, g = int(round(sp["h"] * s)), int(round(GLOW_PAD * s))
    left, right = int(round((sp["icon_w"] if icon else 34) * s)), int(round(sp["right"] * s))
    gapx = int(round(26 * s)) if icon else 0                              # divider -> text
    avail = (float(max_w) - left - gapx - right) if max_w else 10.0 ** 6
    fonts, shaped, tw = _fit([name, role], fp, (sp["name"] * s, sp["role"] * s), max(40.0, avail))
    w = int(max(sp["min_w"] * s, left + gapx + tw + right))
    if max_w:
        w = min(w, int(max_w))
    ext = int(round(14 * s)) if style == "tag_b" else 0
    spr = Image.new("RGBA", (w + 2 * g, H + ext + 2 * g), (0, 0, 0, 0))
    _panel(spr, style, w, H, g, col, s)
    _emblem(spr, icon, left, H, g, col, s)
    rtl = is_rtl_text(name + " " + role)
    role_col = t2_lighten(col, 0.15) if style == "tag_b" else (226, 234, 246)
    area0, area1 = g + left + gapx, g + w - right
    _texts(spr, fonts, shaped, area0, area1, g + H / 2.0, rtl, _is_bold(fp), [(255, 255, 255), role_col], s)
    spr.info["panel"], spr.info["rtl"] = (w, H), rtl
    return spr
