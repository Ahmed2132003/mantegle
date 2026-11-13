"""mt.templates.t4.split_video - Template 4: the baking half of the 'split' module. The media (video file / image) is cut by the diagonal polygon at every
frame of the entry wipe, the hold and the exit wipe and written as a small alpha clip (qtrle, only the polygon's bounding box). FFmpeg overlays it as a
video layer with area 'box' (= UNDER the frame plate, above the speaker video) at a fixed position (key '_xy').
The window is snapped to the frame grid (plan j0 / j1) and the same t4_split_u is used by the seam Items, so seam and media edge move together.
Video media: decoded straight at the patch size onto a pipe (one frame in memory), muted; without seg_end it loops, otherwise it plays once and
holds its last frame. Image media: one picture, composed once per distinct wipe step.
Public: t4_split_prepare_layers(cfg, info, tmpdir) -> list of video layers (called by cards_video.t4_prepare_card_layers)."""
import math
import os
import subprocess

from PIL import Image

from mt.common import FFMPEG, _read_exact
from mt.templates.t4.split import t4_split_cover, t4_split_mask, t4_split_plan, t4_split_u
from mt.templates.t4.warn import t4_warn

GRAY = b"\x5c"


def _reader_cmd(plan, nfr, fps_s):
    c, m = plan["c"], plan["media"]
    _x, _y, w, h = plan["patch"]
    ss, se = c["seg_start"] or 0.0, c["seg_end"]
    if se is not None and se - ss < 0.05:
        se = None
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"]
    if se is None:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-ss", "%.3f" % ss, "-i", str(m["path"])]
    if se is not None:
        cmd += ["-t", "%.3f" % (se - ss)]
    return cmd + ["-an", "-vf", f"fps={fps_s},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format=rgb24",
                  "-frames:v", str(nfr), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


def _bake(plan, info, dur_eff, tmpdir):
    fps = info["fps"]
    fps_f = float(fps)
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    x0, y0, w, h = plan["patch"]
    j0 = plan["j0"]
    nfr = min(plan["j1"], int(math.ceil(dur_eff * fps_f))) - j0
    if nfr < 1:
        return None
    out = os.path.join(tmpdir, "t4split.mov")
    need, blank, media = w * h * 3, bytes(w * h * 4), plan["media"]
    video = media["kind"] == "video"
    still_pic = None if video else t4_split_cover(media["img"], (w, h))
    print("Preparing split-screen clip (%d frames)..." % nfr)
    rd = subprocess.Popen(_reader_cmd(plan, nfr, fps_s), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL) if video else None
    wr = subprocess.Popen([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", f"{w}x{h}",
                           "-framerate", fps_s, "-i", "pipe:0", "-c:v", "qtrle", "-pix_fmt", "argb", out],
                          stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
    last, ckey, cdata = None, None, None
    try:
        for i in range(nfr):
            u = t4_split_u(plan, (j0 + i) / fps_f)
            pic = still_pic
            if video:
                raw = _read_exact(rd.stdout, need)
                raw = raw if len(raw) == need else (last if last is not None else GRAY * need)      # the source ended: hold the last frame
                last = raw
                pic = Image.frombytes("RGB", (w, h), raw)
            if u <= 1e-6:
                data = blank
            elif not video and round(u, 4) == ckey:
                data = cdata
            else:
                mask = t4_split_mask(plan, u)
                if mask is None:
                    data = blank
                else:
                    rgba = pic.convert("RGBA")
                    rgba.putalpha(mask)
                    data = rgba.tobytes()
                ckey, cdata = (None if video else round(u, 4)), data
            wr.stdin.write(data)
        wr.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    finally:
        if rd is not None:
            rd.kill()
            rd.wait()
    err = wr.stderr.read().decode("utf-8", "replace")
    if wr.wait() != 0 or not os.path.isfile(out):
        raise RuntimeError(err[-300:] or "FFmpeg could not write the clip")
    return {"path": out, "start": plan["t0"], "end": min(plan["t1"], dur_eff), "area": "box", "mode": "fit", "fade": 0.0, "_xy": [x0, y0]}


def t4_split_prepare_layers(cfg, info, tmpdir):
    """-> [video layer] for the split media, or []. Never raises: a failing bake warns once and the split shows only its seam + labels."""
    try:
        plan = t4_split_plan(cfg, info["duration"], float(info["fps"]))
        if plan is None:
            return []
        dur_eff = info["duration"]
        if cfg.get("preview"):
            dur_eff = min(dur_eff, float(cfg["preview"]))
        if plan["t0"] >= dur_eff:
            return []
        layer = _bake(plan, info, dur_eff, tmpdir)
        return [layer] if layer else []
    except (Exception, SystemExit) as e:
        t4_warn("split: the clip could not be prepared (%s: %s) - skipped." % (type(e).__name__, e))
        return []