import sys, json, subprocess, os
from pathlib import Path
P = Path(os.environ.get("MT_PROJECT", Path(__file__).resolve().parent.parent)); O = Path(os.environ.get("MT_OUT", "/tmp/mt_quick_out")); O.mkdir(exist_ok=True, parents=True)
sys.path.insert(0, str(P)); sys.argv = ["montage.py", "--help"]
import mt.common, mt.draw, mt.fonts, mt.selftest, mt.templates   # noqa: E402  (tools used `montage as M` before S4)
class _NS:
    def __getattr__(self, n):
        for m in (mt.selftest, mt.templates.t2_lime, mt.draw, mt.common, mt.fonts):
            if hasattr(m, n):
                return getattr(m, n)
        raise AttributeError(n)
M = _NS()
from PIL import Image
import numpy as np
A = P / "selftest_golden_t2" / "assets"
def frames(mp4, gold_prefix, gold_dir):
    res = []
    for t in ("0.5", "1.5", "2.5"):
        png = O / f"{Path(mp4).stem}_{t}.png"
        subprocess.check_call([M.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", t, "-i", str(mp4), "-frames:v", "1", str(png)])
        a = np.asarray(Image.open(png).convert("RGB"), float); b = np.asarray(Image.open(gold_dir / f"{gold_prefix}_{t}.png").convert("RGB"), float)
        res.append(round(float(abs(a - b).mean()), 3))
    return res
# T1 job (same construction as the selftest's own golden job), run from /tmp
c1 = M._st_job(A, 1, O / "t1_job_out.mp4", preview=3.0)
for c in c1["captions"]: c["font"] = str(P / "selftest_golden" / "selftest_font.ttf")
f = str(P / "selftest_golden" / "selftest_font.ttf")
for k in ("texts", "cards"):
    for e in c1[k]: e["font"] = f
j1 = O / "t1_job.json"; j1.write_text(json.dumps(c1, ensure_ascii=False, indent=1), encoding="utf-8")
r = subprocess.run([sys.executable, str(P / "montage.py"), "--job", str(j1), "--arabic-mode", "raqm"], cwd="/tmp", capture_output=True, text=True, encoding="utf-8", errors="replace")
print("T1 --job rc", r.returncode, "| tail:", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])
print("T1 frame diffs vs selftest_golden/t1_*.png (0.5/1.5/2.5):", frames(O / "t1_job_out.mp4", "t1", P / "selftest_golden"))
# T2 job: the stored golden job with paths re-pointed to this folder + output redirected, run from /tmp
txt = (P / "selftest_golden_t2" / "t2_job.json").read_text(encoding="utf-8")
c2 = json.loads(txt)
def fix(o):
    if isinstance(o, str): return o.replace("/home/claude/work/", str(P) + "/")
    if isinstance(o, list): return [fix(x) for x in o]
    if isinstance(o, dict): return {k: fix(v) for k, v in o.items()}
    return o
c2 = fix(c2); c2["output"] = str(O / "t2_job_out.mp4")
j2 = O / "t2_job.json"; j2.write_text(json.dumps(c2, ensure_ascii=False, indent=1), encoding="utf-8")
import time; _t0 = time.perf_counter()
r = subprocess.run([sys.executable, str(P / "montage.py"), "--job", str(j2), "--arabic-mode", "raqm"], cwd="/tmp", capture_output=True, text=True, encoding="utf-8", errors="replace")
print("T2 wall time %.2fs" % (time.perf_counter() - _t0)); print("T2 --job rc", r.returncode, "| tail:", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])
print("T2 frame diffs vs selftest_golden_t2/t2_*.png (0.5/1.5/2.5):", frames(O / "t2_job_out.mp4", "t2", P / "selftest_golden_t2"))
