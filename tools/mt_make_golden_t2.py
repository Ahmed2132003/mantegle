#!/usr/bin/env python3
"""Create selftest_golden_t2/ (frames t=0.5/1.5/2.5 + t2_job.json + assets) from the CURRENT montage.py.
Usage: mt_make_golden_t2.py <folder-with-montage.py> [out_dir]   (frames come from a real --job render, 3 s preview)"""
import sys, json, subprocess, shutil, os
from pathlib import Path
root = Path(sys.argv[1]).resolve(); out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else root / "selftest_golden_t2"
sys.path.insert(0, str(root)); sys.argv = ["montage.py", "--help"]
import mt.common, mt.draw, mt.fonts, mt.selftest, mt.templates   # noqa: E402  (tools used `montage as M` before S4)
class _NS:
    def __getattr__(self, n):
        for m in (mt.selftest, mt.templates.t2_lime, mt.draw, mt.common, mt.fonts):
            if hasattr(m, n):
                return getattr(m, n)
        raise AttributeError(n)
M = _NS()
from PIL import Image, ImageDraw
font = root / "selftest_golden" / "selftest_font.ttf"
A = out / "assets"; A.mkdir(parents=True, exist_ok=True)
M._st_make_assets(A)                                   # test.mp4 (5 s, audio), ar.srt, en.srt, element.png ...
subprocess.check_call([M.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=540x720:rate=30:duration=4",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(A / "broll.mp4")])
f = str(font)
cap = {"font": f, "color": "#ffffff", "hl_color": "#BDDE38", "stroke_color": "#000000", "stroke_w": 0, "shadow": False, "mode": "phrase",
       "max_words": 8, "anim": "fade", "anim_dur": 0.25, "ref": "box", "y_pct": None}
t2 = M.t2_cfg({
    "fonts": {"headline": f, "ui": f, "arabic": f},
    "chapters": [{"start": 0.0, "end": 3.0, "num": "01", "label": "Intro", "anim": "slide_up", "anim_dur": 0.35}],
    "cards": [{"media": str(A / "broll.mp4"), "label": "Development", "icon": "code", "slot": 1, "start": 0.3, "hold": 2.5}],
    "about": [{"start": 0.0, "end": 3.0, "paragraph": "Building apps and teaching code.", "title": "ABOUT ME",
               "rows": [{"icon": "laptop", "text": "Web Development"}, {"icon": "phone", "text": "Mobile Development"}, {"icon": "gear", "text": "AI Automation"}]}],
    "panel": {"on": True},
})
cfg = M._st_job(A, 2, out / "t2_golden.mp4", preview=3.0)
cfg.update({"texts": [], "cards": [], "elements": [], "video_layers": [], "t2": t2,
            "captions": [dict(cap, srt=str(A / "ar.srt"), t2_style="box", size=50),
                         dict(cap, srt=str(A / "en.srt"), t2_style="sub", size=30, keywords="Flutter", shadow=True)]})
jp = out / "t2_job.json"; jp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
r = subprocess.run([sys.executable, str(root / "montage.py"), "--job", str(jp), "--arabic-mode", "raqm"], capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout[-400:], r.stderr[-400:], "rc", r.returncode)
for t in ("0.5", "1.5", "2.5"):
    subprocess.check_call([M.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", t, "-i", str(out / "t2_golden.mp4"), "-frames:v", "1", str(out / f"t2_{t}.png")])
# portable copy of the job: paths relative to this folder
rel = json.loads(jp.read_text(encoding="utf-8")); s = json.dumps(rel, ensure_ascii=False).replace(str(out) + "/", "")
(out / "t2_job_portable.json").write_text(json.dumps(json.loads(s), ensure_ascii=False, indent=1), encoding="utf-8")
(out / "meta.json").write_text(json.dumps({"arabic_mode": M.ARABIC_MODE, "font": "selftest_font.ttf (DejaVu Sans Bold) for headline/ui/arabic",
    "note": "frames of a real --job render (3 s preview, 1080x1920) of the ORIGINAL Template 2 code: captions (box+sub), chapter tag, card, about block, panel",
    "times": [0.5, 1.5, 2.5]}, indent=1))
shutil.copy(font, out / "selftest_font.ttf")
print("ok", sorted(p.name for p in out.iterdir()))
