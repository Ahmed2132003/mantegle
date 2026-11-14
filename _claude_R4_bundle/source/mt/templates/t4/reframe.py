"""mt.templates.t4.reframe - Template 4 module 'reframe' (ref R7): while the diagonal split (t4/split.py) covers one side of the canvas, the speaker
video is zoomed and shifted so the face stays inside the VISIBLE side (R7: speaker on the left half). Pure ffmpeg expressions - nothing is drawn or
baked: build_ffmpeg_cmd (T4 branch) swaps the static cover scale/crop for (vf, ox, oy) returned by t4_reframe_vf(), the same contract as
t3_layout_video: vf = an eased zoom (scale eval=frame), ox / oy = overlay offset expressions that move the zoomed picture over the canvas-size
backdrop (a crop after a per-frame scale cannot be used: crop keeps the size it was configured with).
cfg['t4']['reframe'] = {on False (REQUIRED true to enable), focus_x 0.5, scale 1.35, focus_y 0.4}
    focus_x / focus_y = where the face is in the SOURCE video, 0..1 from the left / top edge (numbers 1 < v <= 100 are read as percent)
    scale             = zoom reached while the split is fully shown, 1.0 .. 3.0 (1 = no zoom; a video that already fills the canvas exactly has no
                        spare picture to shift unless scale > 1)
Motion: ONE progress u(t) shared with the split (t4_split_u: eased wipe in, hold, same path back) - zoom, x offset and y offset all follow it, so the
picture moves exactly while the seam moves and returns to the plain centre crop when the split is gone (u = 0 = the untouched base look).
Target: the face lands on the centre of the largest axis-aligned rectangle that stays on the speaker's side of the seam (reels side 'bottom' -> the top
band; YouTube side 'right' -> the left part). The crop is clamped so the picture always covers the canvas (never a black edge).
Only for video_box mode 'fill' (in 'fit' it is skipped with one t4_warn). Reframe off / no split / no window = the P19 command, unchanged.
Audio is never touched (the filter only changes pixels; timestamps stay as they are).
Public: T4_REFRAME, t4_reframe_cfg(raw), t4_visible_rect(plan), t4_reframe_u_expr(plan), t4_reframe_filter(plan, rc, vw, vh, rect, bx, by) -> (vf, ox, oy),
t4_reframe_vf(cfg, info, box=None) -> (vf, ox, oy) | None, t4_ask_reframe(split_cfg)."""
import copy
import math

from mt.common import ask, c_float, yn
from mt.templates.t4.split import t4_split_plan
from mt.templates.t4.warn import t4_warn

T4_REFRAME = {"on": False, "focus_x": 0.5, "focus_y": 0.4, "scale": 1.35}
SCALE_MIN, SCALE_MAX = 1.0, 3.0


# ---- config -----------------------------------------------------------------------------------------------------------------
def _num(v, lo, hi, default, percent=False):
    """Number clamped to lo..hi; junk / bool / nan -> default. percent=True: 1 < v <= 100 means a percentage."""
    try:
        if isinstance(v, bool) or v is None:
            return default
        x = float(str(v).strip().rstrip("%")) if isinstance(v, str) else float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        if percent and 1.0 < x <= 100.0:
            x /= 100.0
        return max(lo, min(hi, x))
    except (TypeError, ValueError, OverflowError):
        return default


def _on(v):
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(v) if isinstance(v, (bool, int)) else False


def t4_reframe_cfg(raw):
    """Normalise cfg['t4']['reframe'] -> complete dict (extra keys survive). Never raises; junk -> defaults (on False)."""
    out = copy.deepcopy(T4_REFRAME)
    if not isinstance(raw, dict):
        return out
    try:
        out.update({k: copy.deepcopy(v) for k, v in raw.items() if k not in out})
        out["on"] = _on(raw.get("on"))
        out["focus_x"] = _num(raw.get("focus_x"), 0.0, 1.0, T4_REFRAME["focus_x"], True)
        out["focus_y"] = _num(raw.get("focus_y"), 0.0, 1.0, T4_REFRAME["focus_y"], True)
        out["scale"] = _num(raw.get("scale"), SCALE_MIN, SCALE_MAX, T4_REFRAME["scale"])
    except Exception:
        return copy.deepcopy(T4_REFRAME)
    return out


# ---- geometry ---------------------------------------------------------------------------------------------------------------
def t4_visible_rect(plan):
    """(x, y, w, h) floats: the largest axis-aligned canvas rectangle on the speaker's side of the seam at full wipe (the seam is slanted, so the
    rectangle stops at the seam's nearest point). None for a degenerate plan."""
    W, H, P, d, side = float(plan["W"]), float(plan["H"]), plan["P"], plan["d"], plan["side"]
    if side in ("top", "bottom"):
        if abs(d[0]) < 1e-9:
            return None
        ys = [P[1] + (x - P[0]) * d[1] / d[0] for x in (0.0, W)]
        edge = max(0.0, min(H, min(ys) if side == "bottom" else max(ys)))
        r = (0.0, 0.0, W, edge) if side == "bottom" else (0.0, edge, W, H - edge)
    else:
        if abs(d[1]) < 1e-9:
            return None
        xs = [P[0] + (y - P[1]) * d[0] / d[1] for y in (0.0, H)]
        edge = max(0.0, min(W, min(xs) if side == "right" else max(xs)))
        r = (0.0, 0.0, edge, H) if side == "right" else (edge, 0.0, W - edge, H)
    return r if r[2] >= 2.0 and r[3] >= 2.0 else None


# ---- ffmpeg expressions -----------------------------------------------------------------------------------------------------
def _g(v):
    return "%.6g" % v


def t4_reframe_u_expr(plan):
    """ffmpeg expression in t = t4_split_u(plan, t): p = clip(min((t - t0) / wipe, (t1 - t) / wipe), 0, 1); u = 1 - (1 - p)^3.
    Uses the plan's frame-snapped t0 / t1, the same numbers as the seam Items and the baked clip -> frame-exact."""
    t0, t1, w = plan["t0"], plan["t1"], plan["wipe"]
    p = "max(0,min(1,min((t-%.5f)/%.5f,(%.5f-t)/%.5f)))" % (t0, w, t1, w)
    return "(1-pow(1-%s,3))" % p


def _axis(C, focus, target, u, big, base):
    """Overlay offset expression along one axis: `big` = overlay_w / overlay_h (the zoomed picture), C = canvas size, base = box origin.
    The picture's crop offset is the centre crop at u = 0 and puts the face (focus * big) on `target`, clamped to the picture, at u = 1;
    the overlay position is base - offset."""
    ctr = "(%s-%d)/2" % (big, C)
    goal = "max(0,min(%s-%d,%s*%s-%s))" % (big, C, _g(focus), big, _g(target))
    return "'%d-(%s+%s*(%s-%s))'" % (base, ctr, u, goal, ctr)


def t4_reframe_filter(plan, rc, vw, vh, rect, bx=0, by=0):
    """-> (vf, ox, oy): vf = eased zoom of the [r0] stream (same cover size as the plain fill while u = 0), ox / oy = the overlay position
    expressions (strings with their own quotes) that shift the zoomed picture so the face reaches the visible rectangle's centre."""
    W, H = int(plan["W"]), int(plan["H"])
    S = max(W / float(vw), H / float(vh))
    u = t4_reframe_u_expr(plan)
    z = "(1+%s*%s)" % (_g(rc["scale"] - 1.0), u)
    sw = "max(%d,ceil(%s*%s/2)*2)" % (W, _g(vw * S), z)
    sh = "max(%d,ceil(%s*%s/2)*2)" % (H, _g(vh * S), z)
    tx, ty = rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0
    vf = "scale=w='%s':h='%s':eval=frame:flags=bicubic,setsar=1" % (sw, sh)
    return (vf, _axis(W, rc["focus_x"], tx, u, "overlay_w", int(bx)), _axis(H, rc["focus_y"], ty, u, "overlay_h", int(by)))


def t4_reframe_vf(cfg, info, box=None):
    """Hook for build_ffmpeg_cmd (template_id == 5): (vf for [r0], overlay x expr, overlay y expr), or None (reframe off / no split / not
    'fill' / any problem) = the caller keeps the plain fill. Uses the FULL source duration (like the split Items) so a --preview render moves in step.
    Never raises."""
    try:
        t4 = cfg.get("t4") if isinstance(cfg.get("t4"), dict) else {}
        rc = t4_reframe_cfg(t4.get("reframe"))
        if not rc["on"]:
            return None
        mode = (box or cfg.get("video_box") or {}).get("mode", "fit")
        if mode != "fill":
            t4_warn("reframe: it needs the video to FILL the canvas ('fill'); in 'fit' it is skipped.")
            return None
        plan = t4_split_plan(cfg, float(info["duration"]), float(info["fps"]))
        if plan is None:
            return None                      # split off / empty window: nothing to reframe (its own warning, if any, comes from the split)
        rect = t4_visible_rect(plan)
        if rect is None:
            t4_warn("reframe: the split leaves no visible speaker area - skipped.")
            return None
        bx = box.get("x", 0) if isinstance(box, dict) else 0
        by = box.get("y", 0) if isinstance(box, dict) else 0
        return t4_reframe_filter(plan, rc, int(info["w"]), int(info["h"]), rect, bx, by)
    except (Exception, SystemExit) as e:
        t4_warn("reframe: could not be built (%s: %s) - skipped." % (type(e).__name__, e))
        return None


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_ask_reframe(split_cfg):
    """Question group 'reframe' (called by t4_ask_config right after the split). Only asked when the split is on. -> dict for cfg['t4']['reframe']."""
    if not isinstance(split_cfg, dict) or not split_cfg.get("on"):
        return {"on": False}
    if not yn("Reframe the speaker while the split is on (zoom + shift so the face stays on the speaker's side)?", default=False):
        return {"on": False}
    fx = ask("Face position across the source video (0 = left edge ... 1 = right edge)", default=0.5, key="t4_rf_fx", cast=c_float)
    fy = ask("Face position down the source video (0 = top ... 1 = bottom)", default=0.4, key="t4_rf_fy", cast=c_float)
    k = ask("Zoom while the split is shown (1 = none, 1.35 = default, max 3)", default=1.35, key="t4_rf_scale", cast=c_float)
    return {"on": True, "focus_x": fx, "focus_y": fy, "scale": k}