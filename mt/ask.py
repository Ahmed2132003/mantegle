"""mt.ask - moved from montage.py by tools/mt_move.py"""
from mt.fonts import default_font, find_font, font_supports_arabic, list_local_fonts
from mt.common import AR_DIGITS, D, ask
from mt.anim import ANIMS
import os
from pathlib import Path
from mt.anim import PRESETS
from mt.common import AR_DIGITS, D, IMAGE_EXTS, TEMPLATES_DIR, clean_path, probe, VIDEO_EXTS, ask, ask_choice, ask_time, c_color, c_existing_file, c_float, c_int, c_percent, c_text, yn
from mt.common import TEMPLATE_REGISTRY
import re
import json


def ask_font(prompt, key):
    local = list_local_fonts()
    if local:
        print("   Fonts in the 'fonts' folder:")
        for i, f in enumerate(local, 1):
            print(f"     {i}) {Path(f).name}")
    print("   (type a number, a font name like Arial / Cairo, or a full path to a .ttf/.otf file)")
    default = D.get(key) if D.get(key) and os.path.isfile(D.get(key)) else default_font()

    def _c(s):
        if s.isdigit() and local and 1 <= int(s) <= len(local):
            return local[int(s) - 1]
        p = find_font(s)
        if not p:
            raise ValueError("font not found. Put the .ttf in the 'fonts' folder next to the script or give the full path")
        return p

    path = ask(prompt, default=default, cast=_c)
    D[key] = path
    if not font_supports_arabic(path):
        print("   [!] This font does not seem to support Arabic (fine for English-only text).")
    return path


ANIM_LINE = ("0=none  1=fade  2=slide_up  3=slide_down  4=slide_left  5=slide_right  "
             "6=zoom_in  7=pop  8=spin_in  9=reveal(typewriter)  10=drop")


def c_anim(s):
    s = s.strip().lower().translate(AR_DIGITS)
    if s.isdigit():
        v = int(s)
        if v == 0:
            return "none"
        if 1 <= v <= len(ANIMS):
            return ANIMS[v - 1]
        raise ValueError("choose 0-10")
    if s in ("none", "reveal", "typewriter") or s in ANIMS:
        return "reveal" if s == "typewriter" else s
    raise ValueError("unknown animation")


def ask_anim(prompt, default="fade", key=None):
    print("   " + ANIM_LINE)
    return ask(prompt, default=default, key=key, cast=c_anim)


POS_LINE = ("1=top-left 2=top 3=top-right 4=left 5=center 6=right 7=bottom-left 8=bottom 9=bottom-right"
            "  or  x,y  (center point, px or %, e.g. 540,300 or 50%,15%)")


def c_pos(s):
    s = s.strip().lower().translate(AR_DIGITS).replace("_", "-").replace(" ", "")
    if s in PRESETS:
        return PRESETS[s]
    if s in PRESETS.values() or s in ("middle", "centre"):
        return "center" if s in ("middle", "centre") else s
    m = re.fullmatch(r"(-?[\d.]+%?)[,;x](-?[\d.]+%?)", s)
    if m:
        return [m.group(1), m.group(2)]
    raise ValueError("use 1-9, a preset name, or x,y")


def ask_pos(prompt, default="center", key=None):
    print("   " + POS_LINE)
    return ask(prompt, default=default if not isinstance(default, list) else ",".join(default),
               key=key, cast=c_pos)


def list_templates():
    if not TEMPLATES_DIR.is_dir():
        return []
    return sorted(TEMPLATES_DIR.glob("*.json"))


def ask_layers(W, H):
    layers = []
    print("\nTemplate layers = PNG/ICO decorations that stay on screen for the whole video")
    print("(frames, borders, logo, side decorations...).")
    while yn("Add a template layer?", default=False):
        L = {}
        L["path"] = ask("  Image path (PNG/ICO)", cast=c_existing_file(IMAGE_EXTS))
        L["pos"] = ask_pos("  Position", default="center")
        L["width"] = ask("  Width: px or % of canvas (Enter = original size)", allow_empty=True)
        L["opacity"] = ask("  Opacity %", default=100, cast=c_percent)
        L["anim"] = ask_anim("  Entrance animation", default="none")
        L["anim_dur"] = 0.6
        layers.append(L)
    return layers


def maybe_save_template(tpl):
    name = ask("Save this as a template? Type a name (Enter = don't save)", allow_empty=True)
    if name:
        TEMPLATES_DIR.mkdir(exist_ok=True)
        safe = re.sub(r"[^\w\- ]+", "", name, flags=re.UNICODE).strip() or "template"
        (TEMPLATES_DIR / f"{safe}.json").write_text(json.dumps(tpl, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
        print(f"   Saved templates/{safe}.json")
    return tpl


_PRESET = {}     # {"path": saved template chosen in the selector, "sel": True while Template 2's own flow runs}


def _saved_templates():
    """[(path, registry_id)] for every templates/*.json: Template 2 / 3 designs -> 2 / 3, everything else -> 4 (Custom)."""
    out = []
    for p in list_templates():
        out.append((p, _tpl_template_id(p) if _tpl_template_id(p) in (2, 3) else 4))
    return out


def ask_texts(duration):
    texts = []
    if not yn("\nDo you want text on the video?", default=False):
        return texts
    while True:
        print(f"\n--- Text #{len(texts) + 1} ---")
        t = {}
        t["text"] = ask("Text  (use \\n for a new line, or @file.txt to read it from a file)", cast=c_text)
        t["start"] = ask_time("Appears at", default=0)
        t["end"] = ask_time("Disappears at", default=round(min(duration, t["start"] + 3), 2))
        t["pos"] = ask_pos("Position", default="top", key="txt_pos")
        t["font"] = ask_font("Font", "txt_font")
        t["size"] = ask("Font size (px)", default=90, key="txt_size", cast=c_int)
        t["color"] = ask("Text color", default="white", key="txt_color", cast=c_color)
        t["stroke_color"] = ask("Outline color", default="black", key="txt_stroke", cast=c_color)
        t["stroke_w"] = ask("Outline width (px, 0 = none)", default=0, key="txt_strokew", cast=c_int)
        t["anim"] = ask_anim("Animation", default="fade", key="txt_anim")
        t["anim_dur"] = ask("Animation duration (seconds)", default=0.5, key="txt_adur", cast=c_float)
        texts.append(t)
        if not yn("Add another text?", default=False):
            break
    return texts


def ask_elements(duration):
    els = []
    if not yn("\nDo you want elements (PNG / ICO images) on the video?", default=False):
        return els
    while True:
        print(f"\n--- Element #{len(els) + 1} ---")
        e = {}
        e["path"] = ask("Image path (PNG/ICO/...)", cast=c_existing_file(IMAGE_EXTS))
        e["start"] = ask_time("Appears at", default=0)
        e["end"] = ask_time("Disappears at", default=round(min(duration, e["start"] + 3), 2))
        e["pos"] = ask_pos("Position", default="center")
        e["width"] = ask("Width: px or % of canvas (Enter = original size)", allow_empty=True)
        e["opacity"] = ask("Opacity %", default=100, cast=c_percent)
        e["anim"] = ask_anim("Animation", default="pop", key="el_anim")
        e["anim_dur"] = ask("Animation duration (seconds)", default=0.5, key="el_adur", cast=c_float)
        els.append(e)
        if not yn("Add another element?", default=False):
            break
    return els


def ask_video_layers(duration):
    vls = []
    if not yn("\nDo you want a video layer (screen recording / b-roll) shown at a certain time?", default=False):
        return vls
    while True:
        print(f"\n--- Video layer #{len(vls) + 1} ---")
        v = {}
        v["path"] = ask("Video path", cast=c_existing_file(VIDEO_EXTS))
        v["start"] = ask_time("Appears at", default=0)
        v["end"] = ask_time("Disappears at", default=round(min(duration, v["start"] + 5), 2))
        a = ask_choice("Where?", ["Over the video box", "Over the whole canvas"], default=1)
        v["area"] = "box" if a == 1 else "canvas"
        m = ask_choice("Fit:", ["fill (crop to cover)", "fit (whole video visible)"], default=1)
        v["mode"] = "fill" if m == 1 else "fit"
        v["fade"] = 0.3
        vls.append(v)
        if not yn("Add another video layer?", default=False):
            break
    return vls


def _tpl_template_id(path):
    try:
        return int(json.loads(Path(path).read_text(encoding="utf-8")).get("template_id") or 0)
    except Exception:
        return 0


# ---- generic question steps of the main flow (extracted verbatim from montage._interactive_core) ----
def ask_video_path():
    """Video path + probe summary line. Returns (path, info)."""
    video = ask("Video path", cast=c_existing_file(VIDEO_EXTS))
    info = probe(video)
    print(f"   -> {info['w']}x{info['h']}, {float(info['fps']):.2f} fps, {info['duration']:.1f} s"
          f"{'' if info['audio'] else ', no audio'}")
    return video, info


def ask_srt_paths(parse_srt):
    """One or more SRT paths (parse_srt is passed in: mt.captions imports mt.ask, so ask cannot import it)."""
    srt_paths = []
    nxt = ask("SRT captions file path (Enter = no captions)", cast=c_existing_file((".srt",)),
              allow_empty=True)
    while nxt:
        cues = parse_srt(nxt)
        if not cues:
            print("   [!] No captions could be read from that SRT file - skipped.")
        else:
            print(f"   -> {len(cues)} caption blocks read.")
            srt_paths.append(nxt)
        nxt = ask("Another SRT (for example the English translation)? Path, or Enter = no",
                  cast=c_existing_file((".srt",)), allow_empty=True)
    return srt_paths


def ask_output_options(cfg):
    """Output file + quick-preview seconds; fills cfg['output'] and cfg['preview']."""
    print("\n--- Output ---")
    stem = Path(cfg["video"]).with_suffix("")
    cfg["output"] = ask("Output file", default=str(stem) + "_edited.mp4",
                        cast=lambda s: clean_path(s if s.lower().endswith(".mp4") else s + ".mp4"))
    cfg["preview"] = ask("Quick test: render only the first N seconds (Enter = full video)",
                         allow_empty=True, cast=c_float)
    return cfg
