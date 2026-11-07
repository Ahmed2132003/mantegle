"""mt.anim - moved from montage.py by tools/mt_move.py"""


# ----------------------------------------------------------------------------
# Animations
# ----------------------------------------------------------------------------
ANIMS = ["fade", "slide_up", "slide_down", "slide_left", "slide_right",
         "zoom_in", "pop", "spin_in", "reveal", "drop"]


def _out_cubic(p):
    return 1 - (1 - p) ** 3


def _out_back(p, s=1.70158):
    p -= 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def _out_bounce(p):
    n1, d1 = 7.5625, 2.75
    if p < 1 / d1:
        return n1 * p * p
    if p < 2 / d1:
        p -= 1.5 / d1
        return n1 * p * p + 0.75
    if p < 2.5 / d1:
        p -= 2.25 / d1
        return n1 * p * p + 0.9375
    p -= 2.625 / d1
    return n1 * p * p + 0.984375


def anim_state(name, p, W, H):
    """p: 0 (hidden) -> 1 (fully shown). Returns alpha, dx, dy, scale, rotation, reveal."""
    if name in (None, "none") or p >= 1:
        return 1.0, 0, 0, 1.0, 0.0, None
    p = max(0.0, p)
    e = _out_cubic(p)
    if name == "fade":
        return e, 0, 0, 1.0, 0.0, None
    if name == "slide_up":
        return e, 0, (1 - e) * 0.10 * H, 1.0, 0.0, None
    if name == "slide_down":
        return e, 0, -(1 - e) * 0.10 * H, 1.0, 0.0, None
    if name == "slide_left":
        return e, (1 - e) * 0.18 * W, 0, 1.0, 0.0, None
    if name == "slide_right":
        return e, -(1 - e) * 0.18 * W, 0, 1.0, 0.0, None
    if name == "zoom_in":
        return min(1.0, p * 2), 0, 0, 0.4 + 0.6 * e, 0.0, None
    if name == "pop":
        return min(1.0, p * 4), 0, 0, max(0.01, _out_back(p)), 0.0, None
    if name == "spin_in":
        return e, 0, 0, max(0.01, e), (1 - e) * 270.0, None
    if name == "reveal":
        return 1.0, 0, 0, 1.0, 0.0, e
    if name == "drop":
        return min(1.0, p * 5), 0, -(1 - _out_bounce(p)) * 0.22 * H, 1.0, 0.0, None
    if name == "tile_up":                       # T3-6: short slide-up (60 px) + fade for the photo tiles; reversed = slide down + fade
        return min(1.0, p * 2.5), 0, (1 - e) * 60.0, 1.0, 0.0, None
    if name in ("card_r", "card_l"):
        # Template 2 floating card: slides in from the right / left edge with a small rotation settle
        # (ease-out-back); the same curve run backwards = slide + fade out.
        s = 1.0 if name == "card_r" else -1.0
        b = _out_back(p, 1.1)
        return min(1.0, p * 3.5), s * (1 - b) * 0.20 * W, 0, 1.0, s * (1 - b) * 10.0, None
    return 1.0, 0, 0, 1.0, 0.0, None


# ----------------------------------------------------------------------------
# Positions
# ----------------------------------------------------------------------------
PRESETS = {
    "1": "top-left", "2": "top", "3": "top-right",
    "4": "left", "5": "center", "6": "right",
    "7": "bottom-left", "8": "bottom", "9": "bottom-right",
}
