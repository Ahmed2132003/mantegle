"""mt.templates.t4.nameplate - Template 4 module 'nameplate', style 'lower_third' (ref R1): a name card + a tagline bar.
NOT baked into the foreground plate: both are timeline Items (t4_build_items), timed by t4_time / t4_ask_when and animated with the
shared anim presets (default slide_left, in AND out). Everything is text-driven (cfg['t4']['nameplate']):
  name1 (white) name2 (cyan) | roles = up to 3 x {icon, text} | badge_icon | tagline + tagline_highlight (yellow word(s), 'a, b' list ok)
  color (neon) name_color hl_color font | anim anim_dur | start / trigger (spoken phrase) / hold / end  (see timing.t4_time)
Card = chamfered dark panel + neon border, hexagon icon badge, two-tone name + thin underline, icon + role rows, yellow hazard stripes
top-right and blue ones bottom-right. Bar = full-width dark glass band with a bevelled left end, neon line across the width and
tracked italic caps text (one highlighted word). Authored in px at short side 1080 (scaled); text stays inside the 48 px safe margin.
Canvas rule: youtube = card at the bottom-right, bar at the bottom-left (as R1); reels (narrow) = the card stacked above the bar.
Text that is too wide shrinks first, then the tagline wraps to 2 lines - nothing overflows. Arabic / RTL: shaped, untracked, upright.
Public: T4_NAMEPLATE, t4_nameplate_cfg(raw), t4_ask_nameplate(), t4_nameplate_sprite(...), t4_tagline_sprite(...), t4_nameplate_items(cfg, duration)."""
import os

from PIL import Image, ImageDraw

from mt.anim import ANIMS
from mt.ask import ask_anim
from mt.captions import caption_streams, parse_srt, visual_order
from mt.common import ask, ask_choice, c_color, c_float, yn
from mt.draw import Item, t2_glow, t2_grad, t2_paint, t2_poly_mask, t2_rgb
from mt.fonts import default_font, is_rtl_text, load_font, shape
from mt.templates.t4.captions import _is_bold, _ramp_alpha, t4_tokens
from mt.templates.t4.cfg import _hex
from mt.templates.t4.kit import PALETTE, connector, glass_panel, hazard_stripes, hex_badge, icon, kit_paste
from mt.templates.t4.kit_icons import ICON_NAMES
from mt.templates.t4.timing import t4_ask_when, t4_time
from mt.templates.t4.warn import t4_warn

_DEF_ROLES = ({"icon": "laptop", "text": "WEB DEVELOPER"}, {"icon": "phone", "text": "MOBILE DEVELOPER"},
              {"icon": "gear", "text": "AI AUTOMATION"})
T4_NAMEPLATE = {"on": False, "style": "lower_third", "name1": "AHMED", "name2": "IBRAHIM", "roles": [dict(r) for r in _DEF_ROLES],
                "badge_icon": "code", "tagline": "BUILDING DIGITAL EXPERIENCES.", "tagline_highlight": "DIGITAL",
                "color": "#19D3FF", "name_color": "#FFFFFF", "hl_color": "#FFC21A", "anim": "slide_left", "anim_dur": 0.5}
# timing keys (start / trigger / hold / end) are not defaults here: they pass through untouched to timing.t4_time (hold default 6 s)
# layout in px at short side 1080 (the R1 card is ~637 x 295 there)
G = {"text_x": 205, "pad_r": 40, "min_col": 330, "hex": 140, "hex_cy": 96, "name_size": 48, "name_track": 0.02, "name_cy": 62,
     "ul_y": 98, "role_size": 27, "role_track": 0.06, "icon": 38, "icon_gap": 63, "row_y0": 133, "pitch": 52, "bot": 58,
     "cut": (74, 26, 74, 26), "bw": 2.6, "glow": 12, "tint": (6, 16, 40, 205), "stripes_h": 16, "stripes_w": 86,
     "tag_size": 36, "tag_track": 0.20, "slant": 0.22, "band_h": 124, "bev": 155, "tag_x": 184, "line_y": 56,
     "gap": 46, "gap_stack": 40, "safe": 48, "pad": 40, "tag_gap": 36}
_CACHE = {}


# ---- config -----------------------------------------------------------------------------------------------------------------
def _txt(v, default, n):
    return v.strip()[:n] if isinstance(v, str) else default


def _roles(raw):
    out = []
    for i, r in enumerate(raw if isinstance(raw, (list, tuple)) else []):
        if isinstance(r, str):
            r = {"text": r}
        elif isinstance(r, (list, tuple)) and len(r) == 2:
            r = {"icon": r[0], "text": r[1]}
        if not isinstance(r, dict):
            continue
        t = _txt(r.get("text"), "", 60)
        ic = r.get("icon")
        out.append({"icon": ic.strip().lower() if isinstance(ic, str) else _DEF_ROLES[min(i, 2)]["icon"], "text": t})
    return out[:3]


def t4_nameplate_cfg(raw):
    """Normalise cfg['t4']['nameplate'] -> complete dict. Never raises; junk -> defaults; extra keys (timing, font ...) survive.
    No start / trigger -> start 0. Empty texts are allowed (the matching part is simply not drawn)."""
    out = dict(T4_NAMEPLATE, roles=[dict(r) for r in _DEF_ROLES])
    if not isinstance(raw, dict):
        return out
    try:
        out.update({k: v for k, v in raw.items() if k not in out})
        out["on"] = bool(raw.get("on", False))
        for k, n in (("name1", 40), ("name2", 40), ("tagline", 120), ("tagline_highlight", 80)):
            out[k] = _txt(raw.get(k), out[k], n)
        if isinstance(raw.get("roles"), (list, tuple)):
            out["roles"] = _roles(raw["roles"])
        ic = raw.get("badge_icon")
        out["badge_icon"] = "" if (ic is False or (isinstance(ic, str) and ic.strip().lower() in ("", "none", "-"))) \
            else (ic.strip().lower() if isinstance(ic, str) else out["badge_icon"])
        for k in ("color", "name_color", "hl_color"):
            out[k] = _hex(raw.get(k), T4_NAMEPLATE[k])
        a = raw.get("anim")
        out["anim"] = a.strip().lower() if isinstance(a, str) and a.strip().lower() in tuple(ANIMS) + ("none",) else "slide_left"
        try:
            d = float(raw.get("anim_dur", out["anim_dur"]))
            out["anim_dur"] = d if 0.0 <= d <= 5.0 else 0.5
        except (TypeError, ValueError, OverflowError):
            out["anim_dur"] = 0.5
        if "start" not in raw and not str(raw.get("trigger") or "").strip():
            out["start"] = 0
    except Exception:
        return dict(T4_NAMEPLATE, roles=[dict(r) for r in _DEF_ROLES])
    return out


def t4_ask_nameplate():
    """Question group 'nameplate' (called by t4_ask_config). -> the nameplate dict for cfg['t4']['nameplate']."""
    if not yn("Add the lower-third nameplate (name card + tagline bar)?", default=False):
        return {"on": False}
    d = T4_NAMEPLATE
    dash = lambda s: "" if s.strip() in ("-", "none") else s.strip()                    # noqa: E731
    out = {"on": True, "style": "lower_third",
           "name1": ask("Name - first word (white)", default=d["name1"], key="t4_np_n1", cast=dash),
           "name2": ask("Name - second word (cyan, '-' = none)", default=d["name2"], key="t4_np_n2", cast=dash), "roles": []}
    for i, r in enumerate(_DEF_ROLES):
        t = ask(f"Role {i + 1} text ('-' = no row)", default=r["text"], key=f"t4_np_r{i}", cast=dash)
        if t:
            ic = ask_choice(f"Role {i + 1} icon:", list(ICON_NAMES), default=ICON_NAMES.index(r["icon"]) + 1, key=f"t4_np_i{i}")
            out["roles"].append({"icon": ICON_NAMES[ic - 1], "text": t})
    bi = ask_choice("Hexagon badge icon:", list(ICON_NAMES), default=ICON_NAMES.index(d["badge_icon"]) + 1, key="t4_np_badge")
    out["badge_icon"] = ICON_NAMES[bi - 1]
    out["tagline"] = ask("Tagline bar text ('-' = no bar)", default=d["tagline"], key="t4_np_tag", cast=dash)
    if out["tagline"]:
        out["tagline_highlight"] = ask("Highlighted word(s) in the tagline (yellow, '-' = none)", default=d["tagline_highlight"],
                                       key="t4_np_hl", cast=dash)
    out["color"] = ask("Neon colour (hex or name)", default=d["color"], key="t4_np_color", cast=c_color)
    out.update(t4_ask_when("Nameplate", 6.0, key="t4_np_when"))
    out["anim"] = ask_anim("Animation (used in and out)", default="slide_left", key="t4_np_anim")
    out["anim_dur"] = ask("Animation seconds", default=0.5, key="t4_np_adur", cast=c_float)
    return out


# ---- text helpers -----------------------------------------------------------------------------------------------------------
def _w(s, f, tp, rtl):
    """Width of a run: whole-string advance (RTL / untracked) or per-character advance + tracking after each character."""
    return f.getlength(s) if (rtl or tp <= 0) else sum(f.getlength(c) for c in s) + tp * len(s)


def _fit_size(texts, fp, size, track, avail, extra=0.0, floor=0.55):
    """Largest size <= `size` (never below floor x size) at which every text (+ `extra` px) fits `avail`. Shrinks, never wraps."""
    sz, lo = float(size), max(10.0, float(size) * floor)
    while sz > lo:
        f = load_font(fp, max(8, int(round(sz))))
        if all(extra + _w(shape(t) if is_rtl_text(t) else t, f, 0 if is_rtl_text(t) else track * sz, is_rtl_text(t)) <= avail
               for t in texts):
            break
        sz *= 0.95
    return max(lo, sz)


def _put(d, x, yb, s, f, tp, rtl, sw):
    """Draw one run (tracked per character for LTR) on an L mask, return the x after it."""
    if rtl or tp <= 0:
        d.text((x, yb), s, font=f, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
        return x + f.getlength(s)
    for ch in s:
        d.text((x, yb), ch, font=f, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
        x += f.getlength(ch) + tp
    return x


def _cap(f):
    return -f.getbbox("H", anchor="ls")[1]


def _icon_ok(name):
    if name and name not in ICON_NAMES:
        t4_warn(f"nameplate icon '{name}' unknown (use one of: {', '.join(ICON_NAMES)}) - no icon")
        return ""
    return name


def _paint(spr, mask, col, glow=0.0, ga=0.0):
    if glow > 0:
        t2_paint(spr, t2_glow((mask, (0, 0)), glow, 1.2), col, ga)
    t2_paint(spr, (mask, (0, 0)), col)


# ---- card -------------------------------------------------------------------------------------------------------------------
def _draw_name(spr, size, fp, s, names, rtl, x0, col_w, yb, bold, cols):
    f = load_font(fp, max(8, int(round(size))))
    tp = 0 if rtl else G["name_track"] * size
    sw = 0 if bold else max(1, int(round(size * 0.03)))
    runs = [(shape(t) if rtl else t, k) for t, k in names]
    runs = runs[::-1] if rtl else runs
    sp = f.getlength(" ") + tp
    x = x0 + (col_w - (sum(_w(t, f, tp, rtl) for t, _ in runs) + sp * (len(runs) - 1)) if rtl else 0)
    for t, k in runs:
        m = Image.new("L", spr.size, 0)
        x = _put(ImageDraw.Draw(m), x, yb, t, f, tp, rtl, sw) + sp
        _paint(spr, m, cols[k], 4 * s if k == 1 else 0, 0.35)
    return _cap(f)


def _draw_rows(spr, rows, fp, s, size, x0, col_w, y0, rtl_ui, col, bold):
    """Icon + role text per row (white text, neon-coloured icon); RTL rows: icon at the right end, text right-aligned."""
    f = load_font(fp, max(8, int(round(size))))
    tp0, isz, gap = G["role_track"] * size, int(G["icon"] * s), G["icon_gap"] * s
    sw = 0 if bold else max(1, int(round(size * 0.03)))
    m = Image.new("L", spr.size, 0)
    d = ImageDraw.Draw(m)
    for i, (ic, text) in enumerate(rows):
        cy, rtl = y0 + i * G["pitch"] * s, is_rtl_text(text)
        t, tp = (shape(text) if rtl else text), (0 if rtl else tp0)
        yb = cy + _cap(f) / 2.0
        tw = _w(t, f, tp, rtl)
        _put(d, (x0 + col_w - gap - tw) if rtl else (x0 + gap), yb, t, f, tp, rtl, sw)
        if ic:
            kit_paste(spr, icon(ic, isz, col), (x0 + col_w - isz) if rtl else x0, cy - isz / 2.0)
    t2_paint(spr, (m, (0, 0)), (255, 255, 255))


def t4_nameplate_sprite(np_, fp, s, max_w):
    """The card as an RGBA sprite (glow margin included) or None when it has no name and no rows. max_w = widest allowed PANEL (px).
    sprite.info: panel = (x, y, w, h) of the chamfered panel inside the sprite."""
    names = [(t, k) for k, t in ((0, np_["name1"]), (1, np_["name2"])) if t]
    names = [(t.upper(), k) for t, k in names]
    rows = [(_icon_ok(r["icon"]), r["text"].upper()) for r in np_["roles"] if r.get("text")]
    if not names and not rows:
        return None
    col, bold, badge = np_["color"], _is_bold(fp), _icon_ok(np_["badge_icon"])
    tx, pr = G["text_x"] * s, G["pad_r"] * s
    avail = max(60.0, max_w - tx - pr)
    full = " ".join(t for t, _ in names)
    nsz = _fit_size([full], fp, G["name_size"] * s, G["name_track"], avail) if names else G["name_size"] * s
    rsz = _fit_size([t for _, t in rows], fp, G["role_size"] * s, G["role_track"], avail, G["icon_gap"] * s) if rows else G["role_size"] * s
    nf, rf = load_font(fp, max(8, int(round(nsz)))), load_font(fp, max(8, int(round(rsz))))
    rtl_n = is_rtl_text(full)
    nw = _w(shape(full) if rtl_n else full, nf, 0 if rtl_n else G["name_track"] * nsz, rtl_n) if names else 0
    rw = max([G["icon_gap"] * s + _w(shape(t) if is_rtl_text(t) else t, rf, 0 if is_rtl_text(t) else G["role_track"] * rsz,
                                     is_rtl_text(t)) for _, t in rows] or [0])
    cw = max(G["min_col"] * s, nw, rw)
    pw = int(tx + cw + pr)
    ph = int((G["row_y0"] + G["pitch"] * (len(rows) - 1) + G["bot"] if rows else G["ul_y"] + 44) * s)
    pad, top = int(G["pad"] * s), int(G["stripes_h"] * s * 1.6)
    spr = Image.new("RGBA", (pw + 2 * pad, ph + 2 * pad + top + int((G["gap"] + 14) * s)), (0, 0, 0, 0))
    px, py = pad, pad + top
    kit_paste(spr, glass_panel((pw, ph), 0, G["tint"], t2_rgb(col), tuple(c * s for c in G["cut"]), G["bw"] * s, G["glow"] * s), px, py)
    hs = G["hex"] * s
    hcy = min(G["hex_cy"] * s, ph - hs * 0.433 - 8 * s)                      # hexagon centre: R1 position, kept inside short cards
    kit_paste(spr, hex_badge(hs, badge, t2_rgb(col), G["glow"] * 0.8 * s), px + 94 * s - hs / 2.0, py + hcy - hs * 0.433)
    if names:
        _draw_name(spr, nsz, fp, s, names, rtl_n, px + tx, cw, py + G["name_cy"] * s + _cap(nf) / 2.0, bold,
                         [t2_rgb(np_["name_color"]), t2_rgb(col)])
        yu = py + G["ul_y"] * s
        kit_paste(spr, connector([(px + tx, yu), (px + tx + cw, yu)], t2_rgb(col), False, max(1.6, 1.8 * s), 6 * s), 0, 0)
    if rows:
        _draw_rows(spr, rows, fp, s, rsz, px + tx, cw, py + G["row_y0"] * s, False, t2_rgb(col), bold)
    sw_, sh_ = G["stripes_w"] * s, G["stripes_h"] * s
    kit_paste(spr, hazard_stripes((sw_, sh_), 30, PALETTE["yellow"], 6 * s), px + pw - 22 * s - sw_, py - sh_ - 3 * s)
    spr.info["panel"] = (px, py, pw, ph)
    return spr


def _stripes_below(spr, col, drop, s):
    """The blue stripes at the card's bottom-right corner, `drop` px under the panel bottom (drawn after the placement is known)."""
    px, py, pw, ph = spr.info["panel"]
    sw_, sh_ = G["stripes_w"] * s, G["stripes_h"] * s
    kit_paste(spr, hazard_stripes((sw_, sh_), 30, PALETTE["blue"], 6 * s), px + pw - 22 * s - sw_ - 6 * s, py + ph + drop - sh_ / 2.0)
    return spr


# ---- tagline bar ------------------------------------------------------------------------------------------------------------
def _tag_lines(tokens, fp, size, track, avail, rtl):
    f = load_font(fp, max(8, int(round(size))))
    tp = 0 if rtl else track * size
    sp = f.getlength(" ") + tp
    ww = [_w(shape(t) if rtl else t, f, tp, rtl) for t, _ in tokens]
    lines, cur, cw = [], [], 0.0
    for i, w in enumerate(ww):
        add = w if not cur else sp + w
        if cur and cw + add > avail:
            lines.append(cur)
            cur, cw = [i], w
        else:
            cur.append(i)
            cw += add
    lines.append(cur)
    lw = [sum(ww[i] for i in ln) + sp * (len(ln) - 1) for ln in lines]
    return {"f": f, "tp": tp, "sp": sp, "ww": ww, "lines": lines, "lw": lw, "size": size, "rtl": rtl}


def _tag_layout(tokens, fp, size, track, avail):
    """One line at a smaller size first; when even that is too wide -> 2 lines (shrinking further if needed)."""
    rtl = is_rtl_text(" ".join(t for t, _ in tokens))
    for k in (1.0, 0.93, 0.86, 0.79, 0.72):
        lay = _tag_lines(tokens, fp, size * k, track, avail, rtl)
        if len(lay["lines"]) == 1:
            return lay
    for k in (0.86, 0.78, 0.70, 0.62, 0.55):
        lay = _tag_lines(tokens, fp, size * k, track, avail, rtl)
        if len(lay["lines"]) <= 2:
            break
    return lay


def _shear(mask, k, yb):
    """Italic lean: points above the baseline yb move right by k x height (affine, bicubic)."""
    return mask.transform(mask.size, Image.AFFINE, (1, k, -k * yb, 0, 1, 0), Image.BICUBIC)


def _band(spr, W, yt, yb, bev, s, col):
    """Dark glass band (alpha fades to the right) + bevelled left end, neon line across the width, thin second line."""
    mask = t2_poly_mask([(0, yt), (W, yt), (W, yb), (bev, yb)])
    t2_paint(spr, mask, t2_grad([(0, (8, 20, 48, 214)), (0.45, (6, 16, 40, 150)), (1, (6, 16, 40, 0))], 0, (0, 0, W, 1)))
    c, thick = t2_rgb(col), max(2.4, 3.2 * s)
    kit_paste(spr, connector([(0, yt), (bev, yb), (W + 4, yb)], c, False, thick, 14 * s), 0, 0)
    x0, x1 = 44 * s, W * 0.68
    thin = connector([(x0, yt + 1), (x1, yt + 1)], c, False, max(1.4, 1.6 * s), 5 * s)
    kit_paste(spr, _ramp_alpha(thin, x0, x1), 0, 0)


def t4_tagline_sprite(np_, fp, s, W, right_limit=None):
    """The full-width tagline bar (W px wide) or None. right_limit = x where the text must stop (the card on a wide canvas).
    sprite.info: line_y (local y of the neon line), top (local y of the band top), band_h."""
    tokens = t4_tokens(np_["tagline"].upper(), np_["tagline_highlight"].upper()) if np_["tagline"] else []
    if not tokens:
        return None
    x0 = G["tag_x"] * s
    lim = min(float(right_limit if right_limit else W - G["safe"] * s), W - G["safe"] * s)
    lay = _tag_layout(tokens, fp, G["tag_size"] * s, G["tag_track"], max(80.0, lim - x0))
    n, size, f = len(lay["lines"]), lay["size"], lay["f"]
    pitch = size * 1.42
    bh = max(G["band_h"] * s, n * pitch + 52 * s)
    pad = int(G["pad"] * s)
    yt, yb = pad, pad + bh
    spr = Image.new("RGBA", (int(W), int(yb + pad)), (0, 0, 0, 0))
    _band(spr, W, yt, yb, min(G["bev"] * s, W * 0.25), s, np_["color"])
    white, hl = Image.new("L", spr.size, 0), Image.new("L", spr.size, 0)
    sw, bold = (0 if _is_bold(fp) else max(1, int(round(size * 0.03)))), _is_bold(fp)
    cy0 = (yt + yb) / 2.0 - (n - 1) * pitch / 2.0
    for li, ln in enumerate(lay["lines"]):
        items = [(tokens[i][0], tokens[i][1], lay["ww"][i], f) for i in ln]
        x, yline = x0, cy0 + li * pitch + _cap(f) / 2.0
        for t, h, w, _ in visual_order(items, lay["rtl"]):
            _put(ImageDraw.Draw(hl if h else white), x, yline, shape(t) if lay["rtl"] else t, f, lay["tp"], lay["rtl"], sw)
            x += w + lay["sp"]
    k = 0 if lay["rtl"] else G["slant"]
    for m, c in ((white, (255, 255, 255)), (hl, t2_rgb(np_["hl_color"]))):
        t2_paint(spr, (_shear(m, k, cy0 + _cap(f) / 2.0) if k else m, (0, 0)), c)
    spr.info.update({"line_y": yb, "top": yt, "band_h": bh, "n_lines": n})
    return spr


# ---- items ------------------------------------------------------------------------------------------------------------------
def _cues(cfg):
    out = []
    for c in caption_streams(cfg):
        try:
            cues = parse_srt(c["srt"])
        except Exception:
            continue
        if cues:
            out.append(cues)
    return out


def _build(np_, W, H, fp):
    """-> [(sprite, cx, cy)] for a W x H canvas (card, bar). Wide canvas: card bottom-right + bar bottom-left; narrow: card above the bar."""
    s = min(W, H) / 1080.0
    safe, stacked = G["safe"] * s, W < H
    y_line = H - G["line_y"] * s
    max_w = W - 2 * safe if stacked else min(W - 2 * safe, 0.52 * W)          # wide canvas: a long name shrinks, the card stays <= 52 % of W
    card = t4_nameplate_sprite(np_, fp, s, max_w)
    rl = None
    if card is not None and not stacked:
        rl = W - safe - card.info["panel"][2] - G["tag_gap"] * s
    bar = t4_tagline_sprite(np_, fp, s, W, rl)
    out = []
    if bar is not None:
        top = y_line - bar.info["line_y"]
        out.append((bar, W / 2.0, top + bar.height / 2.0))
    if card is not None:
        px, py, pw, ph = card.info["panel"]
        gap = G["gap_stack"] * s if (stacked and bar is not None) else G["gap"] * s
        pb = (y_line - (bar.info["band_h"] if (stacked and bar is not None) else 0) - gap)
        _stripes_below(card, np_["color"], gap if not stacked else gap * 0.5, s)
        out.append((card, W - safe - pw - px + card.width / 2.0, pb - ph - py + card.height / 2.0))
    return out


def t4_nameplate_items(cfg, duration):
    """Timeline items of the lower third (card + bar share one window and one animation). [] when off / not timed / no canvas."""
    t4 = cfg.get("t4") if isinstance(cfg, dict) else None
    np_ = t4_nameplate_cfg(t4.get("nameplate") if isinstance(t4, dict) else None)
    if not np_["on"]:
        return []
    try:
        W, H = int(cfg["canvas"][0]), int(cfg["canvas"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        t4_warn("nameplate: the job has no canvas - skipped.")
        return []
    win = t4_time(dict(np_, label="nameplate"), _cues(cfg) if str(np_.get("trigger") or "").strip() else [], duration, 6.0)
    if win is None:
        return []
    fp = np_.get("font") if isinstance(np_.get("font"), str) and os.path.isfile(np_["font"]) else default_font()
    key = (W, H, fp, repr({k: np_[k] for k in T4_NAMEPLATE if k not in ("anim", "anim_dur", "on")}))
    if key not in _CACHE:
        if len(_CACHE) >= 3:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = _build(np_, W, H, fp)
    rtl = is_rtl_text(np_["name1"] + " " + np_["name2"])
    return [Item(spr, win[0], win[1], cx, cy, np_["anim"], np_["anim_dur"], out=True, rtl=rtl) for spr, cx, cy in _CACHE[key]]
