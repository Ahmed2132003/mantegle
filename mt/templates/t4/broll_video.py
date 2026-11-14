"""mt.templates.t4.broll_video - Template 4: the baking half of the 'broll' module. The media (video file / image / gray placeholder) is cover-fitted to
the canvas, muted (-an) and written as a video layer for FFmpeg (area 'box' = under the frame plate, key '_xy' [0, 0]).
  anim 'fade' / 'none' : ONE ffmpeg transcode (libx264); the cross-fade is the layer's own 'fade' (alpha) - no per-frame Python.
  anim 'wipe'          : frames piped through Python, cut by the diagonal wipe mask (t4_broll_mask) and written as an alpha clip (qtrle).
A video that ends before the window does holds its last frame (tpad clone); a clip without seg_end (and seg_start 0) loops. Speaker audio is never touched
(the layer is muted and never mapped). Public: t4_broll_prepare_layers(cfg, info, tmpdir) -> list of video layers (called by cards_video)."""
import math
import os
import subprocess

from PIL import Image

from mt.common import FFMPEG, _read_exact
from mt.templates.t4.broll import t4_broll_mask, t4_broll_plan
from mt.templates.t4.warn import t4_warn


def _fps_s(fps):
    return f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)


def _src_args(plan, fps_s):
    c, m, W, H = plan["c"], plan["media"], plan["W"], plan["H"]
    if m["kind"] == "gray":
        return ["-f", "lavfi", "-i", f"color=c=0x707478:s={W}x{H}:r={fps_s}"]
    if m["kind"] == "image":
        return ["-loop", "1", "-framerate", fps_s, "-i", m["path"]]
    ss, se = c["seg_start"] or 0.0, c["seg_end"]
    a = ["-stream_loop", "-1"] if (se is None and ss == 0.0) else []
    a += ["-ss", "%.3f" % ss, "-i", m["path"]]
    return a + (["-t", "%.3f" % (se - ss)] if se is not None else [])


def _vf(plan, fps_s, pix):
    W, H = plan["W"], plan["H"]
    return (f"fps={fps_s},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
            f"tpad=stop_mode=clone:stop=-1,format={pix}")


def _transcode(plan, fps_s, nfr, tmpdir):
    out = os.path.join(tmpdir, "t4broll.mp4")
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *_src_args(plan, fps_s), "-an", "-vf", _vf(plan, fps_s, "yuv420p"),
           "-frames:v", str(nfr), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", out]
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError(r.stderr[-300:] or "FFmpeg could not write the clip")
    return out


def _bake_wipe(plan, nfr, fps_s, fps_f, tmpdir):
    W, H, j0 = plan["W"], plan["H"], plan["j0"]
    out = os.path.join(tmpdir, "t4broll.mov")
    need, blank = W * H * 3, bytes(W * H * 4)
    rd = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", *_src_args(plan, fps_s), "-an", "-vf", _vf(plan, fps_s, "rgb24"),
                           "-frames:v", str(nfr), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    wr = subprocess.Popen([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", f"{W}x{H}",
                           "-framerate", fps_s, "-i", "pipe:0", "-c:v", "qtrle", "-pix_fmt", "argb", out],
                          stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
    last = None
    try:
        for i in range(nfr):
            raw = _read_exact(rd.stdout, need)
            if len(raw) != need:                                   # the source gave nothing more: hold the last frame
                raw = last if last is not None else b"\x70" * need
            last = raw
            mask = t4_broll_mask(plan, (j0 + i) / fps_f)
            if isinstance(mask, str) and mask == "empty":
                wr.stdin.write(blank)
                continue
            im = Image.frombytes("RGB", (W, H), raw).convert("RGBA")
            if not isinstance(mask, str):
                im.putalpha(mask)
            wr.stdin.write(im.tobytes())
    except (BrokenPipeError, OSError):
        pass
    finally:
        rd.kill()
        rd.wait()
        try:
            wr.stdin.close()
        except Exception:
            pass
    err = wr.stderr.read().decode("utf-8", "replace")
    if wr.wait() != 0 or not os.path.isfile(out):
        raise RuntimeError(err[-300:] or "FFmpeg could not write the clip")
    return out


def _bake(plan, info, dur_eff, tmpdir):
    fps = info["fps"]
    fps_f, fps_s = float(fps), _fps_s(fps)
    nfr = min(plan["j1"], int(math.ceil(dur_eff * fps_f))) - plan["j0"]
    if nfr < 1:
        return None
    print("Preparing b-roll clip (%d frames, %s)..." % (nfr, plan["anim"]))
    path = _bake_wipe(plan, nfr, fps_s, fps_f, tmpdir) if plan["anim"] == "wipe" else _transcode(plan, fps_s, nfr, tmpdir)
    return {"path": path, "start": plan["t0"], "end": min(plan["t1"], dur_eff), "area": "box", "mode": "fit",
            "fade": plan["d"] if plan["anim"] == "fade" else 0.0, "_xy": [0, 0]}


def t4_broll_prepare_layers(cfg, info, tmpdir):
    """-> [video layer] for the b-roll clip, or []. Never raises: a failing bake warns once and the takeover shows only its decoration."""
    try:
        plan = t4_broll_plan(cfg, info["duration"], float(info["fps"]))
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
        t4_warn("b-roll: the clip could not be prepared (%s: %s) - skipped." % (type(e).__name__, e))
        return []