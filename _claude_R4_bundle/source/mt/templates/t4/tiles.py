"""mt.templates.t4.tiles - Template 4 module 'tiles' (ref R2, left side): groups of dark glass tiles, each holding a user logo (PNG ...,
fitted + centred), laid out in a grid, optionally with a neon connector polyline that ends in a glowing dot at a target point.
cfg['t4']['tiles'] = [group, ...]   (also accepted: one group dict, or {on, groups: [...]})   group = {
    images [paths]       the logos, row by row (<= 12). A missing / unreadable file -> gray placeholder tile + one t4_warn line.
    cols 2, gap 18, size 150   grid columns (a short last row is centred), px between tiles, tile edge (px at short side 1080)
    anchor 'left' | xy     anchor = one of the 9 positions (top-left top top-right left center right bottom-left bottom bottom-right) with
                           inset_x / inset_y px; xy = [x, y] = the CENTRE of the group (px, or '40%' strings). Default anchor 'left'.
    border '#C4D6EF'       tile border colour (light, as R2)
    connector {points [[x, y] ...], color, end_dot True|'both'|'start'|False, width, glow}   points in canvas px or '%' strings; a point may
                           also be 'group', 'group-top|bottom|left|right' = that point of the tile group. >= 2 points, drawn after the tiles.
    start | trigger, end | hold (default 5 s), anim 'pop' (default; 'fade' / 'none' / any mt.anim name), anim_dur 0.35, stagger 0.12 s }
Behaviour: the tiles pop in one after another (t4_stagger), the connector fades in after the last one, and everything fades out together at the
group's end (anim 'pop' = anim 't4_pop' in mt/anim.py: pop in, pure fade out; other anims run reversed). Ink stays >= 48 px from the canvas
edges (connector points are clamped into the safe area). Frame on (P8): an anchored group moves inward until it clears the frame (same search as
the name tag); an xy group is only clamped to the safe area. Each tile = ONE sprite Item (cached); nothing is drawn per frame but the animation.
Public: T4_TILES, t4_tiles_cfg(raw) -> [group], t4_tile_sprite(path, size, border, scale), t4_tiles_items(cfg, duration), t4_ask_tiles()."""
import copy
import math
import os
from pathlib import Path

from PIL import Image

from mt.anim import ANIMS, PRESETS
from mt.ask import ask_anim
from mt.common import IMAGE_EXTS, ask, ask_choice, c_color, c_existing_file, c_float, c_int, yn
from mt.draw import Item, t2_paint, t2_rrect_mask
from mt.templates.t4.cfg import _hex
from mt.templates.t4.frame import t4_frame_cfg
from mt.templates.t4.kit import connector, glass_panel, kit_paste
from mt.templates.t4.nameplate import T4_SAFE, _bool, _cached, _flt, _frame_mask, _place, _window
from mt.templates.t4.timing import t4_ask_when, t4_stagger
from mt.templates.t4.warn import t4_warn

ANCHORS = ("top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right")
MAX_IMAGES = 12
LOGO_FRAC = 0.60                                       # the logo fills this fraction of the tile (R2: ~55-65 %)
TINT = (8, 16, 36, 150)                                # tile glass (rgba): translucent, the video shows through
T4_TILES = {"on": True, "images": [], "cols": 2, "gap": 18.0, "size": 150.0, "anchor": "left", "xy": None, "inset_x": 0.0, "inset_y": 0.0,
            "border": "#c4d6ef", "connector": {}, "start": 0.0, "trigger": "", "end": None, "hold": None, "anim": "pop", "anim_dur": 0.35,
            "stagger": 0.12}
_CONN = {"points": [], "color": "#19d3ff", "end_dot": True, "width": 2.5, "glow": 9.0}
_TOKENS = ("group", "group-top", "group-bottom", "group-left", "group-right")
_TILE = {}


# ---- config -----------------------------------------------------------------------------------------------------------------
def _anchor(v, default):
    s = str(v).strip().lower().replace("_", "-").replace(" ", "-") if isinstance(v, (str, int)) and not isinstance(v, bool) else ""
    s = PRESETS.get(s, s)
    s = {"middle": "center", "centre": "center", "top-center": "top", "bottom-center": "bottom"}.get(s, s)
    return s if s in ANCHORS else default


def _num_or_pct(v):
    """12, '12', '40%' -> kept as given (number or 'NN%' string); anything else -> None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        t = v.strip()
        try:
            return t if t.endswith("%") and math.isfinite(float(t[:-1])) else float(t)
        except ValueError:
            return None
    return None


def _point(p):
    """[x, y] / (x, y) / 'x,y' / a group token -> [x, y] | token | None."""
    if isinstance(p, str):
        t = p.strip().lower()
        if t in _TOKENS:
            return t
        p = [a for a in t.replace(";", ",").split(",")]
    if isinstance(p, (list, tuple)) and len(p) == 2:
        a, b = _num_or_pct(p[0]), _num_or_pct(p[1])
        return [a, b] if a is not None and b is not None else None
    return None


def _conn(raw):
    out = copy.deepcopy(_CONN)
    if not isinstance(raw, dict):
        return {}
    pts = [_point(p) for p in raw.get("points", [])] if isinstance(raw.get("points"), (list, tuple)) else []
    out["points"] = [p for p in pts if p is not None][:12]
    out["color"] = _hex(raw.get("color"), out["color"])
    ed = raw.get("end_dot")
    out["end_dot"] = ed if ed in (True, False, "both", "start") else True
    out["width"], out["glow"] = _flt(raw.get("width"), 0.5, 30, 2.5), _flt(raw.get("glow"), 0, 60, 9.0)
    return out if len(out["points"]) >= 2 else {}


def _group(raw):
    out = copy.deepcopy(T4_TILES)
    out.update({k: copy.deepcopy(v) for k, v in raw.items() if k not in out})                       # extras survive
    imgs = raw.get("images")
    out["images"] = [i.strip() for i in imgs if isinstance(i, str) and i.strip()][:MAX_IMAGES] if isinstance(imgs, (list, tuple)) else []
    try:
        out["cols"] = max(1, min(8, int(raw.get("cols", 2))))
    except (TypeError, ValueError, OverflowError):
        out["cols"] = 2
    out["gap"], out["size"] = _flt(raw.get("gap"), 0, 200, 18.0), _flt(raw.get("size"), 40, 600, 150.0)
    out["anchor"] = _anchor(raw.get("anchor"), "left")
    xy = _point(raw.get("xy"))
    out["xy"] = xy if isinstance(xy, list) else None
    out["inset_x"], out["inset_y"] = _flt(raw.get("inset_x"), 0, 600, 0.0), _flt(raw.get("inset_y"), 0, 600, 0.0)
    out["border"] = _hex(raw.get("border"), "#c4d6ef")
    out["connector"] = _conn(raw.get("connector"))
    trig = raw.get("trigger")
    out["trigger"] = trig.strip() if isinstance(trig, str) else ""
    out["start"] = raw["start"] if raw.get("start") is not None else (None if out["trigger"] else 0.0)      # a phrase never falls back to 0
    out["end"], out["hold"] = raw.get("end"), raw.get("hold")
    a = raw.get("anim")
    a = ("reveal" if a.strip().lower() == "typewriter" else a.strip().lower()) if isinstance(a, str) else "pop"
    out["anim"] = a if a in ANIMS or a in ("pop", "none") else "pop"
    out["anim_dur"], out["stagger"] = _flt(raw.get("anim_dur"), 0.0, 5.0, 0.35), _flt(raw.get("stagger"), 0.0, 2.0, 0.12)
    out["on"] = _bool(raw.get("on"), True)
    return out


def t4_tiles_cfg(raw):
    """Normalise cfg['t4']['tiles'] -> list of complete groups. Accepts a list of groups, one group dict or {on, groups: [...]} (module
    default {'on': False} = no groups). Never raises; junk entries are dropped."""
    try:
        if isinstance(raw, dict) and "images" in raw:
            raw = [raw]
        elif isinstance(raw, dict):
            raw = raw.get("groups") if _bool(raw.get("on"), False) else []
        return [_group(g) for g in raw if isinstance(g, dict)] if isinstance(raw, (list, tuple)) else []
    except Exception:
        return []


# ---- sprites ----------------------------------------------------------------------------------------------------------------
def _load_logo(path):
    """-> RGBA image, or None (missing / not an image). First frame of animated files."""
    try:
        if not path or not os.path.isfile(str(path)):
            return None
        with Image.open(str(path)) as im:
            im.seek(0)
            return im.convert("RGBA")
    except Exception:
        return None


def _placeholder(box):
    """Gray rounded square with a small 'image' mark - stands in for a missing logo (box = px)."""
    n = max(8, int(box))
    ph = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    t2_paint(ph, t2_rrect_mask((0, 0, n, n), n * 0.16), (128, 132, 140), 0.85)
    t2_paint(ph, t2_rrect_mask((n * 0.20, n * 0.24, n * 0.80, n * 0.76), n * 0.06), (60, 64, 72), 0.9)
    t2_paint(ph, t2_rrect_mask((n * 0.30, n * 0.56, n * 0.50, n * 0.68), n * 0.03), (160, 166, 176))
    return ph


def _build_tile(path, size, border, scale):
    sz = max(24, int(round(size * scale)))
    sp = glass_panel((sz, sz), sz * 0.22, TINT, border, 0, max(1.4, sz * 0.010), max(2.5, sz * 0.022))      # thin soft border as R2
    ox, oy = sp.info["origin"]
    box, msg = int(round(sz * LOGO_FRAC)), None
    logo = _load_logo(path)
    if logo is None:
        msg = "tiles: image '%s' is missing or not a readable image - gray placeholder." % (Path(str(path)).name or "(empty path)")
        logo = _placeholder(box)
    k = min(box / logo.width, box / logo.height)
    lw, lh = max(1, int(round(logo.width * k))), max(1, int(round(logo.height * k)))
    logo = logo.resize((lw, lh), Image.LANCZOS)
    kit_paste(sp, logo, ox + (sz - lw) / 2.0, oy + (sz - lh) / 2.0)
    sp.info["panel"] = sz
    return sp, msg


def t4_tile_sprite(path, size=150, border="#c4d6ef", scale=1.0):
    """One glass tile with the logo fitted + centred -> RGBA sprite (glow margin included; sprite.info['origin'] = the tile's top-left,
    sprite.info['panel'] = tile edge px). A missing / unreadable file gives a gray placeholder (the one-line warning goes through t4_warn).
    Cached per (path, size, border, scale); a cache hit warns again so a new render still reports it (t4_warn prints once per render)."""
    key = (str(path), round(float(size) * float(scale)), str(border), round(float(scale), 3), os.path.getmtime(path) if path and os.path.isfile(str(path)) else 0)
    sp, msg = _cached(_TILE, key, lambda: _build_tile(path, float(size), border, float(scale)), 48)
    if msg:
        t4_warn(msg)
    return sp


# ---- layout -----------------------------------------------------------------------------------------------------------------
def _grid(n, cols, size, gap):
    """Top-left of every tile inside the group box + the box size; a short last row is centred. -> ([(x, y)], gw, gh)."""
    cols = max(1, min(cols, n))
    rows = int(math.ceil(n / float(cols)))
    gw, gh = cols * size + (cols - 1) * gap, rows * size + (rows - 1) * gap
    pos = []
    for i in range(n):
        r, c = divmod(i, cols)
        in_row = min(cols, n - r * cols)
        pos.append((c * (size + gap) + (cols - in_row) * (size + gap) / 2.0, r * (size + gap)))
    return pos, gw, gh


def _footprint(tiles, pos, gw, gh, pad):
    """All tiles composited into one sprite - only used to measure the group's ink for the anchor / frame placement."""
    fp = Image.new("RGBA", (int(gw) + 2 * pad, int(gh) + 2 * pad), (0, 0, 0, 0))
    for sp, (x, y) in zip(tiles, pos):
        ox, oy = sp.info["origin"]
        fp.alpha_composite(sp, (int(round(pad + x)) - ox, int(round(pad + y)) - oy))
    return fp


def _coord(v, total, s):
    return total * float(v[:-1]) / 100.0 if isinstance(v, str) else float(v) * s


def _conn_points(c, gbox, W, H, s):
    """Resolve numbers / '%' / group tokens to canvas px, clamped so the line's VISIBLE ink (glow tail + end dot) stays in the 48 px safe area."""
    m, out = (T4_SAFE + c["glow"] * 1.6 + 2) * s, []
    gx0, gy0, gx1, gy1 = gbox
    named = {"group": ((gx0 + gx1) / 2.0, (gy0 + gy1) / 2.0), "group-top": ((gx0 + gx1) / 2.0, gy0), "group-bottom": ((gx0 + gx1) / 2.0, gy1),
             "group-left": (gx0, (gy0 + gy1) / 2.0), "group-right": (gx1, (gy0 + gy1) / 2.0)}
    for p in c["points"]:
        x, y = named[p] if isinstance(p, str) else (_coord(p[0], W, s), _coord(p[1], H, s))
        out.append((min(max(x, m), W - m), min(max(y, m), H - m)))
    return out


# ---- items ------------------------------------------------------------------------------------------------------------------
class TileItem(Item):
    """Tile with anim 't4_pop': in = pop, out = pure fade (progress < 0 encodes the exit, see mt/anim.py)."""

    def progress(self, t):
        L = self.end - self.start
        d = min(self.dur, L / 2.0)
        if d <= 1e-6:
            return 1.0
        pin, pout = (t - self.start) / d, (self.end - t) / d
        if pout < 1.0 and pout <= pin:
            return -max(0.0, pout)
        return max(0.0, min(1.0, pin))


def _make_item(sp, st, en, cx, cy, c):
    if c["anim"] == "pop":
        return TileItem(sp, st, en, cx, cy, "t4_pop", c["anim_dur"], out=True)
    return Item(sp, st, en, cx, cy, c["anim"], c["anim_dur"], out=True)


def _conn_sprite(c, pts, s):
    """Connector sprite + the item centre that puts its local (0, 0) back on the canvas origin (points are canvas coordinates)."""
    k = c["connector"]
    sp = connector(pts, k["color"], k["end_dot"], k["width"] * s, k["glow"] * s)
    ox, oy = sp.info["origin"]
    return sp, -ox + sp.width / 2.0, -oy + sp.height / 2.0


def _one_group(cfg, c, idx, duration, W, H, s, fm, placed):
    label = "tiles group %d" % (idx + 1)
    if not c["images"]:
        t4_warn("%s: no images - skipped." % label)
        return []
    win = _window(cfg, c, label, duration, 5.0)
    if win is None:
        return []
    n, size, gap = len(c["images"]), c["size"] * s, c["gap"] * s
    tiles = [t4_tile_sprite(p, c["size"], c["border"], s) for p in c["images"]]
    pos, gw, gh = _grid(n, c["cols"], size, gap)
    pad = tiles[0].info["origin"][0]
    fp = _footprint(tiles, pos, gw, gh, pad)
    if c["xy"]:
        pl = _place_xy(fp, c["xy"], W, H, s)
    else:
        pl = _place(fp, c["anchor"], W, H, s, c["inset_x"], c["inset_y"], fm, label)
    if pl is None:
        return []
    fcx, fcy, rect, _ = pl
    placed.append((label, rect))
    left, top = fcx - fp.width / 2.0, fcy - fp.height / 2.0                       # the footprint sprite's top-left on the canvas
    steps = t4_stagger(n, c["stagger"])
    last = max(win[0], win[1] - 0.1)
    items = [_make_item(sp, min(win[0] + d, last), win[1], left + pad + x + size / 2.0, top + pad + y + size / 2.0, c)
             for sp, (x, y), d in zip(tiles, pos, steps)]
    if c["connector"]:
        gbox = (left + pad, top + pad, left + pad + gw, top + pad + gh)
        sp, cx, cy = _conn_sprite(c, _conn_points(c["connector"], gbox, W, H, s), s)
        items.append(Item(sp, min(win[0] + (steps[-1] if steps else 0.0) + c["anim_dur"], last), win[1], cx, cy, "fade", c["anim_dur"], out=True))
    return items


def _place_xy(fp, xy, W, H, s):
    """Group centred on xy (px / '%'), then clamped so its ink keeps the 48 px safe margin -> same tuple as nameplate._place."""
    from mt.templates.t4.nameplate import _ink_box
    box = _ink_box(fp)
    if box is None:
        return None
    w, h, m = box[2] - box[0], box[3] - box[1], T4_SAFE * s
    x = int(round(min(max(_coord(xy[0], W, s) - w / 2.0, m), W - m - w)))
    y = int(round(min(max(_coord(xy[1], H, s) - h / 2.0, m), H - m - h)))
    return x - box[0] + fp.width / 2.0, y - box[1] + fp.height / 2.0, (x, y, x + w, y + h), 0


def _warn_overlaps(placed):
    for i, (a, ra) in enumerate(placed):
        for b, rb in placed[i + 1:]:
            if ra[0] < rb[2] and rb[0] < ra[2] and ra[1] < rb[3] and rb[1] < ra[3]:
                t4_warn("%s and %s overlap - give one of them another anchor / xy." % (a, b))


def t4_tiles_items(cfg, duration):
    """Items of every tiles group: one per tile (staggered pop-in) + one for the connector; all fade out together. Never raises."""
    t4 = cfg.get("t4") if isinstance(cfg, dict) and isinstance(cfg.get("t4"), dict) else {}
    groups = [g for g in t4_tiles_cfg(t4.get("tiles")) if g["on"]]
    if not groups:
        return []
    try:
        W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        t4_warn("t4 tiles: the job has no canvas - skipped.")
        return []
    s, items, placed = min(W, H) / 1080.0, [], []
    try:
        fm = _frame_mask(W, H, t4_frame_cfg(t4.get("frame")), s)
        for i, g in enumerate(groups):
            items += _one_group(cfg, g, i, duration, W, H, s, fm, placed)
        _warn_overlaps(placed)
    except Exception as e:
        t4_warn("t4 tiles: could not be drawn (%s: %s) - skipped." % (type(e).__name__, e))
    return items


# ---- questions --------------------------------------------------------------------------------------------------------------
def _c_points(s):
    pts = [_point(p.strip()) for p in s.replace("|", ";").split(";") if p.strip()]
    if len(pts) < 2 or any(p is None for p in pts):
        raise ValueError("enter at least 2 points like  100,900; 250,1000  (px or %, or the words group-bottom / group-right ...)")
    return pts


def t4_ask_tiles():
    """Question group 'tiles' (called by t4_ask_config). -> a list with ONE group, or {'on': False}. More groups: edit the job file."""
    if not yn("Add glass logo tiles (PNG logos in a grid - reference R2)?", default=False):
        return {"on": False}
    imgs = []
    while len(imgs) < MAX_IMAGES:
        p = ask("Logo %d (PNG / image path, Enter = %s)" % (len(imgs) + 1, "done" if imgs else "at least one is needed"),
                key="t4_tiles_img%d" % (len(imgs) + 1), cast=c_existing_file(IMAGE_EXTS), allow_empty=bool(imgs))
        if not p:
            break
        imgs.append(p)
    g = {"images": imgs, "cols": ask("Columns", default=2, key="t4_tiles_cols", cast=c_int),
         "size": ask("Tile size (px, for a 1080 px short side)", default=T4_TILES["size"], key="t4_tiles_size", cast=c_float)}
    a = ask_choice("Where?", ["Top-left", "Top", "Top-right", "Left", "Center", "Right", "Bottom-left", "Bottom", "Bottom-right"],
                   default=4, key="t4_tiles_anchor")
    g["anchor"] = ANCHORS[a - 1]
    if yn("Add a connector line ending in a glowing dot?", default=False):
        pts = ask("Connector points  x,y; x,y; ...  (px or %, first may be group-bottom / group-right)", default="group-bottom; 30%,55%",
                  key="t4_tiles_conn", cast=_c_points)
        g["connector"] = {"points": pts, "end_dot": yn("Dot at both ends (No = only at the target)?", default=False) and "both" or True}
    g.update(t4_ask_when("Logo tiles", 5.0, key="t4_tiles_when"))
    g["anim"] = ask_anim("Tile animation (pop = staggered pop-in, fade-out together)", default="pop", key="t4_tiles_anim")
    return [g]
