"""mt.templates.t4.cards_art - Template 4: the drawing half of the 'cards' module (refs R2 right card, R8 PiP card + label).
One IMAGE card = the picture cut to a chamfered rectangle, a neon border (glow + band + bright core) around it, two small bright accent dashes
inside the top-left corner and - optionally - a LABEL TAG overlapping one corner of the card: dark glass slanted panel, bold slanted capitals
(line 1 white, line 2 in the card colour), three slanted stripes tucked behind the panel's outer end (R8: LIVE CODING / DEVELOPMENT).
Everything is composed into ONE RGBA sprite (glow margins included, cropped to its ink); nothing is drawn per frame.
Public: t4_load_media(path), t4_split_label(text), t4_label_sprite(lines, color, font, size, left), t4_card_sprite(media, label, cw, ch, color, font)
-> (sprite, msg|None); sprite.info['card'] = (x0, y0, x1, y1) = the picture rectangle inside the sprite."""
import math
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps

from mt.common import FFMPEG, VIDEO_EXTS
from mt.draw import _t2_alpha_paste, t2_lighten, t2_line_mask, t2_paint, t2_poly_mask, t2_rgb, t2_text_mask
from mt.fonts import has_arabic
from mt.templates.t4.kit import _glass_sprite, chamfer_rect, hazard_stripes, kit_paste, neon_stroke

ASPECT_MIN, ASPECT_MAX = 0.75, 1.8          # picture width / height limits (outside: centre-cropped to the limit)
LABEL_FRAC = 0.082                          # label font size = this x card width (R8: ~0.08)
LABEL_SHEAR = 0.20                          # fake italic of the label capitals
SHORT_LABEL = 11                            # labels up to this many characters stay on ONE line
LABEL_TINT = (6, 14, 36, 240)               # label glass: nearly opaque (R8) so the picture does not show through the text
OVERHANG = 0.38                             # share of the label height that sticks out of the card edge (R8: ~0.4)
_WHITE = (255, 255, 255)


# ---- media ------------------------------------------------------------------------------------------------------------------
def t4_load_media(path):
    """-> (RGB image | None, warning | None). Missing / unreadable file -> None + a one-line message; video files are P13 (not yet)."""
    name = Path(str(path)).name if path else ""
    if not path or not os.path.isfile(str(path)):
        return None, "cards: image '%s' is missing - gray placeholder." % (name or "(empty path)")
    if str(path).lower().endswith(VIDEO_EXTS):
        return None, "cards: '%s' is a video - videos are baked by cards_video.py (P13), not loaded as a picture - gray placeholder." % name
    try:
        with Image.open(str(path)) as im:
            im.seek(0)
            return im.convert("RGB"), None
    except Exception:
        return None, "cards: '%s' is not a readable image - gray placeholder." % name


def _placeholder(w=640, h=480):
    im = Image.new("RGB", (w, h), (112, 116, 124))
    d = ImageDraw.Draw(im)
    d.rectangle((w * 0.2, h * 0.24, w * 0.8, h * 0.76), fill=(70, 74, 82))
    d.polygon([(w * 0.26, h * 0.68), (w * 0.42, h * 0.46), (w * 0.54, h * 0.60), (w * 0.62, h * 0.52), (w * 0.74, h * 0.68)], fill=(158, 164, 174))
    d.ellipse((w * 0.62, h * 0.32, w * 0.70, h * 0.32 + w * 0.08), fill=(158, 164, 174))
    return im


def _aspect(media):
    """Picture width / height for a card whose height is not given: the media's own shape, clamped."""
    return max(ASPECT_MIN, min(ASPECT_MAX, media.width / float(max(1, media.height)))) if media is not None else 4.0 / 3.0


# ---- label ------------------------------------------------------------------------------------------------------------------
def t4_split_label(text):
    """'LIVE CODING DEVELOPMENT' -> ['LIVE CODING', 'DEVELOPMENT'] (balanced); an explicit newline or '|' decides; short / one-word text = 1 line."""
    t = " ".join(str(text or "").split()) if "\n" not in str(text or "") and "|" not in str(text or "") else str(text)
    for sep in ("\n", "|"):
        if sep in t:
            parts = [p.strip() for p in t.split(sep, 1)]
            return [p for p in parts if p][:2]
    words = t.split(" ") if t else []
    if len(words) < 2 or len(t) <= SHORT_LABEL:
        return [t] if t else []
    best = min(range(1, len(words)), key=lambda i: (max(len(" ".join(words[:i])), len(" ".join(words[i:]))), i))
    return [" ".join(words[:best]), " ".join(words[best:])]


def _label_masks(lines, font, size):
    return [t2_text_mask(t.upper() if not has_arabic(t) else t, font, size, 0.01, LABEL_SHEAR) for t in lines]


def _label_geometry(masks, size):
    gap = size * 0.22
    tw, th = max(m.width for m in masks), sum(m.height for m in masks) + gap * (len(masks) - 1)
    ph = th + 2 * size * 0.46
    sl = ph * 0.16                                                      # lean of the outer edge
    return tw, th, gap, ph, sl, tw + 2 * size * 0.62 + sl


def t4_label_sprite(lines, color, font, size, left=False):
    """The label tag: stripes + dark glass slanted panel + text. left=True mirrors the shape (outer end on the left, for left corners).
    -> RGBA image (glow included); .info['panel'] = (x0, y0, x1, y1) of the panel inside it. Empty lines -> None."""
    lines = [t for t in lines if t]
    if not lines:
        return None
    masks = _label_masks(lines, font, size)
    tw, th, gap, ph, sl, pw = _label_geometry(masks, size)
    cr, bw, glow = ph * 0.20, max(2.0, size * 0.085), max(4.0, size * 0.28)
    pts = [(sl, 0), (pw - cr * 0.55, 0), (pw, cr * 0.55), (pw, ph - cr), (pw - cr, ph), (0, ph)]
    panel = _glass_sprite(t2_poly_mask(pts), LABEL_TINT, color, bw, glow)
    sh, stripe = ph * 0.62, ph * 0.10
    off = sh * math.tan(math.radians(28))
    sw = off + 3 * stripe + 2 * ph * 0.07 + 0.5
    bars = hazard_stripes((sw, sh), 28, color, max(3.0, size * 0.12), stripe=stripe, gap=ph * 0.07)
    pad = int(glow * 2.6) + 6
    ox, oy = pad + int(sw), pad
    cv = Image.new("RGBA", (int(ox + pw + pad), int(ph + 2 * pad)), (0, 0, 0, 0))
    kit_paste(cv, bars, ox - sw * 0.80, oy + ph - sh - ph * 0.04)
    kit_paste(cv, panel, ox, oy)
    box = (ox, oy, ox + pw, oy + ph)
    cx = ox + (sl + pw) / 2.0
    if left:
        cv = ImageOps.mirror(cv)
        cx, box = cv.width - cx, (cv.width - box[2], box[1], cv.width - box[0], box[3])
    y = oy + size * 0.46
    for i, m in enumerate(masks):
        x = int(round(cx - m.width / 2.0))
        t2_paint(cv, (m, (x, int(round(y + size * 0.05)))), (0, 0, 0), 0.55)                       # soft drop shadow
        t2_paint(cv, (m, (x, int(round(y)))), _WHITE if (i == 0 or len(masks) == 1) else t2_lighten(t2_rgb(color), 0.12))
        y += m.height + gap
    cv.info["panel"] = tuple(int(round(v)) for v in box)
    return cv


# ---- card -------------------------------------------------------------------------------------------------------------------
def _picture(media, cw, ch, mask):
    """Media cover-cropped to cw x ch and cut by the chamfer mask -> RGBA."""
    pic = ImageOps.fit(media.convert("RGB"), (cw, ch), Image.LANCZOS, centering=(0.5, 0.5)).convert("RGBA")
    m, (mx, my) = mask
    a = Image.new("L", (cw, ch), 0)
    a.paste(m, (mx, my))
    pic.putalpha(a)
    return pic


def _accent(cv, ox, oy, cw, cut, bw, color):
    """Two short bright dashes under the top edge, right of the top-left cut (R8): a pale thick one and a shorter coloured one."""
    y, x0 = oy + bw * 2.6, ox + cut * 1.7
    c = t2_rgb(color)
    t2_paint(cv, t2_line_mask([(x0, y), (x0 + cw * 0.15, y)], max(1.5, bw * 0.8), caps=False), t2_lighten(c, 0.85), 0.95)
    t2_paint(cv, t2_line_mask([(x0 + cw * 0.17, y), (x0 + cw * 0.215, y)], max(1.5, bw * 0.8), caps=False), c, 0.95)


def _label_pos(lab, rect, anchor):
    """Top-left of the label image so its panel overlaps the card corner `anchor` and sticks out by OVERHANG of its height."""
    px0, py0, px1, py1 = lab.info["panel"]
    ph, (cx0, cy0, cx1, cy1) = py1 - py0, rect
    x = (cx1 + 0.012 * (cx1 - cx0) - px1) if anchor.endswith("right") else (cx0 - 0.012 * (cx1 - cx0) - px0)
    y = (cy1 + OVERHANG * ph - py1) if anchor.startswith("bottom") else (cy0 - OVERHANG * ph - py0)
    return int(round(x)), int(round(y))


def t4_card_mask(cw, ch):
    """The picture's chamfer mask as an 'L' image cw x ch - the exact shape t4_card_sprite cuts its picture with (cards_video bakes clips with it)."""
    cw, ch = max(40, int(round(cw))), max(40, int(round(ch)))
    k = min(cw, ch) * 0.06
    m, (mx, my) = chamfer_rect((cw, ch), (k, k * 0.7, k, k * 1.2))
    a = Image.new("L", (cw, ch), 0)
    a.paste(m, (mx, my))
    return a


def t4_video_frame(path, t=0.0):
    """One RGB frame of a video at time t (seconds) -> PIL image, or None when it cannot be read. Used by --still."""
    import subprocess
    import tempfile
    if not path or not os.path.isfile(str(path)) or not FFMPEG:
        return None
    fd, png = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        r = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", "%.3f" % max(0.0, float(t)), "-i", str(path),
                            "-frames:v", "1", png], capture_output=True)
        return Image.open(png).convert("RGB").copy() if r.returncode == 0 and os.path.getsize(png) > 0 else None
    except Exception:
        return None
    finally:
        try:
            os.remove(png)
        except OSError:
            pass


def t4_card_sprite(media, label, cw, ch, color, font, label_anchor="bottom-right", label_color=None, with_picture=True, media_img=None):
    """One finished card -> (RGBA sprite, warning | None). media = path; label = text ('' = none); cw / ch = picture size px; sprite.info['card']
    = the picture rect inside the sprite. A missing / unreadable / video media gives a gray placeholder (+ the one-line warning)."""
    if media_img is not None:                                   # a frame supplied by the caller (video cards in a --still)
        img, msg = media_img, None
    else:
        img, msg = t4_load_media(media)
    cw, ch = max(40, int(round(cw))), max(40, int(round(ch)))
    k = min(cw, ch) * 0.06
    mask = chamfer_rect((cw, ch), (k, k * 0.7, k, k * 1.2))
    bw, glow = max(2.5, cw * 0.0085), max(6.0, cw * 0.026)
    lab = None
    if label:
        size = cw * LABEL_FRAC
        lab = t4_label_sprite(t4_split_label(label), label_color or color, font, size, label_anchor.endswith("left"))
        if lab is not None and lab.info["panel"][2] - lab.info["panel"][0] > cw * 1.0:               # too wide: shrink the text once
            size *= max(0.55, cw * 1.0 / (lab.info["panel"][2] - lab.info["panel"][0]))
            lab = t4_label_sprite(t4_split_label(label), label_color or color, font, size, label_anchor.endswith("left"))
    M = int(glow * 2.6) + 6 + (max(lab.width, lab.height) if lab is not None else 0)
    cv = Image.new("RGBA", (cw + 2 * M, ch + 2 * M), (0, 0, 0, 0))
    pic = _picture(img if img is not None else _placeholder(), cw, ch, mask)
    if with_picture:                                            # False = frame only: the picture is a baked video layer under it
        cv.alpha_composite(pic, (M, M))
    kit_paste(cv, neon_stroke(mask, color, bw, glow), M, M)
    _accent(cv, M, M, cw, k, bw, color)
    rect = (M, M, M + cw, M + ch)
    if lab is not None:
        lx, ly = _label_pos(lab, rect, label_anchor)
        _t2_alpha_paste(cv, lab, lx, ly)
    ab = cv.getchannel("A")
    if not with_picture:                                        # same crop box as the full card: add the picture's footprint
        fa = Image.new("L", cv.size, 0)
        fa.paste(pic.getchannel("A"), (M, M))
        ab = ImageChops.lighter(ab, fa)
    bb = ab.getbbox() or (0, 0, cv.width, cv.height)
    out = cv.crop(bb)
    out.info["card"] = (rect[0] - bb[0], rect[1] - bb[1], rect[2] - bb[0], rect[3] - bb[1])
    return out, msg
