"""mt.captions - moved from montage.py by tools/mt_move.py"""
from mt.fonts import ARABIC_RE, is_rtl_text, load_font, shape
from mt.common import D, T2_ACCENT, ask, ask_choice, c_color, c_float, c_int, c_percent, yn
from mt.ask import ask_anim, ask_font
from mt.draw import T2_DEFAULT_BOX, t2_cfg
from mt.draw import Item, t2_paint, t2_rgb, t2_rrect_mask
from mt.fonts import t2_font
import re
from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path
import os


# ----------------------------------------------------------------------------
# Rich text: per-word colors, mixed Arabic/English, soft shadow
# ----------------------------------------------------------------------------
_TASH = re.compile("[ً-ٰٟـ]")


def norm_tok(s):
    s = _TASH.sub("", s)
    for a in "أإآ":
        s = s.replace(a, "ا")
    s = s.replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"[^\w]", "", s, flags=re.UNICODE).lower()


def parse_markup(text):
    """'a *b c* d' -> [[a,False],[b,True],[c,True],[d,False]]"""
    out, hl = [], False
    for raw in text.split():
        if raw.startswith("*"):
            hl = True
        tok = raw.replace("*", "")
        if tok:
            out.append([tok, hl])
        if re.search(r"\*[^\w]*$", raw):
            hl = False
    return out


def split_keywords(s):
    return [k.strip() for k in re.split(r"[,،;]", s or "") if k.strip()]


def kw_sequences(keywords):
    seqs = []
    for k in keywords:
        parts = [p for p in (norm_tok(x) for x in k.split()) if p]
        if parts:
            seqs.append(parts)
    return seqs


def find_sequences(norm_list, seqs):
    hits = []
    for seq in seqs:
        n = len(seq)
        for i in range(len(norm_list) - n + 1):
            if norm_list[i:i + n] == seq:
                hits.append((i, n))
    return sorted(hits)


def apply_keywords(tokens, seqs):
    norm = [norm_tok(t) for t, _ in tokens]
    for i, n in find_sequences(norm, seqs):
        for j in range(i, i + n):
            tokens[j][1] = True
    return tokens


def flatten_tokens(cues):
    """[(word, start, end)] - words of sentence cues share the cue time by length."""
    toks = []
    for s, e, text in cues:
        words = text.split()
        if not words:
            continue
        weights = [len(w) + 1 for w in words]
        tot = float(sum(weights))
        t = s
        for w, wt in zip(words, weights):
            d = (e - s) * wt / tot
            toks.append((w, t, t + d))
            t += d
    return toks


def phrase_groups(cues, max_words=8, min_words=3, gap=0.6):
    """Phrases for 'whole sentence' captions. Sentence-level SRTs are kept as they are;
    word-level SRTs are chunked (by max_words, punctuation and pauses)."""
    if not cues:
        return []
    toks = flatten_tokens(cues)
    if len(toks) / float(len(cues)) >= 3:
        return [(s, e, t) for s, e, t in cues]
    groups, cur = [], []

    def flush():
        if cur:
            groups.append([cur[0][1], cur[-1][2], " ".join(w for w, _, _ in cur)])
            cur.clear()

    for w, s, e in toks:
        if cur and s - cur[-1][2] > gap:
            flush()
        cur.append((w, s, e))
        if len(cur) >= max_words or (re.search(r"[.!?؟،,;:]$", w) and len(cur) >= min_words):
            flush()
    flush()
    for i in range(len(groups) - 1):
        if groups[i + 1][0] - groups[i][1] < 0.5:
            groups[i][1] = groups[i + 1][0]
    return [tuple(g) for g in groups]


def _tok_dir(t):
    if ARABIC_RE.search(t):
        return "R"
    if re.search(r"[A-Za-z0-9]", t):
        return "L"
    return "N"


def visual_order(items, base_rtl):
    """Word-level bidi: returns items in left-to-right drawing order."""
    dirs, prev = [], ("R" if base_rtl else "L")
    for it in items:
        d = _tok_dir(it[0])
        if d == "N":
            d = prev
        dirs.append(d)
        prev = d
    runs = []
    for it, d in zip(items, dirs):
        if runs and runs[-1][0] == d:
            runs[-1][1].append(it)
        else:
            runs.append([d, [it]])
    if base_rtl:
        runs.reverse()
    out = []
    for d, ws in runs:
        out.extend(ws[::-1] if d == "R" else ws)
    return out


def make_rich_sprite(tokens, font_path, size, fill, hl_fill=None, stroke_fill=None, stroke_w=0,
                     max_w=10 ** 6, shadow=False):
    """tokens: [[text, highlighted_bool], ...]  ->  centered multi-line RGBA sprite."""
    stroke_w = int(stroke_w or 0)
    if stroke_w and not stroke_fill:
        stroke_fill = "#000000"
    hl_fill = hl_fill or fill
    base_rtl = is_rtl_text(" ".join(t for t, _ in tokens))
    avail = max_w - 2 * (stroke_w + 10)

    def wrap(widths, sp, limit):
        lines, cur, curw = [], [], 0.0
        for i, wd in enumerate(widths):
            add = wd if not cur else sp + wd
            if cur and curw + add > limit:
                lines.append(cur)
                cur, curw = [i], wd
            else:
                cur.append(i)
                curw += add
        if cur:
            lines.append(cur)
        return lines

    while True:
        font = load_font(font_path, int(size))
        sp = font.getlength(" ")
        widths = [font.getlength(shape(t)) for t, _ in tokens]
        lines = wrap(widths, sp, avail)
        n = len(lines)
        total = sum(widths) + sp * (len(widths) - 1)
        if n > 1:  # balance the lines (avoid one very short last line)
            for target in (total / n * 1.08, total / n * 1.2, avail):
                cand = wrap(widths, sp, min(target, avail))
                if len(cand) == n:
                    lines = cand
                    break
        line_w = [sum(widths[i] for i in ln) + sp * (len(ln) - 1) for ln in lines]
        if max(line_w) <= avail or size <= 14:
            break
        size = max(14, int(size * 0.92))

    asc, desc = font.getmetrics()
    lh = asc + desc
    gap = int(size * 0.16)
    pad = stroke_w + int(size * 0.32) + 4
    w = int(max(line_w)) + 2 * pad
    h = len(lines) * lh + (len(lines) - 1) * gap + 2 * pad

    def paint(draw, mono=None, sw=0, soff=0):
        for li, ln in enumerate(lines):
            items = [(tokens[i][0], tokens[i][1], widths[i]) for i in ln]
            ordered = visual_order(items, base_rtl)
            x = (w - line_w[li]) / 2.0
            yb = pad + asc + li * (lh + gap) + soff
            for txt, hl, wd in ordered:
                col = mono if mono else (hl_fill if hl else fill)
                draw.text((x, yb), shape(txt), font=font, fill=col, anchor="ls",
                          stroke_width=sw, stroke_fill=stroke_fill if sw else None)
                x += wd + sp

    img = Image.new("RGBA", (max(w, 4), max(h, 4)), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        paint(ImageDraw.Draw(sh), mono=(0, 0, 0, 215), sw=max(0, stroke_w), soff=max(2, int(size * 0.06)))
        sh = sh.filter(ImageFilter.GaussianBlur(max(2, size * 0.07)))
        img.alpha_composite(sh)
    paint(ImageDraw.Draw(img), sw=stroke_w)
    return img


# ----------------------------------------------------------------------------
# SRT
# ----------------------------------------------------------------------------
TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _ts(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0


def parse_srt(path):
    raw = None
    for enc in ("utf-8-sig", "utf-16", "cp1256", "latin-1"):
        try:
            raw = Path(path).read_text(encoding=enc)
            break
        except Exception:
            continue
    if raw is None:
        raise ValueError("cannot read the SRT file")
    raw = raw.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = raw.split("\n")
    tis = [i for i, l in enumerate(lines) if TIME_RE.search(l)]     # blank lines anywhere are fine: cues start at timing lines
    cues = []
    for n, ti in enumerate(tis):
        j = tis[n + 1] if n + 1 < len(tis) else len(lines)
        body = lines[ti + 1:j]
        if n + 1 < len(tis) and body and body[-1].strip().isdigit() and (len(body) == 1 or not body[-2].strip()):
            body = body[:-1]                                         # the next cue's index number
        m = TIME_RE.search(lines[ti])
        start = _ts(*m.group(1, 2, 3, 4))
        end = _ts(*m.group(5, 6, 7, 8))
        text = " ".join(l.strip() for l in body if l.strip())
        text = re.sub(r"<[^>]+>|\{[^}]*\}", "", text).strip()
        if text and end > start:
            cues.append((start, end, text))
    cues.sort()
    return cues


def caption_groups(cues, words_per_group):
    out = []
    n = max(1, int(words_per_group))
    for start, end, text in cues:
        words = text.split()
        groups = [words[i:i + n] for i in range(0, len(words), n)]
        weights = [sum(len(w) + 1 for w in g) for g in groups]
        total = float(sum(weights)) or 1.0
        t = start
        for g, wt in zip(groups, weights):
            d = (end - start) * wt / total
            out.append((t, t + d, " ".join(g)))
            t += d
    return out


# ----------------------------------------------------------------------------
# Interactive questions
# ----------------------------------------------------------------------------
def ask_caption_style(idx, srt_path):
    print(f"\n--- Caption style for SRT #{idx + 1}: {Path(srt_path).name} ---")
    k = str(idx)
    c = {"srt": srt_path}
    c["font"] = ask_font("Caption font", "cap_font" + k)
    c["size"] = ask("Caption font size (px)", default=(42, 36, 36)[min(idx, 2)], key="cap_size" + k, cast=c_int)
    c["color"] = ask("Text color", default="white", key="cap_color" + k, cast=c_color)
    c["hl_color"] = ask("Highlight color for important words", default="#00b8ff", key="cap_hl" + k, cast=c_color)
    c["keywords"] = ask("Words to highlight automatically, comma separated "
                        "(Enter = none; you can also put *stars* around words inside the SRT)",
                        allow_empty=True) or ""
    c["stroke_color"] = "#000000"
    c["stroke_w"] = ask("Outline width (px, 0 = none)", default=0, key="cap_strokew" + k, cast=c_int)
    c["shadow"] = yn("Soft shadow behind the text?", default=True)
    mode = ask_choice("Show captions as:", ["Word by word", "Whole phrases (auto grouped, like the reference)"],
                      default=2 if idx == 0 else 2)
    c["mode"] = "words" if mode == 1 else "phrase"
    if mode == 1:
        c["words_per_group"] = ask("Words shown at the same time (1 = word by word)", default=1,
                                   key="cap_wpg" + k, cast=c_int)
    else:
        c["max_words"] = ask("Max words per phrase (only used when the SRT is word-by-word)", default=8,
                             key="cap_maxw" + k, cast=c_int)
    ref = ask_choice("Where should these captions appear?",
                     ["Inside the video box", "On the canvas (for example below the video)"],
                     default=1 if idx == 0 else 2)
    c["ref"] = "box" if ref == 1 else "canvas"
    c["y_pct"] = ask("Vertical center position (% from the top of the " + ("video box" if ref == 1 else "canvas") + ")",
                     default=86 if (ref == 1) else (72 if idx <= 1 else 88), cast=c_percent)
    c["anim"] = ask_anim("Caption animation", default="pop" if mode == 1 else "fade", key="cap_anim" + k)
    c["anim_dur"] = ask("Animation duration (seconds)", default=0.12 if mode == 1 else 0.25,
                        key="cap_adur" + k, cast=c_float)
    return c


# ----------------------------------------------------------------------------
# Build timeline + render
# ----------------------------------------------------------------------------
def stream_groups(cues, c):
    """Caption groups for one SRT: [(start, end, [[word, highlighted], ...]), ...]"""
    toks = []
    for ci, (s, e, text) in enumerate(cues):
        pm = parse_markup(text)
        if not pm:
            continue
        weights = [len(w) + 1 for w, _ in pm]
        tot = float(sum(weights))
        t = s
        for (w, hl), wt in zip(pm, weights):
            d = (e - s) * wt / tot
            toks.append([w, t, t + d, hl, ci])
            t += d
    seqs = kw_sequences(split_keywords(c.get("keywords", "")))
    if seqs and toks:
        norm = [norm_tok(x[0]) for x in toks]
        for i, n in find_sequences(norm, seqs):
            for j in range(i, i + n):
                toks[j][3] = True
    chunks = []
    if c.get("mode", "words") == "words":
        n = max(1, int(c.get("words_per_group", 1)))
        chunks = [toks[i:i + n] for i in range(0, len(toks), n)]
    else:
        avg = len(toks) / float(len(cues)) if cues else 0
        if avg >= 3:
            cur_ci = None
            for tk in toks:
                if tk[4] != cur_ci:
                    chunks.append([])
                    cur_ci = tk[4]
                chunks[-1].append(tk)
        else:
            mx, cur = max(2, int(c.get("max_words", 8))), []
            for tk in toks:
                if cur and tk[1] - cur[-1][2] > 0.6:
                    chunks.append(cur)
                    cur = []
                cur.append(tk)
                if len(cur) >= mx or (re.search(r"[.!?\u061f\u060c,;:]$", tk[0]) and len(cur) >= 3):
                    chunks.append(cur)
                    cur = []
            if cur:
                chunks.append(cur)
    groups = [[ch[0][1], ch[-1][2], [[t[0], t[3]] for t in ch]] for ch in chunks if ch]
    if c.get("mode", "words") != "words":
        for i in range(len(groups) - 1):
            if 0 <= groups[i + 1][0] - groups[i][1] < 0.5:
                groups[i][1] = groups[i + 1][0]
    return [tuple(g) for g in groups]


def caption_streams(cfg):
    caps = cfg.get("captions")
    if not caps:
        return []
    if isinstance(caps, dict):  # job files from the first version
        d = dict(caps)
        d["srt"] = cfg.get("srt")
        d.setdefault("mode", "words")
        d.setdefault("ref", "box")
        caps = [d] if d.get("srt") else []
    return caps


# ---- Template 2: caption style (Part 3A) ------------------------------------------------------------
# Poster caption box = (217,985)-(708,1095) -> 1080 px: ~564x126 px, 29 px above the window's bottom edge;
# lime bar = poster x 228-236 (9 px wide, 72 % of the box height, 13 px from the box's left edge).
T2_CAP = {"radius": 20, "alpha": 0.70, "bar_x": 13, "bar_w": 9, "bar_h": 0.72, "text_l": 38, "text_r": 24,
          "pad_y": 16, "min_w": 300, "max_w_frac": 0.78, "bottom_gap": 29, "hl_scale": 1.08,
          "size_box": 42, "size_sub": 30, "max_lines": 2}


def t2_caption_layout(cfg, streams=None):
    """Geometry shared by the Template 2 caption streams (frame = the video window)."""
    b = cfg.get("video_box") or T2_DEFAULT_BOX
    streams = caption_streams(cfg) if streams is None else streams
    sub = [c for c in streams if c.get("t2_style") == "sub"]
    sub_h = int(max([c.get("size") or T2_CAP["size_sub"] for c in sub] or [0]) * 1.75)
    bottom = b["y"] + b["h"] - T2_CAP["bottom_gap"]
    return {"cx": b["x"] + b["w"] / 2.0, "frame": (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]),
            "max_w": int(b["w"] * T2_CAP["max_w_frac"]), "sub_h": sub_h,
            "sub_bottom": bottom, "box_bottom": bottom - (sub_h + 6 if sub_h else 0)}


def t2_caption_sprite(tokens, font_path, size, fill="#ffffff", hl_fill=T2_ACCENT, accent=T2_ACCENT, max_w=660,
                      min_w=None, max_lines=None, stroke_w=0, stroke_fill="#000000", want_meta=False):
    """The Template 2 caption: dark translucent (70 % black) rounded box + accent vertical bar on its left +
    heavy centered text (max 2 lines, RTL-correct, highlighted words in the accent colour, slightly bolder and
    larger).  The box auto-sizes to the text (min_w .. max_w); long text wraps, then shrinks, never overflows.
    tokens = [[text, highlighted_bool], ...].  Returns the RGBA sprite (= the box), or (sprite, meta)."""
    C = T2_CAP
    min_w = C["min_w"] if min_w is None else min_w
    max_lines = max_lines or C["max_lines"]
    fill, hl_fill, acc = t2_rgb(fill), t2_rgb(hl_fill), t2_rgb(accent)
    base_rtl = is_rtl_text(" ".join(t for t, _ in tokens))
    avail = max(60, max_w - C["text_l"] - C["text_r"])
    size = float(size)

    def wrap(widths, sp, limit):
        lines, cur, curw = [], [], 0.0
        for i, wd in enumerate(widths):
            add = wd if not cur else sp + wd
            if cur and curw + add > limit:
                lines.append(cur)
                cur, curw = [i], wd
            else:
                cur.append(i)
                curw += add
        if cur:
            lines.append(cur)
        return lines

    while True:
        isz = max(10, int(round(size)))
        fn = load_font(font_path, isz)
        fh = load_font(font_path, max(10, int(round(isz * C["hl_scale"]))))
        sw = max(1, int(round(isz * 0.022)))            # synthetic 'heavy' weight (also on fonts with no Bold)
        swh = sw + 1
        sp = fn.getlength(" ")
        widths = [(fh if hl else fn).getlength(shape(t)) + 2 * (swh if hl else sw) for t, hl in tokens]
        lines = wrap(widths, sp, avail)
        n = len(lines)
        total = sum(widths) + sp * (len(widths) - 1)
        if n > 1:                                          # balance the lines (no tiny last line)
            for target in (total / n * 1.08, total / n * 1.2, avail):
                cand = wrap(widths, sp, min(target, avail))
                if len(cand) == n:
                    lines = cand
                    break
        if len(lines) <= max_lines or isz <= 22:
            break
        size *= 0.92
    if len(lines) > max_lines:                             # last resort: cut the text, add an ellipsis
        lines = lines[:max_lines]
        last = [i for i in lines[-1]]
        while len(last) > 1 and sum(widths[i] for i in last) + sp * (len(last) - 1) + fn.getlength("…") > avail:
            last.pop()
        lines[-1] = last
        tokens = [list(t) for t in tokens]
        tokens[last[-1]][0] = tokens[last[-1]][0] + "…"
        widths[last[-1]] = max(widths[last[-1]], fn.getlength(shape(tokens[last[-1]][0])) + 2 * sw)
    line_w = [sum(widths[i] for i in ln) + sp * (len(ln) - 1) for ln in lines]
    asc, desc = fn.getmetrics()
    if any(h for _, h in tokens):          # الكلمة المميّزة أكبر، فاحسب الارتفاع منها
        h_asc, h_desc = fh.getmetrics()
        asc, desc = max(asc, h_asc), max(desc, h_desc)
    lh = int(max(isz * 1.12, min(asc + desc, isz * 1.5)))
    gap = int(isz * 0.10)
    pad_y = C["pad_y"]
    box_w = int(min(max_w, max(min_w, max(line_w) + C["text_l"] + C["text_r"])))
    box_h = len(lines) * lh + (len(lines) - 1) * gap + 2 * pad_y
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    t2_paint(img, t2_rrect_mask((0, 0, box_w, box_h), C["radius"]), (0, 0, 0, int(255 * C["alpha"])))
    bh = int(box_h * C["bar_h"])
    bar_box = (C["bar_x"], (box_h - bh) // 2, C["bar_x"] + C["bar_w"], (box_h - bh) // 2 + bh)
    t2_paint(img, t2_rrect_mask(bar_box, C["bar_w"] / 2.0), acc + (255,))
    d = ImageDraw.Draw(img)
    cx_text = C["text_l"] + (box_w - C["text_l"] - C["text_r"]) / 2.0
    tok_boxes = []
    for li, ln in enumerate(lines):
        ordered = visual_order([(tokens[i][0], tokens[i][1], widths[i], i) for i in ln], base_rtl)
        x = cx_text - line_w[li] / 2.0
        yb = pad_y + (lh - (asc + desc)) / 2.0 + asc + li * (lh + gap)
        for txt, hl, wd, ti in ordered:
            f_, s_ = (fh, swh) if hl else (fn, sw)
            col = hl_fill if hl else fill
            if stroke_w:                                   # optional outline, drawn under the text
                d.text((x + wd / 2.0, yb), shape(txt), font=f_, fill=t2_rgb(stroke_fill), anchor="ms",
                       stroke_width=s_ + int(stroke_w), stroke_fill=t2_rgb(stroke_fill))
            d.text((x + wd / 2.0, yb), shape(txt), font=f_, fill=col, anchor="ms",
                   stroke_width=s_, stroke_fill=col)
            tok_boxes.append((txt, bool(hl), (int(x), int(yb - asc), int(x + wd), int(yb + desc))))
            x += wd + sp
    if not want_meta:
        return img
    return img, {"box": (0, 0, box_w, box_h), "bar": bar_box, "tokens": tok_boxes, "lines": len(lines),
                 "size": isz}


def t2_subline_sprite(tokens, font_path, size, fill="#ffffff", hl_fill=T2_ACCENT, max_w=660, stroke_w=0, min_size=20):
    """Small ONE-line caption (the English line under the Arabic box): white, accent highlight, soft shadow.
    Shrinks to fit max_w (not below min_size); text that still does not fit is cut with an ellipsis."""
    size = int(size)
    tokens = [list(t) for t in tokens]

    def build(tk, sz):
        return make_rich_sprite(tk, font_path, sz, fill, hl_fill, "#000000", stroke_w, max_w=10 ** 6, shadow=True)
    spr = build(tokens, size)
    for _ in range(6):
        if spr.width <= max_w or size <= min_size:
            break
        size = max(min_size, int(size * max_w / float(spr.width) * 0.97))
        spr = build(tokens, size)
    while spr.width > max_w and len(tokens) > 1:
        tokens = tokens[:-1] if tokens[-1][0] != "\u2026" else tokens[:-2] + [tokens[-1]]
        if tokens[-1][0] != "\u2026":
            tokens.append(["\u2026", False])
        spr = build(tokens, size)
    return spr


def t2_caption_items(cfg, c, groups, duration):
    """Template 2 caption items for one stream (c['t2_style'] = 'box' | 'sub')."""
    t2 = t2_cfg(cfg.get("t2"))
    lay = t2_caption_layout(cfg)
    role = c.get("t2_style")
    font = c.get("font") if c.get("font") and os.path.isfile(str(c.get("font"))) else t2_font("arabic", "ع", t2.get("fonts"))[0]
    hl = c.get("hl_color") or t2["accent"]
    size = c.get("size") or (T2_CAP["size_box"] if role == "box" else T2_CAP["size_sub"])
    fr = lay["frame"]
    yp = c.get("y_pct")
    items = []
    for s, e, toks in groups:
        if s >= duration:
            continue
        toks = [list(t) for t in toks]
        if role == "box":
            spr = t2_caption_sprite(toks, font, size, c.get("color", "#ffffff"), hl, t2["accent"], lay["max_w"],
                                    stroke_w=c.get("stroke_w", 0), stroke_fill=c.get("stroke_color", "#000000"))
            cy = lay["box_bottom"] - spr.height / 2.0 if yp in (None, "") else fr[1] + (fr[3] - fr[1]) * float(yp) / 100.0
        else:
            spr = t2_subline_sprite(toks, font, size, c.get("color", "#ffffff"), hl, lay["max_w"],
                                    c.get("stroke_w", 0))
            cy = lay["sub_bottom"] - spr.height / 2.0 if yp in (None, "") else fr[1] + (fr[3] - fr[1]) * float(yp) / 100.0
        items.append(Item(spr, s, e, lay["cx"], cy, c.get("anim", "fade"), c.get("anim_dur", 0.2), out=False,
                          rtl=is_rtl_text(" ".join(t[0] for t in toks))))
    return items


def t2_caption_style(idx, srt_path):
    """Questions for one Template 2 caption stream: stream 1 = the Arabic box, further streams = the small line."""
    role = "box" if idx == 0 else "sub"
    print(f"\n--- Caption style for SRT #{idx + 1}: {Path(srt_path).name}  "
          f"({'dark box with lime bar' if role == 'box' else 'small line under the box'}) ---")
    k = "t2cap" + str(idx)
    if not (D.get("cap_font" + k) and os.path.isfile(D.get("cap_font" + k))):
        D["cap_font" + k] = t2_font("arabic", "ع")[0] or ""
    c = {"srt": srt_path, "t2_style": role, "ref": "box"}
    c["font"] = ask_font("Caption font", "cap_font" + k)
    c["size"] = ask("Caption font size (px)", default=T2_CAP["size_box"] if role == "box" else T2_CAP["size_sub"],
                    key="cap_size" + k, cast=c_int)
    c["color"] = ask("Text color", default="white", key="cap_color" + k, cast=c_color)
    c["hl_color"] = ask("Highlight color (Enter = the template accent / lime)", allow_empty=True, cast=c_color) or ""
    c["keywords"] = ask("Words to highlight automatically, comma separated "
                        "(Enter = none; you can also put *stars* around words inside the SRT)",
                        allow_empty=True) or ""
    c["stroke_color"] = "#000000"
    c["stroke_w"] = 0
    c["shadow"] = role == "sub"
    mode = ask_choice("Show captions as:", ["Word by word", "Whole phrases (auto grouped)"], default=2)
    c["mode"] = "words" if mode == 1 else "phrase"
    if mode == 1:
        c["words_per_group"] = ask("Words shown at the same time (1 = word by word)", default=1,
                                   key="cap_wpg" + k, cast=c_int)
    else:
        c["max_words"] = ask("Max words per phrase (only used when the SRT is word-by-word)", default=8,
                             key="cap_maxw" + k, cast=c_int)
    yp = ask("Vertical position override (% from the top of the video window, Enter = poster position)",
             allow_empty=True, cast=c_percent)
    c["y_pct"] = yp
    c["anim"] = ask_anim("Caption animation", default="pop" if mode == 1 else "fade", key="cap_anim" + k)
    c["anim_dur"] = ask("Animation duration (seconds)", default=0.12 if mode == 1 else 0.25,
                        key="cap_adur" + k, cast=c_float)
    return c


def find_trigger(cues, phrase):
    toks = flatten_tokens(cues)
    norm = [norm_tok(t[0]) for t in toks]
    hits = find_sequences(norm, kw_sequences([phrase]))
    return toks[hits[0][0]][1] if hits else None
