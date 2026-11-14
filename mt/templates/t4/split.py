"""mt.templates.t4.split - Template 4 module 'split' (ref R7): diagonal split-screen takeover. The speaker video stays untouched underneath;
a media clip (video or image) shows through a diagonal polygon on one side, with a glowing neon seam on the diagonal and two HUD corner labels
('01 - TALKING HEAD' / '02 - LIVE DEVELOPMENT') with corner brackets. Entry wipe = the seam sweeps along its own normal from the media-side edge
to its place, exit wipe = the same path back.
cfg['t4']['split'] = {on (REQUIRED true in a job file), media 'path' (image or video; missing -> gray placeholder + one warning),
    angle 12 (lean of the seam in degrees, -35..35; + = '/' ), side 'auto'|'bottom'|'top'|'left'|'right' (auto = bottom on reels, right on YouTube),
    pos (seam position, fraction of the canvas along the split axis; default 0.5 top/bottom, 0.6 right, 0.4 left),
    labels [text | {text, color, anchor}, ...] (2 entries; '-' or '' hides one), color '#19d3ff', seam_width 3, wipe 0.55 s,
    seg_start / seg_end (video media: plays from seg_start; without seg_end it loops, otherwise plays once and holds the last frame),
    start | trigger, end | hold (default 6 s)}
Drawing split: the media picture is BAKED by split_video.py into an alpha clip (area 'box' = under the frame plate); the seam (one tiny Item per
frame while it moves) and the labels are ordinary Items. In --still the media is drawn as an Item (first frame).
Public: T4_SPLIT, t4_split_cfg(raw), t4_split_plan(cfg, duration, fps), t4_split_u(plan, t), t4_split_mask(plan, u), t4_split_cover(img, size),
t4_split_items(cfg, duration), t4_ask_split()."""
import copy
import math
import os
import re

from PIL import Image, ImageDraw, ImageOps

from mt.common import IMAGE_EXTS, VIDEO_EXTS, ask, ask_choice, c_color, c_existing_file, c_float, probe, yn
from mt.draw import Item, t2_lighten, t2_paint, t2_rgb, t2_text_mask
from mt.fonts import has_arabic, is_rtl_text
from mt.templates.t4.cfg import _hex
from mt.templates.t4.frame import t4_frame_cfg
from mt.templates.t4.kit import connector, glass_panel, kit_paste
from mt.templates.t4.nameplate import _anchor as _corner, _bool, _flt, _font, _frame_mask, _place, _window
from mt.templates.t4.timing import _num as _secs, t4_ask_when
from mt.templates.t4.warn import t4_warn

SIDES = ("top", "bottom", "left", "right")
POS_DEFAULT = {"top": 0.5, "bottom": 0.5, "left": 0.4, "right": 0.6}
DEFAULT_LABELS = ("01 \u2014 TALKING HEAD", "02 \u2014 LIVE DEVELOPMENT")
LABEL_ANCHORS = {"bottom": ("top-left", "bottom-left"), "top": ("bottom-left", "top-left"),      # (speaker label, media label)
                 "right": ("top-left", "top-right"), "left": ("top-right", "top-left")}
TINT = (5, 12, 30, 214)
T4_SPLIT = {"on": False, "media": "", "angle": 12.0, "side": "auto", "pos": None, "labels": [], "color": "#19d3ff", "seam_width": 3.0,
            "wipe": 0.55, "seg_start": None, "seg_end": None, "start": 0.0, "trigger": "", "end": None, "hold": None}
_NUMRE = re.compile(r"^\s*(\d{1,3})\s*[\u2014\u2013\-]+\s*(.+?)\s*$")


# ---- config -----------------------------------------------------------------------------------------------------------------
def _labels(raw):
    """-> exactly 2 dicts {text, color, anchor}; missing -> the R7 texts; '-' / '' / 'none' -> text '' (hidden)."""
    src = raw if isinstance(raw, (list, tuple)) else []
    out = []
    for i in range(2):
        r = src[i] if i < len(src) else None
        d = r if isinstance(r, dict) else {"text": r}
        t = d.get("text")
        t = DEFAULT_LABELS[i] if (t is None or isinstance(t, bool)) else str(t).strip()[:60]
        if t.lower() in ("-", "none"):
            t = ""
        c = d.get("color")
        out.append({"text": t, "color": _hex(c, "") if isinstance(c, str) else "", "anchor": _corner(d.get("anchor"), "")})
    return out


def t4_split_cfg(raw):
    """Normalise cfg['t4']['split'] -> complete dict (extras survive). Never raises; junk -> defaults (on False)."""
    out = copy.deepcopy(T4_SPLIT)
    out["labels"] = _labels(None)
    if not isinstance(raw, dict):
        return out
    try:
        out.update({k: copy.deepcopy(v) for k, v in raw.items() if k not in out})
        m = raw.get("media")
        out["media"] = m.strip() if isinstance(m, str) else ""
        out["on"] = _bool(raw.get("on"), bool(out["media"]))
        out["angle"] = _flt(raw.get("angle"), -35.0, 35.0, 12.0)
        sd = raw.get("side")
        sd = sd.strip().lower() if isinstance(sd, str) else ""
        out["side"] = sd if sd in SIDES else "auto"
        out["pos"] = _flt(raw.get("pos"), 0.15, 0.85, None)
        out["labels"] = _labels(raw.get("labels"))
        out["color"] = _hex(raw.get("color"), "#19d3ff")
        out["seam_width"] = _flt(raw.get("seam_width"), 0.5, 20.0, 3.0)
        out["wipe"] = _flt(raw.get("wipe"), 0.1, 3.0, 0.55)
        out["seg_start"], out["seg_end"] = _secs(raw.get("seg_start")), _secs(raw.get("seg_end"))
        trig = raw.get("trigger")
        out["trigger"] = trig.strip() if isinstance(trig, str) else ""
        out["start"] = raw["start"] if raw.get("start") is not None else (None if out["trigger"] else 0.0)
        out["end"], out["hold"] = raw.get("end"), raw.get("hold")
    except Exception:
        d = copy.deepcopy(T4_SPLIT)
        d["labels"] = _labels(None)
        return d
    return out


# ---- geometry ---------------------------------------------------------------------------------------------------------------
def _clip(poly, P, n, off):
    """Sutherland-Hodgman: keep the part of `poly` where (p - P) . n >= off."""
    out = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        da = (a[0] - P[0]) * n[0] + (a[1] - P[1]) * n[1] - off
        db = (b[0] - P[0]) * n[0] + (b[1] - P[1]) * n[1] - off
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            t = da / (da - db)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _geometry(W, H, side, angle, pos):
    """Seam line through P with direction d (+ angle = '/'), n = unit normal pointing to the media side, final media polygon, projections."""
    a = math.radians(angle)
    horiz = side in ("top", "bottom")
    d = (math.cos(a), -math.sin(a)) if horiz else (math.sin(a), -math.cos(a))
    n = (-d[1], d[0])
    want = {"bottom": (0, 1), "top": (0, -1), "right": (1, 0), "left": (-1, 0)}[side]
    if n[0] * want[0] + n[1] * want[1] < 0:
        n = (-n[0], -n[1])
    P = (W / 2.0, H * pos) if horiz else (W * pos, H / 2.0)
    rect = [(0.0, 0.0), (float(W), 0.0), (float(W), float(H)), (0.0, float(H))]
    pn = [(x - P[0]) * n[0] + (y - P[1]) * n[1] for x, y in rect]
    pd = [(x - P[0]) * d[0] + (y - P[1]) * d[1] for x, y in rect]
    return {"P": P, "d": d, "n": n, "rect": rect, "poly": _clip(rect, P, n, 0.0), "tmin": min(pd), "tmax": max(pd), "dtot": max(pn) + 2.0}


def _patch(poly, W, H):
    """Even-sized canvas rect (x, y, w, h) that covers the final media polygon, or None for a degenerate polygon."""
    if len(poly) < 3:
        return None
    x0, y0 = max(0, int(math.floor(min(p[0] for p in poly)))), max(0, int(math.floor(min(p[1] for p in poly))))
    x1, y1 = min(W, int(math.ceil(max(p[0] for p in poly)))), min(H, int(math.ceil(max(p[1] for p in poly))))
    if (x1 - x0) % 2:
        x1, x0 = (x1 + 1, x0) if x1 < W else (x1, x0 - 1) if x0 > 0 else (x1 - 1, x0)
    if (y1 - y0) % 2:
        y1, y0 = (y1 + 1, y0) if y1 < H else (y1, y0 - 1) if y0 > 0 else (y1 - 1, y0)
    return (x0, y0, x1 - x0, y1 - y0) if x1 - x0 >= 2 and y1 - y0 >= 2 else None


def _fps(cfg):
    try:
        v = cfg.get("video")
        if v and os.path.isfile(str(v)):
            f = float(probe(str(v))["fps"])
            if f > 0:
                return f
    except (Exception, SystemExit):
        pass
    return 30.0


def _placeholder():
    return Image.new("RGB", (640, 480), (112, 116, 124))


def _media(c):
    """-> {kind 'video'|'image', path, img (images)}; missing / unreadable -> gray placeholder image + one warning."""
    p = c["media"]
    name = os.path.basename(p) or "(none)"
    if p and os.path.isfile(p):
        if p.lower().endswith(VIDEO_EXTS):
            return {"kind": "video", "path": p}
        try:
            with Image.open(p) as im:
                im.seek(0)
                return {"kind": "image", "path": p, "img": im.convert("RGB")}
        except Exception:
            t4_warn("split: '%s' is not a readable image - gray placeholder." % name)
    else:
        t4_warn("split: media '%s' is missing - gray placeholder." % name)
    return {"kind": "image", "path": p, "img": _placeholder()}


def t4_split_plan(cfg, duration, fps=None):
    """Everything the Items and the baked clip share: window snapped to the frame grid (j0 / j1 frames, t0 / t1 s), wipe time, geometry, patch rect,
    media. None when the module is off / has no canvas / its window is empty. Never raises for user data."""
    t4 = cfg.get("t4") if isinstance(cfg, dict) and isinstance(cfg.get("t4"), dict) else {}
    c = t4_split_cfg(t4.get("split"))
    if not c["on"]:
        return None
    try:
        W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        t4_warn("t4 split: the job has no canvas - skipped.")
        return None
    win = _window(cfg, c, "split screen", duration, 6.0)
    if win is None:
        return None
    fps = float(fps) if fps else _fps(cfg)
    j0, j1 = int(round(win[0] * fps)), int(round(win[1] * fps))
    if j1 - j0 < 2:
        return None
    side = c["side"] if c["side"] in SIDES else ("bottom" if H > W else "right")
    g = _geometry(W, H, side, c["angle"], c["pos"] if c["pos"] is not None else POS_DEFAULT[side])
    patch = _patch(g["poly"], W, H)
    if patch is None:
        t4_warn("t4 split: the seam leaves no room for the media - skipped.")
        return None
    wipe = max(2.0 / fps, min(c["wipe"], (j1 - j0) / fps / 2.5))
    return dict(g, c=c, W=W, H=H, s=min(W, H) / 1080.0, fps=fps, j0=j0, j1=j1, t0=j0 / fps, t1=j1 / fps, wipe=wipe, side=side, patch=patch,
                media=_media(c))


def t4_split_u(plan, t):
    """Wipe progress 0 (nothing shown) .. 1 (fully shown) at time t: eased entry over `wipe`, hold, the same path back at the end."""
    w = plan["wipe"]
    p = max(0.0, min(1.0, (t - plan["t0"]) / w, (plan["t1"] - t) / w))
    return 1.0 - (1.0 - p) ** 3


def t4_split_mask(plan, u):
    """'L' mask (patch size, anti-aliased) of the media region at progress u, or None when nothing is visible."""
    x0, y0, w, h = plan["patch"]
    off = 0.0 if u >= 1.0 - 1e-6 else (1.0 - u) * plan["dtot"]
    poly = _clip(plan["rect"], plan["P"], plan["n"], off)
    if len(poly) < 3:
        return None
    k = 2
    m = Image.new("L", (w * k, h * k), 0)
    ImageDraw.Draw(m).polygon([((x - x0) * k, (y - y0) * k) for x, y in poly], fill=255)
    return m.resize((w, h), Image.BOX)


def t4_split_cover(img, size):
    """Picture cover-fitted (cropped, never stretched) to size = (w, h), RGB."""
    return ImageOps.fit(img.convert("RGB"), (int(size[0]), int(size[1])), Image.LANCZOS, centering=(0.5, 0.5))


# ---- seam -------------------------------------------------------------------------------------------------------------------
def _seam_sprite(plan):
    P, d, s, c = plan["P"], plan["d"], plan["s"], plan["c"]
    a = (P[0] + d[0] * (plan["tmin"] - 60), P[1] + d[1] * (plan["tmin"] - 60))
    b = (P[0] + d[0] * (plan["tmax"] + 60), P[1] + d[1] * (plan["tmax"] + 60))
    sp = connector([a, b], c["color"], False, c["seam_width"] * s, 14 * s)
    sp.info["split"] = "seam"
    return sp


def _seam_items(plan, still):
    """The seam sprite is displaced along the normal while it wipes: one Item per frame (frame-exact, same u as the baked clip), one long Item for the hold."""
    sp = _seam_sprite(plan)
    fps, half, items = plan["fps"], 0.5 / plan["fps"], []

    def mk(a, b, off):
        ox, oy = sp.info["origin"]
        return Item(sp, a, b, -ox + sp.width / 2.0 + plan["n"][0] * off, -oy + sp.height / 2.0 + plan["n"][1] * off, "none", 0.0, out=False)
    if still:
        return [mk(plan["t0"], plan["t1"], 0.0)]
    run = None
    for j in range(plan["j0"], plan["j1"]):
        u = t4_split_u(plan, j / fps)
        if u >= 1.0 - 1e-6:
            run = j if run is None else run
            continue
        if run is not None:
            items.append(mk(run / fps - half, j / fps - half, 0.0))
            run = None
        if u > 1e-6:
            items.append(mk(j / fps - half, j / fps + half, (1.0 - u) * plan["dtot"]))
    if run is not None:
        items.append(mk(run / fps - half, plan["j1"] / fps - half, 0.0))
    return items


# ---- labels -----------------------------------------------------------------------------------------------------------------
def _label_sprite(text, color, font, s, max_w):
    """HUD tag: dark glass panel (chamfered corners, neon border) = number | divider | text, plus L-shaped corner brackets at two opposite corners."""
    m = _NUMRE.match(text)
    num, rest = (m.group(1), m.group(2)) if m else ("", text.strip())
    if not has_arabic(rest):
        rest = rest.upper()
    if not num and not rest:
        return None
    col, rtl, size = t2_rgb(color), is_rtl_text(rest), 30.0 * s
    for _ in range(14):
        nm = t2_text_mask(num, font, size * 1.2, 0.04) if num else None
        rm = t2_text_mask(rest, font, size, 0.10) if rest else None
        gap, padx = size * 0.8, size * 0.9
        total = 2 * padx + (nm.width if nm else 0) + (rm.width if rm else 0) + (2 * gap + 2 if (nm and rm) else 0)
        if total <= max_w or size <= 12 * s:
            break
        size *= 0.9
    ph, g, pw = int(size * 2.3), int(36 * s), int(total)
    cut = ph * 0.28
    base = Image.new("RGBA", (pw + 2 * g, ph + 2 * g), (0, 0, 0, 0))
    kit_paste(base, glass_panel((pw, ph), 0, TINT, col, (cut, 0, cut, 0), max(2.0, 2 * s), 10 * s), g, g)
    b, arm = 9 * s, 24 * s
    for pts in ([(g - b, g - b + arm), (g - b, g - b), (g - b + arm, g - b)],
                [(g + pw + b, g + ph + b - arm), (g + pw + b, g + ph + b), (g + pw + b - arm, g + ph + b)]):
        kit_paste(base, connector(pts, col, False, 3 * s, 8 * s), 0, 0)
    parts = [("n", nm)] if nm else []
    parts += [("d", None)] if (nm and rm) else []
    parts += [("t", rm)] if rm else []
    x = g + padx
    for kind, mk in (parts[::-1] if rtl else parts):
        if kind == "d":
            x += gap
            kit_paste(base, connector([(x, g + ph * 0.25), (x, g + ph * 0.75)], t2_lighten(col, 0.15), False, 1.8 * s, 5 * s), 0, 0)
            x += 2 + gap
            continue
        t2_paint(base, (mk, (int(round(x)), int(round(g + ph / 2.0 - mk.height / 2.0)))), col if kind == "n" else (255, 255, 255))
        x += mk.width
    base.info["split"] = "label"
    return base


def _label_items(cfg, plan, t4):
    c, W, H, s = plan["c"], plan["W"], plan["H"], plan["s"]
    fm = _frame_mask(W, H, t4_frame_cfg(t4.get("frame")), s)
    font, items = _font(c.get("font")), []
    for i, lab in enumerate(c["labels"]):
        if not lab["text"]:
            continue
        spr = _label_sprite(lab["text"], lab["color"] or c["color"], font, s, W * 0.6)
        pl = _place(spr, lab["anchor"] or LABEL_ANCHORS[plan["side"]][i], W, H, s, 0, 0, fm, "split label %d" % (i + 1)) if spr is not None else None
        if pl is None:
            continue
        st = plan["t0"] if i == 0 else plan["t0"] + plan["wipe"] * 0.8
        items.append(Item(spr, min(st, plan["t1"] - 0.1), plan["t1"], pl[0], pl[1], "fade", 0.35, out=True))
    return items


# ---- items ------------------------------------------------------------------------------------------------------------------
def _still_region(plan):
    """--still only: the media picture (first frame for a video) cut by the final polygon, as one static Item. A real render bakes it instead."""
    from mt.render import _first_frame
    x0, y0, w, h = plan["patch"]
    m = plan["media"]
    img = _first_frame(m["path"]) if m["kind"] == "video" else m["img"]
    mask = t4_split_mask(plan, 1.0)
    if img is None or mask is None:
        return []
    rgba = t4_split_cover(img, (w, h)).convert("RGBA")
    rgba.putalpha(mask)
    rgba.info["split"] = "region"
    return [Item(rgba, plan["t0"], plan["t1"], x0 + w / 2.0, y0 + h / 2.0, "none", 0.0, out=False)]


def t4_split_items(cfg, duration):
    """Items of the split module: [region (--still only)] + seam + labels. [] when off. Never raises."""
    try:
        plan = t4_split_plan(cfg, duration)
        if plan is None:
            return []
        t4 = cfg.get("t4") if isinstance(cfg.get("t4"), dict) else {}
        still = bool(cfg.get("_t2_still"))
        return (_still_region(plan) if still else []) + _seam_items(plan, still) + _label_items(cfg, plan, t4)
    except Exception as e:
        t4_warn("t4 split: could not be drawn (%s: %s) - skipped." % (type(e).__name__, e))
        return []


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_ask_split(gate=True):
    """Question group 'split' (called by t4_ask_config). -> the dict for cfg['t4']['split'] or {'on': False}."""
    if gate and not yn("Add a diagonal split-screen (a clip / image wipes in on one side, neon seam + two HUD labels - reference R7)?", default=False):
        return {"on": False}
    media = ask("Split media (image or video path)", key="t4_split_media", cast=c_existing_file(IMAGE_EXTS + VIDEO_EXTS))
    l1 = ask("Label 1, the speaker side ('-' = none)", default=DEFAULT_LABELS[0], key="t4_split_l1", cast=lambda v: v.strip())
    l2 = ask("Label 2, the media side ('-' = none)", default=DEFAULT_LABELS[1], key="t4_split_l2", cast=lambda v: v.strip())
    sd = ask_choice("Media side:", ["Auto (bottom on reels, right on YouTube)", "Bottom", "Top", "Right", "Left"], default=1, key="t4_split_side")
    angle = ask("Seam lean in degrees (0 = straight, negative = the other way)", default=12, key="t4_split_angle", cast=c_float)
    color = ask("Seam colour", default="#19D3FF", key="t4_split_color", cast=c_color)
    out = {"on": True, "media": media, "labels": [l1, l2], "side": ("auto", "bottom", "top", "right", "left")[sd - 1], "angle": angle, "color": color}
    out.update(t4_ask_when("Split screen", 6.0, key="t4_split_when"))
    return out