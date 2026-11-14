"""Check of the 'tech_overview' preset (refs R5 portrait / R6 landscape): python tools/mt_t4_overview_check.py   (run from the project root)
Both canvases x EN / AR: all 8 widgets placed, 48 px safe margin, no widget / connector inside the CENTRE SAFE ZONE (speaker stays visible),
no ink overlap, default scene (preset only), Enter-through question flow, real --still diff inside the zone. Stills -> out/t4/tech_overview_<canvas>.png"""
import builtins, contextlib, copy, io, itertools, os, shutil, subprocess, sys, tempfile
from pathlib import Path
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
import numpy as np
from PIL import Image
import mt.templates                                            # noqa: F401  (registers the templates)
from mt.common import D, FFMPEG
from mt.render import render_still
from mt.templates.t4 import scenes as S
from mt.templates.t4.cfg import t4_cfg
from mt.templates.t4.nameplate import T4_SAFE
from mt.templates.t4.warn import t4_warn_reset

CANV = {"reels": (1080, 1920), "youtube": (1920, 1080)}
PRESET = "tech_overview"
AR = {"title_block": {"title": "نظرة على التقنية", "subtitle": "ابنِ وانشر"},
      "bullet_list": {"items": ["واجهات وخوادم", "سحابة وتشغيل", "ذكاء اصطناعي"]},
      "progress_list": {"rows": ["code|بايثون|90", "database|قواعد البيانات|75", "globe|تصميم المواقع|60"]},
      "info_card": {"icon": "cloud", "title": "جاهز للسحابة", "subtitle": "ابنِ • اختبر • انشر"}, "badge": {"text": "بايثون", "icon": "code"}}
rows = []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a)
    return r, [l for l in buf.getvalue().splitlines() if "[!]" in l]
def inter(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
def seg_in(a, b, z):
    n = max(2, int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))))
    return any(z[0] < a[0] + (b[0] - a[0]) * i / n < z[2] and z[1] < a[1] + (b[1] - a[1]) * i / n < z[3] for i in range(n + 1))
def scene(lang):
    ws = copy.deepcopy(S.DEFAULT_WIDGETS[PRESET])
    for w in ws:
        if lang == "ar":
            w.update(AR.get(w["type"], {}))
    return {"preset": PRESET, "widgets": ws, "start": 0, "hold": 3, "stagger": 0.2}
def aspect(cv):
    W, H = CANV[cv]; return "portrait" if H > W else "landscape"

# ---- static: slots vs the safe zone -------------------------------------------------------------------------------------------
for asp in ("portrait", "landscape"):
    z, sl = S.SAFE_ZONE[PRESET][asp], S.SLOTS[PRESET][asp]
    bad = [k for k, b in sl.items() if inter((b[0], b[1], b[0] + b[2], b[1] + b[3]), z)]
    rec(f"{asp}: 8 slots, none touches the centre safe zone {z}", len(sl) == 8 and not bad, ",".join(bad))
types = {w["type"] for w in S.DEFAULT_WIDGETS[PRESET]}
rec("default spec holds all 8 widget types", len(types) == 8 and types <= set(S.WIDGETS), str(sorted(types)))
d = S.t4_scenes_cfg([{"preset": PRESET}])[0]
rec("a scene that only names the preset = the full default scene", {w["type"] for w in d["widgets"]} == types, str(len(d["widgets"])))

# ---- per canvas / language ----------------------------------------------------------------------------------------------------
for lang in ("en", "ar"):
    for cv, (W, H) in CANV.items():
        tag, asp, s = f"{cv}/{lang}", aspect(cv), min(W, H) / 1080.0
        z = S.SAFE_ZONE[PRESET][asp]
        sc = scene(lang)
        cfg = {"canvas": [W, H], "t4": t4_cfg({"canvas_mode": cv, "scenes": [sc]})}
        ctx = {"W": W, "H": H, "s": s, "aspect": asp, "preset": PRESET, "cfg": cfg}
        rects, placed = {}, []
        t4_warn_reset(); _, w = quiet(S._widget_items, cfg, S.t4_scenes_cfg([sc])[0], "chk", (0.0, 3.0), ctx, S.SLOTS[PRESET][asp], rects, placed)
        rec(f"{tag}: all 8 widgets placed, no warning", len(rects) == 8 and not w, f"{sorted(rects)} {w}")
        m = T4_SAFE * s - 1
        bad = [k for k, r in rects.items() if r[0] < m or r[1] < m or r[2] > W - m or r[3] > H - m]
        rec(f"{tag}: ink inside the 48 px safe margin", not bad, ",".join(bad))
        zone = tuple(v * s for v in z)
        inz = [k for k, r in rects.items() if inter(r, zone)]
        rec(f"{tag}: NO widget ink inside the centre safe zone (speaker stays visible)", not inz, ",".join(inz))
        ov = [(a, b) for i, (a, ra) in enumerate(placed) for b, rb in placed[i + 1:] if inter(ra, rb)]
        rec(f"{tag}: no ink overlap between widgets", not ov, str(ov))
        lines = S._lines(S.CONNECTORS[PRESET][asp]) or []
        drawn, cross = 0, []
        for ln in lines:
            pts = [S._resolve(p, rects, s) for p in ln["points"]]
            if any(p is None for p in pts):
                continue
            drawn += 1
            if any(seg_in(pts[i], pts[i + 1], zone) for i in range(len(pts) - 1)):
                cross.append(ln["points"])
        rec(f"{tag}: connectors drawn ({drawn} of {len(lines)}), none crosses the safe zone", drawn == len(lines) and not cross, str(cross))
        t4_warn_reset(); items, w = quiet(S.t4_scenes_items, cfg, 8.0)
        rec(f"{tag}: scene items built (widgets + connectors), no warning", len(items) >= 8 + len(lines) and not w, f"{len(items)} items {w}")

# ---- Enter-through question flow ---------------------------------------------------------------------------------------------------
D.clear()
it = itertools.chain(["y"], itertools.repeat(""))
old = builtins.input; builtins.input = lambda *_: next(it)
try:
    res, _w = quiet(S.t4_ask_scenes)
finally:
    builtins.input = old
D.clear()
ok = isinstance(res, list) and len(res) == 1 and res[0]["preset"] == PRESET and {w["type"] for w in res[0]["widgets"]} == types
rec("Enter-through (only 'y' to add the scene) -> full tech_overview scene with placeholder texts", ok, str(res)[:160])
if ok:
    its, w = quiet(S.t4_scenes_items, {"canvas": [1080, 1920], "t4": t4_cfg({"scenes": res})}, 8.0)
    rec("the Enter-through scene builds items", len(its) >= 12 and not w, f"{len(its)} {w}")

# ---- real --still: the zone is untouched ---------------------------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="t4ov_")); os.makedirs(P / "out" / "t4", exist_ok=True)
try:
    for cv, (W, H) in CANV.items():
        mp4 = tmp / f"v_{cv}.mp4"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=25:d=2", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        def job(scenes):
            return {"template_id": 5, "video": str(mp4), "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"},
                    "background": {"type": "color", "value": "#000000"}, "t4": t4_cfg({"canvas_mode": cv, "fit": "fill", "scenes": scenes}),
                    "layers": [], "captions": [], "cards": [], "texts": [], "elements": [], "video_layers": [], "output": str(tmp / "o.mp4")}
        on, off = P / "out" / "t4" / f"tech_overview_{cv}.png", tmp / f"off_{cv}.png"
        quiet(render_still, job([{"preset": PRESET, "start": 0, "hold": 5, "anim": "none"}]), str(on), 3.0)
        quiet(render_still, job([]), str(off), 3.0)
        if not (on.is_file() and off.is_file()):
            rec(f"{cv} --still", False, "still failed"); continue
        a, b = np.asarray(Image.open(on).convert("RGB"), int), np.asarray(Image.open(off).convert("RGB"), int)
        diff = np.abs(a - b).max(axis=2) > 12
        z = [int(v) for v in S.SAFE_ZONE[PRESET][aspect(cv)]]
        rec(f"{cv} --still: scene drawn, centre zone pixel-identical to the scene-less render (speaker visible)", diff.sum() > 20000 and not diff[z[1]:z[3], z[0]:z[2]].any(),
            f"changed px {diff.sum()}, in zone {int(diff[z[1]:z[3], z[0]:z[2]].sum())} -> {on}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)