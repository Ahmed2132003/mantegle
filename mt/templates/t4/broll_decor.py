"""mt.templates.t4.broll_decor - Template 4: the HUD decoration plate of the 'broll' takeover (ref R4). ONE transparent full-canvas RGBA sprite (cached):
faint grid lines, four diagonal neon light streaks (rising to the right, faded at both ends), a code icon watermark top-left, a dot matrix top-right
and hazard stripes bottom-left. Authored in px at short side 1080 (scaled for other canvases).
Public: t4_broll_decor(W, H, color, stripe) -> RGBA W x H (shared object - never draw into it)."""
import math

from PIL import Image, ImageDraw

from mt.draw import t2_dots_mask, t2_paint, t2_rgb
from mt.templates.t4.captions import _ramp_alpha
from mt.templates.t4.kit import connector, hazard_stripes, kit_paste, neon_icon
from mt.templates.t4.nameplate import _cached

STREAKS = ((0.80, 0.20, 640, 3.0, 1.0), (0.90, 0.31, 430, 2.0, 0.65), (0.20, 0.76, 580, 3.0, 0.9), (0.10, 0.86, 380, 2.0, 0.6))   # cx, cy (fractions), length, width, alpha
_PLATE = {}


def _grid(pl, W, H, col, s):
    c = t2_rgb(col) + (24,)
    d = ImageDraw.Draw(pl)
    step, lw = max(40, int(round(120 * s))), max(1, int(round(s)))
    for x in range(step, W, step):
        d.line([(x, 0), (x, H)], fill=c, width=lw)
    for y in range(step, H, step):
        d.line([(0, y), (W, y)], fill=c, width=lw)


def _streaks(pl, W, H, col, s):
    a = math.radians(-32.0)
    dx, dy = math.cos(a), math.sin(a)
    for fx, fy, ln, wd, al in STREAKS:
        cx, cy, h = fx * W, fy * H, ln * s / 2.0
        p0, p1 = (cx - dx * h, cy - dy * h), (cx + dx * h, cy + dy * h)
        sp = connector([p0, p1], col, False, wd * s, 10 * s)
        _ramp_alpha(sp, p0[0], p1[0])
        if al < 1.0:
            sp.putalpha(sp.getchannel("A").point(lambda v, f=al: int(v * f)))
        kit_paste(pl, sp, 0, 0)


def _matrix(pl, W, col, s):
    cols, rows, pitch, r = 7, 3, 20 * s, 2.4 * s
    x0, y0 = W - 80 * s - (cols - 1) * pitch, 52 * s + r
    t2_paint(pl, t2_dots_mask(x0, y0, cols, rows, pitch, pitch, r), t2_rgb(col), 0.6)


def _icon(pl, col, s):
    size = max(24, int(round(120 * s)))
    ic = neon_icon("code", size, col, size * 0.10)
    ic.putalpha(ic.getchannel("A").point(lambda v: int(v * 0.45)))
    kit_paste(pl, ic, 96 * s, 100 * s)


def _stripes(pl, H, stripe, s):
    w, h = int(round(170 * s)), int(round(30 * s))
    kit_paste(pl, hazard_stripes((w, h), 32.0, stripe, 6, h * 0.5, h * 0.4), 96 * s, H - 150 * s)


def t4_broll_decor(W, H, color="#19D3FF", stripe="#FFC21A"):
    """Cached decoration plate for a canvas size + the two colours."""
    W, H = int(W), int(H)

    def make():
        s = min(W, H) / 1080.0
        pl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _grid(pl, W, H, color, s)
        _streaks(pl, W, H, color, s)
        _matrix(pl, W, color, s)
        _icon(pl, color, s)
        _stripes(pl, H, stripe, s)
        return pl
    return _cached(_PLATE, (W, H, str(color), str(stripe)), make, 3)