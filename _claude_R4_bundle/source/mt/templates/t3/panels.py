"""mt.templates.t3.panels - T3-7 (bottom PANEL: left gallery + right checklist, see the section at the end) and T3-6: the photo-tiles STRIP (poster y 965-1210, full band width).

2-4 slanted photo tiles (cover-fit photo, maroon gradient from the bottom, white line icon + white label bottom-left) on a strip
background (beige paper on the left fading to maroon on the right). Up to 3 SETS over time (time or SRT phrase + hold); a set
replaces the previous one (slide / fade).
Plug-in points (see ARCHITECTURE section 11/12):
  * register_band("strip", ranges=strip_ranges, content=strip_band_content) -> the layout engine draws the strip background band
    and `t3_band_active_ranges()` (AUTO layout) gets the seconds in which a set is active (a band reveal starts `trans` s before
    the first tile so the tiles enter on the fully shown band).
  * strip_items(cfg, duration, box) is called from dynamic.t3_dynamic_items for every layout segment; the strip rect is derived
    from the frame box (strip top = frame bottom + 10 poster px), so tiles follow the moving frame.
cfg["t3"]["strip"] = {on, sets:[{start, trigger, hold, tiles:[{image | frame, label, icon, icon_path}]}], stagger, anim, anim_dur,
set_trans ('slide'|'fade'), slant (deg)}.   The strip is only drawn when cfg["t3"]["layout"]["on"] is true."""
import math
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from mt.captions import caption_streams, find_trigger, parse_srt
from mt.draw import Item, _draw_icon, paper_texture
from mt.templates.t3 import layout as _lay
from mt.templates.t3.static import t3_warn, K, t3_font

ICONS = ("phone", "chip", "globe", "code", "cloud", "shield")
MAROON = (104, 32, 40)
TILE_BG = (52, 24, 28)                           # tile backdrop behind a contain-fit photo (no strip band any more)

PAD = 6                                          # px between the strip band edge and the tiles (band background shows)
MAX_SETS, MAX_TILES = 3, 4
STRIP_DEFAULTS = {"on": False, "sets": [], "stagger": 0.12, "anim": "tile_up", "anim_dur": 0.4, "set_trans": "slide",
                  "slant": 3.0, "fit": "contain"}
POSTER_TILES = [("Mobile Apps", "phone"), ("AI Automation", "chip"), ("Web Development", "globe")]
_SPR, _FR = {}, {}


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


# ---- cfg -------------------------------------------------------------------------------------------------------------
def _norm_icon(v, path=""):
    v = str(v or "").strip()
    if v.lower() in ICONS or v.lower() == "none":
        return v.lower(), ""
    p = str(path or v)
    if p.lower().endswith((".png", ".ico", ".webp", ".jpg", ".jpeg")):
        return "image", p
    return "none", ""


def _norm_tile(t):
    if not isinstance(t, dict):
        return None
    img, fr = str(t.get("image") or "").strip(), _num(t.get("frame"))
    if not img and fr is None:
        return None
    icon, ip = _norm_icon(t.get("icon"), t.get("icon_path"))
    return {"image": img, "frame": None if img else max(0.0, fr), "label": str(t.get("label") or "").strip(),
            "icon": icon, "icon_path": ip}


def t3_strip_cfg(raw=None):
    """Normalise cfg['t3']['strip'] (idempotent; bad values -> defaults; sets without 2-4 usable tiles are dropped)."""
    raw = raw if isinstance(raw, dict) else {}
    d = {k: (list(v) if isinstance(v, list) else v) for k, v in STRIP_DEFAULTS.items()}
    d["on"] = bool(raw.get("on", d["on"]))
    for k, lo, hi in (("stagger", 0.0, 1.5), ("anim_dur", 0.1, 2.0), ("slant", 0.0, 10.0)):
        v = _num(raw.get(k))
        d[k] = d[k] if v is None else max(lo, min(hi, v))
    d["anim"] = str(raw.get("anim") or d["anim"])
    d["set_trans"] = "fade" if str(raw.get("set_trans", "slide")).strip().lower() == "fade" else "slide"
    d["fit"] = "cover" if str(raw.get("fit", "contain")).strip().lower() == "cover" else "contain"
    sets = []
    for s in (raw.get("sets") if isinstance(raw.get("sets"), (list, tuple)) else []):
        if not isinstance(s, dict):
            continue
        tiles = [t for t in (_norm_tile(x) for x in (s.get("tiles") or [])) if t][:MAX_TILES]
        if len(tiles) < 2:
            continue
        hold = _num(s.get("hold"))
        sets.append({"start": _num(s.get("start")), "trigger": str(s.get("trigger") or "").strip(),
                     "hold": 4.0 if hold is None else max(0.5, hold), "tiles": tiles})
    d["sets"] = sets[:MAX_SETS]      # cap AFTER dropping unusable sets (they must not use up a slot)
    return d


# ---- timeline --------------------------------------------------------------------------------------------------------
def _cues(cfg):
    out = []
    for c in caption_streams(cfg):
        try:
            out.append(parse_srt(c["srt"]))
        except Exception:
            pass
    return out


def strip_resolve(cfg, duration):
    """-> [{start, end, tile_start, tile_end, tiles}] sorted by start (set k ends at its hold or 0.25 s after set k+1 starts)."""
    st = cfg["t3"]["strip"] if "strip" in (cfg.get("t3") or {}) and "sets" in cfg["t3"]["strip"] else \
        t3_strip_cfg((cfg.get("t3") or {}).get("strip"))
    if not st["on"]:
        return []
    tr = float(((cfg.get("t3") or {}).get("layout") or {}).get("trans", 0.5))
    cues, rows = _cues(cfg), []
    for s in st["sets"]:
        t0 = None
        if s["trigger"]:
            for c in cues:
                t0 = find_trigger(c, s["trigger"])
                if t0 is not None:
                    break
        if t0 is None:
            t0 = s["start"]
        if t0 is None:
            t3_warn(f"   [!] strip set: phrase '{s['trigger']}' not found and no start time - skipped.")
            continue
        rows.append({"start": float(t0), "end": float(t0) + s["hold"], "tiles": s["tiles"]})
    rows.sort(key=lambda r: r["start"])
    for a, b in zip(rows, rows[1:]):
        a["end"] = min(a["end"], b["start"] + 0.25)
    rows = [r for r in rows if r["start"] < duration]
    merged = _lay._merge([(max(0.0, r["start"] - tr), r["end"]) for r in rows], tr)
    for r in rows:
        r0 = next((m[0] for m in merged if m[0] <= r["start"] - 1e-6 + tr and r["start"] <= m[1] + 1e-6), 0.0)
        r["tile_start"] = max(r["start"], r0 + tr + 0.05)
        r["tile_end"] = min(r["end"], duration + 1.0) - 0.05
        r["band_start"] = max(0.0, r["start"] - tr)
    return [r for r in rows if r["tile_end"] > r["tile_start"] + 0.1]


def strip_ranges(cfg, duration):
    """band provider: seconds in which the strip band must be shown (starts `trans` s before the first tile)."""
    return [(r["band_start"], r["end"]) for r in strip_resolve(cfg, duration)]


# ---- drawing ---------------------------------------------------------------------------------------------------------
def strip_band_content(cfg, w, h):
    """Strip band = fully transparent (w x h): the T3 background shows between the frame, the tiles and the footer
    (the old beige-paper -> maroon band is gone)."""
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def _video_frame(video, t):
    key = (str(video), round(float(t), 3))
    if key in _FR:
        return _FR[key]
    im = None
    try:
        from mt.common import FFMPEG
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", "%.3f" % float(t), "-i", str(video), "-frames:v", "1", tmp],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.getsize(tmp) > 0:
            im = Image.open(tmp).convert("RGB")
            im.load()
        os.remove(tmp)
    except Exception:
        im = None
    _FR[key] = im
    return im


def strip_tile_photo(cfg, tile):
    """The tile's photo (RGB): an image file, or the video frame at tile['frame'] seconds (auto-extracted). Gray if unreadable."""
    im = None
    if tile.get("image"):
        try:
            im = Image.open(tile["image"]).convert("RGB")
            im.load()
        except Exception:
            t3_warn(f"   [!] strip tile image unreadable: {tile['image']}")
    elif tile.get("frame") is not None and cfg.get("video"):
        im = _video_frame(cfg["video"], tile["frame"])
        if im is None:
            t3_warn(f"   [!] strip tile: no video frame at {tile['frame']} s")
    return im or Image.new("RGB", (64, 64), (96, 96, 96))


def strip_tile_sprite(photo, label, icon, icon_path, w, h, off, first, last, accent="#F56D1F", fonts=None, fit="cover"):
    """One slanted tile as RGBA (w x h): `off` = horizontal shift of the top edge (px). Inner edges slant, outer edges are straight;
    thin cream separator line on the right slanted edge.
    fit "cover" = the old look (cropped photo, maroon gradient, label on the photo); fit "contain" = the whole photo (no crop,
    rounded corners) on a dark tile backdrop with the icon + label in a row UNDER it."""
    SS = 2
    W2, H2 = w * SS, h * SS
    o2 = off * SS
    x0, x1 = 0.0, W2 - (0 if last else o2) - 1
    poly = [((x0 if first else x0 + o2), 0), (x1 + (0 if last else o2), 0), (x1, H2), (x0, H2)]
    poly[1] = (x1 + (0 if last else o2), 0)
    mask = Image.new("L", (W2, H2), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    contain = fit == "contain"
    lab = max(44, min(72, int(h * 0.14)))                                      # label row height (contain)
    if contain:
        pad = 8
        sx0, sx1 = (0 if first else off), (w - 1 if last else w - off - 1)     # x-range inside the slanted edges at every y
        bx0, by0, bx1, by1 = sx0 + pad, pad, sx1 - pad, h - lab
        ph = Image.new("RGBA", (W2, H2), TILE_BG + (255,))
        src = photo.convert("RGB")
        r = min((bx1 - bx0) / float(src.width), (by1 - by0) / float(src.height))
        pw, pht = max(2, int(src.width * r * SS)), max(2, int(src.height * r * SS))
        pic = src.resize((pw, pht), Image.LANCZOS).convert("RGBA")
        rm = Image.new("L", (pw, pht), 0)
        ImageDraw.Draw(rm).rounded_rectangle((0, 0, pw - 1, pht - 1), radius=min(12 * SS, pw // 2, pht // 2), fill=255)
        pic.putalpha(rm)
        ph.alpha_composite(pic, (int((bx0 + bx1) / 2.0 * SS - pw / 2.0), int((by0 + by1) / 2.0 * SS - pht / 2.0)))
    else:
        ph = ImageOps.fit(photo.convert("RGB"), (W2, H2), Image.LANCZOS, centering=(0.5, 0.4)).convert("RGBA")
        g = Image.linear_gradient("L").resize((W2, H2))                           # 0 top .. 255 bottom
        ga = g.point(lambda v: int(240 * (max(0.0, (v / 255.0 - 0.32) / 0.68) ** 1.15)))
        ph.alpha_composite(Image.merge("RGBA", (*[Image.new("L", (W2, H2), c) for c in MAROON], ga)))
    spr = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    spr.paste(ph, (0, 0), mask)
    d = ImageDraw.Draw(spr)
    if not last:
        d.line([poly[1], poly[2]], fill=(255, 244, 230, 170), width=2 * SS)
    spr = spr.resize((w, h), Image.LANCZOS)
    if contain:
        isz = int(lab * 0.55)
        x, yb = (0 if first else off) + 22, h - (lab - isz) // 2 - 4
        cyr = yb - isz / 2.0
    else:
        isz = int(h * 0.17)
        x, yb = 26 + (0 if first else int(off * 0.3)), h - 18
        cyr = yb - isz / 2.0
    d = ImageDraw.Draw(spr)
    if icon and icon != "none":
        _draw_icon(spr, icon, (x, yb - isz, x + isz, yb), icon_path or None)
        x += isz + 12
    if label:
        fp, _ = t3_font("caps", label, fonts)
        size = max(14, int(lab * 0.42)) if contain else max(14, int(h * 0.105))
        f = ImageFont.truetype(fp, size)
        maxw = w - x - 14 - (0 if last else off)
        while f.getlength(label) > maxw and size > 12:
            size -= 1
            f = ImageFont.truetype(fp, size)
        d.text((x, cyr), label, font=f, fill=(255, 255, 255, 255), anchor="lm")
    return spr


def strip_tile_rects(strip, n, slant_deg):
    """-> [(x, y, w, h, off, first, last)] canvas px of n tiles inside the strip rect (x, y, w, h)."""
    sx, sy, sw, sh = strip
    th = int(round(sh)) - 2 * PAD
    off = int(round(th * math.tan(math.radians(slant_deg))))
    out = []
    for i in range(n):
        b0, b1 = int(round(sw * i / n)), int(round(sw * (i + 1) / n))
        last = i == n - 1
        out.append((int(round(sx)) + b0, int(round(sy)) + PAD, b1 - b0 + (0 if last else off), th, off, i == 0, last))
    return out

def _tile_aspect(cfg, tile):
    """width / height of a tile's photo (image file, or the video for a `frame` tile); 9:16 when unknown."""
    try:
        if tile.get("image"):
            with Image.open(tile["image"]) as im:
                return max(0.2, min(5.0, im.width / float(im.height)))
        if cfg.get("video"):
            from mt.common import probe
            i = probe(cfg["video"])
            return max(0.2, min(5.0, i["width"] / float(i["height"])))
    except Exception:
        pass
    return 9.0 / 16.0


def t3_strip_geom(cfg, base):
    """Strip geometry for a job -> {} (old poster geometry) when the strip is off, else {"strip_h", "gap_t", "gap_b"} in poster px
    (merged into the layout base box by t3_layout_prepare). gap_t = frame -> strip, gap_b = strip -> footer. fit "contain":
    the height lets the photos fill ~90 % of the tile width (+ the label row), between the poster's 245 and STRIP_AREA (34 %)
    of the free height (frame top .. footer); fit "cover": 245. Needs layout.STRIP_H / STRIP_GAP_T / STRIP_GAP_B / STRIP_AREA /
    FOOT_TOP / BAND_X0 / BAND_X1 and static.K."""
    st = t3_strip_cfg((cfg.get("t3") or {}).get("strip"))
    if not st["on"] or not st["sets"]:
        return {}
    gt, gb = _lay.STRIP_GAP_T, _lay.STRIP_GAP_B
    y0 = float((base or {}).get("y", 0.0)) / K
    avail = _lay.FOOT_TOP - gb - gt - y0                       # poster px for the frame + the strip
    lo, hi = _lay.STRIP_H, max(_lay.STRIP_H, _lay.STRIP_AREA * avail)
    want = lo
    if st["fit"] == "contain":
        band_w = _lay.BAND_X1 - _lay.BAND_X0
        for s_ in st["sets"]:
            for t in s_["tiles"]:
                tw = band_w / float(len(s_["tiles"]))
                want = max(want, tw * 0.9 / _tile_aspect(cfg, t) + 56.0 + 2 * PAD / K)
    return {"strip_h": round(min(hi, want), 2), "gap_t": gt, "gap_b": gb}

# ---- items -----------------------------------------------------------------------------------------------------------
def strip_items(cfg, duration, box):
    """Tile Items for one layout segment (box = frame box of that segment). Empty unless strip.on and layout.on."""
    t3 = cfg.get("t3") or {}
    st, lay = t3.get("strip") or {}, t3.get("layout") or {}
    if not st.get("on") or not lay.get("on") or box is None:
        return []
    from mt.templates.t3 import dynamic as _dyn
    st = t3_strip_cfg(st)
    t3n = dict(t3, strip=st)
    sh, gt, _gb = _lay._strip_dims(_lay._base(cfg))               # strip height / frame gap from the job's free area (t3_strip_geom)
    strip = ((_lay.BAND_X0 * K), box["y"] + box["h"] + gt * K, (_lay.BAND_X1 - _lay.BAND_X0) * K, sh * K)
    items, accent = [], t3.get("accent", "#F56D1F")
    c2 = dict(cfg, t3=t3n)
    rows = strip_resolve(c2, duration)
    for si, r in enumerate(rows):
        if not _dyn._vis(r["tile_start"], r["tile_end"]):
            continue
        rects = strip_tile_rects(strip, len(r["tiles"]), st["slant"])
        for i, (tile, (x, y, w, h, off, first, last)) in enumerate(zip(r["tiles"], rects)):
            key = (repr(tile), w, h, off, first, last, accent, str(cfg.get("video")), st["fit"])
            spr = _SPR.get(key)
            if spr is None:
                spr = _SPR[key] = strip_tile_sprite(strip_tile_photo(cfg, tile), tile["label"], tile["icon"], tile["icon_path"],
                                                    w, h, off, first, last, accent, t3.get("fonts"), st["fit"])
            anim = "fade" if st["set_trans"] == "fade" else st["anim"]
            a = r["tile_start"] + i * st["stagger"]
            if a >= r["tile_end"] - 0.1:
                continue
            items.append(Item(spr, a, r["tile_end"], x + w / 2.0, y + h / 2.0, anim, st["anim_dur"], out=True))
    return items


_lay.register_band("strip", ranges=strip_ranges, content=strip_band_content)


# ---- questions -------------------------------------------------------------------------------------------------------
def _tile_src(s):
    """'img.jpg' -> image; '@3.5' or 'frame 3.5' -> video frame at 3.5 s."""
    s = s.strip()
    if s.startswith("@") or s.lower().startswith("frame"):
        v = float(s.lstrip("@").lower().replace("frame", "").strip() or 0)
        return {"frame": v}
    if not os.path.isfile(s.strip('"')):
        raise ValueError("file not found - give an image path, or @seconds for a video frame (e.g. @3.5)")
    return {"image": s.strip('"')}


def t3_ask_strip():
    """Strip questions (Enter = poster default / last answer). Returns the t3 keys to merge ({} = strip off)."""
    from mt.common import D, ask, ask_choice, c_float, yn
    from mt.templates.t3.dynamic import _c_start
    on = yn("Show the photo-tiles strip (3 photo tiles with icon + label, bottom of the poster)?",
            default=D.get("t3_strip", "n") == "y")
    D["t3_strip"] = "y" if on else "n"
    if not on:
        return {}
    sets, i = [], 1
    while i <= MAX_SETS:
        if i > 1 and not yn(f"Add another tile set (set {i})?", default=False):
            break
        kind, val = ask(f"Set {i} starts at (seconds / mm:ss / spoken phrase)", default=str(2 + 6 * (i - 1)),
                        key=f"t3_strip_start{i}", cast=_c_start)
        hold = ask(f"Set {i} stays for (seconds)", default=4.0, key=f"t3_strip_hold{i}", cast=c_float)
        n = int(ask(f"Set {i}: how many tiles (2-4)", default=3, key=f"t3_strip_n{i}", cast=lambda v: max(2, min(4, int(v)))))
        tiles = []
        for j in range(n):
            lab0, ic0 = POSTER_TILES[j] if j < 3 else (f"Tile {j + 1}", "code")
            src = ask(f"  Tile {j + 1} photo (image path, or @seconds = frame of your video)", default=f"@{1 + j}",
                      key=f"t3_strip_src{i}_{j}", cast=_tile_src)
            lab = ask(f"  Tile {j + 1} label", default=lab0, key=f"t3_strip_lab{i}_{j}",
                      cast=lambda v: "" if v.strip() == "-" else v.strip())
            ic = ask(f"  Tile {j + 1} icon ({', '.join(ICONS)}, a PNG/ICO path, or none)", default=ic0,
                     key=f"t3_strip_icon{i}_{j}", cast=lambda v: v.strip().strip('"'))
            tiles.append(dict(src, label=lab, icon=ic))
        sets.append({"start": val if kind == "t" else None, "trigger": val if kind == "p" else "", "hold": hold, "tiles": tiles})
        i += 1
    ch = ask_choice("Tile set change:", ["Slide up", "Fade"], default=1, key="t3_strip_trans")
    return {"strip": {"on": True, "sets": sets, "set_trans": "slide" if ch == 1 else "fade"},
            "layout": {"on": True, "mode": "auto"}}


# =====================================================================================================================
# T3-7: bottom PANEL (poster y 1220-1530): LEFT gallery (play icon + title + 2-4 captioned thumbnails), CENTER = reserved rect
# for T3-8 (dim placeholder until then), RIGHT checklist (film icon + title + up to 6 rows that reveal one by one).
# cfg["t3"]["panel"] = {on, start, trigger, end, left_title, thumbs:[{image | frame | pct, caption}], right_title,
#                       rows:[{text, trigger}], reveal ('stagger'|'trigger'|'all'), stagger, anim, anim_dur}
# Static part (background, dividers, left column, titles, center placeholder) = the band image; rows = timeline Items on top.
# =====================================================================================================================
BROWN = (24, 15, 12)
CREAM = (255, 244, 230)
PANEL_X = {"div1": 370.0, "div2": 730.0, "left0": 30.0, "left1": 360.0, "right0": 740.0, "right1": 912.0}
PANEL_Y0 = 1220.0                                   # poster y of the panel top (= FOOT_TOP - PANEL_H)
MAX_THUMBS, MAX_ROWS = 4, 6
PANEL_DEFAULTS = {"on": False, "start": None, "trigger": "", "end": None, "left_title": "TEMPLATE VARIATIONS",
                  "thumbs": [], "right_title": "KEY ANIMATIONS", "rows": [], "reveal": "stagger", "stagger": 0.45,
                  "anim": "fade", "anim_dur": 0.3}
DEFAULT_PCT = (0.10, 0.40, 0.70)
DEFAULT_CAPTIONS = ("Variation 1", "Variation 2", "Variation 3", "Variation 4")
DEFAULT_ROWS = ("Chapter tag slide-ins", "Floating photo cards", "Adaptive video frame", "Animated captions",
                "Photo tiles strip", "Smooth band reveals")
_PSPR = {}

# ---- T3 outro (next-episode card in the panel band area) ------------------------------------------------------------------
OUTRO_ANIMS = ("tile_up", "fade", "slide_up", "slide_left", "slide_right", "pop", "zoom_in", "none")
OUTRO_DEFAULTS = {"on": False, "start": None, "end": None, "title_ar": "", "title_en": "", "next_number": "",
                  "anim": "tile_up", "anim_dur": 0.4}
OUTRO_FALLBACK = ("\u062a\u0627\u0628\u0639 \u0627\u0644\u062d\u0644\u0642\u0629 \u0627\u0644\u062c\u0627\u064a\u0629", "Follow the next episode")
OUTRO_STEP = 0.05                                   # seconds per arrow position (the arrow is a chain of tiny Items)
OUTRO_LOOP = 1.1                                    # seconds per arrow pulse
_OSPR = {}


def _norm_thumb(t, i):
    if isinstance(t, str):
        t = {"image": t}
    if not isinstance(t, dict):
        return None
    img, fr, pct = str(t.get("image") or "").strip(), _num(t.get("frame")), _num(t.get("pct"))
    if not img and fr is None and pct is None:
        pct = DEFAULT_PCT[i % 3]
    return {"image": img, "frame": None if img or fr is None else max(0.0, fr),
            "pct": None if img or fr is not None else min(1.0, max(0.0, pct)),
            "caption": str(t.get("caption", DEFAULT_CAPTIONS[i % 4]) or "").strip()}


def t3_panel_cfg(raw=None):
    """Normalise cfg['t3']['panel'] (idempotent). thumbs: 2-4 usable ones, [] -> 3 auto frames (10/40/70 % of the video)
    when the panel is on; rows: up to 6 (str or {text, trigger}); [] -> the default list when on."""
    raw = raw if isinstance(raw, dict) else {}
    d = {k: (list(v) if isinstance(v, list) else v) for k, v in PANEL_DEFAULTS.items()}
    d["on"] = bool(raw.get("on", d["on"]))
    for k in ("start", "end"):
        d[k] = _num(raw.get(k))
    d["trigger"] = str(raw.get("trigger") or "").strip()
    for k in ("left_title", "right_title"):
        if k in raw:
            d[k] = str(raw[k] or "").strip()
    for k, lo, hi in (("stagger", 0.0, 3.0), ("anim_dur", 0.1, 2.0)):
        v = _num(raw.get(k))
        d[k] = d[k] if v is None else max(lo, min(hi, v))
    d["anim"] = str(raw.get("anim") or d["anim"])
    rv = str(raw.get("reveal", d["reveal"])).strip().lower()
    d["reveal"] = rv if rv in ("stagger", "trigger", "all") else "stagger"
    th = [t for t in (_norm_thumb(x, i) for i, x in enumerate((raw.get("thumbs") or [])[:MAX_THUMBS])) if t]
    d["thumbs"] = th if len(th) >= 2 else [_norm_thumb({}, i) for i in range(3)]
    rows = []
    src = raw.get("rows") if isinstance(raw.get("rows"), (list, tuple)) else DEFAULT_ROWS
    for r in list(src)[:MAX_ROWS]:
        r = {"text": r} if isinstance(r, str) else r
        if isinstance(r, dict) and str(r.get("text") or "").strip():
            rows.append({"text": str(r["text"]).strip(), "trigger": str(r.get("trigger") or "").strip()})
    d["rows"] = rows
    return d


def _pcfg(cfg):
    p = (cfg.get("t3") or {}).get("panel")
    return p if isinstance(p, dict) and "reveal" in p and "thumbs" in p else t3_panel_cfg(p)


def t3_panel_rect():
    """Final canvas rect (x, y, w, h) of the panel band."""
    return _lay.t3_layout("S2")["panel"]


def _pt(panel_rect, px, py):
    """poster coords -> canvas coords for a panel rect."""
    x, y, w, h = panel_rect
    kx = w / ((_lay.BAND_X1 - _lay.BAND_X0) * K)
    return x + (px - _lay.BAND_X0) * K * kx, y + (py - PANEL_Y0) * K * (h / (_lay.PANEL_H * K))


def t3_panel_center_rect(panel_rect):
    """(x, y, w, h) canvas px of the reserved CENTER column inside panel_rect = (x, y, w, h) (the band's canvas rect, e.g.
    t3_layout('S2')['panel']). Poster x 380..720, y 1232..1520. T3-8 draws its content inside it."""
    x0, y0 = _pt(panel_rect, PANEL_X["div1"] + 10, 1232.0)
    x1, y1 = _pt(panel_rect, PANEL_X["div2"] - 10, 1520.0)
    return (x0, y0, x1 - x0, y1 - y0)


def _panel_trigger_time(cues, phrase):
    for c in cues:
        t = find_trigger(c, phrase)
        if t is not None:
            return float(t)
    return None


def panel_resolve(cfg, duration):
    """-> None (panel off) or {band_start, start, end, rows:[(text, reveal_time)]} (seconds). Panel = visible from its first content
    start to its last content end (start/trigger and end override); the band starts `trans` s before the first row."""
    p = _pcfg(cfg)
    if not p["on"]:
        return None
    tr = float(((cfg.get("t3") or {}).get("layout") or {}).get("trans", 0.5))
    cues = _cues(cfg)
    trig = {i: _panel_trigger_time(cues, r["trigger"]) for i, r in enumerate(p["rows"]) if r["trigger"]}
    c0 = _panel_trigger_time(cues, p["trigger"]) if p["trigger"] else None
    if c0 is None:
        c0 = p["start"]
    if c0 is None:
        found = [v for v in trig.values() if v is not None]
        c0 = min(found) if (p["reveal"] == "trigger" and found) else 1.0
    band0 = max(0.0, c0 - tr)
    base = max(c0, band0 + tr + 0.05)
    rows = []
    for i, r in enumerate(p["rows"]):
        if p["reveal"] == "all":
            t = base
        elif p["reveal"] == "trigger" and trig.get(i) is not None:
            t = max(base, trig[i])
        else:
            if p["reveal"] == "trigger" and r["trigger"]:
                t3_warn(f"   [!] panel row '{r['text']}': phrase '{r['trigger']}' not found - staggered instead.")
            t = base + i * p["stagger"]
        rows.append((r["text"], t))
    last = max([t for _, t in rows] + [base])
    end = p["end"] if p["end"] is not None else max(duration, last + 1.0)
    end = max(end, c0 + 0.5)
    if c0 >= duration:
        return None
    return {"band_start": band0, "start": c0, "end": end, "rows": rows}


def panel_ranges(cfg, duration):
    """band provider: [(band_start, end)] of the panel (AUTO layout)."""
    r = panel_resolve(cfg, duration)
    return [(r["band_start"], r["end"])] if r else []


def _ptfont(text, size, fonts=None, role="caps"):
    fp, _ = t3_font(role, text, fonts)
    return ImageFont.truetype(fp, max(8, int(size)))


def _fit_font(text, size, maxw, fonts=None, role="caps", lo=11):
    f = _ptfont(text, size, fonts, role)
    while f.getlength(text) > maxw and size > lo:
        size -= 1
        f = _ptfont(text, size, fonts, role)
    return f


def _wrap2(text, font, maxw):
    """-> up to 2 lines that fit maxw (last line ellipsised)."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if font.getlength(t) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
    if len(lines) == 2:
        while font.getlength(lines[1]) > maxw and len(lines[1]) > 2:
            lines[1] = lines[1][:-2] + "\u2026"
    return lines


def _draw_play(d, cx, cy, s, col):
    d.polygon([(cx - s * 0.38, cy - s * 0.5), (cx - s * 0.38, cy + s * 0.5), (cx + s * 0.52, cy)], fill=col)


def _draw_film(d, x, y, s, col):
    """film-strip icon in the s x s box at (x, y): outlined rounded rect + perforation squares on both long sides + centre frame."""
    wid = max(2, int(s * 0.08))
    d.rounded_rectangle((x, y + s * 0.12, x + s, y + s * 0.88), radius=s * 0.1, outline=col, width=wid)
    q = s * 0.09
    for i in range(4):
        yy = y + s * 0.2 + i * s * 0.18
        d.rectangle((x + s * 0.1, yy, x + s * 0.1 + q, yy + q), fill=col)
        d.rectangle((x + s * 0.9 - q, yy, x + s * 0.9, yy + q), fill=col)
    d.rectangle((x + s * 0.32, y + s * 0.3, x + s * 0.68, y + s * 0.7), outline=col, width=max(1, wid - 1))


def _dark_panel(w, h, seed=7):
    """dark brown-black panel with a subtle grain and a thin top edge."""
    import random
    rnd = random.Random(seed)
    n = Image.effect_noise((w, h), 14).convert("L").point(lambda v: int(v * 0.12))
    base = Image.new("RGB", (w, h), BROWN)
    base = ImageChops.add(base, Image.merge("RGB", (n, n.point(lambda v: int(v * 0.8)), n.point(lambda v: int(v * 0.7)))))
    vg = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(v * 0.08))      # slightly lighter toward the bottom
    base = ImageChops.add(base, Image.merge("RGB", (vg, vg, vg)))
    out = base.convert("RGBA")
    ImageDraw.Draw(out).line([(0, 0), (w, 0)], fill=(255, 244, 230, 90), width=2)
    return out


def panel_thumb_photo(cfg, th):
    """RGB photo of a panel thumbnail: image file, video frame at th['frame'] s, or at th['pct'] of the video duration."""
    t = dict(th)
    if t.get("pct") is not None and not t.get("image"):
        dur = 0.0
        try:
            from mt.common import probe
            dur = float(probe(cfg["video"])["duration"]) if cfg.get("video") else 0.0
        except Exception:
            dur = 0.0
        t["frame"] = max(0.0, dur * t["pct"] - 0.05) if dur else 0.0
    return strip_tile_photo(cfg, t)


def panel_band_content(cfg, w, h):
    """Band image (w x h) of the panel: background + dividers + LEFT column + right title + center placeholder (rows are Items)."""
    p = _pcfg(cfg)
    if not p["on"]:
        return None                                                        # panel off: the layout engine's dim placeholder (T3-5 behaviour)
    t3 = cfg.get("t3") or {}
    accent = t3.get("accent", "#F56D1F")
    acc = tuple(int(str(accent).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,) if str(accent).startswith("#") else (245, 109, 31, 255)
    fonts = t3.get("fonts")
    out = _dark_panel(w, h)
    d = ImageDraw.Draw(out)
    kx = w / ((_lay.BAND_X1 - _lay.BAND_X0) * K)
    ky = h / (_lay.PANEL_H * K)
    P = lambda px, py: ((px - _lay.BAND_X0) * K * kx, (py - PANEL_Y0) * K * ky)
    for dx in (PANEL_X["div1"], PANEL_X["div2"]):
        x, y0 = P(dx, 1236)
        _, y1 = P(dx, 1516)
        d.line([(x, y0), (x, y1)], fill=(255, 244, 230, 60), width=2)
    # LEFT column
    lx0, ty = P(PANEL_X["left0"], 1250)
    lx1, _ = P(PANEL_X["left1"], 0)
    isz = 26 * K * kx
    _draw_play(d, lx0 + isz / 2, ty, isz, acc)
    tf = _fit_font(p["left_title"], 17 * K * kx, lx1 - lx0 - isz - 14, fonts)
    d.text((lx0 + isz + 12, ty), p["left_title"], font=tf, fill=CREAM + (255,), anchor="lm")
    n = len(p["thumbs"])
    gap = 12 * K * kx if n <= 3 else 8 * K * kx
    tw = min(100 * K * kx, (lx1 - lx0 - (n - 1) * gap) / n)
    th_h = 135 * K * ky
    ty0 = P(0, 1272)[1]
    for i, th in enumerate(p["thumbs"]):
        x = lx0 + i * (tw + gap)
        W2, H2 = int(round(tw)), int(round(th_h))
        ph = ImageOps.fit(panel_thumb_photo(cfg, th), (W2 * 2, H2 * 2), Image.LANCZOS, centering=(0.5, 0.4)).convert("RGBA")
        m = Image.new("L", (W2 * 2, H2 * 2), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, W2 * 2 - 1, H2 * 2 - 1), radius=14, fill=255)
        ImageDraw.Draw(ph).rounded_rectangle((1, 1, W2 * 2 - 2, H2 * 2 - 2), radius=14, outline=CREAM + (235,), width=4)
        ph = ph.resize((W2, H2), Image.LANCZOS)
        m = m.resize((W2, H2), Image.LANCZOS)
        out.paste(ph, (int(round(x)), int(round(ty0))), m)
        if th["caption"]:
            cf = _fit_font(th["caption"], 11.5 * K * kx, tw + gap - 2, fonts, role="caps", lo=10)
            lines = _wrap2(th["caption"], cf, tw + gap - 2)
            for li, ln in enumerate(lines):
                d.text((x + tw / 2, ty0 + th_h + 8 * K + li * (cf.size + 2)), ln, font=cf, fill=CREAM + (235,), anchor="ma")
    # RIGHT title
    rx0, ry = P(PANEL_X["right0"], 1250)
    rx1, _ = P(PANEL_X["right1"], 0)
    _draw_film(d, rx0, ry - isz / 2, isz, acc)
    tf = _fit_font(p["right_title"], 17 * K * kx, rx1 - rx0 - isz - 14, fonts)
    d.text((rx0 + isz + 10, ry), p["right_title"], font=tf, fill=CREAM + (255,), anchor="lm")
    # CENTER column (T3-8): slot header when the slot is on (empty slot: nothing), else the dim placeholder
    from mt.templates.t3 import slot as _slot
    if _slot._scfg(cfg)["on"]:
        hl = _slot.slot_header(cfg, t3_panel_rect()[:2], w, h)
        if hl is not None:
            out.alpha_composite(hl)
        return out
    c0 = P(PANEL_X["div1"] + 10, 1232)
    c1 = P(PANEL_X["div2"] - 10, 1520)
    ph = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(ph).rounded_rectangle((*c0, *c1), radius=10, fill=(255, 244, 230, 14), outline=(255, 244, 230, 40), width=1)
    out.alpha_composite(ph)
    return out


def _row_size(text, w, h, fonts=None):
    """largest font size (<= 0.48 h, >= 0.34 h) at which `text` fits one line of a row (min size if it never fits -> 2 lines)."""
    x = int(2 * h * 0.30 + 4 + 10)
    size = h * 0.48
    f = _ptfont(text, size, fonts)
    while f.getbbox(text)[2] > w - x - 10 and size > h * 0.34:
        size -= 1
        f = _ptfont(text, size, fonts)
    return size


def _check_sprite(text, w, h, acc, fonts=None, size=None):
    """One checklist row (w x h RGBA): orange filled check-circle + white text auto-fitted (shrinks, then 2 lines)."""
    SS = 2
    spr = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(spr)
    r = h * SS * 0.30
    cx, cy = r + 2 * SS, h * SS / 2.0
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=acc)
    d.line([(cx - r * 0.5, cy + r * 0.02), (cx - r * 0.12, cy + r * 0.42), (cx + r * 0.55, cy - r * 0.38)], fill=BROWN + (255,),
           width=max(2, int(r * 0.22)), joint="curve")
    spr = spr.resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(spr)
    x = int(2 * r / SS + 4 + 10)
    maxw = w - x - 10
    size = size or _row_size(text, w, h, fonts)
    f = _ptfont(text, size, fonts)
    lines = [text]
    if f.getbbox(text)[2] > maxw:                       # does not fit on one line at the common size -> smaller font, up to 2 lines
        f = _ptfont(text, max(10, h * 0.30), fonts)
        lines = _wrap2(text, f, maxw)
    lh = f.size + 1
    y0 = h / 2.0 - lh * (len(lines) - 1) / 2.0
    for i, ln in enumerate(lines):
        d.text((x, y0 + i * lh), ln, font=f, fill=(255, 255, 255, 255), anchor="lm")
    return spr


def panel_items(cfg, duration, box=None):
    """Checklist row Items (constant position: the panel band never moves). Empty unless panel.on and layout.on."""
    t3 = cfg.get("t3") or {}
    lay = t3.get("layout") or {}
    p = _pcfg(cfg)
    if not p["on"] or not lay.get("on"):
        return []
    from mt.templates.t3 import dynamic as _dyn
    res = panel_resolve(cfg, duration)
    if not res:
        return []
    acc = t3.get("accent", "#F56D1F")
    acc = (tuple(int(acc.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,)) if str(acc).startswith("#") else (245, 109, 31, 255)
    pr = t3_panel_rect()
    x0, y0 = _pt(pr, PANEL_X["right0"], 1280)
    x1, _ = _pt(pr, PANEL_X["right1"], 0)
    _, yb = _pt(pr, 0, 1522)
    n = max(1, len(res["rows"]))
    rh = min(int((yb - y0) / n), int(40 * K))
    w, h = int(x1 - x0), rh
    items = []
    size = min([_row_size(tx, w, h, t3.get("fonts")) for tx, _ in res["rows"]] or [h * 0.48])      # one font size for all rows
    for i, (text, t) in enumerate(res["rows"]):
        end = res["end"] - 0.05
        if t >= end - 0.1 or not _dyn._vis(t, end):
            continue
        key = (text, w, h, acc, size, repr(t3.get("fonts")))
        spr = _PSPR.get(key)
        if spr is None:
            spr = _PSPR[key] = _check_sprite(text, w, h, acc, t3.get("fonts"), size)
        items.append(Item(spr, t, end, x0 + w / 2.0, y0 + i * rh + rh / 2.0, p["anim"], p["anim_dur"], out=True))
    from mt.templates.t3 import slot as _slot                         # T3-8: centre content blocks
    return items + _slot.slot_items(cfg, duration)


_lay.register_band("panel", ranges=panel_ranges, content=panel_band_content)

def t3_outro_cfg(raw=None):
    """Normalise cfg['t3']['outro'] (idempotent) = {on, start, end, title_ar, title_en, next_number, anim, anim_dur}.
    start / end in seconds (None: end = end of the video, start = 5 s before the end); next_number '7' -> '07';
    both titles empty -> the default 'next episode' text when the outro is on."""
    raw = raw if isinstance(raw, dict) else {}
    d = dict(OUTRO_DEFAULTS)
    d["on"] = bool(raw.get("on", d["on"]))
    for k in ("start", "end"):
        d[k] = _num(raw.get(k))
    for k in ("title_ar", "title_en"):
        d[k] = str(raw.get(k) or "").strip()
    n = raw.get("next_number")
    n = "" if n is None else str(n).strip()
    d["next_number"] = (n.zfill(2) if n.isdigit() else n)[:3]
    a = str(raw.get("anim") or d["anim"]).strip().lower()
    d["anim"] = a if a in OUTRO_ANIMS else d["anim"]
    v = _num(raw.get("anim_dur"))
    d["anim_dur"] = d["anim_dur"] if v is None else max(0.1, min(2.0, v))
    return d


def _ocfg(cfg):
    o = (cfg.get("t3") or {}).get("outro")
    return o if isinstance(o, dict) and "title_ar" in o and "next_number" in o and "anim_dur" in o else t3_outro_cfg(o)


def outro_resolve(cfg, duration):
    """-> None (outro off / starts after the video) or {band_start, start, end} seconds. The band (same transition as the panel)
    starts `trans` s before `start`, so the card appears on the fully shown band."""
    o = _ocfg(cfg)
    if not o["on"]:
        return None
    tr = float(((cfg.get("t3") or {}).get("layout") or {}).get("trans", 0.5))
    end = float(duration) if o["end"] is None else float(o["end"])
    start = max(0.0, o["start"] if o["start"] is not None else end - 5.0)
    if start >= duration:
        return None
    band0 = max(0.0, start - tr)
    return {"band_start": band0, "start": max(start, band0 + tr), "end": max(end, start + 0.6)}


def outro_ranges(cfg, duration):
    """band provider part: [(band_start, end)] of the outro. layout.t3_band_active_ranges adds it to the PANEL ranges, so the
    outro uses the panel's frame shrink / band slide-in (and merges with the panel when they touch)."""
    r = outro_resolve(cfg, duration)
    return [(r["band_start"], r["end"])] if r else []


def _outro_titles(o):
    return (o["title_ar"], o["title_en"]) if (o["title_ar"] or o["title_en"]) else OUTRO_FALLBACK


def _outro_geom(w, h):
    """Anchors inside a band of w x h px: card rect, number zone (x0, x1), divider x, arrow centre x, title zone (x0, x1), centre y."""
    return {"card": (int(w * 0.022), int(h * 0.075), int(w * 0.978), int(h * 0.925)), "num": (w * 0.05, w * 0.325),
            "div": w * 0.345, "arrow": w * 0.435, "title": (w * 0.535, w * 0.955), "cy": h * 0.5}


def _outro_rgb(accent):
    from mt.draw import t2_rgb
    return t2_rgb(accent or "#F56D1F")


def outro_band_bg(cfg, w, h):
    """Static card background (w x h RGBA, opaque): the panel's dark grain + cream top edge, a rounded cream-outlined card, an accent
    corner bracket and a thin divider between the number and the title. Used as the band image when the panel is off AND as the
    cover Item that replaces the panel gallery when the panel is on."""
    acc = _outro_rgb((cfg.get("t3") or {}).get("accent"))
    key = ("bg", w, h, acc)
    if key in _OSPR:
        return _OSPR[key]
    out = _dark_panel(w, h)
    g = _outro_geom(w, h)
    SS = 2
    ov = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    x0, y0, x1, y1 = [v * SS for v in g["card"]]
    d.rounded_rectangle((x0, y0, x1, y1), radius=18 * SS, fill=CREAM + (9,), outline=CREAM + (110,), width=2 * SS)
    dv = g["div"] * SS
    d.line([(dv, y0 + 26 * SS), (dv, y1 - 26 * SS)], fill=CREAM + (60,), width=2 * SS)
    bl = 64 * SS                                                       # accent corner bracket (like the frame's orange bracket)
    d.line([(x0 - 6 * SS, y0 + bl), (x0 - 6 * SS, y0 - 6 * SS), (x0 + bl, y0 - 6 * SS)], fill=acc + (255,), width=5 * SS,
           joint="curve")
    out.alpha_composite(ov.resize((w, h), Image.LANCZOS))
    _OSPR[key] = out
    return out


def _outro_font(text, role, fonts):
    from mt.fonts import has_arabic
    if has_arabic(text):
        ov = (fonts or {}).get("arabic")
        if ov and os.path.isfile(str(ov)):
            return ov, 0.0
    return t3_font(role, text, fonts)


def outro_number_sprite(num, accent, zone_w, zone_h, fonts):
    """Big accent heavy-italic number + cream '/' (same look as the chapter tag) fitted into zone_w x zone_h."""
    from mt.draw import t2_paint, t2_size_for_cap, t2_text_mask
    acc = _outro_rgb(accent)
    key = ("num", num, acc, int(zone_w), int(zone_h), repr(fonts))
    if key in _OSPR:
        return _OSPR[key]
    hf, hsh = t3_font("head", num or "0", fonts)
    cap = zone_h * 0.72
    while True:
        nm = t2_text_mask(num, hf, t2_size_for_cap(hf, cap), -0.01, hsh)
        sl = t2_text_mask("/", hf, t2_size_for_cap(hf, cap), 0.0, hsh)
        gap = max(4, int(cap * 0.12))
        row_w = nm.width + gap + sl.width
        if row_w <= zone_w or cap < 24:
            break
        cap *= 0.93
    spr = Image.new("RGBA", (int(row_w) + 8, int(max(nm.height, sl.height)) + 8), (0, 0, 0, 0))
    t2_paint(spr, (nm, (4, 4)), acc + (255,))
    t2_paint(spr, (sl, (4 + nm.width + gap, 4)), CREAM + (255,))
    _OSPR[key] = spr
    return spr


def outro_title_sprite(ar, en, accent, zone_w, zone_h, fonts):
    """Title block (zone_w wide): Arabic title (RTL, shaped, auto-fit / 2 lines) + accent line + English caps line.
    Right-aligned when the title is Arabic, left-aligned otherwise."""
    from mt.draw import t2_paint, t2_size_for_cap, t2_text_mask
    from mt.fonts import has_arabic, load_font, shape, wrap_lines
    acc = _outro_rgb(accent)
    zone_w, zone_h = int(zone_w), int(zone_h)
    key = ("title", ar, en, acc, zone_w, zone_h, repr(fonts))
    if key in _OSPR:
        return _OSPR[key]
    right = bool(ar) and has_arabic(ar)
    masks = []
    if ar:
        af, ash = _outro_font(ar, "caps", fonts)
        sa = int(min(80, zone_h * 0.36))
        wid = lambda sz: load_font(af, sz).getlength(shape(ar))
        while wid(sa) > zone_w and sa > 46:
            sa -= 2
        lines = [ar] if wid(sa) <= zone_w else wrap_lines(ar, load_font(af, sa), zone_w)
        while len(lines) > 2 and sa > 30:
            sa -= 2
            lines = wrap_lines(ar, load_font(af, sa), zone_w)
        for ln in lines[:2]:
            m = t2_text_mask(ln, af, sa, 0.0, ash)
            if m.width > zone_w:
                m = m.resize((zone_w, max(1, int(m.height * zone_w / float(m.width)))), Image.LANCZOS)
            masks.append(m)
    em = None
    if en:
        ef, esh = _outro_font(en, "caps", fonts)
        txt = en.upper()
        se = int(min(34, zone_h * 0.15))
        em = t2_text_mask(txt, ef, se, 0.10, esh)
        while em.width > zone_w and se > 14:
            se -= 1
            em = t2_text_mask(txt, ef, se, 0.10, esh)
    gap1, gap2, lh, line_h = 16, 14, 8, 4
    stack_h = sum(m.height for m in masks) + lh * max(0, len(masks) - 1)
    ly = (stack_h + gap1) if masks else 0
    total = ly + line_h + ((gap2 + em.height) if em else 0) + 8
    spr = Image.new("RGBA", (zone_w, max(8, int(total))), (0, 0, 0, 0))
    d = ImageDraw.Draw(spr)
    y = 0
    for m in masks:
        t2_paint(spr, (m, ((zone_w - m.width) if right else 0, y)), CREAM + (255,))
        y += m.height + lh
    lw = int(zone_w * 0.62)
    d.rounded_rectangle(((zone_w - lw) if right else 0, ly, (zone_w if right else lw), ly + line_h), radius=2, fill=acc + (255,))
    if em:
        t2_paint(spr, (em, ((zone_w - em.width) if right else 0, ly + line_h + gap2)), CREAM + (225,))
    _OSPR[key] = spr
    return spr


def outro_arrow_sprite(accent, w, h):
    """Left-pointing arrow (RTL 'next'): rounded shaft + chevron head, accent color."""
    acc = _outro_rgb(accent) + (255,)
    key = ("arrow", acc, int(w), int(h))
    if key in _OSPR:
        return _OSPR[key]
    SS = 4
    im = Image.new("RGBA", (int(w) * SS, int(h) * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    th = max(2, int(h * 0.17 * SS))
    cy, xt, xe, hd = h * SS / 2.0, w * 0.07 * SS, w * 0.93 * SS, h * 0.36 * SS
    d.line([(xt + th * 0.3, cy), (xe, cy)], fill=acc, width=th)
    d.line([(xt + hd, cy - hd), (xt + th * 0.3, cy), (xt + hd, cy + hd)], fill=acc, width=th, joint="curve")
    for px, py in ((xe, cy), (xt + hd, cy - hd), (xt + hd, cy + hd)):
        d.ellipse((px - th / 2.0, py - th / 2.0, px + th / 2.0, py + th / 2.0), fill=acc)
    spr = im.resize((int(w), int(h)), Image.LANCZOS)
    _OSPR[key] = spr
    return spr


def outro_items(cfg, duration):
    """Outro Items in the panel band rect (constant position: the panel band never moves): cover (card background, hides the panel
    gallery) -> number -> title block -> arrow (faint track + a pulsing arrow made of tiny Items). Captions need no handling: the
    outro's band range makes the frame shrink exactly like the panel, so the frame-relative captions move up with it.
    [] unless outro.on and layout.on."""
    t3 = cfg.get("t3") or {}
    if not (t3.get("layout") or {}).get("on"):
        return []
    r = outro_resolve(cfg, duration)
    if not r:
        return []
    from mt.templates.t3 import dynamic as _dyn
    t0, t1 = r["start"], r["end"]
    if not _dyn._vis(t0, t1):
        return []
    o = _ocfg(cfg)
    ar, en = _outro_titles(o)
    fonts, accent = t3.get("fonts"), t3.get("accent", "#F56D1F")
    px, py, pw, ph = t3_panel_rect()
    w, h = int(round(pw)), int(round(ph))
    g = _outro_geom(w, h)
    cx0, cy0 = px + w / 2.0, py + g["cy"]
    an, ad = o["anim"], o["anim_dur"]
    items = [Item(outro_band_bg(cfg, w, h), t0, t1, px + w / 2.0, py + h / 2.0, "fade", min(0.3, ad), True)]
    if o["next_number"]:
        nz0, nz1 = g["num"]
        spr = outro_number_sprite(o["next_number"], accent, nz1 - nz0, h * 0.62, fonts)
        items.append(Item(spr, t0 + 0.05, t1, px + (nz0 + nz1) / 2.0, cy0, an, ad, True))
    tz0, tz1 = g["title"]
    items.append(Item(outro_title_sprite(ar, en, accent, tz1 - tz0, h * 0.66, fonts), t0 + 0.15, t1,
                      px + (tz0 + tz1) / 2.0, cy0, an, ad, True))
    aw, ah = int(w * 0.11), int(h * 0.2)
    spr = outro_arrow_sprite(accent, aw, ah)
    ax, a0 = px + g["arrow"], t0 + 0.3
    if a0 < t1 - 0.2:
        items.append(Item(spr, a0, t1, ax, cy0, "fade", 0.3, True, 0.22))                       # faint track at rest
        n = int((t1 - a0) / OUTRO_STEP)
        for k in range(n):
            a, b = a0 + k * OUTRO_STEP, a0 + (k + 1) * OUTRO_STEP
            if not _dyn._vis(a, b):
                continue
            u = (((a + b) / 2.0 - a0) % OUTRO_LOOP) / OUTRO_LOOP
            e = u * u * (3 - 2 * u)
            op = math.sin(math.pi * u) ** 0.6
            items.append(Item(spr, a, b, ax + 16 - 46 * e, cy0, "none", 0.0, False, op))
    return items

def t3_ask_panel():
    """Panel questions (Enter = default / last answer). Returns the t3 keys to merge ({} = panel off)."""
    from mt.common import D, ask, ask_choice, c_float, yn
    from mt.templates.t3.dynamic import _c_start
    on = yn("Show the bottom panel (gallery on the left, checklist on the right)?", default=D.get("t3_panel", "n") == "y")
    D["t3_panel"] = "y" if on else "n"
    if not on:
        return {}
    kind, val = ask("Panel appears at (seconds / mm:ss / spoken phrase)", default="1", key="t3_panel_start", cast=_c_start)
    end = ask("Panel disappears at (seconds, Enter = end of video)", default="", key="t3_panel_end", allow_empty=True,
              cast=lambda v: None if not v.strip() else float(v))
    lt = ask("Left title", default=PANEL_DEFAULTS["left_title"], key="t3_panel_ltitle", cast=lambda v: v.strip())
    n = int(ask("How many thumbnails (2-4)", default=3, key="t3_panel_nth", cast=lambda v: max(2, min(4, int(v)))))
    thumbs = []
    for j in range(n):
        src = ask(f"  Thumbnail {j + 1} (image path, @seconds, or Enter = auto frame)", default="auto", key=f"t3_panel_th{j}",
                  cast=lambda v: {} if v.strip().lower() in ("", "auto") else _tile_src(v))
        cap = ask(f"  Thumbnail {j + 1} caption", default=DEFAULT_CAPTIONS[j], key=f"t3_panel_cap{j}",
                  cast=lambda v: "" if v.strip() == "-" else v.strip())
        thumbs.append(dict(src, caption=cap))
    rt = ask("Right title", default=PANEL_DEFAULTS["right_title"], key="t3_panel_rtitle", cast=lambda v: v.strip())
    nr = int(ask("How many checklist rows (1-6)", default=len(DEFAULT_ROWS), key="t3_panel_nrow",
                 cast=lambda v: max(1, min(6, int(v)))))
    rv = ask_choice("Checklist rows appear:", ["One by one (stagger)", "Each at a spoken phrase", "All at once"], default=1,
                    key="t3_panel_reveal")
    rows = []
    for j in range(nr):
        txt = ask(f"  Row {j + 1} text", default=DEFAULT_ROWS[j], key=f"t3_panel_row{j}", cast=lambda v: v.strip())
        trg = ask(f"  Row {j + 1} spoken phrase", default="", key=f"t3_panel_rtr{j}", allow_empty=True, cast=lambda v: v.strip()) \
            if rv == 2 else ""
        rows.append({"text": txt, "trigger": trg})
    from mt.templates.t3.slot import t3_ask_slot                       # T3-8: centre content slot
    slot = t3_ask_slot()
    return {"slot": slot["slot"], "panel": {"on": True, "start": val if kind == "t" else None, "trigger": val if kind == "p" else "", "end": end,
                      "left_title": lt, "thumbs": thumbs, "right_title": rt, "rows": rows,
                      "reveal": ("stagger", "trigger", "all")[rv - 1]},
            "layout": {"on": True, "mode": "auto"}}
