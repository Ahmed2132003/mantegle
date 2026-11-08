"""mt.templates.t4.cfg - Template 4 "Overlay Studio": config defaults + normaliser (cfg["t4"]).
The user's video is the BASE and fills the canvas; every module below is an overlay layer (placeholders until their P-task)."""
import copy
import re

CANVAS_REELS = [1080, 1920]
CANVAS_YOUTUBE = [1920, 1080]
T4_MODULES = ("frame", "nameplate", "corner_list", "tags", "tiles", "cards", "scenes", "split", "broll")
T4_DEFAULTS = {
    "canvas_mode": "auto",                                   # 'auto' (by the video aspect) | 'reels' | 'youtube'
    "fit": "fill",                                           # 'fill' (crop to the canvas) | 'fit' (whole video, letterboxed)
    "backdrop": {"type": "color", "value": "#000000", "path": "", "strength": 5},   # type color|image|blur; only visible when fit leaves bars
    **{m: {"on": False} for m in T4_MODULES},
}
_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def t4_canvas(mode, video_info=None):
    """-> [1080, 1920] (reels) or [1920, 1080] (youtube). 'auto' = by the video aspect (wider than tall -> youtube; no info -> reels)."""
    m = str(mode or "auto").strip().lower()
    if m == "youtube":
        return list(CANVAS_YOUTUBE)
    if m == "reels":
        return list(CANVAS_REELS)
    try:
        return list(CANVAS_YOUTUBE) if float(video_info["w"]) > float(video_info["h"]) else list(CANVAS_REELS)
    except (TypeError, KeyError, ValueError):
        return list(CANVAS_REELS)


def _hex(v, default):
    m = _HEX.match(str(v).strip()) if isinstance(v, str) else None
    if not m:
        return default
    h = m.group(1)
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    return "#" + h.lower()


def _choice(v, allowed, default):
    v = str(v).strip().lower() if isinstance(v, str) else ""
    return v if v in allowed else default


def t4_cfg(raw):
    """Normalise cfg["t4"]: always returns a complete dict, never raises (junk values fall back to the defaults).
    Module dicts keep their extra keys (later P-tasks own them); only `on` is coerced to bool."""
    out = copy.deepcopy(T4_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    try:
        out["canvas_mode"] = _choice(raw.get("canvas_mode"), ("auto", "reels", "youtube"), out["canvas_mode"])
        out["fit"] = _choice(raw.get("fit"), ("fill", "fit"), out["fit"])
        bd = raw.get("backdrop")
        if isinstance(bd, dict):
            b = out["backdrop"]
            b["type"] = _choice(bd.get("type"), ("color", "image", "blur"), b["type"])
            b["value"] = _hex(bd.get("value"), b["value"])
            b["path"] = bd["path"].strip() if isinstance(bd.get("path"), str) else ""
            try:
                b["strength"] = max(1, min(10, int(bd.get("strength", b["strength"]))))
            except (TypeError, ValueError, OverflowError):
                pass
        for m in T4_MODULES:
            src = raw.get(m)
            if isinstance(src, dict):
                d = copy.deepcopy(src)
                d["on"] = bool(src.get("on", False))
                out[m] = d
        for k, v in raw.items():                         # unknown keys survive (forward compatibility with newer jobs)
            if k not in out:
                out[k] = copy.deepcopy(v)
    except Exception:
        return copy.deepcopy(T4_DEFAULTS)
    return out
