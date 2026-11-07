"""mt.templates.t3.slot - T3-8: CENTER CONTENT SLOT of the bottom panel (replaces the poster's "Editing Layers" table).

Header (icon + editable title + thin line, hidden when the slot has no blocks) and timed CONTENT BLOCKS inside
t3_panel_center_rect(): points (<=6 lines, bullet/number, reveal one by one), stat (big orange heavy-italic number, optional
count-up, label, sub-text), media (image or short video segment in a rounded frame + caption), chips (<=8 keyword pills, the
spoken one turns orange).  Blocks follow each other (a block holds until the next one starts; the old one animates out, then the
new one animates in).  Rendering is cheap: every block is a static sprite (Items); only count-up steps, per-line reveals, chip
highlights and the baked media clip change.  Media video = video layer baked like the floating cards (alpha clip, qtrle).
cfg["t3"]["slot"] = {on, title, icon, anim, anim_dur, blocks:[{type, start, trigger, hold, ...type keys}]}  (see t3_slot_cfg).
The slot is drawn only when cfg["t3"]["panel"]["on"] (it lives in the panel's centre column)."""
import math
import os
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from mt.anim import anim_state
from mt.draw import Item, draw_item
from mt.fonts import is_rtl_text, shape
from mt.templates.t3 import panels as _pn
from mt.templates.t3.static import t3_warn, K, t3_font

TYPES = ("points", "stat", "media", "chips")
ICONS = ("layers", "star", "bulb", "chart", "tag")
MAX_LINES, MAX_CHIPS, MAX_BLOCKS = 6, 8, 8
ANIMS = ("fade", "tile_up", "slide_up", "slide_left", "slide_right", "none")
SLOT_DEFAULTS = {"on": False, "title": "KEY POINTS", "icon": "layers", "anim": "fade", "anim_dur": 0.35, "blocks": None}
DEMO_BLOCKS = [
    {"type": "points", "lines": ["Template-driven edits", "Animated captions", "Adaptive video frame", "One-click styles"],
     "stagger": 0.5},
    {"type": "stat", "value": "250+", "label": "VIDEOS EDITED", "sub": "and counting", "count_up": True},
    {"type": "chips", "chips": ["Design", "Motion", "Code", "Audio", "Story", "Reels"]},
]
GAP_DEFAULT = 4.0                                      # seconds between block starts when no start is given
_SPR = {}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _s(v):
    return str(v or "").strip()


def _norm_items(src, limit):
    out = []
    for r in list(src or [])[:limit]:
        r = {"text": r} if not isinstance(r, dict) else r
        if _s(r.get("text")):
            out.append({"text": _s(r["text"]), "trigger": _s(r.get("trigger"))})
    return out


def _norm_block(b):
    if not isinstance(b, dict):
        return None
    t = _s(b.get("type")).lower()
    if t not in TYPES:
        return None
    o = {"type": t, "start": _num(b.get("start")), "trigger": _s(b.get("trigger")), "hold": _num(b.get("hold"))}
    if o["hold"] is not None and o["hold"] <= 0:
        o["hold"] = None
    if t == "points":
        o["lines"] = _norm_items(b.get("lines"), MAX_LINES)
        o["bullet"] = "number" if _s(b.get("bullet")).lower() in ("number", "numbers", "num") else "dot"
        rv = _s(b.get("reveal") or "stagger").lower()
        o["reveal"] = rv if rv in ("stagger", "trigger", "all") else "stagger"
        o["stagger"] = max(0.0, min(3.0, _num(b.get("stagger")) if _num(b.get("stagger")) is not None else 0.5))
        if not o["lines"]:
            return None
    elif t == "stat":
        o.update(value=_s(b.get("value")) or "100", label=_s(b.get("label")), sub=_s(b.get("sub")),
                 count_up=bool(b.get("count_up", False)), count_dur=max(0.3, min(3.0, _num(b.get("count_dur")) or 1.0)))
    elif t == "media":
        o.update(image=_s(b.get("image")), video=_s(b.get("video")), caption=_s(b.get("caption")),
                 seg_start=max(0.0, _num(b.get("seg_start")) or 0.0), seg_end=_num(b.get("seg_end")))
        if o["seg_end"] is not None and o["seg_end"] <= o["seg_start"]:
            o["seg_end"] = None
    else:
        o["chips"] = _norm_items(b.get("chips"), MAX_CHIPS)
        if not o["chips"]:
            return None
    return o


def t3_slot_cfg(raw=None):
    """Normalise cfg['t3']['slot'] (idempotent). blocks missing/None -> the 3 demo blocks (points, stat, chips); an explicit [] =
    empty slot (header hidden). Bad blocks are dropped; up to 8 blocks."""
    raw = raw if isinstance(raw, dict) else {}
    d = dict(SLOT_DEFAULTS)
    d["on"] = bool(raw.get("on", False))
    if "title" in raw:
        d["title"] = _s(raw["title"])
    ic = _s(raw.get("icon")).lower()
    d["icon"] = ic if ic in ICONS else "layers"
    an = _s(raw.get("anim")).lower()
    d["anim"] = an if an in ANIMS else "fade"
    d["anim_dur"] = max(0.1, min(1.5, _num(raw.get("anim_dur")) or 0.35))
    src = raw.get("blocks")
    src = DEMO_BLOCKS if src is None else src
    d["blocks"] = [b for b in (_norm_block(x) for x in list(src)[:MAX_BLOCKS]) if b]
    return d


def _scfg(cfg):
    s = (cfg.get("t3") or {}).get("slot")
    return s if isinstance(s, dict) and isinstance(s.get("blocks"), list) and "icon" in s and \
        all("type" in b for b in s["blocks"]) else t3_slot_cfg(s)


def slot_active(cfg):
    p = _pn._pcfg(cfg)
    return bool(p["on"] and _scfg(cfg)["on"])


# ---- geometry -------------------------------------------------------------------------------------------------------------
def slot_rects():
    """-> (center rect, header height, content area rect), canvas px."""
    cx, cy, cw, ch = _pn.t3_panel_center_rect(_pn.t3_panel_rect())
    hh = int(round(36 * K))
    return (cx, cy, cw, ch), hh, (cx + 4, cy + hh + 8, cw - 8, ch - hh - 14)


def _acc(cfg):
    a = (cfg.get("t3") or {}).get("accent", "#F56D1F")
    try:
        return tuple(int(str(a).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    except ValueError:
        return (245, 109, 31, 255)


def _font(text, size, fonts, role="caps"):
    return _pn._ptfont(text, size, fonts, role)


def _fit(texts, maxw, size, fonts, role="caps", lo=12):
    """largest font size <= size at which every text fits maxw (never below lo)."""
    size = int(size)
    while size > lo:
        f = _font(texts[0], size, fonts, role)
        if all(_font(t, size, fonts, role).getlength(shape(t)) <= maxw for t in texts):
            break
        size -= 1
    return max(lo, size)


def _ellipsize(text, f, maxw):
    t = text
    while t and f.getlength(shape(t)) > maxw:
        t = t[:-1]
        if f.getlength(shape(t + "…")) <= maxw:
            return t.rstrip() + "…"
    return t


def _draw_text(d, xy, text, f, fill, anchor):
    d.text(xy, shape(text), font=f, fill=fill, anchor=anchor)


# ---- header ---------------------------------------------------------------------------------------------------------------
def _draw_icon_slot(d, name, cx, cy, s, col):
    if name == "star":
        pts = []
        for i in range(10):
            r = s * (0.5 if i % 2 == 0 else 0.22)
            a = -math.pi / 2 + i * math.pi / 5
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        d.polygon(pts, fill=col)
    elif name == "bulb":
        d.ellipse((cx - s * 0.32, cy - s * 0.5, cx + s * 0.32, cy + s * 0.14), fill=col)
        d.rectangle((cx - s * 0.16, cy + s * 0.18, cx + s * 0.16, cy + s * 0.42), fill=col)
    elif name == "chart":
        for i, hh in enumerate((0.45, 0.8, 0.62)):
            x = cx - s * 0.46 + i * s * 0.34
            d.rectangle((x, cy + s * 0.45 - s * hh, x + s * 0.24, cy + s * 0.45), fill=col)
    elif name == "tag":
        d.polygon([(cx - s * 0.5, cy - s * 0.2), (cx + s * 0.1, cy - s * 0.2), (cx + s * 0.5, cy), (cx + s * 0.1, cy + s * 0.2),
                   (cx - s * 0.5, cy + s * 0.2)], fill=col)
    else:                                                # layers: three stacked rhombi
        for i, dy in enumerate((0.26, 0.0, -0.26)):
            y = cy + s * dy
            pts = [(cx, y - s * 0.2), (cx + s * 0.5, y), (cx, y + s * 0.2), (cx - s * 0.5, y)]
            if i == 2:
                d.polygon(pts, fill=col)
            else:
                d.line(pts + [pts[0]], fill=col, width=max(2, int(s * 0.09)), joint="curve")


def slot_header(cfg, band_xy, w, h_total):
    """Draw the header (icon + title + thin line) onto an ImageDraw of the band: band_xy = (band_x0, band_y0) canvas origin.
    Returns a transparent-safe RGBA overlay layer of size (w, h_total) (band size) or None when the slot hides it."""
    s = _scfg(cfg)
    if not (s["on"] and s["blocks"]):
        return None
    (cx, cy, cw, ch), hh, _ = slot_rects()
    ox, oy = cx - band_xy[0], cy - band_xy[1]
    lay = Image.new("RGBA", (w, h_total), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    acc = _acc(cfg)
    isz = 24 * K
    _draw_icon_slot(d, s["icon"], ox + isz / 2 + 2, oy + hh * 0.46, isz, acc)
    title = s["title"]
    if title:
        fonts = (cfg.get("t3") or {}).get("fonts")
        f = _font(title, _fit([title], cw - isz - 14, 17 * K, fonts, lo=11), fonts)
        if is_rtl_text(title):
            _draw_text(d, (ox + cw - 2, oy + hh * 0.46), title, f, _pn.CREAM + (255,), "rm")
        else:
            _draw_text(d, (ox + isz + 12, oy + hh * 0.46), title, f, _pn.CREAM + (255,), "lm")
    d.line([(ox, oy + hh), (ox + cw, oy + hh)], fill=_pn.CREAM + (70,), width=1)
    return lay


# ---- timeline -------------------------------------------------------------------------------------------------------------
def slot_resolve(cfg, duration):
    """-> [] or list of block dicts: normalised block + {t0, t1} seconds (+ 'lines_t' reveal times / 'chips_t' highlight windows).
    Blocks run inside the panel window; each lasts until the next block starts (or `hold`)."""
    s = _scfg(cfg)
    res = _pn.panel_resolve(cfg, duration)
    if not (s["on"] and res and s["blocks"]):
        return []
    tr = float(((cfg.get("t3") or {}).get("layout") or {}).get("trans", 0.5))
    cues = _pn._cues(cfg)
    base = max(res["start"], res["band_start"] + tr + 0.05)
    out, prev = [], None
    for b in s["blocks"]:
        t0 = _pn._panel_trigger_time(cues, b["trigger"]) if b["trigger"] else None
        if b["trigger"] and t0 is None:
            t3_warn(f"   [!] slot block '{b['type']}': phrase '{b['trigger']}' not found - placed after the previous block.")
        if t0 is None:
            t0 = b["start"]
        if t0 is None:
            t0 = base if prev is None else prev["t0"] + GAP_DEFAULT
        t0 = max(t0, base if prev is None else prev["t0"] + 0.5)
        x = dict(b, t0=t0)
        if prev is not None and prev["hold"] is None:
            prev["t1"] = t0
        out.append(x)
        prev = x
        x["t1"] = None
    last_end = res["end"] - 0.05
    for x in out:
        end = x["t0"] + x["hold"] if x["hold"] else x["t1"]
        end = last_end if end is None else min(end, last_end)
        if x is not out[-1] and x["hold"] and x["t0"] + x["hold"] > out[out.index(x) + 1]["t0"]:
            end = out[out.index(x) + 1]["t0"]
        x["t1"] = end
    out = [x for x in out if x["t1"] - x["t0"] > 0.2 and x["t0"] < duration]
    for x in out:
        if x["type"] == "points":
            tt = []
            for i, ln in enumerate(x["lines"]):
                t = _pn._panel_trigger_time(cues, ln["trigger"]) if (x["reveal"] == "trigger" and ln["trigger"]) else None
                if x["reveal"] == "trigger" and ln["trigger"] and t is None:
                    t3_warn(f"   [!] slot line '{ln['text']}': phrase '{ln['trigger']}' not found - staggered instead.")
                tt.append(x["t0"] + (0.0 if x["reveal"] == "all" else i * x["stagger"]) if t is None else max(x["t0"], t))
            x["lines_t"] = tt
        elif x["type"] == "chips":
            hits = []
            for i, c in enumerate(x["chips"]):
                t = _pn._panel_trigger_time(cues, c["trigger"]) if c["trigger"] else None
                if c["trigger"] and t is None:
                    t3_warn(f"   [!] slot chip '{c['text']}': phrase '{c['trigger']}' not found - not highlighted.")
                if t is not None:
                    hits.append((max(x["t0"], t), i))
            hits.sort()
            x["chips_t"] = [(a, hits[k + 1][0] if k + 1 < len(hits) else x["t1"], i) for k, (a, i) in enumerate(hits)]
    return out


# ---- sprites --------------------------------------------------------------------------------------------------------------
def _cache(key, fn):
    v = _SPR.get(key)
    if v is None:
        v = _SPR[key] = fn()
    return v


def _points_line_sprite(text, n, bullet, w, h, size, acc, fonts):
    rtl = is_rtl_text(text)
    spr = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(spr)
    r = h * 2 * (0.30 if bullet == "number" else 0.13)
    bx = (w * 2 - r - 6) if rtl else (r + 6)
    d.ellipse((bx - r, h - r, bx + r, h + r), fill=acc)
    if bullet == "number":
        nf = _font(str(n), r * 1.3, fonts, "caps")
        d.text((bx, h), str(n), font=nf, fill=_pn.BROWN + (255,), anchor="mm")
    spr = spr.resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(spr)
    bw = int(2 * r / 2 + 14)
    f = _font(text, size, fonts)
    t = _ellipsize(text, f, w - bw - 6)
    if rtl:
        _draw_text(d, (w - bw, h / 2.0), t, f, (255, 255, 255, 255), "rm")
    else:
        _draw_text(d, (bw, h / 2.0), t, f, (255, 255, 255, 255), "lm")
    return spr


def points_sprites(cfg, blk, area):
    """-> [(sprite, cx_off, cy_off)] one per line (centre offsets inside the area)."""
    ax, ay, aw, ah = area
    fonts = (cfg.get("t3") or {}).get("fonts")
    texts = [ln["text"] for ln in blk["lines"]]
    n = len(texts)
    lh = int(min(ah / max(n, 1), 56 * K * 0.8))
    bw = int(0.13 * 2 * lh + 14 + 8) if blk["bullet"] == "dot" else int(0.30 * 2 * lh + 14 + 8)
    size = _fit(texts, aw - bw - 6, lh * 0.5, fonts, lo=12)
    y0 = (ah - n * lh) / 2.0
    acc = _acc(cfg)
    out = []
    for i, tx in enumerate(texts):
        key = ("pt", tx, i + 1, blk["bullet"], int(aw), lh, size, acc, repr(fonts))
        spr = _cache(key, lambda tx=tx, i=i: _points_line_sprite(tx, i + 1, blk["bullet"], int(aw), lh, size, acc, fonts))
        out.append((spr, aw / 2.0, y0 + i * lh + lh / 2.0))
    return out


_NUM_RE = re.compile(r"^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$", re.S)


def _count_texts(value, steps):
    m = _NUM_RE.match(value)
    if not m:
        return [value]
    pre, num, suf = m.groups()
    dec = len(num.split(".")[1]) if "." in num else 0
    comma = "," in num
    target = float(num.replace(",", ""))
    outs = []
    for k in range(steps):
        p = 1 - (1 - (k + 1) / steps) ** 3
        v = target * p
        s = f"{v:,.{dec}f}" if comma else f"{v:.{dec}f}"
        outs.append(pre + s + suf)
    return outs


def _stat_sprite(value, label, sub, w, h, acc, fonts):
    """Composite (value + label + sub) sprite w x h; heavy italic number (sheared when the font is not italic), orange."""
    spr = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rtl = is_rtl_text(label)
    path, shear = t3_font("head", value, fonts)
    size = int(h * 0.50)
    while size > 18:
        f = ImageFont.truetype(path, size)
        if f.getlength(value) + shear * size <= w * 0.96:
            break
        size -= 2
    f = ImageFont.truetype(path, size)
    nh = int(size * 1.25)
    pad = int(shear * nh) + 4
    lay = Image.new("RGBA", (int(f.getlength(value)) + pad * 2 + 6, nh), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((pad, nh / 2.0), value, font=f, fill=acc, anchor="lm", stroke_width=1 if size > 30 else 0,
                             stroke_fill=acc)
    if shear:
        lay = lay.transform(lay.size, Image.AFFINE, (1, shear, -shear * nh / 2.0, 0, 1, 0), Image.BICUBIC)
    top = int(h * 0.50) - nh // 2 - int(h * 0.04)
    spr.alpha_composite(lay, (max(0, (w - lay.width) // 2), max(0, top)))
    d = ImageDraw.Draw(spr)
    y = top + nh + int(h * 0.04)
    if label:
        lf = _font(label, _fit([label], w - 8, h * 0.13, fonts, lo=11), fonts)
        _draw_text(d, (w / 2.0, y), label, lf, _pn.CREAM + (255,), "ma")
        y += int(lf.size * 1.35)
    if sub:
        sf = _font(sub, _fit([sub], w - 8, h * 0.10, fonts, "light", lo=10), fonts, "light")
        _draw_text(d, (w / 2.0, y), sub, sf, _pn.CREAM + (190,), "ma")
    return spr


def stat_sprites(cfg, blk, area):
    """-> [sprite per count step] (a single sprite when no count-up)."""
    ax, ay, aw, ah = area
    acc = _acc(cfg)
    fonts = (cfg.get("t3") or {}).get("fonts")
    texts = _count_texts(blk["value"], 12) if blk["count_up"] else []
    texts = texts[:-1] + [blk["value"]] if texts else [blk["value"]]
    return [_cache(("st", v, blk["label"], blk["sub"], int(aw), int(ah), acc, repr(fonts)),
                   lambda v=v: _stat_sprite(v, blk["label"], blk["sub"], int(aw), int(ah), acc, fonts)) for v in texts]


def _rounded_frame(photo, w, h, radius=14):
    ph = ImageOps.fit(photo.convert("RGB"), (w * 2, h * 2), Image.LANCZOS, centering=(0.5, 0.4)).convert("RGBA")
    m = Image.new("L", (w * 2, h * 2), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 2 - 1, h * 2 - 1), radius=radius * 2, fill=255)
    ImageDraw.Draw(ph).rounded_rectangle((1, 1, w * 2 - 2, h * 2 - 2), radius=radius * 2, outline=_pn.CREAM + (235,), width=5)
    out = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    out.paste(ph, (0, 0), m)
    return out.resize((w, h), Image.LANCZOS)


def _media_geom(blk, area):
    ax, ay, aw, ah = area
    cap_h = int(22 * K * 0.8) if blk["caption"] else 0
    fh = int(ah - cap_h - 4)
    return int(aw), fh, cap_h


def _caption_sprite(text, w, h, fonts):
    spr = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    f = _font(text, _fit([text], w - 6, h * 0.8, fonts, lo=10), fonts)
    _draw_text(ImageDraw.Draw(spr), (w / 2.0, h / 2.0), _ellipsize(text, f, w - 6), f, _pn.CREAM + (235,), "mm")
    return spr


def _media_photo(cfg, blk):
    """RGB still of a media block: the image, or the video frame at the segment start (original video or the given file)."""
    if blk["image"]:
        try:
            im = Image.open(blk["image"]).convert("RGB")
            im.load()
            return im
        except Exception:
            t3_warn(f"   [!] slot media image unreadable: {blk['image']}")
    elif blk["video"] or cfg.get("video"):
        im = _pn._video_frame(blk["video"] or cfg["video"], blk["seg_start"])
        if im is not None:
            return im
    return Image.new("RGB", (64, 64), (96, 96, 96))


def chips_layout(cfg, blk, area):
    """-> (chip rects [(x, y, w, h)] relative to the area, font size, text list). Rows wrap; the font shrinks until all fit."""
    ax, ay, aw, ah = area
    fonts = (cfg.get("t3") or {}).get("fonts")
    texts = [c["text"] for c in blk["chips"]]
    size = int(22 * K * 0.7)
    while True:
        f = _font(texts[0], size, fonts)
        ph, gap = int(size * 1.9), int(size * 0.55)
        rows, cur, curw = [], [], 0
        ws = [min(int(_font(t, size, fonts).getlength(shape(t))) + int(size * 1.6), int(aw)) for t in texts]
        for i, wd in enumerate(ws):
            if cur and curw + gap + wd > aw:
                rows.append((cur, curw))
                cur, curw = [], 0
            cur.append(i)
            curw += wd + (gap if len(cur) > 1 else 0)
        rows.append((cur, curw))
        tot = len(rows) * ph + (len(rows) - 1) * gap
        if (tot <= ah and all(r[1] <= aw for r in rows)) or size <= 11:
            break
        size -= 1
    rects = [None] * len(texts)
    y = (ah - tot) / 2.0
    for idxs, rw in rows:
        x = (aw - rw) / 2.0
        for i in idxs:
            rects[i] = (x, y, ws[i], ph)
            x += ws[i] + gap
        y += ph + gap
    return rects, size, texts


def _pill(text, w, h, size, fonts, acc, hot):
    spr = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(spr)
    if hot:
        d.rounded_rectangle((0, 0, w * 2 - 1, h * 2 - 1), radius=h, fill=acc)
    else:
        d.rounded_rectangle((1, 1, w * 2 - 2, h * 2 - 2), radius=h, outline=_pn.CREAM + (235,), width=3)
    spr = spr.resize((w, h), Image.LANCZOS)
    f = _font(text, size, fonts)
    _draw_text(ImageDraw.Draw(spr), (w / 2.0, h / 2.0), _ellipsize(text, f, w - 8), f,
               (_pn.BROWN + (255,)) if hot else (_pn.CREAM + (255,)), "mm")
    return spr


def chips_sprites(cfg, blk, area):
    """-> (base sprite with all cream pills (area-sized), [(hot pill sprite, cx_off, cy_off)])"""
    ax, ay, aw, ah = area
    fonts = (cfg.get("t3") or {}).get("fonts")
    acc = _acc(cfg)
    rects, size, texts = chips_layout(cfg, blk, area)
    base = Image.new("RGBA", (int(aw), int(ah)), (0, 0, 0, 0))
    hot = []
    for t, (x, y, w, h) in zip(texts, rects):
        base.alpha_composite(_pill(t, int(w), int(h), size, fonts, acc, False), (int(x), int(y)))
        hot.append((_pill(t, int(w), int(h), size, fonts, acc, True), x + w / 2.0, y + h / 2.0))
    return base, hot


# ---- items ----------------------------------------------------------------------------------------------------------------
class SlotItem(Item):
    """Item whose in / out animations can be switched off separately (fin / fout)."""
    __slots__ = ("fin", "fout")

    def __init__(self, sprite, start, end, cx, cy, anim, dur, fin=True, fout=True, rtl=False):
        Item.__init__(self, sprite, start, end, cx, cy, anim, dur, True, 1.0, rtl)
        self.fin, self.fout = fin, fout

    def progress(self, t):
        d = min(self.dur, (self.end - self.start) / 2.0)
        if d <= 1e-6 or self.anim in (None, "none"):
            return 1.0
        pin = (t - self.start) / d if self.fin else 1.0
        pout = (self.end - t) / d if self.fout else 1.0
        return max(0.0, min(1.0, pin, pout))


def slot_items(cfg, duration):
    """All slot Items (static sprites; animated overlays only for points reveal, count-up, chip highlight). [] when off."""
    if not slot_active(cfg):
        return []
    from mt.templates.t3 import dynamic as _dyn
    s = _scfg(cfg)
    (rx, ry, rw, rh), hh, area = slot_rects()
    ax, ay, aw, ah = area
    fonts = (cfg.get("t3") or {}).get("fonts")
    an, ad = s["anim"], s["anim_dur"]
    items = []
    still = bool(cfg.get("_t2_still"))
    for b in slot_resolve(cfg, duration):
        t0, t1 = b["t0"], b["t1"]
        if not _dyn._vis(t0, t1):
            continue

        def add(spr, a, b_, cx, cy, fin=True, fout=True, dur=ad, anim=an):
            items.append(SlotItem(spr, a, b_, ax + cx, ay + cy, anim, dur, fin, fout, rtl=False))
        if b["type"] == "points":
            for (spr, cx, cy), t in zip(points_sprites(cfg, b, area), b["lines_t"]):
                if t < t1 - 0.1:
                    add(spr, t, t1, cx, cy, fin=True, fout=True)
        elif b["type"] == "stat":
            sp = stat_sprites(cfg, b, area)
            n = len(sp)
            step = b["count_dur"] / max(n, 1) if n > 1 else 0
            for k, spr in enumerate(sp):
                a = t0 + k * step
                e = t0 + (k + 1) * step if k < n - 1 else t1
                if a >= t1 - 0.05:
                    break
                add(spr, a, min(e, t1), aw / 2.0, ah / 2.0, fin=(k == 0), fout=(k == n - 1))
        elif b["type"] == "chips":
            base, hot = chips_sprites(cfg, b, area)
            add(base, t0, t1, aw / 2.0, ah / 2.0)
            for a, e, i in b.get("chips_t", []):
                spr, cx, cy = hot[i]
                add(spr, a, e, cx, cy, fin=True, fout=(abs(e - t1) < 1e-6), dur=0.15, anim="fade")
        else:                                              # media
            fw, fh, ch_ = _media_geom(b, area)
            is_vid = (not b["image"])
            if (not is_vid) or still or not _vid_ok(cfg, b):
                photo = _cache(("mp", b["image"], b["video"], b["seg_start"], fw, fh, repr(cfg.get("video"))),
                               lambda: _rounded_frame(_media_photo(cfg, b), fw, fh))
                add(photo, t0, t1, aw / 2.0, fh / 2.0)
            if b["caption"]:
                add(_cache(("cp", b["caption"], fw, ch_, repr(fonts)), lambda: _caption_sprite(b["caption"], fw, ch_, fonts)),
                    t0, t1, aw / 2.0, fh + 4 + ch_ / 2.0)
    return items


def _vid_ok(cfg, b):
    src = b["video"] or cfg.get("video")
    return bool(src and os.path.isfile(str(src)))


# ---- baked media video segments (video layers) -----------------------------------------------------------------------------
def slot_prepare_layers(cfg, info, tmpdir):
    """Media blocks with a video segment -> alpha clips (rounded frame + ring + fade/slide baked), same mechanism as the floating
    cards: a video layer with area 'canvas' and a fixed position (_xy). Frozen on the last frame when shorter than the block."""
    if not slot_active(cfg) or cfg.get("_t2_still"):
        return []
    from mt.common import FFMPEG
    W, H = cfg["canvas"]
    fps = info["fps"]
    fps_f = float(fps)
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    dur_eff = info["duration"]
    if cfg.get("preview"):
        dur_eff = min(dur_eff, float(cfg["preview"]))
    s = _scfg(cfg)
    (rx, ry, rw, rh), hh, area = slot_rects()
    ax, ay, aw, ah = area
    layers = []
    for n, b in enumerate(x for x in slot_resolve(cfg, info["duration"]) if x["type"] == "media" and not x["image"]):
        if b["t0"] >= dur_eff or not _vid_ok(cfg, b):
            continue
        src = b["video"] or cfg["video"]
        fw, fh, _ = _media_geom(b, area)
        t0, t1 = b["t0"], min(b["t1"], dur_eff)
        dx, dy = anim_state(s["anim"], 0.0, W, H)[1:3]
        padx, pady = int(abs(dx)) + 8, int(abs(dy)) + 8
        x0, y0 = int(round(ax)) - padx, int(round(ay)) - pady
        Wp, Hp = fw + 2 * padx, fh + 2 * pady
        Wp, Hp = Wp + Wp % 2, Hp + Hp % 2
        x0, y0 = max(0, x0), max(0, y0)
        Wp, Hp = min(Wp, W - x0), min(Hp, H - y0)
        Wp, Hp = Wp - Wp % 2, Hp - Hp % 2
        nfr = max(1, int(math.ceil((t1 - t0) * fps_f)))
        seg = (b["seg_end"] - b["seg_start"]) if b["seg_end"] else max(0.1, t1 - t0)
        out = os.path.join(tmpdir, f"t3slot{n}.mov")
        rd = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{b['seg_start']:.3f}", "-t", f"{seg:.3f}",
                               "-i", str(src), "-an", "-vf",
                               f"fps={fps_s},scale={fw}:{fh}:force_original_aspect_ratio=increase,crop={fw}:{fh},format=rgb24",
                               "-frames:v", str(nfr), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        wr = subprocess.Popen([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                               "-video_size", f"{Wp}x{Hp}", "-framerate", fps_s, "-i", "pipe:0", "-c:v", "qtrle", "-pix_fmt",
                               "argb", out], stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        print(f"Preparing slot media clip {n + 1} ({Path(str(src)).name}, {nfr} frames)...")
        last = None
        try:
            for i in range(nfr):
                raw = b""
                need = fw * fh * 3
                while len(raw) < need:
                    ch = rd.stdout.read(need - len(raw))
                    if not ch:
                        break
                    raw += ch
                fr = Image.frombytes("RGB", (fw, fh), raw) if len(raw) == need else last
                if fr is None:
                    fr = Image.new("RGB", (fw, fh), (96, 96, 96))
                last = fr
                spr = _rounded_frame(fr, fw, fh)
                it = SlotItem(spr, t0, b["t1"], ax - x0 + fw / 2.0, ay - y0 + fh / 2.0, s["anim"], s["anim_dur"])
                canvas = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
                draw_item(canvas, it, anim_state(it.anim, it.progress(t0 + i / fps_f), W, H))
                wr.stdin.write(canvas.tobytes())
            wr.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        finally:
            rd.kill()
            rd.wait()
        err = wr.stderr.read().decode("utf-8", "replace")
        if wr.wait() != 0 or not os.path.isfile(out):
            raise SystemExit("[!] Could not prepare the slot media clip:\n" + err[-800:])
        layers.append({"path": out, "start": t0, "end": t1, "area": "canvas", "mode": "fit", "fade": 0.0, "_xy": [x0, y0]})
    from mt.templates.t3.layout import split_hide                  # T3-9: the clip is cut where a split hides the bands
    for a, b in split_hide(cfg, info["duration"]):
        for L in layers[:]:
            if L["start"] >= a and L["start"] < b:
                layers.remove(L)
            elif L["start"] < a < L["end"]:
                L["end"] = a
    return layers


# ---- questions ------------------------------------------------------------------------------------------------------------
def t3_ask_slot():
    """Centre-slot questions (Enter = default / last answer). Returns {"slot": {...}} (on False = old placeholder)."""
    from mt.common import D, ask, ask_choice, yn
    from mt.templates.t3.dynamic import _c_start
    on = yn("Fill the panel's centre column with content blocks (key points, stat, media, chips)?",
            default=D.get("t3_slot", "y") == "y")
    D["t3_slot"] = "y" if on else "n"
    if not on:
        return {"slot": {"on": False}}
    title = ask("Centre title ('-' = none)", default=SLOT_DEFAULTS["title"], key="t3_slot_title",
                cast=lambda v: "" if v.strip() == "-" else v.strip())
    icon = ICONS[ask_choice("Centre icon:", list(ICONS), default=1, key="t3_slot_icon") - 1]
    mode = ask_choice("Centre blocks:", ["Demo blocks (points, stat, chips)", "My own blocks", "None (hide the header too)"],
                      default=1, key="t3_slot_mode")
    base = {"on": True, "title": title, "icon": icon}
    if mode == 1:
        return {"slot": base}
    if mode == 3:
        return {"slot": dict(base, blocks=[])}
    blocks = []
    while len(blocks) < MAX_BLOCKS:
        k = len(blocks)
        ty = TYPES[ask_choice(f"Block {k + 1} type:", ["Key points", "Big stat", "Image / video", "Keyword chips"], default=1,
                              key=f"t3_slot_ty{k}") - 1]
        kind, val = ask(f"  Block {k + 1} starts at (seconds / mm:ss / spoken phrase, Enter = after the previous)", default="",
                        key=f"t3_slot_st{k}", allow_empty=True, cast=lambda v: ("t", None) if not v.strip() else _c_start(v))
        hold = ask("  Stays (seconds, Enter = until the next block)", default="", key=f"t3_slot_hold{k}", allow_empty=True,
                   cast=lambda v: None if not v.strip() else float(v))
        b = {"type": ty, "start": val if kind == "t" else None, "trigger": val if kind == "p" else "", "hold": hold}
        if ty == "points":
            n = int(ask("  How many lines (1-6)", default=4, key=f"t3_slot_pn{k}", cast=lambda v: max(1, min(6, int(v)))))
            b["lines"] = [ask(f"    Line {j + 1}", default=DEMO_BLOCKS[0]["lines"][j % 4], key=f"t3_slot_pl{k}_{j}",
                              cast=lambda v: v.strip()) for j in range(n)]
            b["bullet"] = ("dot", "number")[ask_choice("  Bullets:", ["Orange dots", "Numbers"], default=1, key=f"t3_slot_bu{k}") - 1]
        elif ty == "stat":
            b["value"] = ask("  Big number / text (e.g. 250+, 98%)", default="250+", key=f"t3_slot_sv{k}", cast=lambda v: v.strip())
            b["label"] = ask("  Label", default="VIDEOS EDITED", key=f"t3_slot_sl{k}", cast=lambda v: v.strip())
            b["sub"] = ask("  Small sub-text ('-' = none)", default="and counting", key=f"t3_slot_ss{k}",
                           cast=lambda v: "" if v.strip() == "-" else v.strip())
            b["count_up"] = yn("  Count up from 0?", default=D.get("t3_slot_cu", "y") == "y")
            D["t3_slot_cu"] = "y" if b["count_up"] else "n"
        elif ty == "media":
            src = ask("  Image or video file ('-' = a segment of your video)", default="-", key=f"t3_slot_mf{k}",
                      cast=lambda v: "" if v.strip() == "-" else v.strip().strip('"'))
            vid = src.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"))
            if src and not vid:
                b["image"] = src
            else:
                b["video"] = src
                b["seg_start"] = ask("  Segment start (seconds)", default=0, key=f"t3_slot_ms{k}", cast=float)
                b["seg_end"] = ask("  Segment end (seconds)", default=3, key=f"t3_slot_me{k}", cast=float)
            b["caption"] = ask("  Caption ('-' = none)", default="Behind the scenes", key=f"t3_slot_mc{k}",
                               cast=lambda v: "" if v.strip() == "-" else v.strip())
        else:
            raw = ask("  Keywords (comma separated, up to 8; 'word@phrase' highlights at that spoken phrase)",
                      default="Design, Motion, Code, Audio, Story, Reels", key=f"t3_slot_ck{k}", cast=lambda v: v.strip())
            b["chips"] = [{"text": p.split("@", 1)[0].strip(), "trigger": p.split("@", 1)[1].strip() if "@" in p else ""}
                          for p in raw.split(",") if p.strip()][:MAX_CHIPS]
        blocks.append(b)
        if not yn("Add another block?", default=False):
            break
    return {"slot": dict(base, blocks=blocks)}
