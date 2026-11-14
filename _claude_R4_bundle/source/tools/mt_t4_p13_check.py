"""tools/mt_t4_p13_check.py - T4-P13: a 3 s video card on both canvases with a real mp4.
Makes a 3 s main mp4 (with audio) + a 1.5 s clip mp4 (with audio, to prove the card is muted), renders a job with two cards (a clip file with label +
connector, and a segment of the original video) on reels 1080x1920 and youtube 1920x1080, plus a --still of each.
Outputs: out/t4/p13_<canvas>.mp4 / .png. Exit code 1 when a check fails."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PIL import Image, ImageChops, ImageStat  # noqa: E402

from mt.common import FFMPEG, FFPROBE, get_template  # noqa: E402
import mt.templates  # noqa: E402,F401  (fills TEMPLATE_REGISTRY)
from mt.render import preflight_cfg, render, render_still  # noqa: E402
from mt.templates.t4.cards import t4_card_plans  # noqa: E402

OUT = BASE / "out" / "t4"
ASSETS = OUT / "p13_assets"


def run(cmd):
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_assets():
    ASSETS.mkdir(parents=True, exist_ok=True)
    main, clip = ASSETS / "main.mp4", ASSETS / "clip.mp4"
    run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(main)])
    run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=1.5",
         "-f", "lavfi", "-i", "sine=frequency=880:duration=1.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)])
    return str(main), str(clip)


def make_job(main, clip, W, H, out):
    return {"template_id": 5, "video": main, "canvas": [W, H], "video_box": {"x": 0, "y": 0, "w": W, "h": H, "mode": "fill"},
            "background": {"type": "color", "value": "#000000"}, "layers": [], "captions": [], "texts": [], "cards": [], "elements": [],
            "video_layers": [], "output": str(out), "preview": None,
            "t4": {"canvas_mode": "reels" if H > W else "youtube", "fit": "fill", "cards": [
                {"media": clip, "label": "LIVE CODING DEVELOPMENT", "anchor": "top-right", "width": 480, "start": 0.2, "hold": 2.6,
                 "connector": {"target": ["25%", "60%"]}},
                {"media": "original", "seg_start": 0.5, "seg_end": 2.5, "label": "ORIGINAL CLIP", "anchor": "bottom-left", "width": 420,
                 "start": 0.4, "hold": 2.4}]}}


def info_of(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    j = json.loads(r.stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    return int(v["width"]), int(v["height"]), float(j["format"]["duration"]), sum(1 for s in j["streams"] if s["codec_type"] == "audio")


def grab(video, t, png):
    run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(png)])
    return Image.open(png).convert("RGB")


def pic_box(plan, inset=0.15):
    x0 = plan["cx"] - plan["size"][0] / 2.0 + plan["pic"][0]
    y0 = plan["cy"] - plan["size"][1] / 2.0 + plan["pic"][1]
    w, h = plan["pic"][2], plan["pic"][3]
    return x0, y0, w, h, (int(x0 + inset * w), int(y0 + inset * h), int(x0 + (1 - inset) * w), int(y0 + (1 - inset) * h))


def cyan_edge(im, x0, y0, w, h):
    """Sanity: a cyan-ish pixel on the left border of the picture rect at mid height (the neon border Item over the clip)."""
    y = int(y0 + h / 2.0)
    for x in range(int(x0) - 6, int(x0) + 14):
        if 0 <= x < im.width:
            r, g, b = im.getpixel((x, y))
            if b > 200 and g > 150 and r < 170:
                return True
    return False


def check(name, W, H, main, clip):
    fails, notes = [], []
    out = OUT / ("p13_%s.mp4" % name)
    job = make_job(main, clip, W, H, out)
    render(copy.deepcopy(job))
    w, h, dur, aud = info_of(out)
    if (w, h) != (W, H):
        fails.append("size %dx%d != %dx%d" % (w, h, W, H))
    if abs(dur - 3.0) > 0.3:
        fails.append("duration %.2f" % dur)
    if aud != 1:
        fails.append("audio streams: %d (want exactly 1 - the cards are muted)" % aud)
    cfg = preflight_cfg(copy.deepcopy(job))
    tmp = tempfile.mkdtemp(prefix="p13_")
    try:
        get_template(cfg)["build_background"](cfg, tmp)
        plans = t4_card_plans(cfg, 3.0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if len(plans) != 2:
        fails.append("expected 2 video card plans, got %d" % len(plans))
    f1, f2 = grab(out, 1.0, OUT / ("p13_%s_t1.png" % name)), grab(out, 2.0, OUT / ("p13_%s_t2.png" % name))
    for p in plans:
        x0, y0, cw, ch, box = pic_box(p)
        d = ImageStat.Stat(ImageChops.difference(f1.crop(box), f2.crop(box)).convert("L")).mean[0]
        sd = max(ImageStat.Stat(f1.crop(box)).stddev)
        edge = cyan_edge(f1, x0, y0, cw, ch)
        notes.append("card %d (%s): clip moves diff=%.1f detail=%.0f border=%s" % (p["idx"] + 1, p["kind"], d, sd, edge))
        if d < 2.0:
            fails.append("card %d picture does not change between t=1.0 and t=2.0 (diff %.2f)" % (p["idx"] + 1, d))
        if sd < 8:
            fails.append("card %d picture looks flat (stddev %.1f)" % (p["idx"] + 1, sd))
        if not edge:
            fails.append("card %d: no cyan border pixel at its left edge" % (p["idx"] + 1))
    left = [str(x) for x in list(OUT.glob("montage_*")) + list(OUT.rglob("*.mov"))]
    if left:
        fails.append("temp files left behind: %s" % left[:3])
    png = OUT / ("p13_%s.png" % name)
    render_still(copy.deepcopy(job), str(png), 1.0)
    st = Image.open(png)
    if st.size != (W, H):
        fails.append("still size %s" % (st.size,))
    elif plans:
        _x, _y, _w, _h, box = pic_box(plans[0])
        if max(ImageStat.Stat(st.convert("RGB").crop(box)).stddev) < 8:
            fails.append("still: card 1 picture looks flat")
    print("[%s] %s  |  %s  | %dx%d %.2fs audio=%d" % (name, "FAIL" if fails else "PASS", "; ".join(notes), w, h, dur, aud))
    for f in fails:
        print("      FAIL: " + f)
    return not fails


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    m, c = make_assets()
    ok = check("reels", 1080, 1920, m, c)
    ok = check("youtube", 1920, 1080, m, c) and ok
    print("T4-P13 card check: " + ("ALL PASS" if ok else "FAILED"))
    print("Look at out/t4/p13_reels.png, p13_youtube.png (+ _t1 / _t2 frames) and compare with R2 / R8.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())