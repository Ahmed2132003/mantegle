"""mt.templates.t4.broll - Template 4 module 'broll' (ref R4): a FULL-CANVAS takeover of a video / image segment. The speaker video and its audio
keep running underneath (the clip is muted and baked as a video layer, see broll_video.py); a HUD decoration plate (broll_decor.py) sits on top.
cfg['t4']['broll'] = {on (REQUIRED true in a job file), media 'path' (video or image; missing -> gray placeholder + one warning),
    start | trigger, end | hold (default 5 s), decor True|False, anim 'fade' (cross-fade, default) | 'wipe' (diagonal wipe in / out) | 'none' (cut),
    anim_dur 0.5, angle 20 (travel direction of the wipe, degrees), seg_start / seg_end (video: plays from seg_start; without seg_end it loops,
    otherwise it plays once and holds the last frame), color '#19d3ff' (decor neon), stripe_color '#ffc21a' (hazard stripes)}
Layer: area 'box' (= whole canvas in T4) -> UNDER the frame plate, above the speaker. Decor = ONE sprite Item (cached plate). --still: the media is drawn
as an Item (first frame) instead of a baked layer.
Public: T4_BROLL, t4_broll_cfg(raw), t4_broll_plan(cfg, duration, fps), t4_broll_mask(plan, t), t4_broll_items(cfg, duration), t4_ask_broll()."""
import copy
import math

from PIL import Image, ImageDraw

from mt.common import IMAGE_EXTS, VIDEO_EXTS, ask, ask_choice, c_existing_file, c_float, c_time, yn
from mt.draw import Item
from mt.templates.t4.base import _image_ok
from mt.templates.t4.broll_decor import t4_broll_decor
from mt.templates.t4.cfg import _hex
from mt.templates.t4.nameplate import _bool, _flt, _window
from mt.templates.t4.split import _clip, _fps, t4_split_cover
from mt.templates.t4.timing import _num as _secs, t4_ask_when
from mt.templates.t4.warn import t4_warn

T4_BROLL = {"on": False, "media": "", "start": 0.0, "trigger": "", "end": None, "hold": None, "decor": True, "anim": "fade", "anim_dur": 0.5,
            "angle": 20.0, "seg_start": None, "seg_end": None, "color": "#19d3ff", "stripe_color": "#ffc21a"}
_ANIM = {"fade": "fade", "crossfade": "fade", "cross-fade": "fade", "wipe": "wipe", "diagonal": "wipe", "diagonal_wipe": "wipe",
         "none": "none", "cut": "none"}


# ---- config -----------------------------------------------------------------------------------------------------------------
def t4_broll_cfg(raw):
    """Normalise cfg['t4']['broll'] -> complete dict (extras survive). Never raises; junk -> defaults (on False)."""
    out = copy.deepcopy(T4_BROLL)
    if not isinstance(raw, dict):
        return out
    try:
        out.update({k: copy.deepcopy(v) for k, v in raw.items() if k not in out})
        m = raw.get("media")
        out["media"] = m.strip() if isinstance(m, str) else ""
        out["on"] = _bool(raw.get("on"), bool(out["media"]))
        out["decor"] = _bool(raw.get("decor"), True)
        a = raw.get("anim")
        out["anim"] = _ANIM.get(a.strip().lower() if isinstance(a, str) else "", "fade")
        out["anim_dur"] = _flt(raw.get("anim_dur"), 0.05, 3.0, 0.5)
        out["angle"] = _flt(raw.get("angle"), -60.0, 60.0, 20.0)
        out["seg_start"], out["seg_end"] = _secs(raw.get("seg_start")), _secs(raw.get("seg_end"))
        if out["seg_start"] is not None and out["seg_start"] < 0:
            out["seg_start"] = 0.0
        if out["seg_end"] is not None and out["seg_end"] <= (out["seg_start"] or 0.0) + 0.05:
            out["seg_end"] = None
        out["color"] = _hex(raw.get("color"), "#19d3ff")
        out["stripe_color"] = _hex(raw.get("stripe_color"), "#ffc21a")
        trig = raw.get("trigger")
        out["trigger"] = trig.strip() if isinstance(trig, str) else ""
        out["start"] = raw["start"] if raw.get("start") is not None else (None if out["trigger"] else 0.0)
        out["end"], out["hold"] = raw.get("end"), raw.get("hold")
    except Exception:
        return copy.deepcopy(T4_BROLL)
    return out


# ---- plan (shared by the Items and the baked clip) --------------------------------------------------------------------------
def _media(c):
    """-> {kind 'video' | 'image' | 'gray', path}. Missing / unreadable -> gray placeholder + one warning."""
    p = c["media"]
    name = p.replace("\\", "/").split("/")[-1] or "(none)"
    if p and __import__("os").path.isfile(p):
        if p.lower().endswith(VIDEO_EXTS):
            return {"kind": "video", "path": p}
        if _image_ok(p):
            return {"kind": "image", "path": p}
        t4_warn("b-roll: '%s' is not a readable image - gray placeholder." % name)
    else:
        t4_warn("b-roll: media '%s' is missing - gray placeholder." % name)
    return {"kind": "gray", "path": ""}


def t4_broll_plan(cfg, duration, fps=None):
    """Window snapped to the frame grid + wipe geometry + media. None when the module is off / has no canvas / its window is empty."""
    t4 = cfg.get("t4") if isinstance(cfg, dict) and isinstance(cfg.get("t4"), dict) else {}
    c = t4_broll_cfg(t4.get("broll"))
    if not c["on"]:
        return None
    try:
        W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        t4_warn("t4 b-roll: the job has no canvas - skipped.")
        return None
    win = _window(cfg, c, "b-roll", duration, 5.0)
    if win is None:
        return None
    fps = float(fps) if fps else _fps(cfg)
    j0, j1 = int(round(win[0] * fps)), int(round(win[1] * fps))
    if j1 - j0 < 2:
        return None
    d = 0.0 if c["anim"] == "none" else max(2.0 / fps, min(c["anim_dur"], (j1 - j0) / fps / 2.5))
    a = math.radians(c["angle"])
    n = (math.cos(a), math.sin(a))
    pr = [x * n[0] + y * n[1] for x, y in ((0, 0), (W, 0), (W, H), (0, H))]
    return {"c": c, "W": W, "H": H, "s": min(W, H) / 1080.0, "fps": fps, "j0": j0, "j1": j1, "t0": j0 / fps, "t1": j1 / fps, "d": d,
            "anim": c["anim"], "media": _media(c), "n": n, "pmin": min(pr), "pmax": max(pr)}


def t4_broll_mask(plan, t):
    """Wipe state at time t -> 'full' | 'empty' | 'L' mask (W x H). Entry: the seam sweeps along n and reveals the media; exit: the same seam keeps
    going in the same direction and removes it. fade / none -> always 'full' (the layer's own fade does the work)."""
    if plan["anim"] != "wipe" or plan["d"] <= 0:
        return "full"
    W, H, d, n = plan["W"], plan["H"], plan["d"], plan["n"]
    e = lambda p: 1.0 - (1.0 - p) ** 3
    pin = max(0.0, min(1.0, (t - plan["t0"]) / d))
    pout = max(0.0, min(1.0, (t - (plan["t1"] - d)) / d))
    span = plan["pmax"] - plan["pmin"]
    rect = [(0.0, 0.0), (float(W), 0.0), (float(W), float(H)), (0.0, float(H))]
    if pout > 0.0:
        poly = _clip(rect, (0.0, 0.0), n, plan["pmin"] + e(pout) * span)            # keep p.n >= th
    elif pin >= 1.0:
        return "full"
    else:
        poly = _clip(rect, (0.0, 0.0), (-n[0], -n[1]), -(plan["pmin"] + e(pin) * span))   # keep p.n <= th
    if len(poly) < 3:
        return "empty"
    k = 2
    m = Image.new("L", (W * k, H * k), 0)
    ImageDraw.Draw(m).polygon([(x * k, y * k) for x, y in poly], fill=255)
    return m.resize((W, H), Image.BOX)


# ---- items ------------------------------------------------------------------------------------------------------------------
def _still_media(plan):
    """--still only: the media picture (first frame of a video) cover-fitted to the canvas, as one static Item."""
    from mt.render import _first_frame
    m, W, H = plan["media"], plan["W"], plan["H"]
    img = None
    if m["kind"] == "video":
        img = _first_frame(m["path"])
    elif m["kind"] == "image":
        try:
            with Image.open(m["path"]) as im:
                im.seek(0)
                img = im.convert("RGB")
        except Exception:
            img = None
    if img is None:
        img = Image.new("RGB", (640, 480), (112, 116, 124))
    spr = t4_split_cover(img, (W, H)).convert("RGBA")
    return [Item(spr, plan["t0"], plan["t1"], W / 2.0, H / 2.0, "none", 0.0, out=False)]


def t4_broll_items(cfg, duration):
    """[media (--still only)] + [decor plate with fade in / out]. [] when off. Never raises."""
    try:
        plan = t4_broll_plan(cfg, duration)
        if plan is None:
            return []
        c, W, H = plan["c"], plan["W"], plan["H"]
        still = bool(cfg.get("_t2_still"))
        items = _still_media(plan) if still else []
        if c["decor"]:
            spr = t4_broll_decor(W, H, c["color"], c["stripe_color"])
            anim = "none" if (still or plan["anim"] == "none") else "fade"
            items.append(Item(spr, plan["t0"], plan["t1"], W / 2.0, H / 2.0, anim, plan["d"], out=True))
        return items
    except Exception as e:
        t4_warn("t4 b-roll: could not be drawn (%s: %s) - skipped." % (type(e).__name__, e))
        return []


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_ask_broll(gate=True):
    """Question group 'broll' (called by t4_ask_config). -> dict for cfg['t4']['broll'] or {'on': False}."""
    if gate and not yn("Add a b-roll takeover (full-canvas clip / image over the speaker, speaker audio continues, HUD decoration - reference R4)?", default=False):
        return {"on": False}
    media = ask("B-roll media (video or image path)", key="t4_broll_media", cast=c_existing_file(IMAGE_EXTS + VIDEO_EXTS))
    out = {"on": True, "media": media}
    if media.lower().endswith(VIDEO_EXTS):
        for k, q in (("seg_start", "Clip start (seconds or mm:ss; Enter = 0)"), ("seg_end", "Clip end (seconds or mm:ss; Enter = loop the clip)")):
            v = ask(q, allow_empty=True, cast=c_time)
            if v not in (None, ""):
                out[k] = v
    out["decor"] = yn("HUD decoration on top (neon streaks, grid, code icon, dot matrix, hazard stripes)?", default=True)
    a = ask_choice("Transition in / out:", ["Cross-fade", "Diagonal wipe", "Cut (none)"], default=1, key="t4_broll_anim")
    out["anim"] = ("fade", "wipe", "none")[a - 1]
    if a != 3:
        out["anim_dur"] = ask("Transition duration (seconds)", default=0.5, key="t4_broll_adur", cast=c_float)
    out.update(t4_ask_when("B-roll", 5.0, key="t4_broll_when"))
    return out