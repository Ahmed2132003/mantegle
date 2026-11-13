"""Template 4 check of 'bar_chart' / 'progress_list' / 'badge' (P19): python tools/mt_t4_charts_check.py   (run from the project root)
Both canvases x EN / AR: items, 48 px safe margin, growth bands <= 9, junk specs, growth over time, ms / frame of a 5 s scene,
stills -> out/t4/charts_<canvas>_<lang>.png"""
import contextlib, io, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, os.getcwd())
import numpy as np
from PIL import Image
import mt.templates                                            # noqa: F401  (registers the templates)
from mt.anim import anim_state
from mt.common import FFMPEG
from mt.draw import draw_item
from mt.render import render_still
from mt.templates.t4.cfg import t4_cfg
from mt.templates.t4.scenes import SLOTS, t4_scenes_items
from mt.templates.t4.scenes_reg import get_widget
from mt.templates.t4.warn import t4_warn_reset

CV = {"reels": (1080, 1920), "youtube": (1920, 1080)}
LANG = {"en": {"bar_chart": {"values": [35, 55, 42, 78, 95], "labels": ["Jan", "Feb", "Mar", "Apr", "May"]},
               "progress_list": {"rows": ["code|Python|90", "database|SQL|75", "globe|Web design|60"]},
               "badge": {"text": "Python", "icon": "code"}},
        "ar": {"bar_chart": {"values": [35, 55, 42, 78, 95], "labels": ["يناير", "فبراير", "مارس", "أبريل", "مايو"]},
               "progress_list": {"rows": ["code|بايثون|90", "database|قواعد البيانات|75", "globe|تصميم المواقع|60"]},
               "badge": {"text": "بايثون", "icon": "code"}}}
rows = []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a)
    return r, [l for l in buf.getvalue().splitlines() if "[!]" in l]
def ink(it):
    ys, xs = np.where(np.asarray(it.sprite.getchannel("A")) > 8)
    if not len(xs): return None
    x0, y0 = it.cx - it.sprite.width / 2.0, it.cy - it.sprite.height / 2.0
    return x0 + xs.min(), y0 + ys.min(), x0 + xs.max() + 1, y0 + ys.max() + 1
def scene(lang):
    return [{"preset": "web_dev", "start": 0, "hold": 5, "stagger": 0.3, "widgets": [dict(type=t, **v) for t, v in LANG[lang].items()]}]
def job(video, cv, sc, out):
    W, H = CV[cv]
    return {"template_id": 5, "video": str(video), "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"},
            "background": {"type": "color", "value": "#000000"}, "t4": t4_cfg({"canvas_mode": cv, "fit": "fill", "scenes": sc}), "layers": [],
            "captions": [], "cards": [], "texts": [], "elements": [], "video_layers": [], "output": str(out)}
def draw_at(items, W, H, t):
    cv = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for it in items:
        if it.start <= t < it.end:
            draw_item(cv, it, anim_state(it.anim, it.progress(t), W, H))
    return cv
def cost(items, W, H, fps=25, dur=5.0):
    """Same loop as render._render pass 1 (signature cache + tobytes): -> (avg ms / frame, worst ms, frames really drawn, ms per drawn frame)."""
    last, per, drawn = None, [], 0
    for i in range(int(dur * fps)):
        t, t0, act, sig = i / fps, time.perf_counter(), [], []
        for it in items:
            if it.start <= t < it.end:
                st = anim_state(it.anim, it.progress(t), W, H); act.append((it, st))
                sig.append((id(it), round(st[0], 3), round(st[1]), round(st[2]), round(st[3], 3), round(st[4], 1), None if st[5] is None else round(st[5], 3)))
        sig = tuple(sig)
        if sig != last:
            if act:
                c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                for it, st in act: draw_item(c, it, st)
                c.tobytes(); drawn += 1
            last = sig
        per.append((time.perf_counter() - t0) * 1000)
    return sum(per) / len(per), max(per), drawn, sum(per) / max(1, drawn)

tmp = Path(tempfile.mkdtemp(prefix="t4ch_"))
os.makedirs("out/t4", exist_ok=True)
try:
    for cv, (W, H) in CV.items():
        s, asp = min(W, H) / 1080.0, ("portrait" if H > W else "landscape")
        mp4 = tmp / f"v_{cv}.mp4"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=25:d=2", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        for lang in LANG:
            tag = f"{cv}/{lang}"
            j = job(mp4, cv, scene(lang), tmp / "o.mp4")
            t4_warn_reset(); items, w = quiet(t4_scenes_items, j, 5.0)
            m = 48 * s - 1
            bad = [i for i in (ink(it) for it in items) if i is None or i[0] < m or i[1] < m or i[2] > W - m or i[3] > H - m]
            rec(f"{tag}: items built, no warning, every item >= 48 px from the edges", len(items) >= 12 and not w and not bad, f"{len(items)} items warn={w} bad={bad[:2]}")
            ctx = {"W": W, "H": H, "s": s, "aspect": asp, "preset": "web_dev", "cfg": {}}
            sp = get_widget("bar_chart")(dict(LANG[lang]["bar_chart"]), tuple(v * s for v in SLOTS["web_dev"][asp]["chart"]), ctx)
            rec(f"{tag}: bar_chart growth = {len(sp.info['lines'])} pre-built items (<= 9 = 8 steps + value labels), static sprite has no bars",
                0 < len(sp.info["lines"]) <= 9, "")
            box = [int(v * s) for v in SLOTS["web_dev"][asp]["chart"]]
            a1 = draw_at(items, W, H, 0.6).getchannel("A").crop((box[0], box[1], box[0] + box[2], box[1] + box[3]))
            a2 = draw_at(items, W, H, 3.0).getchannel("A").crop((box[0], box[1], box[0] + box[2], box[1] + box[3]))
            rec(f"{tag}: bars grow over time (chart alpha t=0.6 s < t=3.0 s)", np.asarray(a1, int).sum() < np.asarray(a2, int).sum(), f"{np.asarray(a1, int).sum()} < {np.asarray(a2, int).sum()}")
            avg, worst, drawn, per = cost(items, W, H)
            rec(f"{tag}: 5 s scene render cost", avg < 250, f"avg {avg:.1f} ms/frame, worst {worst:.0f} ms, {drawn} of 125 frames really drawn ({per:.0f} ms each)")
            out = Path("out/t4") / f"charts_{cv}_{lang}.png"
            quiet(render_still, j, str(out), 3.0)
            rec(f"{tag}: --still written -> {out}", out.is_file() and Image.open(out).size == (W, H), "")
    junk = [None, 5, "x", [], {"values": "abc"}, {"values": [None, "q", -3, float("nan")]}, {"rows": 5}, {"rows": ["|", {}, 7]}, {"text": None, "icon": None},
            {"text": "x" * 200, "icon": "banana"}, {"values": [1] * 40, "steps": "z", "glow": "q"}]
    errs = []
    for name in ("bar_chart", "progress_list", "badge"):
        for jk in junk:
            try:
                quiet(get_widget(name), jk, (50, 50, 600, 300), {"W": 1080, "H": 1920, "s": 1.0})
            except Exception as e:
                errs.append(f"{name}/{str(jk)[:20]}: {type(e).__name__}: {e}")
    rec("junk specs never raise (3 widgets x 11 junk values)", not errs, "; ".join(errs[:3]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)