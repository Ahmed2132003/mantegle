"""mt.templates.t4.flow - Template 4 "Overlay Studio": the interview as ONE clean flow in 13 numbered groups (same _hdr style as Template 3),
plus saved styles (like T3's STYLE_KEYS).

   1 video            2 SRT              3 canvas + base     4 captions         5 frame           6 name plates / tags
   7 tiles            8 cards            9 scenes            10 split (+ reframe)                  11 b-roll
   12 texts / elements / template layers / video layers       13 output + quick test

Every group except 1 (the video is the only required answer) starts with  'Use this module? (y/n)'.  Enter = n = the module is skipped (or its
defaults are used), so pressing Enter everywhere gives a valid video: the plain video on the 1080x1920 / 1920x1080 canvas, filled.
Exceptions: group 4 defaults to y when an SRT was given (so the captions are not dropped by mistake); with a saved style, the groups
that hold a saved module default to y.

SAVED STYLES  (selector -> your saved templates; saved with 'Save this as a template?' after group 6)
  STYLE_KEYS are keys of cfg['t4'] (+ 'caption_styles'):
    palette = backdrop + every colour inside the style modules      fonts = the font paths inside frame / name tag / captions
    texts   = frame bar text, name tag name + role, corner-list rows  frame, nameplate, corner_list, canvas_mode, fit
    caption_styles = one dict per SRT stream (look only: no srt path, no keywords)
  Content is NEVER saved and always asked: the SRT paths, keywords, WHEN things appear (start / trigger / hold), tiles, cards, scenes,
  split, b-roll, texts / elements / layers / video layers, the output file."""
import copy
import json
from pathlib import Path

from mt.ask import (_PRESET, ask_elements, ask_layers, ask_output_options, ask_srt_paths, ask_texts, ask_video_layers,
                    ask_video_path, maybe_save_template)
from mt.captions import parse_srt
from mt.common import ask, ask_choice, yn
from mt.templates.t3 import _hdr
from mt.templates.t4 import (_ask_backdrop, _full_box, t4_ask_broll, t4_ask_corner_list, t4_ask_frame, t4_ask_image_cards,
                             t4_ask_nameplate, t4_ask_reframe, t4_ask_scenes, t4_ask_split, t4_ask_tiles, t4_canvas, t4_cfg)
from mt.templates.t4.timing import t4_ask_when
from mt.templates.t4.warn import t4_warn

STYLE_KEYS = ("canvas_mode", "fit", "backdrop", "frame", "nameplate", "corner_list", "caption_styles")
BASE_KEYS = ("canvas_mode", "fit", "backdrop")
TIMING_KEYS = ("start", "trigger", "end", "hold")          # WHEN a module shows = content, never part of a saved style
CAPTION_CONTENT_KEYS = ("srt", "keywords")                  # per-stream content, never part of a saved style
KEYWORDS_Q = ("Words to highlight automatically, comma separated "
              "(Enter = none; you can also put *stars* around words inside the SRT)")


def _use(default=False):
    """The first question of every group (except the video)."""
    return yn("Use this module? (y/n)", default=default)


# ---- saved styles ------------------------------------------------------------------------------------------------------------
def t4_load_style():
    """The saved style picked in the selector (_PRESET['path']) -> (style dict | None, name). Never raises: an unreadable file
    warns once and the normal questions are asked."""
    pp = _PRESET.pop("path", None)
    if not pp:
        return None, ""
    try:
        raw = json.loads(Path(pp).read_text(encoding="utf-8-sig"))
        t4 = raw.get("t4") if isinstance(raw, dict) else None
        if not isinstance(t4, dict):
            raise ValueError("it has no 't4' section")
    except (OSError, ValueError) as e:
        t4_warn("saved style '%s' could not be read (%s) - asking all the questions." % (Path(pp).name, e))
        return None, ""
    return {k: copy.deepcopy(v) for k, v in t4.items() if k in STYLE_KEYS}, Path(pp).stem


def t4_style_of(base, frame, nameplate, corner_list, captions):
    """Build the style dict (STYLE_KEYS only) from the answers of groups 3-6. Timing keys and caption content are stripped."""
    def look(d):
        return {k: copy.deepcopy(v) for k, v in d.items() if k not in TIMING_KEYS} if isinstance(d, dict) else {"on": False}
    style = {k: copy.deepcopy(base[k]) for k in BASE_KEYS if k in base}
    style.update(frame=look(frame), nameplate=look(nameplate), corner_list=look(corner_list))
    style["caption_styles"] = [{k: copy.deepcopy(v) for k, v in c.items() if k not in CAPTION_CONTENT_KEYS}
                               for c in captions if isinstance(c, dict)]
    return style


def _saved_on(style, key):
    sv = (style or {}).get(key)
    return isinstance(sv, dict) and bool(sv.get("on"))


def _saved_copy(style, key):
    d = copy.deepcopy(style[key])
    d["on"] = True
    return d


# ---- groups 1-2 --------------------------------------------------------------------------------------------------------------
def _g_video(cfg):
    _hdr(1, "Video")
    cfg["video"], info = ask_video_path()
    if info["duration"] < 3:
        print(f"   [i] very short video ({info['duration']:.1f} s): anything timed after the end is simply not shown.")
    print("   [i] the video is the base layer and fills the canvas (9:16 -> 1080x1920, 16:9 -> 1920x1080); it is never stretched.")
    return info


def _g_srt():
    _hdr(2, "Captions file (SRT)")
    if not _use():
        return []
    return ask_srt_paths(parse_srt)


# ---- group 3: canvas + base --------------------------------------------------------------------------------------------------
def t4_ask_base(info):
    """Canvas (auto / reels / youtube), fill or fit, backdrop (fit only) -> {canvas_mode, fit, backdrop?}."""
    cm = ask_choice("Canvas:", ["Auto (by the video shape)", "Reels / Shorts 1080x1920", "YouTube 1920x1080"], default=1, key="t4_canvas")
    mode = ("auto", "reels", "youtube")[cm - 1]
    canvas = t4_canvas(mode, info)
    print(f"   -> canvas {canvas[0]}x{canvas[1]}")
    ft = ask_choice("Video inside the canvas:", ["Fill (crop to the canvas)", "Fit (whole video, letterboxed)"], default=1, key="t4_fit")
    out = {"canvas_mode": mode, "fit": "fill" if ft == 1 else "fit"}
    if out["fit"] == "fit":
        out["backdrop"] = _ask_backdrop()
    return out


def _g_base(info, style):
    _hdr(3, "Canvas + base video")
    if style and any(k in style for k in BASE_KEYS):
        print("   Saved style: canvas / fit / backdrop (palette).  y = use them, n = canvas Auto + fill.")
        if not _use(default=True):
            return {"canvas_mode": "auto", "fit": "fill"}
        return {k: copy.deepcopy(style[k]) for k in BASE_KEYS if k in style}
    print("   (n = canvas Auto by the video shape, the video fills the canvas)")
    if not _use():
        return {"canvas_mode": "auto", "fit": "fill"}
    return t4_ask_base(info)


# ---- group 4: captions -------------------------------------------------------------------------------------------------------
def _saved_caption(sty, idx, srt):
    print(f"\n--- Caption style for SRT #{idx + 1}: {Path(srt).name} (saved style) ---")
    c = {k: copy.deepcopy(v) for k, v in sty.items() if k not in CAPTION_CONTENT_KEYS}
    c["srt"] = srt
    c["keywords"] = ask(KEYWORDS_Q, allow_empty=True) or ""
    return c


def _g_captions(srt_paths, style, tpl_entry):
    _hdr(4, "Captions")
    if not srt_paths:
        print("   (no SRT given - no captions)")
        return []
    saved = (style or {}).get("caption_styles")
    saved = [s for s in saved if isinstance(s, dict)] if isinstance(saved, list) else []
    print("   (Enter = yes: the captions use the style questions below" + (" / your saved style" if saved else "") + ")")
    if not _use(default=True):
        return []
    return [_saved_caption(saved[i], i, p) if i < len(saved) else tpl_entry["caption_style"](i, p) for i, p in enumerate(srt_paths)]


# ---- groups 5-6: frame, name plates / tags -----------------------------------------------------------------------------------
def _g_frame(style):
    _hdr(5, "Frame")
    on = _saved_on(style, "frame")
    if on:
        print("   Saved style: frame ON (%r)." % (style["frame"].get("text", ""),))
    if not _use(default=on):
        return {"on": False}
    return _saved_copy(style, "frame") if on else t4_ask_frame(gate=False)


def _timing_tag(d):
    d.update(t4_ask_when("Name tag", 5.0, key="t4_np_when"))
    return d


def _timing_list(d):
    if yn("Keep the corner list on screen for the whole video?", default=True):
        d["start"] = 0.0
    else:
        d.update(t4_ask_when("Corner list", 5.0, key="t4_cl_when"))
    return d


def _sub(style, key, label, fresh, timing):
    """One module of group 6: a saved one -> 'use it?' + the WHEN questions; otherwise the module's own questions."""
    if _saved_on(style, key):
        return timing(_saved_copy(style, key)) if yn(label, default=True) else {"on": False}
    return fresh()


def _g_tags(style):
    _hdr(6, "Name plates / tags")
    saved = _saved_on(style, "nameplate") or _saved_on(style, "corner_list")
    if saved:
        print("   Saved style: name tag / corner list found (the WHEN questions are still asked).")
    if not _use(default=saved):
        return {"on": False}, {"on": False}
    np = _sub(style, "nameplate", "Use the saved name tag? (y/n)", t4_ask_nameplate, _timing_tag)
    cl = _sub(style, "corner_list", "Use the saved corner list? (y/n)", t4_ask_corner_list, _timing_list)
    return np, cl


def _save_style(base, frame, nameplate, corner_list, captions):
    print("\n   (A saved template keeps the LOOK: canvas / backdrop, frame, name tag, corner list, caption style, colours, fonts, texts."
          "\n    Content - SRT, keywords, when things appear, tiles, cards, scenes, split, b-roll - is asked again every time.)")
    maybe_save_template({"template_id": 5, "t4_style": True, "layers": [],
                         "t4": t4_style_of(base, frame, nameplate, corner_list, captions)})


# ---- groups 7-11: content modules --------------------------------------------------------------------------------------------
def _g_module(n, title, fresh, off=None):
    _hdr(n, title)
    return fresh(gate=False) if _use() else (off if off is not None else {"on": False})


def _g_split():
    _hdr(10, "Split screen")
    if not _use():
        return {"on": False}, {"on": False}
    split = t4_ask_split(gate=False)
    return split, t4_ask_reframe(split)               # the reframe question only appears when the split is on


# ---- group 12-13 -------------------------------------------------------------------------------------------------------------
def _g_extras(cfg, duration):
    _hdr(12, "Texts / elements / template layers / video layers")
    on = _use()
    cfg["texts"] = ask_texts(duration) if on else []
    cfg["elements"] = ask_elements(duration) if on else []
    cfg["layers"] = ask_layers(*cfg["canvas"]) if on else []
    cfg["video_layers"] = ask_video_layers(duration) if on else []


def _g_output(cfg):
    _hdr(13, "Output + quick test")
    print("   (n = <video>_edited.mp4 next to the video, the whole video is rendered)")
    if _use():
        ask_output_options(cfg)
    else:
        cfg["output"] = str(Path(cfg["video"]).with_suffix("")) + "_edited.mp4"
        cfg["preview"] = None


def t4_interview(cfg, tpl_entry):
    """The whole Template 4 interview (called by templates._interactive_t4). Fills and returns cfg."""
    style, name = t4_load_style()
    print("\n=== Template 4 - Overlay Studio ===")
    print("   (Every group starts with 'Use this module? (y/n)'.  Enter = n = skipped; Enter everywhere = the plain video.)")
    if style is not None:
        print(f"   Loaded saved style '{name}': look questions are skipped, the content questions are still asked.")
    info = _g_video(cfg)
    srt_paths = _g_srt()
    base = _g_base(info, style)
    cfg["captions"] = _g_captions(srt_paths, style, tpl_entry)
    frame = _g_frame(style)
    nameplate, corner_list = _g_tags(style)
    if style is None:
        _save_style(base, frame, nameplate, corner_list, cfg["captions"])
    t4 = dict(base, frame=frame, nameplate=nameplate, corner_list=corner_list)
    t4["tiles"] = _g_module(7, "Logo tiles", t4_ask_tiles)
    t4["cards"] = _g_module(8, "Image / video cards", t4_ask_image_cards)
    t4["scenes"] = _g_module(9, "Infographic scenes", t4_ask_scenes)
    t4["split"], t4["reframe"] = _g_split()
    t4["broll"] = _g_module(11, "B-roll takeover", t4_ask_broll)
    t4 = t4_cfg(t4)
    canvas = t4_canvas(t4["canvas_mode"], info)
    cfg.update({"canvas": canvas, "video_box": _full_box(canvas, t4["fit"]), "background": {"type": "color", "value": t4["backdrop"]["value"]},
                "t4": t4, "cards": []})
    _g_extras(cfg, info["duration"])
    _g_output(cfg)
    return cfg