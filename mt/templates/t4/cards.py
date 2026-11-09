"""mt.templates.t4.cards - Template 4 module 'cards' (refs R2 right card, R8 PiP card + label): IMAGE cards - a picture inside a chamfered
neon border, an optional connector line that ends in a glowing dot at a target point, and an optional label tag with slanted stripes.
Images only here; video media arrives with P13 (a video path = gray placeholder + one warning). Drawing lives in cards_art.py.
cfg['t4']['cards'] = [card, ...]   (also accepted: one card dict, or {on, cards: [...]})   card = {
    media  path           the picture (png / jpg / webp ...). Missing / unreadable / video -> gray placeholder + one t4_warn line.
    label  'TEXT' | {text, color, anchor}   tag overlapping a card corner (anchor bottom-right default | bottom-left | top-right | top-left).
                          Latin text is capitalised; > 11 characters -> two balanced lines (or use '\\n' / '|'); '' / '-' = no label.
    anchor 'top-right' | xy   one of the 9 positions (top-left top top-right left center right bottom-left bottom bottom-right) with inset_x /
                          inset_y px; xy = [x, y] = the centre of the card block (px or '40%'). Default anchor 'top-right' (R8).
    width 480, height     picture width px (short side 1080); height default = the picture's own shape (width / height clamped 0.75 - 1.8).
    color '#19D3FF'       border / stripes / label colour
    connector {target [x, y] | points [...], side auto|left|right|top|bottom, style elbow|line, attach 0.35, color, end_dot True|'both'|'start'|
               False, width, glow}   target = canvas px or '%' strings; points may also be 'card' / 'card-top|bottom|left|right'. Shorthand:
               connector = [x, y]. Elbow = straight - 45 degree diagonal - straight (R2); line = one straight segment (R8).
    start | trigger, end | hold (default 5 s), anim 'auto' (= 'pop'; 'fade' / 'none' / any mt.anim name), anim_dur 0.45 }
Behaviour: the card pops in (anim 't4_pop'), the connector fades in right after it, everything fades out together at the end. The connector is
drawn UNDER the card (its start is hidden inside the border). Ink (card + label + glow) stays >= 48 px from the canvas edges; frame on (P8): the
card moves inward until it clears the frame plate (same search as the name tag). One sprite Item per card (+ one for the connector), cached.
Public: T4_CARD, t4_cards_cfg(raw) -> [card], t4_cards_items(cfg, duration), t4_ask_image_cards()."""
import copy
import os

from mt.anim import ANIMS
from mt.ask import ask_anim
from mt.common import IMAGE_EXTS, ask, ask_choice, c_existing_file, c_float, yn
from mt.draw import Item
from mt.templates.t4.cards_art import _aspect, t4_card_sprite, t4_load_media
from mt.templates.t4.cfg import _hex
from mt.templates.t4.frame import t4_frame_cfg
from mt.templates.t4.kit import connector
from mt.templates.t4.nameplate import T4_SAFE, _anchor as _corner, _bool, _cached, _flt, _font, _frame_mask, _place, _window
from mt.templates.t4.tiles import ANCHORS, TileItem, _anchor, _coord, _place_xy, _point, _warn_overlaps
from mt.templates.t4.timing import t4_ask_when
from mt.templates.t4.warn import t4_warn

T4_CARD = {"on": True, "media": "", "label": {}, "anchor": "top-right", "xy": None, "width": 480.0, "height": None, "inset_x": 0.0, "inset_y": 0.0,
           "color": "#19d3ff", "connector": {}, "start": 0.0, "trigger": "", "end": None, "hold": None, "anim": "auto", "anim_dur": 0.45}
_CONN = {"target": None, "points": [], "side": "auto", "style": "elbow", "attach": 0.35, "color": "", "end_dot": True, "width": 2.5, "glow": 9.0}
_TOKENS = ("card", "card-top", "card-bottom", "card-left", "card-right")
_SPR = {}


# ---- config -----------------------------------------------------------------------------------------------------------------
def _cpoint(p):
    """[x, y] | 'x,y' | a card token -> [x, y] | token | None."""
    if isinstance(p, str) and p.strip().lower() in _TOKENS:
        return p.strip().lower()
    q = _point(p)
    return q if isinstance(q, list) else None


def _label(raw):
    """'TEXT' | {text, color, anchor} -> {text, color, anchor} or {} (no label)."""
    d = raw if isinstance(raw, dict) else {"text": raw}
    t = d.get("text")
    t = str(t).strip()[:80] if isinstance(t, (str, int, float)) and not isinstance(t, bool) else ""
    if t.lower() in ("", "-", "none"):
        return {}
    c = d.get("color")
    return {"text": t, "color": _hex(c, "") if isinstance(c, str) else "", "anchor": _corner(d.get("anchor"), "bottom-right")}


def _connector(raw):
    """Connector dict | [x, y] shorthand -> complete dict, or {} when it has neither a target nor >= 2 points."""
    if isinstance(raw, (list, tuple, str)):
        raw = {"target": raw}
    if not isinstance(raw, dict):
        return {}
    out = copy.deepcopy(_CONN)
    out["target"] = _cpoint(raw.get("target"))
    out["target"] = out["target"] if isinstance(out["target"], list) else None
    pts = [_cpoint(p) for p in raw.get("points", [])] if isinstance(raw.get("points"), (list, tuple)) else []
    out["points"] = [p for p in pts if p is not None][:12]
    side, style = str(raw.get("side", "")).strip().lower(), str(raw.get("style", "")).strip().lower()
    out["side"] = side if side in ("left", "right", "top", "bottom") else "auto"
    out["style"] = "line" if style in ("line", "straight") else "elbow"
    out["attach"] = _flt(raw.get("attach"), 0.05, 0.95, 0.35)
    out["color"] = _hex(raw.get("color"), "") if isinstance(raw.get("color"), str) else ""
    ed = raw.get("end_dot")
    out["end_dot"] = ed if ed in (True, False, "both", "start") else True
    out["width"], out["glow"] = _flt(raw.get("width"), 0.5, 30, 2.5), _flt(raw.get("glow"), 0, 60, 9.0)
    return out if (out["target"] is not None or len(out["points"]) >= 2) else {}


def _card(raw):
    out = copy.deepcopy(T4_CARD)
    out.update({k: copy.deepcopy(v) for k, v in raw.items() if k not in out})                          # extras survive
    m = raw.get("media")
    out["media"] = m.strip() if isinstance(m, str) else ""
    out["label"] = _label(raw.get("label"))
    out["anchor"] = _anchor(raw.get("anchor"), "top-right")
    xy = _point(raw.get("xy"))
    out["xy"] = xy if isinstance(xy, list) else None
    out["width"] = _flt(raw.get("width"), 120, 1800, 480.0)
    h = _flt(raw.get("height"), 80, 2400, None)
    out["height"] = h
    out["inset_x"], out["inset_y"] = _flt(raw.get("inset_x"), 0, 600, 0.0), _flt(raw.get("inset_y"), 0, 600, 0.0)
    out["color"] = _hex(raw.get("color"), "#19d3ff")
    out["connector"] = _connector(raw.get("connector"))
    trig = raw.get("trigger")
    out["trigger"] = trig.strip() if isinstance(trig, str) else ""
    out["start"] = raw["start"] if raw.get("start") is not None else (None if out["trigger"] else 0.0)      # a phrase never falls back to 0
    out["end"], out["hold"] = raw.get("end"), raw.get("hold")
    a = raw.get("anim")
    a = ("reveal" if a.strip().lower() == "typewriter" else a.strip().lower()) if isinstance(a, str) else "auto"
    out["anim"] = a if a in ANIMS or a in ("auto", "pop", "none") else "auto"
    out["anim_dur"] = _flt(raw.get("anim_dur"), 0.0, 5.0, 0.45)
    out["on"] = _bool(raw.get("on"), True)
    return out


def t4_cards_cfg(raw):
    """Normalise cfg['t4']['cards'] -> list of complete cards. Accepts a list, one card dict or {on, cards: [...]} (module default {'on': False}
    = no cards). Never raises; junk entries are dropped."""
    try:
        if isinstance(raw, dict) and "media" in raw:
            raw = [raw]
        elif isinstance(raw, dict):
            raw = raw.get("cards") if _bool(raw.get("on"), False) else []
        return [_card(c) for c in raw if isinstance(c, dict)] if isinstance(raw, (list, tuple)) else []
    except Exception:
        return []


# ---- connector geometry -----------------------------------------------------------------------------------------------------
def _side(side, rect, tx, ty):
    """'auto' = the card side that faces the target: the axis with the larger gap decides (left / right beside the card, top / bottom above or
    below it); a target inside the card's footprint leaves from the bottom."""
    if side != "auto":
        return side
    x0, y0, x1, y1 = rect
    gx, gy = max(x0 - tx, tx - x1, 0.0), max(y0 - ty, ty - y1, 0.0)
    if gx > 0 and gx >= gy:
        return "left" if tx < x0 else "right"
    return ("top" if ty < y0 else "bottom") if gy > 0 else "bottom"


def _edge_point(rect, side, attach):
    x0, y0, x1, y1 = rect
    return {"left": (x0, y0 + (y1 - y0) * attach), "right": (x1, y0 + (y1 - y0) * attach),
            "top": (x0 + (x1 - x0) * attach, y0), "bottom": (x0 + (x1 - x0) * attach, y1)}[side]


def _elbow(start, target, side, style):
    """start -> target: one straight segment ('line'), or straight - 45 degree diagonal - straight along the leaving direction (R2)."""
    (sx, sy), (tx, ty) = start, target
    horiz = side in ("left", "right")
    along, across = (abs(tx - sx), abs(ty - sy)) if horiz else (abs(ty - sy), abs(tx - sx))
    if style == "line" or across < 2 or along <= across + 4:
        return [start, target]
    a = (along - across) / 2.0                                   # the diagonal eats `across` of the run; the rest is split before / after it
    d = (1 if (tx > sx if horiz else ty > sy) else -1)
    p1, p2 = ((sx + d * a, sy), (sx + d * (a + across), ty)) if horiz else ((sx, sy + d * a), (tx, sy + d * (a + across)))
    return [start, p1, p2, target]


def _conn_points(c, rect, W, H, s):
    """Resolve the connector to canvas px points; everything is clamped so the visible ink (glow tail + end dot) stays in the 48 px safe area."""
    x0, y0, x1, y1 = rect
    named = {"card": ((x0 + x1) / 2.0, (y0 + y1) / 2.0), "card-top": ((x0 + x1) / 2.0, y0), "card-bottom": ((x0 + x1) / 2.0, y1),
             "card-left": (x0, (y0 + y1) / 2.0), "card-right": (x1, (y0 + y1) / 2.0)}
    if c["points"] and len(c["points"]) >= 2:
        pts = [named[p] if isinstance(p, str) else (_coord(p[0], W, s), _coord(p[1], H, s)) for p in c["points"]]
    else:
        tx, ty = _coord(c["target"][0], W, s), _coord(c["target"][1], H, s)
        side = _side(c["side"], rect, tx, ty)
        pts = _elbow(_edge_point(rect, side, c["attach"]), (tx, ty), side, c["style"])
    m = (T4_SAFE + c["glow"] * 1.6 + 2) * s
    return [(min(max(x, m), W - m), min(max(y, m), H - m)) for x, y in pts]


# ---- items ------------------------------------------------------------------------------------------------------------------
def _card_sprite(c, s, W, H):
    """Cached (sprite, warning) of one card at canvas scale s."""
    cw = c["width"] * s
    if c["height"]:
        ch = c["height"] * s
    else:
        img, _msg = t4_load_media(c["media"])
        ch = cw / _aspect(img)
    lab, fp = c["label"], _font(c.get("font"))
    key = (c["media"], _mtime(c["media"]), repr(lab), round(cw), round(ch), c["color"], fp)
    return _cached(_SPR, key, lambda: t4_card_sprite(c["media"], lab.get("text", ""), cw, ch, c["color"], fp, lab.get("anchor", "bottom-right"),
                                                     lab.get("color") or None), 16)


def _mtime(path):
    return os.path.getmtime(path) if path and os.path.isfile(str(path)) else 0


def _make_item(spr, st, en, cx, cy, c):
    if c["anim"] in ("auto", "pop"):
        return TileItem(spr, st, en, cx, cy, "t4_pop", c["anim_dur"], out=True)
    return Item(spr, st, en, cx, cy, c["anim"], c["anim_dur"], out=True)


def _one_card(cfg, c, idx, duration, W, H, s, fm, placed):
    label = "card %d" % (idx + 1)
    win = _window(cfg, c, label, duration, 5.0)
    if win is None:
        return []
    spr, msg = _card_sprite(c, s, W, H)
    if msg:
        t4_warn(msg)
    pl = _place_xy(spr, c["xy"], W, H, s) if c["xy"] else _place(spr, c["anchor"], W, H, s, c["inset_x"], c["inset_y"], fm, label)
    if pl is None:
        return []
    cx, cy, ink, _ = pl
    placed.append((label, ink))
    left, top = cx - spr.width / 2.0, cy - spr.height / 2.0
    x0, y0, x1, y1 = spr.info["card"]
    rect = (left + x0, top + y0, left + x1, top + y1)
    last = max(win[0], win[1] - 0.1)
    items = []
    if c["connector"]:
        k = c["connector"]
        col = k["color"] or c["color"]
        csp = connector(_conn_points(k, rect, W, H, s), col, k["end_dot"], k["width"] * s, k["glow"] * s)
        ox, oy = csp.info["origin"]
        items.append(Item(csp, min(win[0] + c["anim_dur"] * 0.8, last), win[1], -ox + csp.width / 2.0, -oy + csp.height / 2.0, "fade", c["anim_dur"], out=True))
    items.append(_make_item(spr, win[0], win[1], cx, cy, c))                              # last = on top of the connector
    return items


def t4_cards_items(cfg, duration):
    """Items of every card: [connector (fade), card (pop)] per card, all ending together. Never raises; [] when the module is off."""
    t4 = cfg.get("t4") if isinstance(cfg, dict) and isinstance(cfg.get("t4"), dict) else {}
    cards = [c for c in t4_cards_cfg(t4.get("cards")) if c["on"]]
    if not cards:
        return []
    try:
        W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        t4_warn("t4 cards: the job has no canvas - skipped.")
        return []
    s, items, placed = min(W, H) / 1080.0, [], []
    try:
        fm = _frame_mask(W, H, t4_frame_cfg(t4.get("frame")), s)
        for i, c in enumerate(cards):
            items += _one_card(cfg, c, i, duration, W, H, s, fm, placed)
        _warn_overlaps(placed)
    except Exception as e:
        t4_warn("t4 cards: could not be drawn (%s: %s) - skipped." % (type(e).__name__, e))
    return items


# ---- questions --------------------------------------------------------------------------------------------------------------
def _c_target(s):
    p = _cpoint(s.strip())
    if p is None or isinstance(p, str):
        raise ValueError("enter a point like  300,900  or  25%,60%  (px or %)")
    return p


def t4_ask_image_cards():
    """Question group 'cards' (called by t4_ask_config). -> a list with ONE card, or {'on': False}. More cards: edit the job file."""
    if not yn("Add an image card (picture in a neon border, optional label + connector - references R2 / R8)?", default=False):
        return {"on": False}
    c = {"media": ask("Card picture (PNG / JPG path)", key="t4_card_img", cast=c_existing_file(IMAGE_EXTS))}
    lab = ask("Label text on the card (Enter / '-' = none, e.g. LIVE CODING DEVELOPMENT)", default="-", key="t4_card_label", cast=lambda s: s.strip())
    c["label"] = "" if lab in ("", "-") else lab
    c["width"] = ask("Card width (px, for a 1080 px short side)", default=T4_CARD["width"], key="t4_card_width", cast=c_float)
    a = ask_choice("Where?", ["Top-left", "Top", "Top-right", "Left", "Center", "Right", "Bottom-left", "Bottom", "Bottom-right"], default=3, key="t4_card_anchor")
    c["anchor"] = ANCHORS[a - 1]
    if yn("Add a connector line ending in a glowing dot?", default=False):
        c["connector"] = {"target": ask("Dot position  x,y  (px or %, e.g. 22%,38%)", default="20%,40%", key="t4_card_target", cast=_c_target)}
    c.update(t4_ask_when("Image card", 5.0, key="t4_card_when"))
    c["anim"] = ask_anim("Card animation (auto = pop in, fade out)", default="pop", key="t4_card_anim")
    return [c]
