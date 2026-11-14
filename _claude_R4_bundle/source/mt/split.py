"""mt.split - moved from montage.py by tools/mt_move.py"""
from mt.draw import T2_DEFAULT_BOX, _draw_frame, make_tech_background, t2_cfg
from mt.draw import T2_SS, t2_rgb
from PIL import Image, ImageChops, ImageDraw, ImageFilter


# ----------------------------------------------------------------------------
# Split layout (main video left + image / screen recording right)
# ----------------------------------------------------------------------------
SPLIT_T = 0.4


def split_boxes(cfg):
    W, H = cfg["canvas"]
    sp = cfg.get("split")
    sp = sp if isinstance(sp, dict) else {}
    vb = cfg["video_box"]
    cy = vb["y"] + vb["h"] / 2.0 + float(sp.get("dy", 0))      # "dy"/"x0": Template 2 only
    h = int(sp.get("h", 800))
    lw = int(sp.get("left_w", 520))
    rw = int(sp.get("right_w", 360))
    gp = int(sp.get("gap_px", 40))
    x0 = int(sp["x0"]) if "x0" in sp else (W - (lw + gp + rw)) // 2
    y = int(cy - h / 2) // 2 * 2
    return ({"x": x0, "y": y, "w": lw, "h": h},
            {"x": x0 + lw + gp, "y": y, "w": rw, "h": h})


def compute_splits(cfg, duration):
    if not (cfg.get("split") and cfg.get("_split_bg")):
        return []
    sp = cfg["split"] if isinstance(cfg["split"], dict) else {}
    ivs = [(float(e["start"]), float(e["end"])) for e in (cfg.get("elements") or [])]
    ivs += [(float(v["start"]), float(v["end"])) for v in (cfg.get("video_layers") or [])
            if v.get("area", "box") == "box"]
    ivs.sort()
    out = []
    for s, e in ivs:
        if out and s - out[-1][1] <= float(sp.get("merge", 1.6)):
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(a, b) for a, b in out if a < duration]


def split_at(splits, t):
    return any(a - SPLIT_T <= t < b + SPLIT_T for a, b in splits)


def make_split_background(W, H, lbox, rbox, divider_pct, out_path):
    make_tech_background(W, H, lbox, divider_pct, out_path)
    base = Image.open(out_path).convert("RGBA")
    _draw_frame(base, rbox, W / 1080.0, W, H)
    base.convert("RGB").save(out_path)
    return out_path


def t2_split_params(cfg):
    """cfg['t2']['split'] -> the dict split_boxes()/compute_splits() (Template 1's split logic) understand.
    The two boxes sit inside the video window, above the caption zone."""
    sp = t2_cfg(cfg.get("t2"))["split"]
    b = cfg.get("video_box") or T2_DEFAULT_BOX
    m, gap = sp["margin"], sp["gap_px"]
    usable = max(40, b["w"] - 2 * m - gap)
    lw = int(round(usable * sp["left_pct"] / 100.0)) // 2 * 2
    h = max(100, (b["h"] - m - sp["bottom_px"]) // 2 * 2)
    return {"left_w": lw, "right_w": usable - lw, "gap_px": gap, "h": h, "x0": b["x"] + m,
            "dy": (b["y"] + m + h / 2.0) - (b["y"] + b["h"] / 2.0), "merge": sp["merge"]}


def t2_make_split_ring(cfg, bg_path, out_path):
    """Transparent full-canvas png: lime rounded border (+ soft glow) around both split boxes, and the four corner
    slivers of each box filled with the background, so rectangular content (video / layer) gets rounded corners."""
    sp = t2_cfg(cfg.get("t2"))["split"]
    W, H = cfg["canvas"]
    acc = t2_rgb(t2_cfg(cfg.get("t2"))["accent"])
    bg = Image.open(bg_path).convert("RGBA")
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    e, r, ss, pad = sp["border"], sp["radius"], T2_SS, sp["border"] + 16
    for box in split_boxes(cfg):
        x0, y0, bw, bh = box["x"], box["y"], box["w"], box["h"]
        w, h = bw + 2 * pad, bh + 2 * pad

        def rr(grow, rad):
            m = Image.new("L", (w * ss, h * ss), 0)
            ImageDraw.Draw(m).rounded_rectangle(((pad - grow) * ss, (pad - grow) * ss, (pad + bw + grow) * ss - 1, (pad + bh + grow) * ss - 1),
                                                radius=max(0, rad) * ss, fill=255)
            return m
        inner, outer = rr(0, r), rr(e, r + e)
        rect = Image.new("L", (w * ss, h * ss), 0)
        ImageDraw.Draw(rect).rectangle((pad * ss, pad * ss, (pad + bw) * ss - 1, (pad + bh) * ss - 1), fill=255)
        ring_m = ImageChops.subtract(outer, inner).resize((w, h), Image.BOX)
        cut_m = ImageChops.subtract(rect, inner).resize((w, h), Image.BOX)
        glow = ImageChops.subtract(ring_m.filter(ImageFilter.GaussianBlur(7)).point(lambda v: int(min(255, v * 1.4))), inner.resize((w, h), Image.BOX))
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        g = Image.new("RGBA", (w, h), acc + (255,))
        g.putalpha(glow.point(lambda v: int(v * 0.55)))
        lay.alpha_composite(g)
        c = bg.crop((x0 - pad, y0 - pad, x0 - pad + w, y0 - pad + h))
        c.putalpha(cut_m)
        lay.alpha_composite(c)
        l = Image.new("RGBA", (w, h), acc + (255,))
        l.putalpha(ring_m)
        lay.alpha_composite(l)
        ring.alpha_composite(lay, (x0 - pad, y0 - pad))
    ring.save(out_path, compress_level=1)
    return out_path
