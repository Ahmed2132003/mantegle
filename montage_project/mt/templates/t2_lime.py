"""mt.templates.t2_lime - moved from montage.py by tools/mt_move.py"""
from mt.draw import Item, T2_SS, _draw_icon, draw_item, t2_darken, t2_dots_mask, t2_draw_mask, t2_fit_text, t2_glow, t2_grad, t2_gradient, t2_lighten, t2_line_mask, t2_mask_full, t2_mask_sub, t2_mix, t2_paint, t2_place, t2_poly_mask, t2_polys_mask, t2_rgb, t2_rrect_mask, t2_size_for_cap, t2_text_mask
from mt.draw import T2_ABOUT, T2_ABOUT_DEFAULT_STATE, T2_DEFAULTS, T2_DEFAULT_BOX, T2_PANEL, T2_PANEL_GUIDE, T2_PANEL_ROWS, t2_about_icon_spec, t2_cfg, t2_norm_about
from mt.fonts import t2_font
from mt.split import t2_make_split_ring, t2_split_params
from mt.common import AR_DIGITS, D, FFMPEG, IMAGE_EXTS, T2_ACCENT, VIDEO_EXTS, _read_exact, ask, ask_choice, c_color, c_existing_file, c_float, c_int, c_percent, c_size_wh, c_time, clean_path, probe, yn
from mt.ask import _PRESET, _tpl_template_id, ask_elements, ask_layers, ask_texts, ask_video_layers, list_templates, maybe_save_template
from mt.captions import caption_streams, parse_srt
from mt.captions import find_trigger
from mt.ask import ask_anim
from mt.render import _first_frame
from mt.anim import anim_state
from mt.templates.t1_tech import ICON_LINE, t1_build_items
from mt.fonts import has_arabic, is_rtl_text, load_font, shape
from PIL import Image, ImageChops, ImageDraw
import shutil
import os
import json
import tempfile
from pathlib import Path
import math
import subprocess
import sys


# ---- Template 2 (Lime Creator Series) ---------------------------------------------------
# PART 2 = the STATIC design (everything that stays on screen for the whole video):
#   background + shapes + dot grids + header + pill + headline + rounded glowing video frame.
# Parts 3-4 add the dynamic parts (captions style, chapter tag, floating B-roll card, about block,
# bottom panel); the reusable drawing helpers below (t2_*) are meant for them.
#
# How the static design reaches the video (see build_ffmpeg_cmd):
#   BACKGROUND png  = input 0 (under the video).  Inside the video window it is plain dark, so a
#                     'fit' video that leaves gaps shows a clean dark colour.
#   FOREGROUND png  = the same design on a full canvas, with a rounded transparent WINDOW where the
#                     video shows + the glowing border. It is overlaid ONCE above the video (and
#                     above box-area video layers), so the video corners are clipped perfectly.
# Everything is drawn with Pillow at render time (4x supersampling), no external image assets.
T2_POSTER_W, T2_POSTER_H = 941.0, 1672.0      # the design reference; coordinates below are poster px


T2_BG0, T2_BG1 = (5, 8, 11), (11, 12, 17)      # background gradient (top -> bottom)


# ---- the static plate -----------------------------------------------------------------
_T2_CACHE = {}


_T2_CACHE_DIR = None


def make_t2_static(W, H, cfg_t2, out_paths, box=None):
    """Draw Template 2's static design and save it:
         out_paths["bg"]  RGB png   background (under the video; plain dark inside the video window)
         out_paths["fg"]  RGBA png  same canvas with a rounded transparent window for the video + glowing border
       box = video window {"x","y","w","h"} (default T2_DEFAULT_BOX).
       Returns info = {"boxes": {name: (x0,y0,x1,y1)} of every drawn element, "window": (x0,y0,x1,y1),
                       "probe": {...points for tests}, "fonts": {...}}. Cached per (size, cfg, box)."""
    t2 = t2_cfg(cfg_t2)
    bx = dict(T2_DEFAULT_BOX)
    bx.update({k: v for k, v in (box or {}).items() if v is not None})
    key = json.dumps([W, H, t2, {k: bx[k] for k in ("x", "y", "w", "h")}], sort_keys=True, ensure_ascii=False)
    hit = _T2_CACHE.get(key)            # same design built again (e.g. --still then render): copy the plates
    if hit and all(os.path.isfile(p) for p in hit[0]):
        for src, dst in zip(hit[0], (out_paths["bg"], out_paths["fg"])):
            shutil.copyfile(src, str(dst))
        return hit[1]

    kx, ky = W / T2_POSTER_W, H / T2_POSTER_H

    def PT(pts):
        return [(x * kx, y * ky) for x, y in pts]
    accent = t2_rgb(t2["accent"])
    fonts = t2.get("fonts") or {}
    info = {"boxes": {}, "probe": {}, "fonts": {}}

    def note(name, bb):
        if bb:
            info["boxes"][name] = tuple(int(v) for v in bb)

    base = t2_gradient((W, H), [(0, T2_BG0), (1, T2_BG1)], 90)
    plain = base.copy()

    # --- background shapes -------------------------------------------------------------
    if t2["show_bg_shapes"]:
        for poly, a in (([(560, 0), (655, 0), (941, 286), (941, 381)], 0.030),
                        ([(700, 0), (735, 0), (941, 206), (941, 241)], 0.040),
                        ([(0, 1395), (0, 1470), (202, 1672), (127, 1672)], 0.022)):
            t2_paint(base, t2_poly_mask(PT(poly)), (255, 255, 255), a)
        dark = lambda f: t2_mix(accent, T2_BG0, f)  # noqa: E731
        # slanted lime band, top right
        pts = PT([(941, 219), (941, 325), (810, 452), (810, 350)])
        bb = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        note("shape_band", t2_paint(base, t2_poly_mask(pts), t2_grad(
            [(0, t2_darken(accent, 0.03)), (0.5, dark(0.38)), (1, dark(0.66))], 135, bb)))
        # lime triangle, left edge (upper)
        pts = PT([(0, 770), (56, 770), (0, 827)])
        note("shape_tri", t2_paint(base, t2_poly_mask(pts), t2_grad(
            [(0, dark(0.5)), (1, dark(0.75))], 0, (0, 0, pts[1][0], 1))))
        # lime band, left edge (lower) - bright at the bottom-left, fading toward the frame
        pts = PT([(0, 1010), (96, 941), (96, 1093), (0, 1180)])
        bb = (0, min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        note("shape_band2", t2_paint(base, t2_poly_mask(pts), t2_grad(
            [(0, accent), (0.55, dark(0.4)), (1, dark(0.8))], -68, bb)))
        # lime corner, bottom-left
        pts = PT([(0, 1632), (110, 1632), (225, 1672), (0, 1672)])
        note("shape_corner", t2_paint(base, t2_poly_mask(pts), t2_grad(
            [(0, accent + (255,)), (0.45, dark(0.45) + (235,)), (1, dark(0.7) + (0,))], 0, (0, 0, pts[2][0], 1))))

    # --- dot grids ---------------------------------------------------------------------
    if t2["show_dots"]:
        for i, (x, y, c, r, px, py, a) in enumerate(((32, 322, 3, 9, 17.5, 17.5, 0.55),
                                                     (849, 400, 4, 3, 23, 23, 0.6),
                                                     (10, 872, 4, 3, 18, 22, 0.5))):
            note(f"dots{i}", t2_paint(base, t2_dots_mask(x * kx, y * ky, c, r, px * kx, py * ky, 1.7 * kx),
                                      (125, 130, 129), a))

    # --- header + pill -----------------------------------------------------------------
    pill_x0 = None
    if t2["show_pill"] and t2["pill"].strip():
        pf, _ = t2_font("ui_bold", t2["pill"], fonts)
        tm, shown, _ = t2_fit_text(t2["pill"].strip(), pf, (330 - 57) * kx, 12.2 * kx, tracking_em=0.03)
        pw = max(178 * kx, tm.width + 57 * kx)
        px1 = 890 * kx
        px0 = px1 - pw
        py0, py1 = 44 * ky, 78 * ky
        pcy = (py0 + py1) / 2.0
        pr, ow = 10 * kx, 2.1 * kx
        outer = t2_rrect_mask((px0, py0, px1, py1), pr)
        inner = t2_rrect_mask((px0 + ow, py0 + ow, px1 - ow, py1 - ow), pr - ow)
        t2_paint(base, inner, (9, 12, 12), 0.82)
        note("pill", t2_paint(base, t2_mask_sub(outer, inner), accent))
        cx, rr = px0 + 24 * kx, 10.5 * kx
        t2_paint(base, t2_draw_mask((cx - rr, pcy - rr, cx + rr, pcy + rr), lambda d, L, s: d.ellipse(
            (*L(cx - rr, pcy - rr), *L(cx + rr, pcy + rr)), fill=255)), accent)
        t2_paint(base, t2_poly_mask([(cx - 3.6 * kx, pcy - 5.6 * kx), (cx - 3.6 * kx, pcy + 5.6 * kx),
                                     (cx + 6.2 * kx, pcy)]), (9, 12, 12))
        note("pill_text", t2_paint(base, t2_place(tm, px0 + 43 * kx, cy=pcy), accent))
        # slanted hatch strip under the pill
        polys, x = [], px0 + 33 * kx
        while x + 9 * kx <= px1 - 2 * kx + 0.5:
            polys.append([(x + 3.5 * kx, 88 * ky), (x + 9 * kx, 88 * ky), (x + 5.5 * kx, 95 * ky), (x, 95 * ky)])
            x += 13.6 * kx
        if polys:
            note("hatch", t2_paint(base, t2_polys_mask(polys), (96, 101, 99), 0.9))
        pill_x0 = px0
        info["fonts"]["ui_bold"] = pf

    if t2["show_header"]:
        has_name, has_sub = bool(t2["name"].strip()), bool(t2["subtitle"].strip())
        if t2["logo"].strip():
            if t2["logo"].strip() == "</>":
                sw = 6.4 * kx
                lg = [[(73, 50), (52, 68), (73, 86)], [(98, 50), (119, 68), (98, 86)], [(94, 45), (80, 91)]]
                mm = [t2_line_mask(PT(pl), sw) for pl in lg]
                bbs = [t2_paint(base, m, accent) for m in mm]
                note("logo", (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs),
                              max(b[3] for b in bbs)))
            else:
                lf, lsh = t2_font("headline", t2["logo"], fonts)
                lm, _, _ = t2_fit_text(t2["logo"].strip(), lf, 70 * kx, 34 * ky, shear=0.0)
                note("logo", t2_paint(base, t2_place(lm, 50 * kx, cy=68 * ky), accent))
            if has_name or has_sub:
                note("divider", t2_paint(base, t2_rrect_mask((147.3 * kx, 43 * ky, 148.9 * kx, 94 * ky), 0.6 * kx),
                                         (112, 117, 115), 0.85))
        limit = (pill_x0 - 22 * kx) if pill_x0 is not None else 890 * kx
        max_w = limit - 178 * kx
        if has_name:
            nf, _ = t2_font("ui", t2["name"], fonts)
            info["fonts"]["ui"] = nf
            nm, _, _ = t2_fit_text(t2["name"].strip(), nf, max_w, 20 * ky, tracking_em=0.075)
            note("name", t2_paint(base, t2_place(nm, 178 * kx, cy=(58 if has_sub else 68) * ky), (236, 235, 229)))
        if has_sub:
            sf, _ = t2_font("ui", t2["subtitle"], fonts)
            sm, _, _ = t2_fit_text(t2["subtitle"].strip(), sf, max_w, 10.5 * ky, tracking_em=0.045)
            note("subtitle", t2_paint(base, t2_place(sm, 178 * kx, cy=(84 if has_name else 68) * ky), (141, 146, 143)))

    # --- headline ----------------------------------------------------------------------
    l1, l2 = t2["line1"].strip(), t2["line2"].strip()
    if t2["show_headline"] and (l1 or l2):
        both = bool(l1 and l2)
        c1 = 160 * ky + (0 if both else 42 * ky)
        c2 = 238.5 * ky + (0 if both else -36.5 * ky)
        # slanted bars on the left
        note("headline_bars", t2_paint(base, t2_poly_mask(PT([(113, 133), (120.5, 133), (92.5, 243), (85, 243)])),
                                       accent))
        t2_paint(base, t2_poly_mask(PT([(127, 133), (139, 133), (109, 277), (97, 277)])), (58, 62, 60), 0.9)
        l1_right = None
        if l1:
            hf, sh = t2_font("headline", l1, fonts)
            info["fonts"]["headline"] = hf
            m1, _, _ = t2_fit_text(l1, hf, 585 * kx, 55 * ky, shear=0.2 if sh else 0.0)
            pm = t2_place(m1, 170 * kx, cy=c1)
            note("line1", t2_paint(base, pm, t2_grad([(0, (250, 248, 240)), (1, (176, 174, 166))], 90)))
            l1_right = pm[1][0] + m1.width
            # thin line + lime dot to the right of line 1
            dx0 = l1_right + 20 * kx
            dx1 = min(dx0 + 92 * kx, 905 * kx)
            if dx1 - dx0 > 30 * kx:
                dy = c1 + 20 * ky
                note("dash", t2_paint(base, t2_line_mask([(dx0, dy), (dx1, dy)], 1.6 * kx, caps=False), (210, 210, 204)))
                r = 4.8 * kx
                t2_paint(base, t2_draw_mask((dx1 - r, dy - r, dx1 + r, dy + r), lambda d, L, s: d.ellipse(
                    (*L(dx1 - r, dy - r), *L(dx1 + r, dy + r)), fill=255)), accent)
        if l2:
            hf2, sh2 = t2_font("headline", l2, fonts)
            info["fonts"].setdefault("headline", hf2)
            m2, _, _ = t2_fit_text(l2, hf2, 606 * kx, 60 * ky, shear=0.2 if sh2 else 0.0)
            pm2 = t2_place(m2, 172 * kx, cy=c2)
            ix0, ix1 = pm2[1][0], pm2[1][0] + m2.width
            s = 0.2
            hh = 40.5 * ky
            xl = ix0 - 38 * kx
            xr = max(ix1 + 14 * kx, xl + 280 * kx)
            poly = [(xl + s * hh, c2 - hh), (xr + s * hh, c2 - hh), (xr - s * hh, c2 + hh), (xl - s * hh, c2 + hh)]
            bb = (poly[3][0], poly[0][1], poly[1][0], poly[2][1])
            note("bar", t2_paint(base, t2_poly_mask(poly, round_r=7 * kx), t2_grad(
                [(0, t2_lighten(accent, 0.5)), (0.28, accent), (1, t2_darken(accent, 0.08))], 0, bb)))
            note("line2", t2_paint(base, pm2, (6, 8, 10)))
            info["probe"]["bar"] = (int((poly[0][0] + poly[1][0]) / 2), int(c2 - hh + 4 * ky))

    # --- video frame -------------------------------------------------------------------
    x0, y0 = int(bx["x"]), int(bx["y"])
    x1, y1 = x0 + int(bx["w"]), y0 + int(bx["h"])
    r = t2["radius"] * W / 1080.0
    b = t2["border"] * W / 1080.0
    outer = t2_rrect_mask((x0, y0, x1, y1), r)
    inner = t2_rrect_mask((x0 + b, y0 + b, x1 - b, y1 - b), max(0.5, r - b))
    info["window"] = (x0, y0, x1, y1)
    info["probe"].update({"window_center": ((x0 + x1) // 2, (y0 + y1) // 2), "window_corner": (x0 + 1, y0 + 1),
                          "bg_corner": (2, 2)})

    bg_img = base.copy()                                   # BACKGROUND: plain dark inside the window
    bg_img.paste(plain.crop((x0, y0, x1, y1)), (x0, y0))
    fg = base.copy()                                       # FOREGROUND: design + glow + border + hole
    t2_paint(fg, t2_glow(outer, 18 * kx, 0.55), accent, 0.55)
    t2_paint(fg, t2_glow(outer, 6 * kx, 0.8), accent, 0.45)
    t2_paint(fg, t2_mask_sub(outer, inner), t2_grad(
        [(0, t2_lighten(accent, 0.55)), (0.45, accent), (1, t2_darken(accent, 0.12))], 70, (x0, y0, x1, y1)))
    hole = ImageChops.invert(t2_mask_full(inner, (W, H)))
    fg.putalpha(ImageChops.multiply(fg.getchannel("A"), hole))
    info["boxes"]["frame"] = (x0, y0, x1, y1)

    bg_img.convert("RGB").save(out_paths["bg"])
    fg.save(out_paths["fg"], compress_level=1)
    try:    # private copies (the caller's files may be overwritten or deleted later)
        global _T2_CACHE_DIR
        if _T2_CACHE_DIR is None:
            _T2_CACHE_DIR = tempfile.mkdtemp(prefix="montage_t2cache_")
            import atexit
            atexit.register(shutil.rmtree, _T2_CACHE_DIR, True)
        n = len(_T2_CACHE)
        cp = [os.path.join(_T2_CACHE_DIR, f"{n}_bg.png"), os.path.join(_T2_CACHE_DIR, f"{n}_fg.png")]
        shutil.copyfile(str(out_paths["bg"]), cp[0])
        shutil.copyfile(str(out_paths["fg"]), cp[1])
        _T2_CACHE[key] = (cp, info)
    except OSError:
        pass
    return info


def t2_build_static_layers(cfg, tmp):
    """Template 2 'build_background' hook: writes the BACKGROUND + FOREGROUND plates into tmp and points the
    pipeline at them (cfg['background'] -> bg png, cfg['_t2_fg'] -> foreground png)."""
    cfg["t2"] = t2_cfg(cfg.get("t2"))
    W, H = cfg["canvas"]
    paths = {"bg": os.path.join(tmp, "t2_bg.png"), "fg": os.path.join(tmp, "t2_fg.png")}
    make_t2_static(W, H, cfg["t2"], paths, cfg.get("video_box"))
    cfg["background"] = {"type": "image", "path": paths["bg"]}
    cfg["_t2_fg"] = paths["fg"]
    cfg["_t2_wave"] = t2_wave_data(cfg)           # Part 4C: real audio peaks (or procedural fallback)
    t2_panel_bake(cfg, paths["fg"], tmp)          # Part 4B: bottom panel baked into the plate; playhead sprite -> cfg["_t2_playhead"]
    # Part 4C: split screen.  Reuses Template 1's machinery: cfg["split"] (derived here, never stored) + cfg["_split_bg"]
    cfg.pop("_t2_split_ring", None)
    if cfg["t2"]["split"]["on"]:
        cfg["split"] = t2_split_params(cfg)
        cfg["_split_bg"] = paths["bg"]            # the plain T2 background (the video window is plain dark in it)
        cfg["_t2_split_ring"] = t2_make_split_ring(cfg, paths["bg"], os.path.join(tmp, "t2_split_ring.png"))
    else:
        cfg.pop("split", None)
        cfg.pop("_split_bg", None)


# ---- Template 2: questions --------------------------------------------------------------
def _c_t2_text(s):
    s = s.strip()
    return "" if s == "-" else s


def t2_ask_config(video_info):
    W, H = 1080, 1920
    pp = _PRESET.pop("path", None)
    if pp and os.path.isfile(pp):                       # a saved design picked in the selector: no questions
        tpl = json.loads(Path(pp).read_text(encoding="utf-8-sig"))
        tpl["t2"] = t2_cfg(tpl.get("t2"))
        tpl.setdefault("canvas", [W, H])
        tpl.setdefault("layers", [])
        tpl["background"] = {"type": "t2"}
        tpl["template_id"] = 2
        print(f"   Loaded saved template '{Path(pp).stem}' (style + texts; its frame, header and headline are not asked again).")
        return tpl
    saved = [] if _PRESET.get("sel") else [p for p in list_templates() if _tpl_template_id(p) == 2]
    if saved:
        labels = ["New Template 2 design (answer the questions)"] + [p.stem for p in saved]
        ch = ask_choice("\n--- Template 2: saved designs ---", labels, default=1) - 1
        if ch > 0:
            tpl = json.loads(saved[ch - 1].read_text(encoding="utf-8"))
            tpl["t2"] = t2_cfg(tpl.get("t2"))
            tpl.setdefault("canvas", [W, H])
            tpl.setdefault("layers", [])
            tpl["background"] = {"type": "t2"}
            tpl["template_id"] = 2
            print(f"   Loaded template '{saved[ch - 1].stem}'.")
            return tpl
    print("\n=== 3. Identity, header and headline  (Template 2 - Lime Creator Series, 1080x1920) ===")
    print("   (Enter = the poster default / your last answer.   '-' = hide that element)")
    t2 = {}
    t2["accent"] = ask("Accent color (hex or name)", default=T2_ACCENT, key="t2_accent", cast=c_color)
    t2["logo"] = ask("Logo glyph text", default=T2_DEFAULTS["logo"], key="t2_logo", cast=_c_t2_text)
    t2["name"] = ask("Header name", default=T2_DEFAULTS["name"], key="t2_name", cast=_c_t2_text)
    t2["subtitle"] = ask("Header subtitle", default=T2_DEFAULTS["subtitle"], key="t2_subtitle", cast=_c_t2_text)
    t2["pill"] = ask("Top-right pill text", default=T2_DEFAULTS["pill"], key="t2_pill", cast=_c_t2_text)
    t2["line1"] = ask("Headline line 1", default=T2_DEFAULTS["line1"], key="t2_line1", cast=_c_t2_text)
    t2["line2"] = ask("Headline line 2 (on the lime bar)", default=T2_DEFAULTS["line2"], key="t2_line2",
                      cast=_c_t2_text)
    d = T2_DEFAULT_BOX
    print("\n=== 4. Frame (the video window) and visible design parts ===")
    bw, bh = ask("Video window size WxH", default=f"{d['w']}x{d['h']}", key="t2_box_wh", cast=c_size_wh)
    bw, bh = min(bw, W - 20), min(bh, H - 400)
    bx = ask("Video window left position (px from the left)", default=d["x"], key="t2_box_x", cast=c_int)
    by = ask("Video window top position (px from the top)", default=d["y"], key="t2_box_y", cast=c_int)
    bx, by = max(0, min(bx, W - bw)), max(0, min(by, H - bh))
    mode = ask_choice("How should the video fit its window?",
                      ["fit  (whole video visible, may leave gaps)", "fill (crop to cover the window)"],
                      default=2, key="t2_fit")
    for k, label in (("show_bg_shapes", "the background shapes (lime bands / diagonals)"),
                     ("show_dots", "the dot grids"), ("show_header", "the header (logo, name, subtitle)"),
                     ("show_pill", "the top-right pill"), ("show_headline", "the headline")):
        v = yn(f"Show {label}?", default=D.get("t2_" + k, "y") == "y")
        D["t2_" + k] = "y" if v else "n"
        t2[k] = v
    tpl = {"template_id": 2, "canvas": [W, H],
           "video_box": {"x": bx, "y": by, "w": bw, "h": bh, "mode": "fit" if mode == 1 else "fill"},
           "background": {"type": "t2"}, "layers": [], "t2": t2_cfg(t2)}
    return maybe_save_template(tpl)


# ---- Template 2: chapter tag (Part 3A) ----------------------------------------------------------
# Poster (941 px wide) -> 1080 px: x1.1477.  Tag plate = poster (112,343)-(315,418), i.e. 18 px right / 42 px below
# the top-left corner of the video window (default window: 110,352).
T2_TAG = {"dx": 18, "dy": 42, "w": 233, "h": 86, "radius": 14, "pad": 15, "num_cap": 33, "label_cap": 16,
          "plate_alpha": 0.64}


def t2_tag_pos(cfg):
    """Top-left canvas position of the chapter-tag plate (relative to the video window)."""
    b = cfg.get("video_box") or T2_DEFAULT_BOX
    return int(b["x"] + T2_TAG["dx"]), int(b["y"] + T2_TAG["dy"])


def t2_chapter_sprite(num, label, accent=T2_ACCENT, fonts=None):
    """Chapter tag: dark translucent rounded plate, big italic accent number (+ thin fading light line to its
    right), white upper-case label below.  Returns an RGBA PIL image (plate size, min 233x86, grows with the label)."""
    T = T2_TAG
    acc = t2_rgb(accent)
    num, label = str(num or "").strip(), str(label or "").strip().upper()
    hf, hsh = t2_font("headline", num, fonts)
    uf, _ = t2_font("ui_bold", label, fonts)
    nm = t2_text_mask(num or " ", hf, t2_size_for_cap(hf, T["num_cap"]), 0.0, 0.2 if hsh else 0.0)
    lm = t2_text_mask(label or " ", uf, t2_size_for_cap(uf, T["label_cap"]), 0.06)
    pad = T["pad"]
    w = int(max(T["w"], 2 * pad + lm.width, 2 * pad + nm.width + 18 + 60))
    w = min(w, 560)
    if lm.width > w - 2 * pad:                       # very long label: shrink it to fit the plate
        lm = lm.resize((max(1, w - 2 * pad), max(1, int(lm.height * (w - 2 * pad) / float(lm.width)))), Image.LANCZOS)
    h = T["h"]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    t2_paint(img, t2_rrect_mask((0, 0, w, h), T["radius"]), (6, 9, 12, int(255 * T["plate_alpha"])))
    ny = 14
    t2_paint(img, (nm, (pad, ny)), acc + (255,))
    ly = h - 12 - lm.height
    t2_paint(img, (lm, (pad, ly)), (255, 255, 255, 255))
    # thin light line right of the number, fading out to the right
    x0, x1 = pad + nm.width + 18, w - 10
    if x1 - x0 > 8:
        cy = ny + nm.height // 2
        ln = Image.new("RGBA", (x1 - x0, 2), (0, 0, 0, 0))
        px_ = ln.load()
        for x in range(ln.width):
            a = int(235 * (1.0 - 0.75 * x / float(ln.width)))
            for y in range(2):
                px_[x, y] = (238, 240, 238, a)
        img.alpha_composite(ln, (x0, cy))
    return img


def t2_resolve_chapters(cfg, duration):
    """Chapters -> [{"start","end","num","label","anim","dur"}] sorted by start.
    start = the phrase found in the caption SRT (trigger, via find_trigger; tries every stream) else the fixed time.
    Auto number = 01, 02, ... in time order.  A chapter ends when the next one starts (+ the transition time)."""
    t2 = t2_cfg(cfg.get("t2"))
    if not t2["chapters_on"] or not t2["chapters"]:
        return []
    cues_all = []
    for c in caption_streams(cfg):
        try:
            cues_all.append(parse_srt(c["srt"]))
        except Exception:
            pass
    found = []
    for ch in t2["chapters"]:
        st = None
        if ch["trigger"]:
            for cues in cues_all:
                st = find_trigger(cues, ch["trigger"])
                if st is not None:
                    break
        if st is None:
            st = ch["start"]
        if st is None:
            print(f"   [!] chapter '{ch['label'] or ch['num']}': trigger '{ch['trigger']}' not found and no start time - skipped.")
            continue
        found.append((float(st), ch))
    found.sort(key=lambda a: a[0])
    out = []
    for i, (st, ch) in enumerate(found):
        d = ch["anim_dur"] if ch["anim_dur"] else t2["chapter_anim_dur"]
        out.append({"start": st, "num": ch["num"] or "%02d" % (i + 1), "label": ch["label"],
                    "anim": ch["anim"] or t2["chapter_anim"], "dur": max(0.05, float(d)), "end": ch["end"]})
    for i, c in enumerate(out):
        nxt = out[i + 1]["start"] + out[i + 1]["dur"] if i + 1 < len(out) else duration + 1
        c["end"] = max(c["start"] + 0.2, min(c["end"], nxt) if c["end"] else nxt)
    return out


def t2_chapter_items(cfg, duration):
    t2 = t2_cfg(cfg.get("t2"))
    items = []
    x, y = t2_tag_pos(cfg)
    for c in t2_resolve_chapters(cfg, duration):
        if c["start"] >= duration:
            continue
        spr = t2_chapter_sprite(c["num"], c["label"], t2["accent"], t2.get("fonts"))
        items.append(Item(spr, c["start"], c["end"], x + spr.width / 2.0, y + spr.height / 2.0,
                          c["anim"], c["dur"], out=True))
    return items


def t2_ask_chapters(cues, duration):
    """Questions for the chapter tags. Returns the t2 keys to merge into cfg['t2'] ({} = none / keep defaults)."""
    if not yn("Add chapter tags (like '01 INTRO' at the top-left of the video window)?",
              default=D.get("t2_chapters_ask", "n") == "y"):
        D["t2_chapters_ask"] = "n"
        return {}
    D["t2_chapters_ask"] = "y"
    print("   For each chapter give its label, and WHEN it starts: a time (seconds or mm:ss) or a phrase")
    print("   from the captions (found automatically in the first SRT). Press Enter on the label to finish.")
    chapters = []
    while True:
        n = len(chapters) + 1
        label = ask(f"Chapter {n} label (Enter = finish)", allow_empty=True, cast=lambda s: s.strip())
        if not label:
            if not chapters:
                print("   (no chapters added)")
            break

        def _when(s):
            try:
                return ("t", c_time(s))
            except (ValueError, OSError):
                if cues and find_trigger(cues, s) is None:
                    raise ValueError("that phrase was not found in the captions; type a time or another phrase")
                return ("p", s.strip())
        kind, val = ask(f"   '{label}' starts at (time or caption phrase)", cast=_when)
        num = ask("   Number (Enter = automatic 01, 02, ...)", allow_empty=True, cast=lambda s: s.strip()) or ""
        chapters.append({"start": val if kind == "t" else None, "trigger": val if kind == "p" else "",
                         "num": num, "label": label})
    if not chapters:
        return {}
    anim = ask_anim("Chapter change animation", default="slide_up", key="t2_chapter_anim")
    dur = ask("Chapter animation duration (seconds)", default=0.35, key="t2_chapter_dur", cast=c_float)
    return {"chapters": chapters, "chapters_on": True, "chapter_anim": anim, "chapter_anim_dur": dur}


# ---- Template 2: dynamic parts - hooks ------------------------------------------------------
# ---- Template 2: floating B-roll card (Part 3B) ----------------------------------------------------
# Poster card = poster (680,490)-(925,810), tilted +4 deg (right side up) => upright ~258 x 350 px at 1080 wide:
# thick cream border, soft shadow, media inside, black label strip (accent icon + italic label) and a thick
# accent bar under the strip.  It overlaps the video window's right edge (card centre ~9 px right of the edge).
#   image media  -> a normal timeline Item (drawn by the Pillow overlay pass, above the foreground plate)
#   video media  -> the existing video-layer mechanism: t2_prepare_card_layers() bakes the card (frame + looped,
#                   muted clip + slide/rotation animation) into a small alpha clip that FFmpeg overlays at a fixed
#                   position above the foreground plate (see build_ffmpeg_cmd: layer key "_xy").
T2_CARD = {"w": 258, "h": 350, "radius": 26, "border": 5, "border_col": (244, 241, 232),
           "strip_inset": 6, "strip_h": 58, "strip_bottom": 14, "strip_radius": 14, "strip_col": (8, 10, 12, 244),
           "bar_bottom": 3, "bar_x0": 0.16, "bar_x1": 0.84, "icon": 42, "icon_gap": 19, "text_pad": 23,
           "label_cap": 26, "shadow_blur": 14, "shadow_dy": 10, "shadow_alpha": 0.62, "room": 56,
           "cx_off": 9, "cy_frac": {1: 0.4227, 2: 0.4227, 3: 0.74}}


_T2_CARD_PARTS = {}


def c_card_icon(s):
    """Answer of the card-icon question -> 'code' | 'phone' | 'chip' | 'none' | path of a PNG/ICO."""
    s = s.strip().translate(AR_DIGITS)
    m = {"1": "code", "2": "phone", "3": "chip", "4": "none"}
    if s in m:
        return m[s]
    if os.path.isfile(clean_path(s)):
        return clean_path(s)
    raise ValueError("use 1-4 or a valid image path")


def t2_card_center(cfg, slot):
    """Centre (cx, cy) of floating-card slot 1 (right-upper, poster) / 2 (left-upper) / 3 (right-lower).
    Positions follow the video window, so a moved window keeps the card on its edge."""
    W, H = cfg["canvas"]
    b = dict(T2_DEFAULT_BOX)
    b.update({k: v for k, v in (cfg.get("video_box") or {}).items() if v is not None})
    T, k = T2_CARD, W / 1080.0
    cy = b["y"] + T["cy_frac"].get(slot, T["cy_frac"][1]) * b["h"]
    cx = b["x"] - T["cx_off"] * k if slot == 2 else b["x"] + b["w"] + T["cx_off"] * k
    hw = (T["w"] * 0.9976 + T["h"] * 0.0698) * k / 2.0
    hh = (T["h"] * 0.9976 + T["w"] * 0.0698) * k / 2.0
    return max(hw + 4, min(W - hw - 4, cx)), max(hh + 4, min(H - hh - 4, cy))


def t2_card_parts(label, icon, icon_path, accent=T2_ACCENT, fonts=None, canvas_w=1080):
    """Everything about a card that does not change between frames, drawn at 2x (supersampled; the final
    sprite is halved): 'under' (shadow + border plate), 'over' (accent bar + label strip + icon + label),
    'win' (L mask of the media window), 'wbox' (window size).  Cached."""
    key = (label, icon, icon_path, str(accent), json.dumps(fonts or {}, sort_keys=True), canvas_w)
    hit = _T2_CARD_PARTS.get(key)
    if hit:
        return hit
    T, k = T2_CARD, canvas_w / 1080.0
    S = 2.0 * k
    acc = t2_rgb(accent)
    w, h = T["w"], T["h"]
    P = int(round(T["room"] * S))
    size = (int(round(w * S)) + 2 * P, int(round(h * S)) + 2 * P)

    def R(x0, y0, x1, y1):
        return (P + x0 * S, P + y0 * S, P + x1 * S, P + y1 * S)

    under = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow = t2_rrect_mask(R(0, T["shadow_dy"], w, h + T["shadow_dy"]), T["radius"] * S)
    t2_paint(under, t2_glow(shadow, T["shadow_blur"] * S, 1.0), (0, 0, 0, int(255 * T["shadow_alpha"])))
    t2_paint(under, t2_rrect_mask(R(0, 0, w, h), T["radius"] * S), tuple(T["border_col"]) + (255,))
    b = T["border"]
    wm, (wox, woy) = t2_rrect_mask(R(b, b, w - b, h - b), (T["radius"] - b) * S)
    win = Image.new("L", size, 0)
    win.paste(wm, (wox, woy))
    wb = win.getbbox()

    over = Image.new("RGBA", size, (0, 0, 0, 0))
    has_strip = bool(label) or icon not in ("none", None, "")
    if has_strip:
        sx0, sx1 = T["strip_inset"], w - T["strip_inset"]
        sy1 = h - T["strip_bottom"]
        sy0 = sy1 - T["strip_h"]
        t2_paint(over, t2_rrect_mask(R(w * T["bar_x0"], sy1 - 6, w * T["bar_x1"], h - T["bar_bottom"]), 4 * S),
                 acc + (255,))
        t2_paint(over, t2_rrect_mask(R(sx0, sy0, sx1, sy1), T["strip_radius"] * S), tuple(T["strip_col"]))
        cy = (sy0 + sy1) / 2.0
        tx = sx0 + T["text_pad"]
        if icon not in ("none", None, ""):
            isz = int(round(T["icon"] * S))
            ic = Image.new("RGBA", (isz, isz), (0, 0, 0, 0))
            _draw_icon(ic, icon, (0, 0, isz, isz), icon_path or None)
            if icon != "image":
                col = Image.new("RGBA", ic.size, acc + (255,))
                col.putalpha(ic.getchannel("A"))
                ic = col
            over.alpha_composite(ic, (int(round(P + tx * S)), int(round(P + (cy - T["icon"] / 2.0) * S))))
            tx += T["icon"] + T["icon_gap"]
        if label:
            txt = label.upper()
            hf, hsh = t2_font("headline", txt, fonts)
            max_w = (sx1 - T["text_pad"] - tx) * S
            m, _, _ = t2_fit_text(txt, hf, max_w, T["label_cap"] * S, 0.01, 0.2 if hsh else 0.0)
            t2_paint(over, (m, (int(round(P + tx * S)), int(round(P + cy * S - m.height / 2.0)))), (255, 255, 255, 255))
    parts = {"under": under, "over": over, "win": win, "wbox": (wb[2] - wb[0], wb[3] - wb[1]) if wb else (2, 2),
             "wpos": (wb[0], wb[1]) if wb else (0, 0), "size": size, "S": S,
             "card": (int(round(w * k)), int(round(h * k)))}
    _T2_CARD_PARTS[key] = parts
    return parts


T2_CARD_BLEED = 3        # media is drawn this many px (1x) beyond the window; the window mask trims it


def t2_card_media_size(parts):
    """Size (px) the media is scaled to before it goes into the card (window size at 1x + a small bleed)."""
    ww, wh = parts["wbox"]
    return (ww + 1) // 2 + 2 * T2_CARD_BLEED, (wh + 1) // 2 + 2 * T2_CARD_BLEED


def _t2_card_static(parts, angle):
    """The parts of a card that never change (shadow + border plate, bar + strip + label, window mask),
    rotated by `angle` and reduced to 1x.  Cached per angle: video cards only redo the media layer per frame."""
    cache = parts.setdefault("_rot", {})
    key = round(float(angle), 3)
    if key not in cache:
        def rot(img):
            r = img.rotate(angle, resample=Image.BICUBIC, expand=True) if abs(angle) > 0.05 else img
            return r.resize((max(2, r.width // 2), max(2, r.height // 2)), Image.LANCZOS)
        cache[key] = {"U": rot(parts["under"]), "O": rot(parts["over"]), "M": rot(parts["win"])}
    return cache[key]


def t2_card_assemble(parts, media, angle):
    """One finished card sprite (RGBA, tilted by `angle` degrees = counter-clockwise, padded for the shadow).
    media = PIL image (cover-fitted into the window) or None (neutral placeholder)."""
    st = _t2_card_static(parts, angle)
    mw, mh = t2_card_media_size(parts)
    if media is None:
        media = Image.new("RGB", (mw, mh), (46, 52, 60))
    if media.mode == "RGBA":
        bgc = Image.new("RGBA", media.size, (20, 22, 26, 255))
        bgc.alpha_composite(media)
        media = bgc
    media = media.convert("RGB")
    if media.size != (mw, mh):
        sc = max(mw / float(media.width), mh / float(media.height))
        nw, nh = max(mw, int(math.ceil(media.width * sc))), max(mh, int(math.ceil(media.height * sc)))
        media = media.resize((nw, nh), Image.LANCZOS if sc < 1 else Image.BICUBIC)
        l, t = (nw - mw) // 2, (nh - mh) // 2
        media = media.crop((l, t, l + mw, t + mh))
    # only the media rectangle is rotated per frame (cheap); the window centre = the card centre, rotated about it
    U = st["U"]
    layer = media.convert("RGBA")
    if abs(angle) > 0.05:
        layer = layer.rotate(angle, resample=Image.BILINEAR, expand=True)
    th = math.radians(angle)
    dx = (parts["wpos"][0] + parts["wbox"][0] / 2.0) / 2.0 - parts["size"][0] / 4.0
    dy = (parts["wpos"][1] + parts["wbox"][1] / 2.0) / 2.0 - parts["size"][1] / 4.0
    vx, vy = dx * math.cos(th) + dy * math.sin(th), -dx * math.sin(th) + dy * math.cos(th)
    m = Image.new("RGBA", U.size, (0, 0, 0, 0))
    m.paste(layer, (int(round((U.width - layer.width) / 2.0 + vx)), int(round((U.height - layer.height) / 2.0 + vy))))
    m.putalpha(ImageChops.multiply(m.getchannel("A"), st["M"]))
    out = U.copy()
    out.alpha_composite(m)
    out.alpha_composite(st["O"])
    return out


def t2_resolve_cards(cfg, duration):
    """Cards -> [{..card keys.., "start","end","kind","angle","cx","cy","anim","dur"}] sorted by start.
    start = the phrase found in the caption SRT (find_trigger, every stream) else the fixed time.
    end = start + hold, or (next card in the SAME slot starts + 0.25 s): the old card slides out while the
    new one slides in."""
    t2 = t2_cfg(cfg.get("t2"))
    if not t2["cards_on"] or not t2["cards"]:
        return []
    cues_all = []
    for c in caption_streams(cfg):
        try:
            cues_all.append(parse_srt(c["srt"]))
        except Exception:
            pass
    rows = []
    for cd in t2["cards"]:
        if not os.path.isfile(cd["media"]):
            print(f"   [!] floating card: file not found, skipped: {cd['media']}")
            continue
        st = None
        if cd["trigger"]:
            for cues in cues_all:
                st = find_trigger(cues, cd["trigger"])
                if st is not None:
                    break
        if st is None:
            st = cd["start"]
        if st is None:
            print(f"   [!] floating card '{cd['label'] or Path(cd['media']).name}': phrase '{cd['trigger']}' not found "
                  f"and no start time - skipped.")
            continue
        r = dict(cd)
        r["start"], r["end"] = float(st), float(st) + cd["hold"]
        rows.append(r)
    rows.sort(key=lambda r: r["start"])
    for i, r in enumerate(rows):
        for o in rows[i + 1:]:
            if o["slot"] == r["slot"] and o["start"] > r["start"]:
                r["end"] = min(r["end"], o["start"] + 0.25)
                break
    out = []
    rot = t2["card_rot"]
    for r in rows:
        if r["start"] >= duration:
            continue
        r["end"] = min(r["end"], duration + 1)
        r["kind"] = "video" if r["media"].lower().endswith(VIDEO_EXTS) else "image"
        r["angle"] = -rot if r["slot"] == 2 else rot
        r["cx"], r["cy"] = t2_card_center(cfg, r["slot"])
        r["anim"] = "card_l" if r["slot"] == 2 else "card_r"
        r["dur"] = t2["card_anim_dur"]
        out.append(r)
    return out


def _t2_card_parts_for(cfg, r):
    t2 = t2_cfg(cfg.get("t2"))
    return t2_card_parts(r["label"], r["icon"], r["icon_path"], t2["accent"], t2.get("fonts"), cfg["canvas"][0])


def t2_card_items(cfg, duration, with_video=False):
    """Timeline Items of the floating cards. Image cards always; video cards only when with_video (the
    --still preview shows their first frame; a real render bakes them into video layers instead)."""
    items = []
    for r in t2_resolve_cards(cfg, duration):
        if r["kind"] == "video" and not with_video:
            continue
        try:
            media = _first_frame(r["media"]) if r["kind"] == "video" else Image.open(r["media"])
            if media is not None and r["kind"] != "video":
                media.load()
        except Exception as e:
            print(f"   [!] floating card media unreadable ({e}): {r['media']}")
            media = None
        spr = t2_card_assemble(_t2_card_parts_for(cfg, r), media, r["angle"])
        items.append(Item(spr, r["start"], r["end"], r["cx"], r["cy"], r["anim"], r["dur"], out=True))
    return items


def t2_prepare_card_layers(cfg, info, tmpdir):
    """Video floating cards -> video layers (same mechanism as ask_video_layers' b-roll).  For each card an alpha
    clip (qtrle) is baked: the media clip is looped + muted, every frame goes through the SAME sprite builder and
    animation code as image cards (anim_state / draw_item), on a small local canvas.  The layer is drawn at a fixed
    canvas position (key "_xy") with area "canvas", i.e. above the foreground plate, so it is never clipped by the
    video window.  Returns [] when there are no video cards."""
    W, H = cfg["canvas"]
    fps = info["fps"]
    fps_f = float(fps)
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    dur_eff = info["duration"]
    if cfg.get("preview"):
        dur_eff = min(dur_eff, float(cfg["preview"]))
    layers = []
    for n, r in enumerate(x for x in t2_resolve_cards(cfg, info["duration"]) if x["kind"] == "video"):
        if r["start"] >= dur_eff:
            continue
        parts = _t2_card_parts_for(cfg, r)
        ref = t2_card_assemble(parts, None, r["angle"])
        # the clip only has to cover where the card can be on screen: slide path (towards its own side edge),
        # a little overshoot (ease-out-back), the rotation settle - clipped to the canvas (smaller = faster overlay)
        slide, back = int(0.21 * W) + 6, int(0.015 * W) + 12
        extra = int(ref.width * 0.2) + 8
        dirn = -1 if r["anim"] == "card_l" else 1
        x0 = int(round(r["cx"] - ref.width / 2.0)) - (back if dirn > 0 else slide)
        x1 = int(round(r["cx"] + ref.width / 2.0)) + (slide if dirn > 0 else back)
        y0, y1 = int(round(r["cy"] - ref.height / 2.0)) - extra, int(round(r["cy"] + ref.height / 2.0)) + extra
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if (x1 - x0) % 2:
            x1, x0 = (x1 + 1, x0) if x1 < W else (x1, x0 - 1)
        if (y1 - y0) % 2:
            y1, y0 = (y1 + 1, y0) if y1 < H else (y1, y0 - 1)
        Wp, Hp = x1 - x0, y1 - y0
        lcx, lcy = r["cx"] - x0, r["cy"] - y0
        s, e_true = r["start"], r["end"]
        e = min(e_true, dur_eff)
        nfr = max(1, int(math.ceil((e - s) * fps_f)))
        ww, wh = t2_card_media_size(parts)
        out = os.path.join(tmpdir, f"t2card{n}.mov")
        rd = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", r["media"],
                               "-an", "-vf", f"fps={fps_s},scale={ww}:{wh}:force_original_aspect_ratio=increase,"
                                             f"crop={ww}:{wh},format=rgb24",
                               "-frames:v", str(nfr), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        wr = subprocess.Popen([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                               "-video_size", f"{Wp}x{Hp}", "-framerate", fps_s, "-i", "pipe:0",
                               "-c:v", "qtrle", "-pix_fmt", "argb", out],
                              stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        print(f"Preparing floating card {n + 1} ({Path(r['media']).name}, {nfr} frames)...")
        last = None
        try:
            for i in range(nfr):
                raw = _read_exact(rd.stdout, ww * wh * 3)
                frame = Image.frombytes("RGB", (ww, wh), raw) if len(raw) == ww * wh * 3 else last
                last = frame
                it = Item(t2_card_assemble(parts, frame, r["angle"]), s, e_true, lcx, lcy, r["anim"], r["dur"], True)
                canvas = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
                draw_item(canvas, it, anim_state(it.anim, it.progress(s + i / fps_f), W, H))
                wr.stdin.write(canvas.tobytes())
            wr.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        finally:
            rd.kill()
            rd.wait()
        err = wr.stderr.read().decode("utf-8", "replace")
        if wr.wait() != 0 or not os.path.isfile(out):
            raise SystemExit("[!] Could not prepare the floating card:\n" + err[-800:])
        layers.append({"path": out, "start": s, "end": e, "area": "canvas", "mode": "fit", "fade": 0.0,
                       "_xy": [x0, y0]})
    return layers


def t2_build_items(cfg, duration, splits, lbox, rbox):
    # Part 3B: floating B-roll cards (image cards here; video cards are baked into video layers, see render()).
    # Part 4A: about block.  Part 4B: bottom panel = baked into the foreground plate (+ FFmpeg playhead), no Items.  TODO(PART4C): waveform + dots
    return (t1_build_items(cfg, duration, splits, lbox, rbox) + t2_chapter_items(cfg, duration)
            + t2_card_items(cfg, duration, with_video=bool(cfg.get("_t2_still"))) + t2_about_items(cfg, duration)
            + t2_dots_items(cfg, duration) + t2_roadmap_items(cfg, duration))


def t2_ask_cards_cfg(cues):
    """Floating B-roll card questions (Template 2 wording). Returns the t2 keys to merge into cfg['t2']
    ({} = none): {"cards": [...], "card_rot": deg, "card_anim_dur": s}."""
    if not yn("\nAdd floating B-roll cards (a tilted photo / short video card on the edge of the video window, "
              "with a label like 'DEVELOPMENT')?", default=D.get("t2_cards_ask", "n") == "y"):
        D["t2_cards_ask"] = "n"
        return {}
    D["t2_cards_ask"] = "y"
    cards = []
    while True:
        print(f"\n--- Floating card #{len(cards) + 1} ---")
        e = {}
        e["media"] = ask("Card picture or short video (PNG/JPG/MP4...; a video loops, muted)",
                         cast=c_existing_file(IMAGE_EXTS + VIDEO_EXTS))
        e["label"] = ask("Label on the black strip, e.g. DEVELOPMENT  (Enter = none)", allow_empty=True,
                         cast=lambda s: s.strip().replace("\\n", " ")) or ""
        print("   " + ICON_LINE)
        ic = ask("Label icon", default="1", key="t2_card_icon", cast=c_card_icon)
        e["icon"], e["icon_path"] = ("image", ic) if ic not in ("code", "phone", "chip", "none") else (ic, "")
        print("   1=right-upper (poster)  2=left-upper  3=right-lower")
        e["slot"] = ask("Position", default="1", key="t2_card_slot",
                        cast=lambda s: int(s.translate(AR_DIGITS)) if s.strip().translate(AR_DIGITS) in ("1", "2", "3")
                        else (_ for _ in ()).throw(ValueError("choose 1-3")))
        e["start"], e["trigger"] = None, ""
        while True:
            raw = ask("Appears when this word/phrase is said (from the SRT)  -or-  a time in seconds")
            try:
                e["start"] = round(c_time(raw), 3)
                break
            except ValueError:
                pass
            t = find_trigger(cues, raw) if cues else None
            if t is None:
                print("   [!] that word was not found in the SRT. Try another word, or type a time.")
                continue
            e["trigger"], e["start"] = raw.strip(), round(t, 3)
            print(f"   -> found at {t:.2f}s")
            break
        e["hold"] = ask("How long it stays (seconds)", default=4, key="t2_card_hold", cast=c_float)
        cards.append(e)
        if not yn("Add another floating card?", default=True):
            break
    rot = ask("Card tilt in degrees (poster = 4)", default=4, key="t2_card_rot", cast=c_float)
    adur = ask("Card slide-in time (seconds)", default=0.5, key="t2_card_adur", cast=c_float)
    return {"cards": cards, "cards_on": True, "card_rot": rot, "card_anim_dur": adur}


def t2_ask_cards(cues):
    """Registry hook: the list of floating cards (interactive() stores it, with the style keys, in cfg['t2'])."""
    return t2_ask_cards_cfg(cues).get("cards", [])


T2_ABOUT_ICON_LINE = "1=laptop  2=phone  3=gear/AI  4=code  5=chip  6=none  or a path to a PNG/ICO"


def c_about_icon(s):
    k, p = t2_about_icon_spec(s)
    if k == "none" and s.strip().translate(AR_DIGITS) not in ("6", "none"):
        raise ValueError("use 1-6 or a valid image path")
    return p if k == "image" else k


def t2_about_geometry(cfg, n_rows=3):
    """Pixel geometry of the block (canvas px): y_base, sprite origin/size, column rect, per-row icon centres."""
    A = T2_ABOUT
    W, H = cfg.get("canvas") or (1080, 1920)
    k = W / 1080.0
    b = cfg.get("video_box") or T2_DEFAULT_BOX
    y_base = b["y"] + b["h"] + A["box_gap"] * k
    y_base = min(y_base, H - (A["h"] + A["top"] + 6) * k)
    n = max(1, min(A["max_rows"], n_rows))
    pitch = (A["row_pitch"] if n <= 3 else A["row_pitch4"]) * k
    cy0 = y_base + A["row_cy"] * k - pitch * (n - 1) / 2.0
    g = {"k": k, "y_base": y_base, "ox": int(round((A["x_left"] - A["pad_x"]) * k)), "oy": int(round(y_base + A["top"] * k)),
         "w": int(round((A["right"] - A["x_left"] + 2 * A["pad_x"]) * k)), "h": int(round(A["h"] * k)),
         "col": (A["x_left"] * k, y_base, (A["x_left"] + A["col_w"]) * k, y_base + A["h"] * k + A["top"] * k),
         "text_x": A["text_x"] * k, "right": A["right"] * k, "pitch": pitch, "row_scale": pitch / (A["row_pitch"] * k),
         "icon_cx": A["icon_cx"] * k, "rows": [(A["icon_cx"] * k, cy0 + i * pitch) for i in range(n)]}
    return g


def t2_about_icon(kind, size, accent=T2_ACCENT, path=None):
    """Lime line icon (RGBA, size x size).  Kinds: laptop, phone, gear, code, chip (drawn 4x, downsampled) or
    'image' = a custom PNG/ICO (kept in its own colours).  Reuses _draw_icon for phone / code / chip / image."""
    size = max(8, int(round(size)))
    S = size * 4
    ic = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(ic)
    wh = (255, 255, 255, 255)
    wid = max(3, int(S * 0.075))
    if kind == "laptop":
        d.rounded_rectangle((S * 0.16, S * 0.18, S * 0.84, S * 0.64), radius=S * 0.05, outline=wh, width=wid)
        d.rounded_rectangle((S * 0.04, S * 0.72, S * 0.96, S * 0.80), radius=S * 0.04, fill=wh)
    elif kind == "gear":
        import math
        cx = cy = S / 2.0
        for i in range(8):
            a = math.radians(i * 45)
            ux, uy, vx, vy = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
            r0, r1, hw = S * 0.30, S * 0.46, S * 0.085
            d.polygon([(cx + ux * r0 + vx * hw, cy + uy * r0 + vy * hw), (cx + ux * r1 + vx * hw * 0.8, cy + uy * r1 + vy * hw * 0.8),
                       (cx + ux * r1 - vx * hw * 0.8, cy + uy * r1 - vy * hw * 0.8), (cx + ux * r0 - vx * hw, cy + uy * r0 - vy * hw)], fill=wh)
        d.ellipse((cx - S * 0.36, cy - S * 0.36, cx + S * 0.36, cy + S * 0.36), fill=wh)
        d.ellipse((cx - S * 0.16, cy - S * 0.16, cx + S * 0.16, cy + S * 0.16), fill=(0, 0, 0, 0))
    elif kind in ("phone", "code", "chip", "image"):
        _draw_icon(ic, kind, (0, 0, S, S), path or None)
    ic = ic.resize((size, size), Image.LANCZOS)
    if kind != "image":
        col = Image.new("RGBA", ic.size, t2_rgb(accent) + (255,))
        col.putalpha(ic.getchannel("A"))
        ic = col
    return ic


def _t2_about_wrap(text, font_path, size, max_w):
    f = load_font(font_path, max(4, int(round(size * 2))))
    lines, cur = [], ""
    for w in text.split():
        cand = (cur + " " + w) if cur else w
        if f.getlength(shape(cand)) / 2.0 <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def t2_about_fit_paragraph(text, font_path, col_w, cap_px, max_lines=3, min_scale=0.55):
    """Auto-fit a paragraph into max_lines x col_w: shrink the font (down to min_scale), re-wrap; if it still does not fit
    the text is cut with '...'.  RTL/Arabic works (wrapping on the logical text, each line shaped on its own).
    Returns (lines, scale)."""
    text = " ".join(str(text or "").split())
    if not text:
        return [], 1.0
    size0 = t2_size_for_cap(font_path, cap_px)
    sc = 1.0
    while True:
        lines = _t2_about_wrap(text, font_path, size0 * sc, col_w)
        if len(lines) <= max_lines or sc <= min_scale + 1e-6:
            break
        sc = max(min_scale, sc - 0.05)
    if len(lines) > max_lines:
        keep = lines[:max_lines - 1]
        last = " ".join(lines[max_lines - 1:])
        words = last.split()
        while words:
            cand = " ".join(words) + "..."
            if len(_t2_about_wrap(cand, font_path, size0 * sc, col_w)) <= 1:
                break
            words.pop()
        lines = keep + ([" ".join(words) + "..."] if words else [lines[max_lines - 1][:10] + "..."])
    return lines, sc


def t2_about_sprite(cfg, state, want_meta=False):
    """One block STATE as an RGBA sprite (origin = geometry ox/oy).  meta = {"ink": {"title","para":[..],"rows":[(icon_bbox,
    text_bbox)]}, "geo": geometry} with canvas-px boxes, for overflow checks."""
    t2 = t2_cfg(cfg.get("t2"))
    A = T2_ABOUT
    rows = state["rows"][:A["max_rows"]]
    g = t2_about_geometry(cfg, len(rows))
    k, oy0, ox0 = g["k"], g["oy"], g["ox"]
    img = Image.new("RGBA", (g["w"], g["h"]), (0, 0, 0, 0))
    acc = t2_rgb(t2["accent"])
    fonts = t2.get("fonts")
    ink = {"title": None, "para": [], "rows": []}
    yb = g["y_base"] - oy0                              # y_base in sprite coords

    def put(mask, x, cy, fill, left=True):
        x0 = int(round(x - ox0 - (0 if left else mask.width)))
        y0 = int(round(cy - oy0 - mask.height / 2.0))
        t2_paint(img, (mask, (x0, y0)), fill)
        return (x0 + ox0, y0 + oy0, x0 + ox0 + mask.width, y0 + oy0 + mask.height)

    col_x0, col_x1 = A["x_left"] * k, (A["x_left"] + A["col_w"]) * k
    title = state["title"]
    if title:
        sq = A["sq"] * k
        sx0, sy0 = col_x0 - ox0, yb + A["sq_y"] * k
        t2_paint(img, t2_rrect_mask((sx0, sy0, sx0 + sq, sy0 + sq), 1.5 * k), acc + (255,))
        tf, _ = t2_font("ui_bold", title, fonts)
        tt = title if has_arabic(title) else title.upper()
        m, _, _ = t2_fit_text(tt, tf, (A["col_w"] - A["title_dx"]) * k, A["title_cap"] * k, 0.0 if has_arabic(tt) else A["title_tr"])
        ink["title"] = put(m, col_x0 + A["title_dx"] * k, g["y_base"] + A["title_cy"] * k, A["muted"] + (255,))
    pf, _ = t2_font("ui", state["paragraph"], fonts)
    lines, sc = t2_about_fit_paragraph(state["paragraph"], pf, A["col_w"] * k, A["para_cap"] * k, A["para_lines"], A["min_scale"])
    rtl = is_rtl_text(state["paragraph"])
    for i, ln in enumerate(lines):
        m, _, _ = t2_fit_text(ln, pf, A["col_w"] * k, A["para_cap"] * k * sc)
        cy = g["y_base"] + A["para_cy"] * k + i * A["para_pitch"] * k * sc
        ink["para"].append(put(m, col_x1 if rtl else col_x0, cy, A["para_col"] + (255,), left=not rtl))
    if rows or title or lines:
        dx = A["div_x"] * k - ox0
        t2_paint(img, t2_rrect_mask((dx, yb + A["div_y0"] * k, dx + max(1.0, 1.5 * k), yb + A["div_y1"] * k), 0.7 * k), A["div_col"])
    for (icx, cy), r in zip(g["rows"], rows):
        isz = A["icon"] * k * g["row_scale"]
        ib = None
        if r["icon"] != "none":
            ic = t2_about_icon(r["icon"], isz, t2["accent"], r["icon_path"])
            ix, iy = int(round(icx - ic.width / 2.0 - ox0)), int(round(cy - ic.height / 2.0 - oy0))
            img.alpha_composite(ic, (ix, iy))
            ib = (ix + ox0, iy + oy0, ix + ox0 + ic.width, iy + oy0 + ic.height)
        tb = None
        if r["text"]:
            rf, _ = t2_font("ui", r["text"], fonts)
            m, _, _ = t2_fit_text(r["text"], rf, g["right"] - g["text_x"], A["row_cap"] * k * g["row_scale"])
            tb = put(m, g["text_x"], cy, (255, 255, 255, 255))
        ink["rows"].append((ib, tb))
    return (img, {"ink": ink, "geo": g, "lines": len(lines), "scale": sc}) if want_meta else img


def t2_resolve_about(cfg, duration):
    """About states -> [{"start","end","anim","dur", + state keys}] sorted by start (trigger phrase via find_trigger in every
    caption stream, else the fixed time; the FIRST state may omit both = start 0).  A state ends when the next one starts
    (+ its transition time).  Empty list = the default (poster) state for the whole video.  [] when the block is off."""
    t2 = t2_cfg(cfg.get("t2"))
    if not t2["about_on"]:
        return []
    states = t2["about"] or t2_norm_about([T2_ABOUT_DEFAULT_STATE])
    cues_all = []
    for c in caption_streams(cfg):
        try:
            cues_all.append(parse_srt(c["srt"]))
        except Exception:
            pass
    found = []
    for i, s in enumerate(states):
        st = None
        if s["trigger"]:
            for cues in cues_all:
                st = find_trigger(cues, s["trigger"])
                if st is not None:
                    break
        if st is None:
            st = s["start"]
        if st is None and i == 0:
            st = 0.0
        if st is None:
            print(f"   [!] about block state {i + 1}: phrase '{s['trigger']}' not found and no start time - skipped.")
            continue
        found.append((float(st), s))
    found.sort(key=lambda a: a[0])
    out = []
    for st, s in found:
        d = s["anim_dur"] if s["anim_dur"] else t2["about_anim_dur"]
        r = dict(s)
        r.update({"start": st, "anim": s["anim"] or t2["about_anim"], "dur": max(0.05, float(d)), "end": s["end"]})
        out.append(r)
    for i, r in enumerate(out):
        nxt = out[i + 1]["start"] + out[i + 1]["dur"] if i + 1 < len(out) else duration + 1
        r["end"] = max(r["start"] + 0.2, min(r["end"], nxt) if r["end"] else nxt)
    return out


def t2_about_items(cfg, duration):
    items = []
    for r in t2_resolve_about(cfg, duration):
        if r["start"] >= duration:
            continue
        spr = t2_about_sprite(cfg, r)
        g = t2_about_geometry(cfg, len(r["rows"]))
        items.append(Item(spr, r["start"], r["end"], g["ox"] + spr.width / 2.0, g["oy"] + spr.height / 2.0,
                          r["anim"], r["dur"], out=True))
    return items


def t2_ask_about(cues, duration, on=None):
    """ABOUT ME + FEATURES block questions. Returns the t2 keys to merge into cfg['t2']:
    {"about_on": bool, "about": [states], "about_anim", "about_anim_dur"}  ({'about_on': False} = block disabled)."""
    if on is None:
        on = yn("\nShow the ABOUT ME + features block under the video window (paragraph + up to 4 icon rows)?",
                default=D.get("t2_about_ask", "y") == "y")
        D["t2_about_ask"] = "y" if on else "n"
    if not on:
        return {"about_on": False}
    D["t2_about_ask"] = "y"
    if yn("Use the poster texts (Passionate about technology... / Web Development, Mobile Development, AI Automation)?",
          default=D.get("t2_about_poster", "y") == "y"):
        D["t2_about_poster"] = "y"
        return {"about_on": True, "about": []}
    D["t2_about_poster"] = "n"
    print("   Each STATE = paragraph + title + up to 4 rows; it appears at a time or when a caption phrase is said.")
    states = []
    while True:
        n = len(states) + 1
        print(f"\n--- About state #{n} ---")
        s = {"title": ask("Small title (Enter = none)", default="ABOUT ME", key="t2_about_title", allow_empty=True,
                          cast=lambda v: v.strip()) or "",
             "paragraph": ask("Paragraph (3 lines max, shrinks to fit)", default=T2_ABOUT_DEFAULT_STATE["paragraph"],
                              key="t2_about_para", allow_empty=True, cast=lambda v: v.strip()) or "", "rows": []}
        print("   " + T2_ABOUT_ICON_LINE)
        while len(s["rows"]) < T2_ABOUT["max_rows"]:
            txt = ask(f"Row {len(s['rows']) + 1} text (Enter = finish)", allow_empty=True, cast=lambda v: v.strip())
            if not txt:
                break
            ic = ask("   icon", default="1", key="t2_about_icon", cast=c_about_icon)
            kind, ip = t2_about_icon_spec(ic)
            s["rows"].append({"icon": kind, "icon_path": ip, "text": txt})
        if n == 1:
            raw = ask("Appears at (time, or a phrase from the captions; Enter = from the start)", allow_empty=True,
                      cast=lambda v: v.strip())
        else:
            raw = ask("Appears at (time, or a phrase from the captions)", cast=lambda v: v.strip())
        s["start"], s["trigger"] = None, ""
        if raw:
            try:
                s["start"] = round(c_time(raw), 3)
            except ValueError:
                s["trigger"] = raw
                t = find_trigger(cues, raw) if cues else None
                print(f"   -> found at {t:.2f}s" if t is not None else "   [!] phrase not found in the SRT yet (it will be skipped unless found at render time)")
        states.append(s)
        if not yn("Add another state (the block changes at that moment)?", default=False):
            break
    anim = ask_anim("Block change animation", default="fade", key="t2_about_anim")
    dur = ask("Block animation duration (seconds)", default=0.4, key="t2_about_dur", cast=c_float)
    return {"about_on": True, "about": states, "about_anim": anim, "about_anim_dur": dur}


def t2_panel_icon(kind, size, accent=T2_ACCENT):
    """Lime 'layers' / 'bolt' icon (RGBA, size x size), drawn 4x and downsampled."""
    size = max(8, int(round(size)))
    S = size * 4
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    if kind == "layers":
        w = max(4, int(S * 0.09))
        d.polygon([(S * .5, S * .08), (S * .95, S * .32), (S * .5, S * .56), (S * .05, S * .32)], fill=255)
        for dy in (.18, .36):
            pts = [(S * .05, S * (.32 + dy) ), (S * .5, S * (.56 + dy)), (S * .95, S * (.32 + dy))]
            d.line(pts, fill=255, width=w, joint="curve")
    else:
        pts = [(.60, .02), (.18, .56), (.45, .56), (.36, .98), (.82, .40), (.55, .40)]
        d.polygon([(S * x, S * y) for x, y in pts], fill=255)
    m = m.resize((size, size), Image.LANCZOS)
    col = Image.new("RGBA", m.size, t2_rgb(accent) + (255,))
    col.putalpha(m)
    return col


def t2_panel_geometry(cfg):
    W, H = (cfg.get("canvas") or [1080, 1920])[:2]
    P = T2_PANEL
    kx, ky = W / T2_POSTER_W, H / T2_POSTER_H
    return {"W": W, "H": H, "kx": kx, "ky": ky, "k": (kx + ky) / 2.0,
            "box": (P["x0"] * kx, P["y0"] * ky, P["x1"] * kx, P["y1"] * ky),
            "tx0": P["track_x0"] * kx, "tx1": P["track_x1"] * kx,
            "row_cy": [(P["row0"] + i * P["pitch"]) * ky for i in range(P["max_rows"])],
            "ph_y": P["ph_top"] * ky}


def t2_panel_playhead_sprite(cfg):
    """White vertical line + small triangle on top.  Odd width so the line is centred on the middle pixel."""
    g = t2_panel_geometry(cfg)
    P, k = T2_PANEL, g["k"]
    w = 2 * int(math.ceil(P["tri_w"] * k / 2.0)) + 3
    h = int(round((P["ph_bot"] - P["ph_top"]) * g["ky"]))
    ss = T2_SS
    m = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(m)
    cx = w * ss / 2.0
    tw, th = P["tri_w"] * k * ss, P["tri_h"] * k * ss
    d.polygon([(cx - tw / 2, 0), (cx + tw / 2, 0), (cx, th)], fill=255)
    lw = P["ph_w"] * k * ss / 2.0
    d.rectangle((cx - lw, th - 2 * ss, cx + lw, h * ss), fill=255)
    m = m.resize((w, h), Image.LANCZOS)
    spr = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    spr.putalpha(m)
    return spr


T2_WAVE_N = 250          # peaks drawn in row 09


T2_DOTS = {"x_last": 880, "y": 1581, "pitch": 25.0, "r": 4.8, "grey": (122, 125, 124)}     # poster px


def t2_dot_plan(cfg):
    """-> (n_dots, resolved chapters).  n = min(chapters, 5), at least 3.  No chapters = decorative dots."""
    t2 = t2_cfg(cfg.get("t2"))
    chs = t2_resolve_chapters(cfg, 1e9) if (t2["panel"]["on"] and t2["panel"]["dots"] and t2["panel"].get("style") != "roadmap") else []
    return max(3, min(len(chs), 5)), chs


def t2_dot_index(i, total, n):
    """Chapter i of `total` -> which of the n dots is lime."""
    return min(n - 1, i) if total <= n else int(round(i * (n - 1) / float(total - 1)))


def t2_dots_sprite(cfg, n, active):
    """-> (RGBA sprite, (x, y) canvas position of its top-left).  n dots, dot `active` lime, the rest grey."""
    g = t2_panel_geometry(cfg)
    kx, k = g["kx"], g["k"]
    acc = t2_rgb(t2_cfg(cfg.get("t2"))["accent"])
    pitch, r = T2_DOTS["pitch"] * kx, T2_DOTS["r"] * k
    cx_last, cy = T2_DOTS["x_last"] * kx, T2_DOTS["y"] * g["ky"]
    left = int(math.floor(cx_last - (n - 1) * pitch - r)) - 2
    top = int(math.floor(cy - r)) - 2
    w, h = int(math.ceil(cx_last + r)) + 2 - left, int(math.ceil(2 * r)) + 4
    ss = T2_SS
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i in range(n):
        cx = cx_last - (n - 1 - i) * pitch - left
        col = acc + (255,) if i == active else T2_DOTS["grey"] + (255,)
        d.ellipse(((cx - r) * ss, (cy - top - r) * ss, (cx + r) * ss, (cy - top + r) * ss), fill=col)
    return im.resize((w, h), Image.LANCZOS), (left, top)


def t2_dots_items(cfg, duration):
    """One tiny sprite per chapter; the lime dot follows the current chapter (Items = the mechanism chapters already use)."""
    n, chs = t2_dot_plan(cfg)
    chs = [c for c in chs if c["start"] < duration]
    if not chs:
        return []
    cache, items = {}, []
    for i, c in enumerate(chs):
        a = t2_dot_index(i, len(chs), n)
        if a not in cache:
            cache[a] = t2_dots_sprite(cfg, n, a)
        spr, (x, y) = cache[a]
        s0 = 0.0 if i == 0 else c["start"]
        e0 = chs[i + 1]["start"] if i + 1 < len(chs) else duration + 1
        items.append(Item(spr, s0, e0, x + spr.width / 2.0, y + spr.height / 2.0, "none", 0.0, out=False))
    return items


def t2_wave_procedural(n=T2_WAVE_N):
    """Deterministic fake waveform (used when the video has no audio / the extraction failed)."""
    import random
    rnd = random.Random(1234)
    out = []
    for i in range(n):
        x = i / float(n)
        env = 0.55 + 0.30 * math.sin(x * 9.0) * math.sin(x * 3.1 + 0.7) + 0.15 * math.sin(x * 31.0)
        out.append(max(0.08, min(1.0, env * (0.55 + 0.45 * rnd.random()))))
    return out


def _t2_peaks_from_pcm(raw, n):
    """raw s16le mono bytes -> n normalised peaks (0..1).  numpy when available, else array()."""
    raw = raw[:len(raw) // 2 * 2]
    try:
        import numpy as np
        a = np.abs(np.frombuffer(raw, dtype="<i2").astype(np.int32))
        if a.size < n:
            return None
        edges = np.linspace(0, a.size, n + 1).astype(np.int64)
        pk = [float(v) for v in np.maximum.reduceat(a, edges[:-1])]
    except ImportError:
        from array import array
        arr = array("h")
        arr.frombytes(raw)
        if sys.byteorder == "big":
            arr.byteswap()
        if len(arr) < n:
            return None
        step = len(arr) / float(n)
        pk = []
        for i in range(n):
            a0 = int(i * step)
            seg = arr[a0:max(a0 + 1, int((i + 1) * step))]
            pk.append(float(max(max(seg), -min(seg))))
    mx = max(pk) if pk else 0.0
    if mx <= 0:
        return [0.05] * n
    return [max(0.05, (v / mx) ** 0.75) for v in pk]


def t2_wave_peaks(path, n=T2_WAVE_N, sr=4000):
    """Audio of `path` -> n peaks via ffmpeg (raw mono PCM at a low sample rate).  None on any failure / no audio."""
    try:
        r = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(sr),
                            "-f", "s16le", "pipe:1"], capture_output=True, timeout=180, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or len(r.stdout) < 2 * n:
            return None
        return _t2_peaks_from_pcm(r.stdout, n)
    except Exception:
        return None


def t2_wave_data(cfg):
    """{"src": "audio"|"procedural", "peaks": [...]} for row 09, or None when the panel / waveform is off.  Never raises."""
    try:
        pn = t2_cfg(cfg.get("t2"))["panel"]
        if not (pn["on"] and pn["wave"]):
            return None
        v = cfg.get("video")
        pk = t2_wave_peaks(v) if v and os.path.isfile(str(v)) else None
    except Exception:
        pk = None
    return {"src": "audio", "peaks": pk} if pk else {"src": "procedural", "peaks": t2_wave_procedural()}


def t2_panel_plate(cfg):
    """Draw the static panel.  -> None when disabled, else (RGBA plate image, (ox, oy), info) with
    info = {"box", "bars": [[(x0,y0,x1,y1) per bar segment] per row], "track": (x0, x1), "rows_cy", "ph_y", "ink": {...}}."""
    t2 = t2_cfg(cfg.get("t2"))
    pn = t2["panel"]
    if not pn["on"] or pn.get("style") == "roadmap":
        return None
    g = t2_panel_geometry(cfg)
    P, kx, ky, k = T2_PANEL, g["kx"], g["ky"], g["k"]
    acc = t2_rgb(t2["accent"])
    fonts = t2.get("fonts")
    lay = Image.new("RGBA", (g["W"], g["H"]), (0, 0, 0, 0))
    x0, y0, x1, y1 = g["box"]
    t2_paint(lay, t2_rrect_mask((x0, y0, x1, y1), P["radius"] * k), P["outline"] + (255,))
    ins = 1.6 * k
    t2_paint(lay, t2_rrect_mask((x0 + ins, y0 + ins, x1 - ins, y1 - ins), P["radius"] * k - ins), P["fill"] + (255,))
    ink = {"texts": [], "bars": []}

    def put(text, role, cap, x, cy, fill, right=False, max_w=300.0, tr=0.0, shear=0.0):
        if not text:
            return None
        f, _ = t2_font(role, text, fonts)
        m, _, _ = t2_fit_text(text, f, max_w * kx, cap * k, 0.0 if has_arabic(text) else tr, shear)
        px = int(round(x - (m.width if right else 0)))
        py = int(round(cy - (m.height / 2.0 if has_arabic(text) else cap * k / 2.0)))
        bb = t2_paint(lay, (m, (px, py)), fill)
        ink["texts"].append(bb)
        return bb

    # ---- left: EDITING LAYERS ----
    ic = t2_panel_icon("layers", P["icon"] * k * 0.9, t2["accent"])
    lay.alpha_composite(ic, (int(round(P["icon_cx"] * kx - ic.width / 2.0)), int(round(P["title_cy"] * ky - ic.height / 2.0))))
    lt = pn["layers_title"]
    put(lt if has_arabic(lt) else lt.upper(), "ui_bold", P["title_cap"], P["title_x"] * kx, P["title_cy"] * ky, (255, 255, 255, 255),
        max_w=P["div_x"] - P["title_x"] - 30, tr=0.0, shear=0.0 if has_arabic(lt) else 0.2)
    bars = []
    for i, r in enumerate(pn["rows"]):
        cy = g["row_cy"][i]
        put("%02d" % (i + 1), "ui", P["num_cap"], P["num_x"] * kx, cy, P["muted"] + (255,), max_w=34)
        lab_rtl = is_rtl_text(r["label"])
        put(r["label"], "ui", P["label_cap"], (P["label_r"] if lab_rtl else P["label_x"]) * kx, cy, (240, 242, 240, 255),
            right=lab_rtl, max_w=P["label_r"] - P["label_x"])
        if i < len(pn["rows"]) - 1:
            sy = cy + P["pitch"] * ky / 2.0
            t2_paint(lay, t2_rrect_mask((P["num_x"] * kx, sy - 0.5, P["track_x1"] * kx, sy + 0.5), 0.4), P["sep"] + (255,))
        row_boxes = []
        if r["bar"]:
            col = t2_rgb(r["color"]) + (255,)
            for a, b in (r["segs"] or [[r["start"], r["end"]]]):
                bx0, bx1 = g["tx0"] + a * (g["tx1"] - g["tx0"]), g["tx0"] + b * (g["tx1"] - g["tx0"])
                if bx1 - bx0 < 1.0:
                    continue
                bb = (bx0, cy - P["bar_h"] * ky / 2.0, bx1, cy + P["bar_h"] * ky / 2.0)
                t2_paint(lay, t2_rrect_mask(bb, P["bar_r"] * k), col)
                row_boxes.append(bb)
        bars.append(row_boxes)
    # ---- row 09: waveform (Part 4C) ----
    wave = None
    if pn.get("wave", True) and len(pn["rows"]) > 8 and not pn["rows"][8]["bar"]:
        wd = cfg.get("_t2_wave") or {"src": "procedural", "peaks": t2_wave_procedural()}
        pk = wd["peaks"]
        cyw, tw, hh = g["row_cy"][8], g["tx1"] - g["tx0"], P["bar_h"] * ky
        ss = T2_SS
        mw, mh = int(math.ceil(tw)) + 2, int(math.ceil(hh)) + 2
        lo, hi = Image.new("L", (mw * ss, mh * ss), 0), Image.new("L", (mw * ss, mh * ss), 0)
        dlo, dhi = ImageDraw.Draw(lo), ImageDraw.Draw(hi)
        pitch = tw / float(len(pk))
        bwid = max(1.0, pitch * 0.6)
        heights = []
        for i, pv in enumerate(pk):
            h_ = max(1.6, pv * hh)
            x_ = 1 + i * pitch
            (dhi if pv > 0.62 else dlo).rectangle((x_ * ss, (mh / 2.0 - h_ / 2.0) * ss, (x_ + bwid) * ss, (mh / 2.0 + h_ / 2.0) * ss), fill=255)
            heights.append(round(h_, 2))
        lo, hi = lo.resize((mw, mh), Image.BOX), hi.resize((mw, mh), Image.BOX)
        grey = (135, 136, 134)
        limegrey = tuple(int(grey[j] * 0.62 + acc[j] * 0.38) for j in range(3))
        wo = (int(round(g["tx0"] - 1)), int(round(cyw - mh / 2.0)))
        t2_paint(lay, (lo, wo), grey + (255,))
        t2_paint(lay, (hi, wo), limegrey + (255,))
        wave = {"src": wd["src"], "n": len(pk), "heights": heights, "origin": wo, "size": (mw, mh)}
    # ---- divider ----
    dx = P["div_x"] * kx
    t2_paint(lay, t2_rrect_mask((dx, P["div_y0"] * ky, dx + max(1.0, 1.4 * k), P["div_y1"] * ky), 0.6 * k), (95, 100, 98, 200))
    # ---- right: MOTION GUIDE ----
    ic = t2_panel_icon("bolt", P["icon"] * k * 0.9, t2["accent"])
    lay.alpha_composite(ic, (int(round(P["g_icon_cx"] * kx - ic.width / 2.0)), int(round(P["title_cy"] * ky - ic.height / 2.0))))
    gt = pn["guide_title"]
    put(gt if has_arabic(gt) else gt.upper(), "ui_bold", P["title_cap"], P["g_title_x"] * kx, P["title_cy"] * ky, (255, 255, 255, 255),
        max_w=P["g_right"] - P["g_title_x"], shear=0.0 if has_arabic(gt) else 0.2)
    circles = []
    for i, txt in enumerate(pn["guide"]):
        cy = (P["g_y0"] + i * P["g_pitch"]) * ky
        ccx, rr = P["g_circ_x"] * kx, P["circ_r"] * k
        t2_paint(lay, t2_rrect_mask((ccx - rr, cy - rr, ccx + rr, cy + rr), rr), acc + (255,))
        circles.append((ccx, cy))
        nf, _ = t2_font("ui_bold", str(i + 1), fonts)
        nm = t2_text_mask(str(i + 1), nf, t2_size_for_cap(nf, 9.6 * k))
        t2_paint(lay, (nm, (int(round(ccx - nm.width / 2.0)), int(round(cy - nm.height / 2.0)))), (12, 16, 8, 255))
        rtl = is_rtl_text(txt)
        put(txt, "ui", P["g_cap"], (P["g_right"] if rtl else P["g_text_x"]) * kx, cy, (240, 242, 240, 255), right=rtl,
            max_w=P["g_right"] - P["g_text_x"] - (0 if not rtl else 0))
    # ---- pagination dots: decorative (grey, grey, lime) baked into the plate when there are no chapters ----
    if pn.get("dots", True) and not t2_dot_plan(cfg)[1]:
        dspr, dpos = t2_dots_sprite(cfg, 3, 2)
        lay.alpha_composite(dspr, dpos)
    plate_box = (int(math.floor(x0)), int(math.floor(y0)), int(math.ceil(x1)), int(math.ceil(y1)))
    plate = lay.crop(plate_box)
    info = {"box": plate_box, "bars": bars, "track": (g["tx0"], g["tx1"]), "rows_cy": g["row_cy"], "ph_y": g["ph_y"],
            "circles": circles, "ink": ink, "wave": wave}
    return plate, (plate_box[0], plate_box[1]), info


# ---- ROADMAP panel (replaces EDITING LAYERS / MOTION GUIDE): one card per chapter, the current chapter is lit ----------------
T2_ROADMAP = {"x0": 25, "x1": 1055, "gap_below_about": 26, "bottom_margin": 82, "radius": 24, "pad": 24, "head_cy": 26,
              "bar_y": 50, "grid_top": 70, "gap": 14, "card_r": 16, "max_cards": 8,
              "outline": (84, 90, 72), "fill": (9, 11, 15), "card_fill": (14, 18, 21), "card_line": (42, 48, 50)}


def t2_roadmap_on(cfg):
    pn = t2_cfg(cfg.get("t2"))["panel"]
    return bool(pn["on"] and pn.get("style") == "roadmap")


def t2_roadmap_zone(cfg):
    """-> ((x0, y0, x1, y1) canvas px, k).  Starts under the about block (or the video window), ends above the bottom margin."""
    R = T2_ROADMAP
    W, H = (cfg.get("canvas") or [1080, 1920])[:2]
    k = W / 1080.0
    b = cfg.get("video_box") or T2_DEFAULT_BOX
    t2 = t2_cfg(cfg.get("t2"))
    if t2["about_on"]:
        g = t2_about_geometry(cfg, 3)
        y0 = g["oy"] + g["h"] + R["gap_below_about"] * k
    else:
        y0 = b["y"] + b["h"] + 36 * k
    y1 = H - R["bottom_margin"] * k
    return (R["x0"] * k, y0, R["x1"] * k, max(y0 + 120 * k, y1)), k


def _t2_rm_mix(a, b, f):
    return tuple(int(round(a[i] + (b[i] - a[i]) * f)) for i in range(3))


def t2_roadmap_sprite(cfg, chs, active):
    """RGBA sprite of the whole panel with chapter `active` lit, the earlier ones ticked, the later ones dimmed."""
    t2 = t2_cfg(cfg.get("t2"))
    pn, fonts, R = t2["panel"], t2.get("fonts"), T2_ROADMAP
    acc = t2_rgb(t2["accent"])
    (x0, y0, x1, y1), k = t2_roadmap_zone(cfg)
    w, h = int(round(x1 - x0)), int(round(y1 - y0))
    n = len(chs)
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    t2_paint(lay, t2_rrect_mask((0, 0, w, h), R["radius"] * k), R["outline"] + (255,))
    ins = 1.6 * k
    t2_paint(lay, t2_rrect_mask((ins, ins, w - ins, h - ins), R["radius"] * k - ins), R["fill"] + (255,))
    pad = R["pad"] * k

    def text(txt, role, cap, x, cy, fill, right=False, max_w=400.0, tr=0.0, shear=0.0, top=None):
        if not txt:
            return None
        f, _ = t2_font(role, txt, fonts)
        m, _, _ = t2_fit_text(txt, f, max_w, cap, 0.0 if has_arabic(txt) else tr, shear)
        px = int(round(x - (m.width if right else 0)))
        py = int(round(top if top is not None else cy - m.height / 2.0))
        t2_paint(lay, (m, (px, py)), fill)
        return m

    # header: lime square + title (left), "03 / 06" (right), thin progress bar
    cy = R["head_cy"] * k
    sq = 13 * k
    t2_paint(lay, t2_rrect_mask((pad, cy - sq / 2, pad + sq, cy + sq / 2), 2 * k), acc + (255,))
    ttl = pn.get("title") or ""
    text(ttl if has_arabic(ttl) else ttl.upper(), "ui_bold", 15 * k, pad + sq + 14 * k, cy, (200, 204, 202, 255),
         max_w=w * 0.6, tr=0.30)
    text("%02d / %02d" % (active + 1, n), "ui_bold", 17 * k, w - pad, cy, acc + (255,), right=True, max_w=200 * k, tr=0.12)
    by, bh = R["bar_y"] * k, 3.2 * k
    t2_paint(lay, t2_rrect_mask((pad, by, w - pad, by + bh), bh / 2), (38, 43, 44, 255))
    t2_paint(lay, t2_rrect_mask((pad, by, pad + (w - 2 * pad) * (active + 1) / float(n), by + bh), bh / 2), acc + (255,))

    # cards
    cols = 3 if n <= 6 else 4
    rows = int(math.ceil(n / float(cols)))
    gap = R["gap"] * k
    top, bottom = R["grid_top"] * k, h - pad
    cw = (w - 2 * pad - gap * (cols - 1)) / float(cols)
    chh = (bottom - top - gap * (rows - 1)) / float(rows)
    dark = R["card_fill"]
    for i, c in enumerate(chs):
        r_, c_ = divmod(i, cols)
        cx0, cy0 = pad + c_ * (cw + gap), top + r_ * (chh + gap)
        box = (cx0, cy0, cx0 + cw, cy0 + chh)
        rad = R["card_r"] * k
        state = "now" if i == active else ("done" if i < active else "todo")
        if state == "now":
            t2_paint(lay, t2_glow(t2_rrect_mask(box, rad), 9 * k, 0.9), acc + (120,))
            t2_paint(lay, t2_rrect_mask(box, rad), acc + (255,))
            li = 2.4 * k
            t2_paint(lay, t2_rrect_mask((box[0] + li, box[1] + li, box[2] - li, box[3] - li), rad - li),
                     _t2_rm_mix(dark, acc, 0.13) + (255,))
        else:
            line = _t2_rm_mix(R["card_line"], acc, 0.30) if state == "done" else R["card_line"]
            t2_paint(lay, t2_rrect_mask(box, rad), line + (255,))
            li = 1.4 * k
            t2_paint(lay, t2_rrect_mask((box[0] + li, box[1] + li, box[2] - li, box[3] - li), rad - li), dark + (255,))
        ncol = acc if state == "now" else (_t2_rm_mix(acc, dark, 0.50) if state == "done" else (84, 90, 90))
        lcol = (255, 255, 255) if state == "now" else ((206, 210, 208) if state == "done" else (118, 123, 122))
        hf, hsh = t2_font("headline", "00", fonts)
        nm = t2_text_mask("%02d" % (i + 1), hf, t2_size_for_cap(hf, 36 * k), 0.0, 0.2 if hsh else 0.0)
        t2_paint(lay, (nm, (int(round(cx0 + 18 * k)), int(round(cy0 + 16 * k)))), ncol + (255,))
        lab = str(c.get("label") or "")
        lab = lab if has_arabic(lab) else lab.upper()
        text(lab, "ui_bold", 16 * k, cx0 + 18 * k, 0, lcol + (255,), max_w=cw - 36 * k, tr=0.08,
             top=cy0 + chh - 18 * k - 16 * k)
        # status badge, top-right
        bx, by_ = cx0 + cw - 18 * k, cy0 + 16 * k
        if state == "done":
            rr = 12 * k
            ccx, ccy = bx - rr, by_ + rr
            t2_paint(lay, t2_rrect_mask((ccx - rr, ccy - rr, ccx + rr, ccy + rr), rr), acc + (255,))

            def tick(d, L, ss, ccx=ccx, ccy=ccy):
                d.line([L(ccx - 5.5 * k, ccy + 0.5 * k), L(ccx - 1.5 * k, ccy + 4.5 * k), L(ccx + 5.5 * k, ccy - 4 * k)],
                       fill=255, width=max(2, int(2.6 * k * ss)), joint="curve")
            t2_paint(lay, t2_draw_mask((ccx - 14 * k, ccy - 14 * k, ccx + 14 * k, ccy + 14 * k), tick), (12, 16, 8, 255))
        elif state == "now":
            lbl = (pn.get("now_label") or "NOW").upper()
            f, _ = t2_font("ui_bold", lbl, fonts)
            tm = t2_text_mask(lbl, f, t2_size_for_cap(f, 11.5 * k), 0.16)
            pw, ph_ = tm.width + 34 * k, 26 * k
            px0, py0 = bx - pw, by_
            t2_paint(lay, t2_rrect_mask((px0, py0, bx, py0 + ph_), ph_ / 2), acc + (255,))
            dr = 3.4 * k
            t2_paint(lay, t2_rrect_mask((px0 + 11 * k, py0 + ph_ / 2 - dr, px0 + 11 * k + 2 * dr, py0 + ph_ / 2 + dr), dr),
                     (12, 16, 8, 255))
            t2_paint(lay, (tm, (int(round(px0 + 11 * k + 2 * dr + 6 * k)), int(round(py0 + ph_ / 2 - tm.height / 2.0)))),
                     (12, 16, 8, 255))
        else:
            rr = 11 * k
            ccx, ccy = bx - rr, by_ + 12 * k
            t2_paint(lay, t2_rrect_mask((ccx - rr, ccy - rr, ccx + rr, ccy + rr), rr), (52, 58, 58, 255))
            t2_paint(lay, t2_rrect_mask((ccx - rr + 1.8 * k, ccy - rr + 1.8 * k, ccx + rr - 1.8 * k, ccy + rr - 1.8 * k),
                                        rr - 1.8 * k), dark + (255,))
    return lay, (int(round(x0)), int(round(y0)))


def t2_roadmap_items(cfg, duration):
    """One full-panel sprite per chapter.  A later state is drawn over the previous one (which stays 0.4 s longer), so only the
    lit card changes; the first state fades in, the last visible state fades out (at panel.end, else at the video end)."""
    if not t2_roadmap_on(cfg):
        return []
    pn = t2_cfg(cfg.get("t2"))["panel"]
    chs = [c for c in t2_resolve_chapters(cfg, duration) if c["start"] < duration][:T2_ROADMAP["max_cards"]]
    if not chs:
        return []
    t_end = pn.get("end")
    t_end = float(t_end) if t_end else duration + 1
    ov, items = 0.4, []
    vis = [(i, 0.0 if i == 0 else c["start"]) for i, c in enumerate(chs)]
    vis = [(i, s0) for i, s0 in vis if s0 < t_end - 0.2]
    for j, (i, s0) in enumerate(vis):
        spr, (x, y) = t2_roadmap_sprite(cfg, chs, i)
        last = j == len(vis) - 1
        e0 = t_end if last else min(t_end, vis[j + 1][1] + ov)
        if last:
            items.append(Item(spr, s0, e0, x + spr.width / 2.0, y + spr.height / 2.0,
                              "fade", ov, out=True))
        else:
            items.append(Item(spr, s0, e0, x + spr.width / 2.0, y + spr.height / 2.0,
                              "fade" if j == 0 else "none", ov, out=False))
    return items


def t2_panel_bake(cfg, fg_path, tmp):
    """Composite the panel onto the foreground plate and write the playhead sprite.  Sets / clears cfg['_t2_playhead']."""
    cfg["_t2_playhead"] = None
    res = t2_panel_plate(cfg)
    if not res:
        return None
    plate, org, info = res
    fg = Image.open(fg_path).convert("RGBA")
    fg.alpha_composite(plate, org)
    fg.save(fg_path, compress_level=1)
    spr = t2_panel_playhead_sprite(cfg)
    p = os.path.join(tmp, "t2_playhead.png")
    spr.save(p)
    cfg["_t2_playhead"] = {"path": p, "cx0": info["track"][0], "cx1": info["track"][1], "y": int(round(info["ph_y"])),
                           "w": spr.width, "h": spr.height}
    return info


def t2_ask_split():
    """Split-screen questions -> {"split": {...}} for cfg['t2'].  Asked only when an element / box video layer exists."""
    if not yn("\nSplit screen: while an element (PNG) or a video layer is shown, move the video to the left and show the "
              "element on the right, in two lime-framed boxes?", default=D.get("t2_split_ask", "n") == "y"):
        D["t2_split_ask"] = "n"
        return {"split": {"on": False}}
    D["t2_split_ask"] = "y"
    left = ask("Video box width (% of the split area, Enter = 50)", default=50, key="t2_split_left", cast=c_percent)
    return {"split": {"on": True, "left_pct": left}}


def t2_ask_panel(on=None):
    """Bottom info panel questions -> {"panel": {...}} for cfg['t2'].  Default yes (as in the poster)."""
    if on is None:
        on = yn("\nShow the bottom info panel (EDITING LAYERS timeline + MOTION GUIDE)? It uses about 18% of the screen",
                default=D.get("t2_panel_ask", "y") == "y")
        D["t2_panel_ask"] = "y" if on else "n"
    if not on:
        return {"panel": {"on": False}}
    D["t2_panel_ask"] = "y"
    if yn("Use the poster texts (Editing layers 01-09 / Motion guide 1-6)?", default=D.get("t2_panel_poster", "y") == "y"):
        D["t2_panel_poster"] = "y"
        return {"panel": {"on": True}}
    D["t2_panel_poster"] = "n"
    print("   (Enter = keep the poster text, '-' = empty; bar start/end/colors can be edited in the job json: t2.panel.rows)")
    rows = []
    for i, r in enumerate(T2_PANEL_ROWS):
        v = ask(f"   layer {i + 1:02d} label", default=r[0], key=f"t2_panel_row{i + 1}", cast=_c_t2_text, allow_empty=True)
        rows.append({"label": v or ""})
    guide = []
    for i, s in enumerate(T2_PANEL_GUIDE):
        v = ask(f"   motion guide {i + 1} text (empty = skip)", default=s, key=f"t2_panel_guide{i + 1}", cast=_c_t2_text, allow_empty=True)
        if v:
            guide.append(v)
    return {"panel": {"on": True, "rows": rows, "guide": guide}}


def _hdr(n, title):
    print("\n=== %s. %s %s" % (n, title, "=" * max(4, 56 - len(title))))


def _t2_ask_on(key, question, default):
    v = yn(question, default=D.get(key, "y" if default else "n") == "y")
    D[key] = "y" if v else "n"
    return v


def _interactive_t2(cfg, tpl_entry):
    """Template 2 question flow, grouped under headers:
    video -> SRT(s) -> identity/header/headline -> frame -> panels on/off -> captions -> chapters -> floating cards ->
    about states -> texts/elements/layers/video layers -> split -> output -> preview.  Every question has a default."""
    _PRESET["sel"] = True
    box = {}

    def _c_video(s):
        p = c_existing_file(VIDEO_EXTS)(s)
        box["info"] = probe(p)                              # unreadable file -> ValueError -> asked again
        if box["info"]["duration"] <= 0:
            raise ValueError("this video has no readable duration")
        return p
    _hdr(1, "Video")
    cfg["video"] = ask("Video path", cast=_c_video)
    info = box["info"]
    print(f"   -> {info['w']}x{info['h']}, {float(info['fps']):.2f} fps, {info['duration']:.1f} s"
          f"{'' if info['audio'] else ', no audio'}")
    if info["duration"] < 3:
        print(f"   [i] very short video ({info['duration']:.1f} s): anything timed after the end is simply not shown.")
    if abs(info["w"] / float(info["h"]) - 9 / 16.0) > 0.02:
        print("   [i] not 9:16 - the video is fitted into the window ('fit' = whole video, 'fill' = cropped); it is never stretched.")

    _hdr(2, "Captions file (SRT)")
    srt_paths = []
    nxt = ask("SRT captions file path (Enter = no captions)", cast=c_existing_file((".srt",)), allow_empty=True)
    while nxt:
        cues = parse_srt(nxt)
        if not cues:
            print("   [!] No captions could be read from that SRT file - skipped.")
        else:
            print(f"   -> {len(cues)} caption blocks read.")
            srt_paths.append(nxt)
        nxt = ask("Another SRT (for example the English translation)? Path, or Enter = no",
                  cast=c_existing_file((".srt",)), allow_empty=True)
    cues0 = parse_srt(srt_paths[0]) if srt_paths else []

    tpl = tpl_entry["ask_config"](info)                       # headers 3 + 4 live inside
    cfg.update({k: tpl[k] for k in ("canvas", "video_box", "background")})
    cfg["layers"] = tpl.get("layers", [])
    t2 = dict(tpl.get("t2") or {})

    _hdr(5, "Panels on/off")
    about_on = _t2_ask_on("t2_about_ask", "Show the ABOUT ME + features block under the video window?", True)
    panel_on = _t2_ask_on("t2_panel_ask", "Show the bottom info panel (EDITING LAYERS + MOTION GUIDE, ~18% of the screen)?", True)
    t2.update(t2_ask_panel(on=panel_on))

    _hdr(6, "Captions")
    if srt_paths:
        cfg["captions"] = [tpl_entry["caption_style"](i, p) for i, p in enumerate(srt_paths)]
    else:
        cfg["captions"] = []
        print("   (no SRT given - no captions)")

    _hdr(7, "Chapter tags")
    t2.update(t2_ask_chapters(cues0, info["duration"]))
    _hdr(8, "Floating cards")
    cfg["cards"] = []
    t2.update(t2_ask_cards_cfg(cues0))
    _hdr(9, "ABOUT ME states")
    t2.update(t2_ask_about(cues0, info["duration"], on=about_on))

    _hdr(10, "Texts, elements, template layers and video layers")
    cfg["texts"] = ask_texts(info["duration"])
    cfg["elements"] = ask_elements(info["duration"])
    if not cfg["layers"]:
        cfg["layers"] = ask_layers(*cfg["canvas"])
    cfg["video_layers"] = ask_video_layers(info["duration"])
    t2 = t2_cfg(t2)
    if cfg["elements"] or any(v.get("area", "box") == "box" for v in cfg["video_layers"]):
        _hdr(11, "Split screen")
        t2.update(t2_ask_split())
        t2 = t2_cfg(t2)
    cfg["t2"] = t2

    _hdr(12, "Output")
    stem = Path(cfg["video"]).with_suffix("")
    cfg["output"] = ask("Output file", default=str(stem) + "_edited.mp4",
                        cast=lambda s: clean_path(s if s.lower().endswith(".mp4") else s + ".mp4"))
    cfg["preview"] = ask("Quick test: render only the first N seconds (Enter = full video)",
                         allow_empty=True, cast=c_float)
    return cfg
