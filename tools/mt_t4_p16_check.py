"""P16 check (put in tools/): python tools/mt_t4_p16_check.py
Joint check of the web_dev title scene (title_block + code_window + ring + bullet_list + info_card) on R5 (1080x1920) and R6 (1920x1080):
ink-rect overlaps, 48 px safe margin, connector-vs-widget crossings, stagger, widget failure isolation, stills + 3 s renders -> out/t4/p16_*.
EDIT AR_SPEC / EN_SPEC below with the real cfg keys of ring / bullet_list / info_card (empty dict = widget defaults)."""
import json, os, re, subprocess, sys, tempfile, shutil
from pathlib import Path
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
import mt.templates  # noqa: E402
from mt.common import FFMPEG  # noqa: E402
from mt.templates.t4 import scenes as S  # noqa: E402
from mt.templates.t4.cfg import t4_cfg  # noqa: E402
from mt.templates.t4.scenes_reg import register_widget  # noqa: E402
from mt.templates.t4.nameplate import T4_SAFE  # noqa: E402

EN_SPEC = {"title_block": {"title": "Web Development", "subtitle": "BUILD. SHIP. SCALE."}, "code_window": {}, "ring": {}, "bullet_list": {}, "info_card": {}}
AR_SPEC = {"title_block": {"title": "تطوير الويب", "subtitle": "ابنِ وانشر"}, "code_window": {}, "ring": {}, "bullet_list": {}, "info_card": {}}   # <- add Arabic text keys
CANV = {"reels": (1080, 1920), "youtube": (1920, 1080)}
rows, warns = [], []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
def hook_warn():                                   # collect every t4_warn, whichever module imported it
    def w(msg, *a, **k): warns.append(str(msg))
    for m in [m for n, m in list(sys.modules.items()) if n.startswith("mt.templates.t4") and hasattr(m, "t4_warn")]: m.t4_warn = w
def scene(spec, **kw):
    return dict({"preset": "web_dev", "widgets": [dict(type=t, **v) for t, v in spec.items()], "start": 0, "hold": 3, "stagger": 0.2}, **kw)
def cfg_for(cv, sc): 
    W, H = CANV[cv]; return {"canvas": [W, H], "t4": t4_cfg({"canvas_mode": cv, "scenes": [sc]})}
def seg_hits_rect(a, b, r, pad=1):                 # sampled segment vs rect (connectors are straight / elbow polylines)
    n = max(2, int(max(abs(b[0]-a[0]), abs(b[1]-a[1])))); 
    return any(r[0]+pad < a[0]+(b[0]-a[0])*i/n < r[2]-pad and r[1]+pad < a[1]+(b[1]-a[1])*i/n < r[3]-pad for i in range(n+1))
hook_warn()
for lang, spec in (("en", EN_SPEC), ("ar", AR_SPEC)):
    for cv, (W, H) in CANV.items():
        tag = f"{cv}/{lang}"; warns.clear(); sc = S.t4_scenes_cfg([scene(spec)])[0]; s = min(W, H) / 1080
        ctx = {"W": W, "H": H, "s": s, "aspect": S._aspect(W, H), "preset": "web_dev", "cfg": cfg_for(cv, scene(spec))}
        rects, placed = {}, []
        S._widget_items(ctx["cfg"], sc, "p16", (0.0, 3.0), ctx, S.SLOTS["web_dev"][ctx["aspect"]], rects, placed)
        rec(f"{tag}: all widgets placed", len(rects) == len(spec), f"got {sorted(rects)}")
        m, bad = T4_SAFE * s - 1, [k for k, r in rects.items() if r[0] < T4_SAFE*s-1 or r[1] < T4_SAFE*s-1 or r[2] > W-T4_SAFE*s+1 or r[3] > H-T4_SAFE*s+1]
        rec(f"{tag}: ink inside 48 px safe margin", not bad, ",".join(bad))
        ov = [(a, b) for i, (a, ra) in enumerate(placed) for b, rb in placed[i+1:] if ra[0] < rb[2] and rb[0] < ra[2] and ra[1] < rb[3] and rb[1] < ra[3]]
        rec(f"{tag}: no sprite ink overlap", not ov, str(ov))
        lines = S._lines(S.CONNECTORS["web_dev"][ctx["aspect"]]) or []; hit = []
        for ln in lines:
            pts = [S._resolve(p, rects, s) for p in ln["points"]]
            if any(p is None for p in pts): continue
            named = {re.sub(r"-(top|bottom|left|right|center)$", "", p) for p in ln["points"] if isinstance(p, str)}
            for k, r in rects.items():
                if k not in named and any(seg_hits_rect(pts[i], pts[i+1], r) for i in range(len(pts)-1)): hit.append((ln["points"], k))
        rec(f"{tag}: connectors ({len(lines)}) cross no other widget", not hit, str(hit))
        its = S.t4_scenes_items(ctx["cfg"], 6.0); st = sorted({round(i.start, 2) for i in its})
        rec(f"{tag}: stagger (distinct start times, ~0.2 s apart)", len(st) >= len(spec) and all(0.1 <= b-a <= 0.35 for a, b in zip(st[:len(spec)], st[1:len(spec)])), str(st))
        rec(f"{tag}: no unexpected warnings", not [w for w in warns if "overlap" in w or "could not" in w], "; ".join(warns[:3]))
# failure isolation: one widget raises, one is unknown, one is off -> others still drawn, one warning each
register_widget("t4_boom", lambda spec, box, ctx: 1 / 0)
for cv in CANV:
    warns.clear(); sp = scene(EN_SPEC); sp["widgets"] += [{"type": "t4_boom", "slot": "ring"}, {"type": "nope", "slot": "card"}, {"type": "ring", "slot": "zzz"}, {"type": "info_card", "on": False}]
    base = len(S.t4_scenes_items(cfg_for(cv, scene(EN_SPEC)), 6.0)); n = len(S.t4_scenes_items(cfg_for(cv, sp), 6.0))
    rec(f"{cv}: failing / unknown / bad-slot widgets are skipped, rest unchanged", n <= base and sum("boom" in w or "nope" in w or "zzz" in w for w in warns) >= 3, f"items {n} vs {base}; warns {len(warns)}")
# stills + 3 s renders
tmp, out = Path(tempfile.mkdtemp(prefix="t4p16_")), P / "out" / "t4"; out.mkdir(parents=True, exist_ok=True)
try:
    vid = tmp / "v.mp4"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(vid)], check=True)
    for cv, (W, H) in CANV.items():
        for lang, spec in (("en", EN_SPEC), ("ar", AR_SPEC)):
            job = {"template_id": 5, "video": str(vid), "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"}, "background": {"type": "color", "value": "#000000"},
                   "t4": t4_cfg({"canvas_mode": cv, "scenes": [scene(spec, hold=3, anim="none")]}), "layers": [], "captions": [], "cards": [], "texts": [], "elements": [], "video_layers": [],
                   "output": str(out / f"p16_{cv}_{lang}.mp4"), "preview": 3}
            jf = tmp / f"{cv}_{lang}.json"; jf.write_text(json.dumps(job), encoding="utf-8")
            for kind, extra in (("still", ["--still", "--still-out", str(out / f"p16_{cv}_{lang}.png")]), ("render", [])):
                r = subprocess.run([sys.executable, str(P / "montage.py"), "--job", str(jf), "--arabic-mode", "raqm"] + extra, cwd=str(tmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
                w = [l for l in (r.stdout + r.stderr).splitlines() if re.search(r"warn", l, re.I)]
                ok = r.returncode == 0 and (out / (f"p16_{cv}_{lang}.png" if kind == "still" else f"p16_{cv}_{lang}.mp4")).is_file()
                rec(f"{cv}/{lang} {kind}: exit 0 + file + no warnings", ok and not w, "; ".join(w[:3]) or (r.stderr[-200:] if not ok else ""))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)
