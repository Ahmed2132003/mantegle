"""Step 4/4 check (put in tools/): python tools/mt_t4_web_dev_check.py
ONE scene, preset 'web_dev' = title_block + code_window + ring + bullet_list + info_card, text cfg = tools/t4_web_dev_scene.json (en + ar),
on R5 1080x1920 and R6 1920x1080.
Unit part (no ffmpeg): safe margin, ink overlaps (the engine's own rule), test connector vs sprites, stagger, RTL (bullets + card), one widget failing / removed.
Render part: --still + 3 s render per canvas x language -> out/t4/wd_<canvas>_<lang>.png (still) and wd_<canvas>_<lang>_t2p3.png (frame at 2.3 s);
every '[!]' line printed by montage.py must match ALLOWED, else FAIL. Exit code 0 = all PASS."""
import contextlib, copy, io, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
rows = []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
import mt.templates  # noqa: E402
from mt.common import FFMPEG, probe  # noqa: E402
from mt.templates.t4.cfg import t4_cfg  # noqa: E402
from mt.templates.t4.nameplate import T4_SAFE  # noqa: E402
from mt.templates.t4.scenes import SLOTS, _lines, _put, _resolve, t4_scenes_items  # noqa: E402
from mt.templates.t4.scenes_reg import WIDGET_SLOT, WIDGETS, get_widget  # noqa: E402
from mt.templates.t4.scenes_widgets import R5_CODE  # noqa: E402
from mt.templates.t4.warn import t4_warn_reset  # noqa: E402

SCN = json.loads(Path(__file__).with_name("t4_web_dev_scene.json").read_text(encoding="utf-8"))
CV = {"reels": (1080, 1920), "youtube": (1920, 1080)}
ALLOWED = []                      # regexes of '[!]' lines that are expected on THIS machine (e.g. a missing font); empty = any warning fails
TEST_LINES = [{"points": ["code-right", "ring-left"]}]      # test connector (the preset's CONNECTORS['web_dev'] is empty)
WL = []                           # (label, warning) printed by the unit builds


# ---- helpers ---------------------------------------------------------------------------------------------------------------
def quiet(fn, *a):
    t4_warn_reset(); buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a)
    return r, [ln.strip() for ln in buf.getvalue().splitlines() if "[!]" in ln]
def Q(label, fn, *a):
    r, w = quiet(fn, *a); WL.extend((label, x) for x in w); return r
def sc_of(lang, **kw):
    sc = copy.deepcopy(SCN[lang][0]); sc.update({"start": 0, "hold": 6}); sc.update(kw); return sc
def wid(sc, t):
    return next(w for w in sc["widgets"] if w["type"] == t)
def ctx_for(W, H):
    return {"W": W, "H": H, "s": min(W, H) / 1080.0, "aspect": "portrait" if H > W else "landscape", "preset": "web_dev", "cfg": {}}
def place(sc, W, H):
    """{slot: (sprite, placed, box)} - same box / ctx / _put as the engine."""
    ctx, out = ctx_for(W, H), {}
    for w in sc["widgets"]:
        slot = w.get("slot") or WIDGET_SLOT[w["type"]]
        box = tuple(v * ctx["s"] for v in SLOTS["web_dev"][ctx["aspect"]][slot])
        sp = get_widget(w["type"])(dict(w), box, ctx)
        out[slot] = (sp, _put(sp, box, W, H, ctx["s"]), box)
    return out
def solid_rect(sp, pl, thr=160):
    """Canvas rect of the pixels with alpha >= thr (sprite + its line sprites)."""
    x0, y0, rs = pl[0] - sp.width / 2.0, pl[1] - sp.height / 2.0, []
    for im, ox, oy in [(sp, x0, y0)] + [(ls, x0 + lx, y0 + ly) for ls, lx, ly in sp.info.get("lines") or []]:
        bb = im.getchannel("A").point(lambda v: 255 if v >= thr else 0).getbbox()
        if bb:
            rs.append((ox + bb[0], oy + bb[1], ox + bb[2], oy + bb[3]))
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs)) if rs else None
def gap(a, b):
    """> 0 clear, 0 touching, < 0 overlapping (the engine warns when < 0)."""
    return max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3])
def seg_hits(p, q, r):
    """True when the segment p-q touches the rect r = (x0, y0, x1, y1) (Liang-Barsky)."""
    t0, t1, dx, dy = 0.0, 1.0, q[0] - p[0], q[1] - p[1]
    for pp, qq in ((-dx, p[0] - r[0]), (dx, r[2] - p[0]), (-dy, p[1] - r[1]), (dy, r[3] - p[1])):
        if pp == 0:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                if t > t1: return False
                t0 = max(t0, t)
            else:
                if t < t0: return False
                t1 = min(t1, t)
    return True
def edge_cyan(im, left):
    """Mean (B - R) of the outermost opaque column: the dot is cyan (> 60), text is white (~0)."""
    a = np.asarray(im.convert("RGBA"), float)
    cols = np.where((a[..., 3] > 60).any(axis=0))[0]
    c = a[:, cols[0] if left else cols[-1]]; c = c[c[:, 3] > 60]
    return float((c[:, 2] - c[:, 0]).mean())
def card_sides(sp, bw, bh):
    """(cyan centroid x = icon, white centroid x = title, centre x) inside the panel, band = centre +- 45 px."""
    a = np.asarray(sp.convert("RGBA"), int); ox, oy = sp.info["origin"]; cy = oy + bh / 2.0
    sub = a[int(cy - 45):int(cy + 45), int(ox + 12):int(ox + bw - 12)]
    cx = lambda m: float(np.where(m)[1].mean()) if m.any() else None
    return (cx((sub[..., 2] - sub[..., 0] > 120) & (sub[..., 3] > 100)), cx((sub[..., :3].min(axis=2) > 230) & (sub[..., 3] > 200)), (bw - 24) / 2.0)
def run_items(sc, W=1080, H=1920, dur=8.0):
    cfg = {"canvas": [W, H], "t4": t4_cfg({"canvas_mode": "reels" if H > W else "youtube", "scenes": [sc]})}
    return quiet(t4_scenes_items, cfg, dur)

rec("self-test: segment / rect + gap helpers", seg_hits((0, 0), (10, 10), (4, 4, 6, 6)) and not seg_hits((0, 0), (10, 10), (20, 20, 30, 30))
    and not seg_hits((0, 5), (10, 5), (4, 6, 6, 9)) and gap((0, 0, 5, 5), (6, 0, 9, 5)) == 1 and gap((0, 0, 5, 5), (4, 0, 9, 5)) < 0)
rec("registered + slots (R5 + R6)", all(t in WIDGETS for t in ("title_block", "code_window", "ring", "bullet_list", "info_card"))
    and all(set(SLOTS["web_dev"][a]) >= {"title", "code", "ring", "bullets", "card"} for a in ("portrait", "landscape")))

# ---- geometry: margin, overlaps, connector, RTL (both canvases x en / ar) ----------------------------------------------------
for cv, (W, H) in CV.items():
    for lang in ("en", "ar"):
        tag = f"{cv} {lang}"
        sc = sc_of(lang, connectors=[])
        pl = Q(tag, place, sc, W, H)
        ink = {k: v[1][2] for k, v in pl.items()}
        sol = {k: solid_rect(v[0], v[1]) for k, v in pl.items()}
        marg = min(min(r[0], r[1], W - r[2], H - r[3]) for r in sol.values())
        rec(f"{tag}: 5 widgets, solid pixels >= {T4_SAFE} px from the canvas edges", len(pl) == 5 and marg >= T4_SAFE - 0.5,
            f"min margin {marg:.0f}; moved by the engine: {[(k, v[1][3]) for k, v in pl.items() if v[1][3]] or 'none'}")
        names = list(ink)
        pairs = [(a, b, gap(ink[a], ink[b])) for i, a in enumerate(names) for b in names[i + 1:]]
        worst = min(pairs, key=lambda t: t[2])
        rec(f"{tag}: no ink overlap between the widgets (engine rule)", worst[2] >= 0, f"tightest {worst[0]} / {worst[1]} = {worst[2]:.0f} px")
        # test connector: both endpoints sit on a widget edge, the line crosses no other widget and is not clamped
        s = ctx_for(W, H)["s"]; ln = _lines(TEST_LINES)[0]
        pts = [_resolve(p, ink, s) for p in ln["points"]]
        named = {p.rpartition("-")[0] for p in ln["points"]}
        hits = [k for k, r in sol.items() if k not in named and any(seg_hits(pts[i], pts[i + 1], r) for i in range(len(pts) - 1))]
        m = (T4_SAFE + ln["glow"] * 1.6 + 2) * s
        free = all(m <= x <= W - m and m <= y <= H - m for x, y in pts)
        rec(f"{tag}: connector code-right -> ring-left crosses no other widget, not clamped", not hits and free,
            f"points {[(round(x), round(y)) for x, y in pts]} crosses {hits or 'none'}")
        # RTL / LTR
        sp, plc, box = pl["bullets"]
        edge = (plc[2][2] - (box[0] + box[2])) if lang == "ar" else (plc[2][0] - box[0])
        row = sp.info["lines"][0][0]
        dot_l, dot_r = edge_cyan(row, True), edge_cyan(row, False)
        rec(f"{tag}: bullet_list {'right-aligned, dot on the right' if lang == 'ar' else 'left-aligned, dot on the left'}",
            abs(edge) <= 2 and ((dot_r > 60 and dot_l < 40) if lang == "ar" else (dot_l > 60 and dot_r < 40)), f"edge off by {edge:.1f} px, B-R left {dot_l:.0f} right {dot_r:.0f}")
        sp, plc, box = pl["card"]
        ic, tx, mid = card_sides(sp, box[2], box[3])
        okc = ic is not None and tx is not None and ((ic > mid + 100 and tx > mid) if lang == "ar" else (ic < mid - 100 and tx < mid))
        rec(f"{tag}: info_card {'icon right, text right-aligned' if lang == 'ar' else 'icon left, text left'}", okc, f"icon x {ic}, text x {tx}, centre {mid:.0f}")

# ---- stagger (reels, en): widget i starts at i x stagger; row / line widgets add their own steps --------------------------------
sc = sc_of("en", connectors=[])
base, w0 = run_items(sc)
sg, ad = sc["stagger"], sc["anim_dur"]
order = [w["type"] for w in sc["widgets"]]
n_code, n_rows = len([ln for ln in R5_CODE.split("\n") if ln.strip()]), len(wid(sc, "bullet_list")["items"])
exp = []
for i, t in enumerate(order):
    st = i * sg
    if t in ("title_block", "ring", "info_card"):
        exp.append(st)
    elif t == "code_window":
        exp += [st] + [st + ad + k * wid(sc, t)["line_step"] for k in range(n_code)]       # window fades in, then the typed lines
    elif t == "bullet_list":
        exp += [st + k * wid(sc, t)["line_step"] for k in range(n_rows)]                    # no window: the rows start with the widget
got = sorted(round(i.start, 3) for i in base)
rec("stagger: widget starts 0 / 0.2 / 0.4 / 0.6 / 0.8 s, code lines after the window fade-in, bullet rows from their own start",
    got == sorted(round(x, 3) for x in exp), f"got {got} want {sorted(round(x, 3) for x in exp)}")
cnt = {}
for w in sc["widgets"]:
    s1 = sc_of("en", connectors=[]); s1["widgets"] = [w]; cnt[w["type"]] = len(run_items(s1)[0])
total = sum(cnt.values())
rec("full scene = sum of the single-widget scenes, no warning", len(base) == total and not w0, f"{cnt} -> {len(base)} items, warnings {w0}")

# ---- one widget fails / is removed: the others stay, one t4_warn -------------------------------------------------------------
def variant(name, mut, want, lost):
    s2 = sc_of("en", connectors=[]); mut(s2)
    its, w = run_items(s2)
    need = total - sum(cnt[t] for t in lost)
    rec(f"isolation: {name} -> {want or 'silent'}, the rest stays", len(its) == need and len(w) == len(want) and all(any(x in ln for ln in w) for x in want),
        f"items {len(its)} want {need}, warnings {w}")
variant("unknown type", lambda s: s["widgets"].append({"type": "nope"}), ["unknown widget type 'nope'"], [])
variant("unknown slot", lambda s: wid(s, "bullet_list").update(slot="zzz"), ["has no slot 'zzz'"], ["bullet_list"])
variant("on: false", lambda s: wid(s, "bullet_list").update(on=False), [], ["bullet_list"])
variant("empty bullet_list", lambda s: wid(s, "bullet_list").update(items=[]), ["bullet_list: no items"], ["bullet_list"])
variant("empty ring", lambda s: wid(s, "ring").update(rings=0, icon="-"), ["ring: no rings and no icon"], ["ring"])
variant("empty info_card", lambda s: wid(s, "info_card").update(icon="-", title="", subtitle=""), ["info_card: no icon, title or subtitle"], ["info_card"])
variant("empty title_block", lambda s: wid(s, "title_block").update(title="", subtitle=""), ["title_block: no title and no subtitle"], ["title_block"])
_orig = WIDGETS["ring"]
def _boom(*a):
    raise RuntimeError("boom")
WIDGETS["ring"] = _boom
try:
    variant("ring raises", lambda s: None, ["widget 'ring' could not be drawn"], ["ring"])
finally:
    WIDGETS["ring"] = _orig
a1, _ = run_items(sc_of("en", connectors=TEST_LINES))
s3 = sc_of("en", connectors=TEST_LINES); wid(s3, "ring").update(on=False)
a2, _ = run_items(s3)
rec("connector: drawn when both slots hold a widget, dropped when the ring is off", len(a1) == total + 1 and len(a2) == total - cnt["ring"], f"{len(a1)} / {len(a2)} items")
rec("no unexpected [!] in the unit builds", not [x for x in WL if not any(re.search(p, x[1]) for p in ALLOWED)], "; ".join(f"{a}: {b}" for a, b in WL)[:400])

# ---- stills + 3 s renders ---------------------------------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="t4wd_")); out_dir = P / "out" / "t4"; out_dir.mkdir(parents=True, exist_ok=True)
def unexpected(log):
    return [ln.strip() for ln in log.splitlines() if "[!]" in ln and not any(re.search(p, ln) for p in ALLOWED)]
try:
    vid = tmp / "black.mp4"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(vid)], check=True)
    for cv, (W, H) in CV.items():
        for lang in ("en", "ar"):
            tag = f"{cv} {lang}"
            def job(sc, name):
                j = {"template_id": 5, "video": str(vid), "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"}, "background": {"type": "color", "value": "#000000"},
                     "t4": t4_cfg({"canvas_mode": cv, "scenes": [sc]}), "layers": [], "captions": [], "cards": [], "texts": [], "elements": [], "video_layers": [],
                     "output": str(tmp / f"{name}.mp4"), "preview": 3.0}
                (tmp / f"{name}.json").write_text(json.dumps(j), encoding="utf-8"); return str(tmp / f"{name}.json")
            def mont(*args):
                r = subprocess.run([sys.executable, str(P / "montage.py"), *args, "--arabic-mode", "raqm"], cwd=str(tmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
                return r.returncode, r.stdout + r.stderr
            st = sc_of(lang, hold=3, anim="none", stagger=0.0, connectors=[])        # still: everything visible at once
            wid(st, "code_window")["reveal"] = "none"; wid(st, "bullet_list").update(line_step=0.0, line_dur=0.05)
            png = out_dir / f"wd_{cv}_{lang}.png"
            rc, log = mont("--still", "--job", job(st, f"{cv}_{lang}_still"), "--still-out", str(png))
            rec(f"--still {tag}: written, no unexpected warning", rc == 0 and png.is_file() and png.stat().st_size > 1000 and not unexpected(log), f"rc {rc} {unexpected(log) or ''} -> {png.name}")
            rc, log = mont("--job", job(sc_of(lang, hold=3, connectors=[]), f"{cv}_{lang}_r"))
            mp4 = tmp / f"{cv}_{lang}_r.mp4"
            i = probe(str(mp4)) if rc == 0 and mp4.is_file() else None
            rec(f"render {tag}: {W}x{H}, ~3 s, audio, no unexpected warning", bool(i) and (i["w"], i["h"]) == (W, H) and abs(i["duration"] - 3.0) < 0.25 and bool(i["audio"]) and not unexpected(log),
                f"{i and (i['w'], i['h'], round(i['duration'], 2), bool(i['audio']))} {unexpected(log) or ''}" if i else log[-300:])
            if not i:
                continue
            fpng = out_dir / f"wd_{cv}_{lang}_t2p3.png"
            subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", "2.3", "-i", str(mp4), "-frames:v", "1", str(fpng)], check=True)
            a = np.asarray(Image.open(fpng).convert("RGB"), int); lit = a.max(axis=2) > 24      # black video: lit pixels = the scene only
            ys, xs = np.where(lit)
            pl = Q(tag, place, sc_of(lang, connectors=[]), W, H)
            miss = [k for k, v in pl.items() if lit[int(v[1][2][1]):int(v[1][2][3]), int(v[1][2][0]):int(v[1][2][2])].sum() < 40]
            zone = np.zeros_like(lit)
            for v in pl.values():
                r = v[1][2]; zone[max(0, int(r[1]) - 40):int(r[3]) + 40, max(0, int(r[0]) - 40):int(r[2]) + 40] = True
            outside = int((lit & ~zone).sum())
            lo = T4_SAFE - 12
            rec(f"frame 2.3 s {tag}: every widget drawn in its slot, nothing outside, lit pixels within the safe area (glow slack 12 px)",
                len(xs) > 0 and not miss and outside <= 20 and xs.min() >= lo and ys.min() >= lo and xs.max() <= W - lo and ys.max() <= H - lo,
                f"bbox x {xs.min() if len(xs) else '-'}-{xs.max() if len(xs) else '-'} y {ys.min() if len(ys) else '-'}-{ys.max() if len(ys) else '-'} empty {miss or 'none'} outside {outside}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)
