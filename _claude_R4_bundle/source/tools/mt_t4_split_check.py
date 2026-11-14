"""Split (R7) check: python tools/mt_t4_split_check.py   (also writes out/t4/split_view_{reels,youtube}.png + split_view_ar_reels.png - LOOK at them)."""
import contextlib, io, json, math, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageChops
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
import mt.templates                                                                       # noqa: E402
from mt.common import FFMPEG, probe                                                       # noqa: E402
from mt.render import render_still                                                        # noqa: E402
from mt.templates.t4.cfg import t4_cfg                                                    # noqa: E402
from mt.templates.t4.frame import t4_frame_cfg, t4_frame_plate                            # noqa: E402
from mt.templates.t4.nameplate import FRAME_THR, INK_THR                                  # noqa: E402
from mt.templates.t4.split import t4_split_cfg, t4_split_items, t4_split_plan, t4_split_u  # noqa: E402
from mt.templates.t4.warn import t4_warn_reset                                            # noqa: E402
rows = []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): r = fn(*a)
    return r, [l for l in buf.getvalue().splitlines() if "[!]" in l]
CV = {"reels": (1080, 1920), "youtube": (1920, 1080)}
TAN = math.tan(math.radians(12))
tmp = Path(tempfile.mkdtemp(prefix="t4split_")); OUT = P / "out" / "t4"; OUT.mkdir(parents=True, exist_ok=True)
def ff(*a): subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *a], check=True)
def mag(a): return (a[..., 0] > 150) & (a[..., 2] > 150) & (a[..., 1] < 100)
def job(cv, split, video, frame=False):
    W, H = CV[cv]
    return {"template_id": 5, "video": str(video), "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"},
            "background": {"type": "color", "value": "#000000"}, "t4": t4_cfg({"canvas_mode": cv, "fit": "fill", "split": split, "frame": {"on": frame}}),
            "layers": [], "captions": [], "cards": [], "texts": [], "elements": [], "video_layers": []}
def SPL(media, **k): return dict({"on": True, "media": str(media)}, **k)
try:
    SPK, VIEW, DEV, MAG = tmp / "spk.mp4", tmp / "view.mp4", tmp / "dev.mp4", tmp / "mag.png"
    ff("-f", "lavfi", "-i", "color=c=0x20a020:s=360x640:r=25:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(SPK))
    ff("-f", "lavfi", "-i", "smptebars=s=640x360:r=25:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(VIEW))
    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(DEV))
    Image.new("RGB", (400, 300), (200, 30, 200)).save(MAG)
    FPS = float(probe(str(SPK))["fps"])
    # ---- cfg ------------------------------------------------------------------------------------------------------------------------
    junk = [None, 5, "x", [], {"angle": "zz", "side": 5, "pos": 9, "labels": "x", "wipe": -1, "media": 7, "color": "zz"}]
    cs = [t4_split_cfg(j) for j in junk]
    ok = all(c["on"] is False and c["angle"] == 12.0 and c["side"] == "auto" and c["pos"] is None and c["wipe"] == 0.55 and len(c["labels"]) == 2 and c["labels"][0]["text"].startswith("01") for c in cs)
    e = t4_split_cfg({"media": "a.png", "labels": ["-", {"text": "B", "anchor": "tl"}], "angle": 99, "side": "RIGHT", "pos": 0.3})
    ok = ok and e["on"] is True and e["labels"][0]["text"] == "" and e["labels"][1] == {"text": "B", "color": "", "anchor": "top-left"} and e["angle"] == 12.0 and e["side"] == "right" and e["pos"] == 0.3
    rec("split cfg: junk -> defaults (never raises), labels '-' hides / anchor alias, side + pos kept, angle out of range -> default, on follows media", ok, f"{cs[-1]} {e}")
    # ---- geometry -------------------------------------------------------------------------------------------------------------------
    area = lambda p: abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(p, p[1:] + p[:1]))) / 2.0
    for cv, (W, H) in CV.items():
        plan, w = quiet(t4_split_plan, job(cv, SPL(MAG), SPK), 6.0, 25.0)
        d = plan["d"]; want = 0.5 if cv == "reels" else 0.4
        slant = abs(d[1] / d[0]) if cv == "reels" else abs(d[0] / d[1])
        side_ok = plan["side"] == ("bottom" if cv == "reels" else "right")
        us = [t4_split_u(plan, (plan["j0"] + k) / 25.0) for k in range(int(plan["wipe"] * 25) + 3)]
        mid, tail = t4_split_u(plan, (plan["t0"] + plan["t1"]) / 2), t4_split_u(plan, plan["t1"] - 1 / 25.0)
        rec(f"split geometry {cv}: auto side, media area {want:.0%}, seam lean 12 deg ({'near-horizontal' if cv == 'reels' else 'near-vertical slant on the right'}), wipe u 0 -> 1 -> back",
            side_ok and abs(area(plan["poly"]) / (W * H) - want) < 0.01 and abs(slant - TAN) < 0.01 and us[0] == 0 and all(b >= a for a, b in zip(us, us[1:])) and mid == 1.0 and tail < 0.3 and not w,
            f"side={plan['side']} area={area(plan['poly']) / (W * H):.3f} slant={slant:.3f} u={[round(x, 2) for x in us[:6]]} tail={tail:.2f} warn={w}")
    # ---- items (no render): seam steps, labels in the safe margin, frame clear -------------------------------------------------------
    def ink(it, W, H):
        full = Image.new("L", (W, H), 0)
        full.paste(it.sprite.getchannel("A").point(lambda v: 255 if v > INK_THR else 0), (int(it.cx - it.sprite.width / 2), int(it.cy - it.sprite.height / 2)))
        return full
    bad = []
    for cv, (W, H) in CV.items():
        for fo in (False, True):
            fa = t4_frame_plate(W, H, t4_frame_cfg({"on": True})).getchannel("A").point(lambda v: 255 if v > FRAME_THR else 0) if fo else None
            t4_warn_reset(); items, w = quiet(t4_split_items, job(cv, SPL(MAG, labels=["01 \u2014 TALKING HEAD", "02 \u2014 LIVE DEVELOPMENT"]), SPK, fo), 6.0)
            seam = [i for i in items if i.sprite.info.get("split") == "seam"]; labs = [i for i in items if i.sprite.info.get("split") == "label"]
            steps = [i for i in seam if i.end - i.start < 0.5]; hold = [i for i in seam if i.end - i.start >= 0.5]
            if w or len(labs) != 2 or len(hold) != 1 or len(steps) < 6 or any(i.sprite.info.get("split") == "region" for i in items) \
                    or any(abs((i.end - i.start) - 1 / FPS) > 1e-6 for i in steps):
                bad.append(f"{cv}/{fo}: labels={len(labs)} hold={len(hold)} steps={len(steps)} warn={w}")
            for it in labs:
                bb = ink(it, W, H).getbbox(); s = min(W, H) / 1080.0
                hit = fa is not None and ImageChops.multiply(ink(it, W, H), fa).getbbox() is not None
                if not bb or bb[0] < 47 * s or bb[1] < 47 * s or W - bb[2] < 47 * s or H - bb[3] < 47 * s or hit:
                    bad.append(f"{cv}/{fo}: label ink={bb} frame_hit={hit}")
    rec("split items (both canvases x frame off / on): 1 hold seam + per-frame seam steps (1 frame each), 2 labels >= 48 px from the edges and clear of the frame, no region item in a real render", not bad, "; ".join(bad[:3]))
    st_items, _w = quiet(t4_split_items, dict(job("reels", SPL(MAG), SPK), _t2_still=True), 6.0)
    rec("split items in --still mode: 1 region + 1 seam + 2 labels", sorted(i.sprite.info.get("split") for i in st_items) == ["label", "label", "region", "seam"])
    # ---- stills: pixels --------------------------------------------------------------------------------------------------------------
    for cv, (W, H) in CV.items():
        stp, ofp = tmp / f"s_{cv}.png", tmp / f"o_{cv}.png"
        quiet(render_still, job(cv, SPL(MAG), SPK), str(stp), 2.0); quiet(render_still, job(cv, {"on": False}, SPK), str(ofp), 2.0)
        a, b = np.asarray(Image.open(stp).convert("RGB"), int), np.asarray(Image.open(ofp).convert("RGB"), int)
        M = mag(a)
        pm, ps = ((W // 2, int(H * .9)), (W // 2, int(H * .1))) if cv == "reels" else ((int(W * .92), H // 2), (int(W * .1), H // 2))
        pix_ok = bool(M[pm[1], pm[0]]) and np.abs(a[ps[1], ps[0]] - np.array([32, 160, 32])).max() < 45
        try:
            if cv == "reels":
                dv = np.where(M[:, int(.1 * W)])[0].min() - np.where(M[:, int(.9 * W)])[0].min(); exp = .8 * W * TAN
            else:
                dv = np.where(M[int(.2 * H), :])[0].min() - np.where(M[int(.8 * H), :])[0].min(); exp = .6 * H * TAN
            slant_ok = dv > 0 and abs(dv - exp) < 22
        except ValueError:
            dv, exp, slant_ok = None, None, False
        if cv == "reels": strip = a[H // 2 - 12:H // 2 + 13, W // 2]
        else: strip = a[H // 2, int(.6 * W) - 12:int(.6 * W) + 13]
        seam_ok = bool(((strip[:, 1] > 170) & (strip[:, 2] > 200)).any())
        reg = (slice(int(.15 * H), int(.35 * H)), slice(None)) if cv == "reels" else (slice(int(.2 * H), int(.8 * H)), slice(int(.1 * W), int(.4 * W)))
        same = float(np.abs(a[reg] - b[reg]).mean()) < 2.0
        rec(f"split still {cv}: media colour on its side only, speaker side untouched, seam leans 12 deg the right way, cyan seam pixels on the diagonal",
            pix_ok and slant_ok and seam_ok and same, f"media/speaker px ok={pix_ok} lean={dv} (want ~{exp and round(exp)}) seam={seam_ok} speaker side unchanged={same}")
    for cv in CV:
        quiet(render_still, job(cv, SPL(DEV, hold=5), VIEW, True), str(OUT / f"split_view_{cv}.png"), 2.0)
    quiet(render_still, job("reels", SPL(DEV, hold=5, labels=["\u0660\u0661 \u2014 \u0627\u0644\u0645\u062a\u062d\u062f\u062b", "\u0660\u0662 \u2014 \u0627\u0644\u062a\u0637\u0648\u064a\u0631 \u0627\u0644\u0645\u0628\u0627\u0634\u0631"]), VIEW, False), str(OUT / "split_view_ar_reels.png"), 2.0)
    # ---- real renders: wipe in / hold / wipe out ---------------------------------------------------------------------------------------
    def grab(mp4, t, name):
        png = tmp / name; ff("-ss", str(t), "-i", str(mp4), "-frames:v", "1", str(png)); return np.asarray(Image.open(png).convert("RGB"), int)
    for cv, (W, H) in CV.items():
        jp, out = tmp / f"r_{cv}.json", tmp / f"r_{cv}.mp4"
        jb = job(cv, SPL(MAG, start=0.5, hold=2.5), SPK); jb["output"] = str(out); jp.write_text(json.dumps(jb), encoding="utf-8")
        r = subprocess.run([sys.executable, str(P / "montage.py"), "--job", str(jp), "--arabic-mode", "raqm"], cwd=str(tmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not out.is_file():
            rec(f"split render {cv}", False, (r.stdout + r.stderr)[-300:]); continue
        i = probe(str(out)); full = 0.5 if cv == "reels" else 0.4
        c = {t: float(mag(grab(out, t, f"g_{cv}_{t}.png")).mean()) for t in (0.35, 0.7, 1.6, 2.8, 3.5)}
        rec(f"split render {cv}: size / duration / audio, then nothing -> partial wipe -> full media -> partial (exit) -> nothing",
            (i["w"], i["h"]) == (W, H) and abs(i["duration"] - 4) < 0.25 and bool(i["audio"]) and c[0.35] < 0.01 and 0.1 * full < c[0.7] < 0.97 * full
            and abs(c[1.6] - full) < 0.04 and 0.1 * full < c[2.8] < 0.97 * c[1.6] and c[3.5] < 0.01, f"{i['w']}x{i['h']} {i['duration']:.2f}s coverage={ {k: round(v, 3) for k, v in c.items()} } (full ~{full})")
    jp, out = tmp / "r_clip.json", tmp / "r_clip.mp4"
    jb = job("reels", SPL(DEV, start=0.5, hold=3), SPK); jb["output"] = str(out); jp.write_text(json.dumps(jb), encoding="utf-8")
    r = subprocess.run([sys.executable, str(P / "montage.py"), "--job", str(jp), "--arabic-mode", "raqm"], cwd=str(tmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.is_file():
        a1, a2 = grab(out, 1.4, "c1.png"), grab(out, 1.9, "c2.png")
        rec("split render with a VIDEO media: the clip plays (media area differs between 1.4 s and 1.9 s)", float(np.abs(a1[int(.75 * 1920):int(.95 * 1920), 200:800] - a2[int(.75 * 1920):int(.95 * 1920), 200:800]).mean()) > 2.0)
    else:
        rec("split render with a VIDEO media", False, (r.stdout + r.stderr)[-300:])
    # ---- robustness ----------------------------------------------------------------------------------------------------------------------
    t4_warn_reset(); r1, w1 = quiet(t4_split_items, job("reels", SPL(tmp / "nope.png"), SPK), 6.0)
    t4_warn_reset(); r2, w2 = quiet(t4_split_items, job("reels", SPL(MAG, trigger="never said"), SPK), 6.0)
    t4_warn_reset(); r3, w3 = quiet(t4_split_items, {"t4": t4_cfg({"split": SPL(MAG)})}, 6.0)
    r4 = quiet(t4_split_items, job("reels", {"on": False}, SPK), 6.0)[0]
    rec("split never raises: missing media -> gray placeholder + ONE warning (seam + labels still drawn); trigger not found -> skipped + 1 warning; no canvas -> [] + 1 warning; off -> []",
        len(r1) >= 3 and len(w1) == 1 and "nope.png" in w1[0] and r2 == [] and len(w2) == 1 and r3 == [] and len(w3) == 1 and r4 == [], f"{w1} {w2} {w3}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)