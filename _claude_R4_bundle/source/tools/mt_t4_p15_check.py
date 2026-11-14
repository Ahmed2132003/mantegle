"""P15 check (put in tools/): python tools/mt_t4_p15_check.py
Unit checks of widget 'code_window' + --still renders of the R5 / R6 snippets on both canvases -> out/t4/p15_<canvas>.png (VIEW them vs R5 / R6)."""
import json, os, subprocess, sys, tempfile, shutil
from pathlib import Path
import numpy as np
from PIL import Image
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
rows = []
def rec(name, ok, detail=""):
    rows.append(bool(ok)); print(f"{'PASS' if ok else 'FAIL':5} {name}  {detail}")
import mt.templates  # noqa: E402
from mt.common import FFMPEG  # noqa: E402
from mt.templates.t4.cfg import t4_cfg  # noqa: E402
from mt.templates.t4.scenes_reg import WIDGETS  # noqa: E402
from mt.templates.t4.scenes import SLOTS, t4_scenes_items  # noqa: E402
from mt.templates.t4.scenes_widgets import R5_CODE, t4_code_window, t4_tokenize, t4_widget_line_items  # noqa: E402
rec("registered + slots", "code_window" in WIDGETS and all("code" in SLOTS["web_dev"][a] for a in ("portrait", "landscape")))
k = lambda s, l: [(t, c) for t, c in t4_tokenize(s, l) if t.strip()]
rec("tokenizer py", k('def f():', "py")[0] == ("def", "kw_a") and ("f", "fn") in k('def f():', "py") and ("return", "kw_b") in k("return 1", "py")
    and ("print", "call_b") in k("print(x)", "py") and k('x = "a # b"', "py")[-1][1] == "str" and k("# hi", "py") == [("# hi", "com")] and ("1", "num") in k("return 1", "py"))
rec("tokenizer js", ("const", "kw_a") in k("const a = 1;", "js") and k("// c", "js")[0][1] == "com" and ("`Hi ${n}`", "str") in k("x = `Hi ${n}`", "js")
    and ("log", "call_b") in k("console.log(1)", "js") and ("add", "fn") in k("function add(a) {}", "js") and ("greet", "text") in k("greet(1)", "js"))
rec("tokenizer junk never raises", t4_tokenize(None, "py") == [] and t4_tokenize("x", "zz") == [("x", "text")])
JS = 'const greet = (name) => `Hi ${name}`;  // comment\nconsole.log(greet("Ahmed"), 42);\nfunction add(a, b) { return a + b; }\n// أهلا بالعالم'
AR = 'def f():\n    return 1\n\n# مرحبا بكم في منصة Eduvia\nprint(f())'
ok, bad = True, []
for nm, sp in (("r5", {}), ("js", {"file": "a.js", "code": JS}), ("ar", {"code": AR}), ("junk", {"code": 5, "lang": 3, "file": None}), ("empty", {"code": ""}), ("many", {"code": "x\n" * 40})):
    for box in ((0, 0, 434, 242), (0, 0, 543, 289)):
        s = t4_code_window(sp, box, {})
        if s is None or s.info.get("origin") is None or s.width < box[2] or s.height < box[3]:
            ok = False; bad.append(nm)
rec("widget sprites (R5 + R6 size, junk / empty / 40 lines)", ok, ",".join(bad))
t = t4_code_window({"reveal": "typewriter"}, (0, 0, 434, 242), {}); b = t4_code_window({}, (0, 0, 434, 242), {})
its = t4_widget_line_items(t, 300, 300, 1.0, 7.0, 0.45)
rec("typewriter: 4 non-empty lines -> 4 'reveal' Items, staggered; baked mode has no lines; window sprite differs (code not baked)",
    len(its) == 4 and all(i.anim == "reveal" for i in its) and its[1].start - its[0].start > 0.3 and not b.info.get("lines") and t.tobytes() != b.tobytes())
tmp = Path(tempfile.mkdtemp(prefix="t4p15_")); out_dir = P / "out" / "t4"; out_dir.mkdir(parents=True, exist_ok=True)
try:
    vid = tmp / "v.mp4"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(vid)], check=True)
    for cv, (W, H) in (("reels", (1080, 1920)), ("youtube", (1920, 1080))):
        shots = {}
        for nm, sc in (("off", None), ("r5", {"widgets": [{"type": "code_window", "code": R5_CODE}]}), ("js", {"widgets": [{"type": "code_window", "file": "app.js", "code": JS}]}),
                       ("ar", {"widgets": [{"type": "code_window", "code": AR}]})):
            t4 = t4_cfg({"canvas_mode": cv, "scenes": [dict(sc, start=0, hold=3, anim="none")] if sc else []})
            job = {"template_id": 5, "video": str(vid), "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"}, "background": {"type": "color", "value": "#000000"},
                   "t4": t4, "layers": [], "captions": [], "cards": [], "texts": [], "elements": [], "video_layers": [], "output": str(tmp / "o.mp4"), "preview": 1.5}
            (tmp / f"{cv}_{nm}.json").write_text(json.dumps(job), encoding="utf-8")
            png = out_dir / (f"p15_{cv}.png" if nm == "r5" else f"p15_{cv}_{nm}.png")
            r = subprocess.run([sys.executable, str(P / "montage.py"), "--still", "--job", str(tmp / f"{cv}_{nm}.json"), "--still-out", str(png), "--arabic-mode", "raqm"],
                               cwd=str(tmp), capture_output=True, text=True, encoding="utf-8", errors="replace")
            shots[nm] = np.asarray(Image.open(png).convert("RGB"), int) if r.returncode == 0 and png.is_file() else None
        ok = all(v is not None for v in shots.values())
        if ok:
            d = np.abs(shots["r5"] - shots["off"]).max(axis=2) > 8
            ys, xs = np.where(d.any(axis=1))[0], np.where(d.any(axis=0))[0]
            want = (48, 295, 482, 537) if cv == "reels" else (52, 316, 595, 605)
            ok = len(xs) and abs(xs[0] - want[0]) <= 8 and abs(xs[-1] - want[2]) <= 8 and abs(ys[0] - want[1]) <= 8 and abs(ys[-1] - want[3]) <= 8
            rec(f"--still {cv}: window box vs R5 / R6 (+-8 px)", ok, f"x {xs[0]}-{xs[-1]} y {ys[0]}-{ys[-1]} want {want}" if len(xs) else "nothing drawn")
        else:
            rec(f"--still {cv}", False, "render failed")
    items = t4_scenes_items({"canvas": [1080, 1920], "t4": t4_cfg({"canvas_mode": "reels", "scenes": [{"widgets": [{"type": "code_window", "reveal": "typewriter"}], "hold": 6}]})}, 8.0)
    rec("engine: typewriter scene = window Item + 4 line Items", len(items) == 5 and sum(i.anim == "reveal" for i in items) == 4, f"{len(items)} items")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(sum(rows), "pass,", len(rows) - sum(rows), "fail"); sys.exit(0 if all(rows) else 1)
