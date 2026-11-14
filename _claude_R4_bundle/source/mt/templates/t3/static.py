"""mt.templates.t3.static - Template 3 "Editorial Orange": the STATIC plates (T3-1).
   BACKGROUND png (RGB, under the video): diagonal polygons, paper patches, orange slash, face watermark, skyline.
   FOREGROUND png (RGBA, over the video):  header (name, roles, tagline) + footer (words, line, signature).
Poster space is 941x1672; everything is scaled by K (= 1080/941) onto the 1080x1920 canvas."""
import hashlib
import math
import os
import subprocess
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from mt.common import FFMPEG
from mt.draw import (draw_dotted_line, paper_texture, rotated_mask, t2_darken, t2_draw_mask, t2_fit_text, t2_gradient,
                     t2_line_mask, t2_lighten, t2_mask_full, t2_mix, t2_paint, t2_place, t2_poly_mask, t2_rgb,
                     t2_size_for_cap, t2_text_mask)
from mt.fonts import _t2_lookup, default_font, has_arabic, t2_font

K = 1080 / 941.0
PALETTE = {"accent": "#F56D1F", "cream": "#FFF4E6", "maroon": "#682028", "deep_maroon": "#4E2224",
           "dark0": "#0D0806", "dark1": "#1C1112", "paper": "#C6A588"}
DEFAULTS = {"accent": PALETTE["accent"], "name1": "Ahmed", "name2": "Ibrahim",
            "roles": ["Web Developer", "Mobile App Developer", "AI Automation"],
            "tagline": "BUILD • INNOVATE • AUTOMATE", "footer": "DREAM • DEVELOP • DELIVER",
            "signature": "Ahmed Ibrahim", "watermark": True,
            "show_bg": True, "show_header": True, "show_footer": True,
            # T3-2: video frame + headline column
            "frame_style": "skewed", "frame_skew": 1.0, "video_fit": "fill",
            "show_headline": True, "headline": ["BEYOND", "THE", "CODE."],
            "headline_colors": ["cream", "cream", "accent"], "headline_underline": True,
            "tag_lines": ["TECHNOLOGY", "THAT MAKES", "A DIFFERENCE"],
            # T3-3: chapter tag (inside the frame, top-left)
            "chapters_on": True, "chapter_anim": "slide_up", "chapter_anim_dur": 0.35,
            # T3-4: floating photo card
            "cards_on": True, "cards": [], "card_rot": 3.0, "card_skew": 0.03, "card_anim_dur": 0.5,
            "chapters": [{"start": 0.0, "trigger": "", "label": "INTRODUCTION", "num": "", "anim": "", "anim_dur": 0.0,
                          "end": None}]}
LEGACY_BOX = {"x": 60, "y": 430, "w": 960, "h": 1060}                    # T3-1 placeholder window (still valid input)
POSTER_QUAD = [(35, 210), (540, 182), (627, 950), (22, 955)]            # TL, TR, BR, BL in poster px (941x1672)
_PB = (22, 182, 627, 955)                                               # poster bbox of that quad
VIDEO_BOX = {"x": int(round(_PB[0] * K)), "y": int(round(_PB[1] * K)), "w": int(round((_PB[2] - _PB[0]) * K)),
             "h": int(round((_PB[3] - _PB[1]) * K)), "mode": "fill"}     # bbox of the poster quad on 1080x1920

# role -> (recommended names for the message, candidates in order of preference, fake-italic if only upright found)
FONTS = {
    "serif": ("PlayfairDisplay-Bold.ttf", ["playfairdisplaybold", "playfairdisplay", "dejavuserifbold", "freeserifbold",
                                           "caladeabold", "liberationserifbold", "timesbd", "georgiab"], False),
    "caps": ("Rajdhani-SemiBold.ttf", ["rajdhanisemibold", "rajdhanimedium", "rajdhanibold", "dejavusansbold",
                                       "liberationsansbold", "arialbd", "freesansbold"], False),
    "light": ("Rajdhani-Light.ttf", ["rajdhanilight", "rajdhaniregular", "rajdhanimedium", "dejavusans",
                                     "liberationsans", "arial", "freesans"], False),
    "head": ("Kanit-BlackItalic.ttf (or Kanit-ExtraBoldItalic.ttf)",
             ["kanitblackitalic", "kanitextrabolditalic", "montserratblackitalic", "poppinsbolditalic",
              "dejavusansboldoblique", "liberationsansbolditalic", "dejavusansbold", "liberationsansbold",
              "arialbd", "freesansbold"], True),
    "script": ("MrsSaintDelafield-Regular.ttf (or Allura-Regular.ttf)",
               ["mrssaintdelafieldregular", "allura", "allurarregular", "dejavuserifitalic", "freeserifitalic",
                "caladeaitalic", "timesi", "georgiai"], True),
}
_WARNED = set()


_MSGS = set()


def t3_warn(msg):
    """Print a [!] message once per render (layout items are rebuilt per segment, so the same warning would repeat hundreds of times)."""
    if msg not in _MSGS:
        _MSGS.add(msg)
        print(msg)


def t3_font(role, text="", overrides=None):
    """-> (font_path, shear). Arabic text uses Cairo (via t2_font). Never raises; one message naming the missing file."""
    if has_arabic(text):
        return t2_font("arabic", text)[0], 0.0
    hint, cands, shear_fb = FONTS[role]
    ov = (overrides or {}).get(role)
    if ov and os.path.isfile(str(ov)):
        return ov, 0.0
    rec = cands[:2] if role != "caps" else cands[:3]
    for n in cands:
        try:
            p = _t2_lookup(n)
        except Exception:
            p = None
        if p:
            fake = shear_fb and n not in rec and not (role == "head" and ("italic" in n or "oblique" in n))
            if n not in rec and role not in _WARNED:
                _WARNED.add(role)
                print(f"[fonts] Template 3 {role}: '{hint}' not found - put it in the fonts/ folder next to montage.py "
                      f"(using '{Path(p).name}' for now)")
            return p, ((0.2 if role == "head" else 0.22) if fake else 0.0)
    if role not in _WARNED:
        _WARNED.add(role)
        print(f"[fonts] Template 3 {role}: '{hint}' not found - put it in the fonts/ folder (using the default font)")
    return default_font(), (0.22 if shear_fb else 0.0)


def t3_cfg(raw=None):
    """Normalise cfg['t3']: every key present and valid (bad values -> poster defaults)."""
    raw = dict(raw or {})
    t = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    for k in ("name1", "name2", "tagline", "footer", "signature"):
        if k in raw and raw[k] is not None:
            t[k] = str(raw[k]).strip()
    roles = raw.get("roles")
    if isinstance(roles, (list, tuple)):
        t["roles"] = [str(r or "").strip() for r in roles][:3]
    t["roles"] += [""] * (3 - len(t["roles"]))
    try:
        t["accent"] = "#%02X%02X%02X" % t2_rgb(raw.get("accent") or DEFAULTS["accent"])
    except Exception:
        pass
    for k in ("watermark", "show_bg", "show_header", "show_footer"):
        if k in raw:
            t[k] = bool(raw[k])
    fs = str(raw.get("frame_style", t["frame_style"])).strip().lower()
    t["frame_style"] = fs if fs in ("skewed", "straight") else "skewed"
    try:
        t["frame_skew"] = max(0.0, min(1.5, float(raw.get("frame_skew", t["frame_skew"]))))
    except (TypeError, ValueError):
        t["frame_skew"] = 1.0
    vf = str(raw.get("video_fit", t["video_fit"])).strip().lower()
    t["video_fit"] = vf if vf in ("fill", "fit") else "fill"
    for k in ("show_headline", "headline_underline"):
        if k in raw:
            t[k] = bool(raw[k])
    for k, n in (("headline", 3), ("headline_colors", 3), ("tag_lines", 3)):
        v = raw.get(k)
        if isinstance(v, (list, tuple)):
            t[k] = [str(x or "").strip() for x in v][:n]
        t[k] = (t[k] + [""] * n)[:n]
    t["headline_colors"] = [c or DEFAULTS["headline_colors"][i] for i, c in enumerate(t["headline_colors"])]
    t["cards_on"] = bool(raw.get("cards_on", t["cards_on"]))
    t["cards"] = _norm_cards(raw.get("cards") if isinstance(raw.get("cards"), (list, tuple)) else [])
    for k, lo, hi, d in (("card_rot", -15.0, 15.0, 3.0), ("card_skew", 0.0, 0.12, 0.03), ("card_anim_dur", 0.1, 3.0, 0.5)):
        v = _num(raw.get(k))
        t[k] = d if v is None else max(lo, min(hi, v))
    t["chapters_on"] = bool(raw.get("chapters_on", t["chapters_on"]))
    t["chapter_anim"] = str(raw.get("chapter_anim") or t["chapter_anim"])
    try:
        t["chapter_anim_dur"] = max(0.05, float(raw.get("chapter_anim_dur", t["chapter_anim_dur"])))
    except (TypeError, ValueError):
        t["chapter_anim_dur"] = 0.35
    t["chapters"] = _norm_chapters(raw["chapters"] if isinstance(raw.get("chapters"), (list, tuple))
                                   else DEFAULTS["chapters"])
    if isinstance(raw.get("fonts"), dict):
        t["fonts"] = dict(raw["fonts"])
    from mt.templates.t3.layout import t3_layout_cfg          # T3-5 (lazy: layout.py imports this module)
    t["layout"] = t3_layout_cfg(raw.get("layout"))
    from mt.templates.t3.panels import t3_strip_cfg          # T3-6 (lazy: panels.py imports layout.py)
    t["strip"] = t3_strip_cfg(raw.get("strip"))
    from mt.templates.t3.panels import t3_panel_cfg          # T3-7
    t["panel"] = t3_panel_cfg(raw.get("panel"))
    from mt.templates.t3.layout import t3_split_cfg           # T3-9
    t["split"] = t3_split_cfg(raw.get("split"))
    from mt.templates.t3.slot import t3_slot_cfg             # T3-8 (lazy: slot.py imports panels.py)
    t["slot"] = t3_slot_cfg(raw.get("slot"))
    from mt.templates.t3.panels import t3_outro_cfg          # T3 outro (next-episode card; rides on the panel layout transition)
    t["outro"] = t3_outro_cfg(raw.get("outro"))
    if t["outro"]["on"]:
        t["layout"]["on"] = True
    return t


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _norm_chapters(lst):
    out = []
    for c in lst:
        if not isinstance(c, dict):
            continue
        out.append({"start": _num(c.get("start")), "trigger": str(c.get("trigger") or "").strip(),
                    "label": str(c.get("label") or "").strip(), "num": str(c.get("num") or "").strip(),
                    "anim": str(c.get("anim") or "").strip(), "anim_dur": _num(c.get("anim_dur")) or 0.0,
                    "end": _num(c.get("end"))})
    return out


def _norm_cards(lst):
    out = []
    for c in lst:
        if not isinstance(c, dict) or not c.get("media"):
            continue
        slot = int(_num(c.get("slot")) or 1)
        out.append({"media": str(c["media"]), "trigger": str(c.get("trigger") or "").strip(), "start": _num(c.get("start")),
                    "hold": max(0.3, _num(c.get("hold")) or 4.0), "slot": slot if slot in (1, 2, 3) else 1,
                    "label": str(c.get("label") or "").strip()})
    return out


def _P(name):
    return t2_rgb(PALETTE[name])


def _px(pts):
    return [(x * K, y * K) for x, y in pts]


def frame_at(video, t=1.0):
    """RGB PIL frame of `video` at t seconds (clamped to the clip: retries at 0). None if unreadable."""
    if not video or not os.path.isfile(str(video)) or not FFMPEG:
        return None
    import tempfile
    fd, png = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        for ss in (t, 0.0):
            r = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{ss:.2f}", "-i", str(video),
                                "-frames:v", "1", png], capture_output=True)
            if r.returncode == 0 and os.path.getsize(png) > 0:
                return Image.open(png).convert("RGB").copy()
        return None
    except Exception:
        return None
    finally:
        try:
            os.remove(png)
        except OSError:
            pass


def _paint_poly(base, pts, fill, opacity=1.0, ss=2):
    return t2_paint(base, t2_poly_mask(_px(pts), ss=ss), fill, opacity)


def _watermark(base, video, strength=0.15):
    """Blurred, desaturated, maroon-tinted face of the user's video in the top-right (poster x480-941, y0-300)."""
    fr = frame_at(video, 1.0)
    if fr is None:
        return False
    x0, y0, x1, y1 = [int(round(v * K)) for v in (480, 0, 941, 300)]
    w, h = x1 - x0, y1 - y0
    s = max(w / fr.width, h / fr.height)
    fr = fr.resize((max(w, int(fr.width * s)), max(h, int(fr.height * s))), Image.LANCZOS)
    l, tp = (fr.width - w) // 2, int((fr.height - h) * 0.25)          # faces sit in the upper part of the frame
    fr = fr.crop((l, tp, l + w, tp + h)).filter(ImageFilter.GaussianBlur(5)).convert("L")
    fr = ImageChops.multiply(Image.merge("RGB", [fr] * 3), Image.new("RGB", (w, h), _P("maroon"))).point(lambda v: min(255, int(v * 2.4)))
    fade = Image.linear_gradient("L").rotate(90).resize((w, h))          # left -> right: 0..255 mask (fade in toward the edge)
    vfade = Image.linear_gradient("L").resize((w, h)).point(lambda v: 255 - v)   # top -> bottom fade out
    a = ImageChops.multiply(ImageChops.multiply(fade.point(lambda v: min(255, v * 2)), vfade), Image.new("L", (w, h), int(255 * strength)))
    lay = fr.convert("RGBA")
    lay.putalpha(a)
    base.alpha_composite(lay, (x0, y0))
    return True


def _skyline(base, color, opacity=0.08):
    """Very faint city silhouette of rectangles (poster x540-941, y1480-1672), seeded -> deterministic."""
    rnd = random.Random(7)
    x, rects = 540.0, []
    while x < 941:
        w = rnd.uniform(14, 34)
        h = rnd.uniform(25, 150) * (1.0 - 0.35 * abs((x - 760) / 220.0))
        rects.append((x, 1672 - max(22, h), min(941, x + w), 1672))
        if rnd.random() < 0.3:
            rects.append(((x + w * 0.4), 1672 - h - rnd.uniform(14, 30), (x + w * 0.6), 1672 - h))   # antenna
        x += w + rnd.uniform(0, 4)

    def fn(d, L, s):
        for r in rects:
            a, b = L(r[0] * K, r[1] * K), L(r[2] * K, r[3] * K)
            d.rectangle((a[0], a[1], b[0], b[1]), fill=255)
    m = t2_draw_mask((540 * K, 1480 * K, 941 * K, 1672 * K), fn, ss=2)
    t2_paint(base, m, color, opacity)


def _bg(W, H, t3, video):
    base = Image.new("RGBA", (W, H))
    base.paste(t2_gradient((W, H), [(0, _P("dark0")), (1, _P("dark1"))], 90).convert("RGBA"), (0, 0))
    acc = t2_rgb(t3["accent"])
    mar, deep = _P("maroon"), _P("deep_maroon")
    # far-left and far-right maroon facets (diagonal polygons, deep over light)
    _paint_poly(base, [(0, 0), (300, 0), (0, 820)], deep)
    _paint_poly(base, [(0, 0), (190, 0), (0, 470)], mar)
    _paint_poly(base, [(0, 1215), (230, 1672), (0, 1672)], deep)
    _paint_poly(base, [(0, 1330), (120, 1672), (0, 1672)], mar)
    _paint_poly(base, [(941, 0), (941, 1180), (780, 0)], deep)
    _paint_poly(base, [(941, 330), (941, 1520), (700, 1672), (941, 1672)], mar, 0.9)
    _paint_poly(base, [(941, 760), (941, 1672), (820, 1672)], deep)
    _paint_poly(base, [(300, 0), (560, 0), (120, 1672), (0, 1672), (0, 820)], t2_mix(_P("dark1"), mar, 0.10), 0.55)  # soft diagonal sheen
    # paper patches
    for i, pts in enumerate(([(0, 0), (150, 0), (0, 150)], [(0, 955), (118, 955), (30, 1215), (0, 1215)],
                             [(0, 1672), (0, 1618), (92, 1672)])):
        m = t2_poly_mask(_px(pts), ss=2)
        t2_paint(base, m, lambda size, o, i=i: paper_texture(size, _P("paper"), seed=11 + i).convert("RGBA"), 0.92)
    # thin orange diagonal slash, top-right
    t2_paint(base, t2_line_mask([(884 * K, 168 * K), (938 * K, 74 * K)], 7 * K), acc)
    if t3["watermark"] and video:
        _watermark(base, video)
    _skyline(base, _P("cream"))
    return base.convert("RGB")


def _text_at(fg, text, role, x, top, max_w, cap_px, color, t3, tracking=0.0, right=None):
    """Ink-fitted text with its top at `top` (canvas px). Returns the painted bbox or None."""
    if not text:
        return None
    fp, sh = t3_font(role, text, t3.get("fonts"))
    m, _shown, _sz = t2_fit_text(text, fp, max_w, cap_px, tracking, sh)
    return t2_paint(fg, t2_place(m, x, y=top, right=right), color)


def _header(fg, t3):
    cream, acc = _P("cream"), t2_rgb(t3["accent"])
    boxes = {}
    n1, n2 = t3["name1"], t3["name2"]
    if n1 or n2:
        if n1:
            boxes["name1"] = _text_at(fg, n1, "serif", 88 * K, 52 * K, (298 - 88) * K, 40 * K, cream, t3)
        if n2:
            boxes["name2"] = _text_at(fg, n2, "serif", 88 * K, 112 * K, (322 - 88) * K, 40 * K, acc, t3)
        if n1:   # thin vertical cream line next to line 1
            t2_paint(fg, t2_line_mask([(307 * K, 38 * K), (307 * K, 105 * K)], 1.6 * K, caps=False), cream)
    for i, r in enumerate(t3["roles"]):
        if r:
            boxes[f"role{i + 1}"] = _text_at(fg, r, "light", 364 * K, (75 + i * 25) * K, (632 - 364) * K, 13 * K, cream, t3,
                                               tracking=0.03)
    if t3["tagline"]:
        fp, _ = t3_font("caps", t3["tagline"], t3.get("fonts"))
        boxes["tagline"] = draw_dotted_line(fg, t3["tagline"], fp, 640 * K, 880 * K, 106 * K, 9.5 * K, cream, acc,
                                            tracking_em=0.22, align="right")
    return boxes


def _footer(fg, t3):
    cream, acc = _P("cream"), t2_rgb(t3["accent"])
    boxes = {}
    if t3["footer"]:
        fp, _ = t3_font("caps", t3["footer"], t3.get("fonts"))
        boxes["footer"] = draw_dotted_line(fg, t3["footer"], fp, 38 * K, 355 * K, 1566 * K, 12.5 * K, cream, acc,
                                           tracking_em=0.22)
        t2_paint(fg, t2_line_mask([(375 * K, 1566 * K), (560 * K, 1566 * K)], 1.8 * K, caps=False), acc)
        boxes["footer_line"] = (int(375 * K), int(1566 * K - 2), int(560 * K), int(1566 * K + 2))
    sig = t3["signature"]
    if sig:
        fp, sh = t3_font("script", sig, t3.get("fonts"))
        bw, bh = (905 - 600) * K, (1620 - 1540) * K
        m, _s, _z = t2_fit_text(sig, fp, bw * 0.96, 40 * K, 0.0, sh)
        m = rotated_mask(m, 6)                                # -6 deg in poster terms: the line rises to the right
        if m.height > bh:
            m = m.resize((max(1, int(m.width * bh / m.height)), int(bh)), Image.LANCZOS)
        cx, cy = (600 + 905) / 2.0 * K, (1540 + 1620) / 2.0 * K
        boxes["signature"] = t2_paint(fg, t2_place(m, cx - m.width / 2.0, cy=cy), cream)
    return boxes


_CACHE = {}


def make_t3_static(W, H, cfg_t3, video, out_paths):
    """Draw the T3 plates: out_paths["bg"] (RGB png, under the video), out_paths["fg"] (RGBA png, over it).
    Returns {"boxes": {name: bbox}, "watermark": bool}. Cached per (size, cfg, video file)."""
    t3 = t3_cfg(cfg_t3)
    try:
        vst = (str(video), os.stat(video).st_mtime_ns) if video and os.path.isfile(str(video)) else None
    except OSError:
        vst = None
    _dyn = ("cards", "cards_on", "card_rot", "card_skew", "card_anim_dur", "chapters", "chapters_on", "chapter_anim",
            "chapter_anim_dur", "layout", "strip", "panel")                    # dynamic keys never change the static plate (and its paper grain is random)
    key = hashlib.md5(repr((W, H, sorted((k, repr(v)) for k, v in t3.items() if k not in _dyn), vst)).encode()).hexdigest()
    if key in _CACHE:
        for k in ("bg", "fg"):
            Path(out_paths[k]).write_bytes(_CACHE[key][k])
        return _CACHE[key]["info"]
    info = {"boxes": {}, "watermark": False}
    if t3["show_bg"]:
        bg = _bg(W, H, t3, video if t3["watermark"] else None)
        info["watermark"] = bool(t3["watermark"] and video and frame_at(video) is not None)
    else:
        bg = t2_gradient((W, H), [(0, _P("dark0")), (1, _P("dark1"))], 90).convert("RGB")
    fg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if t3["show_header"]:
        info["boxes"].update({k: v for k, v in _header(fg, t3).items() if v})
    if t3["show_footer"]:
        info["boxes"].update({k: v for k, v in _footer(fg, t3).items() if v})
    bg.save(out_paths["bg"])
    fg.save(out_paths["fg"], compress_level=1)
    _CACHE[key] = {"bg": Path(out_paths["bg"]).read_bytes(), "fg": Path(out_paths["fg"]).read_bytes(), "info": info}
    return info


def t3_build_static_layers(cfg, tmp):
    """Template 3 'build_background' hook: bg plate under the video, fg plate (cfg['_t2_fg'] - the pipeline's generic
    foreground slot, same as Template 2) over it."""
    cfg["t3"] = t3_cfg(cfg.get("t3"))
    _MSGS.clear()
    W, H = cfg["canvas"]
    paths = {"bg": os.path.join(tmp, "t3_bg.png"), "fg": os.path.join(tmp, "t3_fg.png")}
    info = make_t3_static(W, H, cfg["t3"], cfg.get("video"), paths)
    info = {"boxes": dict(info["boxes"]), "watermark": info["watermark"]}       # the cached dict stays untouched
    t3 = cfg["t3"]
    vb = dict(cfg.get("video_box") or {})
    if not vb or all(vb.get(k) == v for k, v in LEGACY_BOX.items()):       # T3-1 placeholder -> the poster box
        vb = dict(VIDEO_BOX)
    box = {k: int(vb.get(k, VIDEO_BOX[k])) for k in ("x", "y", "w", "h")}
    cfg["video_box"] = dict(box, mode=t3["video_fit"])
    bg, fg = Image.open(paths["bg"]).convert("RGB"), Image.open(paths["fg"]).convert("RGBA")
    lay, finfo = t3_frame_layer(W, H, bg, box, t3["frame_style"], t3["frame_skew"], t3["accent"])
    info["boxes"].update(t3_headline_layer(lay, t3))
    lay.alpha_composite(fg)                                   # header + footer stay on top of the frame layer
    lay.save(paths["fg"], compress_level=1)
    info["frame"] = finfo
    cfg["_t3_info"] = info
    cfg["background"] = {"type": "image", "path": paths["bg"]}
    cfg["_t2_fg"] = paths["fg"]
    cfg.pop("_t3_lay", None)
    if t3["layout"]["on"]:                                    # T3-5: adaptive layout replaces the single fixed plate
        from mt.templates.t3.layout import t3_layout_prepare
        t3_layout_prepare(cfg, tmp, bg, fg)


# ---- T3-2: video frame (skewed editorial cut-out) + headline column ---------------------------------------------------
_FRAC = [((x - _PB[0]) / float(_PB[2] - _PB[0]), (y - _PB[1]) / float(_PB[3] - _PB[1])) for x, y in POSTER_QUAD]


def _box4(box):
    if isinstance(box, dict):
        return float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
    x, y, w, h = box
    return float(x), float(y), float(w), float(h)


def t3_frame_quad(box, skew=1.0):
    """Corners [TL, TR, BR, BL] (float canvas px) of the video frame inside `box` = (x, y, w, h) or {x,y,w,h}.
    skew 1.0 / True = the poster's slightly skewed cut-out, 0 / False = straight rectangle; in between blends.
    The quad touches the box on every side (its bbox is the box), so every anchored element can follow any box."""
    x, y, w, h = _box4(box)
    k = 1.0 if skew is True else 0.0 if skew in (False, None) else float(skew)
    rect = [(0, 0), (1, 0), (1, 1), (0, 1)]
    return [(x + w * (r[0] + k * (f[0] - r[0])), y + h * (r[1] + k * (f[1] - r[1]))) for r, f in zip(rect, _FRAC)]


def t3_bracket_polygon(quad, box):
    """Orange L-shaped corner bracket at the quad's top-left (arms follow the quad's top and left edges)."""
    x, y, w, h = _box4(box)
    s = w / float(VIDEO_BOX["w"])                       # 1.0 for the poster box
    tl, tr, bl = quad[0], quad[1], quad[3]

    def unit(a, b):
        d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        return (b[0] - a[0]) / d, (b[1] - a[1]) / d
    u, v = unit(tl, tr), unit(tl, bl)
    t, lh, lv, off = 14.0 * s, 32 * K * s, 140 * K * s, 5 * K * s
    lh, lv = min(lh, w * 0.5), min(lv, h * 0.5)
    o = (tl[0] - (u[0] + v[0]) * off, tl[1] - (u[1] + v[1]) * off)

    def P(a, b):
        return (o[0] + u[0] * a + v[0] * b, o[1] + u[1] * a + v[1] * b)
    return [P(0, 0), P(lh, 0), P(lh, t), P(t, t), P(t, lv), P(0, lv)]


def _full(mask, W, H):
    m, (ox, oy) = mask
    f = Image.new("L", (W, H), 0)
    f.paste(m, (ox, oy))
    return f


def t3_frame_layer(W, H, bg_img, box, style="skewed", skew=1.0, accent="#F56D1F", full=False):
    """RGBA plate over the video: opaque copy of the design outside the quad (inside the box), soft shadow, cream border,
    orange bracket. The video (straight, in `box`) shows through the quad -> a polygon alpha-mask, no ffmpeg warp.
    Returns (layer, {"quad", "box", "bracket"})."""
    quad = t3_frame_quad(box, 0.0 if style == "straight" else skew)
    x, y, w, h = [int(round(v)) for v in _box4(box)]
    q = _full(t2_poly_mask(quad, ss=3), W, H)
    inv = q.point(lambda v: 255 - v)
    rect = Image.new("L", (W, H), 0)
    ImageDraw.Draw(rect).rectangle((0, 0, W, H) if full else (x, y, x + w - 1, y + h - 1), fill=255)   # full: opaque everywhere (T3-5)
    lay = bg_img.convert("RGBA")
    lay.putalpha(ImageChops.multiply(rect, inv))
    sh = ImageChops.offset(q, 5, 10).filter(ImageFilter.GaussianBlur(13)).point(lambda v: int(v * 0.62))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(ImageChops.multiply(sh, inv))
    lay.alpha_composite(shadow)
    ring = _full(t2_draw_mask((x - 8, y - 8, x + w + 8, y + h + 8), lambda d, L, s_: (
        d.polygon([L(*p) for p in quad], fill=255),
        d.line([L(*p) for p in quad + [quad[0]]], fill=255, width=int(6 * s_), joint="curve")), ss=3), W, H)
    ring = ImageChops.multiply(ring.point(lambda v: v), inv)
    t2_paint(lay, (ring, (0, 0)), _P("cream"))
    br = t3_bracket_polygon(quad, (x, y, w, h))
    bb = t2_paint(lay, t2_poly_mask(br, ss=3), t2_rgb(accent))
    return lay, {"quad": quad, "box": (x, y, w, h), "bracket": bb}


def _line_color(v, t3):
    v = (v or "").strip().lower()
    if v in ("", "cream"):
        return _P("cream")
    if v == "accent":
        return t2_rgb(t3["accent"])
    try:
        return t2_rgb(v)
    except Exception:
        return _P("cream")


def _fit_rotated(make_mask, box_w, box_h, deg):
    """make_mask(f) -> text mask at scale f. Shrinks f until the (rotated) ink fits box_w x box_h. Never overflows."""
    f, m = 1.0, None
    for _ in range(8):
        m = make_mask(f)
        r = rotated_mask(m, deg) if deg else m
        if r.width <= box_w and r.height <= box_h:
            return r
        f *= min(box_w / float(r.width), box_h / float(r.height)) * 0.98
        if f < 0.08:
            break
    r = rotated_mask(m, deg) if deg else m
    if r.width > box_w or r.height > box_h:       # last resort (absurd input): squash the mask itself
        k = min(box_w / float(r.width), box_h / float(r.height))
        r = r.resize((max(1, int(r.width * k)), max(1, int(r.height * k))), Image.LANCZOS)
    return r


HEAD_SLOTS = [  # (poster box x0, y0, x1, y1, cap px, rotation deg)
    ((545, 200, 918, 335), 112, 3.0), ((600, 335, 740, 410), 56, 0.0), ((583, 405, 905, 545), 120, 0.0)]
UNDERLINE = (555, 865, 550)            # x0, x1, y (poster px)
TAG_BOX = (620, 585, 790, 655)
TAG_ROT = 4.0


def t3_headline_layer(lay, t3):
    """Headline column + underline + tagline onto the RGBA plate `lay`. Returns {name: bbox} (canvas px)."""
    boxes = {}
    if not t3["show_headline"]:
        return boxes
    for i, ((bx, cap, deg), text) in enumerate(zip(HEAD_SLOTS, t3["headline"])):
        if not text:
            continue
        fp, sh = t3_font("head", text, t3.get("fonts"))
        size0 = t2_size_for_cap(fp, cap * K)
        w, h = (bx[2] - bx[0]) * K, (bx[3] - bx[1]) * K
        m = _fit_rotated(lambda f: t2_text_mask(text, fp, size0 * f, -0.01, sh), w, h, deg)
        mk = t2_place(m, bx[0] * K, cy=(bx[1] + bx[3]) / 2.0 * K)
        boxes[f"headline{i + 1}"] = t2_paint(lay, mk, _line_color(t3["headline_colors"][i], t3))
    if t3["headline_underline"] and any(t3["headline"]):
        x0, x1, yy = UNDERLINE
        boxes["underline"] = t2_paint(lay, t2_line_mask([(x0 * K, yy * K), (x1 * K, yy * K)], 3.2 * K, caps=False),
                                      t2_rgb(t3["accent"]))
    tl = [t.upper() for t in t3["tag_lines"] if t]
    if tl:
        fp, sh = t3_font("light", " ".join(tl), t3.get("fonts"))
        cap = 13.5 * K
        size0 = t2_size_for_cap(fp, cap)
        bx = TAG_BOX

        def block(f):
            ms = [t2_text_mask(t, fp, size0 * f, 0.3, 0.0) for t in tl]
            pitch = int(cap * f * 1.95)
            B = Image.new("L", (max(m.width for m in ms), pitch * (len(ms) - 1) + max(m.height for m in ms)), 0)
            for j, m in enumerate(ms):
                B.paste(m, (0, j * pitch))
            return B
        m = _fit_rotated(block, (bx[2] - bx[0]) * K, (bx[3] - bx[1]) * K, TAG_ROT)
        boxes["tag_lines"] = t2_paint(lay, t2_place(m, bx[0] * K, cy=(bx[1] + bx[3]) / 2.0 * K), _P("cream"), 0.8)
    return {k: v for k, v in boxes.items() if v}
