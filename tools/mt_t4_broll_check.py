"""B-roll (R4) check: python tools/mt_t4_broll_check.py   (run from the project root)
Both canvases: cfg, wipe mask, decor plate, items, real renders (fade + wipe: speaker -> b-roll -> speaker, decor on/off, audio continuous and byte-identical
to a render without b-roll), video media, --still, robustness. Writes out/t4/broll_{reels,youtube}[_wipe].png - LOOK at them."""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
import mt.templates                                                                       # noqa: E402,F401
from mt.common import FFMPEG, probe                                                       # noqa: E402
from mt.render import render_still                                                        # noqa: E402
from mt.templates.t4.broll import t4_broll_cfg, t4_broll_items, t4_broll_mask, t4_broll_plan   # noqa: E402
from mt.templates.t4.broll_decor import t4_broll_decor                                    # noqa: E402
from mt.templates.t4.cfg import t4_cfg                                                    # noqa: E402
from mt.templates.t4.warn import t4_warn_reset                                            # noqa: E402
rows = []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
def quiet(fn, *a):
    t4_warn_reset(); buf = io.StringIO()
    with contextlib.redirect_stdout(buf): r = fn(*a)
    return r, [l for l in buf.getvalue().splitlines() if "[!]" in l]
def ff(*a): subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *a], check=True)
CV = {"reels": (1080, 1920), "youtube": (1920, 1080)}
FPS, DUR = 25, 6.0
tmp = Path(tempfile.mkdtemp(prefix="t4broll_")); OUT = P / "out" / "t4"; OUT.mkdir(parents=True, exist_ok=True)
def BR(media, **k): return dict({"on": True, "media": str(media), "start": 1.0, "hold": 3.0}, **k)
def job(cv, br, video):
    W, H = CV[cv]; t4 = {"canvas_mode": cv, "fit": "fill"}
    if br is not None: t4["broll"] = br
    return {"template_id": 5, "video": str(video), "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"},
            "background": {"type": "color", "value": "#000000"}, "t4": t4_cfg(t4), "layers": [], "captions": [], "cards": [], "texts": [],
            "elements": [], "video_layers": []}
def render(jb, out):
    jp = tmp / (Path(out).stem + ".json"); jp.write_text(json.dumps(dict(jb, output=str(out))), encoding="utf-8")
    r = subprocess.run([sys.executable, str(P / "montage.py"), "--job", str(jp), "--arabic-mode", "raqm"], cwd=str(tmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and Path(out).is_file(), (r.stdout + r.stderr)[-300:]
def grab(mp4, t, name):
    png = tmp / name; ff("-ss", str(t), "-i", str(mp4), "-frames:v", "1", str(png)); return np.asarray(Image.open(png).convert("RGB"), int), png
def audio(f):
    return subprocess.run([FFMPEG, "-v", "error", "-i", str(f), "-f", "s16le", "-ac", "1", "-ar", "48000", "-"], capture_output=True).stdout
def green(a): return (a[..., 1] > 150) & (a[..., 0] < 90) & (a[..., 2] < 110)
def cen(a, n=12): h, w = a.shape[:2]; return a[h // 2 - n:h // 2 + n, w // 2 - n:w // 2 + n].reshape(-1, 3).mean(0)
def cov(m): return 0.0 if isinstance(m, str) and m == "empty" else 1.0 if isinstance(m, str) else float(np.asarray(m).mean()) / 255.0
try:
    Image.new("RGB", (400, 300), (30, 200, 60)).save(tmp / "g.png")
    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp / "clip.mp4"))
    for cv, (W, H) in CV.items():
        ff("-f", "lavfi", "-i", f"color=c=0x303030:s={W // 2}x{H // 2}:r={FPS}:d={DUR}", "-f", "lavfi", "-i", f"sine=f=1000:d={DUR}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp / f"spk_{cv}.mp4"))
    G = tmp / "g.png"
    # ---- cfg ----------------------------------------------------------------------------------------------------------------------
    d = t4_broll_cfg(None); ok = d["on"] is False and d["anim"] == "fade" and d["decor"] is True
    ok = ok and all(t4_broll_cfg(j) == d for j in (5, "x", []))
    e = t4_broll_cfg({"media": "a.png", "anim": "Diagonal", "anim_dur": 99, "angle": "zz", "seg_start": -3, "seg_end": 1, "color": "zz", "extra": 1})
    ok = ok and e["on"] is True and e["anim"] == "wipe" and e["anim_dur"] == 0.5 and e["angle"] == 20.0 and e["seg_start"] == 0.0 and e["seg_end"] is None \
        and e["color"] == "#19d3ff" and e["extra"] == 1 and t4_broll_cfg(e) == e
    rec("broll cfg: junk -> defaults (never raises), anim aliases, seg fixes, extras kept, idempotent", ok, str(e))
    # ---- wipe mask ------------------------------------------------------------------------------------------------------------------
    for cv in CV:
        plan, w = quiet(t4_broll_plan, job(cv, BR(G, anim="wipe"), tmp / f"spk_{cv}.mp4"), DUR, float(FPS))
        d_, t0, t1 = plan["d"], plan["t0"], plan["t1"]
        a = [cov(t4_broll_mask(plan, t0 + d_ * k / 6.0)) for k in range(6)]
        b = [cov(t4_broll_mask(plan, t1 - d_ + d_ * k / 6.0)) for k in range(6)]
        mid = t4_broll_mask(plan, (t0 + t1) / 2)
        rec(f"wipe mask {cv}: entry coverage grows from ~0, middle = full, exit shrinks to ~0, entry is partial early on",
            all(y >= x - 1e-6 for x, y in zip(a, a[1:])) and all(y <= x + 1e-6 for x, y in zip(b, b[1:])) and a[0] < 0.02 and b[-1] < 0.4
            and isinstance(mid, str) and mid == "full" and 0.1 < a[2] < 0.9 and not w, f"in={[round(x, 2) for x in a]} out={[round(x, 2) for x in b]} warn={w}")
    # ---- decor plate + items ----------------------------------------------------------------------------------------------------------
    for cv, (W, H) in CV.items():
        pl = t4_broll_decor(W, H, "#19d3ff", "#ffc21a"); al = np.asarray(pl.getchannel("A"))
        reg = lambda x0, y0, x1, y1: al[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)].max()
        rec(f"decor plate {cv}: canvas size, content top-left / top-right / bottom-left, transparent centre-ish pixel",
            pl.size == (W, H) and reg(0, 0, .25, .16) > 0 and reg(.7, 0, 1, .12) > 0 and reg(0, .85, .25, .96) > 0 and t4_broll_decor(W, H, "#19d3ff", "#ffc21a") is pl,
            f"size={pl.size}")
        j = job(cv, BR(G, start=0.0), tmp / f"spk_{cv}.mp4")
        real, w1 = quiet(t4_broll_items, j, DUR)
        still, _w = quiet(t4_broll_items, dict(j, _t2_still=True), DUR)
        off, _w = quiet(t4_broll_items, job(cv, BR(G, decor=False), tmp / f"spk_{cv}.mp4"), DUR)
        none, _w = quiet(t4_broll_items, job(cv, {"on": False}, tmp / f"spk_{cv}.mp4"), DUR)
        rec(f"broll items {cv}: real = 1 (decor), --still = 2 (media + decor), decor off = 0, module off = 0", len(real) == 1 and len(still) == 2 and off == [] and none == [] and not w1,
            f"{len(real)}/{len(still)}/{len(off)}/{len(none)} warn={w1}")
    # ---- real renders: fade + wipe ----------------------------------------------------------------------------------------------------
    for cv, (W, H) in CV.items():
        spk = tmp / f"spk_{cv}.mp4"; base = tmp / f"base_{cv}.mp4"
        okb, msg = render(job(cv, None, spk), base)
        if not okb: rec(f"render {cv} without b-roll", False, msg); continue
        ab, ib = audio(base), probe(str(base))
        for anim in ("fade", "wipe"):
            out = tmp / f"br_{cv}_{anim}.mp4"; okr, msg = render(job(cv, BR(G, anim=anim), spk), out)
            if not okr: rec(f"render {cv} {anim}", False, msg); continue
            i = probe(str(out)); fr = {t: grab(out, t, f"{cv}_{anim}_{t}.png") for t in (0.5, 1.1, 2.5, 4.8)}
            spk_ok = all(abs(cen(fr[t][0]) - 48).max() < 14 for t in (0.5, 4.8))
            grn_ok = abs(cen(fr[2.5][0]) - np.array([30, 200, 60])).max() < 45
            part = float(green(fr[1.1][0]).mean()); full_g = float(green(fr[2.5][0]).mean())
            tr_ok = (0.1 < part < 0.9 * full_g) if anim == "wipe" else (part < full_g - 0.05)
            rec(f"render {cv} {anim}: speaker -> b-roll (green, full canvas) -> speaker, partial transition at 1.1 s",
                spk_ok and grn_ok and tr_ok and (i["w"], i["h"]) == (W, H), f"speaker={spk_ok} green={cen(fr[2.5][0]).round().tolist()} part={part:.2f} full={full_g:.2f}")
            ao = audio(out); e = np.abs(np.frombuffer(ao, np.int16).astype(float)); n = len(e) // 480
            en = e[:n * 480].reshape(n, 480).mean(1)
            rec(f"audio {cv} {anim}: speaker audio continuous (no gap) and byte-identical to the render without b-roll; same duration",
                ao == ab and en[10:-10].min() > 800 and abs(i["duration"] - ib["duration"]) < 0.02, f"identical={ao == ab} min energy={en[10:-10].min():.0f} dur={i['duration']:.3f}/{ib['duration']:.3f}")
            if anim == "fade":
                shutil.copy(fr[2.5][1], OUT / f"broll_{cv}.png")
                off = tmp / f"br_{cv}_nodecor.mp4"
                if render(job(cv, BR(G, anim="fade", decor=False), spk), off)[0]:
                    diff = (np.abs(fr[2.5][0] - grab(off, 2.5, f"{cv}_nd.png")[0]).max(axis=2) > 12).sum()
                    rec(f"decor {cv}: visible on the rendered frame (decor on vs off differ)", diff > 800, f"{diff} px differ")
            else:
                shutil.copy(fr[2.5][1], OUT / f"broll_{cv}_wipe.png")
    # ---- video media ------------------------------------------------------------------------------------------------------------------
    cv = "reels"; out = tmp / "br_clip.mp4"
    if render(job(cv, BR(tmp / "clip.mp4"), tmp / f"spk_{cv}.mp4"), out)[0]:
        a1, a2 = grab(out, 1.6, "c1.png")[0], grab(out, 3.0, "c2.png")[0]
        rec("broll with a VIDEO clip: it plays (centre differs between 1.6 s and 3.0 s)", float(np.abs(a1[700:1200] - a2[700:1200]).mean()) > 2.0)
    else:
        rec("broll with a VIDEO clip", False, "render failed")
    # ---- still + robustness ------------------------------------------------------------------------------------------------------------
    for cv, (W, H) in CV.items():
        sp = tmp / f"still_{cv}.png"; quiet(render_still, job(cv, BR(G, start=0.0), tmp / f"spk_{cv}.mp4"), str(sp), 1.5)
        rec(f"--still {cv}: written, b-roll fills the canvas", sp.is_file() and abs(cen(np.asarray(Image.open(sp).convert("RGB"), int)) - np.array([30, 200, 60])).max() < 45)
    spk = tmp / "spk_reels.mp4"
    r1, w1 = quiet(t4_broll_items, job("reels", BR(tmp / "nope.png"), spk), DUR)
    r2, w2 = quiet(t4_broll_items, job("reels", BR(G, trigger="never said", start=None), spk), DUR)
    r3, w3 = quiet(t4_broll_items, {"t4": t4_cfg({"broll": BR(G)})}, DUR)
    r4, w4 = quiet(t4_broll_items, job("reels", BR(G, start=99), spk), DUR)
    rec("broll never raises: missing media -> gray placeholder + ONE warning (decor still drawn); trigger not found / start after the end / no canvas -> skipped + warning",
        len(r1) == 1 and len(w1) == 1 and r2 == [] and len(w2) == 1 and r3 == [] and len(w3) == 1 and r4 == [] and len(w4) == 1, f"{w1} {w2} {w3} {w4}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)