"""Template 4 quick check (fast): python tools/mt_t4_quick.py
P1: compile + imports + cfg normaliser + 1.5 s --job renders on BOTH canvases (size / duration / audio).
P3 ('T4-3'): timing.py unit checks (t4_time / t4_stagger / t4_ask_when).
P2 ('T4-2'): base-video modes fill / fit and the backdrops colour / image / blur, measured on the rendered frames."""
import json, os, py_compile, subprocess, sys, tempfile, shutil
from pathlib import Path
import numpy as np
from PIL import Image
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
rows = []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
# ---- P1 ------------------------------------------------------------------------------------------------------------------------
bad = []
for f in list((P / "mt" / "templates" / "t4").glob("*.py")) + [P / "mt" / "templates" / "__init__.py", P / "mt" / "render.py"]:
    try: py_compile.compile(str(f), doraise=True)
    except Exception as e: bad.append(f"{f.name}: {e}")
rec("compile t4 package + templates/__init__ + render", not bad, "; ".join(bad))
import mt.templates                                            # noqa: E402
from mt.common import FFMPEG, TEMPLATE_REGISTRY, probe        # noqa: E402
from mt.templates.t4.cfg import T4_MODULES, t4_canvas, t4_cfg  # noqa: E402
e = TEMPLATE_REGISTRY.get(5, {})
rec("registry id 5", e.get("name") == "Template 4" and all(k in e for k in ("ask_config", "ask_cards", "caption_style", "build_background", "build_items")))
junk = [None, 5, "x", [], {"fit": 3, "canvas_mode": None, "backdrop": "red", "frame": 7, "tiles": {"on": 1, "n": 2}}]
ok = all(set(T4_MODULES) <= set(t4_cfg(j)) and t4_cfg(j)["fit"] == "fill" and t4_cfg(j)["backdrop"]["value"] == "#000000" for j in junk)
ok = ok and t4_cfg(junk[-1])["tiles"] == {"on": True, "n": 2} and t4_cfg({"backdrop": {"value": "#ABC"}})["backdrop"]["value"] == "#aabbcc"
rec("t4_cfg never raises, fills defaults", ok)
ok = (t4_canvas("auto", {"w": 1920, "h": 1080}) == [1920, 1080] and t4_canvas("auto", {"w": 720, "h": 1280}) == [1080, 1920]
      and t4_canvas("auto", None) == [1080, 1920] and t4_canvas("reels", {"w": 9, "h": 1}) == [1080, 1920] and t4_canvas("youtube") == [1920, 1080])
rec("t4_canvas", ok)
# ---- helpers -------------------------------------------------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="t4q_"))
CV = {"reels": [1080, 1920], "youtube": [1920, 1080]}
def job_for(video, canvas, fit, backdrop=None, **extra):
    t4 = t4_cfg({"canvas_mode": canvas, "fit": fit, "backdrop": backdrop or {}})
    cv = CV[canvas]
    return dict({"template_id": 5, "video": str(video), "canvas": cv, "video_box": {"x": 0, "y": 0, "w": cv[0], "h": cv[1], "mode": fit},
                 "background": {"type": "color", "value": t4["backdrop"]["value"]}, "t4": t4, "layers": [], "captions": [], "cards": [],
                 "texts": [], "elements": [], "video_layers": []}, **extra)
def run(name, job, still=False):
    jp, out = tmp / f"{name}.json", tmp / (f"{name}.png" if still else f"{name}.mp4")
    job = dict(job, output=str(tmp / f"{name}.mp4"), preview=1.5)
    jp.write_text(json.dumps(job), encoding="utf-8")
    args = ["--still", "--job", str(jp), "--still-out", str(out)] if still else ["--job", str(jp)]
    r = subprocess.run([sys.executable, str(P / "montage.py"), *args, "--arabic-mode", "raqm"], cwd=str(tmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (out if r.returncode == 0 and out.is_file() else None), r.stdout + r.stderr
def frame(path, t="0.7"):
    if str(path).endswith(".png"):
        return np.asarray(Image.open(path).convert("RGB"), float)
    png = tmp / "f.png"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", t, "-i", str(path), "-frames:v", "1", str(png)], check=True)
    return np.asarray(Image.open(png).convert("RGB"), float)
def bbox(a, thr=24):
    """(x0, x1, y0, y1) of the non-black area (pixels brighter than thr on any channel)."""
    m = a.max(axis=2) > thr
    xs, ys = np.where(m.any(axis=0))[0], np.where(m.any(axis=1))[0]
    return (int(xs[0]), int(xs[-1]) + 1, int(ys[0]), int(ys[-1]) + 1) if len(xs) and len(ys) else (0, 0, 0, 0)
def grad(a):
    return float(np.abs(np.diff(a.mean(axis=2), axis=1)).mean())
def mk(name, size, color=None):
    out = tmp / name
    src = f"testsrc2=s={size}:r=25:d=3" if not color else f"color=c={color}:s={size}:r=25:d=3"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i", "sine=f=440:d=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)], check=True)
    return out
def check_render(name, job, want):
    out, log = run(name, job)
    if not out:
        return rec(f"render {name}", False, log[-300:]), None
    i = probe(str(out)); w, h = want
    rec(f"render {name}", (i["w"], i["h"]) == (w, h) and abs(i["duration"] - 1.5) < 0.2 and bool(i["audio"]), f"{i['w']}x{i['h']} {i['duration']:.2f}s audio={bool(i['audio'])} (want {w}x{h} 1.5s audio)")
    return None, out
try:
    land, port = mk("land.mp4", "640x360"), mk("port.mp4", "360x640")
    # P1 renders (kept)
    for cname in ("reels", "youtube"):
        for fit in ("fill", "fit"):
            check_render(f"{cname}_{fit}", job_for(land, cname, fit), CV[cname])
    check_render("auto_nocanvas", {"template_id": 5, "video": str(land), "t4": {"canvas_mode": "auto"}, "layers": [], "captions": [], "cards": [], "texts": [], "elements": [], "video_layers": []}, (1920, 1080))
    # ---- T4-2: base video modes + backdrops ----------------------------------------------------------------------------------
    # (a) 9:16 clip, 16:9 canvas, fit, black sides (R3): centred full-height column, bars pure black
    out, _ = run("t42_port_yt_fit", job_for(port, "youtube", "fit"))
    a = frame(out) if out else None
    if a is not None:
        x0, x1, y0, y1 = bbox(a); bars = max(a[:, :x0 - 2].max(), a[:, x1 + 2:].max()) if x0 > 2 else 255
        rec("T4-2 9:16 clip on 16:9 canvas, fit: black sides, centred, full height", abs((x0 + x1) / 2 - 960) < 3 and abs((x1 - x0) - 607) < 6 and y0 <= 1 and y1 >= 1079 and bars < 8,
            f"video columns {x0}-{x1} (want ~656-1264), rows {y0}-{y1}, bar max={bars:.0f}")
    else: rec("T4-2 9:16 clip on 16:9 canvas, fit", False, "render failed")
    # (b) 16:9 clip on the 9:16 canvas, fit: full width, centred band
    out, _ = run("t42_land_rl_fit", job_for(land, "reels", "fit"))
    a = frame(out) if out else None
    if a is not None:
        x0, x1, y0, y1 = bbox(a); bars = max(a[:y0 - 2].max(), a[y1 + 2:].max()) if y0 > 2 else 255
        rec("T4-2 16:9 clip on 9:16 canvas, fit: full width, centred band, black bars", x0 <= 1 and x1 >= 1079 and abs((y0 + y1) / 2 - 960) < 3 and abs((y1 - y0) - 607) < 6 and bars < 8,
            f"cols {x0}-{x1}, band rows {y0}-{y1} (want ~656-1264), bar max={bars:.0f}")
    else: rec("T4-2 16:9 clip on 9:16 canvas, fit", False, "render failed")
    # (c) fill covers the canvas on both canvases (no black corner), aspect kept (crop, not stretch)
    for cname, src in (("youtube", port), ("reels", land)):
        out, _ = run(f"t42_fill_{cname}", job_for(src, cname, "fill"))
        a = frame(out) if out else None
        W, H = CV[cname]
        rec(f"T4-2 fill covers the {cname} canvas", a is not None and a.shape[:2] == (H, W) and min(a[:8, :8].max(), a[-8:, -8:].max(), a[:8, -8:].max(), a[-8:, :8].max()) > 24,
            "" if a is not None else "render failed")
    # (d) blur backdrop: sides are NOT black, much smoother than the video, video column untouched
    out, _ = run("t42_port_yt_blur", job_for(port, "youtube", "fit", {"type": "blur", "strength": 5}))
    a = frame(out) if out else None
    if a is not None:
        side, mid = a[:, 20:560], a[:, 700:1220]
        rec("T4-2 blur backdrop (9:16 on 16:9): sides lit + smooth, video sharp", side.mean() > 25 and grad(side) < 0.35 * grad(mid) and bbox(a, 8) == (0, 1920, 0, 1080),
            f"side mean={side.mean():.0f} side grad={grad(side):.2f} video grad={grad(mid):.2f}")
        ref = frame(run("t42_port_yt_fit2", job_for(port, "youtube", "fit"))[0])
        rec("T4-2 blur: the video column itself is identical to the plain fit render", float(np.abs(a[:, 700:1220] - ref[:, 700:1220]).mean()) < 1.5, f"mean diff {float(np.abs(a[:, 700:1220] - ref[:, 700:1220]).mean()):.2f}")
    else: rec("T4-2 blur backdrop", False, "render failed")
    out, log = run("t42_land_rl_blur", job_for(land, "reels", "fit", {"type": "blur", "strength": 8}))
    a = frame(out) if out else None
    rec("T4-2 blur backdrop (16:9 on 9:16): top / bottom bars lit", a is not None and a[:400].mean() > 25 and a[-400:].mean() > 25, "" if a is not None else log[-200:])
    # (e) image backdrop + broken image path
    Image.new("RGB", (64, 64), (200, 30, 30)).save(tmp / "bd.png")
    out, _ = run("t42_img", job_for(port, "youtube", "fit", {"type": "image", "path": str(tmp / "bd.png")}))
    a = frame(out) if out else None
    px = a[540, 100] if a is not None else None
    rec("T4-2 image backdrop (solid red png) fills the side bars", px is not None and abs(px - np.array([200, 30, 30])).max() < 14, f"pixel={None if px is None else px.round().tolist()}")
    out, log = run("t42_img_missing", job_for(port, "youtube", "fit", {"type": "image", "path": str(tmp / "nope.png"), "value": "#202020"}))
    a = frame(out) if out else None
    rec("T4-2 missing backdrop image -> solid colour + one warning, render still ok", a is not None and abs(a[540, 100] - 32).max() < 8 and log.count("backdrop image") == 1, f"warnings={log.count('backdrop image')}")
    # (f) colour backdrop value (16:9 clip on the 9:16 canvas leaves bars above / below)
    out, _ = run("t42_color", job_for(land, "reels", "fit", {"type": "color", "value": "#112233"}))
    a = frame(out) if out else None
    rec("T4-2 colour backdrop #112233 in the top / bottom bars", a is not None and abs(a[100, 540] - [17, 34, 51]).max() < 8 and abs(a[1800, 540] - [17, 34, 51]).max() < 8,
        "" if a is None else f"pixel={a[100, 540].round().tolist()}")
    # (g) --still on both canvases (fit + blur) + normaliser
    for cname, src in (("youtube", port), ("reels", land)):
        out, log = run(f"t42_still_{cname}", job_for(src, cname, "fit", {"type": "blur", "strength": 5}), still=True)
        a = frame(out) if out else None
        W, H = CV[cname]
        side = a[:, :150] if cname == "youtube" else a[:150]
        rec(f"T4-2 --still blur on {cname}", a is not None and a.shape[:2] == (H, W) and side.mean() > 25, "" if a is not None else log[-200:])
    n = t4_cfg({"backdrop": {"type": "weird", "strength": 99, "path": 5}})["backdrop"]; m = t4_cfg({"backdrop": {"type": "BLUR", "strength": "x"}})["backdrop"]
    rec("T4-2 normaliser: backdrop type / strength / path", n["type"] == "color" and n["strength"] == 10 and n["path"] == "" and m["type"] == "blur" and m["strength"] == 5, f"{n} {m}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
# ---- T4-3 timing (pure unit checks, no render) ----------------------------------------------------------------------------------
import builtins, contextlib, io                                # noqa: E402
from mt.templates.t4.timing import t4_ask_when, t4_stagger, t4_time, t4_warn_reset  # noqa: E402
def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): r = fn(*a)
    return r, [l for l in buf.getvalue().splitlines() if "[!]" in l]
CUES = [(1.0, 2.0, "hello everyone"), (3.0, 4.0, "open the project now")]
t4_warn_reset()
r, w = quiet(lambda: (t4_time({"start": 2, "end": 5}, [], 10, 4), t4_time({"start": "0:03", "end": "0:06"}, None, 10, 4)))
rec("T4-3 explicit start / end (numbers and mm:ss strings)", r == ((2.0, 5.0), (3.0, 6.0)) and not w, f"{r} {w}")
r, w = quiet(lambda: (t4_time({"trigger": "open the project", "hold": 2}, CUES, 10, 4), t4_time({"trigger": "open the project"}, [CUES, []], 10, 4)))
rec("T4-3 trigger found (one cue list, or a list of streams); hold / default_hold", r == ((3.0, 5.0), (3.0, 7.0)) and not w, f"{r} {w}")
t4_warn_reset()
r, w = quiet(lambda: [t4_time({"trigger": "never said"}, CUES, 10, 4) for _ in range(3)])
rec("T4-3 trigger missing -> None, warned once", r == [None] * 3 and len(w) == 1, f"{r} {w}")
r, w = quiet(lambda: t4_time({"trigger": "never said", "start": 2, "hold": 1}, CUES, 10, 4))
rec("T4-3 trigger missing but start given -> start is used", r == (2.0, 3.0), f"{r} {w}")
r, w = quiet(lambda: (t4_time({"start": 1, "hold": 2.5}, None, 10, 4), t4_time({"start": 1}, None, 10, 4), t4_time({"start": 1, "hold": 0}, None, 10, 3), t4_time({"start": 1, "end": 9, "hold": 2}, None, 10, 4)))
rec("T4-3 hold / default_hold / end wins over hold", r == ((1.0, 3.5), (1.0, 5.0), (1.0, 4.0), (1.0, 9.0)), f"{r}")
r, w = quiet(lambda: (t4_time({"start": 8, "end": 20}, None, 10, 4), t4_time({"start": 9, "hold": 5}, None, 10, 4), t4_time({"start": 10}, None, 10, 4), t4_time({"start": 12}, None, 10, 4), t4_time({"start": 2}, None, 10, None)))
rec("T4-3 end beyond duration clamped; start at / after the video end -> None; no hold -> to the end", r == ((8.0, 10.0), (9.0, 10.0), None, None, (2.0, 10.0)), f"{r}")
junk = [None, 5, "x", [], {}, {"start": "abc"}, {"start": float("nan")}, {"start": True}, {"trigger": 7}, {"start": 1, "end": "zz", "hold": "q"}]
r, w = quiet(lambda: [t4_time(j, CUES, "bad", "bad") for j in junk])
rec("T4-3 junk never raises", r == [None] * len(junk), f"{r}")
rec("T4-3 t4_stagger", t4_stagger(3, 0.2) == [0.0, 0.2, 0.4] and t4_stagger(0, 1) == [] and t4_stagger("x", 1) == [] and t4_stagger(2, "q") == [0.0, 0.0] and t4_stagger(2, -1) == [0.0, 0.0])
def scripted(inputs, **kw):
    it = iter(inputs); old = builtins.input; builtins.input = lambda *_: next(it)
    try: return quiet(t4_ask_when, "Name tag", 4.0)[0]
    finally: builtins.input = old
a, b = scripted(["1", "0:05", "3"]), scripted(["2", "open the project", ""])
rec("T4-3 t4_ask_when (time mode / phrase mode, default hold)", a == {"start": 5.0, "hold": 3.0} and b == {"trigger": "open the project", "hold": 4.0}, f"{a} {b}")
# ---- T4-4 captions 'pill' (unit checks; stills are checked by eye - see T4_NOTES) ---------------------------------------------------
import itertools, tempfile                                                # noqa: E402
from mt.captions import parse_srt, stream_groups               # noqa: E402
from mt.render import build_items                              # noqa: E402
from mt.templates.t4.captions import T4_CAP, t4_caption_items, t4_caption_style, t4_pill_sprite, t4_tokens  # noqa: E402
ctmp = Path(tempfile.mkdtemp(prefix="t4cap_"))               # (tmp is already removed by the render section's finally)
AR = "بس أنا مش عايز حسابي يبقى مجرد *بوست* ولا حاجة تانية خالص في الدنيا دي كلها يا جماعة"
EN = "Learn Flutter and build real apps that people actually use every single day without any stress"
(ctmp / "ar.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\n" + AR + "\n\n2\n00:00:02,000 --> 00:00:04,000\nأنا أحمد مطور\n", encoding="utf-8")
(ctmp / "en.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\n" + EN + "\n\n2\n00:00:02,000 --> 00:00:04,000\nHello *world*\n", encoding="utf-8")
CAPC = {"t4_style": "pill", "ref": "canvas", "mode": "phrase", "keywords": "Flutter"}
rec("T4-4 t4_tokens: *stars* + keyword list", t4_tokens("a *b c* d Flutter", "flutter") == [["a", False], ["b", True], ["c", True], ["d", False], ["Flutter", True]], str(t4_tokens("a *b c* d Flutter", "flutter")))
for cv in ("reels", "youtube"):
    W, H = CV[cv]
    for nm in ("ar", "en"):
        job = job_for(ctmp / "none.mp4", cv, "fill", captions=[dict(CAPC, srt=str(ctmp / f"{nm}.srt"))])
        t4_warn_reset()
        items, w = quiet(t4_caption_items, job, 4.0)
        ph = [(it.sprite.info["pill_h"], it.sprite.info["pad"], it.sprite.width) for it in items]
        pill_w = [sw - 2 * g for _, g, sw in ph]
        want_y = H * T4_CAP["y_pct"][cv] / 100.0
        ok = len(items) == 2 and not w and all(pw <= W * 0.84 + 1 for pw in pill_w)
        ok = ok and all(abs((it.cy + h / 2.0) - want_y) < 1.5 and it.cx == W / 2.0 for it, (h, g, _) in zip(items, ph))
        ok = ok and all(it.cy + h / 2.0 <= H - 48 and it.cy - h / 2.0 >= 48 for it, (h, g, _) in zip(items, ph))
        rec(f"T4-4 pill items {nm} on {cv}: 2 items, pill <= 84 % wide, bottom edge at {T4_CAP['y_pct'][cv]} %, inside the safe margin", ok, f"{len(items)} items pill_w={pill_w} bottom={[round(it.cy + h / 2.0) for it, (h, _, _) in zip(items, ph)]} want {want_y:.0f} warn={w}")
job = job_for(ctmp / "none.mp4", "reels", "fill", captions=[dict(CAPC, srt=str(ctmp / "ar.srt"))])
n_t4, n_all = len(quiet(t4_caption_items, job, 4.0)[0]), len([i for i in quiet(build_items, job, 4.0)[0] if i.sprite.info.get("pill_h")])
rec("T4-4 render.build_items: pill streams drawn once (by t4_build_items, skipped by the generic caption loop)", n_t4 == 2 and n_all == 2, f"t4={n_t4} via build_items={n_all} (4 would mean drawn twice)")
groups = stream_groups(parse_srt(str(ctmp / "en.srt")), dict(CAPC))
rec("T4-4 keyword highlighted via the list and via *stars* in the SRT", [w for g in groups for w, h in g[2] if h] == ["Flutter", "world"], str([[w for w, h in g[2] if h] for g in groups]))
two = t4_pill_sprite([[x, False] for x in "Learn Flutter and build real apps".split()], None, 56, max_w=700)
one = t4_pill_sprite([["Hi", False], ["there", True]], None, 56, max_w=700)
huge = t4_pill_sprite([[x, False] for x in EN.split()], None, 56, max_w=900)
rec("T4-4 wraps to 2 lines / very long text shrinks to <= 2 lines inside max_w; empty -> None",
    two.info["pill_h"] > one.info["pill_h"] * 1.5 and two.width - 2 * two.info["pad"] <= 700 and huge.width - 2 * huge.info["pad"] <= 900
    and huge.info["pill_h"] < one.info["pill_h"] * 2.6 and t4_pill_sprite([], None) is None and t4_pill_sprite([["  ", False]], None) is None,
    f"two={two.info['pill_h']} one={one.info['pill_h']} huge={huge.info['pill_h']}")
t4_warn_reset()
r, w = quiet(lambda: (t4_caption_items(dict(job, captions=[dict(CAPC, srt=str(ctmp / "nope.srt"))]), 4.0), t4_caption_items(dict(job, captions=[dict(CAPC, srt=str(ctmp / "nope.srt"))]), 4.0)))
rec("T4-4 missing SRT -> no items, warned once, no crash", r == ([], []) and len(w) == 1, f"{r} {w}")
t4_warn_reset()
r, w = quiet(t4_caption_items, dict(job, captions=[dict(CAPC, srt=str(ctmp / "en.srt"), font="/no/such/font.ttf", size="abc", y_pct="zz", anim_dur="q")]), 4.0)
rec("T4-4 missing font / junk size, y, anim_dur -> fallbacks, one font warning", len(r) == 2 and len(w) == 1 and "font" in w[0], f"{len(r)} items {w}")
rec("T4-4 job without canvas -> warned, no items", quiet(t4_caption_items, {"captions": job["captions"]}, 4.0)[0] == [])
def scripted2(first, n=40):
    it = itertools.chain(first, itertools.repeat("")); old = builtins.input; builtins.input = lambda *_: next(it)
    try: return quiet(t4_caption_style, 0, str(ctmp / "ar.srt"))[0]
    finally: builtins.input = old
cp, cplain = scripted2(["1"]), scripted2(["2"])
rec("T4-4 t4_caption_style: 'pill' -> t4_style pill + yellow / cyan defaults + y_pct None; 'plain' -> classic stream", cp.get("t4_style") == "pill" and cp["hl_color"].lower() in ("#ffc21a", "#ffc21a".upper()) and cp.get("y_pct") in (None, "") and cp["mode"] == "phrase" and "t4_style" not in cplain and cplain.get("srt"), f"{ {k: cp.get(k) for k in ('t4_style', 'hl_color', 'neon', 'y_pct', 'mode', 'size')} } plain={sorted(cplain)[:4]}")
# ---- T4-5 captions 'glow' (unit checks; stills are checked by eye - see T4_NOTES) --------------------------------------------------
from mt.templates.t4.captions_glow import T4_GLOW, t4_glow_sprite   # noqa: E402
GL = {"t4_style": "glow", "ref": "canvas", "mode": "phrase"}
GAR = {"start": "*بوست* ده اللي مش عايزه يحصل", "middle": "بس أنا مش عايز *بوست* حسابي يبقى مجرد", "end": "بس أنا مش عايز حسابي يبقى مجرد *بوست*"}
GEN = {"start": "*Flutter* is the best way to build real apps", "middle": "Build real *Flutter* apps that people use", "end": "I do not want my account to be just a *post*"}
bad_g = []
for cv in ("reels", "youtube"):
    W, H = CV[cv]
    for nm, d in (("ar", GAR), ("en", GEN)):
        for pos, txt in d.items():
            f = ctmp / f"g_{nm}_{pos}.srt"
            f.write_text("1\n00:00:00,000 --> 00:00:02,000\n" + txt + "\n", encoding="utf-8")
            t4_warn_reset()
            items, w = quiet(t4_caption_items, job_for(ctmp / "none.mp4", cv, "fill", captions=[dict(GL, srt=str(f))]), 4.0)
            if len(items) != 1 or w:
                bad_g.append(f"{cv}/{nm}/{pos}: {len(items)} items warn={w}"); continue
            it = items[0]; a = np.asarray(it.sprite.getchannel("A"))
            ys, xs = np.where(a > 60)
            x0, x1 = it.cx - it.sprite.width / 2.0 + xs.min(), it.cx - it.sprite.width / 2.0 + xs.max()
            y0, y1 = it.cy - it.sprite.height / 2.0 + ys.min(), it.cy - it.sprite.height / 2.0 + ys.max()
            sf = 48 * min(W, H) / 1080.0
            if not (x0 >= sf * 0.9 and x1 <= W - sf * 0.9 and y0 >= sf and y1 <= H - sf * 0.9 and it.cx == W / 2.0):
                bad_g.append(f"{cv}/{nm}/{pos}: ink box x {x0:.0f}-{x1:.0f} y {y0:.0f}-{y1:.0f} outside safe")
rec("T4-5 glow items (ar/en x start/middle/end x both canvases): 1 item, no warning, ink inside the safe margin, centred", not bad_g, "; ".join(bad_g[:3]))
job = job_for(ctmp / "none.mp4", "reels", "fill", captions=[dict(GL, srt=str(ctmp / "g_ar_end.srt"))])
rec("T4-5 render.build_items: glow streams drawn once (generic caption loop skips them)", len(quiet(t4_caption_items, job, 4.0)[0]) == 1 and len([i for i in quiet(build_items, job, 4.0)[0] if i.sprite.info.get("block_h")]) == 1)
ok = (t4_glow_sprite([], None) is None and t4_glow_sprite(None, None) is None and t4_glow_sprite([["  ", False]], None) is None
      and t4_glow_sprite([["Hi", False]], "/no/font.ttf", size="x" if False else 40) is not None
      and t4_glow_sprite([["Hi", True], [5, True]], None, 40, color="junk", hl=None, neon=(1, 2)) is not None)
nokw = t4_glow_sprite([["plain", False], ["text", False]], None, 60, max_w=700)
withkw = t4_glow_sprite([["plain", False], ["text", True]], None, 60, max_w=700)
rec("T4-5 t4_glow_sprite never raises (empty / junk colours / missing font); no keyword -> no sparks / swoosh margin", ok and nokw.info["above"] == 0 and withkw.info["above"] > 0 and withkw.info["below"] > 0)
t4_warn_reset()
r, w = quiet(t4_caption_items, dict(job, captions=[dict(GL, srt=str(ctmp / "g_en_end.srt"), font="/no/such/font.ttf", size="abc", y_pct="zz", anim_dur="q")]), 4.0)
rec("T4-5 glow: missing font / junk size, y, anim_dur -> fallbacks, one font warning", len(r) == 1 and len(w) == 1 and "font" in w[0], f"{len(r)} items {w}")
cg = scripted2(["3"])
rec("T4-5 t4_caption_style: choice 3 -> t4_style glow + blue keyword default + y_pct None; 'pill' stays pill", cg.get("t4_style") == "glow" and cg["hl_color"].lower() == T4_GLOW["hl"].lower() and cg.get("y_pct") in (None, "") and cp.get("t4_style") == "pill", str({k: cg.get(k) for k in ("t4_style", "hl_color", "neon", "size")}))
# ---- T4-6 captions 'twoline' (unit checks; stills are checked by eye - see T4_NOTES) ------------------------------------------------
from mt.templates.t4.captions_twoline import T4_TWO, t4_split_words, t4_twoline_sprite   # noqa: E402
W6 = lambda s: [[w, False] for w in s.split()]
a, b = t4_split_words(W6("a b c d e"), 3), t4_split_words(W6("a b c"), 3)
rec("T4-6 split by word count: 5 words -> 3 + 2; <= words1 words or 1 word -> pill only; 0 = half; junk -> 3",
    [len(x) for x in a] == [3, 2] and [len(x) for x in b] == [0, 3] and t4_split_words(W6("a"), 3)[0] == []
    and [len(x) for x in t4_split_words(W6("a b c d e"), 0)] == [3, 2] and [len(x) for x in t4_split_words(W6("a b c d"), "x")] == [3, 1]
    and t4_split_words(None, 3) == ([], []) and [len(x) for x in t4_split_words(W6("a b c d"), float("inf"))] == [3, 1], f"{[len(x) for x in a]} {[len(x) for x in b]}")
TW = {"t4_style": "twoline", "ref": "canvas", "mode": "phrase", "words1": 3}
TAR = {"two": "أنا *أحمد* إيراهيم، مطور ويب وتطبيقات موبايل", "one": "مطور ويب"}
TEN = {"two": "I am *Ahmed* Ibrahim, a web and mobile app developer", "one": "Web developer"}
bad_t = []
for cv in ("reels", "youtube"):
    W, H = CV[cv]
    for nm, d in (("ar", TAR), ("en", TEN)):
        for kind, txt in d.items():
            f = ctmp / f"t_{nm}_{kind}.srt"
            f.write_text("1\n00:00:00,000 --> 00:00:02,000\n" + txt + "\n", encoding="utf-8")
            t4_warn_reset()
            items, w = quiet(t4_caption_items, job_for(ctmp / "none.mp4", cv, "fill", captions=[dict(TW, srt=str(f))]), 4.0)
            if len(items) != 1 or w:
                bad_t.append(f"{cv}/{nm}/{kind}: {len(items)} items warn={w}"); continue
            it = items[0]; i = it.sprite.info
            a_ = np.asarray(it.sprite.getchannel("A")); ys, xs = np.where(a_ > 60)
            x0, x1 = it.cx - it.sprite.width / 2.0 + xs.min(), it.cx - it.sprite.width / 2.0 + xs.max()
            y0, y1 = it.cy - it.sprite.height / 2.0 + ys.min(), it.cy - it.sprite.height / 2.0 + ys.max()
            sf, want = 48 * min(W, H) / 1080.0, H * T4_TWO["y_pct"][cv] / 100.0
            pill_w = it.sprite.width - 2 * (i["pad"] + int(i["pill_h"] * 0.4))
            if not (x0 >= sf * 0.9 and x1 <= W - sf * 0.9 and y0 >= sf and y1 <= H - sf * 0.9 and it.cx == W / 2.0
                    and i["lines"] == (2 if kind == "two" else 1) and abs(it.cy + i["pill_bottom"] - it.sprite.height / 2.0 - want) < 1.5
                    and pill_w <= W * 0.84 + 2):
                bad_t.append(f"{cv}/{nm}/{kind}: ink x {x0:.0f}-{x1:.0f} y {y0:.0f}-{y1:.0f} lines={i['lines']}")
rec("T4-6 twoline items (ar/en x two-line/one-line x both canvases): 1 item, no warning, 2 vs 1 lines, ink in the safe margin, pill bottom at y_pct", not bad_t, "; ".join(bad_t[:3]))
job = job_for(ctmp / "none.mp4", "reels", "fill", captions=[dict(TW, srt=str(ctmp / "t_ar_two.srt"))])
rec("T4-6 render.build_items: twoline streams drawn once (generic caption loop skips them)", len(quiet(t4_caption_items, job, 4.0)[0]) == 1 and len([i for i in quiet(build_items, job, 4.0)[0] if i.sprite.info.get("pill_bottom")]) == 1)
ok = (t4_twoline_sprite([], None) is None and t4_twoline_sprite(None, None) is None and t4_twoline_sprite([["  ", False]], None) is None
      and t4_twoline_sprite([["Hi", True], [5, True], ["x", False], ["y", False]], "/no/font.ttf", 40, color="junk", hl=None, neon=(1, 2), words1="q") is not None)
one_s, two_s = t4_twoline_sprite(W6("Web developer"), None, 60, max_w=700), t4_twoline_sprite(W6("I am Ahmed Ibrahim a web developer"), None, 60, max_w=700)
rec("T4-6 t4_twoline_sprite never raises; one line (pill only) is shorter than two lines", ok and one_s.info["lines"] == 1 and two_s.info["lines"] == 2 and one_s.height < two_s.height)
t4_warn_reset()
r, w = quiet(t4_caption_items, dict(job, captions=[dict(TW, srt=str(ctmp / "t_en_two.srt"), font="/no/such/font.ttf", size="abc", y_pct="zz", anim_dur="q", words1="zz")]), 4.0)
rec("T4-6 twoline: missing font / junk size, y, anim_dur, words1 -> fallbacks, one font warning", len(r) == 1 and len(w) == 1 and "font" in w[0], f"{len(r)} items {w}")
ct = scripted2(["4"])
rec("T4-6 t4_caption_style: choice 4 -> t4_style twoline + cyan keyword default + words1 3 + y_pct None; pill / glow unchanged", ct.get("t4_style") == "twoline" and ct["hl_color"].lower() == T4_TWO["hl"].lower() and ct.get("words1") == 3 and ct.get("y_pct") in (None, "") and cp.get("t4_style") == "pill" and cg.get("t4_style") == "glow", str({k: ct.get(k) for k in ("t4_style", "hl_color", "neon", "words1", "size")}))
# ---- T4-7 frame (unit checks + one --still pixel check; the look is checked by eye - see T4_NOTES) ----------------------------------------
import mt.templates.t4 as t4mod                                             # noqa: E402
from mt.fonts import default_font                                         # noqa: E402
from mt.templates.t4.frame import T4_FRAME, t4_ask_frame, t4_frame_cfg, t4_frame_part, t4_frame_plate   # noqa: E402
ftmp = Path(tempfile.mkdtemp(prefix="t4frm_"))
try:
    FN = t4_frame_cfg({"on": True})
    a, b = t4_frame_cfg({"on": "no", "text": "-", "color": "zzz", "icon": "NONE", "show_ticks": "false", "font": "/x.ttf"}), t4_frame_cfg(7)
    c = t4_frame_cfg({"on": 1, "text": " Hi ", "color": "#abc", "icon": "Gear", "show_ticks": 0})
    rec("T4-7 t4_frame_cfg: defaults, junk -> defaults, '-' / none -> off, extras kept, never raises",
        FN == dict(T4_FRAME, on=True) and a["on"] is False and a["text"] == "" and a["color"] == "#19D3FF" and a["icon"] == "" and a["show_ticks"] is False
        and a["font"] == "/x.ttf" and b == T4_FRAME and c["text"] == "Hi" and c["color"] == "#aabbcc" and c["icon"] == "gear" and c["show_ticks"] is False,
        f"{a} {c}")
    bad_f = []
    for cv, (W, H) in CV.items():
        for nm, txt in (("en", "CODE \u2022 BUILD \u2022 INSPIRE"), ("ar", "\u0643\u0648\u0651\u062f \u2022 \u0627\u0628\u0646\u0650 \u2022 \u0623\u0644\u0647\u0650\u0645"),
                        ("long", "WEB \u2022 MOBILE \u2022 AI \u2022 CLOUD \u2022 DEVOPS \u2022 DESIGN \u2022 SECURITY \u2022 DATA")):
            pl = t4_frame_plate(W, H, t4_frame_cfg({"on": True, "text": txt}))
            al = np.asarray(pl.getchannel("A"))
            cen = al[int(H * 0.18):int(H * 0.72), int(W * 0.20):int(W * 0.80)]
            ys, xs = np.where(al[H - 90:H - 30, int(W * 0.30):int(W * 0.70)] > 200)
            bar_w = (xs.max() - xs.min()) if xs.size else 0
            if not (pl.size == (W, H) and pl.mode == "RGBA" and cen.max() == 0 and al[:60].max() > 200 and al[-60:].max() > 200
                    and al[:, :60].max() > 200 and al[:, -60:].max() > 200 and bar_w > 120):
                bad_f.append(f"{cv}/{nm}: size={pl.size} centre_alpha={cen.max()} bar_w={bar_w}")
    rec("T4-7 frame plate (both canvases x EN / AR / long text): full-canvas RGBA, centre fully transparent, rails + brackets on all 4 sides, bar drawn", not bad_f, "; ".join(bad_f[:3]))
    W, H = CV["reels"]
    base = t4_frame_cfg({"on": True})
    notxt, noic, notk = (np.asarray(t4_frame_plate(W, H, dict(base, **kw)).getchannel("A"), int) for kw in ({"text": ""}, {"icon": ""}, {"show_ticks": False}))
    full = np.asarray(t4_frame_plate(W, H, base).getchannel("A"), int)
    rec("T4-7 frame options: text '' drops the bar + stripes, icon '' drops the icon, show_ticks False drops the ticks (nothing else changes)",
        (full - notxt)[H - 120:].sum() > 0 and (full - notxt)[:H - 120].sum() == 0 and (full - noic)[:260, W - 260:].sum() > 0 and (full - noic).clip(0).sum() == (full - noic)[:260, W - 260:].clip(0).sum()
        and (full - notk)[:, 40:70].sum() > 0 and (full - notk)[:, :20].sum() == 0 and (full - notk)[:, 100:W - 100].sum() == 0)
    # compose: one plate from several parts
    got = {}
    for cv, (W, H) in CV.items():
        cfg = {"canvas": [W, H], "t4": t4_cfg({"canvas_mode": cv, "frame": {"on": True}}), "video": str(ftmp / "none.mp4")}
        (ftmp / cv).mkdir()
        quiet(t4mod.t4_build_static_layers, cfg, str(ftmp / cv))
        got[cv] = (cfg.get("_t2_fg"), cfg["t4"]["frame"], cfg["canvas"])
    ok = all(v[0] and os.path.isfile(v[0]) and Image.open(v[0]).size == tuple(CV[k]) and v[1] == dict(T4_FRAME, on=True) and v[2] == CV[k] for k, v in got.items())
    rec("T4-7 t4_build_static_layers -> cfg['_t2_fg'] = one canvas-size PNG (both canvases), cfg['t4']['frame'] completed", ok, str(got))
    cfg = {"canvas": [1080, 1920], "t4": t4_cfg({"frame": {"on": False}}), "_t2_fg": "/stale.png"}
    quiet(t4mod.t4_build_static_layers, cfg, str(ftmp))
    cfg2 = {"canvas": [1080, 1920], "t4": t4_cfg({})}
    quiet(t4mod.t4_build_static_layers, cfg2, None)
    rec("T4-7 frame off (or no frame key) -> no plate, a stale cfg['_t2_fg'] is removed", "_t2_fg" not in cfg and "_t2_fg" not in cfg2, str(cfg.get("_t2_fg")))
    # a later module adds its part to the SAME plate; a failing part is skipped with one warning
    def dummy(W, H, t4):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); im.paste((255, 0, 0, 255), (W // 2 - 20, H // 2 - 20, W // 2 + 20, H // 2 + 20)); return im
    def boom(W, H, t4):
        raise ValueError("boom")
    def wrong(W, H, t4):
        return Image.new("RGBA", (10, 10))
    saved = list(t4mod.T4_FG_PARTS)
    try:
        t4mod.T4_FG_PARTS[:] = saved + [("dummy", dummy), ("boom", boom), ("wrong", wrong)]
        cfg = {"canvas": [1080, 1920], "t4": t4_cfg({"frame": {"on": True}})}
        t4_warn_reset(); r, w = quiet(t4mod.t4_compose_fg, cfg, str(ftmp))
        pm = np.asarray(Image.open(cfg["_t2_fg"]).convert("RGBA"))
        t4mod.T4_FG_PARTS[:] = [("dummy", dummy)]
        cfg3 = {"canvas": [1080, 1920], "t4": t4_cfg({})}
        quiet(t4mod.t4_compose_fg, cfg3, str(ftmp))
    finally:
        t4mod.T4_FG_PARTS[:] = saved
    rec("T4-7 t4_compose_fg: frame + a later part merged into ONE plate; a raising / wrong-size part -> one warning each, others kept; parts without the frame still work",
        pm[960, 540].tolist() == [255, 0, 0, 255] and pm[:60, :, 3].max() > 200 and len(w) == 2 and "boom" in w[0] and "1080x1920" in w[1] and "_t2_fg" in cfg3, f"{w}")
    t4_warn_reset(); r, w = quiet(t4_frame_part, 1080, 1920, {"frame": {"on": True, "icon": "banana"}})
    rec("T4-7 unknown icon -> one warning, plate still built without an icon; part = None when off", r is not None and len(w) == 1 and "banana" in w[0]
        and t4_frame_part(1080, 1920, {"frame": {"on": False}}) is None and t4_frame_part(1080, 1920, None) is None, f"{w}")
    def ask_with(ans):
        it = iter(ans); old = builtins.input; builtins.input = lambda *_: next(it)
        try: return quiet(t4_ask_frame)[0]
        finally: builtins.input = old
    from mt.common import D                                                 # ask() remembers answers as the next defaults
    D.clear(); qn, qy = ask_with(["n"]), ask_with(["y", "KEEP IT", "red", "3", "n"])
    D.clear(); qd = ask_with(["y", "", "", "", ""]); D.clear()
    rec("T4-7 question group: n -> {'on': False}; y + answers -> {on, text, color, icon, show_ticks}; Enter = defaults",
        qn == {"on": False} and qy == {"on": True, "text": "KEEP IT", "color": "#ff0000", "icon": "laptop", "show_ticks": False}
        and qd == {"on": True, "text": T4_FRAME["text"], "color": T4_FRAME["color"].lower(), "icon": "code", "show_ticks": True}, f"{qn} {qy} {qd}")
    # real --still on both canvases: the video pixels are untouched wherever the plate is transparent
    bad_s = []
    for cv, (W, H) in CV.items():
        mp4 = ftmp / f"v_{cv}.mp4"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=25:d=2", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        res = {}
        for nm, fr in (("off", {"on": False}), ("on", {"on": True})):
            fr = dict(fr, font=default_font())                              # same font in this process and in montage.py
            job = dict(job_for(mp4, cv, "fill"), t4=t4_cfg({"canvas_mode": cv, "fit": "fill", "frame": fr}), output=str(ftmp / "o.mp4"))
            jp, out = ftmp / f"{cv}_{nm}.json", ftmp / f"{cv}_{nm}.png"
            jp.write_text(json.dumps(job), encoding="utf-8")
            r = subprocess.run([sys.executable, str(P / "montage.py"), "--still", "--job", str(jp), "--still-out", str(out), "--arabic-mode", "reshape"], cwd=str(ftmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
            res[nm] = np.asarray(Image.open(out).convert("RGB"), int) if r.returncode == 0 and out.is_file() else None
        if res["off"] is None or res["on"] is None:
            bad_s.append(f"{cv}: still failed"); continue
        al = np.asarray(t4_frame_plate(W, H, t4_frame_cfg({"on": True, "font": default_font()})).getchannel("A"))
        same = (np.abs(res["on"] - res["off"]).max(axis=2) <= 2)
        if not (same[al == 0].all() and (~same).sum() > 3000 and (~same)[:, :].any(axis=1)[:60].any()):
            bad_s.append(f"{cv}: untouched={same[al == 0].mean():.4f} changed_px={(~same).sum()}")
    rec("T4-7 --still on both canvases: frame drawn over the video, every pixel the plate leaves transparent is byte-identical to the frame-less render", not bad_s, "; ".join(bad_s))
finally:
    shutil.rmtree(ftmp, ignore_errors=True)
# ---- T4-8 nameplate (tag_a / tag_b) + corner_list: cfg, placement, frame coexistence, timing, animation, questions ---------------------------
from PIL import ImageChops                                                  # noqa: E402
from mt.templates.t4.nameplate import (CORNERS, FRAME_THR, INK_THR, T4_CORNER_LIST, T4_NAMEPLATE, t4_ask_corner_list, t4_ask_nameplate,  # noqa: E402
                                        t4_corner_list_cfg, t4_nameplate_cfg, t4_nameplate_items)
from mt.templates.t4.frame import t4_frame_plate as _fplate               # noqa: E402
def _np_job(cv, frame_on, tag=None, lst=None, **extra):
    t4 = t4_cfg({"canvas_mode": cv, "frame": {"on": frame_on}, "nameplate": tag or {"on": False}, "corner_list": lst or {"on": False}})
    return dict({"canvas": list(CV[cv]), "t4": t4}, **extra)
def _ink(it, W, H):
    full = Image.new("L", (W, H), 0)
    full.paste(it.sprite.getchannel("A").point(lambda v: 255 if v > INK_THR else 0), (int(it.cx - it.sprite.width / 2), int(it.cy - it.sprite.height / 2)))
    return full
a, b = t4_nameplate_cfg({"on": "yes", "style": "B", "anchor": "br", "color": "zzz", "inset_x": "x", "anim": "bogus", "anim_dur": -3, "icon": "NONE", "font": "/x.ttf"}), t4_nameplate_cfg(7)
c, d = t4_corner_list_cfg({"on": 1, "rows": ["gear|Hi", "plain", 5, {"text": ""}, ["globe", "Web"]], "size": "abc", "anchor": "zzz", "icon": False}), t4_corner_list_cfg("x")
rec("T4-8 nameplate / corner_list cfg: defaults, junk -> defaults, style / anchor aliases, rows cleaned, extras kept, never raises",
    b == T4_NAMEPLATE and d == T4_CORNER_LIST and a["style"] == "tag_b" and a["anchor"] == "bottom-right" and a["on"] is True and a["color"] == "#19D3FF" and a["inset_x"] == 0.0
    and a["anim"] == "auto" and a["anim_dur"] == 0.45 and a["icon"] == "" and a["font"] == "/x.ttf" and t4_nameplate_cfg({"style": "tag_b"})["anchor"] == "top-left"
    and t4_nameplate_cfg({})["anchor"] == "bottom-left" and [r["text"] for r in c["rows"]] == ["Hi", "plain", "Web"] and c["rows"][0]["icon"] == "gear"
    and c["size"] == 22.0 and c["anchor"] == "bottom-right" and c["icon"] == "", f"{a} {c}")
rec("T4-8 'corner_list' is a registered T4 module and t4_cfg keeps its dict", "corner_list" in T4_MODULES and t4_cfg({"corner_list": {"on": 1, "x": 2}})["corner_list"] == {"on": True, "x": 2})
bad_n = []
for cv, (W, H) in CV.items():
    s = min(W, H) / 1080.0
    for fo in (False, True):
        fa = _fplate(W, H, t4_frame_cfg({"on": True})).getchannel("A").point(lambda v: 255 if v > FRAME_THR else 0) if fo else None
        cases = [({"on": True, "style": st, "anchor": an}, None) for st in ("tag_a", "tag_b") for an in CORNERS]
        cases += [({"on": True, "style": "tag_b", "name": "أحمد إبراهيم", "role": "مطور ويب"}, None), (None, {"on": True}),
                  (None, {"on": True, "anchor": "top-left", "icon_anchor": "top-right"}), ({"on": True, "name": "N" * 55, "role": "R" * 55}, None)]
        for tag, lst in cases:
            t4_warn_reset(); items, w = quiet(t4_nameplate_items, _np_job(cv, fo, tag, lst), 10.0)
            if not items or w:
                bad_n.append(f"{cv}/frame={fo}/{tag or lst}: items={len(items)} warn={w}"); continue
            for it in items:
                m = _ink(it, W, H); bb = m.getbbox()
                hit = fa is not None and ImageChops.multiply(m, fa).getbbox() is not None
                if not (bb and bb[0] >= 48 * s - 1 and bb[1] >= 48 * s - 1 and W - bb[2] >= 48 * s - 1 and H - bb[3] >= 48 * s - 1) or hit:
                    bad_n.append(f"{cv}/frame={fo}/{(tag or lst).get('style', 'list')}/{(tag or lst).get('anchor', '')}: ink={bb} frame_hit={hit}")
rec("T4-8 both canvases x frame off / on x tag_a / tag_b x 4 corners + Arabic + long text + list: ink >= 48 px from every edge, zero overlap with the frame plate, no warning",
    not bad_n, "; ".join(bad_n[:3]))
W, H = CV["reels"]
t4_warn_reset(); (on_i, off_i), _ = quiet(lambda: (t4_nameplate_items(_np_job("reels", True, {"on": True, "style": "tag_b"}), 10), t4_nameplate_items(_np_job("reels", False, {"on": True, "style": "tag_b"}), 10)))
rec("T4-8 frame on shifts the tag inward (same sprite, further from the corner); frame off = exactly the 48 px margin",
    on_i[0].cx > off_i[0].cx and on_i[0].cy > off_i[0].cy and _ink(off_i[0], W, H).getbbox()[:2] == (48, 48), f"{on_i[0].cx, on_i[0].cy} vs {off_i[0].cx, off_i[0].cy}")
it_a = quiet(t4_nameplate_items, _np_job("reels", False, {"on": True, "style": "tag_a", "start": 2, "hold": 3}), 10.0)[0][0]
it_b = quiet(t4_nameplate_items, _np_job("reels", False, {"on": True, "style": "tag_a", "anchor": "bottom-right"}), 10.0)[0][0]
it_l = quiet(t4_nameplate_items, _np_job("reels", False, None, {"on": True, "start": 1}), 6.0)[0]
it_n = quiet(t4_nameplate_items, _np_job("reels", False, {"on": True, "anim": "pop", "anim_dur": 0.9}), 10.0)[0][0]
rec("T4-8 timing + animation: start / hold -> window; default hold 5 s; list lasts to the video end (no fade-out); 'auto' slides in from its own side; explicit anim / dur kept",
    (it_a.start, it_a.end) == (2.0, 5.0) and it_a.anim == "slide_right" and it_b.anim == "slide_left" and (it_b.start, it_b.end) == (0.0, 5.0)
    and len(it_l) == 2 and all((i.start, i.end, i.out) == (1.0, 6.0, False) for i in it_l) and it_n.anim == "pop" and abs(it_n.dur - 0.9) < 1e-9, f"{it_a.anim} {it_b.anim} {[(i.start, i.end, i.out) for i in it_l]}")
(ctmp / "t.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nhello\n\n2\n00:00:03,000 --> 00:00:04,000\nopen the project now\n", encoding="utf-8")
cap = [{"srt": str(ctmp / "t.srt"), "t4_style": "pill", "ref": "canvas", "mode": "phrase"}]
t4_warn_reset(); ok_t, w1 = quiet(t4_nameplate_items, dict(_np_job("reels", False, {"on": True, "trigger": "open the project", "hold": 2}), captions=cap), 10.0)
t4_warn_reset(); no_t, w2 = quiet(t4_nameplate_items, dict(_np_job("reels", False, {"on": True, "trigger": "never said"}), captions=cap), 10.0)
t4_warn_reset(); late, w3 = quiet(t4_nameplate_items, _np_job("reels", False, {"on": True, "start": 99}), 10.0)
rec("T4-8 trigger phrase found -> starts at that cue; not found (no start) -> skipped with one warning; start after the video end -> skipped",
    len(ok_t) == 1 and (ok_t[0].start, ok_t[0].end) == (3.0, 5.0) and not w1 and no_t == [] and len(w2) == 1 and late == [] and len(w3) == 1, f"{w1} {w2} {w3}")
t4_warn_reset(); r, w = quiet(t4_nameplate_items, _np_job("reels", False, {"on": True, "icon": "banana", "font": "/no/font.ttf", "name": "", "role": "Dev"}), 10.0)
r0 = quiet(t4_nameplate_items, _np_job("reels", False, {"on": True, "name": "-", "role": "-"}), 10.0)[0]
r1 = quiet(t4_nameplate_items, {"t4": t4_cfg({"nameplate": {"on": True}})}, 10.0)[0]
r2 = quiet(t4_nameplate_items, _np_job("reels", False), 10.0)[0]
rec("T4-8 never raises: unknown icon + missing font -> one warning each, still drawn; empty name + role -> skipped; no canvas -> []; both off -> []",
    len(r) == 1 and len(w) == 2 and r0 == [] and r1 == [] and r2 == [], f"{w}")
t4_warn_reset(); two, w = quiet(t4_nameplate_items, _np_job("reels", False, {"on": True, "style": "tag_a", "anchor": "bottom-left"}, {"on": True}), 10.0)
rec("T4-8 two modules in the same corner -> an overlap warning (never silent)", len(two) == 3 and any("overlap" in x for x in w), f"{w}")
rec("T4-8 render.build_items: tag + list drawn once through the T4 hook; frame plate unchanged by the nameplate (still its own part)",
    len([i for i in quiet(build_items, dict(job_for(ctmp / "none.mp4", "youtube", "fill"), t4=_np_job("youtube", True, {"on": True}, {"on": True})["t4"]), 10.0)[0]
         if i.sprite.info.get("panel") or i.sprite.info.get("rows") is not None]) == 2          # tag + list (the laptop sprite has no info key)
    and [n for n, _ in t4mod.T4_FG_PARTS] == ["frame"])
def ask_np(fn, ans):
    it = itertools.chain(ans, itertools.repeat("")); old = builtins.input; builtins.input = lambda *_: next(it)
    try: return quiet(fn)[0]
    finally: builtins.input = old
D.clear(); n0 = ask_np(t4_ask_nameplate, ["n"]); l0 = ask_np(t4_ask_corner_list, ["n"])
D.clear(); n1 = ask_np(t4_ask_nameplate, ["y", "2", "Sara Ali", "Designer", "2", "red", "4", "1", "0:05", "3", "pop", "0.3"])
D.clear(); n2 = ask_np(t4_ask_nameplate, ["y"])
D.clear(); l1 = ask_np(t4_ask_corner_list, ["y", "Web", "cloud|Cloud", "-", "1", "2", "red", "y", "slide_up", "0.2"])
D.clear()
rec("T4-8 question groups: n -> {'on': False}; tag answers -> style / name / role / icon / colour / corner / start + hold / anim; Enter = tag_a defaults; list rows + corners + whole video",
    n0 == {"on": False} and l0 == {"on": False} and n1["style"] == "tag_b" and n1["name"] == "Sara Ali" and n1["role"] == "Designer" and n1["icon"] == "code" and n1["color"] == "#ff0000"
    and n1["anchor"] == "bottom-right" and n1["start"] == 5.0 and n1["hold"] == 3.0 and n1["anim"] == "pop" and n1["anim_dur"] == 0.3
    and n2["style"] == "tag_a" and n2["name"] == T4_NAMEPLATE["name"] and n2["anchor"] == "bottom-left" and n2["icon"] == "code"
    and l1["rows"] == ["Web", "cloud|Cloud"] and l1["icon"] == "" and l1["anchor"] == "top-right" and l1["color"] == "#ff0000" and l1["start"] == 0.0 and l1["anim"] == "slide_up",
    f"{n1} {l1}")
# ---- T4-9 tiles: logo glass tiles in a grid + connector, staggered pop-in, fade-out together, placeholder -----------------------------------
from PIL import ImageDraw                                                    # noqa: E402
from mt.anim import anim_state                                               # noqa: E402
from mt.render import render_still                                           # noqa: E402
from mt.templates.t4.tiles import TileItem, t4_ask_tiles, t4_tile_sprite, t4_tiles_cfg, t4_tiles_items   # noqa: E402
ttmp = Path(tempfile.mkdtemp(prefix="t4til_"))
try:
    LG = []
    for nm, (w, h), col in (("sq", (300, 300), (240, 96, 40)), ("wide", (600, 200), (40, 110, 255)), ("tall", (200, 400), (250, 205, 40)), ("round", (300, 300), (30, 215, 235))):
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse((0, 0, w - 1, h - 1), fill=col + (255,)) if nm == "round" else ImageDraw.Draw(im).rectangle((0, 0, w - 1, h - 1), fill=col + (255,))
        im.save(ttmp / f"{nm}.png"); LG.append(str(ttmp / f"{nm}.png"))
    (ttmp / "broken.png").write_text("not an image", encoding="utf-8")
    def tj(cv, fo, groups, **extra):
        return dict({"canvas": list(CV[cv]), "t4": t4_cfg({"canvas_mode": cv, "frame": {"on": fo}, "tiles": groups})}, **extra)
    def ink_rect(it, W, H):
        full = Image.new("L", (W, H), 0)
        full.paste(it.sprite.getchannel("A").point(lambda v: 255 if v > INK_THR else 0), (int(it.cx - it.sprite.width / 2), int(it.cy - it.sprite.height / 2)))
        return full
    a = t4_tiles_cfg([{"images": LG + [5, None, ""], "cols": "3", "gap": -4, "size": "x", "anchor": "7", "xy": ["10%", 20], "border": "zz", "anim": "bogus",
                       "stagger": 99, "connector": {"points": ["group-bottom", "30%,50%", [1, "x"], "bad"], "end_dot": "both"}, "extra": 1}, "junk", 5, {"images": "x"}])
    b, c, d = t4_tiles_cfg({"on": False}), t4_tiles_cfg({"images": [LG[0]]}), t4_tiles_cfg({"on": True, "groups": [{"images": [LG[0]]}]})
    g = a[0]
    rec("T4-9 t4_tiles_cfg: list / single group / {on, groups}; junk dropped; cols / gap / size / anchor preset / xy / border / anim / stagger fall back; connector points cleaned; extras kept; never raises",
        len(a) == 2 and g["images"] == LG and g["cols"] == 3 and g["gap"] == 18.0 and g["size"] == 150.0 and g["anchor"] == "bottom-left" and g["xy"] == ["10%", 20.0]
        and g["border"] == "#c4d6ef" and g["anim"] == "pop" and g["stagger"] == 0.12 and g["connector"]["points"] == ["group-bottom", ["30%", "50%"]] and g["connector"]["end_dot"] == "both"
        and g["extra"] == 1 and a[1]["images"] == [] and b == [] and len(c) == 1 and c[0]["anchor"] == "left" and len(d) == 1 and t4_tiles_cfg(None) == [] and t4_tiles_cfg("x") == [],
        f"{ {k: g[k] for k in ('cols', 'gap', 'size', 'anchor', 'xy', 'connector', 'anim', 'stagger')} }")
    rec("T4-9 t4_cfg keeps cfg['t4']['tiles'] as a list of groups (default stays {'on': False})", t4_cfg({"tiles": [{"images": ["a.png"]}]})["tiles"] == [{"images": ["a.png"]}] and t4_cfg({})["tiles"] == {"on": False})
    t4_warn_reset(); sps, w = quiet(lambda: [t4_tile_sprite(p, 150, "#c4d6ef", 1.0) for p in LG])
    pm = [np.asarray(s_.getchannel("A")) for s_ in sps]
    ox, oy = sps[0].info["origin"]
    def logo_box(s_, col):
        arr = np.asarray(s_.convert("RGB"), int); ys, xs = np.where(np.abs(arr - np.array(col)).sum(axis=2) < 40)
        return (xs.min() - ox, ys.min() - oy, xs.max() + 1 - ox, ys.max() + 1 - oy)
    bw, bt = logo_box(sps[1], (40, 110, 255)), logo_box(sps[2], (250, 205, 40))
    rec("T4-9 tile sprites: same size for every logo, logo fitted (wide = 90 px wide, tall = 90 px tall) and centred in the 150 px tile, no warning",
        len({s_.size for s_ in sps}) == 1 and abs((bw[2] - bw[0]) - 90) <= 2 and abs((bt[3] - bt[1]) - 90) <= 2 and abs((bw[0] + bw[2]) / 2 - 75) <= 1.5 and abs((bw[1] + bw[3]) / 2 - 75) <= 1.5
        and abs((bt[0] + bt[2]) / 2 - 75) <= 1.5 and abs((bt[1] + bt[3]) / 2 - 75) <= 1.5 and not w, f"{bw} {bt} {w}")
    t4_warn_reset(); r, w = quiet(lambda: (t4_tile_sprite("/no/such/x.png", 150), t4_tile_sprite(str(ttmp / "broken.png"), 150), t4_tile_sprite("", 150), t4_tile_sprite("/no/such/x.png", 150)))
    gray = np.asarray(r[0].convert("RGB"), int)[oy + 60:oy + 90, ox + 60:ox + 90]
    rec("T4-9 missing / unreadable / empty path -> gray placeholder tile (same size) + one warning per distinct file", all(x.size == sps[0].size for x in r) and len(w) == 3 and "x.png" in w[0]
        and abs(gray[..., 0] - gray[..., 2]).max() < 40, f"{w}")
    bad_t = []
    for cv, (W, H) in CV.items():
        s = min(W, H) / 1080.0
        for fo in (False, True):
            fa = t4_frame_plate(W, H, t4_frame_cfg({"on": True})).getchannel("A").point(lambda v: 255 if v > FRAME_THR else 0) if fo else None
            for an in ("top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right"):
                t4_warn_reset(); items, w = quiet(t4_tiles_items, tj(cv, fo, [{"images": LG, "anchor": an, "connector": {"points": ["group-bottom", "30%,60%"]}}]), 10.0)
                if len(items) != 5 or w:
                    bad_t.append(f"{cv}/{fo}/{an}: {len(items)} items warn={w}"); continue
                for it in items[:4]:
                    bb = ink_rect(it, W, H).getbbox()
                    hit = fa is not None and ImageChops.multiply(ink_rect(it, W, H), fa).getbbox() is not None
                    if not (bb[0] >= 47 and bb[1] >= 47 and W - bb[2] >= 47 and H - bb[3] >= 47) or hit:
                        bad_t.append(f"{cv}/{fo}/{an}: ink={bb} frame_hit={hit}")
    rec("T4-9 4 logos + connector, both canvases x frame off / on x all 9 anchors: 5 items, no warning, every tile >= 48 px from the edges, zero overlap with the frame plate", not bad_t, "; ".join(bad_t[:3]))
    items = quiet(t4_tiles_items, tj("youtube", False, [{"images": LG, "start": 1, "hold": 4, "stagger": 0.2, "anim_dur": 0.3, "connector": {"points": ["group-right", "70%,60%"]}}]), 10.0)[0]
    tl, cn = items[:4], items[4]
    xs, ys = sorted({round(i.cx) for i in tl}), sorted({round(i.cy) for i in tl})
    rec("T4-9 grid + timing: 2 columns x 2 rows (gap 18), tiles start 1.0 / 1.2 / 1.4 / 1.6 s (t4_stagger), connector after the last one, ALL end together at 5.0 s",
        len(xs) == 2 and len(ys) == 2 and xs[1] - xs[0] == 168 and ys[1] - ys[0] == 168 and [round(i.start, 3) for i in tl] == [1.0, 1.2, 1.4, 1.6] and abs(cn.start - 1.9) < 1e-6
        and {i.end for i in items} == {5.0} and all(isinstance(i, TileItem) and i.anim == "t4_pop" and i.out for i in tl) and cn.anim == "fade", f"{xs} {ys} {[i.start for i in items]}")
    probe = tl[0]
    sts = [anim_state(probe.anim, probe.progress(t), 1920, 1080) for t in (1.0, 1.1, 1.3, 3.0, 4.85, 4.95, 4.999)]
    rec("T4-9 TileItem: entry = fade + scale pop from 0, hold = fully shown, exit = PURE fade (scale stays 1) ending at 0; the exit mirrors the entry length",
        sts[0][0] == 0 and 0 < sts[1][0] <= 1 and sts[1][3] != 1.0 and sts[2] == (1.0, 0, 0, 1.0, 0.0, None) and sts[3] == (1.0, 0, 0, 1.0, 0.0, None)
        and 0 < sts[4][0] < 1 and sts[4][3] == 1.0 and sts[5][0] < sts[4][0] and sts[6][0] < 0.05, f"{sts}")
    rec("T4-9 anim.py: other animations unchanged (fade / pop / slide_up / none / unknown spot checks)",
        anim_state("fade", 0.5, 1080, 1920)[0] == 1 - 0.5 ** 3 and anim_state("pop", 0.5, 1080, 1920)[:3] == (1.0, 0, 0) and anim_state("slide_up", 1.0, 1080, 1920) == (1.0, 0, 0, 1.0, 0.0, None)
        and anim_state("none", 0.2, 1080, 1920) == (1.0, 0, 0, 1.0, 0.0, None) and anim_state("zzz", 0.2, 1080, 1920) == (1.0, 0, 0, 1.0, 0.0, None))
    it_f = quiet(t4_tiles_items, tj("reels", False, [{"images": LG[:2], "anim": "fade", "start": 0}]), 6.0)[0]
    it_n = quiet(t4_tiles_items, tj("reels", False, [{"images": LG[:2], "anim": "none"}]), 6.0)[0]
    rec("T4-9 other anims: 'fade' -> plain Item (fade in / out), 'none' -> static; default hold 5 s", all(type(i) is not TileItem and i.anim == "fade" for i in it_f) and all(i.anim == "none" for i in it_n)
        and {i.end for i in it_f} == {5.0})
    # connector: tokens + clamping + glowing end dot
    W, H = CV["youtube"]
    it = quiet(t4_tiles_items, tj("youtube", False, [{"images": LG, "anchor": "top-left", "connector": {"points": ["group-bottom", [5, 5000], "999%,50%"], "end_dot": True}}]), 10.0)[0]
    bb = ink_rect(it[4], W, H).getbbox()
    rec("T4-9 connector: points far outside the canvas are clamped so the whole polyline ink (glow + end dot included) stays inside the 48 px safe area",
        bb[0] >= 47 and bb[1] >= 47 and W - bb[2] >= 47 and H - bb[3] >= 47, f"{bb}")
    it = quiet(t4_tiles_items, tj("youtube", False, [{"images": LG, "anchor": "top-left", "connector": {"points": ["group-bottom", "60%,90%"], "end_dot": False}}]), 10.0)[0]
    gx, gb = (it[0].cx + it[1].cx) / 2.0, max(i.cy for i in it[:4]) + 75
    cs = it[4].sprite
    yy, xx = int(gb - (it[4].cy - cs.height / 2.0)), int(gx - (it[4].cx - cs.width / 2.0))
    px = np.asarray(cs.getchannel("A"))[yy - 3:yy + 4, xx - 3:xx + 4].max()
    rec("T4-9 connector token 'group-bottom' = the bottom centre of the tile group (the line starts exactly there)", px > 200, f"max alpha around ({gx:.0f},{gb:.0f}) = {px}")
    # xy
    for cv, (W, H) in CV.items():
        itx = quiet(t4_tiles_items, tj(cv, False, [{"images": LG, "xy": ["50%", "50%"]}, {"images": LG[:1], "xy": [-500, 99999], "size": 100}]), 10.0)[0]
        g1 = [i for i in itx[:4]]
        gcx, gcy = sum(i.cx for i in g1) / 4.0, sum(i.cy for i in g1) / 4.0
        b2 = ink_rect(itx[4], W, H).getbbox()
        rec(f"T4-9 xy on {cv}: group centred on 50%,50%; an xy far outside is clamped inside the safe area", abs(gcx - W / 2) < 2 and abs(gcy - H / 2) < 2 and b2[0] >= 47 and b2[1] >= 47 and W - b2[2] >= 47 and H - b2[3] >= 47, f"{gcx, gcy} {b2}")
    t4_warn_reset(); r, w = quiet(t4_tiles_items, tj("reels", False, [{"images": [LG[0], "/no/such/a.png", "/no/such/a.png"]}]), 10.0)
    t4_warn_reset(); r1, w1 = quiet(t4_tiles_items, tj("reels", False, [{"images": []}]), 10.0)
    t4_warn_reset(); r2, w2 = quiet(t4_tiles_items, dict(tj("reels", False, [{"images": LG, "trigger": "never said"}]), captions=[]), 10.0)
    t4_warn_reset(); r3, w3 = quiet(t4_tiles_items, tj("reels", False, [{"images": LG, "start": 50}]), 10.0)
    r4 = quiet(t4_tiles_items, {"t4": t4_cfg({"tiles": [{"images": LG}]})}, 10.0)[0]
    r5 = quiet(t4_tiles_items, tj("reels", False, {"on": False}), 10.0)[0]
    rec("T4-9 never raises: missing PNG -> still 3 tiles + ONE warning; no images / trigger not found / start after the end -> skipped with a warning; no canvas -> []; module off -> []",
        len(r) == 3 and len(w) == 1 and r1 == [] and len(w1) == 1 and r2 == [] and len(w2) == 1 and r3 == [] and len(w3) == 1 and r4 == [] and r5 == [], f"{w} {w1} {w2} {w3}")
    t4_warn_reset(); r, w = quiet(t4_tiles_items, tj("reels", False, [{"images": LG[:2], "anchor": "left"}, {"images": LG[2:], "anchor": "left"}]), 10.0)
    rec("T4-9 two groups on the same anchor -> an overlap warning (never silent)", len(r) == 4 and any("overlap" in x for x in w), f"{w}")
    jb = dict(job_for(ctmp / "none.mp4", "youtube", "fill"), t4=tj("youtube", True, [{"images": LG}])["t4"])
    rec("T4-9 render.build_items: the T4 hook draws the tiles (4 tile items) next to captions / nameplate", len([i for i in quiet(build_items, jb, 10.0)[0] if isinstance(i, TileItem)]) == 4)
    def ask_t(ans):
        it_ = itertools.chain(ans, itertools.repeat("")); old = builtins.input; builtins.input = lambda *_: next(it_)
        try: return quiet(t4_ask_tiles)[0]
        finally: builtins.input = old
    D.clear(); q0 = ask_t(["n"])
    D.clear(); q1 = ask_t(["y", LG[0], LG[1], "", "3", "120", "1", "y", "group-bottom; 30%,50%", "y", "1", "0:02", "4", "fade"])
    D.clear(); q2 = ask_t(["y", "/nope.png", LG[2], "", "", "", "", "n", "2", "open the project", "", ""])
    D.clear()
    rec("T4-9 question group: n -> {'on': False}; answers -> one group (images, cols, size, anchor, connector, start + hold, anim); a missing path is re-asked; Enter = defaults",
        q0 == {"on": False} and len(q1) == 1 and q1[0]["images"] == LG[:2] and q1[0]["cols"] == 3 and q1[0]["size"] == 120.0 and q1[0]["anchor"] == "top-left"
        and q1[0]["connector"]["points"] == ["group-bottom", ["30%", "50%"]] and q1[0]["connector"]["end_dot"] == "both" and q1[0]["start"] == 2.0 and q1[0]["hold"] == 4.0 and q1[0]["anim"] == "fade"
        and q2[0]["images"] == [LG[2]] and q2[0]["cols"] == 2 and q2[0]["anchor"] == "left" and "connector" not in q2[0] and q2[0]["trigger"] == "open the project" and q2[0]["anim"] == "pop", f"{q1} {q2}")
    # real still, both canvases: only the tile + connector area changes, the rest of the video is untouched
    bad_s = []
    for cv, (W, H) in CV.items():
        mp4 = ttmp / f"v_{cv}.mp4"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=25:d=2", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        res = {}
        for nm, grp in (("off", []), ("on", [{"images": LG, "anchor": "top-left", "inset_x": 30, "inset_y": 60, "connector": {"points": ["group-bottom", "40%,60%"]}}])):
            job = dict(job_for(mp4, cv, "fill"), t4=t4_cfg({"canvas_mode": cv, "fit": "fill", "tiles": grp}), output=str(ttmp / "o.mp4"))
            out = ttmp / f"s_{cv}_{nm}.png"; quiet(render_still, job, str(out), 1.5)
            res[nm] = np.asarray(Image.open(out).convert("RGB"), int) if out.is_file() else None
        if res["off"] is None or res["on"] is None:
            bad_s.append(f"{cv}: still failed"); continue
        diff = np.abs(res["on"] - res["off"]).max(axis=2) > 2
        ys_, xs_ = np.where(diff)
        if not (diff.sum() > 8000 and xs_.min() >= 40 and ys_.min() >= 40 and xs_.max() <= W * 0.45 and ys_.max() <= H * 0.65 and not diff[:, int(W * 0.5):].any()):
            bad_s.append(f"{cv}: changed_px={diff.sum()} box=({xs_.min() if xs_.size else 0},{ys_.min() if ys_.size else 0})-({xs_.max() if xs_.size else 0},{ys_.max() if ys_.size else 0})")
    rec("T4-9 --still on both canvases (4 logos + connector): tiles drawn over the video, the right half of the canvas is byte-identical to the tile-less render", not bad_s, "; ".join(bad_s))
finally:
    shutil.rmtree(ttmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)
