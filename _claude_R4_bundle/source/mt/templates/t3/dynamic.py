"""mt.templates.t3.dynamic - Template 3 "Editorial Orange": the DYNAMIC parts (T3-3): chapter tag + captions.
Everything is positioned RELATIVE TO THE CURRENT FRAME BOX (cfg["video_box"] / any box passed in), never in absolute
canvas px, because the frame moves and shrinks later (T3-5). Scale s = box w / poster-box w (1.0 for the poster box)."""
import math
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from mt.anim import anim_state
from mt.ask import ask_anim, ask_font
from mt.captions import (caption_streams, find_trigger, parse_srt, stream_groups, t2_caption_sprite,
                         t2_subline_sprite)
from mt.common import (AR_DIGITS, D, FFMPEG, IMAGE_EXTS, VIDEO_EXTS, _read_exact, ask, ask_choice, c_color, c_existing_file,
                       c_float, c_int, c_percent, c_time, yn)
from mt.draw import Item, draw_item, t2_paint, t2_poly_mask, t2_rgb, t2_size_for_cap, t2_text_mask
from mt.fonts import is_rtl_text, t2_font
from mt.render import _first_frame
from mt.templates.t3.static import t3_warn, K, VIDEO_BOX, _P, t3_cfg, t3_font, t3_frame_quad

# poster geometry (941x1672) of the pieces, relative to the poster frame bbox (22,182)-(627,955)
CAP_POSTER = {"cx_frac": ((68 + 592) / 2.0 - 22) / 605.0, "w_frac": (592 - 68) / 605.0,
              "bottom_frac": (937 - 182) / 773.0, "size_box": 42, "size_sub": 30, "min_w": 300}
TAG_POSTER = {"dx": 48 - 35, "dy": 240 - 210, "num_cap": 40, "label_cap": 11.5, "plate_alpha": 0.70}


_WIN = None                       # (t0, t1) set by layout.py while it builds one layout segment; None = everything


def _vis(st, en):
    return _WIN is None or (en > _WIN[0] and st < _WIN[1])


def t3_scale(box):
    """Frame scale vs the poster frame: 1.0 for VIDEO_BOX, smaller when the frame shrinks (clamped 0.25..2)."""
    w = box["w"] if isinstance(box, dict) else box[2]
    return max(0.25, min(2.0, float(w) / VIDEO_BOX["w"]))


def _b4(box):
    if isinstance(box, dict):
        return float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
    return tuple(float(v) for v in box)


# ---- chapter tag --------------------------------------------------------------------------------------------------
def t3_tag_origin(box, skew=1.0):
    """Top-left canvas px of the chapter tag: the quad's TL corner + the poster offset, scaled with the frame."""
    q = t3_frame_quad(box, skew)
    s = t3_scale(box)
    return q[0][0] + TAG_POSTER["dx"] * K * s, q[0][1] + TAG_POSTER["dy"] * K * s


def t3_chapter_sprite(num, label, accent="#F56D1F", scale=1.0, fonts=None, max_w=None):
    """Big accent heavy-italic number + cream '/', label in cream caps on a dark (70 % black) parallelogram plate.
    RGBA sprite; the label shrinks to `max_w` (never overflows)."""
    T, s = TAG_POSTER, float(scale)
    acc, cream = t2_rgb(accent), _P("cream")
    num, label = str(num or "").strip(), str(label or "").strip().upper()
    hf, hsh = t3_font("head", num or "0", fonts)
    cap = T["num_cap"] * K * s
    nm = t2_text_mask(num or " ", hf, t2_size_for_cap(hf, cap), -0.01, hsh)
    sl = t2_text_mask("/", hf, t2_size_for_cap(hf, cap), 0.0, hsh)
    gap = int(5 * s)
    row_w = nm.width + gap + sl.width
    H1 = max(nm.height, sl.height)
    lm, plate_w = None, 0
    pad_x, pad_y = int(14 * s), int(7 * s)
    if label:
        uf, _ = t3_font("caps", label, fonts)
        lm = t2_text_mask(label, uf, t2_size_for_cap(uf, T["label_cap"] * K * s), 0.14)
        lim = int(max_w) if max_w else int(10 ** 6)
        if lm.width > lim - 2 * pad_x:
            k = max(4, lim - 2 * pad_x) / float(lm.width)
            lm = lm.resize((max(1, int(lm.width * k)), max(1, int(lm.height * k))), Image.LANCZOS)
        plate_w = lm.width + 2 * pad_x + int(lm.height * 0.5)
    ph = (lm.height + 2 * pad_y) if lm else 0
    W = int(max(row_w, plate_w) + 8)
    Ht = int(H1 + (int(8 * s) + ph if lm else 0) + 8)
    img = Image.new("RGBA", (W, Ht), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, Ht), (0, 0, 0, 0))                       # soft shadow under the number (video may be bright)
    t2_paint(sh, (nm, (3, 3)), (0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(2.5 * s + 0.5)))
    t2_paint(img, (nm, (0, 0)), acc + (255,))
    t2_paint(img, (sl, (nm.width + gap, 0)), cream + (255,))
    if lm:
        y0 = H1 + int(8 * s)
        sk = ph * 0.28                                                   # slight skew -> parallelogram
        pts = [(sk, y0), (plate_w, y0), (plate_w - sk, y0 + ph), (0, y0 + ph)]
        t2_paint(img, t2_poly_mask(pts, ss=3), (0, 0, 0, int(255 * T["plate_alpha"])))
        t2_paint(img, (lm, (int(pad_x + sk * 0.5), int(y0 + pad_y))), cream + (255,))
    return img


def t3_resolve_chapters(cfg, duration):
    """-> [{"start","end","num","label","anim","dur"}] sorted by start. start = SRT trigger phrase (find_trigger, tries every
    stream) else the fixed time; auto number 01, 02, ...; a chapter ends when the next one starts (+ transition time)."""
    t3 = t3_cfg(cfg.get("t3"))
    if not t3["chapters_on"] or not t3["chapters"]:
        return []
    cues_all = []
    for c in caption_streams(cfg):
        try:
            cues_all.append(parse_srt(c["srt"]))
        except Exception:
            pass
    found = []
    for ch in t3["chapters"]:
        st = None
        if ch["trigger"]:
            for cues in cues_all:
                st = find_trigger(cues, ch["trigger"])
                if st is not None:
                    break
        if st is None:
            st = ch["start"]
        if st is None:
            t3_warn(f"   [!] chapter '{ch['label'] or ch['num']}': trigger '{ch['trigger']}' not found and no start time - skipped.")
            continue
        found.append((float(st), ch))
    found.sort(key=lambda a: a[0])
    out = []
    for i, (st, ch) in enumerate(found):
        d = ch["anim_dur"] if ch["anim_dur"] else t3["chapter_anim_dur"]
        out.append({"start": st, "num": ch["num"] or "%02d" % (i + 1), "label": ch["label"],
                    "anim": ch["anim"] or t3["chapter_anim"], "dur": max(0.05, float(d)), "end": ch["end"]})
    for i, c in enumerate(out):
        nxt = out[i + 1]["start"] + out[i + 1]["dur"] if i + 1 < len(out) else duration + 1
        c["end"] = max(c["start"] + 0.2, min(c["end"], nxt) if c["end"] else nxt)
    return out


def t3_chapter_items(cfg, duration, box=None):
    t3 = t3_cfg(cfg.get("t3"))
    box = box or cfg.get("video_box") or VIDEO_BOX
    bx, by, bw, bh = _b4(box)
    s = t3_scale(box)
    x, y = t3_tag_origin(box, 0.0 if t3["frame_style"] == "straight" else t3["frame_skew"])
    items = []
    for c in t3_resolve_chapters(cfg, duration):
        if c["start"] >= duration or not _vis(c["start"], c["end"]):
            continue
        spr = t3_chapter_sprite(c["num"], c["label"], t3["accent"], s, t3.get("fonts"), max_w=bw * 0.62)
        items.append(Item(spr, c["start"], c["end"], x + spr.width / 2.0, y + spr.height / 2.0, c["anim"], c["dur"],
                          out=True))
    return items


# ---- captions -----------------------------------------------------------------------------------------------------
def t3_caption_layout(box, streams=(), skew=1.0):
    """Caption geometry for ANY frame box: {"cx", "max_w", "box_bottom", "sub_bottom", "sub_h", "frame", "scale"}.
    Poster values are fractions of the frame, so the captions follow the frame when it moves / shrinks."""
    x, y, w, h = _b4(box)
    s = t3_scale(box)
    sub = [c for c in streams if c.get("t3_style") == "sub"]
    sub_h = int(max([(c.get("size") or CAP_POSTER["size_sub"]) * s for c in sub] or [0]) * 1.75)
    bottom = y + h * CAP_POSTER["bottom_frac"]
    return {"cx": x + w * CAP_POSTER["cx_frac"], "max_w": int(w * CAP_POSTER["w_frac"]), "sub_h": sub_h,
            "sub_bottom": bottom, "box_bottom": bottom - (sub_h + 6 * s if sub_h else 0),
            "frame": (x, y, x + w, y + h), "scale": s}


def t3_caption_sprite(tokens, font_path, size, color="#ffffff", hl="#F56D1F", accent="#F56D1F", max_w=520, scale=1.0,
                      stroke_w=0, stroke_fill="#000000", want_meta=False):
    """Arabic caption box (70 % black rounded box, accent bar on its left, heavy text, keywords in the accent, max 2 lines,
    auto size / shrink). Reuses the Template 2 sprite. `size` and min width scale with the frame."""
    return t2_caption_sprite(tokens, font_path, max(12, size * scale), color, hl, accent, int(max_w),
                             min_w=int(min(max_w, CAP_POSTER["min_w"] * scale)), stroke_w=stroke_w,
                             stroke_fill=stroke_fill, want_meta=want_meta)


def t3_caption_items(cfg, c, groups, duration, box=None):
    t3 = t3_cfg(cfg.get("t3"))
    box = box or cfg.get("video_box") or VIDEO_BOX
    streams = caption_streams(cfg)
    lay = t3_caption_layout(box, streams)
    s, role = lay["scale"], c.get("t3_style")
    font = c.get("font") if c.get("font") and os.path.isfile(str(c.get("font"))) else t2_font("arabic", "ع")[0]
    hl = c.get("hl_color") or t3["accent"]
    size = c.get("size") or (CAP_POSTER["size_box"] if role == "box" else CAP_POSTER["size_sub"])
    fr, yp, items = lay["frame"], c.get("y_pct"), []
    for st, en, toks in groups:
        if st >= duration or not _vis(st, en):
            continue
        toks = [list(t) for t in toks]
        if role == "box":
            spr = t3_caption_sprite(toks, font, size, c.get("color", "#ffffff"), hl, t3["accent"], lay["max_w"], s,
                                    c.get("stroke_w", 0), c.get("stroke_color", "#000000"))
            cy = lay["box_bottom"] - spr.height / 2.0 if yp in (None, "") else fr[1] + (fr[3] - fr[1]) * float(yp) / 100.0
        else:
            spr = t2_subline_sprite(toks, font, max(10, size * s), c.get("color", "#ffffff"), hl, lay["max_w"],
                                    c.get("stroke_w", 0), min_size=max(10, int(20 * s)))
            cy = lay["sub_bottom"] - spr.height / 2.0 if yp in (None, "") else fr[1] + (fr[3] - fr[1]) * float(yp) / 100.0
        items.append(Item(spr, st, en, lay["cx"], cy, c.get("anim", "fade"), c.get("anim_dur", 0.2), out=False,
                          rtl=is_rtl_text(" ".join(t[0] for t in toks))))
    return items


def t3_dynamic_items(cfg, duration, box=None):
    """All Template 3 timeline items for the current frame box: chapter tags, every t3 caption stream, cards (on top)."""
    items = t3_chapter_items(cfg, duration, box)
    for c in caption_streams(cfg):
        if c.get("t3_style") in ("box", "sub"):
            items += t3_caption_items(cfg, c, stream_groups(parse_srt(c["srt"]), c), duration, box)
    items += t3_card_items(cfg, duration, box, with_video=bool(cfg.get("_t2_still")))
    from mt.templates.t3.panels import outro_items, panel_items, strip_items    # T3-6 photo tiles / T3-7 checklist rows / outro card (only when layout is on)
    from mt.templates.t3.layout import t3_split_clip                # T3-9: bands are hidden while the split is on
    return items + t3_split_clip(cfg, strip_items(cfg, duration, box) + panel_items(cfg, duration, box)
                                 + outro_items(cfg, duration), duration)


# ---- questions ----------------------------------------------------------------------------------------------------
def t3_caption_style(idx, srt_path):
    """Questions for one Template 3 caption stream: stream 1 = the Arabic box, further streams = the small line below it."""
    role = "box" if idx == 0 else "sub"
    print(f"\n--- Caption style for SRT #{idx + 1}: {Path(srt_path).name}  "
          f"({'dark box with orange bar' if role == 'box' else 'small line under the box'}) ---")
    k = "t3cap" + str(idx)
    if not (D.get("cap_font" + k) and os.path.isfile(D.get("cap_font" + k))):
        D["cap_font" + k] = t2_font("arabic", "ع")[0] or ""
    c = {"srt": srt_path, "t3_style": role, "ref": "box"}
    c["font"] = ask_font("Caption font (Cairo ExtraBold recommended)", "cap_font" + k)
    c["size"] = ask("Caption font size (px, at poster frame size)",
                    default=CAP_POSTER["size_box"] if role == "box" else CAP_POSTER["size_sub"], key="t3_cap_size" + str(idx),
                    cast=c_int)
    c["color"] = ask("Text color", default="white", key="t3_cap_color" + str(idx), cast=c_color)
    c["hl_color"] = ask("Highlight color (Enter = the template accent / orange)", allow_empty=True, cast=c_color) or ""
    c["keywords"] = ask("Words to highlight automatically, comma separated "
                        "(Enter = none; you can also put *stars* around words inside the SRT)", allow_empty=True) or ""
    c["stroke_color"], c["stroke_w"], c["shadow"] = "#000000", 0, role == "sub"
    mode = ask_choice("Show captions as:", ["Word by word", "Whole phrases (auto grouped)"], default=2,
                      key="t3_cap_mode" + str(idx))
    c["mode"] = "words" if mode == 1 else "phrase"
    if mode == 1:
        c["words_per_group"] = ask("Words shown at the same time (1 = word by word)", default=1,
                                   key="t3_cap_wpg" + str(idx), cast=c_int)
    else:
        c["max_words"] = ask("Max words per phrase (only used when the SRT is word-by-word)", default=8,
                             key="t3_cap_maxw" + str(idx), cast=c_int)
    c["y_pct"] = ask("Vertical position override (% from the top of the frame, Enter = poster position)",
                     allow_empty=True, cast=c_percent)
    c["anim"] = ask_anim("Caption animation", default="pop" if mode == 1 else "fade", key="t3_cap_anim" + str(idx))
    c["anim_dur"] = ask("Animation duration (seconds)", default=0.12 if mode == 1 else 0.25,
                        key="t3_cap_adur" + str(idx), cast=c_float)
    return c


def _c_start(s):
    """'3.5' / '1:05' -> ('t', seconds); anything else -> ('p', phrase)."""
    s = s.strip()
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return "t", int(m) * 60 + float(sec)
        return "t", float(s)
    except ValueError:
        if not s:
            raise ValueError("give a time (seconds or mm:ss) or a phrase")
        return "p", s


def t3_ask_chapters():
    """Chapter-tag questions (poster default = '01 INTRODUCTION' from the start). Returns the t3 keys to merge."""
    on = yn("Show chapter tags (like '01 / INTRODUCTION' at the top-left inside the frame)?",
            default=D.get("t3_chapters", "y") == "y")
    D["t3_chapters"] = "y" if on else "n"
    if not on:
        return {"chapters_on": False}
    chapters, i = [], 1
    print("   For each chapter: its label, then WHEN it starts - a time (seconds or mm:ss) or a spoken phrase from the SRT.")
    while i <= 12:
        label = ask(f"Chapter {i} label (Enter = {'the poster label' if i == 1 else 'no more chapters'}, '-' = none)",
                    default="INTRODUCTION" if i == 1 else "", key=f"t3_chapter{i}" if i == 1 else None,
                    allow_empty=True, cast=lambda v: "" if v.strip() == "-" else v.strip()) if i == 1 else \
            ask(f"Chapter {i} label (Enter = no more chapters)", allow_empty=True)
        if not label:
            break
        kind, val = ask(f"Chapter {i} starts at (seconds / mm:ss / spoken phrase)", default="0" if i == 1 else None,
                        cast=_c_start)
        chapters.append({"start": val if kind == "t" else None, "trigger": val if kind == "p" else "", "label": label})
        i += 1
    out = {"chapters_on": bool(chapters), "chapters": chapters}
    if chapters:
        out["chapter_anim"] = ask_anim("Chapter change animation", default="slide_up", key="t3_chapter_anim")
        out["chapter_anim_dur"] = ask("Chapter animation duration (seconds)", default=0.35, key="t3_chapter_dur",
                                      cast=c_float)
    return out


# ---- floating photo card (T3-4) -----------------------------------------------------------------------------------
# Poster card (612,640)-(915,945) = 303x305 poster px, thick cream border, pinned-photo tilt + a little skew/taper, soft shadow,
# orange bar on the outer right edge (poster x 905-918, y 760-890). It overlaps the frame's bottom-right corner.
CARD = {"w": 303, "h": 305, "border": 10, "bar_in": 10, "bar_out": 3, "bar_y0": 120, "bar_y1": 250,
        "dx": 136.5, "dy": -147.5, "dx3": 118.0, "shadow_dx": 4, "shadow_dy": 9, "shadow_blur": 8, "shadow_alpha": 0.58,
        "cream": (244, 241, 232)}
_CARD_CACHE = {}
SS = 2                                                                      # supersampling of the card plates


def _card_dims(scale):
    return CARD["w"] * K * scale, CARD["h"] * K * scale                    # 1x px (float)


def t3_anchor(slot, box, skew=1.0, canvas=(1080, 1920)):
    """Centre (cx, cy) of floating-card slot 1 (bottom-right of the frame, poster) / 2 (bottom-left) / 3 (right-middle),
    computed from the frame quad of `box` (x, y, w, h | dict) so the card follows the frame; clamped to stay on the canvas."""
    q = t3_frame_quad(box, skew)
    s = t3_scale(box)
    W, H = canvas
    if slot == 2:
        cx, cy = q[3][0] - CARD["dx"] * K * s, q[3][1] + CARD["dy"] * K * s
    elif slot == 3:
        cx, cy = (q[1][0] + q[2][0]) / 2.0 + CARD["dx3"] * K * s, (q[1][1] + q[2][1]) / 2.0
    else:
        cx, cy = q[2][0] + CARD["dx"] * K * s, q[2][1] + CARD["dy"] * K * s
    cw, ch = _card_dims(s)
    hw, hh = cw * 0.55 + 4, ch * 0.55 + 4
    return max(hw, min(W - hw, cx)), max(hh, min(H - hh, cy))


def _card_warp_pts(scale, angle, skew, rect, SSx=1):
    """Corners (relative to the card centre, px at SSx) of `rect` = (w, h) after taper + shear + tilt (ccw degrees)."""
    w, h = rect
    th = math.radians(angle)
    out = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x, y = sx * w / 2.0, sy * h / 2.0
        y *= 1.0 - skew * (x / w)                       # perspective-like taper (right edge a little shorter)
        x += skew * 0.5 * y                              # slight shear
        out.append((x * math.cos(th) + y * math.sin(th), -x * math.sin(th) + y * math.cos(th)))
    return out


def t3_card_quad(center, scale=1.0, angle=3.0, skew=0.03):
    """The card BODY polygon (4 corners, canvas px) for a card centred at `center` - used to place / test the card."""
    cw, ch = _card_dims(scale)
    return [(center[0] + x, center[1] + y) for x, y in _card_warp_pts(scale, angle, skew, (cw, ch))]


def _persp_coeffs(dst, src):
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -x * u, -y * u]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -x * v, -y * v]); B.append(v)
    n = len(B)                                   # pure-Python Gauss-Jordan (T3 does not need numpy)
    M = [list(map(float, A[i])) + [float(B[i])] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            raise ValueError("floating card: degenerate card shape")
        M[c], M[piv] = M[piv], M[c]
        M[c] = [v / M[c][c] for v in M[c]]
        for r in range(n):
            if r != c and M[r][c]:
                f = M[r][c]
                M[r] = [a - f * b for a, b in zip(M[r], M[c])]
    return [M[i][n] for i in range(n)]


def _card_static(scale, angle, skew, accent, label, fonts):
    key = (round(scale, 3), round(angle, 3), round(skew, 4), accent, label, str(fonts))
    if key in _CARD_CACHE:
        return _CARD_CACHE[key]
    S = SS
    cw, ch = int(round(CARD["w"] * K * scale * S)), int(round(CARD["h"] * K * scale * S))
    b = max(2, int(round(CARD["border"] * scale * S)))
    pad = int(round(8 * scale * S)) + 2
    Fw, Fh = cw + 2 * pad, ch + 2 * pad
    under = Image.new("RGBA", (Fw, Fh), (0, 0, 0, 0))
    ImageDraw.Draw(under).rounded_rectangle((pad, pad, pad + cw - 1, pad + ch - 1), radius=int(5 * scale * S),
                                            fill=CARD["cream"] + (255,))
    wmask = Image.new("L", (Fw, Fh), 0)
    ImageDraw.Draw(wmask).rectangle((pad + b, pad + b, pad + cw - b - 1, pad + ch - b - 1), fill=255)
    over = Image.new("RGBA", (Fw, Fh), (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    bx1 = pad + cw + int(CARD["bar_out"] * K * scale * S)
    bx0 = pad + cw - int(CARD["bar_in"] * K * scale * S)
    od.rectangle((bx0, pad + int(CARD["bar_y0"] * K * scale * S), bx1, pad + int(CARD["bar_y1"] * K * scale * S)),
                 fill=t2_rgb(accent) + (255,))
    if label:
        uf, _ = t3_font("caps", label, fonts)
        lm = t2_text_mask(label.upper(), uf, t2_size_for_cap(uf, 10 * K * scale * S), 0.14)
        sh_, sw_ = lm.height + int(14 * scale * S), min(cw - 2 * b, lm.width + int(28 * scale * S))
        if lm.width > sw_ - int(20 * scale * S):
            k = (sw_ - int(20 * scale * S)) / float(lm.width)
            lm = lm.resize((max(1, int(lm.width * k)), max(1, int(lm.height * k))), Image.LANCZOS)
        y1 = pad + ch - b - int(10 * scale * S)
        od.rectangle((pad + b, y1 - sh_, pad + b + sw_, y1), fill=(8, 10, 12, 215))
        t2_paint(over, (lm, (pad + b + int(14 * scale * S), y1 - sh_ + int(7 * scale * S))), _P("cream") + (255,))
    pts = _card_warp_pts(scale, angle, skew, (Fw, Fh))
    marg = int(round(34 * scale * S))
    wd = int(math.ceil(max(p[0] for p in pts) - min(p[0] for p in pts))) + 2 * marg
    hd = int(math.ceil(max(p[1] for p in pts) - min(p[1] for p in pts))) + 2 * marg
    wd, hd = wd + wd % 2, hd + hd % 2
    dst = [(wd / 2.0 + x, hd / 2.0 + y) for x, y in pts]
    src = [(0, 0), (Fw, 0), (Fw, Fh), (0, Fh)]
    co = _persp_coeffs(dst, src)

    def warp(im):
        return im.transform((wd, hd), Image.PERSPECTIVE, co, Image.BICUBIC)
    U, O, M = warp(under), warp(over), warp(wmask)
    sh = ImageChops.offset(U.getchannel("A"), int(CARD["shadow_dx"] * scale * S), int(CARD["shadow_dy"] * scale * S))
    sh = sh.filter(ImageFilter.GaussianBlur(CARD["shadow_blur"] * scale * S)).point(lambda v: int(v * CARD["shadow_alpha"]))
    base = Image.new("RGBA", (wd, hd), (0, 0, 0, 0))
    base.putalpha(sh)
    base.alpha_composite(U)
    st = {"U": base, "O": O, "M": M, "co": co, "flat": (Fw, Fh), "win": (pad + b, pad + b, cw - 2 * b, ch - 2 * b),
          "size": (wd, hd), "S": S}
    _CARD_CACHE[key] = st
    return st


def t3_card_sprite(media, scale=1.0, angle=3.0, skew=0.03, accent="#F56D1F", label="", fonts=None):
    """RGBA card sprite (1x), centred on the card centre: cream border, media in the window (cover-fit), orange bar on the
    right edge, optional label chip, perspective tilt + soft shadow. media = PIL image or None (neutral placeholder)."""
    st = _card_static(scale, angle, skew, accent, label, fonts)
    x, y, ww, wh = st["win"]
    if media is None:
        media = Image.new("RGB", (ww, wh), (46, 52, 60))
    media = media.convert("RGB")
    k = max(ww / float(media.width), wh / float(media.height))
    nw, nh = max(ww, int(math.ceil(media.width * k))), max(wh, int(math.ceil(media.height * k)))
    media = media.resize((nw, nh), Image.LANCZOS if k < 1 else Image.BICUBIC)
    l, t = (nw - ww) // 2, (nh - wh) // 2
    media = media.crop((l, t, l + ww, t + wh))
    flat = Image.new("RGBA", st["flat"], (0, 0, 0, 0))
    flat.paste(media.convert("RGBA"), (x, y))
    m = flat.transform(st["size"], Image.PERSPECTIVE, st["co"], Image.BICUBIC)
    m.putalpha(ImageChops.multiply(m.getchannel("A"), st["M"]))
    out = st["U"].copy()
    out.alpha_composite(m)
    out.alpha_composite(st["O"])
    return out.resize((st["size"][0] // 2, st["size"][1] // 2), Image.LANCZOS)


def t3_resolve_cards(cfg, duration, box=None):
    """Cards -> [{..keys.., "start","end","kind","angle","cx","cy","anim","dur"}] sorted by start. start = SRT trigger phrase
    (find_trigger) else the fixed time; end = start + hold, or the next card in the SAME slot starts + 0.25 s (smooth replace)."""
    t3 = t3_cfg(cfg.get("t3"))
    if not t3["cards_on"] or not t3["cards"]:
        return []
    box = box or cfg.get("video_box") or VIDEO_BOX
    cues_all = []
    for c in caption_streams(cfg):
        try:
            cues_all.append(parse_srt(c["srt"]))
        except Exception:
            pass
    rows = []
    for cd in t3["cards"]:
        if not os.path.isfile(cd["media"]):
            t3_warn(f"   [!] floating card: file not found, skipped: {cd['media']}")
            continue
        st = None
        if cd["trigger"]:
            for cues in cues_all:
                st = find_trigger(cues, cd["trigger"])
                if st is not None:
                    break
        if st is None:
            st = cd["start"]
        if st is None:
            t3_warn(f"   [!] floating card '{cd['label'] or Path(cd['media']).name}': phrase '{cd['trigger']}' not found "
                  f"and no start time - skipped.")
            continue
        r = dict(cd)
        r["start"], r["end"] = float(st), float(st) + cd["hold"]
        rows.append(r)
    rows.sort(key=lambda r: r["start"])
    for i, r in enumerate(rows):
        for o in rows[i + 1:]:
            if o["slot"] == r["slot"] and o["start"] > r["start"]:
                r["end"] = min(r["end"], o["start"] + 0.25)
                break
    out = []
    skew = 0.0 if t3["frame_style"] == "straight" else t3["frame_skew"]
    for r in rows:
        if r["start"] >= duration:
            continue
        r["end"] = min(r["end"], duration + 1)
        r["kind"] = "video" if r["media"].lower().endswith(VIDEO_EXTS) else "image"
        r["angle"] = -t3["card_rot"] if r["slot"] == 2 else t3["card_rot"]
        r["cx"], r["cy"] = t3_anchor(r["slot"], box, skew, tuple(cfg.get("canvas") or (1080, 1920)))
        r["anim"] = "card_l" if r["slot"] == 2 else "card_r"
        r["dur"] = t3["card_anim_dur"]
        r["scale"], r["skew"] = t3_scale(box), t3["card_skew"]
        out.append(r)
    return out


def _card_sprite_for(cfg, r, media):
    t3 = t3_cfg(cfg.get("t3"))
    return t3_card_sprite(media, r["scale"], r["angle"], r["skew"], t3["accent"], r["label"], t3.get("fonts"))


def t3_card_items(cfg, duration, box=None, with_video=False):
    """Timeline Items of the cards (drawn above the foreground plate, never clipped by the video window). Image cards always;
    video cards only when with_video (the --still preview shows their first frame; a real render bakes them into video layers)."""
    items = []
    for r in t3_resolve_cards(cfg, duration, box):
        if (r["kind"] == "video" and not with_video) or not _vis(r["start"], r["end"]):
            continue
        try:
            media = _first_frame(r["media"]) if r["kind"] == "video" else Image.open(r["media"])
            if media is not None and r["kind"] != "video":
                media.load()
        except Exception as e:
            t3_warn(f"   [!] floating card media unreadable ({e}): {r['media']}")
            media = None
        items.append(Item(_card_sprite_for(cfg, r, media), r["start"], r["end"], r["cx"], r["cy"], r["anim"], r["dur"], out=True))
    return items


def t3_prepare_card_layers(cfg, info, tmpdir):
    """Video cards -> video layers (same mechanism as T2 / b-roll): per card an alpha clip (qtrle) is baked - the media clip is
    looped + muted, every frame goes through the same sprite builder + animation code as image cards - and overlaid by FFmpeg at
    a fixed position above the foreground plate (area "canvas", key "_xy"), so it is never clipped by the video window."""
    W, H = cfg["canvas"]
    fps = info["fps"]
    fps_f = float(fps)
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    dur_eff = info["duration"]
    if cfg.get("preview"):
        dur_eff = min(dur_eff, float(cfg["preview"]))
    layers = []
    for n, r in enumerate(x for x in t3_resolve_cards(cfg, info["duration"]) if x["kind"] == "video"):
        if r["start"] >= dur_eff:
            continue
        ref = _card_sprite_for(cfg, r, None)
        slide, back = int(0.21 * W) + 6, int(0.015 * W) + 12
        extra = int(ref.width * 0.2) + 8
        dirn = -1 if r["anim"] == "card_l" else 1
        x0 = int(round(r["cx"] - ref.width / 2.0)) - (back if dirn > 0 else slide)
        x1 = int(round(r["cx"] + ref.width / 2.0)) + (slide if dirn > 0 else back)
        y0, y1 = int(round(r["cy"] - ref.height / 2.0)) - extra, int(round(r["cy"] + ref.height / 2.0)) + extra
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if (x1 - x0) % 2:
            x1, x0 = (x1 + 1, x0) if x1 < W else (x1, x0 - 1)
        if (y1 - y0) % 2:
            y1, y0 = (y1 + 1, y0) if y1 < H else (y1, y0 - 1)
        Wp, Hp = x1 - x0, y1 - y0
        lcx, lcy = r["cx"] - x0, r["cy"] - y0
        s, e_true = r["start"], r["end"]
        e = min(e_true, dur_eff)
        nfr = max(1, int(math.ceil((e - s) * fps_f)))
        st = _card_static(r["scale"], r["angle"], r["skew"], t3_cfg(cfg.get("t3"))["accent"], r["label"], t3_cfg(cfg.get("t3")).get("fonts"))
        ww, wh = st["win"][2] // 2, st["win"][3] // 2
        out = os.path.join(tmpdir, f"t3card{n}.mov")
        rd = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", r["media"],
                               "-an", "-vf", f"fps={fps_s},scale={ww}:{wh}:force_original_aspect_ratio=increase,"
                                             f"crop={ww}:{wh},format=rgb24",
                               "-frames:v", str(nfr), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        wr = subprocess.Popen([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                               "-video_size", f"{Wp}x{Hp}", "-framerate", fps_s, "-i", "pipe:0",
                               "-c:v", "qtrle", "-pix_fmt", "argb", out],
                              stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        print(f"Preparing floating card {n + 1} ({Path(r['media']).name}, {nfr} frames)...")
        last = None
        try:
            for i in range(nfr):
                raw = _read_exact(rd.stdout, ww * wh * 3)
                frame = Image.frombytes("RGB", (ww, wh), raw) if len(raw) == ww * wh * 3 else last
                last = frame
                it = Item(_card_sprite_for(cfg, r, frame), s, e_true, lcx, lcy, r["anim"], r["dur"], True)
                canvas = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
                draw_item(canvas, it, anim_state(it.anim, it.progress(s + i / fps_f), W, H))
                wr.stdin.write(canvas.tobytes())
            wr.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        finally:
            rd.kill()
            rd.wait()
        err = wr.stderr.read().decode("utf-8", "replace")
        if wr.wait() != 0 or not os.path.isfile(out):
            raise SystemExit("[!] Could not prepare the floating card:\n" + err[-800:])
        layers.append({"path": out, "start": s, "end": e, "area": "canvas", "mode": "fit", "fade": 0.0, "_xy": [x0, y0]})
    return layers


def t3_ask_cards_cfg(cues):
    """Floating photo-card questions (Template 3 wording). Returns the t3 keys to merge ({} = none):
    {"cards": [...], "cards_on": True, "card_rot": deg, "card_anim_dur": s}."""
    if not yn("\nAdd floating photo cards (a tilted photo / short video card pinned on the corner of the frame)?",
              default=D.get("t3_cards_ask", "n") == "y"):
        D["t3_cards_ask"] = "n"
        return {}
    D["t3_cards_ask"] = "y"
    cards = []
    while len(cards) < 12:
        print(f"\n--- Floating card #{len(cards) + 1} ---")
        e = {}
        e["media"] = ask("Card picture or short video (PNG/JPG/MP4...; a video loops, muted)",
                         cast=c_existing_file(IMAGE_EXTS + VIDEO_EXTS))
        e["label"] = ask("Small label on the card, e.g. DEVELOPMENT  (Enter = none)", allow_empty=True,
                         cast=lambda s: s.strip().replace("\\n", " ")) or ""
        print("   1=bottom-right of the frame (poster)  2=bottom-left  3=right-middle")
        e["slot"] = ask("Position", default="1", key="t3_card_slot",
                        cast=lambda s: int(s.translate(AR_DIGITS)) if s.strip().translate(AR_DIGITS) in ("1", "2", "3")
                        else (_ for _ in ()).throw(ValueError("choose 1-3")))
        e["start"], e["trigger"] = None, ""
        while True:
            raw = ask("Appears when this word/phrase is said (from the SRT)  -or-  a time in seconds")
            try:
                e["start"] = round(c_time(raw), 3)
                break
            except ValueError:
                pass
            t = find_trigger(cues, raw) if cues else None
            if t is None:
                print("   [!] that word was not found in the SRT. Try another word, or type a time.")
                continue
            e["trigger"], e["start"] = raw.strip(), round(t, 3)
            print(f"   -> found at {t:.2f}s")
            break
        e["hold"] = ask("How long it stays (seconds)", default=4, key="t3_card_hold", cast=c_float)
        cards.append(e)
        if not yn("Add another floating card?", default=True):
            break
    rot = ask("Card tilt in degrees (poster = 3)", default=3, key="t3_card_rot", cast=c_float)
    adur = ask("Card slide-in time (seconds)", default=0.5, key="t3_card_adur", cast=c_float)
    return {"cards": cards, "cards_on": True, "card_rot": rot, "card_anim_dur": adur}
