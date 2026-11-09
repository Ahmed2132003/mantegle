"""mt.templates.t4 - Template 4 "Overlay Studio" (registry id 5): hooks. Config namespace cfg["t4"] (see cfg.py).
T4-0: only the plain video on a solid backdrop; the design modules (frame, nameplate, tiles, ...) arrive in later tasks."""
import os
import tempfile

from mt.templates.t4.captions import t4_caption_items, t4_caption_style  # noqa: F401  (t4_caption_style = registry hook)
from mt.common import D, IMAGE_EXTS, ask, ask_choice, c_color, c_existing_file, c_int, probe
from mt.templates.t4.base import t4_apply_backdrop
from mt.templates.t4.frame import t4_ask_frame, t4_frame_cfg, t4_frame_part
from mt.templates.t4.nameplate import t4_ask_corner_list, t4_ask_nameplate, t4_corner_list_cfg, t4_nameplate_cfg, t4_nameplate_items
from mt.templates.t4.tiles import t4_ask_tiles, t4_tiles_cfg, t4_tiles_items
from mt.templates.t4.warn import t4_warn, t4_warn_reset
from mt.templates.t4.cfg import CANVAS_REELS, T4_DEFAULTS, T4_MODULES, t4_canvas, t4_cfg  # noqa: F401


def _full_box(canvas, fit):
    return {"x": 0, "y": 0, "w": int(canvas[0]), "h": int(canvas[1]), "mode": fit}


def t4_ask_config(video_info):
    """Canvas (auto / reels / youtube), fill or fit, letterbox colour (fit only). -> tpl dict; video_box = the whole canvas."""
    print("\n=== Template 4 - Overlay Studio ===")
    cm = ask_choice("Canvas:", ["Auto (by the video shape)", "Reels / Shorts 1080x1920", "YouTube 1920x1080"], default=1,
                    key="t4_canvas")
    mode = ("auto", "reels", "youtube")[cm - 1]
    canvas = t4_canvas(mode, video_info)
    print(f"   -> canvas {canvas[0]}x{canvas[1]}")
    ft = ask_choice("Video inside the canvas:", ["Fill (crop to the canvas)", "Fit (whole video, letterboxed)"], default=1,
                    key="t4_fit")
    fit = "fill" if ft == 1 else "fit"
    t4 = {"canvas_mode": mode, "fit": fit}
    if fit == "fit":
        t4["backdrop"] = _ask_backdrop()
    t4["frame"] = t4_ask_frame()                       # question group 'frame' (T4-8)
    t4["nameplate"] = t4_ask_nameplate()               # question groups 'nameplate' (tag_a / tag_b) and 'corner_list' (T4-9)
    t4["corner_list"] = t4_ask_corner_list()
    t4["tiles"] = t4_ask_tiles()                       # question group 'tiles' (T4-10): a list with one group, or {'on': False}
    t4 = t4_cfg(t4)
    return {"template_id": 5, "canvas": canvas, "video_box": _full_box(canvas, fit), "background": {"type": "color", "value": t4["backdrop"]["value"]},
            "layers": [], "t4": t4}


def _ask_backdrop():
    """What shows around a 'fit' video: solid colour / image / blurred copy of the video. -> backdrop dict (t4_cfg normalises it)."""
    kind = ask_choice("Around the video (backdrop):", ["Solid colour (black by default)", "Image", "Blurred copy of the video"],
                      default=1, key="t4_backdrop_type")
    if kind == 2:
        return {"type": "image", "path": ask("Backdrop image (PNG/JPG...)", cast=c_existing_file(IMAGE_EXTS))}
    if kind == 3:
        return {"type": "blur", "strength": ask("Blur strength 1-10", default=5, key="t4_blur", cast=c_int)}
    return {"type": "color", "value": ask("Backdrop colour (hex or name)", default="#000000", key="t4_backdrop", cast=c_color)}


def t4_ask_cards(cues):
    return []                      # Template 4 has no generic cards; its card modules come later (cfg["t4"]["cards"])


def _canvas_ok(c):
    try:
        return len(c) == 2 and all(int(v) > 0 for v in c)
    except (TypeError, ValueError):
        return False


# ---- the T4 foreground plate (cfg['_t2_fg']): ONE transparent full-canvas PNG over the video, merged from the static parts ---------------
# Each part = (name, builder); builder(W, H, t4) -> RGBA image W x H | None (module off). List order = bottom -> top. A later module
# (nameplate, tags, ...) adds ONE line here: T4_FG_PARTS.append(("nameplate", t4_nameplate_part)) - never its own _t2_fg.
T4_FG_PARTS = [("frame", t4_frame_part)]


def t4_compose_fg(cfg, tmp):
    """Alpha-composite every active part into one plate, save tmp/t4_fg.png and point cfg['_t2_fg'] at it (the pipeline's generic
    foreground slot). No active part -> cfg['_t2_fg'] removed, returns None. A failing part warns once and is skipped; never raises."""
    cfg.pop("_t2_fg", None)
    try:
        W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    plate = None
    for name, build in T4_FG_PARTS:
        try:
            part = build(W, H, cfg.get("t4"))
        except Exception as e:
            t4_warn(f"{name}: could not be drawn ({type(e).__name__}: {e}) - skipped")
            continue
        if part is None:
            continue
        if part.size != (W, H):
            t4_warn(f"{name}: plate is {part.size[0]}x{part.size[1]}, canvas is {W}x{H} - skipped")
            continue
        if plate is None:
            plate = part.convert("RGBA")
        else:
            plate.alpha_composite(part.convert("RGBA"))
    if plate is None:
        return None
    path = os.path.join(tmp or tempfile.gettempdir(), "t4_fg.png")
    plate.save(path, compress_level=1)
    cfg["_t2_fg"] = path
    return path


def t4_build_static_layers(cfg, tmp):
    """Hook build_background: solid backdrop + the foreground plate. The video is the base, so video_box is forced to the full canvas
    (fill / fit from cfg["t4"]); a job without a usable canvas gets one from canvas_mode + the video shape."""
    t4_warn_reset()
    t4 = t4_cfg(cfg.get("t4"))
    cfg["t4"] = t4
    if not _canvas_ok(cfg.get("canvas")):
        info = None
        try:
            info = probe(cfg["video"]) if cfg.get("video") and os.path.isfile(str(cfg["video"])) else None
        except Exception:
            info = None
        cfg["canvas"] = t4_canvas(t4["canvas_mode"], info)
    cfg["canvas"] = [int(cfg["canvas"][0]), int(cfg["canvas"][1])]
    cfg["video_box"] = _full_box(cfg["canvas"], t4["fit"])
    t4_apply_backdrop(cfg, t4)
    t4["frame"] = t4_frame_cfg(t4.get("frame"))        # complete {on, text, color, icon, show_ticks} (extras kept)
    t4["nameplate"] = t4_nameplate_cfg(t4.get("nameplate"))          # complete dicts (extras kept); drawn as Items by t4_build_items
    t4["corner_list"] = t4_corner_list_cfg(t4.get("corner_list"))
    t4["tiles"] = t4_tiles_cfg(t4.get("tiles")) or {"on": False}      # complete groups (extras kept), drawn as Items by t4_build_items
    t4_compose_fg(cfg, tmp)


def t4_build_items(cfg, duration, splits, lbox, rbox):
    return t4_caption_items(cfg, duration) + t4_nameplate_items(cfg, duration) + t4_tiles_items(cfg, duration)   # captions (render.py skips t4_style) + tag / list + logo tiles
