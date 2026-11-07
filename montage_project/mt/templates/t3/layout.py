"""mt.templates.t3.layout - T3-5 adaptive layout engine.

The video frame starts LARGE and shrinks when the optional bands (photo-tiles STRIP, bottom PANEL) appear.
Geometry is in poster px (941x1672, x K = canvas px). Bands are stacked bottom-up above the footer:
    footer top 1530 | PANEL h 310 | gap 10 | STRIP h 245 | gap 10 | frame bottom
    S0 = no bands, S1 = strip only, S2 = panel only, S3 = both (= exactly the poster).
Two scalar "presence" tracks s(t), p(t) in 0..1 drive everything (frame box, band position / fade, caption anchors):
    frame_bottom = 1520 - 310 p - 245 s - 10 p s   (poster px),  frame top / x / w never move.
Render approach (cost report in the T3-5 notes): the video is scaled per frame by ONE ffmpeg `scale` (eval=frame, time expression);
a full-canvas opaque plate (design + hole + frame border) is pre-drawn once per STATE and once per FRAME inside a transition
(0.5 s = 15 small PNGs, only a bbox-crop is recomputed) and overlaid with enable windows; bands = tiny looped PNGs with
overlay y-expressions + fade. Items (captions, chapter tag, cards) are re-anchored per frame inside a transition (pieces)."""
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from mt.captions import caption_streams, find_trigger, parse_srt
from mt.common import probe
from mt.draw import Item
from mt.templates.t3 import dynamic as _dyn
from mt.templates.t3.static import t3_warn, K, VIDEO_BOX, TAG_BOX, UNDERLINE, t3_font, t3_frame_layer, t3_headline_layer

# ---- poster geometry ------------------------------------------------------------------------------------------------
FOOT_TOP, PANEL_H, STRIP_H, GAP = 1530.0, 310.0, 245.0, 10.0
STRIP_GAP_T, STRIP_GAP_B, STRIP_AREA = 28.0, 26.0, 0.34       # strip gaps (poster px): frame->strip, strip->footer; max strip share of the free height
BAND_X0, BAND_X1 = 22.0, 919.0
SLIDE = 40.0                                   # poster px a band slides up while it fades in
STATES = {"S0": (0.0, 0.0), "S1": (1.0, 0.0), "S2": (0.0, 1.0), "S3": (1.0, 1.0)}
LAYOUT_DEFAULTS = {"on": False, "mode": "auto", "start": "S0", "trans": 0.5, "events": []}
SPLIT_LEFT, SPLIT_GAP = 0.56, 0.05             # S4 (T3-9): left frame = 56 % of the frame width, gap 5 %, right frame = the rest
SPLIT_DEFAULTS = {"on": False, "segments": [], "merge": 0.3}
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
EL_PLACES = ("side", "inside", "plain")          # element / video-layer placement in T3 (default "side" for elements)
EL_SIDE_GAP, EL_SIDE_EDGE, EL_SIDE_MIN_W, EL_SIDE_MIN_LIFE = 26.0, 40.0, 200.0, 1.0   # px: gap to the frame edge / to the canvas edge / smallest readable card width


# ---- cfg ------------------------------------------------------------------------------------------------------------
def _state_name(v, default="S0"):
    s = str(v).strip().upper()
    if s.isdigit() and 0 <= int(s) <= 3:
        s = "S" + s
    return s if s in STATES else default


def t3_layout_cfg(raw=None):
    """Normalise cfg['t3']['layout'] = {on, mode 'auto'|'manual', start 'S0'.., trans seconds, events [{at | trigger, state}]}.
    `on` is False by default: the old fixed poster geometry is kept until the layout is switched on (back-compat)."""
    raw = raw if isinstance(raw, dict) else {}
    d = {k: (list(v) if isinstance(v, list) else v) for k, v in LAYOUT_DEFAULTS.items()}
    d["on"] = bool(raw.get("on", d["on"]))
    d["mode"] = "manual" if str(raw.get("mode", "auto")).strip().lower() == "manual" else "auto"
    d["start"] = _state_name(raw.get("start", "S0"))
    try:
        d["trans"] = max(0.1, min(3.0, float(raw.get("trans", d["trans"]))))
    except (TypeError, ValueError):
        d["trans"] = 0.5
    ev = []
    for e in raw.get("events") or []:
        if not isinstance(e, dict):
            continue
        at, trig = e.get("at", e.get("time")), str(e.get("trigger") or "").strip()
        try:
            at = None if at in (None, "") else max(0.0, float(at))
        except (TypeError, ValueError):
            at = None
        if at is None and not trig:
            continue
        ev.append({"at": at, "trigger": trig, "state": _state_name(e.get("state"), "S0")})
    d["events"] = ev
    return d


# ---- split (S4) cfg ---------------------------------------------------------------------------------------------------
def _fnum(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def t3_split_cfg(raw=None):
    """Normalise cfg['t3']['split'] = {on, merge, segments:[{start | trigger, end | hold, media, mode 'fill'|'fit'}]} (idempotent).
    media = image or video file; '' = a frame of the original video at the segment start. Up to 8 segments."""
    raw = raw if isinstance(raw, dict) else {}
    d = {"on": bool(raw.get("on", False)), "merge": max(0.0, min(5.0, _fnum(raw.get("merge")) if _fnum(raw.get("merge")) is not None else 0.3)),
         "segments": []}
    for g in list(raw.get("segments") or [])[:8]:
        if not isinstance(g, dict):
            continue
        st, tr = _fnum(g.get("start")), str(g.get("trigger") or "").strip()
        if st is None and not tr:
            continue
        hold, end = _fnum(g.get("hold")), _fnum(g.get("end"))
        d["segments"].append({"start": None if st is None else max(0.0, st), "trigger": tr,
                              "end": end, "hold": hold if hold and hold > 0 else None,
                              "media": str(g.get("media") or "").strip(),
                              "mode": "fit" if str(g.get("mode", "fill")).strip().lower() == "fit" else "fill"})
    return d


def _scfg(cfg):
    s = (cfg.get("t3") or {}).get("split")
    return s if isinstance(s, dict) and "segments" in s and "merge" in s else t3_split_cfg(s)


def split_resolve(cfg, duration):
    """-> [] or [{a, b, media, mode, first, last}] seconds (segments sorted, resolved from time / SRT phrase; default hold 4 s) plus
    cfg-level windows via split_windows(). first/last: first / last segment of a merged window (x-track in / out)."""
    sp = _scfg(cfg)
    if not sp["on"] or not sp["segments"]:
        return []
    cues = _cues(cfg) if any(g["trigger"] for g in sp["segments"]) else []
    segs = []
    for g in sp["segments"]:
        a = None
        if g["trigger"]:
            for c in cues:
                t = find_trigger(c, g["trigger"])
                if t is not None:
                    a = float(t)
                    break
            if a is None:
                t3_warn(f"   [!] split phrase '{g['trigger']}' not found{' - using the start time' if g['start'] is not None else ' - skipped'}.")
        if a is None:
            a = g["start"]
        if a is None or a >= duration:
            continue
        b = g["end"] if g["end"] is not None else a + (g["hold"] or 4.0)
        b = min(max(b, a + 0.5), duration)
        segs.append({"a": a, "b": b, "media": g["media"], "mode": g["mode"]})
    segs.sort(key=lambda z: z["a"])
    for i, g in enumerate(segs):                                       # no overlap: a segment ends when the next starts
        if i + 1 < len(segs) and g["b"] > segs[i + 1]["a"]:
            g["b"] = segs[i + 1]["a"]
    segs = [g for g in segs if g["b"] - g["a"] > 0.2]
    tr = float(cfg["t3"]["layout"]["trans"]) if (cfg.get("t3") or {}).get("layout") else 0.5
    wins = _merge([(g["a"], g["b"]) for g in segs], max(tr, _scfg(cfg)["merge"]))
    for g in segs:
        w = next(w for w in wins if w[0] - 1e-9 <= g["a"] and g["b"] <= w[1] + 1e-9)
        g["first"], g["last"] = abs(g["a"] - w[0]) < 1e-9, abs(g["b"] - w[1]) < 1e-9
    return segs


def split_windows(cfg, duration):
    """[(a, b)] merged split windows (seconds): S4 is fully on between a + trans and b."""
    tr = float(cfg["t3"]["layout"]["trans"]) if (cfg.get("t3") or {}).get("layout") else 0.5
    return [(a, b) for a, b in _merge([(g["a"], g["b"]) for g in split_resolve(cfg, duration)], max(tr, _scfg(cfg)["merge"]))]


def split_hide(cfg, duration):
    """[(a, b + trans)]: bands (strip/panel) and their content are hidden while the split is (partly) on screen."""
    tr = float(cfg["t3"]["layout"]["trans"]) if (cfg.get("t3") or {}).get("layout") else 0.5
    return [(a, b + tr) for a, b in split_windows(cfg, duration)]


def t3_split_clip(cfg, items, duration):
    """Cut band items (strip tiles / panel rows / slot blocks) so none is visible while the split hides the bands."""
    import copy
    hide = split_hide(cfg, duration)
    if not hide:
        return items
    out = []
    for it in items:
        pieces = [(it.start, it.end, True, True)]
        for a, b in hide:
            nxt = []
            for s0, e0, fi, fo in pieces:
                if e0 <= a or s0 >= b:
                    nxt.append((s0, e0, fi, fo))
                    continue
                if s0 < a:
                    nxt.append((s0, a, fi, True))
                if e0 > b:
                    nxt.append((b, e0, True, fo))
            pieces = nxt
        for s0, e0, fi, fo in pieces:
            if e0 - s0 < 0.05:
                continue
            if (s0, e0) == (it.start, it.end):
                out.append(it)
                continue
            c = copy.copy(it)
            c.start, c.end = s0, e0
            if hasattr(c, "fin"):
                c.fin = it.fin if s0 == it.start else True
                c.fout = it.fout if e0 == it.end else True
            elif s0 != it.start and getattr(c, "out", True) and e0 == it.end:
                pass
            out.append(c)
    return out


# ---- geometry -------------------------------------------------------------------------------------------------------
def _base(cfg):
    return cfg.get("_t3_base") or cfg.get("video_box") or VIDEO_BOX


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(v)))


def _sp(x):
    """state name ('S0'..'S3', 'S4' = split) / index 0..3 / float progress 0..3 (blend of consecutive states) / (s, p) or
    (s, p, split) tuple -> (s, p, x)."""
    if isinstance(x, str):
        if x.strip().upper() == "S4":
            return 0.0, 0.0, 1.0
        return STATES[_state_name(x)] + (0.0,)
    if isinstance(x, (tuple, list)) and len(x) in (2, 3):
        return _clamp(x[0]), _clamp(x[1]), (_clamp(x[2]) if len(x) == 3 else 0.0)
    u = _clamp(x, 0.0, 3.0)
    i = int(math.floor(u))
    f = u - i
    a, b = STATES["S%d" % i], STATES["S%d" % min(3, i + 1)]
    return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, 0.0

def _strip_dims(b):
    """(strip height, gap frame->strip, gap strip->footer) in poster px from a base box; without the keys = the old poster
    geometry (245, 10, 0), so t3_layout(state) with no base box and jobs without a strip are unchanged."""
    b = b or {}
    return float(b.get("strip_h", STRIP_H)), float(b.get("gap_t", GAP)), float(b.get("gap_b", 0.0))

def _bottom_poster(s, p, dims=None):
    sh, gt, gb = dims or (STRIP_H, GAP, 0.0)
    return FOOT_TOP - GAP - PANEL_H * p - s * (sh + gt + (gb - GAP) * (1 - p))


def t3_layout(state_or_progress, base_box=None):
    """Geometry for a state ('S0'..'S3' / 0..3), a float progress 0..3 (blend between consecutive states) or a presence pair (s, p).
    Returns {"sp": (s, p), "frame": (x, y, w, h) canvas px (float), "strip": (x, y, w, h) | None, "panel": (x, y, w, h) | None}.
    A band that is not present (presence 0) is None; present bands are at their FINAL position (the slide-in offset is only
    a transition effect). base_box = {x, y, w, ...} of the frame (default = the poster VIDEO_BOX: top, x and width never change)."""
    s, p, sx = _sp(state_or_progress)
    b = base_box or VIDEO_BOX
    x, y, w = float(b["x"]), float(b["y"]), float(b["w"])
    sh, gt, gb = _strip_dims(b)
    fh = _bottom_poster(s, p, (sh, gt, gb)) * K - y
    bx, bw = BAND_X0 * K, (BAND_X1 - BAND_X0) * K
    panel = (bx, (FOOT_TOP - PANEL_H) * K, bw, PANEL_H * K) if p > 1e-6 else None
    strip_top = FOOT_TOP - gb * (1 - p) - (PANEL_H + GAP) * p - sh
    strip = (bx, strip_top * K, bw, sh * K) if s > 1e-6 else None
    right = None
    if sx > 1e-6:                                                     # S4: frame shrinks to the left, matching frame on the right
        right = (x + w * (SPLIT_LEFT + SPLIT_GAP), y, w * (1 - SPLIT_LEFT - SPLIT_GAP), fh)
    return {"sp": (s, p), "frame": (x, y, w * (1 - sx * (1 - SPLIT_LEFT)), fh), "strip": strip, "panel": panel, "right": right,
            "x": sx}


def _box(fr):
    return {"x": fr[0], "y": fr[1], "w": fr[2], "h": fr[3]}


# ---- band providers (T3-6 / T3-7 / T3-8 fill these) -------------------------------------------------------------------
BAND_PROVIDERS = {"strip": {"ranges": None, "content": None}, "panel": {"ranges": None, "content": None}}


def register_band(name, ranges=None, content=None):
    """T3-6/7/8 call this once: ranges(cfg, duration) -> [(start, end), ...] seconds when the band's content is active;
    content(cfg, w, h) -> RGBA PIL image (w x h px, the band's final size) or None (= placeholder rectangle)."""
    BAND_PROVIDERS[name] = {"ranges": ranges, "content": content}


def t3_band_active_ranges(cfg, duration):
    """HOOK (AUTO mode): {"strip": [(a, b), ...], "panel": [...]} - seconds in which each band's content is active.
    Empty until the real bands register themselves with register_band(); merged here, nothing to edit in this file."""
    out = {}
    for name, prov in BAND_PROVIDERS.items():
        rs = []
        if prov.get("ranges"):
            try:
                rs = [(float(a), float(b)) for a, b in (prov["ranges"](cfg, duration) or []) if float(b) > float(a)]
            except Exception as e:
                t3_warn(f"   [!] layout: {name} ranges failed ({e}) - band stays hidden")
        out[name] = rs
    try:                                                         # T3 outro: rides on the PANEL band (same frame shrink / slide-in)
        from mt.templates.t3.panels import outro_ranges
        out["panel"] = list(out.get("panel", [])) + outro_ranges(cfg, duration)
    except Exception as e:
        t3_warn(f"   [!] layout: outro ranges failed ({e}) - outro hidden")
    return out


def _band_image(cfg, name, w, h):
    prov = BAND_PROVIDERS.get(name) or {}
    img = None
    if prov.get("content"):
        try:
            img = prov["content"](cfg, w, h)
        except Exception as e:
            t3_warn(f"   [!] layout: {name} content failed ({e}) - placeholder used")
    if img is None and name == "panel":                                      # T3 outro without a panel: the card background
        try:
            from mt.templates.t3.panels import _ocfg, outro_band_bg
            if _ocfg(cfg)["on"]:
                img = outro_band_bg(cfg, w, h)
        except Exception as e:
            t3_warn(f"   [!] layout: outro background failed ({e}) - placeholder used")
    if img is not None:
        return img.convert("RGBA").resize((w, h)) if img.size != (w, h) else img.convert("RGBA")
    im = Image.new("RGBA", (w, h), (255, 244, 230, 26))                      # dim placeholder
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, w - 1, h - 1), outline=(255, 244, 230, 120), width=3)
    try:
        fp, _ = t3_font("light", name.upper(), (cfg.get("t3") or {}).get("fonts"))
        f = ImageFont.truetype(fp, max(18, int(h * 0.22)))
    except Exception:
        f = ImageFont.load_default()
    d.text((w / 2.0, h / 2.0), name.upper(), font=f, fill=(255, 244, 230, 170), anchor="mm")
    return im


# ---- timeline: presence tracks ----------------------------------------------------------------------------------------
def _ease(u):
    u = _clamp(u)
    return u * u * (3 - 2 * u)


def _val(tr, v0, t):
    v = v0
    for t0, t1, a, b in tr:
        if t >= t1:
            v = b
        elif t > t0:
            return a + (b - a) * _ease((t - t0) / (t1 - t0))
        else:
            break
    return v


def _merge(rs, gap):
    out = []
    for a, b in sorted(rs):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _cues(cfg):
    out = []
    for c in caption_streams(cfg):
        try:
            out.append(parse_srt(c["srt"]))
        except Exception:
            pass
    return out


def t3_layout_timeline(cfg, duration):
    """{"v0": (s0, p0), "s": [(t0, t1, from, to)], "p": [...], "trans": sec} from the layout events (manual) or the band ranges (auto)."""
    lay = cfg["t3"]["layout"]
    tr = lay["trans"]
    v0 = STATES[lay["start"]]
    tracks = {"s": [], "p": []}
    last_end = {"s": 0.0, "p": 0.0, "x": 0.0}
    tracks["x"] = []

    def add(k, t, a, b):
        t0 = max(t, last_end[k])
        tracks[k].append((t0, t0 + tr, a, b))
        last_end[k] = t0 + tr
    if lay["mode"] == "manual":
        cur, cues, evs = list(v0), _cues(cfg), []
        for e in lay["events"]:
            t = e["at"]
            if e["trigger"]:
                for c in cues:
                    st = find_trigger(c, e["trigger"])
                    if st is not None:
                        t = float(st)
                        break
            if t is None:
                t3_warn(f"   [!] layout event '{e['trigger']}' not found and no time - skipped.")
                continue
            evs.append((t, STATES[e["state"]]))
        for t, tgt in sorted(evs, key=lambda z: z[0]):
            for i, k in enumerate("sp"):
                if tgt[i] != cur[i]:
                    add(k, t, cur[i], tgt[i])
                    cur[i] = tgt[i]
    else:
        ranges = t3_band_active_ranges(cfg, duration)
        sw = split_windows(cfg, duration)
        if sw:                                                         # bands are hidden while the split is on (they return after b)
            for name in ranges:
                rs = []
                for a, b in ranges[name]:
                    parts = [(a, b)]
                    for wa, wb in sw:
                        parts = [q for p0, p1 in parts for q in (((p0, min(p1, wa)), (max(p0, wb), p1)) if (p0 < wb and p1 > wa) else ((p0, p1),))]
                    rs += [(p0, p1) for p0, p1 in parts if p1 - p0 > 1e-6]
                ranges[name] = rs
        for i, (k, name) in enumerate((("s", "strip"), ("p", "panel"))):
            cur = v0[i]
            for a, b in _merge(ranges.get(name, []), tr):
                if a >= duration:
                    break
                if cur != 1.0:
                    add(k, a, cur, 1.0)
                    cur = 1.0
                if b < duration:
                    add(k, b, 1.0, 0.0)
                    cur = 0.0
    for wa, wb in split_windows(cfg, duration):
        add("x", wa, 0.0, 1.0)
        if wb < duration:
            add("x", wb, 1.0, 0.0)
    return {"v0": v0, "s": tracks["s"], "p": tracks["p"], "x": tracks["x"], "trans": tr}


def _sp_at(tl, t):
    return _val(tl["s"], tl["v0"][0], t), _val(tl["p"], tl["v0"][1], t)


def _spx_at(tl, t):
    return _val(tl["s"], tl["v0"][0], t), _val(tl["p"], tl["v0"][1], t), _val(tl.get("x") or [], 0.0, t)


def t3_layout_at(cfg, t, duration=None):
    """t3_layout() for time t of the job (uses the prepared timeline when there is one). T3-6/7/8: use this to place band content."""
    lay = cfg.get("_t3_lay")
    tl = lay["tl"] if lay else t3_layout_timeline(cfg, duration or 1e6)
    return t3_layout(_spx_at(tl, t), _base(cfg))


def _windows(tl, fps, nfr):
    """Frame-aligned [i0, i1) windows (merged over both tracks) in which the frame is moving."""
    rs = [(t0, t1) for k in "spx" for t0, t1, _, _ in (tl.get(k) or [])]
    out = []
    for a, b in _merge(rs, 0.0):
        i0, i1 = int(math.floor(a * fps + 1e-6)), int(math.ceil(b * fps - 1e-6))
        if i0 >= nfr:
            continue
        i1 = min(i1, nfr)
        if out and i0 <= out[-1][1]:
            out[-1][1] = max(out[-1][1], i1)
        else:
            out.append([i0, i1])
    return [tuple(w) for w in out]


# ---- items follow the frame -----------------------------------------------------------------------------------------
def _segments(tl, fps, duration):
    nfr = int(math.ceil(duration * fps)) + 1
    segs, cur = [], 0
    for i0, i1 in _windows(tl, fps, nfr):
        if i0 > cur:
            segs.append((cur / fps, i0 / fps, _spx_at(tl, cur / fps)))
        for i in range(i0, i1):
            segs.append((i / fps, (i + 1) / fps, _spx_at(tl, i / fps)))
        cur = i1
    segs.append((cur / fps, duration + 1.0, _spx_at(tl, cur / fps)))
    return segs


def t3_layout_items(cfg, duration):
    """Chapter tags + captions + cards re-anchored to the moving frame: the timeline is cut into constant segments and one
    segment per frame inside a transition; each segment is built for its own frame box and clipped. An item that spans segments
    becomes pieces: only the first keeps the in-animation, later pieces are static (the out-animation is lost on spanning items)."""
    lay = cfg.get("_t3_lay")
    tl = lay["tl"] if lay else t3_layout_timeline(cfg, duration)
    fps = lay["fps"] if lay else 30.0
    base = _base(cfg)
    out = []
    try:
        for a, b, sp in _segments(tl, fps, duration):
            _dyn._WIN = (a, b)
            for it in _dyn.t3_dynamic_items(cfg, duration, box=_box(t3_layout(sp, base)["frame"])):
                if it.end <= a or it.start >= b:
                    continue
                ns, ne = max(it.start, a), min(it.end, b)
                if ns == it.start and ne == it.end:
                    out.append(it)
                else:
                    first, last = ns == it.start, ne == it.end
                    out.append(Item(it.sprite, ns, ne, it.cx, it.cy, it.anim if first else "none", it.dur,
                                    out=(it.out and last and first), opacity=it.opacity, rtl=it.rtl))
    finally:
        _dyn._WIN = None
    return out + split_items(cfg, duration)

def t3_el_cfg(e):
    """Template 3 element style -> {"fit", "radius", "border", "color", "place", "side"} for style "card" (the T3 default), or None
    for style "plain" / place "plain" (= the old behaviour: a straight PNG at e["pos"]). Optional keys of an element:
    place ("side" = default: a card in the free column beside the frame, never over the speaker | "inside" = the old card inside the
    frame | "plain"), side ("right" = default | "left"), style ("card"|"plain"),
    fit ("contain" = whole image, no crop | "cover" = fills the frame, cropped; "side" cards are always "contain"),
    radius (px, default 28), border (px, default 3; 0 / false = none; "#rrggbb" = default width in that colour).
    Border colour = accent."""
    style = str(e.get("style") or "card").strip().lower()
    if style != "card":
        return None
    place = str(e.get("place") or "side").strip().lower()
    if place == "plain":
        return None
    place = place if place in ("side", "inside") else "side"
    side = "left" if str(e.get("side") or "right").strip().lower() == "left" else "right"
    fit = str(e.get("fit") or "contain").strip().lower()
    fit = fit if fit in ("contain", "cover") else "contain"
    if place == "side":
        fit = "contain"
    try:
        radius = max(0.0, min(200.0, float(e.get("radius", 28))))
    except (TypeError, ValueError):
        radius = 28.0
    b, color = e.get("border", 3), None
    if isinstance(b, str) and b.strip().startswith("#"):
        color, b = b.strip(), 3
    try:
        bw = 3.0 if b is True else 0.0 if (b is False or b is None) else max(0.0, min(40.0, float(b)))
    except (TypeError, ValueError):
        bw = 3.0
    return {"fit": fit, "radius": radius, "border": bw, "color": color, "place": place, "side": side}


def _el_inset_quad(q, m):
    """Convex quad [TL, TR, BR, BL] (screen px, y down) with every edge moved inward by m px."""
    lines = []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy) or 1.0
        lines.append(((a[0] - dy / d * m, a[1] + dx / d * m), (dx, dy)))
    out = []
    for i in range(4):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-9:
            out.append(p2)
            continue
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
        out.append((p1[0] + d1[0] * t, p1[1] + d1[1] * t))
    return out


def _el_fit_rect(q, ar, cap_w=None):
    """Largest rectangle of aspect ar (= w / h) inside the convex quad q [TL, TR, BR, BL], centred on the quad's centre line:
    cy = the quad's vertical centre, cx = the middle of the quad's real left / right edges over the rectangle's own y-range
    (so a skewed frame centres the card on the frame, not on its bounding box). Returns (cx, cy, w, h) or None."""
    xs, ys = [p[0] for p in q], [p[1] for p in q]
    cy = sum(ys) / 4.0

    def edge_x(a, b, y):
        return a[0] + (b[0] - a[0]) * ((y - a[1]) / ((b[1] - a[1]) or 1e-9))

    def inside(px, py):
        for i in range(4):
            a, b = q[i], q[(i + 1) % 4]
            if (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0]) < -0.5:
                return False
        return True

    def place(w):
        h = w / ar
        yt, yb = cy - h / 2.0, cy + h / 2.0
        L = max(edge_x(q[0], q[3], yt), edge_x(q[0], q[3], yb))
        R = min(edge_x(q[1], q[2], yt), edge_x(q[1], q[2], yb))
        if R - L < w:
            return None
        cx = (L + R) / 2.0
        if all(inside(cx + sx * w / 2.0, cy + sy * h / 2.0) for sx in (-1, 1) for sy in (-1, 1)):
            return cx, cy, w, h
        return None
    hi = min(max(xs) - min(xs), (max(ys) - min(ys)) * ar)
    if cap_w:
        hi = min(hi, float(cap_w))
    lo, best = 2.0, None
    if hi < lo:
        return None
    best = place(hi)
    if best:
        return best
    for _ in range(40):
        mid = (lo + hi) / 2.0
        r = place(mid)
        if r:
            best, lo = r, mid
        else:
            hi = mid
    return best


def t3_el_card_sprite(im, w, h, cfgx, accent):
    """RGBA sprite of an element card: image (contain = the card has the image's aspect, cover = cropped to the card),
    rounded corners, thin accent border, soft shadow. An image without transparency gets a 1.2 px feathered edge.
    The sprite is padded the same on every side, so the sprite centre = the card centre (pop / scale animate from it)."""
    from PIL import ImageChops, ImageFilter
    from mt.draw import t2_rgb
    w, h = max(8, int(round(w))), max(8, int(round(h)))
    if cfgx["fit"] == "cover":
        s = max(w / float(im.width), h / float(im.height))
        big = im.resize((max(w, int(round(im.width * s))), max(h, int(round(im.height * s)))), Image.LANCZOS)
        l, t = (big.width - w) // 2, (big.height - h) // 2
        img = big.crop((l, t, l + w, t + h))
    else:
        img = im.resize((w, h), Image.LANCZOS)
    SS, r = 4, min(cfgx["radius"], w / 2.0, h / 2.0)

    def rr(inset, rad, fill):
        m = Image.new("L", (w * SS, h * SS), 0 if fill else 255)
        ImageDraw.Draw(m).rounded_rectangle((inset * SS, inset * SS, (w - inset) * SS - 1, (h - inset) * SS - 1),
                                            radius=max(0.0, rad) * SS, fill=255 if fill else 0)
        return m
    mask = rr(0, r, True).resize((w, h), Image.LANCZOS)
    a = img.getchannel("A")
    if a.getextrema()[0] >= 250:                                          # no alpha in the file -> feather the edge
        mask = rr(1, r - 1, True).filter(ImageFilter.GaussianBlur(1.2 * SS)).resize((w, h), Image.LANCZOS)
    img.putalpha(ImageChops.multiply(a, mask))
    bw = cfgx["border"]
    if bw > 0:
        outer = rr(0, r, True)
        inner = rr(bw, r - bw, True)
        ring = ImageChops.subtract(outer, inner).resize((w, h), Image.LANCZOS)
        col = Image.new("RGBA", (w, h), tuple(t2_rgb(cfgx["color"] or accent)) + (255,))
        col.putalpha(ring)
        img.alpha_composite(col)
    pad = 30
    spr = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", spr.size, 0)
    sh.paste(mask, (pad, pad + 6))
    sh = sh.filter(ImageFilter.GaussianBlur(12)).point(lambda v: int(v * 0.40))
    shadow = Image.new("RGBA", spr.size, (0, 0, 0, 255))
    shadow.putalpha(sh)
    spr.alpha_composite(shadow)
    spr.alpha_composite(img, (pad, pad))
    return spr


def _el_edge_x(q, y):
    """x of the RIGHT edge (TR -> BR) of the convex quad q = [TL, TR, BR, BL] at height y (above / below the edge = its end point)."""
    a, b = q[1], q[2]
    if y <= a[1]:
        return a[0]
    if y >= b[1]:
        return b[0]
    return a[0] + (b[0] - a[0]) * (y - a[1]) / ((b[1] - a[1]) or 1e-9)


def _el_side_fit(quads, W, ar, cap_w, yt, yb, side="right", gap=EL_SIDE_GAP, edge=EL_SIDE_EDGE):
    """Largest card (aspect ar = w / h) for the free column beside the frame. quads = frame quads [TL, TR, BR, BL] that must stay
    clear (quads[0] = the full-size frame: its edge slope sets the card's shear); the column = between the frame edge (+ gap)
    and the canvas edge (- edge), from yt to yb, the card centred in it. The card is a parallelogram whose near edge is PARALLEL
    to the frame edge (constant gap, no straight-against-slanted wedge). Returns (cx, cy, w, h, shear) - shear = dx / dy of the
    card's vertical edges, cx / cy = centre of the card's middle row - or None when nothing fits."""
    if side == "left":                                   # mirror the world, solve for the right side, mirror back
        quads = [[(W - p[0], p[1]) for p in (q[1], q[0], q[3], q[2])] for q in quads]
    q0 = quads[0]
    s = (q0[2][0] - q0[1][0]) / ((q0[2][1] - q0[1][1]) or 1e-9)
    xr, yc = W - edge, (yt + yb) / 2.0

    def solve(w):
        h = w / ar
        if h > yb - yt + 1e-6:
            return None
        ys = [yc - h / 2.0 + h * i / 16.0 for i in range(17)]
        nl = max(_el_edge_x(q, y) + gap - s * (y - yc) for q in quads for y in ys)      # card's left edge at yc, all rows clear
        slack = xr - (nl + w + abs(s) * h / 2.0)
        return (nl, h, slack) if slack >= 0 else None
    hi = min(xr, (yb - yt) * ar)
    if cap_w:
        hi = min(hi, float(cap_w))
    if hi < 2.0:
        return None
    w, r = hi, solve(hi)
    if r is None:
        lo, best = 2.0, None
        for _ in range(40):
            mid = (lo + hi) / 2.0
            rr = solve(mid)
            if rr:
                best, lo = (mid, rr), mid
            else:
                hi = mid
        if best is None:
            return None
        w, r = best
    nl, h, slack = r
    cx = nl + w / 2.0 + slack / 2.0
    return (W - cx, yc, w, h, -s) if side == "left" else (cx, yc, w, h, s)


def _el_side_ctx(cfg, t3, start, end, duration):
    """Free-column context for a card alive in [start, end): (frame quads it must clear, top limit, bottom limit, end) in canvas px.
    Top = under the headline / tag lines, bottom = above the footer and above any strip / panel band already on screen when the card
    appears (the card keeps ONE size for its whole life). A band that starts moving in LATER than EL_SIDE_MIN_LIFE after the card
    appeared ends the card at that moment instead (it leaves just before the layout moves). Quad 0 = the full-size frame."""
    from mt.templates.t3.static import t3_frame_quad
    skew = 0.0 if t3["frame_style"] == "straight" else t3["frame_skew"]
    lay, base = cfg.get("_t3_lay"), _base(cfg)
    yb, quads = FOOT_TOP * K - 24.0, []
    if lay:
        quads.append(t3_frame_quad(_box(t3_layout("S0", base)["frame"]), skew))
        for k in "sp":
            for t0, t1, fa, fb in lay["tl"][k]:
                if fb > fa and t1 > start and start + EL_SIDE_MIN_LIFE <= t0 < end:
                    end = t0
        for a, b, sp in _segments(lay["tl"], lay["fps"], duration):
            if b <= start + 1e-6 or a >= end - 1e-6:
                continue
            L = t3_layout(sp, base)
            quads.append(t3_frame_quad(_box(L["frame"]), skew))
            for name in ("strip", "panel"):
                if L[name]:
                    yb = min(yb, L[name][1] - 20.0)
    else:
        quads.append(t3_frame_quad(cfg.get("video_box") or VIDEO_BOX, skew))
    if t3["show_headline"]:
        yt = (TAG_BOX[3] if any(t3["tag_lines"]) else UNDERLINE[2]) * K + 28.0
    else:
        yt = float(base["y"])
    return quads, yt, yb, end


def _el_shear(spr, s):
    """Horizontal shear x += s * y of an RGBA sprite (premultiplied, so no dark fringe); the output's centre = the card's centre."""
    if abs(s) < 1e-4:
        return spr
    w0, h0 = spr.size
    off = 0.0 if s >= 0 else -s * h0
    aff = getattr(Image, "Transform", Image).AFFINE
    out = spr.convert("RGBa").transform((w0 + int(math.ceil(abs(s) * h0)), h0), aff, (1.0, -s, -off, 0.0, 1.0, 0.0), Image.BICUBIC)
    return out.convert("RGBA")


def _el_side_place(cfg, t3, cfgx, label, ar, cap, start, end, duration):
    """Card geometry for place "side": ((cx, cy, w, h, shear), end) or None when there is no room at all. Falls back from
    side "left" to "right" when the left column is too small (the frame normally sits on the left), and warns when the card is small."""
    quads, yt, yb, end = _el_side_ctx(cfg, t3, start, end, duration)
    W = cfg["canvas"][0]
    g = _el_side_fit(quads, W, ar, cap, yt, yb, cfgx["side"])
    if (g is None or g[2] < EL_SIDE_MIN_W) and cfgx["side"] == "left":
        g2 = _el_side_fit(quads, W, ar, cap, yt, yb, "right")
        if g2 and (g is None or g2[2] > g[2]):
            t3_warn(f"   [!] element '{label}': no room on the left of the frame - placed on the right.")
            g = g2
    if g is None:
        t3_warn(f"   [!] element '{label}': no free column beside the frame - placed inside it.")
        return None
    if g[2] < EL_SIDE_MIN_W:
        t3_warn(f"   [!] element '{label}': the free column only fits a {int(g[2])} px wide card (small).")
    return g, end


def _el_side_items(cfg, e, duration, cfgx, im, t3, cap):
    """place "side": ONE static card in the free column beside the frame (see _el_side_fit); None = no room (caller falls back)."""
    start, end = float(e["start"]), min(float(e["end"]), duration + 1)
    if end - start <= 1e-6:
        return []
    for o in cfg.get("elements") or []:                  # the next card on the same side starts as this one ends -> overlap them
        ox = t3_el_cfg(o) if o is not e else None        # for the animation time: smooth swap instead of a hole
        try:
            if ox and ox["place"] == "side" and ox["side"] == cfgx["side"] and abs(float(o["start"]) - float(e["end"])) <= 0.15:
                end = min(end + float(e.get("anim_dur", 0.5)), duration + 1.0)
                break
        except (TypeError, ValueError, KeyError):
            pass
    r = _el_side_place(cfg, t3, cfgx, Path(str(e.get("path"))).name, im.width / float(im.height), cap, start, end, duration)
    if r is None:
        return None
    (cx, cy, w, h, sh), end = r
    spr = _el_shear(t3_el_card_sprite(im, w, h, cfgx, t3["accent"]), sh)
    return [Item(spr, start, end, cx, cy, e.get("anim", "fade"), e.get("anim_dur", 0.5), out=True,
                 opacity=e.get("opacity", 100) / 100.0)]


# ---- video layers beside the frame (place "side": opt-in, same geometry / look as the image cards) --------------------------
def t3_split_side_video_layers(cfg):
    """(other video layers, side video layers): a T3 video layer is a card beside the frame only when it says place "side"
    (default = unchanged: over the frame box / the canvas, so existing b-roll jobs keep working)."""
    side, rest = [], []
    for L in cfg.get("video_layers") or []:
        (side if str(L.get("place") or "").strip().lower() == "side" else rest).append(L)
    return rest, side


def _el_cap(L, W):
    ws = str(L.get("width") or "").strip()
    try:
        return (float(ws[:-1]) / 100.0 * W if ws.endswith("%") else float(ws)) if ws else None
    except ValueError:
        return None


def t3_side_video_items(cfg, duration):
    """STILL preview of the side video layers: their first frame as an image card (renders use baked clips, t3_side_video_prepare)."""
    from mt.templates.t3.panels import _video_frame
    from mt.templates.t3.static import t3_cfg
    t3, out = t3_cfg(cfg.get("t3")), []
    for L in t3_split_side_video_layers(cfg)[1]:
        fr = _video_frame(L["path"], 0.0)
        cfgx = t3_el_cfg(dict(L, style="card", place="side"))
        if fr is None or cfgx is None:
            continue
        its = _el_side_items(cfg, dict(L, anim=L.get("anim", "fade")), duration, cfgx, fr.convert("RGBA"), t3, _el_cap(L, cfg["canvas"][0]))
        out += its or []
    return out


def t3_el_card_kit(w, h, cfgx, accent, shear=0.0):
    """The part of t3_el_card_sprite that does not depend on the picture (mask, border ring, shadow), computed once ->
    compose(rgb picture of exactly w x h) = the same sheared card sprite, about 10x faster (video cards: one call per frame)."""
    from PIL import ImageChops, ImageFilter
    from mt.draw import t2_rgb
    w, h = max(8, int(round(w))), max(8, int(round(h)))
    SS, r, pad = 4, min(cfgx["radius"], w / 2.0, h / 2.0), 30

    def rr(inset, rad):
        m = Image.new("L", (w * SS, h * SS), 0)
        ImageDraw.Draw(m).rounded_rectangle((inset * SS, inset * SS, (w - inset) * SS - 1, (h - inset) * SS - 1),
                                            radius=max(0.0, rad) * SS, fill=255)
        return m
    mask0 = rr(0, r).resize((w, h), Image.LANCZOS)
    mask = rr(1, r - 1).filter(ImageFilter.GaussianBlur(1.2 * SS)).resize((w, h), Image.LANCZOS)     # video frames have no alpha
    ring = None
    if cfgx["border"] > 0:
        bw = cfgx["border"]
        rg = ImageChops.subtract(rr(0, r), rr(bw, r - bw)).resize((w, h), Image.LANCZOS)
        ring = Image.new("RGBA", (w, h), tuple(t2_rgb(cfgx["color"] or accent)) + (255,))
        ring.putalpha(rg)
    shadow = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 255))
    sh = Image.new("L", shadow.size, 0)
    sh.paste(mask0, (pad, pad + 6))
    shadow.putalpha(sh.filter(ImageFilter.GaussianBlur(12)).point(lambda v: int(v * 0.40)))

    def compose(img):
        img = img.convert("RGBA")
        img.putalpha(mask)
        if ring is not None:
            img.alpha_composite(ring)
        spr = shadow.copy()
        spr.alpha_composite(img, (pad, pad))
        return _el_shear(spr, shear)
    return compose


def t3_side_video_prepare(cfg, info, tmpdir):
    """Side video layers -> baked alpha clips (qtrle): every frame = the picture in the rounded / bordered / sheared card with the
    entry / exit animation, drawn on a small local canvas at a fixed canvas position (key "_xy", area "canvas" = above the frame
    plate). Same mechanism as the split clips / floating cards. [] when there are none (or in a still)."""
    import subprocess
    from mt.anim import anim_state
    from mt.common import FFMPEG
    from mt.draw import draw_item
    from mt.templates.t3.static import t3_cfg
    vls = [] if cfg.get("_t2_still") else list(cfg.get("_t3_side_vl") or [])
    if not vls:
        return []
    t3, (W, H), fps = t3_cfg(cfg.get("t3")), cfg["canvas"], info["fps"]
    fps_f = float(fps)
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    dur_eff = min(info["duration"], float(cfg["preview"])) if cfg.get("preview") else info["duration"]
    layers = []
    for n, L in enumerate(vls):
        s0, e_true = float(L["start"]), float(L["end"])
        if s0 >= dur_eff or e_true <= s0:
            continue
        cfgx = t3_el_cfg(dict(L, style="card", place="side"))
        vi = probe(L["path"])
        r = _el_side_place(cfg, t3, cfgx, Path(str(L["path"])).name, vi["w"] / float(vi["h"]), _el_cap(L, W), s0, e_true, info["duration"])
        if r is None:
            continue
        (cx, cy, w, h, sh), e_true = r
        w, h = max(8, int(round(w))), max(8, int(round(h)))
        compose = t3_el_card_kit(w, h, cfgx, t3["accent"], sh)
        ref = compose(Image.new("RGB", (w, h), (0, 0, 0)))
        Wp, Hp = int(ref.width * 1.3) // 2 * 2 + 2, int(ref.height * 1.3) // 2 * 2 + 2       # room for the pop overshoot
        x0, y0 = int(round(cx - Wp / 2.0)), int(round(cy - Hp / 2.0))
        e = min(e_true, dur_eff)
        nfr = max(1, int(math.ceil((e - s0) * fps_f)))
        out = os.path.join(tmpdir, f"t3sidevl{n}.mov")
        rd = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", L["path"], "-an", "-vf",
                               f"fps={fps_s},scale={w}:{h},setsar=1,format=rgb24", "-frames:v", str(nfr), "-f", "rawvideo",
                               "-pix_fmt", "rgb24", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        wr = subprocess.Popen([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                               "-video_size", f"{Wp}x{Hp}", "-framerate", fps_s, "-i", "pipe:0", "-c:v", "qtrle", "-pix_fmt", "argb", out],
                              stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        print(f"Preparing side video card {n + 1} ({Path(L['path']).name}, {nfr} frames)...")
        anim, adur, last = L.get("anim", "fade"), L.get("anim_dur", 0.4), None
        try:
            for i in range(nfr):
                need, raw = w * h * 3, b""
                while len(raw) < need:
                    ch = rd.stdout.read(need - len(raw))
                    if not ch:
                        break
                    raw += ch
                fr = Image.frombytes("RGB", (w, h), raw) if len(raw) == need else (last or Image.new("RGB", (w, h), (24, 15, 12)))
                last = fr
                it = Item(compose(fr), s0, e_true, Wp / 2.0, Hp / 2.0, anim, adur, out=True, opacity=L.get("opacity", 100) / 100.0)
                cv = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
                draw_item(cv, it, anim_state(it.anim, it.progress(s0 + i / fps_f), W, H))
                wr.stdin.write(cv.tobytes())
            wr.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        finally:
            rd.kill()
            rd.wait()
        err = wr.stderr.read().decode("utf-8", "replace")
        if wr.wait() != 0 or not os.path.isfile(out):
            raise SystemExit("[!] Could not prepare the side video card:\n" + err[-800:])
        layers.append({"path": out, "start": s0, "end": e, "area": "canvas", "mode": "fit", "fade": 0.0, "_xy": [x0, y0]})
    return layers


def t3_element_items(cfg, e, duration, margin=24):
    """Template 3 `elements` entry with style "card" (default) -> [Item]; None for style / place "plain" (caller keeps the old path).
    place "side" (default): the card sits in the free column BESIDE the frame (_el_side_items), never over the speaker.
    place "inside": the card sits INSIDE the real frame quad (margin px from every edge), centred on it, never cropped (fit "contain"),
    and follows the frame when the adaptive layout moves it (same segment cut as t3_layout_items: only the first piece
    keeps the in-animation). e["width"] (px or %) is only a maximum width; e["pos"] is ignored for cards.
    Needs: t3_cfg / t3_frame_quad (static.py), load_image_sprite / t2_rgb (draw.py), _segments / t3_layout / _base / _box (here)."""
    cfgx = t3_el_cfg(e)
    if cfgx is None:
        return None
    from mt.draw import load_image_sprite
    from mt.templates.t3.static import t3_cfg, t3_frame_quad
    t3 = t3_cfg(cfg.get("t3"))
    skew = 0.0 if t3["frame_style"] == "straight" else t3["frame_skew"]
    W = cfg["canvas"][0]
    im = load_image_sprite(e["path"], None, W)
    ws = str(e.get("width") or "").strip()
    try:
        cap = (float(ws[:-1]) / 100.0 * W if ws.endswith("%") else float(ws)) if ws else None
    except ValueError:
        cap = None
    if cfgx["place"] == "side":                           # default: beside the frame, never over the speaker
        side_items = _el_side_items(cfg, e, duration, cfgx, im, t3, cap)
        if side_items is not None:
            return side_items
        cfgx = dict(cfgx, place="inside")                 # no room at all -> the old inside card
    lay = cfg.get("_t3_lay")
    if lay and not lay.get("still"):
        base = _base(cfg)
        segs = [(a, b, _box(t3_layout(sp, base)["frame"])) for a, b, sp in _segments(lay["tl"], lay["fps"], duration)]
    else:
        segs = [(0.0, duration + 1.0, cfg.get("video_box") or VIDEO_BOX)]
    start, end = float(e["start"]), min(float(e["end"]), duration + 1)
    pieces = []
    for a, b, box in segs:
        ns, ne = max(start, a), min(end, b)
        if ne - ns <= 1e-6:
            continue
        qi = _el_inset_quad(t3_frame_quad(box, skew), margin)
        if cfgx["fit"] == "cover":
            qx, qy = [p[0] for p in qi], [p[1] for p in qi]
            ar = (max(qx) - min(qx)) / max(1.0, max(qy) - min(qy))
        else:
            ar = im.width / float(im.height)
        g = _el_fit_rect(qi, ar, cap)
        if g is None:
            continue
        key = tuple(int(round(v)) for v in g)
        if pieces and pieces[-1][3] == key and abs(pieces[-1][1] - ns) < 1e-6:
            pieces[-1][1] = ne
        else:
            pieces.append([ns, ne, g, key])
    cache, out = {}, []
    for k, (ns, ne, g, key) in enumerate(pieces):
        sk = key[2:]
        if sk not in cache:
            cache[sk] = t3_el_card_sprite(im, g[2], g[3], cfgx, t3["accent"])
        first, last = ns <= start + 1e-6, k == len(pieces) - 1
        out.append(Item(cache[sk], ns, ne, g[0], g[1], e.get("anim", "fade") if first else "none", e.get("anim_dur", 0.5),
                        out=(first and last), opacity=e.get("opacity", 100) / 100.0))
    return out


# ---- plates ---------------------------------------------------------------------------------------------------------
def _right_frame(plate, bg_rgba, t3, rbox, x, margin=40):
    """S4: the matching (skewed, cream border, orange bracket) frame on the right, alpha = split progress x; its inside is a dark
    panel (the content - image / baked video - is drawn above by Items / video layers)."""
    W, H = bg_rgba.size
    rx, ry, rw, rh = [int(round(v)) for v in rbox]
    c0, r0, c1, r1 = max(0, rx - margin), max(0, ry - margin), min(W, rx + rw + margin), min(H, ry + rh + margin)
    crop = bg_rgba.crop((c0, r0, c1, r1)).convert("RGB")
    lay, info = t3_frame_layer(c1 - c0, r1 - r0, crop, (rx - c0, ry - r0, rw, rh), t3["frame_style"], t3["frame_skew"], t3["accent"],
                               full=True)
    dark = Image.new("RGBA", lay.size, (0, 0, 0, 0))
    ImageDraw.Draw(dark).polygon([tuple(p) for p in info["quad"]], fill=(24, 15, 12, 255))
    dark.alpha_composite(lay)
    if x < 0.999:
        dark.putalpha(dark.getchannel("A").point(lambda v, a=x: int(v * a)))
    plate.alpha_composite(dark, (c0, r0))


def _plate(bg_rgba, top, t3, frame, margin=64, right=None, x=0.0):
    """Full-canvas plate: opaque design everywhere except the (transparent) video window + border/shadow/bracket of `frame`.
    right/x (T3-9): the S4 right frame box and the split progress."""
    W, H = bg_rgba.size
    x, y, w, h = [int(round(v)) for v in frame]
    c0, r0, c1, r1 = max(0, x - margin), max(0, y - margin), min(W, x + w + margin), min(H, y + h + margin)
    crop = bg_rgba.crop((c0, r0, c1, r1)).convert("RGB")
    lay, _ = t3_frame_layer(c1 - c0, r1 - r0, crop, (x - c0, y - r0, w, h), t3["frame_style"], t3["frame_skew"],
                            t3["accent"], full=True)
    plate = bg_rgba.copy()
    plate.paste(lay, (c0, r0))
    if right is not None and x > 1e-3:
        _right_frame(plate, bg_rgba, t3, right, x)
    plate.alpha_composite(top)
    return plate


def _band_layer(cfg, sp, t_progress=None):
    """Bands of presence sp as an RGBA canvas layer (still previews only; renders overlay them with ffmpeg)."""
    W, H = cfg["canvas"]
    lay = t3_layout(sp, _base(cfg))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for name, pres in (("strip", sp[0]), ("panel", sp[1])):
        r = lay[name]
        if r:
            im = _band_image(cfg, name, int(round(r[2])), int(round(r[3])))
            im.putalpha(im.getchannel("A").point(lambda v, a=pres: int(v * a)))
            out.alpha_composite(im, (int(round(r[0])), int(round(r[1] + (1 - pres) * SLIDE * K))))
    return out


# ---- ffmpeg expressions ---------------------------------------------------------------------------------------------
def _expr(tr, v0):
    """ffmpeg expression in t for a presence track (smoothstep transitions)."""
    if not tr:
        return "%g" % v0
    e = "%g" % tr[-1][3]
    for t0, t1, a, b in reversed(tr):
        u = "((t-%.4f)/%.4f)" % (t0, t1 - t0)
        e = "if(lt(t,%.4f),%g,if(lt(t,%.4f),%g+(%g)*(%s*%s*(3-2*%s)),%s))" % (t0, a, t1, a, b - a, u, u, u, e)
    return e


def _pexprs(tl):
    return _expr(tl["s"], tl["v0"][0]), _expr(tl["p"], tl["v0"][1])


def _hexpr(S, P, y0, dims=None):
    sh, gt, gb = dims or (STRIP_H, GAP, 0.0)
    return "(%.3f-%.3f*(%s)-(%.3f)*(%s)+(%.3f)*(%s)*(%s)-%g)" % (
        (FOOT_TOP - GAP) * K, PANEL_H * K, P, (sh + gt + gb - GAP) * K, S, (gb - GAP) * K, P, S, y0)


# ---- prepare (hook, called from t3_build_static_layers) ----------------------------------------------------------------
def t3_layout_prepare(cfg, tmp, bg_img, fg_img):
    """Builds everything the layout needs into cfg: cfg['video_box'] = frame at the start (items anchor to it), and for a render
    cfg['_t3_lay'] (plates, band PNGs, ffmpeg expressions; consumed by build_ffmpeg_cmd via t3_layout_inputs/graph/video).
    A --still previews the layout state at the still's time t (plate + bands baked into the foreground plate)."""
    t3, W, H = cfg["t3"], cfg["canvas"][0], cfg["canvas"][1]
    vb = dict(cfg.get("video_box") or VIDEO_BOX)
    base = {"x": vb["x"], "y": vb["y"], "w": vb["w"]}
    from mt.templates.t3.panels import t3_strip_geom                    # strip height / gaps from the free area (only when strip.on)
    base.update(t3_strip_geom(cfg, base))
    cfg["_t3_base"] = dict(base)
    mode = t3["video_fit"]
    vid = cfg.get("video")
    info = probe(vid) if vid and os.path.isfile(str(vid)) else None
    fps = float(info["fps"]) if info else 30.0
    duration = float(info["duration"]) if info else 5.0
    if cfg.get("preview"):
        duration = min(duration, float(cfg["preview"]))
    tl = t3_layout_timeline(cfg, duration)
    head = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    t3_headline_layer(head, t3)
    _tops = {}

    def top_for(x):                                                   # headline column fades out while the split is on
        k = round(x * 1000)
        if k not in _tops:
            t_ = head.copy()
            if k:
                t_.putalpha(t_.getchannel("A").point(lambda v, a=1 - x: int(v * a)))
            t_.alpha_composite(fg_img)
            _tops[k] = t_
        return _tops[k]
    bg_rgba = bg_img.convert("RGBA")
    pk = lambda sp: "%d_%d_%d" % (round(sp[0] * 1000), round(sp[1] * 1000), round((sp[2] if len(sp) > 2 else 0) * 1000))
    mkplate = lambda sp: _plate(bg_rgba, top_for(sp[2]), t3, t3_layout(sp, base)["frame"], right=t3_layout(sp, base)["right"], x=sp[2])
    if cfg.get("_t2_still"):
        sp = _spx_at(tl, float(cfg.get("_t3_still_t", 0.5)))
        fr = t3_layout(sp, base)["frame"]
        plate = mkplate(sp)
        plate.alpha_composite(_band_layer(dict(cfg, video_box=base), sp))
        path = os.path.join(tmp, "t3_lay_still.png")
        plate.save(path, compress_level=1)
        cfg["_t2_fg"] = path
        cfg["video_box"] = dict({k: int(round(v)) for k, v in _box(fr).items()}, mode=mode)
        cfg["_t3_lay"] = {"tl": tl, "fps": fps, "still": True}
        return
    nfr = int(math.ceil(duration * fps))
    wins = _windows(tl, fps, nfr)
    half = 0.5 / fps
    const, bounds, cur = {}, [], 0
    for i0, i1 in wins + [(nfr + 1, nfr + 1)]:                       # constant stretches between the windows
        a, b = cur / fps, (9999.0 if i0 > nfr else i0 / fps)
        if b > a + 1e-9:
            sp = _spx_at(tl, a)
            const.setdefault(pk(sp), {"sp": sp, "en": []})["en"].append((a, b))
        cur = i1
    lay = {"tl": tl, "fps": fps, "const": [], "windows": [], "bands": []}
    for k, c in const.items():
        path = os.path.join(tmp, f"t3_plate_{k}.png")
        mkplate(c["sp"]).save(path, compress_level=1)
        lay["const"].append({"path": path, "en": "+".join("gte(t,%.4f)*lt(t,%.4f)" % (a - half, b - half) for a, b in c["en"])})
    for wi, (i0, i1) in enumerate(wins):
        for i in range(i0, i1):
            mkplate(_spx_at(tl, i / fps)).save(os.path.join(tmp, f"t3_tr{wi}_{i - i0:04d}.png"), compress_level=1)
        lay["windows"].append({"pattern": os.path.join(tmp, f"t3_tr{wi}_%04d.png"), "t0": i0 / fps, "t1": i1 / fps})
    S, P = _pexprs(tl)
    for name, track, X in (("strip", "s", S), ("panel", "p", P)):
        ivs, st = [], ((0.0, 0.0) if tl["v0"][0 if track == "s" else 1] == 1.0 else None)
        for t0, t1, a, b in tl[track]:
            if b > a:
                st = (t0, t1 - t0)
            elif st is not None:
                ivs.append((st[0], st[1], t0, t1 - t0, t1))
                st = None
        if st is not None:
            ivs.append((st[0], st[1], None, 0, duration + 1.0))
        if not ivs:
            continue
        r = t3_layout(STATES["S3"], base)[name]
        w, h = int(round(r[2])), int(round(r[3]))
        path = os.path.join(tmp, f"t3_band_{name}.png")
        _band_image(cfg, name, w, h).save(path)
        ybase = ("%.3f-%.3f*(%s)" % (r[1], (PANEL_H + GAP) * K, P)) if name == "strip" else "%.3f" % r[1]
        lay["bands"].append({"name": name, "path": path, "x": r[0], "y": "%s+(1-(%s))*%.2f" % (ybase, X, SLIDE * K), "ivs": ivs})
    y0 = float(base["y"])
    H_t = _hexpr(S, P, y0, _strip_dims(base))
    bx, bw = float(base["x"]), float(base["w"])
    bwx = "%g" % bw if not tl.get("x") else "(%g*(1-%g*(%s)))" % (bw, 1 - SPLIT_LEFT, _expr(tl["x"], 0.0))   # S4: frame width expr
    if mode == "fill":
        vw = "trunc(max(%s,%s*iw/ih)/2)*2" % (bwx, H_t)
        vh = "trunc(max(%s,%s*ih/iw)/2)*2" % (H_t, bwx)
    else:
        vw = "trunc(min(%s,%s*iw/ih)/2)*2" % (bwx, H_t)
        vh = "trunc(min(%s,%s*ih/iw)/2)*2" % (H_t, bwx)
    lay["video"] = {"vf": "scale=w='%s':h='%s':eval=frame:flags=bilinear,setsar=1" % (vw, vh),
                    "ox": "'%g+(%s-overlay_w)/2'" % (bx, bwx), "oy": "'%g+(%s-overlay_h)/2'" % (y0, H_t)}
    cfg["_t3_lay"] = lay
    cfg.pop("_t2_fg", None)                                            # the layout plates replace the single fixed plate
    cfg["video_box"] = dict({k: int(round(v)) for k, v in _box(t3_layout(_spx_at(tl, 0.0), base)["frame"]).items()}, mode=mode)


def t3_layout_video(cfg):
    """(video filter chain, overlay x expr, overlay y expr) replacing the static scale/crop in build_ffmpeg_cmd."""
    v = cfg["_t3_lay"]["video"]
    return v["vf"], v["ox"], v["oy"]


def t3_layout_inputs(cfg, fps_s, duration):
    """Extra ffmpeg input arguments (plates, transition sequences, band PNGs) in the order t3_layout_graph expects."""
    lay, a = cfg["_t3_lay"], []
    for c in lay["const"]:
        a += ["-loop", "1", "-framerate", fps_s, "-t", f"{duration:.3f}", "-i", c["path"]]
    for w in lay["windows"]:
        a += ["-framerate", fps_s, "-itsoffset", f"{w['t0']:.5f}", "-i", w["pattern"]]
    for b in lay["bands"]:
        a += ["-loop", "1", "-framerate", fps_s, "-t", f"{duration:.3f}", "-i", b["path"]]
    return a


def t3_layout_graph(cfg, cur, idx0):
    """Filter-graph fragment: plates (state / transition frames) then the bands. Returns (fragment, new current label)."""
    lay, fc, i = cfg["_t3_lay"], "", idx0
    half = 0.5 / lay["fps"]
    for j, c in enumerate(lay["const"]):
        fc += f";[{cur}][{i}:v]overlay=0:0:eof_action=pass:format=auto:enable='{c['en']}'[t3pl{j}]"
        cur, i = f"t3pl{j}", i + 1
    for j, w in enumerate(lay["windows"]):
        fc += (f";[{cur}][{i}:v]overlay=0:0:eof_action=pass:format=auto:"
               f"enable='gte(t,{w['t0'] - half:.4f})*lt(t,{w['t1'] - half:.4f})'[t3pw{j}]")
        cur, i = f"t3pw{j}", i + 1
    for j, b in enumerate(lay["bands"]):
        n = len(b["ivs"])
        fc += f";[{i}:v]format=yuva420p,split={n}" + "".join(f"[t3b{j}_{k}]" for k in range(n)) if n > 1 else \
            f";[{i}:v]format=yuva420p[t3b{j}_0]"
        for k, (u0, ud, d0, dd, end) in enumerate(b["ivs"]):
            fd = f"fade=t=in:st={u0:.4f}:d={max(ud, 0.05):.4f}:alpha=1" if ud > 0 else "null"
            if d0 is not None:
                fd += f",fade=t=out:st={d0:.4f}:d={max(dd, 0.05):.4f}:alpha=1"
            fc += (f";[t3b{j}_{k}]{fd}[t3bf{j}_{k}];[{cur}][t3bf{j}_{k}]overlay=x={b['x']:.2f}:y='{b['y']}':eof_action=pass:"
                   f"format=auto:enable='between(t,{u0:.4f},{end:.4f})'[t3bo{j}_{k}]")
            cur = f"t3bo{j}_{k}"
        i += 1
    return fc, cur


def t3_layout_input_count(cfg):
    lay = cfg["_t3_lay"]
    return len(lay["const"]) + len(lay["windows"]) + len(lay["bands"])


# ---- S4 right-frame content (T3-9) -----------------------------------------------------------------------------------------
def _seg_times(seg, tr):
    """(start, end) of a segment's content: the first one fades in with the x track, the last one fades out with it."""
    return seg["a"], seg["b"] + (tr if seg["last"] else 0.0)


def _is_video(path):
    return str(path).lower().endswith(VIDEO_EXTS)


def _right_geom(cfg):
    """(box (x, y, w, h) ints, quad local to the box) of the right frame at S4."""
    r = t3_layout("S4", _base(cfg))["right"]
    box = tuple(int(round(v)) for v in r)
    from mt.templates.t3.static import t3_frame_quad
    t3 = cfg["t3"]
    quad = t3_frame_quad((0, 0, box[2], box[3]), 0.0 if t3["frame_style"] == "straight" else t3["frame_skew"])
    return box, quad


def _quad_mask(w, h, quad, inset=2):
    ss = 3
    m = Image.new("L", (w * ss, h * ss), 0)
    cx, cy = w / 2.0, h / 2.0
    pts = []
    for px, py in quad:                                               # shrink the quad a little: the cream border covers the edge
        d = math.hypot(px - cx, py - cy) or 1.0
        pts.append(((px - (px - cx) / d * inset) * ss, (py - (py - cy) / d * inset) * ss))
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def _fit_photo(photo, w, h, mode):
    photo = photo.convert("RGB")
    if mode == "fit":
        sc = min(w / photo.width, h / photo.height)
        im = photo.resize((max(1, int(photo.width * sc)), max(1, int(photo.height * sc))), Image.LANCZOS)
        out = Image.new("RGB", (w, h), (24, 15, 12))
        out.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
        return out
    sc = max(w / photo.width, h / photo.height)
    im = photo.resize((max(w, int(round(photo.width * sc))), max(h, int(round(photo.height * sc)))), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))


def split_sprite(cfg, seg, photo=None):
    """RGBA sprite (right frame box size) of a segment: image / video frame / original-video frame, quad-masked."""
    box, quad = _right_geom(cfg)
    w, h = box[2], box[3]
    if photo is None:
        from mt.templates.t3 import panels as _pn
        photo = None
        if seg["media"] and not _is_video(seg["media"]):
            try:
                photo = Image.open(seg["media"]).convert("RGB")
                photo.load()
            except Exception:
                t3_warn(f"   [!] split image unreadable: {seg['media']}")
        elif cfg.get("video") or seg["media"]:
            photo = _pn._video_frame(seg["media"] or cfg["video"], 0.0 if seg["media"] else seg["a"])
        photo = photo or Image.new("RGB", (64, 64), (96, 96, 96))
    sp = _fit_photo(photo, w, h, seg["mode"]).convert("RGBA")
    sp.putalpha(_quad_mask(w, h, quad))
    return sp


def split_items(cfg, duration):
    """Right-frame content Items (images, or a frame of video media in a still); videos are baked layers (split_prepare_layers)."""
    segs = split_resolve(cfg, duration)
    if not segs:
        return []
    from mt.templates.t3 import dynamic as _dyn
    tr = float(cfg["t3"]["layout"]["trans"])
    box, _ = _right_geom(cfg)
    still = bool(cfg.get("_t2_still"))
    out = []
    for g in segs:
        if _is_video(g["media"]) and not still and os.path.isfile(g["media"]):
            continue
        a, b = _seg_times(g, tr)
        if not _dyn._vis(a, b):
            continue
        out.append(Item(split_sprite(cfg, g), a, b, box[0] + box[2] / 2.0, box[1] + box[3] / 2.0, "fade", tr, out=True))
    return out


def split_prepare_layers(cfg, info, tmpdir):
    """Video media of split segments -> alpha clips (quad mask + fade baked), same mechanism as the floating cards / slot media."""
    import subprocess
    from mt.anim import anim_state
    from mt.common import FFMPEG
    from mt.draw import draw_item
    if cfg.get("_t2_still") or not (cfg.get("t3") or {}).get("split", {}).get("on"):
        return []
    segs = [g for g in split_resolve(cfg, info["duration"]) if _is_video(g["media"]) and os.path.isfile(g["media"])]
    if not segs:
        return []
    W, H = cfg["canvas"]
    fps = info["fps"]
    fps_f = float(fps)
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    dur_eff = min(info["duration"], float(cfg["preview"])) if cfg.get("preview") else info["duration"]
    tr = float(cfg["t3"]["layout"]["trans"])
    box, quad = _right_geom(cfg)
    w, h = box[0:4][2], box[3]
    mask = _quad_mask(w, h, quad)
    Wp, Hp = w - w % 2, h - h % 2
    layers = []
    for n, g in enumerate(segs):
        t0, t1 = _seg_times(g, tr)
        if t0 >= dur_eff:
            continue
        e = min(t1, dur_eff)
        nfr = max(1, int(math.ceil((e - t0) * fps_f)))
        out = os.path.join(tmpdir, f"t3split{n}.mov")
        vf = f"fps={fps_s},scale={w}:{h}:force_original_aspect_ratio={'decrease' if g['mode'] == 'fit' else 'increase'}"
        vf += f",pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x180f0c,format=rgb24" if g["mode"] == "fit" else f",crop={w}:{h},format=rgb24"
        rd = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", g["media"], "-an", "-vf", vf,
                               "-frames:v", str(nfr), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        wr = subprocess.Popen([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                               "-video_size", f"{Wp}x{Hp}", "-framerate", fps_s, "-i", "pipe:0", "-c:v", "qtrle", "-pix_fmt", "argb", out],
                              stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        print(f"Preparing split clip {n + 1} ({Path(g['media']).name}, {nfr} frames)...")
        last = None
        try:
            for i in range(nfr):
                need = w * h * 3
                raw = b""
                while len(raw) < need:
                    ch = rd.stdout.read(need - len(raw))
                    if not ch:
                        break
                    raw += ch
                fr = Image.frombytes("RGB", (w, h), raw) if len(raw) == need else last
                fr = fr or Image.new("RGB", (w, h), (24, 15, 12))
                last = fr
                spr = fr.convert("RGBA")
                spr.putalpha(mask)
                it = Item(spr, t0, t1, w / 2.0, h / 2.0, "fade", tr, out=True)
                cv = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                draw_item(cv, it, anim_state(it.anim, it.progress(t0 + i / fps_f), W, H))
                wr.stdin.write(cv.crop((0, 0, Wp, Hp)).tobytes())
            wr.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        finally:
            rd.kill()
            rd.wait()
        err = wr.stderr.read().decode("utf-8", "replace")
        if wr.wait() != 0 or not os.path.isfile(out):
            raise SystemExit("[!] Could not prepare the split clip:\n" + err[-800:])
        layers.append({"path": out, "start": t0, "end": e, "area": "canvas", "mode": "fit", "fade": 0.0, "_xy": [box[0], box[1]]})
    return layers


def t3_ask_split():
    """Split-screen questions (Enter = default / last answer). Returns the t3 keys to merge ({} = no split)."""
    from mt.common import D, ask, ask_choice, yn
    from mt.templates.t3.dynamic import _c_start
    on = yn("\nAdd split-screen moments (the video shrinks to the left, an image / video appears on the right)?",
            default=D.get("t3_split", "n") == "y")
    D["t3_split"] = "y" if on else "n"
    if not on:
        return {}
    segs = []
    while len(segs) < 8:
        k = len(segs)
        print(f"--- Split moment #{k + 1} ---")
        media = ask("  Right-side image or video file ('-' = a frame of your own video)", default="-", key=f"t3_split_media{k}",
                    cast=lambda v: "" if v.strip() in ("", "-") else v.strip().strip('"'))
        mode = ("fill", "fit")[ask_choice("  Fit inside the right frame:", ["Fill (crop)", "Fit (whole picture)"], default=1,
                                          key=f"t3_split_mode{k}") - 1]
        kind, val = ask("  Starts at (seconds / mm:ss / spoken phrase)", default="2" if k == 0 else None, key=f"t3_split_st{k}",
                        cast=_c_start)
        hold = ask("  Stays (seconds)", default=4, key=f"t3_split_hold{k}", cast=float)
        segs.append({"start": val if kind == "t" else None, "trigger": val if kind == "p" else "", "hold": hold, "media": media,
                     "mode": mode})
        if not yn("Add another split moment?", default=False):
            break
    return {"split": {"on": True, "segments": segs}, "layout": {"on": True, "mode": "auto"}}
