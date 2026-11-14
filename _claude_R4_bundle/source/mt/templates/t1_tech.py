"""mt.templates.t1_tech - moved from montage.py by tools/mt_move.py"""
from mt.fonts import load_font, shape
from mt.draw import CYAN, CYAN_TXT, Item, _draw_icon
from mt.common import AR_DIGITS, IMAGE_EXTS, VIDEO_EXTS, ask, ask_choice, c_color, c_existing_file, c_float, c_int, c_percent, c_size_wh, c_time, clean_path, yn
from mt.ask import _PRESET, _tpl_template_id, ask_layers, list_templates, maybe_save_template
from mt.ask import ask_anim, ask_font
from mt.captions import find_trigger
from mt.split import SPLIT_T, make_split_background, split_at, split_boxes
from mt.draw import make_tech_background
from PIL import Image, ImageDraw, ImageFilter
import os
from pathlib import Path
import re
import json


def make_card_sprite(l1, l2, icon, icon_path, layout, tail, font_path, canvas_w):
    k = canvas_w / 1080.0
    if layout == "v":
        w, h = int(200 * k), int(187 * k)
    else:
        w, h = int(380 * k), int(105 * k)
    P = int((110 if tail else 36) * k)
    img = Image.new("RGBA", (w + 2 * P, h + 2 * P), (0, 0, 0, 0))
    c = int(15 * k)
    if layout == "v" and tail != "v-right":
        pts = [(c * 1.6, 0), (w, 0), (w, h - c), (w - c, h), (0, h), (0, c * 1.6)]
    elif layout == "v":
        pts = [(0, 0), (w - c * 1.6, 0), (w, c * 1.6), (w, h), (c, h), (0, h - c)]
    else:
        pts = [(0, 0), (w - c, 0), (w, c), (w, h), (c, h), (0, h - c)]
    pts = [(P + x, P + y) for x, y in pts]
    tails = {
        "h-right-down": [(w - 6 * k, h * 0.42), (w + 50 * k, h * 0.42 + 28 * k), (w + 50 * k, h + 78 * k)],
        "v-left": [(w * 0.55, h), (w * 0.55 + 18 * k, h + 26 * k), (w + 3 * k, h + 26 * k)],
        "v-right": [(w * 0.45, h), (w * 0.45 - 18 * k, h + 26 * k), (-3 * k, h + 26 * k)],
    }
    tl = [(P + x, P + y) for x, y in tails.get(tail, [])]

    gl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(gl)
    gd.line(pts + [pts[0]], fill=CYAN + (255,), width=max(3, int(5 * k)), joint="curve")
    if tl:
        gd.line(tl, fill=CYAN + (255,), width=max(2, int(4 * k)), joint="curve")
    glow = gl.filter(ImageFilter.GaussianBlur(9 * k))
    img.alpha_composite(glow)
    img.alpha_composite(glow)

    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=(6, 19, 50, 228))
    d.line(pts + [pts[0]], fill=(45, 175, 255, 255), width=max(2, int(3 * k)), joint="curve")
    d.line([(P + w * 0.52, P), (P + w * 0.90, P)], fill=(160, 228, 255, 255), width=max(3, int(5 * k)))
    if tl:
        d.line(tl, fill=(60, 185, 255, 255), width=max(2, int(2.5 * k)), joint="curve")
        r = 4.5 * k
        d.ellipse((tl[-1][0] - r, tl[-1][1] - r, tl[-1][0] + r, tl[-1][1] + r), fill=(120, 215, 255, 255))

    bd = int(72 * k)
    if layout == "v":
        bx, by = P + (w - bd) / 2.0, P + int(14 * k)
    else:
        bx, by = P + int(16 * k), P + (h - bd) / 2.0
    d.ellipse((bx, by, bx + bd, by + bd), fill=(12, 40, 96, 255), outline=(30, 125, 235, 255),
              width=max(2, int(3 * k)))
    if icon and icon != "none":
        _draw_icon(img, "image" if icon == "image" else icon,
                   (bx + bd * 0.22, by + bd * 0.22, bx + bd * 0.78, by + bd * 0.78), icon_path)

    lines = [(l1, (255, 255, 255, 255))] + ([(l2, CYAN_TXT + (255,))] if l2 else [])
    if layout == "v":
        ax0, ay0 = P + 22 * k, by + bd + 10 * k
        aw, ah = w - 40 * k, (P + h) - ay0 - 10 * k
        size = int(24 * k)
    else:
        ax0, ay0 = bx + bd + 18 * k, P + 8 * k
        aw, ah = (P + w) - ax0 - 18 * k, h - 16 * k
        size = int(31 * k)
    while True:
        font = load_font(font_path, max(8, size))
        asc, desc = font.getmetrics()
        lh = asc + desc
        widest = max(font.getlength(shape(t)) for t, _ in lines)
        if (widest <= aw and lh * len(lines) <= ah) or size <= 9:
            break
        size -= 1
    y = ay0 + (ah - lh * len(lines)) / 2.0
    for t, col in lines:
        d.text((ax0, y + asc), shape(t), font=font, fill=col, anchor="ls")
        y += lh
    return img


def ask_hud_template(title="Tech HUD template (1080x1920)", save=True):
    tpl = {"canvas": [1080, 1920]}
    W, H = tpl["canvas"]
    print(f"\n--- {title} ---")
    bw, bh = ask("Video window size WxH", default="604x928", cast=c_size_wh)
    bw, bh = min(bw, W - 100), min(bh, H - 600)
    by = ask("Video window top position (px from the top)", default=335, cast=c_int)
    mode = ask_choice("How should the video fit its window?",
                      ["fit  (whole video visible, may leave gaps)", "fill (crop to cover the window)"], default=2)
    tpl["video_box"] = {"x": (W - bw) // 2, "y": by, "w": bw, "h": bh, "mode": "fit" if mode == 1 else "fill"}
    tpl["background"] = {"type": "tech",
                         "divider_pct": ask("Divider line position under the video (% of height, 0 = none)",
                                            default=79, cast=c_percent)}
    tpl["layers"] = ask_layers(W, H)
    return maybe_save_template(tpl) if save else tpl


def ask_template(video_info):
    """Custom flow: saved templates (templates/*.json) or a brand-new custom template.
    (The 'Template style' question moved to choose_template(), which is asked first.)"""
    tpl = {}
    pp = _PRESET.pop("path", None)
    if pp and os.path.isfile(pp):                       # chosen in the selector: load it, ask nothing
        tpl = json.loads(Path(pp).read_text(encoding="utf-8-sig"))
        print(f"   Loaded template '{Path(pp).stem}'.")
        return tpl
    existing = [p for p in list_templates() if _tpl_template_id(p) != 2]   # Template 2 designs load via Template 2
    choice = 0
    if existing:
        labels = ["New template (answer the questions)"] + [p.stem for p in existing]
        choice = ask_choice("\n--- Template ---", labels, default=1) - 1
    if choice > 0:
        tpl = json.loads(existing[choice - 1].read_text(encoding="utf-8"))
        print(f"   Loaded template '{existing[choice - 1].stem}'.")
        return tpl

    print("\n--- Canvas (final video size) ---")
    n = ask_choice("Final size:", ["1080x1920  (9:16 vertical)", "1920x1080  (16:9 horizontal)",
                                   "1080x1080  (square)", "1080x1350  (4:5)", "Custom"], default=1)
    presets = {1: [1080, 1920], 2: [1920, 1080], 3: [1080, 1080], 4: [1080, 1350]}
    if n == 5:
        tpl["canvas"] = ask("Custom size WxH", cast=c_size_wh)
    else:
        tpl["canvas"] = presets[n]
    W, H = tpl["canvas"]

    print("\n--- Video box (where the video sits inside the canvas) ---")
    print(f"   Source video: {video_info['w']}x{video_info['h']}   Canvas: {W}x{H}")
    bw, bh = ask("Video size WxH (Enter = whole canvas)", default=f"{W}x{H}", cast=c_size_wh)
    bw, bh = min(bw, W), min(bh, H)
    print("   Position of the video box:  1=center  2=top  3=bottom  or  x,y (top-left corner in px)")

    def _vp(s):
        s = s.strip().translate(AR_DIGITS)
        if s in ("1", "2", "3"):
            return s
        m = re.fullmatch(r"(-?\d+)\s*[,;x]\s*(-?\d+)", s)
        if m:
            return [int(m.group(1)), int(m.group(2))]
        raise ValueError("use 1, 2, 3 or x,y")
    vp = ask("Video box position", default="1", cast=_vp)
    if vp == "1":
        bx, by = (W - bw) // 2, (H - bh) // 2
    elif vp == "2":
        bx, by = (W - bw) // 2, 0
    elif vp == "3":
        bx, by = (W - bw) // 2, H - bh
    else:
        bx, by = vp
    mode = ask_choice("How should the video fit its box?",
                      ["fit  (whole video visible, may leave gaps)", "fill (crop to cover the box)"], default=1)
    tpl["video_box"] = {"x": bx, "y": by, "w": bw, "h": bh, "mode": "fit" if mode == 1 else "fill"}

    print("\n--- Background (the edges around the video) ---")
    b = ask_choice("Background type:", ["Solid color", "Image", "Video (looped)"], default=1)
    if b == 1:
        tpl["background"] = {"type": "color", "value": ask("Background color", default="#101820",
                                                           key="bg_color", cast=c_color)}
    elif b == 2:
        tpl["background"] = {"type": "image", "path": ask("Background image path",
                                                          cast=c_existing_file(IMAGE_EXTS))}
    else:
        tpl["background"] = {"type": "video", "path": ask("Background video path",
                                                          cast=c_existing_file(VIDEO_EXTS))}
    tpl["layers"] = ask_layers(W, H)

    return maybe_save_template(tpl)


ICON_LINE = "1=code  2=phone  3=chip/AI  4=none  or a path to a PNG/ICO"


SLOT_LINE = "1=top-left  2=left  3=right"


SLOTS = {1: (0.25, 0.1255, "h", "h-right-down"),
         2: (0.116, 0.32, "v", "v-left"),
         3: (0.887, 0.32, "v", "v-right")}


def ask_cards(cues):
    cards = []
    if not yn("\nDo you want HUD cards (like WEB DEVELOPER / AI AUTOMATION) that change with the speech?",
              default=False):
        return cards
    while True:
        print(f"\n--- Card #{len(cards) + 1} ---")
        e = {}
        e["l1"] = ask("Line 1 (white)  e.g. WEB")
        e["l2"] = ask("Line 2 (blue)   e.g. DEVELOPER  (Enter = none)", allow_empty=True) or ""
        print("   " + ICON_LINE)

        def _icon(s):
            s = s.strip().translate(AR_DIGITS)
            m = {"1": "code", "2": "phone", "3": "chip", "4": "none"}
            if s in m:
                return m[s]
            return clean_path(s) if os.path.isfile(clean_path(s)) else (_ for _ in ()).throw(
                ValueError("use 1-4 or a valid image path"))
        ic = ask("Icon", default="1", cast=_icon)
        e["icon"], e["icon_path"] = ("image", ic) if ic not in ("code", "phone", "chip", "none") else (ic, None)
        print("   " + SLOT_LINE)
        e["slot"] = ask("Position", default="1", cast=lambda s: int(s.translate(AR_DIGITS)) if s.strip().translate(
            AR_DIGITS) in ("1", "2", "3") else (_ for _ in ()).throw(ValueError("choose 1-3")))
        while True:
            raw = ask("Appears when this word/phrase is said (from the SRT)  -or-  a time in seconds")
            try:
                e["start"] = c_time(raw)
                break
            except ValueError:
                pass
            t = find_trigger(cues, raw) if cues else None
            if t is None:
                print("   [!] that word was not found in the SRT. Try another word, or type a time.")
                continue
            e["start"] = round(t, 3)
            print(f"   -> found at {t:.2f}s")
            break
        e["hold"] = ask("How long it stays (seconds)", default=4, cast=c_float)
        e["anim"] = ask_anim("Animation", default="pop", key="card_anim")
        e["anim_dur"] = 0.45
        cards.append(e)
        if not yn("Add another card?", default=True):
            break
    if cards:
        cfg_font = ask_font("Card font (bold sans looks best)", "card_font")
        for c in cards:
            c["font"] = cfg_font
    return cards


def t1_build_items(cfg, duration, splits, lbox, rbox):
    """Template 1 (Tech HUD) hook: template-specific timeline items = the HUD cards.
    (end = hold time, or when the next card of the same slot appears)"""
    W, H = cfg["canvas"]
    T = SPLIT_T
    items = []
    cards = sorted(cfg.get("cards", []), key=lambda x: x["start"])
    for i, cd in enumerate(cards):
        slot = cd.get("slot", 1)
        fx, fy, layout, tail = SLOTS.get(slot, SLOTS[1])
        end = cd["start"] + cd.get("hold", 4)
        for o in cards[i + 1:]:
            if o.get("slot", 1) == slot and o["start"] > cd["start"]:
                end = min(end, o["start"])
                break
        end = min(end, duration + 1)
        cuts = [cd["start"], end]
        if splits and slot in (2, 3):
            for a, b in splits:
                for x in (a - T, b + T):
                    if cd["start"] < x < end:
                        cuts.append(x)
        cuts = sorted(set(cuts))
        for s0, e0 in zip(cuts, cuts[1:]):
            if splits and slot in (2, 3) and split_at(splits, (s0 + e0) / 2.0):
                px, py, lay, tl = (0.27 if slot == 2 else 0.73), 0.672, "h", None
            else:
                px, py, lay, tl = fx, fy, layout, tail
            spr = make_card_sprite(cd["l1"], cd.get("l2", ""), cd.get("icon"), cd.get("icon_path"),
                                   lay, tl, cd["font"], W)
            items.append(Item(spr, s0, e0, px * W, py * H,
                              cd.get("anim", "pop"), cd.get("anim_dur", 0.45), True, 1.0))
    return items


# ----------------------------------------------------------------------------
# Template system (registry)
#
#   cfg["template_id"]  1 = Tech HUD      2 = Lime Creator Series      3 = Custom
#   Every template provides these hooks (see TEMPLATE_REGISTRY below):
#     ask_config(video_info)            -> dict(canvas, video_box, background, layers[, t2])
#     ask_cards(cues)                   -> list of card dicts
#     caption_style(idx, srt_path)      -> caption style dict
#     build_background(cfg, tmpdir)     -> writes the static background (and split background)
#                                          PNGs and points cfg["background"] / cfg["_split_bg"] at them
#     build_items(cfg, duration, splits, lbox, rbox) -> template-specific timeline Items
#                                          (cards / floating cards / badges...), appended after texts
#   Old job files have no "template_id" and are rendered as Template 1.
# ----------------------------------------------------------------------------
# Per-template color palettes (RGB). Template 2 must never use the Template 1 cyan.
PALETTES = {
    1: {"accent": CYAN, "accent_txt": CYAN_TXT},
    # TODO(PART2/3/4): tune these values against the poster (Building_Digital_Experiences_Poster.png)
    2: {"bg": (8, 10, 14), "lime": (189, 222, 56), "lime_dark": (110, 136, 32),
        "white": (255, 255, 255), "muted": (141, 146, 143)},
}


def t1_build_background(cfg, tmp):
    """Template 1 (Tech HUD) static layers: procedural background (+ split background)."""
    bg = cfg["background"]
    if bg.get("type") == "tech":
        W, H = cfg["canvas"]
        p = make_tech_background(W, H, cfg["video_box"], bg.get("divider_pct", 79), os.path.join(tmp, "bg.png"))
        cfg["background"] = {"type": "image", "path": p}
        if cfg.get("split"):
            lb, rb = split_boxes(cfg)
            cfg["_split_bg"] = make_split_background(W, H, lb, rb, bg.get("divider_pct", 79),
                                                     os.path.join(tmp, "bg_split.png"))


def t1_ask_config(video_info):
    return ask_hud_template()
