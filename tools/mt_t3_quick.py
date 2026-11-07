"""Run only the Template 3 selftest checks (fast): python tools/mt_t3_quick.py"""
import sys, tempfile, shutil, io, contextlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mt.templates
from mt import selftest as S
rows = []
def rec(n, st, d=""):
    rows.append((n, st, d)); print(f"{st:5} {n}  {d}")
def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)
tmp = Path(tempfile.mkdtemp(prefix="t3q_"))
S._st_make_assets(tmp / "assets")
for name, fn in S.SELFTEST_CHECKS:
    if name.startswith("T3-"):
        try:
            fn(rec, quiet, S._st_feed, tmp / "assets", tmp)
        except BaseException as e:
            rec(name, "FAIL", "crashed: " + repr(e))
shutil.rmtree(tmp, ignore_errors=True)
print(sum(r[1] == "PASS" for r in rows), "pass,", sum(r[1] == "FAIL" for r in rows), "fail")
