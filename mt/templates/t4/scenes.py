"""mt.templates.t4.scenes - Template 4 module 'scenes' (refs R5 portrait / R6 landscape): infographic scenes built from WIDGETS placed in SLOTS.
cfg['t4']['scenes'] = [scene, ...]   (also accepted: one scene dict, or {on, scenes: [...]}; module default {'on': False} = none)
scene = {
    preset 'web_dev'         names the slot set (SLOTS) + connector lines (CONNECTORS); unknown -> one warning, 'web_dev'
    widgets [{type, slot, box, on, ...widget keys}]   type = a name from scenes_reg.WIDGETS; slot = a slot of the preset (default: the widget's
                             own default slot); box [x, y, w, h] (px at short side 1080) replaces the slot. Unknown type / slot -> one warning, skipped.
    start | trigger, end | hold (default 6 s)   timing via t4_time (spoken phrase must be in the captions)
    anim 'fade' (default; 'pop' / 'none' / any mt.anim name), anim_dur 0.45, stagger 0.2 (s between widgets)
    connectors None | [] | [{points, color, end_dot, width, glow}]   None = the preset's lines, [] = none }
SLOTS[preset]['portrait'|'landscape'] = {slot: (x, y, w, h)}  px at short side 1080 (canvas short side is always 1080); CONNECTORS[preset][aspect] = [line, ...]
with points = [x, y] px | 'slot' | 'slot-top|bottom|left|right' (the visible ink of the widget in that slot). A line is drawn only when every
slot it names holds a widget. Engine: widget fn(spec, box, ctx) -> sprite -> ONE Item per widget (staggered), connectors after the last widget, all fade
out together. Ink stays >= 48 px from the canvas edges (the sprite is moved inward when a widget draws outside the safe area; no frame avoidance yet).
Public: SLOTS, CONNECTORS, T4_SCENE, t4_scenes_cfg(raw) -> [scene], t4_scenes_items(cfg, duration), t4_ask_scenes(); registry: scenes_reg."""
import copy
import math

from mt.anim import ANIMS
from mt.ask import ask_anim
from mt.common import ask_choice, yn
from mt.draw import Item
from mt.templates.t4 import scenes_title  # noqa: F401  (registers the 'title_block' widget)
from mt.templates.t4 import scenes_widgets  # noqa: F401  (registers the 'code_window' widget)\
from mt.templates.t4 import scenes_ring
from mt.templates.t4 import scenes_bullets  # noqa: F401  (registers the 'bullet_list' widget)
from mt.templates.t4 import scenes_card  # noqa: F401  (registers the 'info_card' widget)
from mt.templates.t4 import scenes_charts  # noqa: F401  (registers 'bar_chart', 'progress_list', 'badge')
from mt.templates.t4.scenes_widgets import t4_widget_line_items
from mt.templates.t4.kit import connector
from mt.templates.t4.nameplate import T4_SAFE, _bool, _flt, _ink_box, _window
from mt.templates.t4.scenes_reg import WIDGET_ASK, WIDGET_SLOT, WIDGETS, get_widget
from mt.templates.t4.tiles import _make_item
from mt.templates.t4.timing import t4_ask_when, t4_stagger
from mt.templates.t4.warn import t4_warn

DEFAULT_PRESET = "web_dev"
PRESET_LABEL = {"web_dev": "Web development HUD (R5 / R6)"}
SLOTS = {"web_dev": {"portrait": {"title": (48, 60, 984, 220),        # R5: content centred on y 170; text area = 984 - 175 - 32
                                  "code": (48, 295, 434, 242),
                                  "ring": (637, 296, 240, 240),                                  
                                  "bullets": (48, 640, 984, 440),
                                  "chart": (64, 1310, 952, 300),
                                  "progress": (64, 1630, 952, 220),
                                  "badge": (684, 556, 316, 64),                                  
                                  "card": (48, 1100, 984, 190)},

                     "landscape": {"title": (48, 126, 780, 116),       # R6: content centred on y 184 (P15-P17 add their slots here)
                                   "code": (52, 316, 543, 289),
                                   "ring": (700, 300, 320, 320),
                                   "bullets": (1080, 270, 780, 420),
                                   "chart": (52, 640, 560, 392),
                                   "progress": (672, 650, 380, 380),
                                   "badge": (860, 150, 340, 64),
                                   "card": (1080, 720, 780, 170)}}}

CONNECTORS = {"web_dev": {"portrait": [], "landscape": []}}
# ---- preset 'tech_overview': speaker stays visible in the CENTRE (no widget over the face area) ----------------------------
SLOTS["tech_overview"] = {
    "portrait": {"title": (48, 60, 984, 200), "code": (48, 290, 434, 242), "ring": (690, 290, 240, 240),
                 "badge": (684, 1306, 348, 56),
                 "bullets": (48, 1380, 470, 230), "chart": (560, 1380, 472, 230),
                 "progress": (48, 1630, 520, 230), "card": (590, 1640, 442, 170)},
    "landscape": {"title": (48, 60, 590, 116), "code": (52, 210, 543, 289), "progress": (52, 540, 560, 300), "badge": (52, 880, 340, 64),
                  "ring": (1300, 60, 280, 280), "bullets": (1300, 375, 572, 200), "chart": (1300, 600, 572, 230),
                  "card": (1300, 860, 572, 160)}}
CONNECTORS["tech_overview"] = {
    "portrait": [{"points": ["code-right", "ring-left"]}, {"points": ["bullets-right", "chart-left"]},
                 {"points": ["bullets-bottom", "progress-top"]}, {"points": ["chart-bottom", "card-top"]}],
    "landscape": [{"points": ["code-bottom", "progress-top"]}, {"points": ["progress-bottom", "badge-top"]},
                  {"points": ["ring-bottom", "bullets-top"]}, {"points": ["bullets-bottom", "chart-top"]},
                  {"points": ["chart-bottom", "card-top"]}]}
PRESET_LABEL["tech_overview"] = "Tech overview HUD (speaker stays in the centre, R5 / R6)"
SAFE_ZONE = {"tech_overview": {"portrait": (200, 560, 880, 1280), "landscape": (660, 130, 1260, 1000)}}   # px at short side 1080: no widget ink / line here
DEFAULT_WIDGETS = {"tech_overview": [
    {"type": "title_block", "title": "Tech Overview", "subtitle": "Build. Ship. Scale."},
    {"type": "code_window", "file": "main.py"},
    {"type": "ring", "icon": "chip"},
    {"type": "badge", "text": "Python", "icon": "code"},
    {"type": "bullet_list", "items": ["Frontend & Backend", "Cloud & DevOps", "AI & Automation"]},
    {"type": "bar_chart", "values": [30, 55, 45, 80, 95], "labels": ["Jan", "Feb", "Mar", "Apr", "May"]},
    {"type": "progress_list", "rows": ["code|Python|90", "database|SQL|75", "globe|Web|60"]},
    {"type": "info_card", "icon": "cloud", "title": "Cloud Ready", "subtitle": "Build \u2022 Test \u2022 Deploy"}]}
T4_SCENE = {"on": True, "preset": DEFAULT_PRESET, "widgets": [], "start": 0.0, "trigger": "", "end": None, "hold": None, "anim": "fade",
            "anim_dur": 0.45, "stagger": 0.2, "connectors": None}
_LINE = {"points": [], "color": "#19d3ff", "end_dot": True, "width": 2.5, "glow": 9.0}
_SIDES = ("top", "bottom", "left", "right", "center")


# ---- config -----------------------------------------------------------------------------------------------------------------
def _box(v):
    try:
        b = [float(x) for x in v]
        return b if len(b) == 4 and all(math.isfinite(x) for x in b) and b[2] > 0 and b[3] > 0 else None
    except (TypeError, ValueError):
        return None


def _widget(raw):
    """Clean widget entry (extras kept) or None."""
    if not isinstance(raw, dict):
        return None
    t = raw.get("type")
    t = t.strip().lower() if isinstance(t, str) else ""
    if not t:
        return None
    out = copy.deepcopy(raw)
    sl = raw.get("slot")
    out.update({"type": t, "slot": sl.strip().lower() if isinstance(sl, str) else "", "box": _box(raw.get("box")), "on": _bool(raw.get("on"), True)})
    return out


def _pt(p):
    """[x, y] numbers | 'slot' token -> kept; else None."""
    if isinstance(p, str):
        return p.strip().lower() or None
    try:
        x, y = float(p[0]), float(p[1])
        return [x, y] if len(p) == 2 and math.isfinite(x) and math.isfinite(y) else None
    except (TypeError, ValueError, IndexError):
        return None


def _lines(raw):
    """None -> None (= use the preset's); list -> clean lines (>= 2 points each); anything else -> None."""
    if not isinstance(raw, (list, tuple)):
        return None
    out = []
    for r in raw:
        if not isinstance(r, dict) or not isinstance(r.get("points"), (list, tuple)):
            continue
        ln = copy.deepcopy(_LINE)
        ln["points"] = [p for p in (_pt(q) for q in r["points"]) if p is not None][:12]
        c = r.get("color")
        ln["color"] = c if isinstance(c, str) and c.strip() else ln["color"]
        ed = r.get("end_dot")
        ln["end_dot"] = ed if ed in (True, False, "both", "start") else True
        ln["width"], ln["glow"] = _flt(r.get("width"), 0.5, 30, 2.5), _flt(r.get("glow"), 0, 60, 9.0)
        if len(ln["points"]) >= 2:
            out.append(ln)
    return out


def _scene(raw):
    out = copy.deepcopy(T4_SCENE)
    out.update({k: copy.deepcopy(v) for k, v in raw.items() if k not in out})                     # extras survive
    p = raw.get("preset")
    out["preset"] = p.strip().lower() if isinstance(p, str) and p.strip() else DEFAULT_PRESET
    ws = raw.get("widgets")
    ws = [ws] if isinstance(ws, dict) else ws if isinstance(ws, (list, tuple)) else []
    out["widgets"] = [w for w in (_widget(x) for x in ws) if w is not None]
    if "widgets" not in raw and out["preset"] in DEFAULT_WIDGETS:         # a scene that only names the preset = the ready default scene
        out["widgets"] = [w for w in (_widget(x) for x in copy.deepcopy(DEFAULT_WIDGETS[out["preset"]])) if w is not None]
    trig = raw.get("trigger")
    out["trigger"] = trig.strip() if isinstance(trig, str) else ""
    out["start"] = raw["start"] if raw.get("start") is not None else (None if out["trigger"] else 0.0)
    out["end"], out["hold"] = raw.get("end"), raw.get("hold")
    a = raw.get("anim")
    a = ("reveal" if a.strip().lower() == "typewriter" else a.strip().lower()) if isinstance(a, str) else "fade"
    out["anim"] = a if a in ANIMS or a in ("pop", "none") else "fade"
    out["anim_dur"], out["stagger"] = _flt(raw.get("anim_dur"), 0.0, 5.0, 0.45), _flt(raw.get("stagger"), 0.0, 3.0, 0.2)
    out["connectors"] = _lines(raw.get("connectors"))
    out["on"] = _bool(raw.get("on"), True)
    return out


def t4_scenes_cfg(raw):
    """Normalise cfg['t4']['scenes'] -> list of complete scenes. Accepts a list, one scene dict (has 'widgets') or {on, scenes: [...]}
    (the module default {'on': False} = no scenes). Never raises; junk entries are dropped."""
    try:
        if isinstance(raw, dict) and "widgets" in raw:
            raw = [raw]
        elif isinstance(raw, dict):
            raw = raw.get("scenes") if _bool(raw.get("on"), False) else []
        return [_scene(x) for x in raw if isinstance(x, dict)] if isinstance(raw, (list, tuple)) else []
    except Exception:
        return []


# ---- placement ---------------------------------------------------------------------------------------------------------------
def _aspect(W, H):
    return "portrait" if H > W else "landscape"


def _shift(a, b, lo, hi):
    """Move needed so [a, b] lies inside [lo, hi] (0 when it does, or when it is larger than the room)."""
    if b - a > hi - lo:
        return 0
    return int(math.ceil(lo - a)) if a < lo else int(math.floor(hi - b)) if b > hi else 0


def _put(sprite, box, W, H, s):
    """Sprite whose origin (info['origin']) = the box's top-left -> (cx, cy of the Item, ink rect on the canvas, moved px) | None (empty sprite)."""
    ink = sprite.info.get("ink") or _ink_box(sprite)    
    if ink is None:
        return None
    ox, oy = sprite.info.get("origin", (0, 0))
    x0, y0, m = int(round(box[0])) - ox, int(round(box[1])) - oy, T4_SAFE * s
    dx = _shift(x0 + ink[0], x0 + ink[2], m, W - m)
    dy = _shift(y0 + ink[1], y0 + ink[3], m, H - m)
    x0, y0 = x0 + dx, y0 + dy
    return x0 + sprite.width / 2.0, y0 + sprite.height / 2.0, (x0 + ink[0], y0 + ink[1], x0 + ink[2], y0 + ink[3]), abs(dx) + abs(dy)


def _warn_overlaps(placed):
    for i, (a, ra) in enumerate(placed):
        for b, rb in placed[i + 1:]:
            if ra[0] < rb[2] and rb[0] < ra[2] and ra[1] < rb[3] and rb[1] < ra[3]:
                t4_warn("%s and %s overlap - give one of them another slot / box." % (a, b))


def _widget_items(cfg, scene, label, win, ctx, slots, rects, placed):
    """One staggered Item per widget; fills rects[slot or 'wN'] with the placed ink rect. -> (items, start of the last item)."""
    W, H, s = ctx["W"], ctx["H"], ctx["s"]
    ready = []
    for i, w in enumerate(scene["widgets"]):
        if not w["on"]:
            continue
        fn, slot = get_widget(w["type"]), (w["slot"] or WIDGET_SLOT.get(w["type"], ""))
        if fn is None:
            t4_warn("%s: unknown widget type '%s' - skipped (known: %s)." % (label, w["type"], ", ".join(sorted(WIDGETS)) or "none"))
            continue
        box = w["box"] or slots.get(slot)
        if box is None:
            t4_warn("%s: widget '%s' has no slot '%s' in preset '%s' (%s) and no box - skipped." % (label, w["type"], slot, ctx["preset"], ctx["aspect"]))
            continue
        box = tuple(float(v) * s for v in box)
        try:
            sp = fn(dict(w), box, ctx)
            pl = _put(sp, box, W, H, s) if sp is not None else None
        except Exception as e:
            t4_warn("%s: widget '%s' could not be drawn (%s: %s) - skipped." % (label, w["type"], type(e).__name__, e))
            continue
        if pl is None:
            continue
        key = slot if slot and slot not in rects else "w%d" % (i + 1)
        rects[key] = pl[2]
        placed.append(("%s widget '%s'" % (label, key), pl[2]))
        ready.append((sp, pl))
    steps, last = t4_stagger(len(ready), scene["stagger"]), max(win[0], win[1] - 0.1)
    items = [_make_item(sp, min(win[0] + d, last), win[1], pl[0], pl[1], scene) for (sp, pl), d in zip(ready, steps) if not sp.info.get("lines_only")]    
    for (sp, pl), d in zip(ready, steps):                                   # typewriter widgets: one 'reveal' Item per code line
        items += t4_widget_line_items(sp, pl[0], pl[1], min(win[0] + d, last), win[1], 0.0 if sp.info.get("lines_only") else scene["anim_dur"])
    return items, (min(win[0] + steps[-1], last) if steps else win[0])


# ---- connectors --------------------------------------------------------------------------------------------------------------
def _resolve(p, rects, s):
    """[x, y] px | 'slot' | 'slot-side' -> canvas point, or None when that slot has no widget."""
    if not isinstance(p, str):
        return float(p[0]) * s, float(p[1]) * s
    name, side = p, "center"
    head, _, tail = p.rpartition("-")
    if head and tail in _SIDES:
        name, side = head, tail
    r = rects.get(name)
    if r is None:
        return None
    cx, cy = (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0
    return {"left": (r[0], cy), "right": (r[2], cy), "top": (cx, r[1]), "bottom": (cx, r[3])}.get(side, (cx, cy))


def _connector_items(scene, ctx, rects, t0, end):
    lines = scene["connectors"] if scene["connectors"] is not None else _lines(CONNECTORS.get(ctx["preset"], {}).get(ctx["aspect"], [])) or []
    W, H, s, out = ctx["W"], ctx["H"], ctx["s"], []
    for ln in lines:
        pts = [_resolve(p, rects, s) for p in ln["points"]]
        if any(p is None for p in pts):
            continue                                                       # a slot it needs holds no widget: no line
        m = (T4_SAFE + ln["glow"] * 1.6 + 2) * s
        pts = [(min(max(x, m), W - m), min(max(y, m), H - m)) for x, y in pts]
        sp = connector(pts, ln["color"], ln["end_dot"], ln["width"] * s, ln["glow"] * s)
        ox, oy = sp.info["origin"]
        out.append(Item(sp, min(t0 + scene["anim_dur"], max(t0, end - 0.1)), end, -ox + sp.width / 2.0, -oy + sp.height / 2.0, "fade", scene["anim_dur"], out=True))
    return out


def t4_scenes_items(cfg, duration):
    """Items of every scene: one per widget (staggered), then the preset's connectors; all fade out together. Never raises."""
    t4 = cfg.get("t4") if isinstance(cfg, dict) and isinstance(cfg.get("t4"), dict) else {}
    scenes = [sc for sc in t4_scenes_cfg(t4.get("scenes")) if sc["on"]]
    if not scenes:
        return []
    try:
        W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        t4_warn("t4 scenes: the job has no canvas - skipped.")
        return []
    items, placed = [], []
    for i, sc in enumerate(scenes):
        label = "scene %d" % (i + 1)
        try:
            items += _one_scene(cfg, sc, label, duration, W, H, placed)
        except Exception as e:
            t4_warn("t4 %s: could not be drawn (%s: %s) - skipped." % (label, type(e).__name__, e))
    _warn_overlaps(placed)
    return items


def _one_scene(cfg, sc, label, duration, W, H, placed):
    if not sc["widgets"]:
        t4_warn("%s: no widgets - skipped." % label)
        return []
    win = _window(cfg, sc, label, duration, 6.0)
    if win is None:
        return []
    preset = sc["preset"]
    if preset not in SLOTS:
        t4_warn("%s: unknown preset '%s' - using '%s' (known: %s)." % (label, preset, DEFAULT_PRESET, ", ".join(sorted(SLOTS))))
        preset = DEFAULT_PRESET
    ctx = {"W": W, "H": H, "s": min(W, H) / 1080.0, "aspect": _aspect(W, H), "preset": preset, "cfg": cfg}
    rects = {}
    items, t_last = _widget_items(cfg, sc, label, win, ctx, SLOTS[preset][ctx["aspect"]], rects, placed)
    return items + (_connector_items(sc, ctx, rects, t_last, win[1]) if items else [])


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_ask_scenes():
    """Question group 'scenes' (called by t4_ask_config). -> a list with ONE scene, or {'on': False}. More scenes: edit the job file."""
    if not yn("Add an infographic scene (title block + more widgets in later tasks - reference R5 / R6)?", default=False):
        return {"on": False}
    names = sorted(SLOTS)                     # 'tech_overview' sorts first = the Enter default; put web_dev first by hand if you prefer
    p = ask_choice("Scene layout", [PRESET_LABEL.get(n, n) for n in names], default=1, key="t4_scene_preset")
    preset, widgets = names[p - 1], []
    if preset in DEFAULT_WIDGETS and yn("Use the ready default scene (all widgets, placeholder texts)?", default=True):
        widgets = copy.deepcopy(DEFAULT_WIDGETS[preset])
    else:
        for name in WIDGETS:
            if name in WIDGET_ASK and yn("Add the '%s' widget?" % name, default=True):
                widgets.append(dict(WIDGET_ASK[name](), type=name, slot=WIDGET_SLOT.get(name, "")))
    sc = {"preset": preset, "widgets": widgets}
    sc.update(t4_ask_when("Scene", 6.0, key="t4_scene_when"))
    sc["anim"] = ask_anim("Scene animation (widgets appear one after another)", default="fade", key="t4_scene_anim")
    return [sc]