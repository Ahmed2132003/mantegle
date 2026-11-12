"""T4-14 check (scenes engine + title_block): python tools/mt_t4_p14_check.py     (MT_PROJECT = project root, default = parent of tools/)
Part A (pure Python): normaliser, registry / warnings, slots on BOTH canvases, title-block geometry vs the R5 / R6 measurements,
  stagger / timing / connectors, Arabic, cache, questions. Writes out/t4/p14_title_{reels,youtube}[_ar].png (sprite on a dark test backdrop).
Part B (needs montage.py + t4_scenes_items wired into t4_build_items): real --still on both canvases, the title block must change the pixels."""
import contextlib, io, json, os, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
rows = []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): r = fn(*a)
    return r, [l for l in buf.getvalue().splitlines() if "[!]" in l]
import mt.common as _c                                                           # noqa: E402,F401
from mt.templates.t4.warn import t4_warn_reset                                   # noqa: E402
from mt.templates.t4.scenes import SLOTS, T4_SCENE, t4_ask_scenes, t4_scenes_cfg, t4_scenes_items   # noqa: E402
from mt.templates.t4.scenes_reg import WIDGETS, register_widget, get_widget       # noqa: E402
import mt.templates.t4.scenes as SC                                              # noqa: E402
OUT = P / "out" / "t4"; OUT.mkdir(parents=True, exist_ok=True)
CV = {"reels": (1080, 1920), "youtube": (1920, 1080)}
SAFE = 48
def cfg_for(cv, scenes):
    return {"canvas": list(CV[cv]), "t4": {"scenes": scenes}}
def title_scene(**w):
    return [{"preset": "web_dev", "widgets": [dict({"type": "title_block"}, **w)], "start": 0, "hold": 5}]
def paste_item(it, W, H, bg=(14, 18, 30)):
    """Composite an Item's sprite onto a dark test backdrop (no animation) -> (RGBA canvas, alpha-only full-canvas array)."""
    img = Image.new("RGBA", (W, H), bg + (255,)); full = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x, y = int(it.cx - it.sprite.width / 2), int(it.cy - it.sprite.height / 2)
    for t in (img, full): t.alpha_composite(it.sprite, (x, y)) if x >= 0 and y >= 0 else t.paste(it.sprite, (x, y), it.sprite)
    return img, np.asarray(full)
def runs(mask):
    """[(first, last)] of consecutive True entries."""
    out, st = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and st is None: st = i
        if not v and st is not None: out.append((st, i - 1)); st = None
    return out
# ---- normaliser --------------------------------------------------------------------------------------------------------------
a = t4_scenes_cfg([{"preset": " WEB_DEV ", "widgets": [{"type": "Title_Block", "slot": "Title", "box": [1, 2, 3, 4]}, "junk", {"slot": "x"}, {"type": "x", "box": [1, 2, 0, 4]}],
                    "hold": 3, "anim": "bogus", "stagger": 99, "connectors": [{"points": ["a", [1, 2], "bad?", None]}, {"points": [[1, 2]]}], "extra": 7}, "junk", 5])
b, c, d = t4_scenes_cfg({"on": False}), t4_scenes_cfg({"widgets": [{"type": "title_block"}]}), t4_scenes_cfg({"on": True, "scenes": [{"widgets": {"type": "title_block"}}]})
g = a[0]
rec("T4-14 t4_scenes_cfg: list / one scene / {on, scenes}; junk dropped; preset / type / slot lower-cased; bad box -> None; anim / stagger fall back; connectors cleaned; extras kept",
    len(a) == 1 and g["preset"] == "web_dev" and [w["type"] for w in g["widgets"]] == ["title_block", "x"] and g["widgets"][0]["slot"] == "title" and g["widgets"][0]["box"] == [1, 2, 3, 4]
    and g["widgets"][1]["box"] is None and g["anim"] == "fade" and g["stagger"] == 0.2 and len(g["connectors"]) == 1 and g["connectors"][0]["points"] == ["a", [1.0, 2.0], "bad?"]
    and g["extra"] == 7 and b == [] and len(c) == 1 and len(d) == 1 and t4_scenes_cfg(None) == [] and t4_scenes_cfg("x") == [] and T4_SCENE["connectors"] is None, f"{g['connectors']}")
rec("T4-14 slots: web_dev has a 'title' slot for portrait and landscape (the addendum values)", SLOTS["web_dev"]["portrait"]["title"] == (48, 60, 984, 220) and SLOTS["web_dev"]["landscape"]["title"] == (48, 126, 780, 116))
rec("T4-14 registry: title_block registered; register_widget refuses junk", get_widget("TITLE_BLOCK") is not None and register_widget("", print) is False and register_widget("x", 5) is False and get_widget(5) is None)
# ---- title block geometry on both canvases -----------------------------------------------------------------------------------
REF = {"reels": {"cap": 62, "sub_cap": 29, "title_x": 277, "ink_cy": 170}, "youtube": {"cap": 53, "sub_cap": 27, "title_x": 201, "ink_cy": 184}}
for cv, (W, H) in CV.items():
    t4_warn_reset(); items, w = quiet(t4_scenes_items, cfg_for(cv, title_scene()), 10.0)
    ok = len(items) == 1 and not w
    if not ok: rec(f"T4-14 title_block {cv}: one item, no warning", False, f"{len(items)} items {w}"); continue
    it = items[0]; img, arr = paste_item(it, W, H); img.convert("RGB").save(OUT / f"p14_title_{cv}.png")
    al = arr[..., 3] > 24; ys, xs = np.where(al); x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    rec(f"T4-14 title_block {cv}: ink >= {SAFE} px from every edge, slot-sized (<= slot + glow)", x0 >= SAFE and y0 >= SAFE and x1 <= W - SAFE and y1 <= H - SAFE, f"ink {x0},{y0}..{x1},{y1}")
    rgb = arr[..., :3].astype(int); a_ = arr[..., 3]
    white = (a_ > 200) & (rgb.min(axis=2) > 235)
    cyan = (a_ > 200) & (rgb[..., 0] < 140) & (rgb[..., 1] > 200) & (rgb[..., 2] > 200)
    cr = runs((white | cyan).any(axis=0))                                   # column runs: [icon block, ..., text]; the text starts after the 32 px gap
    tx = next((b[0] for a, b in zip(cr, cr[1:]) if b[0] - a[1] >= 20), 0) - 2
    txt_rows = runs((white | cyan)[:, tx:].any(axis=1))
    txt_rows = [r for r in txt_rows if r[1] - r[0] >= 8]
    if len(txt_rows) < 2: rec(f"T4-14 title_block {cv}: title + subtitle rows found", False, f"rows {txt_rows}"); continue
    (t0, t1), (s0, s1) = txt_rows[0], txt_rows[1]
    tc, sc_ = np.where((white | cyan)[t0:t1 + 1, tx:].any(axis=0))[0], np.where((white | cyan)[s0:s1 + 1, tx:].any(axis=0))[0]
    tw, sw = tc.max() - tc.min() + 1, sc_.max() - sc_.min() + 1
    wx, cx_ = np.where(white[t0:t1 + 1, tx:].any(axis=0))[0], np.where(cyan[t0:t1 + 1, tx:].any(axis=0))[0]
    gap = s0 - t1
    cap_t = t1 - t0 + 1
    rec(f"T4-14 title_block {cv}: title = ONE row, white words left of the cyan word; subtitle white, same left edge (+-8), width = 0.95 x title (+-0.04), gap title -> subtitle ~ 20 px",
        wx.max() < cx_.min() and not cyan[s0:s1 + 1, tx:].any() and abs(tc.min() - sc_.min()) <= 8 and abs(sw / tw - 0.95) <= 0.04 and 14 <= gap <= 26,
        f"title x {tx + tc.min()}..{tx + tc.max()} ({tw}px, ref {662 if cv == 'reels' else 557}) sub {sw}px ratio {sw / tw:.3f} gap {gap}")
    sc_cap = s1 - s0 + 1
    rec(f"T4-14 title_block {cv}: subtitle cap = 0.465 x title cap (+-0.06), row centred on the slot centre y {REF[cv]['ink_cy']} (+-14), title no wider than the slot",
        abs(sc_cap / cap_t - 0.465) <= 0.06 and abs((y0 + y1) / 2 - REF[cv]["ink_cy"]) <= 14 and x1 <= SLOTS["web_dev"]["portrait" if H > W else "landscape"]["title"][0] + SLOTS["web_dev"]["portrait" if H > W else "landscape"]["title"][2] + 8,
        f"cap {cap_t} (ref {REF[cv]['cap']}; smaller = the default font is wider than the ref face and the title shrank to fit) sub cap {sc_cap} ink centre {(y0 + y1) / 2:.0f}; title x starts {tx + tc.min()} (ref {REF[cv]['title_x']})")
    it2 = t4_scenes_items(cfg_for(cv, title_scene(title="Web Dev", subtitle="")), 10.0)[0]; _, arr2 = paste_item(it2, W, H)
    rg2 = arr2[..., :3].astype(int); m2 = ((arr2[..., 3] > 200) & ((rg2.min(axis=2) > 235) | ((rg2[..., 0] < 140) & (rg2[..., 1] > 200) & (rg2[..., 2] > 200))))[:, tx:]
    cap2 = max(r[1] - r[0] + 1 for r in runs(m2.any(axis=1)))
    rec(f"T4-14 title_block {cv}: a title that fits keeps the font size from the slot height - cap height ~ ref {REF[cv]['cap']} (+-6; DejaVu caps are 0.73 em, the ref face ~0.72)", abs(cap2 - REF[cv]["cap"]) <= 6, f"cap {cap2}")
# ---- accent / options ---------------------------------------------------------------------------------------------------------
def cyan_cols(spec, cv="youtube"):
    W, H = CV[cv]; it = t4_scenes_items(cfg_for(cv, title_scene(**spec)), 10.0)[0]; _, arr = paste_item(it, W, H)
    rgb = arr[..., :3].astype(int); m = (arr[..., 3] > 200) & (rgb[..., 0] < 140) & (rgb[..., 1] > 200) & (rgb[..., 2] > 200)
    return np.where(m[:, 260:].any(axis=0))[0]
t4_warn_reset(); one, w1 = quiet(cyan_cols, {"title": "Web Development Course", "accent": "Development Course", "subtitle": ""})
last, _ = quiet(cyan_cols, {"title": "Web Development Course", "subtitle": ""}); single, _ = quiet(cyan_cols, {"title": "Hello", "subtitle": ""})
bad, w2 = quiet(cyan_cols, {"title": "Web Development", "accent": "Nope", "subtitle": ""}); dflt, _ = quiet(cyan_cols, {"title": "Web Development", "subtitle": ""})
rec("T4-14 accent: explicit words, default = last word, one-word title = all cyan, unknown accent -> last word + 1 warning", one.min() < last.min() and len(single) > 100 and bad.min() == dflt.min() and len(w2) == 1 and not w1,
    f"{one.min()} < {last.min()}, single {len(single)} cols, warn {w2}")
t4_warn_reset(); r, w = quiet(lambda: [t4_scenes_items(cfg_for("reels", title_scene(**s)), 10.0) for s in ({"badge": False}, {"badge": True}, {"panel": True}, {"icon": "none"}, {"icon": "nope"}, {"font": "/no/f.ttf"},
                  {"title": "", "subtitle": ""}, {"title": "W" * 80}, {"color": "zzz", "size": "x", "tracking": "bad", "badge": "maybe", "caps": 3}, {"title": 5, "subtitle": None})])
rec("T4-14 title_block options never raise (badge / panel / no icon / bad icon / bad font / empty / 80-char title / junk values); each case still returns <= 1 item", all(len(x) <= 1 for x in r) and sum(len(x) for x in r) >= 8, f"{[len(x) for x in r]} {w[:3]}")
t4_warn_reset(); sm, _ = quiet(lambda: t4_scenes_items(cfg_for("youtube", title_scene(title="W" * 80, subtitle="S" * 120)), 10.0)[0])
al = np.asarray(sm.sprite.getchannel("A")) > 24; ys, xs = np.where(al)
rec("T4-14 an over-long title / subtitle shrinks / is cut and stays inside the slot width (no ink past x = 48 + 780 + 8)", (sm.cx - sm.sprite.width / 2 + xs.max()) <= 48 + 780 + 8, f"max x {sm.cx - sm.sprite.width / 2 + xs.max():.0f}")
# ---- Arabic -------------------------------------------------------------------------------------------------------------------
for cv, (W, H) in CV.items():
    t4_warn_reset(); items, w = quiet(t4_scenes_items, cfg_for(cv, title_scene(title="تطوير الويب", subtitle="بناء حلول رقمية")), 10.0)
    if len(items) != 1: rec(f"T4-14 title_block Arabic {cv}", False, f"{len(items)} items {w}"); continue
    img, arr = paste_item(items[0], W, H); img.convert("RGB").save(OUT / f"p14_title_{cv}_ar.png")
    ys, xs = np.where(arr[..., 3] > 24); sl = SLOTS["web_dev"]["portrait" if H > W else "landscape"]["title"]
    rec(f"T4-14 title_block Arabic {cv}: row mirrored (ink reaches the slot's right side, starts well inside its left side), inside the safe area", xs.max() >= sl[0] + sl[2] - 60 and xs.min() >= SAFE and xs.max() <= W - SAFE, f"ink x {xs.min()}..{xs.max()} slot {sl[0]}..{sl[0] + sl[2]}")
# ---- engine: warnings, timing, stagger, connectors ------------------------------------------------------------------------------
def probe_w(spec, box, ctx=None):
    from PIL import Image as _I
    w, h = int(box[-2]), int(box[-1])
    im = _I.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0)); ImageDraw.Draw(im).rectangle((20, 20, 20 + w - 1, 20 + h - 1), fill=(255, 255, 255, 255)); im.info["origin"] = (20, 20); return im
register_widget("t4_probe", probe_w, slot="probe")
SLOTS["t4_test"] = {"portrait": {"title": (48, 60, 984, 220), "probe": (100, 600, 300, 200)}, "landscape": {"title": (48, 126, 780, 116), "probe": (1200, 400, 300, 200)}}
SC.CONNECTORS["t4_test"] = {"portrait": [{"points": ["title-bottom", "probe-top"]}, {"points": ["title", "ghost"]}], "landscape": [{"points": ["title-bottom", "probe-left"]}]}
try:
    sc = [{"preset": "t4_test", "start": 1.0, "hold": 4, "stagger": 0.3, "widgets": [{"type": "title_block"}, {"type": "t4_probe"}, {"type": "nope"}, {"type": "t4_probe", "slot": "missing"}]}]
    for cv in CV:
        t4_warn_reset(); items, w = quiet(t4_scenes_items, cfg_for(cv, sc), 10.0)
        st = [round(i.start, 2) for i in items]; en = {round(i.end, 2) for i in items}
        rec(f"T4-14 engine {cv}: 2 widgets (staggered 0.3 s) + 1 connector (the one naming a slot without a widget is dropped); all end together; unknown type + unknown slot = 1 warning each",
            len(items) == 3 and st[:2] == [1.0, 1.3] and st[2] >= 1.3 and en == {5.0} and len(w) == 2 and any("'nope'" in x for x in w) and any("missing" in x for x in w), f"starts {st} ends {en} warns {w}")
    t4_warn_reset(); i2, w2 = quiet(t4_scenes_items, cfg_for("reels", [dict(sc[0], connectors=[])]), 10.0)
    t4_warn_reset(); i3, _ = quiet(t4_scenes_items, cfg_for("reels", [dict(sc[0], connectors=[{"points": [[100, 100], [400, 300]]}])]), 10.0)
    t4_warn_reset(); i4, w4 = quiet(t4_scenes_items, cfg_for("reels", [dict(sc[0], preset="nope")]), 10.0)
    t4_warn_reset(); i5, w5 = quiet(t4_scenes_items, cfg_for("reels", [dict(sc[0], start=99)]), 10.0)
    t4_warn_reset(); i6, w6 = quiet(t4_scenes_items, {"t4": {"scenes": sc}}, 10.0)
    t4_warn_reset(); i7, w7 = quiet(t4_scenes_items, cfg_for("reels", [{"widgets": []}]), 10.0)
    rec("T4-14 engine: connectors [] = none, own connectors replace the preset's, unknown preset = warning + web_dev, start past the end / no canvas / no widgets = skipped with a warning, never raises",
        len(i2) == 2 and len(i3) == 3 and any("unknown preset" in x for x in w4) and not i5 and not i6 and any("no canvas" in x for x in w6) and not i7 and any("no widgets" in x for x in w7), f"{len(i2)} {len(i3)} {w4} {len(i5)} {w6}")
    # a widget that draws outside the safe area is moved in; a widget that raises is skipped
    register_widget("t4_far", lambda s, b, c: probe_w(s, (0, 0, 200, 100)), slot="probe"); register_widget("t4_boom", lambda s, b, c: 1 / 0, slot="probe")
    t4_warn_reset(); it, w = quiet(t4_scenes_items, cfg_for("reels", [{"preset": "t4_test", "widgets": [{"type": "t4_far", "box": [0, 0, 200, 100]}, {"type": "t4_boom"}]}]), 10.0)
    ys, xs = np.where(paste_item(it[0], 1080, 1920)[1][..., 3] > 24)
    rec("T4-14 engine: a widget drawn at the canvas edge is moved to the 48 px margin; a widget that raises = 1 warning, the rest of the scene is kept", len(it) == 1 and xs.min() >= SAFE and ys.min() >= SAFE and len(w) == 1 and "t4_boom" in w[0], f"ink {xs.min()},{ys.min()} {w}")
finally:
    SLOTS.pop("t4_test", None); SC.CONNECTORS.pop("t4_test", None)
    for n in ("t4_probe", "t4_far", "t4_boom"): WIDGETS.pop(n, None)
# ---- cache + questions --------------------------------------------------------------------------------------------------------
from mt.templates.t4.scenes_title import t4_title_block                                  # noqa: E402
a1, a2 = t4_title_block({}, (48, 60, 984, 220), {"s": 1.0, "aspect": "portrait"}), t4_title_block({}, (48, 60, 984, 220), {"s": 1.0, "aspect": "portrait"})
rec("T4-14 title sprite is cached (same object for the same spec + size) and carries info['origin']", a1 is a2 and a1.info.get("origin", (0, 0)) > (0, 0), f"origin {a1.info.get('origin')}")
import mt.templates.t4.scenes_title as ST                                                  # noqa: E402
def scripted(yes=True):
    """Replace the prompts used by t4_ask_scenes / the title_block questions with fixed answers (works on the real package, no stdin)."""
    keys = {"t4_scene_title": "My Title", "t4_scene_subtitle": "My Sub", "t4_scene_accent": "", "t4_scene_color": "#ff00aa"}
    fake_ask = lambda prompt, default=None, key=None, cast=None, allow_empty=False: keys.get(key, default if default is not None else "")
    old = (SC.yn, SC.ask_choice, SC.ask_anim, SC.t4_ask_when, ST.ask, ST.ask_choice, ST.yn, ST.c_color)
    SC.yn, SC.ask_choice, SC.ask_anim = (lambda *a, **k: yes), (lambda *a, **k: 1), (lambda *a, **k: "fade")
    SC.t4_ask_when = lambda *a, **k: {"start": 0, "hold": 2.5}
    ST.ask, ST.ask_choice, ST.yn = fake_ask, (lambda *a, **k: 2), (lambda *a, **k: yes)
    return old
def unscripted(old):
    SC.yn, SC.ask_choice, SC.ask_anim, SC.t4_ask_when, ST.ask, ST.ask_choice, ST.yn, ST.c_color = old
old = scripted(True)
try:
    q, _ = quiet(t4_ask_scenes)
finally:
    unscripted(old)
w0 = q[0]["widgets"][0] if isinstance(q, list) and q and q[0].get("widgets") else {}
t4_warn_reset(); built, _ = quiet(t4_scenes_items, cfg_for("youtube", q), 10.0) if isinstance(q, list) else ([], [])
old = scripted(False)
try:
    no, _ = quiet(t4_ask_scenes)
finally:
    unscripted(old)
rec("T4-14 t4_ask_scenes -> one scene with a title_block (answers kept) that builds; 'no' -> {'on': False}",
    w0.get("type") == "title_block" and w0.get("title") == "My Title" and w0.get("badge") is True and len(built) == 1 and no == {"on": False}, f"{q} / {no}")
# ---- Part B: the real still --------------------------------------------------------------------------------------------------
if (P / "montage.py").is_file():
    tmp = Path(tempfile.mkdtemp(prefix="t4p14_")); vid = tmp / "v.mp4"
    from mt.common import FFMPEG
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=3", "-pix_fmt", "yuv420p", str(vid)], check=True)
    for cv, (W, H) in CV.items():
        res, log = {}, ""
        for nm, scenes in (("off", {"on": False}), ("on", title_scene())):
            from mt.templates.t4.cfg import t4_cfg
            job = {"template_id": 5, "video": str(vid), "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"}, "background": {"type": "color", "value": "#000000"},
                   "t4": t4_cfg({"canvas_mode": cv, "scenes": scenes}), "layers": [], "captions": [], "cards": [], "texts": [], "elements": [], "video_layers": [], "output": str(tmp / "o.mp4"), "preview": 1.5}
            (tmp / f"{nm}.json").write_text(json.dumps(job), encoding="utf-8"); out = OUT / f"p14_still_{cv}_{nm}.png"
            r = subprocess.run([sys.executable, str(P / "montage.py"), "--still", "--job", str(tmp / f"{nm}.json"), "--still-out", str(out), "--arabic-mode", "raqm"], cwd=str(tmp), capture_output=True, text=True)
            res[nm] = np.asarray(Image.open(out).convert("RGB"), int) if r.returncode == 0 and out.is_file() else None
            if res[nm] is None: log = f"[{nm}: rc={r.returncode}] " + (r.stdout + r.stderr)[-400:].replace(chr(10), " | ")
        ok = res["on"] is not None and res["off"] is not None and (np.abs(res["on"] - res["off"]).max(axis=2) > 8).sum() > 3000
        rec(f"T4-14 real --still {cv}: the title block changes the pixels (needs t4_scenes_items in t4_build_items)", ok, "" if ok else (log or "the two stills are identical: scenes never reached the render - check wiring edits 1 (cfg.py list), 2 (__init__.py) and 3 (t4_ask_config) in T4_P14_WIRING.txt; t4_cfg({'scenes': [{'widgets': []}]})['scenes'] must stay a list"))
else:
    print("SKIP  T4-14 real --still (no montage.py under", P, ")")
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)