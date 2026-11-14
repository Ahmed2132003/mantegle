"""mt.templates.t4.cards_video - Template 4: VIDEO cards (refs R2 right card, R8 PiP card) - the baking half of the 'cards' module.
A card whose media is a clip file or a segment of the original video ('original' + seg_start / seg_end, see cards.py) is drawn in two layers:
  - the PICTURE = a muted clip cut by the card's chamfer mask, baked here into a small alpha video (qtrle) and overlaid by FFmpeg as a video
    layer (area 'canvas', key '_xy'), i.e. above the foreground plate, exactly like the T3 floating video cards;
  - the neon border + accent dashes + label tag = the ordinary card sprite (cards_art, with_picture=False), an Item over the clip.
Both use the same sprite size, centre and Item animation (t4_pop / chosen anim), so border and picture pop in and fade out together.
Memory: FFmpeg decodes the source straight at the picture's pixel size (-ss / -t / fps / scale / crop / rgb24 on a pipe = the pre-scaled proxy of
prepare_video_layers), so only one small frame is held at a time; nothing is written but the final alpha clip. The clip is muted (-an).
Source rules: 'original' starts at seg_start (default = the card's start time); a clip file loops when it has no seg_end and starts at 0, otherwise
it plays once; when the source ends before the card does, the last frame is held. Missing source / bake failure -> one t4_warn, that card has no picture.
Public: t4_prepare_card_layers(cfg, info, tmpdir) = the registry hook prepare_layers for id 5 (render.py calls it for template ids 2, 3, 5)."""
import math
import os
import subprocess
from pathlib import Path

from PIL import Image

from mt.anim import anim_state
from mt.common import FFMPEG, _read_exact
from mt.draw import draw_item
from mt.templates.t4.cards import _make_item, t4_card_plans
from mt.templates.t4.cards_art import t4_card_mask
from mt.templates.t4.warn import t4_warn

SAMPLES = 40                    # anim_state samples per direction when measuring how far the animated card reaches
MARGIN = 6                      # px around that reach
GRAY = b"\x5c"                  # filler byte when the source gives no frame at all


def _anim_name(c):
    return "t4_pop" if c["anim"] in ("auto", "pop") else c["anim"]


def _even(a0, a1, limit):
    if (a1 - a0) % 2:
        if a1 < limit:
            a1 += 1
        elif a0 > 0:
            a0 -= 1
        else:
            a1 -= 1
    return a0, a1


def _extent(plan, W, H):
    """Canvas rect (x0, y0, x1, y1) that covers the card at every moment of its animation: anim_state is sampled over the whole 0..1 range
    (plus the pop-out range for t4_pop), clamped to the canvas, even size."""
    w, h = plan["size"]
    name = _anim_name(plan["c"])
    ps = [i / float(SAMPLES) for i in range(SAMPLES + 1)]
    if name == "t4_pop":
        ps += [-p for p in ps[1:]]
    lo_x = lo_y = 1e9
    hi_x = hi_y = -1e9
    for p in ps:
        try:
            _a, dx, dy, sc, rot, _r = anim_state(name, p, W, H)
        except Exception:
            dx, dy, sc, rot = 0.0, 0.0, 1.0, 0.0
        sc = float(sc)
        if abs(rot) > 0.05:
            hw = hh = math.hypot(w, h) * sc / 2.0
        else:
            hw, hh = w * sc / 2.0, h * sc / 2.0
        lo_x, hi_x = min(lo_x, plan["cx"] + dx - hw), max(hi_x, plan["cx"] + dx + hw)
        lo_y, hi_y = min(lo_y, plan["cy"] + dy - hh), max(hi_y, plan["cy"] + dy + hh)
    x0, x1 = _even(max(0, int(math.floor(lo_x)) - MARGIN), min(W, int(math.ceil(hi_x)) + MARGIN), W)
    y0, y1 = _even(max(0, int(math.floor(lo_y)) - MARGIN), min(H, int(math.ceil(hi_y)) + MARGIN), H)
    if x1 - x0 < 2 or y1 - y0 < 2:
        raise ValueError("the card is outside the canvas")
    return x0, y0, x1, y1


def _reader_cmd(plan, win, nfr, cw, ch, fps_s):
    """FFmpeg command that decodes the source at the picture size and writes raw rgb24 frames to stdout (muted)."""
    c, original = plan["c"], plan["kind"] == "original"
    seg_s, seg_e = c["seg_start"], c["seg_end"]
    ss = seg_s if seg_s is not None else (win[0] if original else 0.0)
    if seg_e is not None and seg_e - ss < 0.05:
        seg_e = None
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"]
    if (not original) and seg_e is None and ss == 0.0:
        cmd += ["-stream_loop", "-1"]                                     # a whole clip file loops while the card is shown
    cmd += ["-ss", "%.3f" % ss, "-i", str(plan["src"])]
    if seg_e is not None:
        cmd += ["-t", "%.3f" % (seg_e - ss)]
    cmd += ["-an", "-vf", f"fps={fps_s},scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},format=rgb24",
            "-frames:v", str(nfr), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    return cmd


def _picture_sprite(raw, cw, ch, mask, size, pos):
    """One decoded frame -> RGBA sprite of the card's full size: the frame cut by the chamfer mask, at the picture rect, rest transparent."""
    pic = Image.frombytes("RGB", (cw, ch), raw).convert("RGBA")
    pic.putalpha(mask)
    spr = Image.new("RGBA", size, (0, 0, 0, 0))
    spr.paste(pic, pos)
    return spr


def _bake(cfg, plan, n, tmpdir, info, dur_eff):
    """Bake one card's picture into tmpdir/t4cardN.mov -> the video-layer dict for render.py."""
    c, win = plan["c"], plan["win"]
    W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    fps = info["fps"]
    fps_f = float(fps)
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    s0, e_true = win
    e = min(e_true, dur_eff)
    nfr = max(1, int(math.ceil((e - s0) * fps_f)))
    x0, y0, x1, y1 = _extent(plan, W, H)
    Wp, Hp = x1 - x0, y1 - y0
    px, py, cw, ch = plan["pic"]
    mask, need = t4_card_mask(cw, ch), cw * ch * 3
    out = os.path.join(tmpdir, "t4card%d.mov" % n)
    print("Preparing video card %d (%s, %d frames)..." % (n + 1, Path(str(plan["src"])).name, nfr))
    rd = subprocess.Popen(_reader_cmd(plan, win, nfr, cw, ch, fps_s), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL)
    wr = subprocess.Popen([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                           "-video_size", f"{Wp}x{Hp}", "-framerate", fps_s, "-i", "pipe:0", "-c:v", "qtrle", "-pix_fmt", "argb", out],
                          stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
    last, it = None, None
    try:
        for i in range(nfr):
            raw = _read_exact(rd.stdout, need)
            if len(raw) != need:
                raw = last if last is not None else GRAY * need          # the source ended: hold the last frame
            last = raw
            spr = _picture_sprite(raw, cw, ch, mask, plan["size"], (px, py))
            if it is None:
                it = _make_item(spr, s0, e_true, plan["cx"] - x0, plan["cy"] - y0, c)
            else:
                it.sprite = spr
            canvas = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
            draw_item(canvas, it, anim_state(it.anim, it.progress(s0 + i / fps_f), W, H))
            wr.stdin.write(canvas.tobytes())
        wr.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    finally:
        rd.kill()
        rd.wait()
    err = wr.stderr.read().decode("utf-8", "replace")
    if wr.wait() != 0 or not os.path.isfile(out):
        raise RuntimeError(err[-300:] or "FFmpeg could not write the clip")
    return {"path": out, "start": s0, "end": e, "area": "canvas", "mode": "fit", "fade": 0.0, "_xy": [x0, y0]}


def t4_prepare_card_layers(cfg, info, tmpdir):
    """Registry hook prepare_layers (id 5): one alpha clip per video / original-segment card -> list of video layers (drawn above the
    foreground plate, under the card's border Item). [] when there is none. Never raises: a failing card warns once and has no picture."""
    try:
        int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        return []
    dur_eff = info["duration"]
    if cfg.get("preview"):
        dur_eff = min(dur_eff, float(cfg["preview"]))
    layers = []
    for n, plan in enumerate(t4_card_plans(cfg, info["duration"])):
        if plan["win"][0] >= dur_eff:
            continue
        try:
            layers.append(_bake(cfg, plan, n, tmpdir, info, dur_eff))
        except (Exception, SystemExit) as e:
            t4_warn("cards: video card %d could not be prepared (%s: %s) - skipped." % (plan["idx"] + 1, type(e).__name__, e))
    try:                                                           # T4 split (R7): its baked clip goes FIRST = under the cards
        from mt.templates.t4.split_video import t4_split_prepare_layers
        split_layers = t4_split_prepare_layers(cfg, info, tmpdir)
    except Exception:
        split_layers = []
    try:                                                           # T4 b-roll takeover: its baked clip goes FIRST = bottom of all video layers
        from mt.templates.t4.broll_video import t4_broll_prepare_layers
        broll_layers = t4_broll_prepare_layers(cfg, info, tmpdir)
    except Exception:
        broll_layers = []
    return broll_layers + split_layers + layers