"""mt.templates.t4.nameplate - Template 4 modules 'nameplate' (name tag, styles tag_a = ref R2 / tag_b = ref R10) and 'corner_list'
(ref R10: laptop icon in one bottom corner + a 3-row icon list in the other). Both are timed + animated overlay ITEMS (one sprite each,
drawn above the frame plate) - not part of the static foreground plate.
cfg['t4']['nameplate'] = {on, style 'tag_a'|'tag_b', name, role, icon, color, anchor, inset_x, inset_y, start|trigger, end|hold, anim, anim_dur}
cfg['t4']['corner_list'] = {on, color, icon ('laptop' | kit icon | '' = none), icon_anchor, anchor, rows [{icon, text}], size, inset_x, inset_y,
                            start|trigger, end|hold, anim, anim_dur}
  anchor     top-left | top-right | bottom-left | bottom-right (default: tag_a bottom-left, tag_b top-left, list bottom-right, laptop bottom-left).
  inset_x/y  extra px (short side 1080) inward from the corner margin.
  timing     as t4/timing.t4_time: `trigger` (spoken phrase in the captions) or `start` (default 0); `end` or `hold` (tag default 5 s; list
             default = to the end of the video); trigger not found -> one warning, skipped.
  anim       'auto' (default: slides in from its own side) | none | any mt.anim name; anim_dur seconds (default 0.45).
Placement: the VISIBLE ink (alpha > 24, glow tails included) sits at least 48 px (short side 1080) from every canvas edge. Frame on (cfg['t4']['frame']):
the item is moved along the vertical (down from a top corner, up from a bottom one) just far enough that its ink keeps ~10 px away from every
solid frame pixel (brackets, hazard stripes, tab, icon) - measured against the real frame plate, so a frame redesign needs no change here.
Public: T4_NAMEPLATE, T4_CORNER_LIST, t4_nameplate_cfg(raw), t4_corner_list_cfg(raw), t4_nameplate_items(cfg, duration), t4_ask_nameplate(), t4_ask_corner_list()."""
import copy
import math
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

from mt.anim import ANIMS, PRESETS
from mt.ask import ask_anim
from mt.captions import caption_streams, parse_srt
from mt.common import ask, ask_choice, c_color, c_float, yn
from mt.draw import Item
from mt.fonts import default_font, t2_font
from mt.templates.t4.cfg import _hex
from mt.templates.t4.frame import t4_frame_cfg, t4_frame_plate
from mt.templates.t4.kit_icons import ICON_NAMES
from mt.templates.t4.nameplate_list import LIST_ICONS, T4_LIST, t4_laptop_sprite, t4_list_sprite
from mt.templates.t4.nameplate_tags import TAG_STYLES, t4_tag_sprite
from mt.templates.t4.timing import t4_ask_when, t4_time
from mt.templates.t4.warn import t4_warn

T4_SAFE = 48                                       # px at short side 1080: no ink closer than this to a canvas edge
INK_THR, FRAME_THR, GAP = 24, 60, 10               # sprite alpha = ink | frame alpha = solid | px kept between ink and frame
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
STYLE_ANCHOR = {"tag_a": "bottom-left", "tag_b": "top-left"}             # R2 / R10
DEFAULT_ROWS = [{"icon": "globe", "text": "Web Development"}, {"icon": "phone", "text": "Mobile Development"},
                {"icon": "gear", "text": "Tech Content Creator"}]
MAX_ROWS = 5
_COMMON = {"on": False, "color": "#19D3FF", "inset_x": 0.0, "inset_y": 0.0, "start": 0.0, "trigger": "", "end": None, "hold": None,
           "anim": "auto", "anim_dur": 0.45}
T4_NAMEPLATE = dict(_COMMON, style="tag_a", name="Ahmed Ibrahim", role="Full Stack Developer", icon="code", anchor="bottom-left")
T4_CORNER_LIST = dict(_COMMON, icon="laptop", icon_anchor="bottom-left", anchor="bottom-right", rows=DEFAULT_ROWS, size=22.0)
_OFF = ("", "none", "off", "false", "no", "0", "-")
_ALIAS = {"tl": "top-left", "tr": "top-right", "bl": "bottom-left", "br": "bottom-right", "left-top": "top-left",
          "right-top": "top-right", "left-bottom": "bottom-left", "right-bottom": "bottom-right"}


# ---- config -----------------------------------------------------------------------------------------------------------------
def _bool(v, default):
    if isinstance(v, str):
        return default if not v.strip() else v.strip().lower() not in _OFF
    return default if v is None else bool(v)


def _flt(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return default
    return x if not isinstance(v, bool) and lo <= x <= hi else default           # nan fails the comparison -> default


def _anchor(v, default):
    s = str(v).strip().lower().replace("_", "-").replace(" ", "-") if isinstance(v, (str, int)) and not isinstance(v, bool) else ""
    s = _ALIAS.get(PRESETS.get(s, s), PRESETS.get(s, s))
    return s if s in CORNERS else default


def _anim(v):
    s = v.strip().lower() if isinstance(v, str) else ""
    s = "reveal" if s == "typewriter" else s
    return s if s in ANIMS or s in ("none", "auto") else "auto"


def _icon(v, default):
    if v is False:
        return ""
    return ("" if v.strip().lower() in _OFF else v.strip().lower()) if isinstance(v, str) else default


def _common(raw, out, anchor):
    """Fields both modules share: on, colour, anchor, insets, timing (start / trigger / end / hold) and animation."""
    out["on"] = _bool(raw.get("on"), False)
    out["color"] = _hex(raw.get("color"), out["color"])
    out["anchor"] = _anchor(raw.get("anchor"), anchor)
    out["inset_x"], out["inset_y"] = _flt(raw.get("inset_x"), 0, 600, 0.0), _flt(raw.get("inset_y"), 0, 600, 0.0)
    trig = raw.get("trigger")
    out["trigger"] = trig.strip() if isinstance(trig, str) else ""
    out["start"] = raw["start"] if raw.get("start") is not None else (None if out["trigger"] else 0.0)    # a phrase never falls back to 0
    out["end"], out["hold"] = raw.get("end"), raw.get("hold")
    out["anim"] = _anim(raw.get("anim"))
    out["anim_dur"] = _flt(raw.get("anim_dur"), 0.0, 5.0, 0.45)


def _style(v):
    s = str(v).strip().lower().replace("-", "_") if isinstance(v, (str, int)) and not isinstance(v, bool) else ""
    return {"tag_b": "tag_b", "b": "tag_b", "2": "tag_b", "tagb": "tag_b"}.get(s, "tag_a")


def t4_nameplate_cfg(raw):
    """Normalise cfg['t4']['nameplate'] -> complete dict (extra keys such as 'font' survive). Never raises; junk -> defaults."""
    out = dict(T4_NAMEPLATE)
    if not isinstance(raw, dict):
        return out
    try:
        out.update({k: v for k, v in raw.items() if k not in out})
        out["style"] = _style(raw.get("style"))
        for k in ("name", "role"):
            v = raw.get(k)
            if isinstance(v, str):
                out[k] = "" if v.strip().lower() in ("-", "none") else v.strip()[:60]
        out["icon"] = _icon(raw.get("icon"), T4_NAMEPLATE["icon"])
        _common(raw, out, STYLE_ANCHOR[out["style"]])
    except Exception:
        return dict(T4_NAMEPLATE)
    return out


def _rows(v):
    """[{'icon', 'text'} | ('icon', 'text') | 'text' | 'icon|text'] -> clean rows (<= 5). Nothing usable -> the three R10 rows."""
    out = []
    for i, r in enumerate(v[:MAX_ROWS] if isinstance(v, (list, tuple)) else []):
        ic, tx = None, None
        if isinstance(r, dict):
            ic, tx = r.get("icon"), r.get("text")
        elif isinstance(r, (list, tuple)) and len(r) == 2:
            ic, tx = r
        elif isinstance(r, str):
            head, _, tail = r.partition("|")
            ic, tx = (head, tail) if tail and head.strip().lower() in ICON_NAMES else (None, r)
        tx = tx.strip()[:40] if isinstance(tx, str) else ""
        if tx:
            out.append({"icon": _icon(ic, LIST_ICONS[len(out) % len(LIST_ICONS)]), "text": tx})
    return out or copy.deepcopy(DEFAULT_ROWS)


def t4_corner_list_cfg(raw):
    """Normalise cfg['t4']['corner_list'] -> complete dict. Never raises; junk -> defaults (rows: the three R10 rows)."""
    out = copy.deepcopy(T4_CORNER_LIST)
    if not isinstance(raw, dict):
        return out
    try:
        out.update({k: copy.deepcopy(v) for k, v in raw.items() if k not in out})
        out["icon"] = _icon(raw.get("icon"), "laptop")
        out["icon_anchor"] = _anchor(raw.get("icon_anchor"), "bottom-left")
        out["rows"] = _rows(raw.get("rows"))
        out["size"] = _flt(raw.get("size"), 8, 120, 22.0)
        _common(raw, out, "bottom-right")
    except Exception:
        return copy.deepcopy(T4_CORNER_LIST)
    return out


# ---- placement --------------------------------------------------------------------------------------------------------------
_FM, _SPR = {}, {}


def _cached(cache, key, make, limit=12):
    if key not in cache:
        if len(cache) >= limit:
            cache.pop(next(iter(cache)))
        cache[key] = make()
    return cache[key]


def _frame_mask(W, H, fcfg, s):
    """Quarter-size 'L' mask of where the frame is solid, grown by GAP px (conservative). None when the frame is off."""
    if not fcfg["on"]:
        return None

    def make():
        a = t4_frame_plate(W, H, fcfg).getchannel("A").point(lambda v: 255 if v > FRAME_THR else 0)
        q = a.resize(((W + 3) // 4, (H + 3) // 4), Image.BOX).point(lambda v: 255 if v > 0 else 0)
        return q.filter(ImageFilter.MaxFilter(2 * int(math.ceil((GAP * s + 4) / 4.0)) + 1))
    return _cached(_FM, (W, H, round(s, 3), repr(sorted(fcfg.items()))), make, 4)


def _ink_box(spr):
    return spr.getchannel("A").point(lambda v: 255 if v > INK_THR else 0).getbbox()


def _pooled(spr, box):
    """Quarter-size ink mask of the sprite (cropped to its ink), grown by one cell so a placement that is not a multiple of 4 px stays safe."""
    a = spr.getchannel("A").crop(box).point(lambda v: 255 if v > INK_THR else 0)
    q = a.resize((max(1, (a.width + 3) // 4), max(1, (a.height + 3) // 4)), Image.BOX).point(lambda v: 255 if v > 0 else 0)
    padded = Image.new("L", (q.width + 2, q.height + 2), 0)             # 1 cell of room on every side, then grow by 1 cell
    padded.paste(q, (1, 1))
    return padded.filter(ImageFilter.MaxFilter(3))


def _hits(fm, q, x, y):
    qx, qy = int(x // 4), int(y // 4)
    return ImageChops.multiply(fm.crop((qx - 1, qy - 1, qx - 1 + q.width, qy - 1 + q.height)), q).getbbox() is not None


def _place(spr, anchor, W, H, s, inx, iny, fm, label):
    """Item centre for `spr` anchored at a corner -> (cx, cy, ink rect on the canvas, moved px) or None for an empty sprite.
    Ink at the 48 px safe margin (+ inset); with a frame mask: moved vertically (down from the top, up from the bottom) until clear."""
    box = _ink_box(spr)
    if box is None:
        return None
    w, h = box[2] - box[0], box[3] - box[1]
    m = T4_SAFE * s
    sx = 1 if anchor.endswith("left") else -1 if anchor.endswith("right") else 0          # inward direction; 0 = centred on that axis
    sy = 1 if anchor.startswith("top") else -1 if anchor.startswith("bottom") else 0     # (the 4 corners behave exactly as before)
    x = m + inx * s if sx > 0 else W - m - inx * s - w if sx < 0 else (W - w) / 2.0
    y = m + iny * s if sy > 0 else H - m - iny * s - h if sy < 0 else (H - h) / 2.0
    x, y = int(round(min(max(x, m), W - m - w))), int(round(min(max(y, m), H - m - h)))
    moved = 0
    if fm is not None:
        dx, dy = _clear_shift(fm, _pooled(spr, box), x, y, sx, sy, W, H, s)
        if dx is None:
            t4_warn("%s: no free place next to the frame in the %s corner - kept at the safe margin." % (label, anchor))
        else:
            x, y, moved = x + dx, y + dy, abs(dx) + abs(dy)
    return x - box[0] + spr.width / 2.0, y - box[1] + spr.height / 2.0, (x, y, x + w, y + h), moved


def _clear_shift(fm, q, x, y, sx, sy, W, H, s):
    """Smallest inward shift (dx toward the canvas centre horizontally first, then dy vertically) that leaves the sprite clear of the
    frame mask -> (dx, dy), or (None, None). Rails run the full side height, so a horizontal step is tried before a vertical one."""
    step = max(2, int(round(4 * s)))
    nx, ny = int(180 * s) // step, int(H * 0.45) // step
    for c in range(0, nx + ny + 1):                                     # total shift in steps: the cheapest clear place wins
        for i in range(max(0, c - ny), min(c, nx) + 1):                 # i steps inward horizontally, c - i vertically
            dx, dy = i * step, (c - i) * step
            xx, yy = x + sx * dx, y + sy * dy
            if xx < 0 or yy < 0 or xx + q.width * 4 > W + 8 or yy + q.height * 4 > H + 8:
                continue
            if not _hits(fm, q, xx, yy):
                return sx * dx, sy * dy
    return None, None


# ---- items ------------------------------------------------------------------------------------------------------------------
def _font(path):
    if path and os.path.isfile(str(path)):
        return str(path)
    if path:
        t4_warn("t4 nameplate: font '%s' not found - using the default bold font." % Path(str(path)).name)
    p = t2_font("arabic", "ع")[0]
    return p if p and os.path.isfile(p) else default_font()


def _cues(cfg):
    out = []
    for c in caption_streams(cfg):
        try:
            out.append(parse_srt(c["srt"]))
        except Exception:
            continue
    return out


def _window(cfg, entry, label, duration, default_hold):
    return t4_time(dict(entry, label=label), _cues(cfg) if entry.get("trigger") else None, duration, default_hold)


def _item(spr, win, anchor, c, W, H, s, fm, label, placed, duration):
    pos = _place(spr, anchor, W, H, s, c["inset_x"], c["inset_y"], fm, label)
    if pos is None:
        return None
    cx, cy, rect, _ = pos
    placed.append((label, rect))
    anim = c["anim"] if c["anim"] != "auto" else ("slide_right" if anchor.endswith("left") else "slide_left")
    persistent = win[1] >= float(duration) - 0.01                       # lasts to the end of the video -> no fade-out at the very end
    return Item(spr, win[0], win[1], cx, cy, anim, c["anim_dur"], out=not persistent, rtl=bool(spr.info.get("rtl")))


def _tag_items(cfg, c, duration, W, H, s, fm, placed):
    label = "name tag '%s'" % (c["name"] or c["role"])[:30]
    win = _window(cfg, c, label, duration, 5.0)
    if win is None:
        return []
    icon = c["icon"]
    if icon and icon not in ICON_NAMES:
        t4_warn("%s: icon '%s' unknown (use one of: %s) - no icon." % (label, icon, ", ".join(ICON_NAMES)))
        icon = ""
    # widest panel: canvas - safe margin - glow tails (~30 px) on both sides; frame on: +36 px each side so the tag can still clear the rails
    fp, max_w = _font(c.get("font")), W - 2 * (T4_SAFE + 30 + (36 if fm is not None else 0)) * s
    spr = _cached(_SPR, ("tag", c["style"], c["name"], c["role"], icon, c["color"], fp, W, H),
                  lambda: t4_tag_sprite(c["style"], c["name"], c["role"], icon, c["color"], fp, s, max_w))
    if spr is None:
        t4_warn("%s: name and role are both empty - skipped." % label)
        return []
    it = _item(spr, win, c["anchor"], c, W, H, s, fm, label, placed, duration)
    return [it] if it else []


def _list_items(cfg, c, duration, W, H, s, fm, placed):
    win = _window(cfg, c, "corner list", duration, None)
    if win is None:
        return []
    out, fp = [], _font(c.get("font"))
    if c["icon"]:
        lap = _cached(_SPR, ("lap", c["icon"], c["color"], W, H), lambda: t4_laptop_sprite(c["icon"], T4_LIST["laptop_w"], c["color"], s))
        out.append(_item(lap, win, c["icon_anchor"], c, W, H, s, fm, "corner list icon", placed, duration))
    key = ("list", repr(c["rows"]), c["size"], c["color"], fp, W, H)
    lst = _cached(_SPR, key, lambda: t4_list_sprite(c["rows"], c["size"], c["color"], fp, s, (W - 2 * T4_SAFE * s) * 0.6))
    out.append(_item(lst, win, c["anchor"], c, W, H, s, fm, "corner list", placed, duration))
    return [i for i in out if i]


def _warn_overlaps(placed):
    for i, (a, ra) in enumerate(placed):
        for b, rb in placed[i + 1:]:
            if ra[0] < rb[2] and rb[0] < ra[2] and ra[1] < rb[3] and rb[1] < ra[3]:
                t4_warn("%s and %s overlap - give one of them another corner (anchor) or an inset." % (a, b))


def t4_nameplate_items(cfg, duration):
    """Items of the name tag and the corner list (each one sprite, timed + animated); [] when both are off. Never raises."""
    t4 = cfg.get("t4") if isinstance(cfg, dict) and isinstance(cfg.get("t4"), dict) else {}
    tag, lst = t4_nameplate_cfg(t4.get("nameplate")), t4_corner_list_cfg(t4.get("corner_list"))
    if not (tag["on"] or lst["on"]):
        return []
    try:
        W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        t4_warn("t4 nameplate: the job has no canvas - skipped.")
        return []
    s = min(W, H) / 1080.0
    placed, items = [], []
    try:
        fm = _frame_mask(W, H, t4_frame_cfg(t4.get("frame")), s)
        if tag["on"]:
            items += _tag_items(cfg, tag, duration, W, H, s, fm, placed)
        if lst["on"]:
            items += _list_items(cfg, lst, duration, W, H, s, fm, placed)
        _warn_overlaps(placed)
    except Exception as e:
        t4_warn("t4 nameplate: could not be drawn (%s: %s) - skipped." % (type(e).__name__, e))
    return items


# ---- questions --------------------------------------------------------------------------------------------------------------
def _ask_corner(prompt, default, key, allow_none=False):
    """Corner question -> 'top-left' | ... (or '' for 'none' when allowed)."""
    labels = (["None (hide it)"] if allow_none else []) + ["Top-left", "Top-right", "Bottom-left", "Bottom-right"]
    n = ask_choice(prompt, labels, default=CORNERS.index(default) + 1 + (1 if allow_none else 0), key=key) - (1 if allow_none else 0)
    return CORNERS[n - 1] if n >= 1 else ""


def _ask_motion(prompt, corner, key, whole_video):
    """Timing + animation questions -> dict(start|trigger, hold?, anim, anim_dur). whole_video: offer 'keep it for the whole video' first."""
    if whole_video and yn("Keep the %s on screen for the whole video?" % prompt, default=True):
        out = {"start": 0.0}
    else:
        out = t4_ask_when(prompt.capitalize(), 5.0, key=key + "_when")
    out["anim"] = ask_anim("%s animation" % prompt.capitalize(), default="slide_right" if (corner or "left").endswith("left") else "slide_left",
                           key=key + "_anim")
    out["anim_dur"] = ask("Animation duration (seconds)", default=0.45, key=key + "_adur", cast=c_float)
    return out


def t4_ask_nameplate():
    """Question group 'nameplate' (called by t4_ask_config). -> the dict for cfg['t4']['nameplate']."""
    if not yn("Add a name tag (name + role - references R2 / R10)?", default=False):
        return {"on": False}
    st = ask_choice("Tag style:", ["tag_a - hexagon-cut glass panel, code icon | name + role, stripes in the corner (R2)",
                                   "tag_b - chamfered panel, capitals, bright bar + stripes on the bottom edge (R10)"],
                    default=1, key="t4_np_style")
    style = TAG_STYLES[st - 1]
    d = T4_NAMEPLATE
    clean = lambda s: "" if s.strip() in ("-", "none") else s.strip()
    name = ask("Name (Arabic works too)", default=d["name"], key="t4_np_name", cast=clean)
    role = ask("Role / subtitle ('-' = none)", default=d["role"], key="t4_np_role", cast=clean)
    ic = ask_choice("Icon in the tag:", ["None"] + list(ICON_NAMES), default=2, key="t4_np_icon")
    color = ask("Tag colour (hex or name)", default=d["color"], key="t4_np_color", cast=c_color)
    anchor = _ask_corner("Corner:", STYLE_ANCHOR[style], "t4_np_corner_" + style)
    out = {"on": True, "style": style, "name": name, "role": role, "icon": "" if ic == 1 else ICON_NAMES[ic - 2], "color": color, "anchor": anchor}
    out.update(_ask_motion("name tag", anchor, "t4_np", whole_video=False))
    return out


def t4_ask_corner_list():
    """Question group 'corner_list' (called by t4_ask_config). -> the dict for cfg['t4']['corner_list']."""
    if not yn("Add the corner list (laptop icon + service rows - reference R10)?", default=False):
        return {"on": False}
    d = T4_CORNER_LIST
    rows = []
    for i, r in enumerate(DEFAULT_ROWS, 1):
        v = ask("Row %d: text, or icon|text (icons: %s; '-' = no row)" % (i, ", ".join(ICON_NAMES)), default="%s|%s" % (r["icon"], r["text"]),
                key="t4_cl_row%d" % i, cast=lambda s: s.strip())
        if v and v != "-":
            rows.append(v)
    laptop = _ask_corner("Laptop icon corner:", d["icon_anchor"], "t4_cl_icon_corner", allow_none=True)
    anchor = _ask_corner("List corner:", d["anchor"], "t4_cl_corner")
    color = ask("Colour (hex or name)", default=d["color"], key="t4_cl_color", cast=c_color)
    out = {"on": True, "rows": rows, "icon": "laptop" if laptop else "", "icon_anchor": laptop or d["icon_anchor"], "anchor": anchor, "color": color}
    out.update(_ask_motion("corner list", anchor, "t4_cl", whole_video=True))
    return out
