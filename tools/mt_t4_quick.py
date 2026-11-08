"""Template 4 quick check (fast): python tools/mt_t4_quick.py
P1: compile + imports + cfg normaliser + 1.5 s --job renders on BOTH canvases (size / duration / audio).
P3 ('T4-3'): timing.py unit checks (t4_time / t4_stagger / t4_ask_when).
P9 ('T4-8'): nameplate lower third (cfg, items, geometry on both canvases, timing, animation, Arabic, question group, --still + real encode).
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
# ---- T4-8 nameplate 'lower_third' (unit checks + real --still / video pixel checks; the look is checked by eye - see T4_NOTES) -----------
from mt.captions import find_trigger                                        # noqa: E402
from mt.draw import Item                                                    # noqa: E402
from mt.templates.t4.nameplate import G as NG, T4_NAMEPLATE, t4_ask_nameplate, t4_nameplate_cfg, t4_nameplate_items   # noqa: E402
ntmp = Path(tempfile.mkdtemp(prefix="t4np_"))
def ncfg(cv, **kw):
    return {"canvas": list(CV[cv]), "captions": [], "t4": t4_cfg({"canvas_mode": cv, "nameplate": dict({"on": True, "font": default_font()}, **kw)})}
def nbox(it):
    return (it.cx - it.sprite.width / 2.0, it.cy - it.sprite.height / 2.0, it.cx + it.sprite.width / 2.0, it.cy + it.sprite.height / 2.0)
def white_x(spr, rows=None):
    a = np.asarray(spr.convert("RGBA"), int)
    a = a if rows is None else a[rows[0]:rows[1]]
    xs = np.where(((a[..., :3] >= 245).all(axis=2) & (a[..., 3] >= 245)).any(axis=0))[0]
    return (int(xs.min()), int(xs.max())) if len(xs) else None
try:
    a = t4_nameplate_cfg(None)
    b = t4_nameplate_cfg({"on": 1, "name1": 5, "roles": ["x", ("phone", "Y"), {"text": "z"}, {}, 7], "color": "zzz", "anim": "bogus", "anim_dur": "q",
                          "badge_icon": "NONE", "extra": 1, "start": "0:03", "hold": 2})
    c = t4_nameplate_cfg({"on": True, "trigger": "hello"})
    junk_n = [None, 5, "x", [], {"roles": "no", "anim_dur": [1], "color": 3, "tagline": 9}]
    rec("T4-8 t4_nameplate_cfg: defaults (R1 text), junk -> defaults, roles x3 (str / pair / dict), extras + timing keys kept, start 0 only when no start / trigger",
        a["on"] is False and a["name1"] == "AHMED" and len(a["roles"]) == 3 and a["style"] == "lower_third" and b["on"] is True and b["name1"] == "AHMED"
        and [r["text"] for r in b["roles"]] == ["x", "Y", "z"] and b["roles"][1]["icon"] == "phone" and b["color"] == "#19D3FF" and b["anim"] == "slide_left"
        and b["anim_dur"] == 0.5 and b["badge_icon"] == "" and b["extra"] == 1 and b["start"] == "0:03" and b["hold"] == 2
        and t4_nameplate_cfg({"on": True})["start"] == 0 and "start" not in c and all(t4_nameplate_cfg(j)["name1"] for j in junk_n), f"{b}")
    t4_warn_reset()
    r, w = quiet(lambda: [t4_nameplate_items(j, 5.0) for j in ({}, {"t4": 5}, {"t4": {"nameplate": {"on": True}}}, {"canvas": "x", "t4": {"nameplate": {"on": True}}})])
    rec("T4-8 items: module off / no t4 / no canvas / junk canvas -> [] (never raises; the no-canvas warning prints once)", r == [[]] * 4 and len(w) == 1, f"{r} {w}")
    bad_i = []
    for cv, (W, H) in CV.items():
        its = t4_nameplate_items(ncfg(cv), 10.0)
        its4 = t4_nameplate_items(ncfg(cv, hold=20), 4.0)
        notag = t4_nameplate_items(ncfg(cv, tagline=""), 10.0)
        onlytag = t4_nameplate_items(ncfg(cv, name1="", name2="", roles=[]), 10.0)
        none = t4_nameplate_items(ncfg(cv, name1="", name2="", roles=[], tagline=""), 10.0)
        if not (len(its) == 2 and all(isinstance(i, Item) and i.anim == "slide_left" and i.out and (i.start, i.end) == (0.0, 6.0) for i in its)
                and its4[0].end == 4.0 and len(notag) == 1 and notag[0].sprite.width < W and len(onlytag) == 1 and onlytag[0].sprite.width == W and none == []):
            bad_i.append(f"{cv}: {[(i.anim, i.start, i.end) for i in its]} {len(notag)} {len(onlytag)} {len(none)}")
    rec("T4-8 two Items (bar + card, slide_left in / out, 0-6 s default hold, clamped to the video), tagline '' -> card only, no name / roles -> bar only, nothing -> []",
        not bad_i, "; ".join(bad_i))
    bad_g = []
    for cv, (W, H) in CV.items():
        s = min(W, H) / 1080.0
        for nm, kw in (("default", {}), ("long", {"name1": "ABDELRAHMAN", "name2": "MOHAMED ELSAYED", "tagline": "BUILDING RELIABLE DIGITAL EXPERIENCES FOR PEOPLE AND TEAMS WHO CARE ABOUT SOFTWARE QUALITY",
                                                  "roles": [{"icon": "cloud", "text": "SENIOR CLOUD SOLUTIONS ARCHITECT"}, {"icon": "shield", "text": "CYBER SECURITY CONSULTANT AND TRAINER"}]})):
            bar, card = t4_nameplate_items(ncfg(cv, **kw), 10.0)
            px, py, pw, ph = card.sprite.info["panel"]
            x0, y0, x1, y1 = nbox(card)
            L, R, T, B = x0 + px, x0 + px + pw, y0 + py, y0 + py + ph
            bx0, by0, bx1, by1 = nbox(bar)
            band_top = by0 + bar.sprite.info["top"]
            tw = white_x(bar.sprite, (int(bar.sprite.info["top"]) + 6, int(bar.sprite.info["line_y"]) - 6))
            cw = white_x(card.sprite)
            lim = (L - NG["tag_gap"] * s + 2) if W > H else W - NG["safe"] * s + 2
            ok = (L >= NG["safe"] * s - 1 and R <= W - NG["safe"] * s + 1 and T >= 0 and B <= H - NG["safe"] * s and x0 >= 0 and x1 <= W and y0 >= 0 and y1 <= H
                  and (bx0, bx1) == (0, W) and by1 <= H and (R - L) <= (W - 2 * NG["safe"] * s) + 1
                  and tw is not None and bx0 + tw[1] <= lim and bx0 + tw[0] >= NG["safe"] * s
                  and cw is not None and px - 1 <= cw[0] and cw[1] <= px + pw + 1
                  and (B <= band_top if W < H else (W > H and (R - L) <= 0.52 * W + 1)))
            if not ok:
                bad_g.append(f"{cv}/{nm}: panel x {L:.0f}-{R:.0f} y {T:.0f}-{B:.0f} band_top {band_top:.0f} bar text {tw} card text {cw} lim {lim:.0f}")
    rec("T4-8 geometry on BOTH canvases (default + long text): card inside the 48 px margin and the canvas, reels = card above the bar, youtube = card <= 52 % of W and the tagline "
        "stops before it, every white text pixel inside its panel / before the limit (reflow, no overflow)", not bad_g, "; ".join(bad_g[:2]))
    srt = ntmp / "c.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello everyone\n\n2\n00:00:02,500 --> 00:00:04,000\nso open the project now\n", encoding="utf-8")
    from mt.captions import parse_srt
    tcue = find_trigger(parse_srt(str(srt)), "open the project")
    cfg = dict(ncfg("youtube", trigger="open the project", hold=2), captions=[{"srt": str(srt)}])
    t4_warn_reset(); its, w1 = quiet(t4_nameplate_items, cfg, 10.0)
    cfg2 = dict(ncfg("youtube", trigger="never said", start=1), captions=[{"srt": str(srt)}])
    t4_warn_reset(); its2, w2 = quiet(t4_nameplate_items, cfg2, 10.0)
    cfg3 = dict(ncfg("youtube", trigger="never said"), captions=[{"srt": str(srt)}])
    t4_warn_reset(); its3, w3 = quiet(t4_nameplate_items, cfg3, 10.0)
    cfg4 = dict(ncfg("youtube", start=12), captions=[])
    t4_warn_reset(); its4, w4 = quiet(t4_nameplate_items, cfg4, 10.0)
    rec("T4-8 timing via t4_time: spoken phrase -> its cue time + hold; phrase missing + start -> start (1 warning); missing and no start / start after the end -> [] (1 warning each)",
        tcue is not None and [(i.start, i.end) for i in its] == [(tcue, tcue + 2.0)] * 2 and not w1 and [i.start for i in its2] == [1.0, 1.0] and len(w2) == 1
        and its3 == [] and len(w3) == 1 and its4 == [] and len(w4) == 1, f"{tcue} {[(i.start, i.end) for i in its]} {w1} {w2} {w3} {w4}")
    from mt.anim import anim_state
    f_ = t4_nameplate_items(ncfg("reels", anim="fade", anim_dur=0.3), 10.0)
    g_ = t4_nameplate_items(ncfg("reels", anim="bogus", start=1, anim_dur=0.4), 10.0)
    i = g_[1]
    st_mid = anim_state(i.anim, i.progress(i.start + 0.1), 1080, 1920)
    rec("T4-8 animation: default / unknown -> slide_left (in AND out, comes from the right), 'fade' honoured, progress 0 -> 1 over anim_dur and back to 0 at the end",
        f_[0].anim == "fade" and f_[0].dur == 0.3 and g_[0].anim == "slide_left" and i.dur == 0.4 and abs(i.progress(i.start)) < 1e-9 and abs(i.progress(i.start + 0.4) - 1) < 1e-9
        and abs(i.progress(i.end)) < 1e-9 and st_mid[1] > 0 and 0 < st_mid[0] < 1, f"{st_mid}")
    bad_r = []
    for cv in CV:
        for nm, n1, n2 in (("en", "AHMED", "IBRAHIM"), ("ar", "أحمد", "إبراهيم")):
            t4_warn_reset()
            its, w = quiet(t4_nameplate_items, ncfg(cv, name1=n1, name2=n2, tagline="نبني تجارب رقمية" if nm == "ar" else "BUILDING DIGITAL EXPERIENCES.",
                                                 tagline_highlight="رقمية" if nm == "ar" else "DIGITAL", roles=[{"icon": "gear", "text": "مطور ويب" if nm == "ar" else "WEB"}]), 10.0)
            if len(its) != 2 or w:
                bad_r.append(f"{cv}/{nm}: {len(its)} items {w}"); continue
            spr = its[1].sprite
            a_ = np.asarray(spr.convert("RGBA"), int)
            py_ = spr.info["panel"][1]
            row = a_[int(py_ + 10):int(py_ + NG["ul_y"] * min(CV[cv]) / 1080.0 - 6)]
            cy_ = np.where(((row[..., 0] < 90) & (row[..., 1] > 170) & (row[..., 2] > 220) & (row[..., 3] >= 240)))[1]
            wh_ = np.where(((row[..., :3] >= 245).all(axis=2) & (row[..., 3] >= 245)))[1]
            if not (cy_.size > 30 and wh_.size > 30 and ((cy_.mean() < wh_.mean()) if nm == "ar" else (cy_.mean() > wh_.mean()))):
                bad_r.append(f"{cv}/{nm}: cyan {cy_.size} px mean {cy_.mean() if cy_.size else None} white {wh_.size} px mean {wh_.mean() if wh_.size else None}")
    rec("T4-8 English + Arabic on both canvases: no warnings, English name = white then cyan (left to right), Arabic = white on the RIGHT, cyan to its left", not bad_r, "; ".join(bad_r))
    t4_warn_reset(); r, w = quiet(t4_nameplate_items, ncfg("youtube", roles=[{"icon": "banana", "text": "X"}, {"icon": "code", "text": "Y"}], badge_icon="nope", font="/no/such.ttf"), 10.0)
    rec("T4-8 unknown role / badge icon -> one warning each + drawn without that icon; missing font file -> default font; never raises", len(r) == 2 and len(w) == 2 and "banana" in w[0] and "nope" in w[1], f"{w}")
    cfg = {"canvas": [1080, 1920], "t4": t4_cfg({"nameplate": {"on": True}, "frame": {"on": True}}), "video": str(ntmp / "none.mp4")}
    (ntmp / "bk").mkdir()
    quiet(t4mod.t4_build_static_layers, cfg, str(ntmp / "bk"))
    cfg5 = {"canvas": [1080, 1920], "t4": t4_cfg({"nameplate": {"on": True}}), "video": str(ntmp / "none.mp4")}
    quiet(t4mod.t4_build_static_layers, cfg5, str(ntmp / "bk"))
    pl = np.asarray(Image.open(cfg["_t2_fg"]).convert("RGBA"))[..., 3] if cfg.get("_t2_fg") else None
    its = t4mod.t4_build_items(dict(cfg, t4=t4_cfg({"nameplate": {"on": True, "font": default_font()}})), 10.0, [], None, None)
    rec("T4-8 not baked: nameplate alone -> no foreground plate; with the frame the plate keeps its centre transparent (no card pixels); t4_build_items returns the 2 Items",
        "_t2_fg" not in cfg5 and "nameplate" not in [n for n, _ in t4mod.T4_FG_PARTS] and pl is not None and pl[int(1920 * 0.18):int(1920 * 0.72), 216:864].max() == 0 and len(its) == 2, f"{len(its)}")
    def ask_np(ans):
        it = iter(ans); old = builtins.input; builtins.input = lambda *_: next(it)
        try: return quiet(t4_ask_nameplate)[0]
        finally: builtins.input = old
    from mt.common import D
    D.clear(); qn = ask_np(["n"])
    D.clear(); qy = ask_np(["y", "LINA", "-", "Designer", "3", "-", "", "", "", "Hello there", "there", "red", "1", "2", "5", "", "0.4"]); D.clear()
    rec("T4-8 question group: n -> {'on': False}; y + answers -> name / roles (icon asked only for kept rows) / badge / tagline / highlight / colour / t4_ask_when / anim",
        qn == {"on": False} and qy.get("on") is True and qy["name1"] == "LINA" and qy["name2"] == "" and qy["roles"] == [{"icon": "phone", "text": "Designer"}, {"icon": "gear", "text": "AI AUTOMATION"}]
        and qy["badge_icon"] == "code" and qy["tagline"] == "Hello there" and qy["tagline_highlight"] == "there" and qy["color"] == "#ff0000" and qy["start"] == 2.0 and qy["hold"] == 5.0
        and qy["anim"] == "slide_left" and qy["anim_dur"] == 0.4 and t4_nameplate_cfg(qy)["roles"] == qy["roles"], f"{qy}")
    # real --still: the plate-less video is untouched everywhere outside the two Items; both cards really drawn
    bad_s = []
    for cv, (W, H) in CV.items():
        mp4 = ntmp / f"v_{cv}.mp4"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=25:d=2", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        res = {}
        for nm, on in (("off", False), ("on", True)):
            job = dict(job_for(mp4, cv, "fill"), t4=t4_cfg({"canvas_mode": cv, "fit": "fill", "nameplate": {"on": on, "font": default_font()}}), output=str(ntmp / "o.mp4"))
            jp, out = ntmp / f"{cv}_{nm}.json", ntmp / f"{cv}_{nm}.png"
            jp.write_text(json.dumps(job), encoding="utf-8")
            r = subprocess.run([sys.executable, str(P / "montage.py"), "--still", "--job", str(jp), "--still-out", str(out), "--arabic-mode", "reshape"], cwd=str(ntmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
            res[nm] = np.asarray(Image.open(out).convert("RGB"), int) if r.returncode == 0 and out.is_file() else None
        if res["off"] is None or res["on"] is None:
            bad_s.append(f"{cv}: still failed"); continue
        ins = np.zeros((H, W), bool)
        for it in t4_nameplate_items(ncfg(cv), 10.0):
            b0 = nbox(it); ins[max(0, int(b0[1])):int(b0[3]) + 1, max(0, int(b0[0])):int(b0[2]) + 1] = True
        ch = np.abs(res["on"] - res["off"]).max(axis=2) > 2
        if ch[~ins].any() or ch[ins].sum() < 20000:
            bad_s.append(f"{cv}: outside-changed={int(ch[~ins].sum())} inside-changed={int(ch[ins].sum())}")
    rec("T4-8 --still on both canvases: card + bar drawn over the video, every pixel outside the two Items identical to the nameplate-less render", not bad_s, "; ".join(bad_s))
    # real encode: absent before the window, present inside, gone after (slide in / out happens at the window edges)
    bad_v = []
    for cv, (W, H) in CV.items():
        mp4 = ntmp / f"anim_{cv}.mp4"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x305070:s={W}x{H}:r=25:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(mp4)], check=True)
        def grab(path, t_):
            png = ntmp / "g.png"
            subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", t_, "-i", str(path), "-frames:v", "1", str(png)], check=True)
            return np.asarray(Image.open(png).convert("RGB"), float)
        frames = {}
        for nm, on in (("off", False), ("on", True)):
            job = dict(job_for(mp4, cv, "fill"), t4=t4_cfg({"canvas_mode": cv, "fit": "fill", "nameplate": {"on": on, "font": default_font(), "start": 0.5, "hold": 1.5, "anim_dur": 0.4}}), output=str(ntmp / f"an_{cv}_{nm}.mp4"))
            job.pop("preview", None)
            jp = ntmp / f"an_{cv}_{nm}.json"; jp.write_text(json.dumps(job), encoding="utf-8")
            r = subprocess.run([sys.executable, str(P / "montage.py"), "--job", str(jp), "--arabic-mode", "reshape"], cwd=str(ntmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
            frames[nm] = {t: grab(ntmp / f"an_{cv}_{nm}.mp4", t) for t in ("0.2", "1.0", "2.4")} if r.returncode == 0 else None
        if frames["on"] is None or frames["off"] is None:
            bad_v.append(f"{cv}: render failed"); continue
        cnt = {t: int((np.abs(frames["on"][t] - frames["off"][t]).max(axis=2) > 40).sum()) for t in ("0.2", "1.0", "2.4")}
        if not (cnt["0.2"] == 0 and cnt["2.4"] == 0 and cnt["1.0"] > 20000):
            bad_v.append(f"{cv}: changed px at 0.2 / 1.0 / 2.4 s = {cnt}")
    rec("T4-8 real encode on both canvases (start 0.5, hold 1.5): nothing at 0.2 s, card + bar at 1.0 s, nothing again at 2.4 s", not bad_v, "; ".join(bad_v))
finally:
    shutil.rmtree(ntmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)
