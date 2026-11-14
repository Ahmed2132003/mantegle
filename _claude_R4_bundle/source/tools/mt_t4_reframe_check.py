"""Reframe (R7) check: python tools/mt_t4_reframe_check.py
Real renders on 1080x1920 and 1920x1080 (reframe ON vs OFF, same job): frames BEFORE / DURING / AFTER the split, the face marker position,
the plain command unchanged when reframe is off, and the audio / video sync (flash frames vs beeps, durations, identical audio).
Also writes out/t4/reframe_{reels,youtube}_{off,on}_{before,during,after}.png - LOOK at them."""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile
from fractions import Fraction
from pathlib import Path
import numpy as np
from PIL import Image
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
import mt.templates                                                                       # noqa: E402
from mt.common import FFMPEG, probe                                                       # noqa: E402
from mt.render import build_ffmpeg_cmd                                                    # noqa: E402
from mt.templates.t4.cfg import t4_cfg                                                    # noqa: E402
from mt.templates.t4.reframe import t4_reframe_cfg, t4_reframe_vf, t4_visible_rect        # noqa: E402
from mt.templates.t4.split import t4_split_plan                                           # noqa: E402
from mt.templates.t4.warn import t4_warn_reset                                            # noqa: E402
rows = []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): r = fn(*a)
    return r, [l for l in buf.getvalue().splitlines() if "[!]" in l]
CV = {"reels": (1080, 1920), "youtube": (1920, 1080)}
SRC = {"reels": (720, 1280), "youtube": (1280, 720)}                 # the speaker video matches the canvas shape (the normal case)
START, HOLD, FPS, DUR = 1.0, 3.0, 25, 6.0
MID = START + HOLD / 2 + 0.2                                           # a frame in the hold that is not a flash frame
EVENTS = (0.4, 2.4, 5.0)                                              # flash + beep: before / INSIDE / after the split
tmp = Path(tempfile.mkdtemp(prefix="t4rf_")); OUT = P / "out" / "t4"; OUT.mkdir(parents=True, exist_ok=True)
def ff(*a): subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *a], check=True)
def marker(a): return (a[..., 0] > 200) & (a[..., 2] > 200) & (a[..., 1] < 80)       # magenta 'face' box
def job(cv, reframe, video, split_extra=None):
    W, H = CV[cv]; sp = dict({"on": True, "media": str(tmp / "media.png"), "start": START, "hold": HOLD}, **(split_extra or {}))
    t4 = {"canvas_mode": cv, "fit": "fill", "split": sp}
    if reframe is not None: t4["reframe"] = reframe
    return {"template_id": 5, "video": str(video), "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"},
            "background": {"type": "color", "value": "#000000"}, "t4": t4_cfg(t4), "layers": [], "captions": [], "cards": [], "texts": [],
            "elements": [], "video_layers": []}
def grab(mp4, t, name):
    png = tmp / name; ff("-ss", str(t), "-i", str(mp4), "-frames:v", "1", str(png)); return png
def face(png):
    a = np.asarray(Image.open(png).convert("RGB"), int); m = marker(a); ys, xs = np.where(m)
    return (float(xs.mean()), float(ys.mean())) if len(xs) else None
def flashes(f):
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(f), "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, 36 * 64).mean(1); idx = np.where(a > 120)[0]; g = []      # the media / seam cover part of a flash frame inside the split
    for i in idx:
        if g and i - g[-1][-1] <= 1: g[-1].append(i)
        else: g.append([i])
    return len(a), [x[0] / FPS for x in g]
def beeps(f):
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(f), "-f", "s16le", "-ac", "1", "-ar", "48000", "-"], capture_output=True).stdout
    a = np.abs(np.frombuffer(raw, np.int16).astype(float)); n = len(a) // 480; e = a[:n * 480].reshape(n, 480).mean(1); idx = np.where(e > 2000)[0]; g = []
    for i in idx:
        if g and i - g[-1][-1] <= 2: g[-1].append(i)
        else: g.append([i])
    return [x[0] * 0.01 for x in g], raw
def render(jb, out):
    jp = tmp / (Path(out).stem + ".json"); jb = dict(jb, output=str(out)); jp.write_text(json.dumps(jb), encoding="utf-8")
    r = subprocess.run([sys.executable, str(P / "montage.py"), "--job", str(jp), "--arabic-mode", "raqm"], cwd=str(tmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and Path(out).is_file(), (r.stdout + r.stderr)[-300:]
try:
    Image.new("RGB", (400, 300), (40, 200, 90)).save(tmp / "media.png")      # green: never mistaken for the magenta face box
    en = "+".join(f"between(t,{t},{t + 0.08})" for t in EVENTS)
    for cv, (vw, vh) in SRC.items():                                  # speaker source: grey, magenta face box at (0.5, 0.4) + flash + beep
        x, y = int(0.5 * vw), int(0.4 * vh)
        ff("-f", "lavfi", "-i", f"color=c=0x303030:s={vw}x{vh}:r={FPS}:d={DUR}", "-f", "lavfi", "-i", f"aevalsrc='sin(2*PI*1000*t)*({en})':s=48000:d={DUR}",
           "-vf", f"drawbox=x={x - 30}:y={y - 30}:w=60:h=60:c=magenta:t=fill,drawbox=x=0:y=0:w={vw}:h={vh}:c=white:t=fill:enable='{en}'",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(tmp / f"spk_{cv}.mp4"))
    # ---- cfg ---------------------------------------------------------------------------------------------------------------------------
    d = {"on": False, "focus_x": 0.5, "focus_y": 0.4, "scale": 1.35}
    ok = all(t4_reframe_cfg(j) == d for j in (None, 5, "x", [], {"on": 0}, {"focus_x": "zz", "scale": None}))
    e = t4_reframe_cfg({"on": True, "focus_x": "30%", "scale": 9, "focus_y": -4, "extra": 1})
    ok = ok and e == {"on": True, "focus_x": 0.3, "focus_y": 0.0, "scale": 3.0, "extra": 1}
    rec("reframe cfg: junk -> defaults (never raises), percent / clamp, extras kept, on only when asked", ok, str(e))
    # ---- visible rectangle ----------------------------------------------------------------------------------------------------------------
    for cv, (W, H) in CV.items():
        plan, w = quiet(t4_split_plan, job(cv, {"on": True}, tmp / f"spk_{cv}.mp4"), DUR, float(FPS)); r = t4_visible_rect(plan)
        okr = (r[0] == 0 and r[1] == 0 and abs(r[2] - (W if cv == "reels" else 1037.2)) < 1 and abs(r[3] - (845.2 if cv == "reels" else H)) < 1)
        rec(f"visible rect {cv}: the speaker's side only (reels = top band above the seam's nearest point, YouTube = left part)", okr and not w, str(tuple(round(v, 1) for v in r)))
    # ---- command: reframe off / no split / fit = the plain command ---------------------------------------------------------------------------
    for cv, (W, H) in CV.items():
        v = tmp / f"spk_{cv}.mp4"; info = probe(str(v))
        mk = lambda rf, sp=None: job(cv, rf, v, sp)
        c_none, c_off = [build_ffmpeg_cmd(mk(rf), info, DUR, "o.mp4", False, "ov.mov") for rf in (None, {"on": False, "scale": 2.0, "focus_x": 0.2})]
        c_on = build_ffmpeg_cmd(mk({"on": True}), info, DUR, "o.mp4", False, "ov.mov")
        nosplit = job(cv, {"on": True}, v); nosplit["t4"]["split"]["on"] = False
        c_ns = build_ffmpeg_cmd(nosplit, info, DUR, "o.mp4", False, "ov.mov")
        fit = mk({"on": True}); fit["video_box"]["mode"] = "fit"; t4_warn_reset()
        c_fit, wf = quiet(build_ffmpeg_cmd, fit, info, DUR, "o.mp4", False, "ov.mov")
        fit_plain = job(cv, None, v); fit_plain["video_box"]["mode"] = "fit"
        c_fit0 = build_ffmpeg_cmd(fit_plain, info, DUR, "o.mp4", False, "ov.mov")
        fc = lambda c: c[c.index("-filter_complex") + 1]
        rec(f"command {cv}: reframe off (or missing) = identical command; split off = identical; 'fit' = identical",
            c_none == c_off and fc(c_ns) == fc(c_none) and c_fit == c_fit0, "")
        rec(f"command {cv}: reframe on changes only the video chain (zoom scale eval=frame + overlay offset expressions)",
            "eval=frame" in fc(c_on) and "overlay_w" in fc(c_on) and fc(c_on) != fc(c_none) and c_on[:c_on.index("-filter_complex")] == c_none[:c_none.index("-filter_complex")]
            and c_on[c_on.index("-filter_complex") + 2:] == c_none[c_none.index("-filter_complex") + 2:], "")
    # ---- real renders: frames before / during / after, face position -----------------------------------------------------------------------
    for cv, (W, H) in CV.items():
        v = tmp / f"spk_{cv}.mp4"; outs = {}
        for tag, rf in (("off", None), ("on", {"on": True, "focus_x": 0.5, "focus_y": 0.4, "scale": 1.5})):
            outs[tag] = tmp / f"r_{cv}_{tag}.mp4"; okr, msg = render(job(cv, rf, v), outs[tag])
            if not okr: rec(f"render {cv} {tag}", False, msg)
        if len(outs) < 2 or not all(Path(o).is_file() for o in outs.values()): continue
        tt = {"before": 0.7, "during": MID, "after": START + HOLD + 0.9}; pos = {}
        for tag in ("off", "on"):
            for k, t in tt.items():
                png = grab(outs[tag], t, f"{cv}_{tag}_{k}.png"); pos[(tag, k)] = face(png); shutil.copy(png, OUT / f"reframe_{cv}_{tag}_{k}.png")
        plan, _w = quiet(t4_split_plan, job(cv, {"on": True}, v), DUR, float(FPS)); rect = t4_visible_rect(plan)
        base = pos[("off", "before")]; dur_on = pos[("on", "during")]
        axis = 0 if cv == "youtube" else 1
        inside = dur_on is not None and dur_on[axis] < (rect[2] if cv == "youtube" else rect[3]) - 40
        moved = dur_on is not None and abs(dur_on[axis] - base[axis]) > 100
        same_before = pos[("on", "before")] is not None and max(abs(a - b) for a, b in zip(pos[("on", "before")], base)) < 3
        same_after = pos[("on", "after")] is not None and max(abs(a - b) for a, b in zip(pos[("on", "after")], base)) < 3
        rec(f"reframe {cv}: face BEFORE = plain fill, DURING = inside the visible side (moved toward it), AFTER = back to the plain fill",
            inside and moved and same_before and same_after, f"before={pos[('on','before')]} during={dur_on} after={pos[('on','after')]} plain={base} visible={tuple(round(x) for x in rect)}")
        pic = lambda tag, t: np.asarray(Image.open(grab(outs[tag], t, f"cmp_{cv}_{tag}_{t}.png")).convert("RGB"), int)
        rec(f"reframe {cv}: whole frame before and after the split is the same picture as reframe off (mean diff < 3)",
            all(float(np.abs(pic("on", t) - pic("off", t)).mean()) < 3.0 for t in (0.7, START + HOLD + 0.9)))
        # ---- sync ----------------------------------------------------------------------------------------------------------------------------
        info = {}
        for tag in ("off", "on"):
            nf, fl = flashes(outs[tag]); bp, raw = beeps(outs[tag])
            vi, ai = probe(str(outs[tag])), None
            info[tag] = (nf, fl, bp, raw, vi["duration"])
        nf0, fl0, bp0, raw0, d0 = info["off"]; nf1, fl1, bp1, raw1, d1 = info["on"]
        sync = len(fl1) == len(EVENTS) and len(bp1) == len(EVENTS) and all(abs(f - b) <= 1.5 / FPS for f, b in zip(fl1, bp1)) \
            and all(abs(f - e) <= 1.5 / FPS for f, e in zip(fl1, EVENTS))
        rec(f"audio sync {cv}: flash frames match the beeps (one INSIDE the split, at 2.4 s), same frame count / duration as reframe off, audio bytes identical",
            sync and nf0 == nf1 and abs(d0 - d1) < 0.02 and raw0 == raw1, f"flash={fl1} beep={bp1} frames={nf0}/{nf1} dur={d0:.3f}/{d1:.3f} audio_same={raw0 == raw1}")
    # ---- the other sides (left / right / top / bottom) keep the face inside the visible rect ------------------------------------------------------
    for cv in CV:
        v = tmp / f"spk_{cv}.mp4"; bad = []
        for sd in ("left", "right", "top", "bottom"):
            out = tmp / f"s_{cv}_{sd}.mp4"; okr, msg = render(job(cv, {"on": True, "scale": 1.8}, v, {"side": sd}), out)
            if not okr: bad.append(f"{sd}: render failed"); continue
            plan, _w = quiet(t4_split_plan, job(cv, {"on": True}, v, {"side": sd}), DUR, float(FPS)); r = t4_visible_rect(plan)
            f = face(grab(out, MID, f"s_{cv}_{sd}.png"))
            if f is None or not (r[0] <= f[0] <= r[0] + r[2] and r[1] <= f[1] <= r[1] + r[3]): bad.append(f"{sd}: face={f} rect={tuple(round(x) for x in r)}")
        rec(f"reframe {cv}: all four split sides keep the face inside the visible rectangle (scale 1.8)", not bad, "; ".join(bad))
    # ---- robustness ---------------------------------------------------------------------------------------------------------------------------
    v = tmp / "spk_reels.mp4"; info = probe(str(v)); t4_warn_reset()
    bad = {"t4": {"split": {"on": True, "media": str(tmp / "media.png")}, "reframe": {"on": True, "scale": "zz", "focus_x": []}}}
    r1 = t4_reframe_vf(dict(job("reels", None, v), **bad), info)
    r2 = t4_reframe_vf({"t4": {"reframe": {"on": True}}}, info)            # no canvas
    r3 = t4_reframe_vf({}, info)
    rec("reframe never raises: junk values -> defaults, no canvas / empty cfg -> None", r1 is not None and r2 is None and r3 is None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)