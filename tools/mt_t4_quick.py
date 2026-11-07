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
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)
