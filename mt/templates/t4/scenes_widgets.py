"""mt.templates.t4.scenes_widgets - Template 4 scenes: widget 'code_window' (refs R5 portrait / R6 landscape, measured in T4_P15_ADDENDUM).
[ red yellow green dots | tab: file icon + file name ]     tab bar (49 px at R5 size)
  1  def create_better_future():                           line numbers (gutter) + syntax-coloured monospace code
  2      return "Learn • Build • Grow"
spec keys (all optional): file 'main.py' (tab name; the extension picks the icon: .py / .js / .html / other), lang '' ('py' | 'js' | 'plain';
  '' = from the extension; python and javascript rules), code (str with \\n, or a list of lines; missing = the R5 demo snippet), font '' (path;
  '' = first monospace font found: Consolas, Cascadia Mono, Source Code Pro, Ubuntu Mono, Lucida Console, DejaVu Sans Mono, Courier New, else the
  default font), numbers True (line numbers), reveal 'none' | 'typewriter' (one Item per non-empty line, 'reveal' anim, staggered),
  line_step 0.35 (s between lines), line_dur 0.4 (s one line takes to be typed).
Everything scales with u = min(box.w / 434, box.h / 242) (R5 window = 434 x 242 px). The code font shrinks (down to 60 %) when a line is too
wide or there are too many lines; more lines than fit are cut with one t4_warn. Characters the monospace font lacks (the bullet) and Arabic
runs are drawn with the default font per run (Arabic shaped with mt.fonts.shape); the line stays left-aligned at the code column.
The static window (frame + tab + gutter) is ONE cached sprite. 'typewriter': the lines are NOT in it; they sit in sprite.info['lines'] =
[(line sprite, x, y)] (top-left in sprite coords) with info['line_step'] / ['line_dur'] and the engine adds one Item per line through
t4_widget_line_items(). Public: T4_CODE_WINDOW, t4_tokenize(line, lang), t4_code_window(spec, box, ctx), t4_widget_line_items(...),
t4_ask_code_window()."""
import os
import re
import textwrap

from PIL import Image, ImageChops, ImageDraw

from mt.common import ask, ask_choice
from mt.draw import Item
from mt.fonts import default_font, find_font, load_font, shape
from mt.templates.t4.kit import glass_panel, kit_paste
from mt.templates.t4.nameplate import _bool, _cached, _flt
from mt.templates.t4.scenes_reg import register_widget
from mt.templates.t4.warn import t4_warn

try:
    from mt.fonts import _font_cmap
except ImportError:                                            # pragma: no cover - older mt.fonts
    def _font_cmap(path):
        return None

R5_CODE = 'def create_better_future():\n    return "Learn • Build • Grow"\n\n# Eduvia\nprint(create_better_future())'
T4_CODE_WINDOW = {"file": "main.py", "lang": "", "code": R5_CODE, "font": "", "numbers": True, "reveal": "none", "line_step": 0.35, "line_dur": 0.4}
MAX_LINES = 16
BASE_W, BASE_H = 434.0, 242.0                                   # R5 window; every size below is px at that scale (x u)
BAR_H, DOT_D, DOT_X, DOT_PITCH, TAB_X = 49, 16, 25, 24, 99
FONT_PX, PITCH_K, TOP_PAD, CODE_X, NUM_X = 18, 1.65, 24, 89, 50
TINT_BODY, BORDER, BAR_RGB, TAB_RGB, DIVIDER = (10, 20, 36, 235), (27, 58, 85), (15, 29, 49), (8, 17, 32), (4, 9, 18)
DOTS = ((255, 95, 86), (255, 189, 46), (39, 201, 63))
NAME_RGB, NUM_RGBA, GUIDE_RGB = (142, 232, 240), (143, 201, 221, 178), (36, 64, 90)
COLORS = {"kw_a": (255, 210, 31), "kw_b": (255, 92, 225), "call_b": (47, 140, 255), "str": (255, 201, 60), "com": (107, 224, 74),
          "num": (255, 158, 74), "fn": (242, 246, 250), "text": (242, 246, 250)}
MONO_NAMES = ("consola", "CascadiaMono", "SourceCodePro-Regular", "UbuntuMono-Regular", "lucon", "DejaVuSansMono", "cour")
_CW, _MONO = {}, {}


# ---- tokenizer -------------------------------------------------------------------------------------------------------------
_NUM = r"(?P<num>\b\d[\d_]*(?:\.\d+)?\b)"
_TAIL = _NUM + r"|(?P<id>[A-Za-z_$][\w$]*)|(?P<sp>\s+)|(?P<other>.)"
_TOK = {"py": re.compile(r"(?P<com>#.*)|(?P<str>[rbfRBF]{0,2}(?:\"(?:\\.|[^\"\\])*\"?|'(?:\\.|[^'\\])*'?))|" + _TAIL),
        "js": re.compile(r"(?P<com>//.*|/\*.*?(?:\*/|$))|(?P<str>\"(?:\\.|[^\"\\])*\"?|'(?:\\.|[^'\\])*'?|`(?:\\.|[^`\\])*`?)|" + _TAIL)}
_KW = {"py": ({"def", "class", "lambda"}, {"return", "if", "elif", "else", "for", "while", "import", "from", "as", "in", "not", "and", "or", "is",
                                           "try", "except", "finally", "with", "raise", "pass", "break", "continue", "yield", "None", "True", "False"}),
       "js": ({"const", "let", "var", "function", "class"}, {"return", "if", "else", "for", "while", "import", "from", "export", "new", "typeof",
                                                             "await", "async", "of", "in", "switch", "case", "break", "continue", "throw", "try",
                                                             "catch", "default", "null", "true", "false", "undefined"})}
_DEFWORD = {"py": {"def", "class"}, "js": {"function", "class"}}
_BUILTIN = {"py": {"print", "len", "range", "input", "int", "str", "float", "open", "list", "dict", "set", "sum", "min", "max", "enumerate", "zip", "type"},
            "js": {"log", "warn", "error", "info", "require", "fetch", "parseInt", "parseFloat", "setTimeout", "alert"}}


def _next_char(toks, i):
    for t, k in toks[i + 1:]:
        if k != "sp":
            return t[0]
    return ""


def t4_tokenize(line, lang):
    """One code line -> [(text, kind)], kind in kw_a / kw_b / fn / call_b / str / com / num / text. Unknown lang = no colouring. Never raises."""
    line = line if isinstance(line, str) else ""
    if lang not in _TOK:
        return [(line, "text")] if line else []
    ka, kb = _KW[lang]
    toks = [(m.group(), m.lastgroup) for m in _TOK[lang].finditer(line)]
    out, prev = [], ""
    for i, (t, k) in enumerate(toks):
        kind = k if k in ("str", "com", "num") else "text"
        if k == "id":
            kind = ("kw_a" if t in ka else "kw_b" if t in kb else "fn" if prev in _DEFWORD[lang]
                    else "call_b" if t in _BUILTIN[lang] and _next_char(toks, i) == "(" else "text")
        out.append((t, kind))
        if k != "sp":
            prev = t if k == "id" else ""
    return out


# ---- spec -------------------------------------------------------------------------------------------------------------------
def _lang(raw, name):
    v = raw.strip().lower() if isinstance(raw, str) else ""
    alias = {"py": "py", "python": "py", "js": "js", "javascript": "js", "ts": "js", "typescript": "js", "jsx": "js", "plain": "plain", "text": "plain"}
    if v in alias:
        return alias[v]
    if v:
        t4_warn("code_window: unknown lang '%s' - taken from the file extension." % v)
    ext = os.path.splitext(name)[1].lower()
    return "py" if ext == ".py" else "js" if ext in (".js", ".mjs", ".ts", ".jsx", ".tsx", ".json") else "plain"


def _code_lines(code):
    if isinstance(code, (list, tuple)):
        code = "\n".join(str(x) for x in code)
    code = str(code).replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    lines = [ln.rstrip() for ln in textwrap.dedent(code).rstrip("\n").split("\n")]
    if len(lines) > MAX_LINES:
        t4_warn("code_window: %d lines - only the first %d are used." % (len(lines), MAX_LINES))
        lines = lines[:MAX_LINES]
    return lines


def _spec(raw):
    """Complete, clean spec (never raises; junk -> defaults); out['_lines'] = the code lines."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(T4_CODE_WINDOW)
    f = raw.get("file")
    out["file"] = re.split(r"[\\/]", f.strip())[-1] if isinstance(f, str) and f.strip() else out["file"]
    out["lang"] = _lang(raw.get("lang"), out["file"])
    fo = raw.get("font")
    out["font"] = fo.strip() if isinstance(fo, str) else ""
    out["numbers"] = _bool(raw.get("numbers"), True)
    r = raw.get("reveal")
    out["reveal"] = "typewriter" if r is True or (isinstance(r, str) and r.strip().lower() in ("typewriter", "type", "reveal", "line", "lines")) else "none"
    out["line_step"], out["line_dur"] = _flt(raw.get("line_step"), 0.0, 5.0, 0.35), _flt(raw.get("line_dur"), 0.05, 5.0, 0.4)
    code = raw.get("code") if "code" in raw and isinstance(raw.get("code"), (str, list, tuple)) else R5_CODE
    out["code"] = code
    out["_lines"] = _code_lines(code)
    return out


# ---- fonts / runs -----------------------------------------------------------------------------------------------------------
_AR = "\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF"
_AR_RUN = re.compile("[%s]+(?:[ ]+[%s]+)*" % (_AR, _AR))


def _mono_font(path):
    """Monospace font path: the given one, else the first of MONO_NAMES found, else the default font (one warning each)."""
    if path in _MONO:
        return _MONO[path]
    found = None
    if path and os.path.isfile(path):
        found = path
    else:
        if path:
            t4_warn("code_window: font '%s' not found - looking for a monospace font." % os.path.basename(path))
        for n in MONO_NAMES:
            try:
                p = find_font(n)
            except Exception:
                p = None
            if p and os.path.isfile(p):
                found = p
                break
        if not found:
            t4_warn("code_window: no monospace font found - using the default font (put e.g. SourceCodePro-Regular.ttf in fonts/).")
            found = default_font()
    _MONO[path] = found
    return found


def _mono_runs(text, mono, fb):
    cm, out = _font_cmap(mono) if mono else None, []
    for ch in text:
        p = mono if (not cm or ord(ch) in cm or ch.isspace()) else fb
        if out and out[-1][1] == p:
            out[-1] = (out[-1][0] + ch, p, False)
        else:
            out.append((ch, p, False))
    return out


def _split_runs(text, mono, fb):
    """-> [(text, font path, arabic)]: Arabic runs -> fb (shaped when drawn); chars the monospace font lacks -> fb; the rest -> mono."""
    out, pos = [], 0
    for m in _AR_RUN.finditer(text):
        out += _mono_runs(text[pos:m.start()], mono, fb) + [(m.group(), fb, True)]
        pos = m.end()
    return out + _mono_runs(text[pos:], mono, fb)


def _line_runs(line, lang, mono, fb):
    return [(t, p, ar, COLORS[kind]) for text, kind in t4_tokenize(line, lang) for t, p, ar in _split_runs(text, mono, fb)]


def _measure(runs, size):
    w = 0.0
    for t, p, ar, _ in runs:
        f = load_font(p, size)
        w += f.getlength(shape(t) if ar else t)          # load_font first: shape() reads the font that was loaded last
    return w


def _draw_runs(d, x, base, runs, size):
    for t, p, ar, c in runs:
        f = load_font(p, size)
        s = shape(t) if ar else t
        d.text((x, base), s, font=f, fill=c + (255,), anchor="ls")
        x += f.getlength(s)
    return x


def _baseline(font, pitch):
    asc, desc = font.getmetrics()
    return pitch / 2.0 + (asc - desc) / 2.0


# ---- drawing helpers --------------------------------------------------------------------------------------------------------
def _shape_layer(size, paint, k=4):
    """RGBA layer drawn at k x and scaled down (anti-aliased). paint(draw, k)."""
    big = Image.new("RGBA", (size[0] * k, size[1] * k), (0, 0, 0, 0))
    paint(ImageDraw.Draw(big), k)
    return big.resize(size, Image.LANCZOS)


def _file_icon(name, size):
    """Simple vector file icon by extension: .py two squares, .js yellow 'JS', .html orange '<>', else a page glyph."""
    ext = os.path.splitext(name)[1].lower()

    def paint(d, k):
        S = size * k
        if ext == ".py":
            d.rounded_rectangle((.04 * S, .04 * S, .64 * S, .64 * S), radius=.18 * S, fill=(62, 142, 222, 255))
            d.rounded_rectangle((.36 * S, .36 * S, .96 * S, .96 * S), radius=.18 * S, fill=(255, 212, 59, 255))
            for cx, cy in ((.22, .22), (.78, .78)):
                d.ellipse(((cx - .05) * S, (cy - .05) * S, (cx + .05) * S, (cy + .05) * S), fill=(255, 255, 255, 255))
        elif ext in (".js", ".mjs"):
            d.rounded_rectangle((.04 * S, .04 * S, .96 * S, .96 * S), radius=.12 * S, fill=(247, 223, 30, 255))
            d.text((.92 * S, .90 * S), "JS", font=load_font(default_font(), max(8, int(.46 * S))), fill=(30, 30, 30, 255), anchor="rs")
        elif ext in (".html", ".htm"):
            w = max(2, int(.10 * S))
            for pts in (((.38, .22), (.08, .5), (.38, .78)), ((.62, .22), (.92, .5), (.62, .78))):
                d.line([(x * S, y * S) for x, y in pts], fill=(240, 110, 40, 255), width=w, joint="curve")
        else:
            d.polygon([(.2 * S, .05 * S), (.62 * S, .05 * S), (.82 * S, .25 * S), (.82 * S, .95 * S), (.2 * S, .95 * S)], fill=(200, 215, 230, 255))
            d.polygon([(.62 * S, .05 * S), (.82 * S, .25 * S), (.62 * S, .25 * S)], fill=(140, 160, 180, 255))
    return _shape_layer((size, size), paint)


def _window(spr, g, w, h, u):
    cut = 14 * u
    kit_paste(spr, glass_panel((w, h), 0, TINT_BODY, BORDER, (cut, cut, 0, 0), max(1.0, 1.3 * u), 0), g, g)


def _tab_bar(spr, g, w, bh, u, name, ui):
    """Slightly lighter bar (kept inside the 1 px border), divider, three dots, tab with icon + file name."""
    b = max(1, int(round(1.5 * u)))
    a = spr.getchannel("A").crop((g, g, g + w, g + bh))
    inner = Image.new("L", (w, bh), 0)
    ImageDraw.Draw(inner).rectangle((b, b, w - 1 - b, bh), fill=255)
    layer = Image.new("RGBA", (w, bh), BAR_RGB + (255,))
    layer.putalpha(ImageChops.multiply(a, inner))
    spr.alpha_composite(layer, (g, g))
    ImageDraw.Draw(spr).rectangle((g + b, g + bh - 1, g + w - 1 - b, g + bh - 1), fill=DIVIDER + (255,))

    def dots(d, k):
        for i, c in enumerate(DOTS):
            cx, cy, r = (DOT_X + i * DOT_PITCH) * u * k, bh / 2.0 * k, DOT_D / 2.0 * u * k
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=c + (255,))
    spr.alpha_composite(_shape_layer((int(round((DOT_X + 2 * DOT_PITCH + DOT_D) * u)), bh), dots), (g, g))
    f = load_font(ui, max(8, int(round(23 * u))))
    label = shape(name)
    isz, pad, gap = int(round(34 * u)), int(round(12 * u)), int(round(8 * u))
    tw = max(int(round(151 * u)), int(round(pad * 2 + gap + isz + f.getlength(label))))
    tx, r = g + int(round(TAB_X * u)), 7 * u
    spr.alpha_composite(_shape_layer((tw, bh), lambda d, k: d.rounded_rectangle((0, 0, tw * k - 1, (bh + r) * k), radius=r * k, fill=TAB_RGB + (255,))), (tx, g))
    spr.alpha_composite(_file_icon(name, isz), (tx + pad, g + (bh - isz) // 2))
    ImageDraw.Draw(spr).text((tx + pad + isz + gap, g + bh / 2.0), label, font=f, fill=NAME_RGB + (255,), anchor="lm")


def _levels(lines):
    """Indent level per line (4 spaces = 1); a blank line keeps the level of the line above (R5 line 3)."""
    out, prev = [], 0
    for ln in lines:
        if ln.strip():
            prev = (len(ln) - len(ln.lstrip(" "))) // 4
        out.append(prev)
    return out


def _gutter(spr, lines, g, top, pitch, size, u, mono, numbers, code_x):
    d, f = ImageDraw.Draw(spr), load_font(mono, size)
    base, adv, gw = _baseline(f, pitch), f.getlength(" "), max(1, int(round(u)))
    for i, lv in enumerate(_levels(lines)):
        y = top + i * pitch
        if numbers:
            d.text((g + NUM_X * u, y + base), str(i + 1), font=f, fill=NUM_RGBA, anchor="rs")
        for j in range(lv):
            x = int(round(code_x + j * 4 * adv + 2 * u))
            d.rectangle((x, y, x + gw - 1, y + pitch - 1), fill=GUIDE_RGB + (255,))


def _fit(rows, w, h, u, mono):
    """-> (font px, line pitch, lines kept): the code font shrinks (>= 60 %) for width / height, then lines are cut."""
    size, n = max(8, int(round(FONT_PX * u))), len(rows)
    if not n:
        return size, int(round(PITCH_K * size)), 0
    avail_w, avail_h = w - (CODE_X + 14) * u, h - (BAR_H + TOP_PAD + 12) * u
    k = min(1.0, avail_w / max(1.0, max(_measure(r, size) for r in rows)), avail_h / (n * PITCH_K * size))
    size = max(8, int(round(size * max(0.6, k))))
    pitch = int(round(PITCH_K * size))
    fit = max(1, int(avail_h // pitch))
    if n > fit:
        t4_warn("code_window: only %d of %d lines fit the window - the rest are cut." % (fit, n))
        n = fit
    return size, pitch, n


def _line_sprite(runs, size, pitch, maxw, mono):
    """One code line as its own sprite (clipped at maxw); None for a blank line."""
    if not runs:
        return None
    w = int(min(maxw, _measure(runs, size) + 4))
    if w < 2:
        return None
    im = Image.new("RGBA", (w, pitch), (0, 0, 0, 0))
    _draw_runs(ImageDraw.Draw(im), 0.0, _baseline(load_font(mono, size), pitch), runs, size)
    return im


# ---- build ------------------------------------------------------------------------------------------------------------------
def _build(sp, w, h, u, mono, fb, ui):
    g, lang = max(2, int(round(3 * u))), sp["lang"]
    rows = [_line_runs(t, lang, mono, fb) for t in sp["_lines"]]
    size, pitch, n = _fit(rows, w, h, u, mono)
    rows, lines = rows[:n], sp["_lines"][:n]
    spr = Image.new("RGBA", (w + 2 * g, h + 2 * g), (0, 0, 0, 0))
    bh = int(round(BAR_H * u))
    _window(spr, g, w, h, u)
    _tab_bar(spr, g, w, bh, u, sp["file"], ui)
    top, cx0 = g + bh + int(round(TOP_PAD * u)), g + int(round(CODE_X * u))
    _gutter(spr, lines, g, top, pitch, size, u, mono, sp["numbers"], cx0)
    maxw = g + w - 8 * u - cx0
    parts = [(_line_sprite(r, size, pitch, maxw, mono), cx0, top + i * pitch) for i, r in enumerate(rows)]
    parts = [p for p in parts if p[0] is not None]
    if sp["reveal"] == "typewriter":
        spr.info["lines"] = parts
    else:
        for ls, x, y in parts:
            spr.alpha_composite(ls, (x, y))
    spr.info.update({"origin": (g, g), "line_step": sp["line_step"], "line_dur": sp["line_dur"]})
    return spr


def t4_code_window(spec, box, ctx):
    """Widget function: code window sprite for the slot `box` = (x, y, w, h) canvas px. sprite.info['origin'] = the box's top-left; cached sprite
    (do not draw into it). 'typewriter': code lines are in sprite.info['lines'] (see t4_widget_line_items)."""
    sp = _spec(spec)
    w, h = max(120, int(round(box[2]))), max(80, int(round(box[3])))
    u = min(w / BASE_W, h / BASE_H)
    mono, ui = _mono_font(sp["font"]), default_font()
    fb = ui if ui else mono
    key = (tuple(sorted((k, str(v)) for k, v in sp.items())), w, h, round(u, 3), str(mono), str(fb))
    return _cached(_CW, key, lambda: _build(sp, w, h, u, mono, fb, ui), 6)


def t4_widget_line_items(sp, cx, cy, start, end, delay):
    """Typewriter Items of a widget sprite: one 'reveal' Item per line, `delay` s after `start` (the window's fade-in), then line_step apart.
    (cx, cy) = the centre of the placed widget sprite. A sprite without info['lines'] -> []. Never raises."""
    out = []
    try:
        lines = sp.info.get("lines") or []
        step, dur = float(sp.info.get("line_step", 0.35)), float(sp.info.get("line_dur", 0.4))
        last = max(start, end - 0.1)
        for i, (ls, x, y) in enumerate(lines):
            t0 = min(start + delay + i * step, last)
            out.append(Item(ls, t0, end, cx - sp.width / 2.0 + x + ls.width / 2.0, cy - sp.height / 2.0 + y + ls.height / 2.0, "reveal", dur, out=True))
    except Exception as e:
        t4_warn("code_window: typewriter lines could not be built (%s: %s)." % (type(e).__name__, e))
    return out


# ---- questions --------------------------------------------------------------------------------------------------------------
def t4_ask_code_window():
    """Question group of the widget (called by t4_ask_scenes) -> spec dict. Font / lang / numbers: edit the job file."""
    d = T4_CODE_WINDOW
    out = {"file": ask("File name shown in the tab (.py / .js / .html pick the icon and colours)", default=d["file"], key="t4_cw_file")}
    code = ask("Code (Enter = the demo snippet; write \\n between lines)", key="t4_cw_code", allow_empty=True) or ""
    if code.strip():
        out["code"] = code.replace("\\n", "\n")
    out["reveal"] = ["none", "typewriter"][ask_choice("Code appears", ["All at once", "Line by line (typewriter)"], default=1, key="t4_cw_reveal") - 1]
    return out


register_widget("code_window", t4_code_window, ask=t4_ask_code_window, slot="code")
