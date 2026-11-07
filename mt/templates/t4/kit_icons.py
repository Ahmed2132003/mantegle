"""mt.templates.t4.kit_icons - Template 4 vector icons + the soft-erode helper shared with kit.py.
Every icon is drawn at 4x on an 'L' canvas and shrunk with LANCZOS (no jagged edges), then tinted by kit.icon().
Reused from mt.draw._draw_icon (drawn at 4x): code, phone, chip, shield. New here: laptop, gear, database, server,
cloud (upload arrow, as in R5), bulb, globe (lighter than the old one: its crowded strokes clogged at 96 px). Unknown names never raise: one t4_warn line + an empty icon."""
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from mt.draw import _draw_icon
from mt.templates.t4.warn import t4_warn

SS = 4
ICON_NAMES = ("code", "laptop", "phone", "gear", "globe", "database", "server", "cloud", "bulb", "chip", "shield")
_REUSED = ("code", "phone", "chip", "shield")


def soft_erode(L, d):
    """Coverage ('L') of the shape in L shrunk by d px - isotropic and anti-aliased (gaussian blur + soft threshold)."""
    if d <= 0:
        return L
    sigma = max(1.2, d / 1.1)
    z = d / sigma
    p = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    slope = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi) / sigma          # d(blur)/d(px) at the edge
    b = L.filter(ImageFilter.GaussianBlur(sigma))
    return b.point(lambda v: int(255 * min(1.0, max(0.0, 0.5 + (v / 255.0 - p) / slope))))


class _Pen:
    """Unit-square pen on a big 'L' canvas: coordinates 0..1, stroke width w (unit), round caps / joints."""

    def __init__(self, S, w=0.075):
        self.S = S
        self.W = max(2, int(round(w * S)))
        self.im = Image.new("L", (S, S), 0)
        self.d = ImageDraw.Draw(self.im)

    def P(self, pts):
        return [(x * self.S, y * self.S) for x, y in pts]

    def line(self, pts, closed=False):
        P = self.P(pts + ([pts[0]] if closed else []))
        self.d.line(P, fill=255, width=self.W, joint="curve")
        r = self.W / 2.0
        for x, y in P:
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=255)

    def dot(self, cx, cy, r, fill=255):
        S = self.S
        self.d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), fill=fill)

    def ring(self, cx, cy, r):
        S = self.S
        self.d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), outline=255, width=self.W)

    def rrect(self, box, rad):
        self.d.rounded_rectangle([v * self.S for v in box], radius=rad * self.S, outline=255, width=self.W)

    def arc(self, box, a0, a1):
        self.d.arc([v * self.S for v in box], a0, a1, fill=255, width=self.W)

    def fill_union(self, circles, rects):
        S = self.S
        for cx, cy, r in circles:
            self.d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), fill=255)
        for x0, y0, x1, y1 in rects:
            self.d.rectangle((x0 * S, y0 * S, x1 * S, y1 * S), fill=255)


def _arc_pts(cx, cy, r, a0, a1, n=48):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def _laptop(S):
    p = _Pen(S, 0.07)
    p.rrect((0.20, 0.20, 0.80, 0.64), 0.04)
    p.line([(0.08, 0.77), (0.92, 0.77)])
    p.line([(0.40, 0.77), (0.44, 0.71), (0.56, 0.71), (0.60, 0.77)])
    return p.im


def _gear(S):
    p = _Pen(S, 0.07)
    n, R, r = 8, 0.43, 0.32
    per = 2 * math.pi / n
    pts = []
    for k in range(n):
        c = k * per
        for rr, off in ((r, -0.30), (R, -0.17), (R, 0.17), (r, 0.30)):
            a = c + off * per
            pts.append((0.5 + rr * math.cos(a), 0.5 + rr * math.sin(a)))
    p.line(pts, closed=True)
    p.ring(0.5, 0.5, 0.13)
    return p.im


def _database(S):
    p = _Pen(S, 0.07)
    p.d.ellipse((0.20 * S, 0.12 * S, 0.80 * S, 0.30 * S), outline=255, width=p.W)
    p.line([(0.20, 0.21), (0.20, 0.79)])
    p.line([(0.80, 0.21), (0.80, 0.79)])
    for top in (0.32, 0.52, 0.70):
        p.arc((0.20, top, 0.80, top + 0.18), 0, 180)
    return p.im


def _server(S):
    p = _Pen(S, 0.06)
    for y0 in (0.12, 0.39, 0.66):
        p.rrect((0.12, y0, 0.88, y0 + 0.22), 0.04)
        p.dot(0.27, y0 + 0.11, 0.032)
        p.dot(0.39, y0 + 0.11, 0.032)
        p.line([(0.62, y0 + 0.11), (0.76, y0 + 0.11)])
    return p.im


def _cloud(S):
    p = _Pen(S, 0.075)
    big = Image.new("L", (S, S), 0)
    q = _Pen(S)
    q.im, q.d = big, ImageDraw.Draw(big)
    q.fill_union([(0.27, 0.60, 0.17), (0.47, 0.42, 0.22), (0.72, 0.58, 0.18)], [(0.27, 0.58, 0.72, 0.77)])
    ring = ImageChops.subtract(big, soft_erode(big, p.W))
    p.im = ring
    p.d = ImageDraw.Draw(ring)
    p.line([(0.49, 0.66), (0.49, 0.42)])
    p.line([(0.40, 0.50), (0.49, 0.41), (0.58, 0.50)])
    return p.im


def _bulb(S):
    p = _Pen(S, 0.07)
    arc = _arc_pts(0.5, 0.40, 0.27, 125, 415)
    p.line(arc + [(0.59, 0.73), (0.41, 0.73)], closed=True)
    p.line([(0.42, 0.85), (0.58, 0.85)])
    p.line([(0.43, 0.56), (0.5, 0.47), (0.57, 0.56)])
    p.line([(0.5, 0.47), (0.5, 0.73)])
    return p.im


def _globe(S):
    p = _Pen(S, 0.06)
    p.ring(0.5, 0.5, 0.40)
    p.d.ellipse((0.33 * S, 0.10 * S, 0.67 * S, 0.90 * S), outline=255, width=p.W)
    p.line([(0.10, 0.5), (0.90, 0.5)])
    p.line([(0.5, 0.10), (0.5, 0.90)])
    p.line([(0.17, 0.30), (0.83, 0.30)])
    p.line([(0.17, 0.70), (0.83, 0.70)])
    return p.im


_NEW = {"globe": _globe, "laptop": _laptop, "gear": _gear, "database": _database, "server": _server, "cloud": _cloud, "bulb": _bulb}


def icon_mask(name, size):
    """White-on-black 'L' mask (size x size) of icon `name`, anti-aliased. Unknown name -> empty mask + one warning."""
    size = max(4, int(round(size)))
    S = size * SS
    if name in _NEW:
        big = _NEW[name](S)
    elif name in _REUSED:
        rgba = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        _draw_icon(rgba, name, (0, 0, S, S))
        big = rgba.getchannel("A")
    else:
        t4_warn("t4 icon: unknown name %r (known: %s)" % (name, ", ".join(ICON_NAMES)))
        big = Image.new("L", (S, S), 0)
    return big.resize((size, size), Image.LANCZOS)
