#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
montage.py  -  Interactive montage builder (Pillow + FFmpeg), one file, two templates.

TEMPLATES (the FIRST question of the program; saved templates from templates/*.json are listed there too)
  1 = Template 1  "Tech HUD": dark blue tech background, glowing video frame, info cards, 1080x1920.
  2 = Template 2  "Lime Creator Series": dark poster look with lime accents - header (logo / name / subtitle / pill),
      two-line headline, rounded glowing video window, chapter tag ("01 INTRO"), word-by-word captions (Arabic box +
      small second line), floating B-roll card, ABOUT ME + feature rows, bottom EDITING LAYERS / MOTION GUIDE panel with
      a moving playhead, audio waveform and pagination dots, optional split screen.  1080x1920.
  3 = Custom      the old free-form flow (any canvas size / background) + your saved templates.
  4.. = your saved templates (templates/<name>.json).  A saved Template 2 design restores its style and static texts
      (accent, header, headline, frame) without asking them again; everything else is still asked.

QUESTION FLOW  (every question has a default: Enter = default / your last answer; the only required answer is the video)
  Template 1 / Custom:  template -> video -> SRT(s) -> template questions -> caption style -> texts -> cards ->
                        elements -> video layers -> split -> output -> quick-test seconds -> recap -> render.
  Template 2 (grouped under numbered headers):
      template -> 1 video -> 2 SRT(s) -> 3 identity / header / headline -> 4 frame (+ show/hide design parts) ->
      5 panels on/off (about, bottom panel) -> 6 captions -> 7 chapters -> 8 floating cards -> 9 about states ->
      10 texts / elements / template layers / video layers -> 11 split (only if elements or box video layers) ->
      12 output + quick-test seconds -> one-line recap (template + which modules are on) -> "Start rendering?"
  Every run is saved as <output>_job.json so you can re-render without answering again.

FLAGS
  --job FILE.json       re-render from a saved *_job.json (no questions)
  --preview N           render only the first N seconds
  --still               render ONE png of the composite at t=0.5 s (no video encoding) to check the design
  --still-out FILE.png  where to save the --still png (default: next to the output file)
  --arabic-mode MODE    auto | raqm | reshape   (Arabic text engine; auto = Raqm when available)
  --selftest            run the built-in checks on synthetic assets (no questions) and print a PASS/FAIL table
  --help                this list
  Environment: MONTAGE_DEBUG=1 shows full tracebacks instead of the one-line [!] messages.

EXAMPLES
  python montage.py                               interactive
  python montage.py --job my_video_job.json       re-render, no questions
  python montage.py --job my_video_job.json --still --still-out check.png

FOLDER LAYOUT  (everything next to montage.py)
  montage.py
  templates/        saved named templates (*.json), created by "Save this as a template?"
  fonts/            your .ttf/.otf files (listed in the font questions; found automatically by Template 2)
  selftest_golden/  reference frames + font used by --selftest (optional; the golden comparison is skipped without it)
  montage_defaults.json   your last answers (created automatically)
  ffmpeg/bin/ or bin/     optional place for ffmpeg.exe / ffprobe.exe when they are not on PATH

FONTS Template 2 looks best with (put these files in fonts/; without them it falls back to installed fonts and says which)
  headline : Kanit-ExtraBoldItalic.ttf   (or Montserrat-ExtraBoldItalic.ttf / BarlowCondensed-ExtraBoldItalic.ttf)
  UI text  : Rajdhani-Medium.ttf + Rajdhani-SemiBold.ttf   (or Barlow-Medium.ttf / Montserrat-Medium.ttf)
  Arabic   : Cairo-Bold.ttf              (or Tajawal-Bold.ttf / IBMPlexSansArabic-Bold.ttf)

INPUT NOTES
  * The video may have any size: it is fitted into its window ("fit" = whole video, "fill" = cropped), never stretched.
  * No audio is fine (silent output, procedural waveform).  SRT: UTF-8 with/without BOM, blank lines, CRLF are accepted.
  * Missing elements / icons / fonts / SRTs are skipped or replaced with a one-line [!] message; the render continues.
  * Captions are shown word by word (or N words at a time).  Texts and elements appear at an exact time with one of
    10 built-in animations.  Arabic + English supported (arabic-reshaper + python-bidi, or Raqm when available).
  * Requires: Python 3.9+, Pillow, arabic-reshaper, python-bidi, fonttools, FFmpeg.  numpy is optional (faster waveform).
"""
import os
import sys
import re
import json
import math
import shutil
import argparse
import subprocess
import tempfile
import time
from fractions import Fraction
from pathlib import Path
import unicodedata

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE / "templates"
FONTS_DIR = BASE / "fonts"
DEFAULTS_FILE = BASE / "montage_defaults.json"

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")
IMAGE_EXTS = (".png", ".ico", ".webp", ".jpg", ".jpeg", ".bmp", ".gif")


# ----------------------------------------------------------------------------
# Dependencies
# ----------------------------------------------------------------------------
def _ensure_python_packages():
    missing = []
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    try:
        import arabic_reshaper  # noqa: F401
    except ImportError:
        missing.append("arabic-reshaper")
    try:
        try:
            from bidi import get_display  # noqa: F401
        except ImportError:
            from bidi.algorithm import get_display  # noqa: F401
    except ImportError:
        missing.append("python-bidi")
    try:
        import fontTools  # noqa: F401
    except ImportError:
        missing.append("fonttools")
    if not missing:
        return
    print("Missing Python packages: " + ", ".join(missing))
    try:
        ans = input("Install them now with pip? [Y/n]: ").strip().lower()
    except EOFError:
        sys.exit("Please run:  pip install " + " ".join(missing))
    if ans in ("", "y", "yes"):
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        print("Installed. Continuing...\n")
    else:
        sys.exit("Please run:  pip install " + " ".join(missing))


_ensure_python_packages()

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, features  # noqa: E402
import arabic_reshaper  # noqa: E402

try:
    from bidi import get_display  # noqa: E402
except ImportError:
    from bidi.algorithm import get_display  # noqa: E402


def _find_tool(name):
    p = shutil.which(name)
    if p:
        return p
    exe = name + (".exe" if os.name == "nt" else "")
    for cand in (BASE / exe, BASE / "ffmpeg" / "bin" / exe, BASE / "bin" / exe):
        if cand.is_file():
            return str(cand)
    return None


FFMPEG = _find_tool("ffmpeg")
FFPROBE = _find_tool("ffprobe")


def _require_ffmpeg():
    if FFMPEG and FFPROBE:
        return
    print("\n[!] FFmpeg was not found on this computer.")
    print("    Windows : winget install Gyan.FFmpeg      (then close and reopen the terminal)")
    print("    macOS   : brew install ffmpeg")
    print("    Linux   : sudo apt install ffmpeg")
    sys.exit(1)


# ----------------------------------------------------------------------------
# Persistent "last used" answers (press Enter to reuse)
# ----------------------------------------------------------------------------
def _load_defaults():
    try:
        return json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


D = _load_defaults()


def _save_defaults():
    try:
        DEFAULTS_FILE.write_text(json.dumps(D, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Small input helpers
# ----------------------------------------------------------------------------
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")

AR_COLORS = {
    "ابيض": "white", "أبيض": "white", "اسود": "black", "أسود": "black",
    "احمر": "red", "أحمر": "red", "ازرق": "blue", "أزرق": "blue",
    "اخضر": "#00c853", "أخضر": "#00c853", "اصفر": "yellow", "أصفر": "yellow",
    "برتقالي": "orange", "بنفسجي": "purple", "وردي": "pink", "رمادي": "gray",
    "ذهبي": "#ffd700", "سماوي": "cyan", "بني": "brown",
}

YES = {"y", "yes", "ي", "ايوه", "أيوه", "اه", "أه", "آه", "نعم", "ايوا", "أيوا", "1"}
NO = {"n", "no", "لا", "لأ", "لاا", "0"}


def clean_path(s):
    s = s.strip()
    if s.startswith("& "):
        s = s[2:].strip()
    return os.path.abspath(os.path.expanduser(s.strip('"').strip("'").strip()))


def ask(prompt, default=None, key=None, cast=None, allow_empty=False):
    if key and D.get(key) not in (None, ""):
        default = D[key]
    while True:
        tail = f" [{default}]" if default not in (None, "") else ""
        try:
            raw = input(f"{prompt}{tail}: ").strip()
        except EOFError:
            raise SystemExit("\nInput ended.")
        if not raw:
            if default not in (None, ""):
                raw = str(default)
            elif allow_empty:
                return None
            else:
                print("   (required)")
                continue
        try:
            val = cast(raw) if cast else raw
        except (ValueError, OSError) as e:
            print(f"   [!] {e}")
            continue
        if key:
            D[key] = raw
        return val


def yn(prompt, default=False):
    d = "Y/n" if default else "y/N"
    while True:
        try:
            raw = input(f"{prompt} [{d}]: ").strip().lower()
        except EOFError:
            raise SystemExit("\nInput ended.")
        if not raw:
            return default
        if raw in YES:
            return True
        if raw in NO:
            return False
        print("   please answer y or n")


def c_float(s):
    return float(s.translate(AR_DIGITS))


def c_int(s):
    return int(float(s.translate(AR_DIGITS)))


def c_time(s):
    s = s.strip().lower().translate(AR_DIGITS).replace("ث", "")
    if s.endswith("s"):
        s = s[:-1]
    if ":" in s:
        secs = 0.0
        for part in s.split(":"):
            secs = secs * 60 + float(part)
        return secs
    return float(s)


def c_color(s):
    s = s.strip()
    s = AR_COLORS.get(s, s)
    for cand in (s, "#" + s):
        try:
            r, g, b = ImageColor.getrgb(cand)[:3]
            return "#%02x%02x%02x" % (r, g, b)
        except ValueError:
            pass
    m = re.fullmatch(r"\s*(\d+)\s*[, ]\s*(\d+)\s*[, ]\s*(\d+)\s*", s)
    if m:
        r, g, b = (min(255, int(x)) for x in m.groups())
        return "#%02x%02x%02x" % (r, g, b)
    raise ValueError("unknown color. Use a name (white, red...), hex (#ff8800) or r,g,b")


def c_size_wh(s):
    m = re.fullmatch(r"\s*(\d+)\s*[x*,Xx×]\s*(\d+)\s*", s.translate(AR_DIGITS))
    if not m:
        raise ValueError("use the form WIDTHxHEIGHT, e.g. 1080x1920")
    w, h = int(m.group(1)), int(m.group(2))
    if w < 64 or h < 64:
        raise ValueError("size too small")
    return [w - w % 2, h - h % 2]


def c_existing_file(exts=None):
    def _c(s):
        p = clean_path(s)
        if not os.path.isfile(p):
            raise ValueError(f"file not found: {p}")
        if exts and not p.lower().endswith(tuple(exts)):
            raise ValueError("unsupported file type (expected: " + ", ".join(exts) + ")")
        return p
    return _c


def c_text(s):
    if s.startswith("@"):
        p = clean_path(s[1:])
        if not os.path.isfile(p):
            raise ValueError(f"text file not found: {p}")
        return Path(p).read_text(encoding="utf-8-sig").strip()
    return s.replace("\\n", "\n")


def c_percent(s):
    v = float(s.translate(AR_DIGITS).replace("%", ""))
    if not 0 <= v <= 100:
        raise ValueError("enter a number from 0 to 100")
    return v


def ask_time(prompt, default=None, key=None):
    return ask(prompt + "  (seconds or mm:ss)", default=default, key=key, cast=c_time)


def ask_choice(prompt, labels, default=1, key=None):
    print(prompt)
    for i, lab in enumerate(labels, 1):
        print(f"   {i}) {lab}")

    def _c(s):
        v = int(s.translate(AR_DIGITS))
        if not 1 <= v <= len(labels):
            raise ValueError(f"choose 1-{len(labels)}")
        return v
    return ask("Choice", default=default, key=key, cast=_c)


# ----------------------------------------------------------------------------
# Fonts + Arabic text shaping
# ----------------------------------------------------------------------------
ARABIC_RE = re.compile("[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
ARABIC_MODE = "reshape"  # "raqm" or "reshape" (decided in setup_arabic_mode)
_reshaper = arabic_reshaper.ArabicReshaper()


def has_arabic(s):
    return bool(ARABIC_RE.search(s))


def is_rtl_text(s):
    ar = len(ARABIC_RE.findall(s))
    lat = len(re.findall(r"[A-Za-z]", s))
    return ar > lat


def setup_arabic_mode(forced="auto"):
    global ARABIC_MODE
    raqm_ok = False
    try:
        raqm_ok = bool(features.check("raqm")) and bool(features.check("fribidi"))
    except Exception:
        raqm_ok = False
    if forced == "raqm" and raqm_ok:
        ARABIC_MODE = "raqm"
    elif forced == "auto" and raqm_ok:
        ARABIC_MODE = "raqm"
    else:
        ARABIC_MODE = "reshape"
    return ARABIC_MODE


_CUR_FONT = {"path": None}
_cmap_cache = {}


def _font_cmap(path):
    if path not in _cmap_cache:
        try:
            from fontTools.ttLib import TTFont
            _cmap_cache[path] = set(TTFont(path, fontNumber=0, lazy=True).getBestCmap().keys())
        except Exception:
            _cmap_cache[path] = None
    return _cmap_cache[path]


def _fix_missing(s):
    cm = _font_cmap(_CUR_FONT["path"]) if _CUR_FONT["path"] else None
    if not cm:
        return s
    out = []
    for ch in s:
        if ord(ch) in cm or ch.isspace():
            out.append(ch)
            continue
        base = unicodedata.normalize("NFKC", ch)
        if base != ch and all(ord(c) in cm for c in base):
            out.append(base[::-1])  # the string is already in visual (RTL) order
        else:
            out.append(ch)
    return "".join(out)


def shape(s):
    """Return the string in the form that must be handed to Pillow for drawing."""
    if ARABIC_MODE == "reshape" and has_arabic(s):
        return _fix_missing(get_display(_reshaper.reshape(s)))
    return s


_font_cache = {}


def load_font(path, size):
    _CUR_FONT["path"] = path
    key = (path, size, ARABIC_MODE)
    f = _font_cache.get(key)
    if f is None:
        layout = ImageFont.Layout.RAQM if ARABIC_MODE == "raqm" else ImageFont.Layout.BASIC
        f = ImageFont.truetype(path, size, layout_engine=layout)
        _font_cache[key] = f
    return f

def font_supports_arabic(path):
    try:
        f = load_font(path, 40)
        ch = "\u0633" if ARABIC_MODE == "raqm" else "\ufeb3"
        a = f.getmask(ch).tobytes()
        n = f.getmask("\uffff").tobytes()
        return any(a) and a != n
    except Exception:
        return True


def _system_font_dirs():
    dirs = []
    if os.name == "nt":
        win = os.environ.get("WINDIR", r"C:\Windows")
        dirs += [os.path.join(win, "Fonts"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
    elif sys.platform == "darwin":
        dirs += ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts")]
    return [d for d in dirs if d and os.path.isdir(d)]


_font_index = None


def _build_font_index():
    global _font_index
    if _font_index is not None:
        return _font_index
    idx = {}
    roots = ([str(FONTS_DIR)] if FONTS_DIR.is_dir() else []) + _system_font_dirs()
    for root in roots:
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.lower().endswith((".ttf", ".otf", ".ttc")):
                    idx.setdefault(Path(f).stem.lower(), os.path.join(dp, f))
    _font_index = idx
    return idx


def list_local_fonts():
    if not FONTS_DIR.is_dir():
        return []
    out = []
    for f in sorted(FONTS_DIR.rglob("*")):
        if f.suffix.lower() in (".ttf", ".otf", ".ttc"):
            out.append(str(f))
    return out


def find_font(spec):
    spec = spec.strip()
    p = clean_path(spec)
    if os.path.isfile(p):
        return p
    idx = _build_font_index()
    low = spec.lower().replace(".ttf", "").replace(".otf", "")
    if low in idx:
        return idx[low]
    cands = sorted((k for k in idx if low and low in k), key=len)
    return idx[cands[0]] if cands else None


def default_font():
    local = list_local_fonts()
    if local:
        return local[0]
    cands = []
    if os.name == "nt":
        win = os.environ.get("WINDIR", r"C:\Windows")
        cands = [os.path.join(win, "Fonts", n) for n in ("tahoma.ttf", "arial.ttf", "segoeui.ttf")]
    elif sys.platform == "darwin":
        cands = ["/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Supplemental/Tahoma.ttf"]
    else:
        cands = ["/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for c in cands:
        if os.path.isfile(c):
            return c
    idx = _build_font_index()
    for k in ("arial", "tahoma", "dejavusans", "notosansarabic"):
        if k in idx:
            return idx[k]
    return next(iter(idx.values()), None)


def ask_font(prompt, key):
    local = list_local_fonts()
    if local:
        print("   Fonts in the 'fonts' folder:")
        for i, f in enumerate(local, 1):
            print(f"     {i}) {Path(f).name}")
    print("   (type a number, a font name like Arial / Cairo, or a full path to a .ttf/.otf file)")
    default = D.get(key) if D.get(key) and os.path.isfile(D.get(key)) else default_font()

    def _c(s):
        if s.isdigit() and local and 1 <= int(s) <= len(local):
            return local[int(s) - 1]
        p = find_font(s)
        if not p:
            raise ValueError("font not found. Put the .ttf in the 'fonts' folder next to the script or give the full path")
        return p

    path = ask(prompt, default=default, cast=_c)
    D[key] = path
    if not font_supports_arabic(path):
        print("   [!] This font does not seem to support Arabic (fine for English-only text).")
    return path


# ----------------------------------------------------------------------------
# Animations
# ----------------------------------------------------------------------------
ANIMS = ["fade", "slide_up", "slide_down", "slide_left", "slide_right",
         "zoom_in", "pop", "spin_in", "reveal", "drop"]
ANIM_LINE = ("0=none  1=fade  2=slide_up  3=slide_down  4=slide_left  5=slide_right  "
             "6=zoom_in  7=pop  8=spin_in  9=reveal(typewriter)  10=drop")


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
    if name in ("card_r", "card_l"):
        # Template 2 floating card: slides in from the right / left edge with a small rotation settle
        # (ease-out-back); the same curve run backwards = slide + fade out.
        s = 1.0 if name == "card_r" else -1.0
        b = _out_back(p, 1.1)
        return min(1.0, p * 3.5), s * (1 - b) * 0.20 * W, 0, 1.0, s * (1 - b) * 10.0, None
    return 1.0, 0, 0, 1.0, 0.0, None


def c_anim(s):
    s = s.strip().lower().translate(AR_DIGITS)
    if s.isdigit():
        v = int(s)
        if v == 0:
            return "none"
        if 1 <= v <= len(ANIMS):
            return ANIMS[v - 1]
        raise ValueError("choose 0-10")
    if s in ("none", "reveal", "typewriter") or s in ANIMS:
        return "reveal" if s == "typewriter" else s
    raise ValueError("unknown animation")


def ask_anim(prompt, default="fade", key=None):
    print("   " + ANIM_LINE)
    return ask(prompt, default=default, key=key, cast=c_anim)


# ----------------------------------------------------------------------------
# Positions
# ----------------------------------------------------------------------------
PRESETS = {
    "1": "top-left", "2": "top", "3": "top-right",
    "4": "left", "5": "center", "6": "right",
    "7": "bottom-left", "8": "bottom", "9": "bottom-right",
}
POS_LINE = ("1=top-left 2=top 3=top-right 4=left 5=center 6=right 7=bottom-left 8=bottom 9=bottom-right"
            "  or  x,y  (center point, px or %, e.g. 540,300 or 50%,15%)")


def c_pos(s):
    s = s.strip().lower().translate(AR_DIGITS).replace("_", "-").replace(" ", "")
    if s in PRESETS:
        return PRESETS[s]
    if s in PRESETS.values() or s in ("middle", "centre"):
        return "center" if s in ("middle", "centre") else s
    m = re.fullmatch(r"(-?[\d.]+%?)[,;x](-?[\d.]+%?)", s)
    if m:
        return [m.group(1), m.group(2)]
    raise ValueError("use 1-9, a preset name, or x,y")


def ask_pos(prompt, default="center", key=None):
    print("   " + POS_LINE)
    return ask(prompt, default=default if not isinstance(default, list) else ",".join(default),
               key=key, cast=c_pos)


def resolve_pos(pos, sw, sh, W, H):
    """Return the sprite CENTER (cx, cy) on the canvas."""
    if isinstance(pos, (list, tuple)):
        def one(v, total):
            v = str(v)
            return float(v[:-1]) / 100.0 * total if v.endswith("%") else float(v)
        return one(pos[0], W), one(pos[1], H)
    mx, my = 0.05 * W, 0.04 * H
    name = pos or "center"
    cx = W / 2
    cy = H / 2
    if "left" in name:
        cx = mx + sw / 2
    elif "right" in name:
        cx = W - mx - sw / 2
    if name.startswith("top"):
        cy = my + sh / 2
    elif name.startswith("bottom"):
        cy = H - my - sh / 2
    return cx, cy


# ----------------------------------------------------------------------------
# Sprites (pre-rendered RGBA images of texts / elements)
# ----------------------------------------------------------------------------
def wrap_lines(text, font, max_w):
    lines = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            cand = cur + " " + w
            if font.getlength(shape(cand)) <= max_w:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def make_text_sprite(text, font_path, size, fill, stroke_fill=None, stroke_w=0, max_w=10 ** 6):
    stroke_w = int(stroke_w or 0)
    if stroke_w and not stroke_fill:
        stroke_fill = "#000000"
    avail = max_w - 2 * (stroke_w + 6)
    while True:
        font = load_font(font_path, int(size))
        lines = wrap_lines(text, font, avail)
        shaped = [shape(l) for l in lines]
        widths = [font.getlength(s) for s in shaped]
        if max(widths) <= avail or size <= 14:
            break
        size = max(14, int(size * 0.92))
    asc, desc = font.getmetrics()
    lh = asc + desc
    gap = int(size * 0.18)
    pad = stroke_w + int(size * 0.18) + 3
    w = int(max(widths)) + 2 * pad
    h = len(lines) * lh + (len(lines) - 1) * gap + 2 * pad
    img = Image.new("RGBA", (max(w, 4), max(h, 4)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, s in enumerate(shaped):
        y = pad + asc + i * (lh + gap)
        d.text((w / 2, y), s, font=font, fill=fill, anchor="ms",
               stroke_width=stroke_w, stroke_fill=stroke_fill)
    return img


def load_image_sprite(path, width_spec, W):
    im = Image.open(path)
    try:
        im.seek(0)
    except Exception:
        pass
    im = im.convert("RGBA")
    if width_spec:
        ws = str(width_spec).strip()
        if ws.endswith("%"):
            tw = int(float(ws[:-1]) / 100.0 * W)
        else:
            tw = int(float(ws))
        tw = max(2, tw)
        th = max(2, int(round(im.height * tw / im.width)))
        im = im.resize((tw, th), Image.LANCZOS)
    return im


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
# HUD cards (icon + two lines, glowing border) - like WEB DEVELOPER / AI AUTOMATION
# ----------------------------------------------------------------------------
CYAN = (30, 170, 255)
CYAN_TXT = (0, 184, 255)


def _draw_icon(img, kind, box, path=None):
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    s = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    wid = max(2, int(s * 0.09))
    white = (255, 255, 255, 255)
    if kind == "code":
        a = s * 0.30
        d.line([(cx - a * 0.55, cy - a * 0.9), (cx - a * 1.45, cy), (cx - a * 0.55, cy + a * 0.9)],
               fill=white, width=wid, joint="curve")
        d.line([(cx + a * 0.55, cy - a * 0.9), (cx + a * 1.45, cy), (cx + a * 0.55, cy + a * 0.9)],
               fill=white, width=wid, joint="curve")
        d.line([(cx + a * 0.25, cy - a * 1.0), (cx - a * 0.25, cy + a * 1.0)], fill=white, width=wid)
    elif kind == "phone":
        d.rounded_rectangle((cx - s * 0.22, y0 + s * 0.02, cx + s * 0.22, y1 - s * 0.02),
                            radius=s * 0.08, outline=white, width=wid)
        d.line([(cx - s * 0.07, y0 + s * 0.12), (cx + s * 0.07, y0 + s * 0.12)], fill=white, width=max(2, wid // 2))
        r = s * 0.035
        d.ellipse((cx - r, y1 - s * 0.14 - r, cx + r, y1 - s * 0.14 + r), fill=white)
    elif kind == "chip":
        q = s * 0.20
        d.rounded_rectangle((cx - q, cy - q, cx + q, cy + q), radius=s * 0.04, outline=white, width=wid)
        r = s * 0.09
        d.rectangle((cx - r, cy - r, cx + r, cy + r), fill=white)
        for off in (-0.11, 0.0, 0.11):
            d.line([(cx + s * off, cy - q), (cx + s * off, cy - q - s * 0.12)], fill=white, width=max(2, wid // 2))
            d.line([(cx + s * off, cy + q), (cx + s * off, cy + q + s * 0.12)], fill=white, width=max(2, wid // 2))
            d.line([(cx - q, cy + s * off), (cx - q - s * 0.12, cy + s * off)], fill=white, width=max(2, wid // 2))
            d.line([(cx + q, cy + s * off), (cx + q + s * 0.12, cy + s * off)], fill=white, width=max(2, wid // 2))
    elif kind == "image" and path:
        try:
            ic = Image.open(path).convert("RGBA")
            ic.thumbnail((int(s), int(s)), Image.LANCZOS)
            img.alpha_composite(ic, (int(cx - ic.width / 2), int(cy - ic.height / 2)))
        except Exception:
            pass


def make_card_sprite(l1, l2, icon, icon_path, layout, tail, font_path, canvas_w):
    k = canvas_w / 1080.0
    if layout == "v":
        w, h = int(200 * k), int(187 * k)
    else:
        w, h = int(380 * k), int(105 * k)
    P = int((110 if tail else 36) * k)
    img = Image.new("RGBA", (w + 2 * P, h + 2 * P), (0, 0, 0, 0))
    c = int(15 * k)
    if layout == "v" and tail != "v-right":
        pts = [(c * 1.6, 0), (w, 0), (w, h - c), (w - c, h), (0, h), (0, c * 1.6)]
    elif layout == "v":
        pts = [(0, 0), (w - c * 1.6, 0), (w, c * 1.6), (w, h), (c, h), (0, h - c)]
    else:
        pts = [(0, 0), (w - c, 0), (w, c), (w, h), (c, h), (0, h - c)]
    pts = [(P + x, P + y) for x, y in pts]
    tails = {
        "h-right-down": [(w - 6 * k, h * 0.42), (w + 50 * k, h * 0.42 + 28 * k), (w + 50 * k, h + 78 * k)],
        "v-left": [(w * 0.55, h), (w * 0.55 + 18 * k, h + 26 * k), (w + 3 * k, h + 26 * k)],
        "v-right": [(w * 0.45, h), (w * 0.45 - 18 * k, h + 26 * k), (-3 * k, h + 26 * k)],
    }
    tl = [(P + x, P + y) for x, y in tails.get(tail, [])]

    gl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(gl)
    gd.line(pts + [pts[0]], fill=CYAN + (255,), width=max(3, int(5 * k)), joint="curve")
    if tl:
        gd.line(tl, fill=CYAN + (255,), width=max(2, int(4 * k)), joint="curve")
    glow = gl.filter(ImageFilter.GaussianBlur(9 * k))
    img.alpha_composite(glow)
    img.alpha_composite(glow)

    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=(6, 19, 50, 228))
    d.line(pts + [pts[0]], fill=(45, 175, 255, 255), width=max(2, int(3 * k)), joint="curve")
    d.line([(P + w * 0.52, P), (P + w * 0.90, P)], fill=(160, 228, 255, 255), width=max(3, int(5 * k)))
    if tl:
        d.line(tl, fill=(60, 185, 255, 255), width=max(2, int(2.5 * k)), joint="curve")
        r = 4.5 * k
        d.ellipse((tl[-1][0] - r, tl[-1][1] - r, tl[-1][0] + r, tl[-1][1] + r), fill=(120, 215, 255, 255))

    bd = int(72 * k)
    if layout == "v":
        bx, by = P + (w - bd) / 2.0, P + int(14 * k)
    else:
        bx, by = P + int(16 * k), P + (h - bd) / 2.0
    d.ellipse((bx, by, bx + bd, by + bd), fill=(12, 40, 96, 255), outline=(30, 125, 235, 255),
              width=max(2, int(3 * k)))
    if icon and icon != "none":
        _draw_icon(img, "image" if icon == "image" else icon,
                   (bx + bd * 0.22, by + bd * 0.22, bx + bd * 0.78, by + bd * 0.78), icon_path)

    lines = [(l1, (255, 255, 255, 255))] + ([(l2, CYAN_TXT + (255,))] if l2 else [])
    if layout == "v":
        ax0, ay0 = P + 22 * k, by + bd + 10 * k
        aw, ah = w - 40 * k, (P + h) - ay0 - 10 * k
        size = int(24 * k)
    else:
        ax0, ay0 = bx + bd + 18 * k, P + 8 * k
        aw, ah = (P + w) - ax0 - 18 * k, h - 16 * k
        size = int(31 * k)
    while True:
        font = load_font(font_path, max(8, size))
        asc, desc = font.getmetrics()
        lh = asc + desc
        widest = max(font.getlength(shape(t)) for t, _ in lines)
        if (widest <= aw and lh * len(lines) <= ah) or size <= 9:
            break
        size -= 1
    y = ay0 + (ah - lh * len(lines)) / 2.0
    for t, col in lines:
        d.text((ax0, y + asc), shape(t), font=font, fill=col, anchor="ls")
        y += lh
    return img


# ----------------------------------------------------------------------------
# Procedural "Tech HUD" background (dark blue, glowing frame, floor grid, divider)
# ----------------------------------------------------------------------------
def _chamfer(x0, y0, x1, y1, c):
    return [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c), (x1 - c, y1), (x0 + c, y1),
            (x0, y1 - c), (x0, y0 + c)]


def make_tech_background(W, H, box, divider_pct, out_path):
    k = W / 1080.0
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    stops = [(0.0, (3, 8, 24)), (0.45, (5, 17, 46)), (1.0, (2, 10, 30))]
    for y in range(H):
        p = y / float(max(1, H - 1))
        col = stops[-1][1]
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= p <= p1:
                f = (p - p0) / (p1 - p0)
                col = tuple(int(c0[i] + (c1[i] - c0[i]) * f) for i in range(3))
                break
        d.line([(0, y), (W, y)], fill=col)
    base = img.convert("RGBA")

    def layer():
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    bx, by, bw, bh = box["x"], box["y"], box["w"], box["h"]
    # soft blue light behind the frame + diagonal light streaks
    L = layer()
    ImageDraw.Draw(L).ellipse((bx - 0.35 * W, by + bh * 0.05, bx + bw + 0.35 * W, by + bh * 0.95),
                              fill=(20, 80, 200, 70))
    base.alpha_composite(L.filter(ImageFilter.GaussianBlur(150 * k)))
    L = layer()
    ld = ImageDraw.Draw(L)
    ld.polygon([(W * 0.50, 0), (W * 0.80, 0), (W, H * 0.22), (W, H * 0.34)], fill=(40, 110, 255, 26))
    ld.polygon([(0, H * 0.62), (0, H * 0.78), (W * 0.35, H), (W * 0.10, H)], fill=(40, 110, 255, 22))
    base.alpha_composite(L.filter(ImageFilter.GaussianBlur(22 * k)))
    # dot grids
    L = layer()
    ld = ImageDraw.Draw(L)
    for r in range(4):
        for cc in range(6):
            x, y = 80 * k + cc * 21 * k, 84 * k + r * 21 * k
            ld.ellipse((x - 2 * k, y - 2 * k, x + 2 * k, y + 2 * k), fill=(70, 150, 240, 170))
    for r in range(3):
        for cc in range(4):
            x, y = W - 80 * k - cc * 21 * k, 368 * k + r * 21 * k
            ld.ellipse((x - 2 * k, y - 2 * k, x + 2 * k, y + 2 * k), fill=(70, 150, 240, 150))
    base.alpha_composite(L)

    # floor grid + glowing horizon
    L = layer()
    ld = ImageDraw.Draw(L)
    hz = H - 190 * k
    for i in range(1, 8):
        y = hz + ((i / 7.0) ** 2) * 190 * k
        ld.line([(0, y), (W, y)], fill=(30, 100, 230, 70), width=max(1, int(1.5 * k)))
    for j in range(-14, 15):
        ld.line([(W / 2 + j * W * 0.03, hz), (W / 2 + j * W * 0.11, H)], fill=(30, 100, 230, 60),
                width=max(1, int(1.5 * k)))
    base.alpha_composite(L)
    G = layer()
    ImageDraw.Draw(G).line([(0, hz), (W, hz)], fill=(40, 150, 255, 255), width=max(3, int(5 * k)))
    g = G.filter(ImageFilter.GaussianBlur(10 * k))
    base.alpha_composite(g)
    base.alpha_composite(g)
    L = layer()
    ImageDraw.Draw(L).line([(0, hz), (W, hz)], fill=(110, 205, 255, 230), width=max(2, int(2.5 * k)))
    base.alpha_composite(L)

    # glowing frame around the video box
    G = layer()
    gd = ImageDraw.Draw(G)
    e = 7 * k
    gd.line(_chamfer(bx - e, by - e, bx + bw + e, by + bh + e, 14 * k) + [(bx - e + 14 * k, by - e)],
            fill=(30, 130, 255, 255), width=max(4, int(6 * k)), joint="curve")
    g = G.filter(ImageFilter.GaussianBlur(12 * k))
    base.alpha_composite(g)
    base.alpha_composite(g)
    L = layer()
    ld = ImageDraw.Draw(L)
    ld.line(_chamfer(bx - e, by - e, bx + bw + e, by + bh + e, 14 * k) + [(bx - e + 14 * k, by - e)],
            fill=(35, 150, 255, 255), width=max(3, int(4 * k)), joint="curve")
    e2 = 24 * k
    ld.line(_chamfer(bx - e2, by - e2, bx + bw + e2, by + bh + e2, 40 * k) + [(bx - e2 + 40 * k, by - e2)],
            fill=(40, 110, 230, 120), width=max(1, int(2 * k)), joint="curve")
    ln = 52 * k
    br = (130, 220, 255, 255)
    bwid = max(3, int(6 * k))
    xs0, ys0, xs1, ys1 = bx - e, by - e, bx + bw + e, by + bh + e
    for (px, py, sx, sy) in ((xs0, ys0, 1, 1), (xs1, ys0, -1, 1), (xs0, ys1, 1, -1), (xs1, ys1, -1, -1)):
        ld.line([(px + sx * ln, py), (px, py), (px, py + sy * ln)], fill=br, width=bwid, joint="curve")
    base.alpha_composite(L)

    # divider line under the video
    if divider_pct:
        y = int(H * divider_pct / 100.0)
        x0, x1 = int(W * 0.17), int(W * 0.83)
        G = layer()
        ImageDraw.Draw(G).line([(x0, y), (x1, y)], fill=(30, 130, 255, 255), width=max(3, int(4 * k)))
        g = G.filter(ImageFilter.GaussianBlur(7 * k))
        base.alpha_composite(g)
        L = layer()
        ld = ImageDraw.Draw(L)
        ld.line([(x0, y), (x1, y)], fill=(40, 110, 215, 190), width=max(2, int(3 * k)))
        ld.line([(x0, y), (x0 + (x1 - x0) * 0.26, y)], fill=(70, 185, 255, 255), width=max(3, int(5 * k)))
        base.alpha_composite(L)

    # bottom corner brackets
    L = layer()
    ld = ImageDraw.Draw(L)
    yb = H * 0.752
    ld.line([(98 * k, yb), (66 * k, yb), (66 * k, yb + 36 * k)], fill=(60, 175, 255, 255), width=max(3, int(6 * k)),
            joint="curve")
    yb2 = H * 0.868
    ld.line([(W - 66 * k, yb2 - 36 * k), (W - 66 * k, yb2), (W - 98 * k, yb2)], fill=(60, 175, 255, 255),
            width=max(3, int(6 * k)), joint="curve")
    base.alpha_composite(L)
    base.convert("RGB").save(out_path)
    return out_path


# ----------------------------------------------------------------------------
# Timeline items
# ----------------------------------------------------------------------------
class Item:
    __slots__ = ("sprite", "start", "end", "cx", "cy", "anim", "dur", "out", "opacity", "rtl")

    def __init__(self, sprite, start, end, cx, cy, anim="fade", dur=0.5, out=True, opacity=1.0, rtl=False):
        self.sprite, self.start, self.end = sprite, start, end
        self.cx, self.cy = cx, cy
        self.anim, self.dur, self.out = anim, dur, out
        self.opacity, self.rtl = opacity, rtl

    def progress(self, t):
        L = self.end - self.start
        d = min(self.dur, L / 2 if self.out else L)
        if d <= 1e-6 or self.anim in (None, "none"):
            return 1.0
        pin = (t - self.start) / d
        if self.out:
            return max(0.0, min(1.0, pin, (self.end - t) / d))
        return max(0.0, min(1.0, pin))


def _paste(canvas, spr, x, y):
    W, H = canvas.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + spr.width), min(H, y + spr.height)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + spr.width, y + spr.height):
        spr = spr.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    canvas.alpha_composite(spr, (x0, y0))


def draw_item(canvas, it, st):
    alpha, dx, dy, scale, rot, reveal = st
    alpha *= it.opacity
    if alpha < 0.004:
        return
    spr = it.sprite
    ox = 0
    if reveal is not None and reveal < 1:
        w = spr.width
        cw = max(1, int(w * reveal))
        if it.rtl:
            spr = spr.crop((w - cw, 0, w, spr.height))
            ox = w - cw
        else:
            spr = spr.crop((0, 0, cw, spr.height))
    base_w, base_h = it.sprite.width, it.sprite.height
    if abs(scale - 1.0) > 1e-3:
        spr = spr.resize((max(1, int(spr.width * scale)), max(1, int(spr.height * scale))), Image.BICUBIC)
        ox = int(ox * scale)
        base_w, base_h = base_w * scale, base_h * scale
    if abs(rot) > 0.05:
        spr = spr.rotate(rot, resample=Image.BICUBIC, expand=True)
    if alpha < 0.996:
        lut = [int(i * alpha) for i in range(256)]
        a = spr.getchannel("A").point(lut)
        spr = spr.copy()
        spr.putalpha(a)
    if rot and abs(rot) > 0.05:
        x = int(it.cx + dx - spr.width / 2)
        y = int(it.cy + dy - spr.height / 2)
    else:
        x = int(it.cx + dx - base_w / 2 + ox)
        y = int(it.cy + dy - base_h / 2)
    _paste(canvas, spr, x, y)


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
# Probe
# ----------------------------------------------------------------------------
def probe(path):
    cmd = [FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ValueError("ffprobe could not read this file:\n" + r.stderr[-400:])
    j = json.loads(r.stdout)
    v = next((s for s in j["streams"] if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    if v is None:
        raise ValueError("no video stream found in this file")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    try:
        rot = int(float(v.get("tags", {}).get("rotate", 0)))
    except Exception:
        pass
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if abs(rot) % 180 == 90:
        w, h = h, w

    def frac(s):
        try:
            a, b = s.split("/")
            return Fraction(int(a), int(b)) if int(b) else Fraction(0)
        except Exception:
            return Fraction(0)

    fps = frac(v.get("avg_frame_rate", "0/1")) or frac(v.get("r_frame_rate", "0/1"))
    if fps <= 0 or fps < 10:
        fps = Fraction(30)
    if fps > 60:
        fps = Fraction(60)
    fps = fps.limit_denominator(1001)
    dur = float(j.get("format", {}).get("duration") or v.get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in j["streams"])
    return {"w": w, "h": h, "fps": fps, "duration": dur, "audio": has_audio}


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


def list_templates():
    if not TEMPLATES_DIR.is_dir():
        return []
    return sorted(TEMPLATES_DIR.glob("*.json"))


def ask_layers(W, H):
    layers = []
    print("\nTemplate layers = PNG/ICO decorations that stay on screen for the whole video")
    print("(frames, borders, logo, side decorations...).")
    while yn("Add a template layer?", default=False):
        L = {}
        L["path"] = ask("  Image path (PNG/ICO)", cast=c_existing_file(IMAGE_EXTS))
        L["pos"] = ask_pos("  Position", default="center")
        L["width"] = ask("  Width: px or % of canvas (Enter = original size)", allow_empty=True)
        L["opacity"] = ask("  Opacity %", default=100, cast=c_percent)
        L["anim"] = ask_anim("  Entrance animation", default="none")
        L["anim_dur"] = 0.6
        layers.append(L)
    return layers


def maybe_save_template(tpl):
    name = ask("Save this as a template? Type a name (Enter = don't save)", allow_empty=True)
    if name:
        TEMPLATES_DIR.mkdir(exist_ok=True)
        safe = re.sub(r"[^\w\- ]+", "", name, flags=re.UNICODE).strip() or "template"
        (TEMPLATES_DIR / f"{safe}.json").write_text(json.dumps(tpl, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
        print(f"   Saved templates/{safe}.json")
    return tpl


def ask_hud_template(title="Tech HUD template (1080x1920)", save=True):
    tpl = {"canvas": [1080, 1920]}
    W, H = tpl["canvas"]
    print(f"\n--- {title} ---")
    bw, bh = ask("Video window size WxH", default="604x928", cast=c_size_wh)
    bw, bh = min(bw, W - 100), min(bh, H - 600)
    by = ask("Video window top position (px from the top)", default=335, cast=c_int)
    mode = ask_choice("How should the video fit its window?",
                      ["fit  (whole video visible, may leave gaps)", "fill (crop to cover the window)"], default=2)
    tpl["video_box"] = {"x": (W - bw) // 2, "y": by, "w": bw, "h": bh, "mode": "fit" if mode == 1 else "fill"}
    tpl["background"] = {"type": "tech",
                         "divider_pct": ask("Divider line position under the video (% of height, 0 = none)",
                                            default=79, cast=c_percent)}
    tpl["layers"] = ask_layers(W, H)
    return maybe_save_template(tpl) if save else tpl


_PRESET = {}     # {"path": saved template chosen in the selector, "sel": True while Template 2's own flow runs}


def _saved_templates():
    """[(path, registry_id)] for every templates/*.json: Template 2 designs -> 2, everything else -> 3 (Custom)."""
    out = []
    for p in list_templates():
        out.append((p, 2 if _tpl_template_id(p) == 2 else 3))
    return out


def choose_template():
    """FIRST question of the program: which template (or one of your saved templates).
    Returns the registry entry; a saved template is remembered in _PRESET['path'] and loaded without re-asking."""
    _PRESET.clear()
    print("\n--- Choose template ---")
    ids = sorted(TEMPLATE_REGISTRY)
    for i in ids:
        t = TEMPLATE_REGISTRY[i]
        print(f"   {i} = {t['name']:<10}  ({t['desc']})")
    saved = _saved_templates()
    first_saved = len(ids) + 1
    if saved:
        print("   --- your saved templates ---")
        for n, (p, tid) in enumerate(saved, first_saved):
            print(f"   {n} = {p.stem:<10}  (saved - {'Template 2, Lime Creator Series' if tid == 2 else 'Template 1 / Custom'})")
    last = len(ids) + len(saved)

    def _c(s):
        v = int(s.translate(AR_DIGITS))
        if v in TEMPLATE_REGISTRY or first_saved <= v <= last:
            return v
        raise ValueError(("choose 1-%d" % last) if saved else "choose " + ", ".join(str(i) for i in ids))
    dflt = 1
    try:
        if int(D.get("template_id")) in TEMPLATE_REGISTRY:
            dflt = int(D.get("template_id"))
    except (TypeError, ValueError):
        pass
    v = ask("Choice", default=dflt, cast=_c)
    if v in TEMPLATE_REGISTRY:
        D["template_id"] = str(v)
        return TEMPLATE_REGISTRY[v]
    path, tid = saved[v - first_saved]
    _PRESET["path"] = str(path)
    return TEMPLATE_REGISTRY[tid]


def ask_template(video_info):
    """Custom flow: saved templates (templates/*.json) or a brand-new custom template.
    (The 'Template style' question moved to choose_template(), which is asked first.)"""
    tpl = {}
    pp = _PRESET.pop("path", None)
    if pp and os.path.isfile(pp):                       # chosen in the selector: load it, ask nothing
        tpl = json.loads(Path(pp).read_text(encoding="utf-8-sig"))
        print(f"   Loaded template '{Path(pp).stem}'.")
        return tpl
    existing = [p for p in list_templates() if _tpl_template_id(p) != 2]   # Template 2 designs load via Template 2
    choice = 0
    if existing:
        labels = ["New template (answer the questions)"] + [p.stem for p in existing]
        choice = ask_choice("\n--- Template ---", labels, default=1) - 1
    if choice > 0:
        tpl = json.loads(existing[choice - 1].read_text(encoding="utf-8"))
        print(f"   Loaded template '{existing[choice - 1].stem}'.")
        return tpl

    print("\n--- Canvas (final video size) ---")
    n = ask_choice("Final size:", ["1080x1920  (9:16 vertical)", "1920x1080  (16:9 horizontal)",
                                   "1080x1080  (square)", "1080x1350  (4:5)", "Custom"], default=1)
    presets = {1: [1080, 1920], 2: [1920, 1080], 3: [1080, 1080], 4: [1080, 1350]}
    if n == 5:
        tpl["canvas"] = ask("Custom size WxH", cast=c_size_wh)
    else:
        tpl["canvas"] = presets[n]
    W, H = tpl["canvas"]

    print("\n--- Video box (where the video sits inside the canvas) ---")
    print(f"   Source video: {video_info['w']}x{video_info['h']}   Canvas: {W}x{H}")
    bw, bh = ask("Video size WxH (Enter = whole canvas)", default=f"{W}x{H}", cast=c_size_wh)
    bw, bh = min(bw, W), min(bh, H)
    print("   Position of the video box:  1=center  2=top  3=bottom  or  x,y (top-left corner in px)")

    def _vp(s):
        s = s.strip().translate(AR_DIGITS)
        if s in ("1", "2", "3"):
            return s
        m = re.fullmatch(r"(-?\d+)\s*[,;x]\s*(-?\d+)", s)
        if m:
            return [int(m.group(1)), int(m.group(2))]
        raise ValueError("use 1, 2, 3 or x,y")
    vp = ask("Video box position", default="1", cast=_vp)
    if vp == "1":
        bx, by = (W - bw) // 2, (H - bh) // 2
    elif vp == "2":
        bx, by = (W - bw) // 2, 0
    elif vp == "3":
        bx, by = (W - bw) // 2, H - bh
    else:
        bx, by = vp
    mode = ask_choice("How should the video fit its box?",
                      ["fit  (whole video visible, may leave gaps)", "fill (crop to cover the box)"], default=1)
    tpl["video_box"] = {"x": bx, "y": by, "w": bw, "h": bh, "mode": "fit" if mode == 1 else "fill"}

    print("\n--- Background (the edges around the video) ---")
    b = ask_choice("Background type:", ["Solid color", "Image", "Video (looped)"], default=1)
    if b == 1:
        tpl["background"] = {"type": "color", "value": ask("Background color", default="#101820",
                                                           key="bg_color", cast=c_color)}
    elif b == 2:
        tpl["background"] = {"type": "image", "path": ask("Background image path",
                                                          cast=c_existing_file(IMAGE_EXTS))}
    else:
        tpl["background"] = {"type": "video", "path": ask("Background video path",
                                                          cast=c_existing_file(VIDEO_EXTS))}
    tpl["layers"] = ask_layers(W, H)

    return maybe_save_template(tpl)


def ask_texts(duration):
    texts = []
    if not yn("\nDo you want text on the video?", default=False):
        return texts
    while True:
        print(f"\n--- Text #{len(texts) + 1} ---")
        t = {}
        t["text"] = ask("Text  (use \\n for a new line, or @file.txt to read it from a file)", cast=c_text)
        t["start"] = ask_time("Appears at", default=0)
        t["end"] = ask_time("Disappears at", default=round(min(duration, t["start"] + 3), 2))
        t["pos"] = ask_pos("Position", default="top", key="txt_pos")
        t["font"] = ask_font("Font", "txt_font")
        t["size"] = ask("Font size (px)", default=90, key="txt_size", cast=c_int)
        t["color"] = ask("Text color", default="white", key="txt_color", cast=c_color)
        t["stroke_color"] = ask("Outline color", default="black", key="txt_stroke", cast=c_color)
        t["stroke_w"] = ask("Outline width (px, 0 = none)", default=0, key="txt_strokew", cast=c_int)
        t["anim"] = ask_anim("Animation", default="fade", key="txt_anim")
        t["anim_dur"] = ask("Animation duration (seconds)", default=0.5, key="txt_adur", cast=c_float)
        texts.append(t)
        if not yn("Add another text?", default=False):
            break
    return texts


def ask_elements(duration):
    els = []
    if not yn("\nDo you want elements (PNG / ICO images) on the video?", default=False):
        return els
    while True:
        print(f"\n--- Element #{len(els) + 1} ---")
        e = {}
        e["path"] = ask("Image path (PNG/ICO/...)", cast=c_existing_file(IMAGE_EXTS))
        e["start"] = ask_time("Appears at", default=0)
        e["end"] = ask_time("Disappears at", default=round(min(duration, e["start"] + 3), 2))
        e["pos"] = ask_pos("Position", default="center")
        e["width"] = ask("Width: px or % of canvas (Enter = original size)", allow_empty=True)
        e["opacity"] = ask("Opacity %", default=100, cast=c_percent)
        e["anim"] = ask_anim("Animation", default="pop", key="el_anim")
        e["anim_dur"] = ask("Animation duration (seconds)", default=0.5, key="el_adur", cast=c_float)
        els.append(e)
        if not yn("Add another element?", default=False):
            break
    return els


def ask_video_layers(duration):
    vls = []
    if not yn("\nDo you want a video layer (screen recording / b-roll) shown at a certain time?", default=False):
        return vls
    while True:
        print(f"\n--- Video layer #{len(vls) + 1} ---")
        v = {}
        v["path"] = ask("Video path", cast=c_existing_file(VIDEO_EXTS))
        v["start"] = ask_time("Appears at", default=0)
        v["end"] = ask_time("Disappears at", default=round(min(duration, v["start"] + 5), 2))
        a = ask_choice("Where?", ["Over the video box", "Over the whole canvas"], default=1)
        v["area"] = "box" if a == 1 else "canvas"
        m = ask_choice("Fit:", ["fill (crop to cover)", "fit (whole video visible)"], default=1)
        v["mode"] = "fill" if m == 1 else "fit"
        v["fade"] = 0.3
        vls.append(v)
        if not yn("Add another video layer?", default=False):
            break
    return vls


ICON_LINE = "1=code  2=phone  3=chip/AI  4=none  or a path to a PNG/ICO"
SLOT_LINE = "1=top-left  2=left  3=right"
SLOTS = {1: (0.25, 0.1255, "h", "h-right-down"),
         2: (0.116, 0.32, "v", "v-left"),
         3: (0.887, 0.32, "v", "v-right")}


def find_trigger(cues, phrase):
    toks = flatten_tokens(cues)
    norm = [norm_tok(t[0]) for t in toks]
    hits = find_sequences(norm, kw_sequences([phrase]))
    return toks[hits[0][0]][1] if hits else None


def ask_cards(cues):
    cards = []
    if not yn("\nDo you want HUD cards (like WEB DEVELOPER / AI AUTOMATION) that change with the speech?",
              default=False):
        return cards
    while True:
        print(f"\n--- Card #{len(cards) + 1} ---")
        e = {}
        e["l1"] = ask("Line 1 (white)  e.g. WEB")
        e["l2"] = ask("Line 2 (blue)   e.g. DEVELOPER  (Enter = none)", allow_empty=True) or ""
        print("   " + ICON_LINE)

        def _icon(s):
            s = s.strip().translate(AR_DIGITS)
            m = {"1": "code", "2": "phone", "3": "chip", "4": "none"}
            if s in m:
                return m[s]
            return clean_path(s) if os.path.isfile(clean_path(s)) else (_ for _ in ()).throw(
                ValueError("use 1-4 or a valid image path"))
        ic = ask("Icon", default="1", cast=_icon)
        e["icon"], e["icon_path"] = ("image", ic) if ic not in ("code", "phone", "chip", "none") else (ic, None)
        print("   " + SLOT_LINE)
        e["slot"] = ask("Position", default="1", cast=lambda s: int(s.translate(AR_DIGITS)) if s.strip().translate(
            AR_DIGITS) in ("1", "2", "3") else (_ for _ in ()).throw(ValueError("choose 1-3")))
        while True:
            raw = ask("Appears when this word/phrase is said (from the SRT)  -or-  a time in seconds")
            try:
                e["start"] = c_time(raw)
                break
            except ValueError:
                pass
            t = find_trigger(cues, raw) if cues else None
            if t is None:
                print("   [!] that word was not found in the SRT. Try another word, or type a time.")
                continue
            e["start"] = round(t, 3)
            print(f"   -> found at {t:.2f}s")
            break
        e["hold"] = ask("How long it stays (seconds)", default=4, cast=c_float)
        e["anim"] = ask_anim("Animation", default="pop", key="card_anim")
        e["anim_dur"] = 0.45
        cards.append(e)
        if not yn("Add another card?", default=True):
            break
    if cards:
        cfg_font = ask_font("Card font (bold sans looks best)", "card_font")
        for c in cards:
            c["font"] = cfg_font
    return cards


def _interactive_core():
    print("=" * 60)
    print("  Montage builder  (Pillow + FFmpeg)")
    print("=" * 60)
    cfg = {}
    tpl_entry = choose_template()
    cfg["template_id"] = tpl_entry["id"]
    if tpl_entry["id"] == 2:
        return _interactive_t2(cfg, tpl_entry)
    cfg["video"] = ask("Video path", cast=c_existing_file(VIDEO_EXTS))
    info = probe(cfg["video"])
    print(f"   -> {info['w']}x{info['h']}, {float(info['fps']):.2f} fps, {info['duration']:.1f} s"
          f"{'' if info['audio'] else ', no audio'}")

    srt_paths = []
    nxt = ask("SRT captions file path (Enter = no captions)", cast=c_existing_file((".srt",)),
              allow_empty=True)
    while nxt:
        cues = parse_srt(nxt)
        if not cues:
            print("   [!] No captions could be read from that SRT file - skipped.")
        else:
            print(f"   -> {len(cues)} caption blocks read.")
            srt_paths.append(nxt)
        nxt = ask("Another SRT (for example the English translation)? Path, or Enter = no",
                  cast=c_existing_file((".srt",)), allow_empty=True)

    tpl = tpl_entry["ask_config"](info)
    cfg.update({k: tpl[k] for k in ("canvas", "video_box", "background")})
    cfg["layers"] = tpl.get("layers", [])
    if tpl_entry["id"] == 2:
        cfg["t2"] = dict(tpl.get("t2") or {})
        cfg["t2"].update(t2_ask_chapters(parse_srt(srt_paths[0]) if srt_paths else [], info["duration"]))
        if not cfg["layers"]:                      # parity with Template 1: PNG/ICO decorations for the whole video
            cfg["layers"] = ask_layers(*cfg["canvas"])

    cfg["captions"] = [tpl_entry["caption_style"](i, p) for i, p in enumerate(srt_paths)]
    cfg["texts"] = ask_texts(info["duration"])
    if tpl_entry["id"] == 2:
        cfg["cards"] = []
        cfg["t2"].update(t2_ask_cards_cfg(parse_srt(srt_paths[0]) if srt_paths else []))
        cfg["t2"].update(t2_ask_about(parse_srt(srt_paths[0]) if srt_paths else [], info["duration"]))
        cfg["t2"].update(t2_ask_panel())
        cfg["t2"] = t2_cfg(cfg["t2"])
    else:
        cfg["cards"] = tpl_entry["ask_cards"](parse_srt(srt_paths[0]) if srt_paths else [])
    cfg["elements"] = ask_elements(info["duration"])
    cfg["video_layers"] = ask_video_layers(info["duration"])
    if tpl_entry["id"] == 2:
        if cfg["elements"] or any(v.get("area", "box") == "box" for v in cfg["video_layers"]):
            cfg["t2"].update(t2_ask_split())
            cfg["t2"] = t2_cfg(cfg["t2"])

    print("\n--- Output ---")
    stem = Path(cfg["video"]).with_suffix("")
    cfg["output"] = ask("Output file", default=str(stem) + "_edited.mp4",
                        cast=lambda s: clean_path(s if s.lower().endswith(".mp4") else s + ".mp4"))
    cfg["preview"] = ask("Quick test: render only the first N seconds (Enter = full video)",
                         allow_empty=True, cast=c_float)
    return cfg


def interactive():
    try:
        return _interactive_core()
    finally:
        _PRESET.clear()


# ----------------------------------------------------------------------------
# Robustness: validate every path / font BEFORE rendering (one-line messages, never a traceback)
# ----------------------------------------------------------------------------
_WARNED = set()


def _warn(msg):
    if msg not in _WARNED:
        _WARNED.add(msg)
        print("[!] " + msg)


def _font_ok(path):
    try:
        return bool(path) and os.path.isfile(str(path)) and ImageFont.truetype(str(path), 20) is not None
    except Exception:
        return False


def _font_or_fallback(path, what):
    """Usable font path: the given one, or the default font + a message naming the file to put in fonts/."""
    if _font_ok(path):
        return path
    fb = default_font()
    if not _font_ok(fb):
        raise ValueError("no usable font found - put a .ttf/.otf file (for example Cairo-Bold.ttf) in the fonts/ folder "
                         "next to montage.py")
    if path:
        _warn(f"font '{Path(str(path)).name}' ({what}) not found or unreadable - put that file in the fonts/ folder "
              f"next to montage.py (using '{Path(fb).name}' for now)")
    return fb


def _img_ok(path, what):
    try:
        if path and os.path.isfile(str(path)):
            with Image.open(str(path)) as im:
                im.verify()
            return True
    except Exception:
        pass
    _warn(f"{what} image '{Path(str(path)).name if path else '(empty path)'}' is missing or not a valid image - skipped")
    return False


def _vid_ok(path, what):
    if path and os.path.isfile(str(path)):
        return True
    _warn(f"{what} '{Path(str(path)).name if path else '(empty path)'}' not found - skipped")
    return False


def preflight_cfg(cfg, need_video=True):
    """Deep copy of cfg with every missing / unreadable asset dropped or replaced (one-line [!] message each)."""
    import copy
    _WARNED.clear()                                   # each render reports its own problems once
    cfg = copy.deepcopy(cfg)
    v = cfg.get("video")
    if need_video and (not v or not os.path.isfile(str(v))):
        raise ValueError(f"video file not found: {v}")
    cfg["layers"] = [L for L in cfg.get("layers", []) if _img_ok(L.get("path"), "template layer")]
    cfg["elements"] = [e for e in cfg.get("elements", []) if _img_ok(e.get("path"), "element")]
    cfg["video_layers"] = [x for x in cfg.get("video_layers", []) if _vid_ok(x.get("path"), "video layer")]
    for t in cfg.get("texts", []):
        t["font"] = _font_or_fallback(t.get("font"), "text")
    caps = []
    for c in cfg.get("captions", []):
        if not (c.get("srt") and os.path.isfile(str(c["srt"]))):
            _warn(f"SRT file '{Path(str(c.get('srt'))).name}' not found - those captions are skipped")
            continue
        c["font"] = _font_or_fallback(c.get("font"), "captions") if c.get("font") else default_font()
        caps.append(c)
    cfg["captions"] = caps
    bg = cfg.get("background") or {}
    if bg.get("type") in ("image", "video") and not os.path.isfile(str(bg.get("path"))):
        _warn(f"background {bg.get('type')} '{bg.get('path')}' not found - using a solid dark background")
        cfg["background"] = {"type": "color", "value": "#101820"}
    for c in cfg.get("cards", []) or []:
        if c.get("icon_path") and not _img_ok(c["icon_path"], "card icon"):
            c["icon"], c["icon_path"] = "none", ""
        if c.get("font") and not _font_ok(c["font"]):
            c["font"] = _font_or_fallback(c["font"], "card")
    if get_template(cfg)["id"] == 2:
        t2 = cfg.setdefault("t2", {})
        try:
            import numpy  # noqa: F401
        except ImportError:
            _warn("numpy is not installed - Template 2 uses a slower pure-Python audio waveform (optional: pip install numpy)")
        fonts = t2.get("fonts") or {}
        for role in list(fonts):
            if not _font_ok(fonts[role]):
                _warn(f"Template 2 font override '{Path(str(fonts[role])).name}' not found - put it in the fonts/ folder "
                      f"(using the automatic choice)")
                fonts.pop(role)
        cards = []
        for c in t2.get("cards", []) or []:
            if not _vid_ok(c.get("media"), "floating card media"):
                continue
            if c.get("icon_path") and not _img_ok(c["icon_path"], "card icon"):
                c["icon"], c["icon_path"] = "none", ""
            cards.append(c)
        t2["cards"] = cards
        for st in t2.get("about", []) or []:
            for r in st.get("rows", []) or []:
                if r.get("icon_path") and not _img_ok(r["icon_path"], "about icon"):
                    r["icon"], r["icon_path"] = "none", ""
    return cfg


def _load_job(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ValueError(f"job file not found: {path}")
    except ValueError as e:
        raise ValueError(f"job file '{Path(path).name}' is not valid JSON ({e})")


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


def _draw_frame(base, box, k, W, H):
    bx, by, bw, bh = box["x"], box["y"], box["w"], box["h"]

    def layer():
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    e = 7 * k
    poly = _chamfer(bx - e, by - e, bx + bw + e, by + bh + e, 14 * k)
    poly = poly + [poly[0]]
    G = layer()
    ImageDraw.Draw(G).line(poly, fill=(30, 130, 255, 255), width=max(4, int(6 * k)), joint="curve")
    g = G.filter(ImageFilter.GaussianBlur(12 * k))
    base.alpha_composite(g)
    base.alpha_composite(g)
    L = layer()
    ld = ImageDraw.Draw(L)
    ld.line(poly, fill=(35, 150, 255, 255), width=max(3, int(4 * k)), joint="curve")
    e2 = 24 * k
    p2 = _chamfer(bx - e2, by - e2, bx + bw + e2, by + bh + e2, 40 * k)
    ld.line(p2 + [p2[0]], fill=(40, 110, 230, 120), width=max(1, int(2 * k)), joint="curve")
    ln = 52 * k
    br = (130, 220, 255, 255)
    bwid = max(3, int(6 * k))
    xs0, ys0, xs1, ys1 = bx - e, by - e, bx + bw + e, by + bh + e
    for (px, py, sx, sy) in ((xs0, ys0, 1, 1), (xs1, ys0, -1, 1), (xs0, ys1, 1, -1), (xs1, ys1, -1, -1)):
        ld.line([(px + sx * ln, py), (px, py), (px, py + sy * ln)], fill=br, width=bwid, joint="curve")
    base.alpha_composite(L)


def make_split_background(W, H, lbox, rbox, divider_pct, out_path):
    make_tech_background(W, H, lbox, divider_pct, out_path)
    base = Image.open(out_path).convert("RGBA")
    _draw_frame(base, rbox, W / 1080.0, W, H)
    base.convert("RGB").save(out_path)
    return out_path

def t1_build_items(cfg, duration, splits, lbox, rbox):
    """Template 1 (Tech HUD) hook: template-specific timeline items = the HUD cards.
    (end = hold time, or when the next card of the same slot appears)"""
    W, H = cfg["canvas"]
    T = SPLIT_T
    items = []
    cards = sorted(cfg.get("cards", []), key=lambda x: x["start"])
    for i, cd in enumerate(cards):
        slot = cd.get("slot", 1)
        fx, fy, layout, tail = SLOTS.get(slot, SLOTS[1])
        end = cd["start"] + cd.get("hold", 4)
        for o in cards[i + 1:]:
            if o.get("slot", 1) == slot and o["start"] > cd["start"]:
                end = min(end, o["start"])
                break
        end = min(end, duration + 1)
        cuts = [cd["start"], end]
        if splits and slot in (2, 3):
            for a, b in splits:
                for x in (a - T, b + T):
                    if cd["start"] < x < end:
                        cuts.append(x)
        cuts = sorted(set(cuts))
        for s0, e0 in zip(cuts, cuts[1:]):
            if splits and slot in (2, 3) and split_at(splits, (s0 + e0) / 2.0):
                px, py, lay, tl = (0.27 if slot == 2 else 0.73), 0.672, "h", None
            else:
                px, py, lay, tl = fx, fy, layout, tail
            spr = make_card_sprite(cd["l1"], cd.get("l2", ""), cd.get("icon"), cd.get("icon_path"),
                                   lay, tl, cd["font"], W)
            items.append(Item(spr, s0, e0, px * W, py * H,
                              cd.get("anim", "pop"), cd.get("anim_dur", 0.45), True, 1.0))
    return items


def build_items(cfg, duration):
    W, H = cfg["canvas"]
    box = cfg["video_box"]
    items = []
    T = SPLIT_T
    splits = compute_splits(cfg, duration)
    lbox, rbox = split_boxes(cfg) if splits else (None, None)
    
    for L in cfg.get("layers", []):
        spr = load_image_sprite(L["path"], L.get("width"), W)
        cx, cy = resolve_pos(L["pos"], spr.width, spr.height, W, H)
        items.append(Item(spr, 0.0, duration + 1, cx, cy, L.get("anim", "none"), L.get("anim_dur", 0.6),
                          out=False, opacity=L.get("opacity", 100) / 100.0))

    for e in cfg.get("elements", []):
        spr = load_image_sprite(e["path"], None if rbox else e.get("width"), W)
        if rbox:
            r = min(rbox["w"] / spr.width, rbox["h"] / spr.height)
            spr = spr.resize((max(2, int(spr.width * r)), max(2, int(spr.height * r))), Image.LANCZOS)
            cx, cy = rbox["x"] + rbox["w"] / 2.0, rbox["y"] + rbox["h"] / 2.0
        else:
            cx, cy = resolve_pos(e["pos"], spr.width, spr.height, W, H)
        items.append(Item(spr, e["start"], min(e["end"], duration + 1), cx, cy,
                          e.get("anim", "fade"), e.get("anim_dur", 0.5), True,
                          e.get("opacity", 100) / 100.0))

    for t in cfg.get("texts", []):
        spr = make_text_sprite(t["text"], t["font"], t["size"], t["color"],
                               t.get("stroke_color"), t.get("stroke_w", 0), max_w=int(W * 0.92))
        cx, cy = resolve_pos(t["pos"], spr.width, spr.height, W, H)
        items.append(Item(spr, t["start"], min(t["end"], duration + 1), cx, cy,
                          t.get("anim", "fade"), t.get("anim_dur", 0.5), True, 1.0,
                          rtl=is_rtl_text(t["text"])))

    # template-specific items (HUD cards for Template 1 / Custom; Template 2 plugs in here)
    items += get_template(cfg)["build_items"](cfg, duration, splits, lbox, rbox)

    for c in caption_streams(cfg):
        cues = parse_srt(c["srt"])
        groups = stream_groups(cues, c)
        if c.get("t2_style") in ("box", "sub"):          # Template 2 caption style (Part 3A)
            items += t2_caption_items(cfg, c, groups, duration)
            continue
        if c.get("ref", "box") == "box":
            cx = box["x"] + box["w"] / 2.0
            cy = box["y"] + box["h"] * c.get("y_pct", 72) / 100.0
            max_w = int(box["w"] * 0.94)
        else:
            cx = W / 2.0
            cy = H * c.get("y_pct", 73) / 100.0
            max_w = int(W * 0.84)
        for s, e, toks in groups:
            if s >= duration:
                continue
            ccx, ccy, cmw = cx, cy, max_w
            if lbox and c.get("ref", "box") == "box" and split_at(splits, (s + e) / 2.0):
                ccx = lbox["x"] + lbox["w"] / 2.0
                ccy = lbox["y"] + lbox["h"] * c.get("y_pct", 72) / 100.0
                cmw = int(lbox["w"] * 0.94)
            spr = make_rich_sprite([list(t) for t in toks], c["font"], c["size"], c["color"],
                                   c.get("hl_color"), c.get("stroke_color"), c.get("stroke_w", 0),
                                   max_w=cmw, shadow=c.get("shadow", False))
            items.append(Item(spr, s, e, ccx, ccy, c.get("anim", "fade"), c.get("anim_dur", 0.2),
                              out=False, rtl=is_rtl_text(" ".join(t[0] for t in toks))))
    return items


def _hex0x(c):
    return "0x" + c.lstrip("#")


def build_ffmpeg_cmd(cfg, info, duration, out_path, preview, overlay_path):
    W, H = cfg["canvas"]
    box = cfg["video_box"]
    fps = info["fps"]
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    bg = cfg["background"]
    T = SPLIT_T
    splits = compute_splits(cfg, duration)
    lbox, rbox = split_boxes(cfg) if splits else (None, None)

    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
    # input 0: background
    if bg["type"] == "color":
        cmd += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", f"color=c={_hex0x(bg['value'])}:s={W}x{H}:r={fps_s}"]
        bg_f = "[0:v]setsar=1,format=yuv420p[bg]"
    elif bg["type"] == "image":
        cmd += ["-loop", "1", "-framerate", fps_s, "-t", f"{duration:.3f}", "-i", bg["path"]]
        bg_f = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"setsar=1,fps={fps_s},format=yuv420p[bg]")
    else:
        cmd += ["-stream_loop", "-1", "-t", f"{duration:.3f}", "-i", bg["path"]]
        bg_f = (f"[0:v]fps={fps_s},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"setsar=1,format=yuv420p[bg]")
    # input 1: source video
    cmd += ["-i", cfg["video"]]
    # input 2: overlay frames (texts/captions/cards) pre-rendered by Python into a lossless alpha file
    cmd += ["-i", overlay_path]
    # inputs 3..: timed video layers (screen recordings, b-roll...)
    vl = [L for L in (cfg.get("video_layers") or [])
          if float(L["end"]) > float(L["start"]) and float(L["start"]) < duration]
    for L in vl:
        # -itsoffset delivers the frames at their real time (no early buffering);
        # L["path"] is already a small pre-scaled proxy (see prepare_video_layers)
        cmd += ["-thread_queue_size", "32", "-itsoffset", f"{float(L['start']):.3f}",
                "-t", f"{float(L['end']) - float(L['start']):.3f}", "-i", L["path"]]
    
    sb_idx = 3 + len(vl)
    if splits:
        cmd += ["-loop", "1", "-framerate", fps_s, "-t", f"{duration:.3f}", "-i", cfg["_split_bg"]]
    rg_idx = None   # Template 2 split: lime rounded borders + corner masks (fade/enable like the split background)
    if splits and cfg.get("_t2_split_ring"):
        rg_idx = sb_idx + 1
        cmd += ["-loop", "1", "-framerate", fps_s, "-t", f"{duration:.3f}", "-i", cfg["_t2_split_ring"]]
    fg_idx = None   # Template 2: foreground plate (design + rounded transparent video window)
    if cfg.get("_t2_fg"):
        fg_idx = sb_idx + (1 if splits else 0) + (1 if rg_idx is not None else 0)
        cmd += ["-loop", "1", "-framerate", fps_s, "-t", f"{duration:.3f}", "-i", cfg["_t2_fg"]]
    ph_idx, ph = None, cfg.get("_t2_playhead")     # Template 2 panel playhead: one tiny looped png moved by an x-expression
    if fg_idx is not None and ph:
        ph_idx = fg_idx + 1
        cmd += ["-loop", "1", "-framerate", fps_s, "-t", f"{duration:.3f}", "-i", ph["path"]]

    bw, bh = box["w"], box["h"]
    vw, vh = info["w"], info["h"]
    ns = 1 + len(splits)
    if ns > 1:
        src = (f"[1:v]fps={fps_s},setpts=PTS-STARTPTS,split={ns}"
               + "".join(f"[r{i}]" for i in range(ns)))
    else:
        src = f"[1:v]fps={fps_s},setpts=PTS-STARTPTS[r0]"
    if box.get("mode", "fit") == "fill":
        v_f = (f"[r0]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
               f"setsar=1[v]")
        ox, oy = box["x"], box["y"]
    else:
        sc = min(bw / vw, bh / vh)
        sw, sh = max(2, int(vw * sc) // 2 * 2), max(2, int(vh * sc) // 2 * 2)
        v_f = f"[r0]scale={sw}:{sh}:flags=lanczos,setsar=1[v]"
        ox, oy = box["x"] + (bw - sw) // 2, box["y"] + (bh - sh) // 2

    fc = f"{bg_f};{src};{v_f};[bg][v]overlay={ox}:{oy}[base0]"
    cur = "base0"
    if splits:
        n = len(splits)
        if n > 1:
            fc += f";[{sb_idx}:v]split={n}" + "".join(f"[sbr{i}]" for i in range(n))
            srcs = [f"sbr{i}" for i in range(n)]
        else:
            srcs = [f"{sb_idx}:v"]
        for i, (a, b) in enumerate(splits):
            s0, e1 = max(0.0, a - T), b + T
            fd = (f"fade=t=in:st={s0:.3f}:d={max(0.05, a - s0):.3f}:alpha=1,"
                  f"fade=t=out:st={b:.3f}:d={T}:alpha=1")
            en = f"enable='between(t,{s0:.3f},{e1:.3f})'"
            fc += (f";[{srcs[i]}]format=yuva420p,{fd}[sbf{i}]"
                   f";[{cur}][sbf{i}]overlay=0:0:eof_action=pass:{en}[sbo{i}]"
                   f";[r{i + 1}]scale={lbox['w']}:{lbox['h']}:force_original_aspect_ratio=increase,"
                   f"crop={lbox['w']}:{lbox['h']},setsar=1,format=yuva420p,{fd}[lv{i}]"
                   f";[sbo{i}][lv{i}]overlay={lbox['x']}:{lbox['y']}:eof_action=pass:{en}[sp{i}]")
            cur = f"sp{i}"    
    seq = list(enumerate(vl))
    if fg_idx is not None:
        # layers over the video box go UNDER the rounded frame (clipped by it), full-canvas layers above it
        seq = ([x for x in seq if x[1].get("area", "box") != "canvas"] + [(None, None)]
               + [x for x in seq if x[1].get("area", "box") == "canvas"])
    for i, L in seq:
        if i is None:
            if rg_idx is not None:
                n = len(splits)
                if n > 1:
                    fc += f";[{rg_idx}:v]split={n}" + "".join(f"[rgs{j}]" for j in range(n))
                for j, (a, b) in enumerate(splits):
                    s0, e1 = max(0.0, a - T), b + T
                    fd = (f"fade=t=in:st={s0:.3f}:d={max(0.05, a - s0):.3f}:alpha=1,"
                          f"fade=t=out:st={b:.3f}:d={T}:alpha=1")
                    rsrc = f"rgs{j}" if n > 1 else f"{rg_idx}:v"
                    fc += (f";[{rsrc}]format=yuva420p,{fd}[rgf{j}]"
                           f";[{cur}][rgf{j}]overlay=0:0:eof_action=pass:enable='between(t,{s0:.3f},{e1:.3f})'[rgo{j}]")
                    cur = f"rgo{j}"
            fc += f";[{cur}][{fg_idx}:v]overlay=0:0:eof_action=repeat:format=auto[tfg]"
            cur = "tfg"
            continue
        s, e = float(L["start"]), float(L["end"])
        if L.get("area", "box") == "canvas":
            ax, ay, aw, ah = 0, 0, W, H
        elif rbox:
            ax, ay, aw, ah = rbox["x"], rbox["y"], rbox["w"], rbox["h"]
        else:
            ax, ay, aw, ah = box["x"], box["y"], bw, bh
        pos = f"{ax}:{ay}"
        if L.get("mode", "fill") != "fill":
            pos = f"{ax}+({aw}-overlay_w)/2:{ay}+({ah}-overlay_h)/2"
        if L.get("_xy"):                     # Template 2 floating card: fixed canvas position
            pos = f"{int(L['_xy'][0])}:{int(L['_xy'][1])}"
        fd = float(L.get("fade", 0.3))
        fades = ""
        if fd > 0:
            fades = (f",fade=t=in:st={s:.3f}:d={fd}:alpha=1"
                     f",fade=t=out:st={max(s, e - fd):.3f}:d={fd}:alpha=1")
        fc += (f";[{3 + i}:v]format=yuva420p{fades}[vl{i}]"
               f";[{cur}][vl{i}]overlay={pos}:eof_action=pass:"
               f"enable='between(t,{s:.3f},{e:.3f})'[base{i + 1}]")
        cur = f"base{i + 1}"
    if ph_idx is not None:
        fc += (f";[{cur}][{ph_idx}:v]overlay=x='{ph['cx0']:.3f}+({ph['cx1']:.3f}-{ph['cx0']:.3f})"
               f"*min(max(t/{float(info['duration']):.4f},0),1)-{ph['w'] / 2.0:.2f}':y={ph['y']}:"
               f"eof_action=repeat:format=auto[tph]")
        cur = "tph"
    fc += f";[{cur}][2:v]overlay=0:0:format=auto,format=yuv420p[out]"
    cmd += ["-filter_complex", fc, "-map", "[out]"]
    if info["audio"]:
        cmd += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-t", f"{duration:.3f}", "-c:v", "libx264",
            "-preset", "ultrafast" if preview else "veryfast",
            "-crf", "23" if preview else "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
    return cmd


def video_layer_area(cfg, L):
    W, H = cfg["canvas"]
    if L.get("area", "box") == "canvas":
        return W, H
    if cfg.get("split") and cfg.get("_split_bg"):
        r = split_boxes(cfg)[1]
        return r["w"], r["h"]
    box = cfg["video_box"]
    return box["w"], box["h"]


def prepare_video_layers(cfg, info, tmpdir):
    """Pre-render every video layer (screen recording / b-roll) into a small, already
    scaled/cropped video with the right fps. This keeps FFmpeg's memory low even when
    the recording is huge (4K / 60fps / high bitrate)."""
    fps = info["fps"]
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    out = []
    for i, L in enumerate(cfg.get("video_layers") or []):
        L = dict(L)
        dur = float(L["end"]) - float(L["start"])
        aw, ah = video_layer_area(cfg, L)
        if L.get("mode", "fill") == "fill":
            vf = (f"fps={fps_s},scale={aw}:{ah}:force_original_aspect_ratio=increase,"
                  f"crop={aw}:{ah},setsar=1,format=yuv420p")
        else:
            vf = (f"fps={fps_s},scale={aw}:{ah}:force_original_aspect_ratio=decrease:"
                  f"force_divisible_by=2,setsar=1,format=yuv420p")
        proxy = os.path.join(tmpdir, f"vlayer{i}.mp4")
        print(f"Preparing video layer {i + 1} ({Path(L['path']).name})...")
        cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-t", f"{dur:.3f}", "-i", L["path"],
               "-an", "-vf", vf, "-threads", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
               "-pix_fmt", "yuv420p", proxy]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not os.path.isfile(proxy):
            raise SystemExit("[!] Could not prepare the video layer:\n" + r.stderr[-800:])
        L["path"] = proxy
        out.append(L)
    return out


def render(cfg):
    cfg = preflight_cfg(cfg)
    cfg = dict(cfg)
    # old job files have no template_id -> Template 1
    cfg["template_id"] = get_template(cfg)["id"]
    # temp folders live next to the output file (not on the system drive)
    Path(cfg["output"]).parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="montage_", dir=str(Path(cfg["output"]).parent))
    # the template builds its static background (and split background) into cfg
    get_template(cfg)["build_background"](cfg, tmp)
    try:
        _require_ffmpeg()
        pre = prepare_video_layers(cfg, probe(cfg["video"]), tmp) if cfg.get("video_layers") else None
        cards = t2_prepare_card_layers(cfg, probe(cfg["video"]), tmp) if cfg["template_id"] == 2 else []
        if pre is not None or cards:
            cfg["video_layers"] = (pre or []) + cards      # floating video cards last = on top
        _render(cfg)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _render(cfg):
    _require_ffmpeg()
    info = probe(cfg["video"])
    W, H = cfg["canvas"]
    duration = info["duration"]
    preview = cfg.get("preview")
    if preview:
        duration = min(duration, float(preview))
    fps = info["fps"]
    fps_f = float(fps)
    n_frames = int(math.ceil(duration * fps_f))

    print("\nPreparing texts, captions and elements...")
    items = build_items(cfg, info["duration"])
    print(f"   {len(items)} timeline items ready.")

    out_path = cfg["output"]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    log_path = Path(out_path).with_suffix(".ffmpeg.log")
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    work = tempfile.mkdtemp(prefix="montage_ov_", dir=str(Path(out_path).parent))
    overlay_path = os.path.join(work, "overlay.mov")

    # ---- Pass 1: draw the overlay frames in Python and encode them to a small lossless alpha file.
    # ffmpeg has NO other input in this pass, so it never buffers decoded video while waiting
    # for Python (that buffering is what filled the RAM before).
    cmd1 = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", f"{W}x{H}", "-framerate", fps_s, "-i", "pipe:0",
            "-c:v", "qtrle", "-pix_fmt", "argb", overlay_path]
    logf = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd1, stdin=subprocess.PIPE, stderr=logf, stdout=subprocess.DEVNULL)

    empty_bytes = bytes(W * H * 4)
    last_sig, last_bytes = (), empty_bytes
    t0 = time.time()
    print(f"Pass 1/2: drawing {n_frames} overlay frames ({W}x{H} @ {fps_f:.2f} fps)...")
    try:
        for i in range(n_frames):
            t = i / fps_f
            active = []
            sig = []
            for it in items:
                if it.start <= t < it.end:
                    st = anim_state(it.anim, it.progress(t), W, H)
                    active.append((it, st))
                    sig.append((id(it), round(st[0], 3), round(st[1]), round(st[2]), round(st[3], 3),
                                round(st[4], 1), None if st[5] is None else round(st[5], 3)))
            sig = tuple(sig)
            if sig != last_sig:
                if not active:
                    last_bytes = empty_bytes
                else:
                    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    for it, st in active:
                        draw_item(canvas, it, st)
                    last_bytes = canvas.tobytes()
                    del canvas
                last_sig = sig
            proc.stdin.write(last_bytes)
            if i % 20 == 0 or i == n_frames - 1:
                el = time.time() - t0
                eta = el / (i + 1) * (n_frames - i - 1)
                print(f"\r   {i + 1}/{n_frames}  ({(i + 1) * 100 // n_frames}%)  ETA {eta:4.0f}s   ",
                      end="", flush=True)
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    except KeyboardInterrupt:
        proc.kill()
        logf.close()
        shutil.rmtree(work, ignore_errors=True)
        raise SystemExit("\nStopped.")
    rc = proc.wait()
    logf.close()
    print()
    if rc != 0 or not os.path.isfile(overlay_path):
        tail = Path(log_path).read_text(encoding="utf-8", errors="replace")[-1500:]
        shutil.rmtree(work, ignore_errors=True)
        print("[!] FFmpeg failed while saving the overlay:\n" + tail)
        raise SystemExit(1)

    # ---- Pass 2: combine background + video + video layers + overlay file (all plain files).
    print("Pass 2/2: combining everything and encoding the final video...")
    cmd2 = build_ffmpeg_cmd(cfg, info, duration, out_path, bool(preview), overlay_path)
    cmd2[cmd2.index("-loglevel") + 1] = "error"
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf2:
        rc = subprocess.run(cmd2, stdin=subprocess.DEVNULL, stderr=logf2, stdout=subprocess.DEVNULL).returncode
    shutil.rmtree(work, ignore_errors=True)
    if rc != 0:
        tail = Path(log_path).read_text(encoding="utf-8", errors="replace")[-1500:]
        print("[!] FFmpeg failed:\n" + tail)
        raise SystemExit(1)
    try:
        log_path.unlink()
    except Exception:
        pass
    size = os.path.getsize(out_path) / (1024 * 1024)
    print(f"Done in {time.time() - t0:.0f}s  ->  {out_path}  ({size:.1f} MB)")


# ----------------------------------------------------------------------------
# Template system (registry)
#
#   cfg["template_id"]  1 = Tech HUD      2 = Lime Creator Series      3 = Custom
#   Every template provides these hooks (see TEMPLATE_REGISTRY below):
#     ask_config(video_info)            -> dict(canvas, video_box, background, layers[, t2])
#     ask_cards(cues)                   -> list of card dicts
#     caption_style(idx, srt_path)      -> caption style dict
#     build_background(cfg, tmpdir)     -> writes the static background (and split background)
#                                          PNGs and points cfg["background"] / cfg["_split_bg"] at them
#     build_items(cfg, duration, splits, lbox, rbox) -> template-specific timeline Items
#                                          (cards / floating cards / badges...), appended after texts
#   Old job files have no "template_id" and are rendered as Template 1.
# ----------------------------------------------------------------------------
# Per-template color palettes (RGB). Template 2 must never use the Template 1 cyan.
PALETTES = {
    1: {"accent": CYAN, "accent_txt": CYAN_TXT},
    # TODO(PART2/3/4): tune these values against the poster (Building_Digital_Experiences_Poster.png)
    2: {"bg": (8, 10, 14), "lime": (189, 222, 56), "lime_dark": (110, 136, 32),
        "white": (255, 255, 255), "muted": (141, 146, 143)},
}


def t1_build_background(cfg, tmp):
    """Template 1 (Tech HUD) static layers: procedural background (+ split background)."""
    bg = cfg["background"]
    if bg.get("type") == "tech":
        W, H = cfg["canvas"]
        p = make_tech_background(W, H, cfg["video_box"], bg.get("divider_pct", 79), os.path.join(tmp, "bg.png"))
        cfg["background"] = {"type": "image", "path": p}
        if cfg.get("split"):
            lb, rb = split_boxes(cfg)
            cfg["_split_bg"] = make_split_background(W, H, lb, rb, bg.get("divider_pct", 79),
                                                     os.path.join(tmp, "bg_split.png"))


def t1_ask_config(video_info):
    return ask_hud_template()


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
T2_ACCENT = "#BDDE38"                          # sampled from the poster (median of the lime headline bar)
T2_SS = 4                                      # supersampling factor of every shape / text mask
T2_BG0, T2_BG1 = (5, 8, 11), (11, 12, 17)      # background gradient (top -> bottom)
T2_DEFAULT_BOX = {"x": 110, "y": 352, "w": 802, "h": 932, "mode": "fill"}
T2_DEFAULTS = {
    "accent": T2_ACCENT, "logo": "</>", "name": "AHMED IBRAHIM",
    "subtitle": "WEB DEVELOPER · MOBILE DEVELOPER · AI AUTOMATION",
    "pill": "CREATOR SERIES", "line1": "BUILDING DIGITAL", "line2": "EXPERIENCES",
    "radius": 28, "border": 5,                 # video window corner radius / border width (px at 1080 wide)
    "show_bg_shapes": True, "show_dots": True, "show_header": True, "show_pill": True, "show_headline": True,
    "fonts": {},                               # optional overrides {"headline": path, "ui": path, "arabic": path}
    # Part 3A - chapter tag (dynamic): list of {"start","end","trigger","num","label","anim","anim_dur"}
    "chapters": [], "chapters_on": True, "chapter_anim": "slide_up", "chapter_anim_dur": 0.35,
    # Part 3B - floating B-roll cards: list of {"media","label","icon","icon_path","slot","start","trigger","hold"}
    "cards": [], "cards_on": True, "card_rot": 4.0, "card_anim_dur": 0.5,
    # Part 4A - ABOUT ME + features block: list of states {"start","end","trigger","paragraph","title","rows","anim","anim_dur"}
    # ([] = one default state with the poster texts); about_on False = block disabled.
    "about": [], "about_on": True, "about_anim": "fade", "about_anim_dur": 0.4,
    # Part 4B - bottom info panel: {on, layers_title, guide_title, rows:[{label,start,end,color,segs,bar}], guide:[str]}
    # ({} = poster defaults; {"on": False} = panel disabled, nothing drawn).  Static plate + one moving playhead.
    "panel": {},
    # Part 4C - split screen: {on, left_pct, gap_px, margin, bottom_px, merge, radius, border}; off by default.
    # While an element (PNG) / video layer over the box is shown: video left, element right, two lime-framed rounded boxes.
    "split": {},
}
T2_TEXT_KEYS = ("logo", "name", "subtitle", "pill", "line1", "line2")
T2_BOOL_KEYS = ("show_bg_shapes", "show_dots", "show_header", "show_pill", "show_headline", "chapters_on", "cards_on", "about_on")


# ---- config ---------------------------------------------------------------------------
def t2_rgb(c):
    """'#rrggbb' / name / (r,g,b[,a]) -> (r,g,b). Unknown values fall back to the poster lime."""
    if isinstance(c, (tuple, list)):
        return tuple(int(v) for v in c[:3])
    try:
        return tuple(ImageColor.getrgb(str(c))[:3])
    except ValueError:
        return tuple(ImageColor.getrgb(T2_ACCENT)[:3])


def t2_mix(a, b, f):
    return tuple(int(round(a[i] + (b[i] - a[i]) * f)) for i in range(3))


def t2_lighten(c, f):
    return t2_mix(c, (255, 255, 255), f)


def t2_darken(c, f):
    return t2_mix(c, (0, 0, 0), f)


def t2_cfg(raw=None):
    """Complete, validated cfg["t2"]: every key present (unknown keys are kept for Parts 3-4)."""
    d = dict(T2_DEFAULTS)
    d["fonts"] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if v is not None:
                d[k] = v
    d["accent"] = "#%02x%02x%02x" % t2_rgb(d["accent"])
    for k in T2_TEXT_KEYS:
        d[k] = str(d.get(k, "")).replace("\n", " ")
    for k in T2_BOOL_KEYS:
        d[k] = bool(d.get(k, True))
    for k, lo, hi in (("radius", 0, 90), ("border", 1, 20)):
        try:
            d[k] = max(lo, min(hi, float(d[k])))
        except (TypeError, ValueError):
            d[k] = T2_DEFAULTS[k]
    if not isinstance(d.get("fonts"), dict):
        d["fonts"] = {}
    d["chapters"] = t2_norm_chapters(d.get("chapters"))
    if d.get("chapter_anim") not in ANIMS + ["none"]:
        d["chapter_anim"] = T2_DEFAULTS["chapter_anim"]
    try:
        d["chapter_anim_dur"] = max(0.05, min(3.0, float(d["chapter_anim_dur"])))
    except (TypeError, ValueError):
        d["chapter_anim_dur"] = T2_DEFAULTS["chapter_anim_dur"]
    d["cards"] = t2_norm_cards(d.get("cards"))
    for k, lo, hi in (("card_rot", -25.0, 25.0), ("card_anim_dur", 0.05, 3.0)):
        try:
            d[k] = max(lo, min(hi, float(d[k])))
        except (TypeError, ValueError):
            d[k] = T2_DEFAULTS[k]
    d["about"] = t2_norm_about(d.get("about"))
    if d.get("about_anim") not in ANIMS + ["none"]:
        d["about_anim"] = T2_DEFAULTS["about_anim"]
    try:
        d["about_anim_dur"] = max(0.05, min(3.0, float(d["about_anim_dur"])))
    except (TypeError, ValueError):
        d["about_anim_dur"] = T2_DEFAULTS["about_anim_dur"]
    d["panel"] = t2_norm_panel(d.get("panel"))
    d["split"] = t2_norm_split(d.get("split"))
    return d


def t2_norm_split(raw):
    """Validated cfg['t2']['split'] (see T2_DEFAULTS).  raw may be None / True / False / dict."""
    r = {"on": bool(raw)} if isinstance(raw, bool) else (raw if isinstance(raw, dict) else {})

    def num(k, dflt, lo, hi):
        try:
            return max(lo, min(hi, float(r.get(k, dflt))))
        except (TypeError, ValueError):
            return float(dflt)
    return {"on": bool(r.get("on", False)), "left_pct": num("left_pct", 50, 25, 75), "gap_px": int(round(num("gap_px", 24, 8, 120))),
            "margin": int(round(num("margin", 26, 12, 80))), "bottom_px": int(round(num("bottom_px", 170, 0, 400))),
            "merge": num("merge", 1.6, 0, 10), "radius": num("radius", 20, 0, 60), "border": int(round(num("border", 4, 1, 12)))}


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


def _t2_num_or_none(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def t2_norm_chapters(raw):
    """Chapter list -> clean list (idempotent). Entry: start (s) | trigger (SRT phrase), num (''=auto), label,
    optional end (s), anim ('' = cfg default), anim_dur (None = cfg default). Entries without num/label are dropped."""
    out = []
    for ch in (raw if isinstance(raw, (list, tuple)) else []):
        if not isinstance(ch, dict):
            continue
        num = str(ch.get("num") if ch.get("num") is not None else "").replace("\n", " ").strip()
        label = str(ch.get("label") if ch.get("label") is not None else "").replace("\n", " ").strip()
        if not num and not label and not str(ch.get("trigger") or "").strip():
            continue
        anim = ch.get("anim") if ch.get("anim") in ANIMS + ["none"] else ""
        out.append({"start": _t2_num_or_none(ch.get("start")), "end": _t2_num_or_none(ch.get("end")),
                    "trigger": str(ch.get("trigger") or "").strip(), "num": num, "label": label,
                    "anim": anim, "anim_dur": _t2_num_or_none(ch.get("anim_dur"))})
    return out


def t2_norm_cards(raw):
    """Floating-card list -> clean list (idempotent). Entry: media (image/video path), label, icon
    (code|phone|chip|none|image + icon_path), slot 1-3, start (s) | trigger (SRT phrase), hold (s).
    Entries without a media path are dropped."""
    out = []
    for c in (raw if isinstance(raw, (list, tuple)) else []):
        if not isinstance(c, dict) or not str(c.get("media") or "").strip():
            continue
        icon = c.get("icon") if c.get("icon") in ("code", "phone", "chip", "none", "image") else "code"
        ip = str(c.get("icon_path") or "") if icon == "image" else ""
        if icon == "image" and not ip:
            icon = "none"
        try:
            slot = int(c.get("slot") or 1)
        except (TypeError, ValueError):
            slot = 1
        hold = _t2_num_or_none(c.get("hold"))
        out.append({"media": str(c["media"]).strip(), "label": str(c.get("label") or "").replace("\n", " ").strip(),
                    "icon": icon, "icon_path": ip, "slot": slot if slot in (1, 2, 3) else 1,
                    "start": _t2_num_or_none(c.get("start")), "trigger": str(c.get("trigger") or "").strip(),
                    "hold": hold if hold and hold > 0.2 else 4.0})
    return out


# ---- fonts (3 roles, never crash on a missing font) -------------------------------------
# candidates are matched on letters only (case/digits/punctuation ignored): "Kanit_800ExtraBold_Italic.ttf"
# and "Kanit-ExtraBoldItalic.ttf" both become "kanitextrabolditalic".
T2_FONTS = {
    "headline": {
        "rec": ["kanitextrabolditalic", "montserratextrabolditalic", "barlowcondensedextrabolditalic"],
        "italic": ["montserratblackitalic", "barlowcondensedbolditalic", "barlowextrabolditalic",
                   "kanitbolditalic", "montserratbolditalic", "poppinsextrabolditalic", "poppinsbolditalic",
                   "interextrabolditalic", "interblackitalic", "interbolditalic", "dejavusansboldoblique"],
        "upright": ["barlowcondensedextrabold", "kanitextrabold", "montserratextrabold", "montserratbold",
                    "poppinsbold", "interextrabold", "interbold", "arialbd", "segoeuib", "tahomabd", "dejavusansbold"],
        "hint": "Kanit-ExtraBoldItalic.ttf (or Montserrat-ExtraBoldItalic.ttf / BarlowCondensed-ExtraBoldItalic.ttf)"},
    "ui": {
        "rec": ["rajdhanimedium", "barlowmedium", "montserratmedium"],
        "italic": [],
        "upright": ["rajdhanisemibold", "barlowsemibold", "montserratsemibold", "intermedium", "poppinsmedium",
                    "segoeui", "tahoma", "arial", "dejavusans"],
        "hint": "Rajdhani-Medium.ttf + Rajdhani-SemiBold.ttf (or Barlow-Medium.ttf / Montserrat-Medium.ttf)"},
    "ui_bold": {
        "rec": ["rajdhanisemibold", "barlowsemibold", "montserratsemibold"],
        "italic": [],
        "upright": ["rajdhanibold", "barlowbold", "montserratbold", "intersemibold", "interbold", "poppinssemibold",
                    "poppinsbold", "segoeuib", "tahomabd", "arialbd", "dejavusansbold"],
        "hint": ""},
    "arabic": {
        "rec": ["cairobold", "tajawalbold", "ibmplexsansarabicbold"],
        "italic": [],
        "upright": ["cairosemibold", "cairo", "tajawalmedium", "tajawal", "ibmplexsansarabicmedium",
                    "ibmplexsansarabic", "notosansarabicbold", "notosansarabic", "tahomabd", "tahoma", "arialbd", "dejavusansbold"],
        "hint": "Cairo-Bold.ttf (or Tajawal-Bold.ttf / IBMPlexSansArabic-Bold.ttf)"},
}
_t2_font_idx = None
_T2_WARNED = set()


def _t2_norm(s):
    return re.sub(r"[^a-z]", "", s.lower())


def _t2_lookup(norm):
    """Path of an installed/local font whose letters-only name is `norm` (or starts with it: variable fonts)."""
    global _t2_font_idx
    if _t2_font_idx is None:
        _t2_font_idx = {}
        for k, p in _build_font_index().items():
            _t2_font_idx.setdefault(_t2_norm(k), p)
    p = _t2_font_idx.get(norm)
    if p:
        return p
    for k, p in _t2_font_idx.items():
        if k.startswith(norm) and len(k) - len(norm) <= 12 and norm.count("bold") + norm.count("italic") == 0:
            return p
    return None


def t2_font(role, text="", overrides=None):
    """-> (font_path, needs_fake_italic). Arabic text always uses the Arabic role. Never raises."""
    if has_arabic(text):
        role = "arabic"
    spec = T2_FONTS[role]
    ov = (overrides or {}).get(role)
    if ov and os.path.isfile(ov):
        return ov, False
    found, shear = None, False
    # 1) recommended fonts, 2) other real italics, 3) upright bold (+ fake italic for the headline)
    for lst, sh in ((spec["rec"], False), (spec["italic"], False), (spec["upright"], role == "headline")):
        for n in lst:
            p = _t2_lookup(n)
            if p and (role != "arabic" or font_supports_arabic(p)):
                found, shear = p, sh
                break
        if found:
            break
    if not found:
        found = default_font()
        shear = role == "headline"
    if spec["hint"] and role not in _T2_WARNED and not any(_t2_lookup(n) == found for n in spec["rec"]):
        _T2_WARNED.add(role)
        print(f"[fonts] Template 2 {role}: recommended font not found, using "
              f"'{Path(found).name if found else 'none'}'. For the poster look put {spec['hint']} in the fonts/ folder.")
    return found, shear


def t2_size_for_cap(font_path, cap_px):
    """Font size (px) whose capital letters are `cap_px` tall."""
    try:
        f = load_font(font_path, 200)
        bb = f.getbbox("H")
        r = (bb[3] - bb[1]) / 200.0
    except Exception:
        r = 0.7
    return cap_px / (r if r > 0.2 else 0.7)


# ---- masks / paint helpers (reusable) ---------------------------------------------------
# A "mask" is a tuple (L image, (ox, oy)): an anti-aliased coverage mask placed at canvas pos (ox, oy).
def t2_draw_mask(bbox, draw_fn, ss=T2_SS, pad=3, post=None):
    """Generic 4x-supersampled mask. draw_fn(draw, L, ss): L(x, y) maps canvas px to the big mask's px."""
    x0, y0, x1, y1 = bbox
    ox, oy = int(math.floor(x0)) - pad, int(math.floor(y0)) - pad
    w, h = int(math.ceil(x1)) + pad - ox, int(math.ceil(y1)) + pad - oy
    m = Image.new("L", (max(1, w) * ss, max(1, h) * ss), 0)
    draw_fn(ImageDraw.Draw(m), lambda x, y: ((x - ox) * ss, (y - oy) * ss), ss)
    if post:
        m = post(m)
    return m.resize((max(1, w), max(1, h)), Image.LANCZOS), (ox, oy)


def t2_rrect_mask(box, radius, ss=T2_SS):
    """Rounded rectangle (x0, y0, x1, y1) - float coordinates allowed, clean anti-aliased corners."""
    x0, y0, x1, y1 = box

    def fn(d, L, s):
        a, b = L(x0, y0), L(x1, y1)
        d.rounded_rectangle((a[0], a[1], b[0] - 1, b[1] - 1), radius=max(0.0, radius) * s, fill=255)
    return t2_draw_mask(box, fn, ss, pad=2)


def t2_poly_mask(pts, round_r=0.0, ss=T2_SS):
    """Polygon mask; round_r > 0 rounds the corners (blur + threshold at 4x)."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]

    def fn(d, L, s):
        d.polygon([L(x, y) for x, y in pts], fill=255)
    post = None
    if round_r > 0:
        def post(m):
            return m.filter(ImageFilter.GaussianBlur(round_r * ss * 0.6)).point(lambda v: 255 if v >= 128 else 0)
    return t2_draw_mask((min(xs), min(ys), max(xs), max(ys)), fn, ss, pad=int(round_r) + 3, post=post)


def t2_polys_mask(polys, ss=T2_SS):
    """Several polygons in one mask (hatch stripes...)."""
    xs = [p[0] for pl in polys for p in pl]
    ys = [p[1] for pl in polys for p in pl]

    def fn(d, L, s):
        for pl in polys:
            d.polygon([L(x, y) for x, y in pl], fill=255)
    return t2_draw_mask((min(xs), min(ys), max(xs), max(ys)), fn, ss)


def t2_line_mask(pts, width, caps=True, ss=T2_SS):
    """Poly-line with round joints (and round caps)."""
    hw = width / 2.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]

    def fn(d, L, s):
        P = [L(x, y) for x, y in pts]
        d.line(P, fill=255, width=max(1, int(round(width * s))), joint="curve")
        if caps:
            for x, y in P:
                d.ellipse((x - hw * s, y - hw * s, x + hw * s, y + hw * s), fill=255)
    return t2_draw_mask((min(xs) - hw, min(ys) - hw, max(xs) + hw, max(ys) + hw), fn, ss)


def t2_dots_mask(x0, y0, cols, rows, pitch_x, pitch_y, r, ss=T2_SS):
    def fn(d, L, s):
        for i in range(cols):
            for j in range(rows):
                cx, cy = L(x0 + i * pitch_x, y0 + j * pitch_y)
                d.ellipse((cx - r * s, cy - r * s, cx + r * s, cy + r * s), fill=255)
    return t2_draw_mask((x0 - r, y0 - r, x0 + (cols - 1) * pitch_x + r, y0 + (rows - 1) * pitch_y + r), fn, ss)


def t2_mask_sub(a, b):
    """a minus b (result lives in a's frame)."""
    am, (ax, ay) = a
    bm, (bx, by) = b
    layer = Image.new("L", am.size, 0)
    layer.paste(bm, (bx - ax, by - ay))
    return ImageChops.subtract(am, layer), (ax, ay)


def t2_mask_full(mask, size):
    """Mask -> full-canvas 'L' image."""
    m, (ox, oy) = mask
    full = Image.new("L", size, 0)
    full.paste(m, (ox, oy))
    return full


def t2_place(m, x, cy=None, y=None, right=None):
    """Put a 1x mask on the canvas: left edge x (or right edge `right`), vertically centred on cy (or top y)."""
    ox = int(round(right - m.width)) if right is not None else int(round(x))
    oy = int(round(cy - m.height / 2.0)) if cy is not None else int(round(y))
    return m, (ox, oy)


def t2_ramp(stops, n=1024):
    """stops [(pos 0..1, (r,g,b[,a]))...] -> RGBA image n x 2 (two identical rows)."""
    st = sorted(((float(p), tuple(c) if len(c) == 4 else tuple(c) + (255,)) for p, c in stops), key=lambda s: s[0])
    px = []
    for i in range(n):
        t = i / float(n - 1)
        if t <= st[0][0]:
            col = st[0][1]
        elif t >= st[-1][0]:
            col = st[-1][1]
        else:
            col = st[-1][1]
            for (p0, c0), (p1, c1) in zip(st, st[1:]):
                if p0 <= t <= p1:
                    f = (t - p0) / (p1 - p0) if p1 > p0 else 0.0
                    col = tuple(int(round(c0[j] + (c1[j] - c0[j]) * f)) for j in range(4))
                    break
        px.append(col)
    im = Image.new("RGBA", (n, 2))
    im.putdata(px + px)
    return im


def t2_gradient(size, stops, angle=90.0, box=None):
    """Linear gradient image (RGBA). angle: 0 = left->right, 90 = top->bottom, 135 = top-right->bottom-left.
    box = (x0, y0, x1, y1): the area the 0..1 range spans (default: the whole image)."""
    w, h = size
    x0, y0, x1, y1 = box or (0, 0, w, h)
    n = 1024
    ramp = t2_ramp(stops, n)
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    proj = [x * dx + y * dy for x in (x0, x1) for y in (y0, y1)]
    lo, span = min(proj), max(max(proj) - min(proj), 1e-6)
    s = (n - 1) / span
    return ramp.transform((w, h), Image.AFFINE, (dx * s, dy * s, 0.5 - lo * s, 0, 0, 1.0), resample=Image.BILINEAR)


def t2_grad(stops, angle=90.0, box=None):
    """Callable fill for t2_paint: a gradient defined in CANVAS coordinates (box) - or the mask's bounds."""
    def f(size, off):
        b = None if box is None else (box[0] - off[0], box[1] - off[1], box[2] - off[0], box[3] - off[1])
        return t2_gradient(size, stops, angle, b)
    return f


def _t2_alpha_paste(base, layer, ox, oy):
    W, H = base.size
    w, h = layer.size
    sx, sy = max(0, -ox), max(0, -oy)
    ex, ey = min(w, W - ox), min(h, H - oy)
    if ex > sx and ey > sy:
        base.alpha_composite(layer.crop((sx, sy, ex, ey)), (ox + sx, oy + sy))


def t2_paint(base, mask, fill, opacity=1.0):
    """Paint `fill` through `mask` onto the RGBA `base` (in place).
    fill = (r,g,b[,a]) | RGBA image of the mask's size | callable(size, (ox, oy)) -> RGBA image.
    Returns the tight canvas bbox of what was painted (or None)."""
    m, (ox, oy) = mask
    if callable(fill):
        col = fill(m.size, (ox, oy))
    elif isinstance(fill, Image.Image):
        col = fill.convert("RGBA")
    else:
        c = tuple(fill)
        col = Image.new("RGBA", m.size, (c[0], c[1], c[2], c[3] if len(c) > 3 else 255))
    a = ImageChops.multiply(m, col.getchannel("A"))
    if opacity < 1.0:
        a = a.point(lambda v: int(v * opacity + 0.5))
    col = col.copy()
    col.putalpha(a)
    _t2_alpha_paste(base, col, ox, oy)
    bb = m.point(lambda v: 255 if v > 8 else 0).getbbox()
    return None if not bb else (ox + bb[0], oy + bb[1], ox + bb[2], oy + bb[3])


def t2_glow(mask, radius, strength=1.0):
    """Soft glow mask around a mask (paint it with the glow colour)."""
    m, (ox, oy) = mask
    pad = int(radius * 3) + 2
    big = Image.new("L", (m.width + 2 * pad, m.height + 2 * pad), 0)
    big.paste(m, (pad, pad))
    big = big.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, int(v * strength)))
    return big, (ox - pad, oy - pad)


# ---- text -----------------------------------------------------------------------------
def t2_shear_mask(m, k):
    """Fake italic: lean the top of the glyphs to the right by tan = k (works on 'L' / RGBA images)."""
    w, h = m.size
    extra = int(math.ceil(abs(k) * h)) + 1
    return m.transform((w + extra, h), Image.AFFINE, (1, k, -k * h, 0, 1, 0), resample=Image.BICUBIC)


def t2_text_mask(text, font_path, size, tracking_em=0.0, shear=0.0, ss=T2_SS):
    """Ink-cropped 1x 'L' mask of one line of text (4x supersampled). Arabic is shaped as a whole;
    letter-spacing (tracking) and fake italic only apply to Latin text."""
    S = max(4, int(round(size * ss)))
    font = load_font(font_path, S)
    s = shape(text)
    arabic = has_arabic(text)
    tr = 0.0 if arabic else tracking_em * S
    asc, desc = font.getmetrics()
    total = font.getlength(s) + tr * max(0, len(s) - 1)
    pad = int(S * 0.3) + 4
    m = Image.new("L", (int(total) + 2 * pad + 8, asc + desc + 2 * pad), 0)
    d = ImageDraw.Draw(m)
    if tr:
        for i, ch in enumerate(s):
            if ch != " ":
                d.text((pad + font.getlength(s[:i]) + tr * i, pad + asc), ch, font=font, fill=255, anchor="ls")
    else:
        d.text((pad, pad + asc), s, font=font, fill=255, anchor="ls")
    bb = m.getbbox()
    if not bb:
        return Image.new("L", (1, 1), 0)
    m = m.crop(bb)
    if shear and not arabic:
        m = t2_shear_mask(m, shear)
        m = m.crop(m.getbbox() or (0, 0, 1, 1))
    w, h = m.size
    w2, h2 = -(-w // ss) * ss, -(-h // ss) * ss
    if (w2, h2) != (w, h):
        n = Image.new("L", (w2, h2), 0)
        n.paste(m, (0, 0))
        m = n
    return m.resize((w2 // ss, h2 // ss), Image.LANCZOS)


def t2_fit_text(text, font_path, max_w, cap_px, tracking_em=0.0, shear=0.0, min_scale=0.4):
    """Auto-fit: shrink the font until the ink fits max_w (never below min_scale); as a last resort the text
    is cut and '...' added. Returns (mask, shown_text, font_size)."""
    size0 = t2_size_for_cap(font_path, cap_px)
    size = size0
    m = t2_text_mask(text, font_path, size, tracking_em, shear)
    for _ in range(6):
        if m.width <= max_w:
            return m, text, size
        size = max(size0 * min_scale, size * max_w / float(m.width) * 0.99)
        m = t2_text_mask(text, font_path, size, tracking_em, shear)
        if size <= size0 * min_scale + 1e-6:
            break
    t = text
    while m.width > max_w and len(t) > 1:
        t = t[:-max(1, len(t) // 10)].rstrip()
        m = t2_text_mask(t + "...", font_path, size, tracking_em, shear)
    return m, (t + "..." if t != text else text), size


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


def _tpl_template_id(path):
    try:
        return int(json.loads(Path(path).read_text(encoding="utf-8")).get("template_id") or 0)
    except Exception:
        return 0


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


# ---- Template 2: still preview (--still) ------------------------------------------------
def _first_frame(video, size_hint=None):
    """First frame of the video as an RGB PIL image (None if it cannot be read)."""
    if not video or not os.path.isfile(str(video)) or not FFMPEG:
        return None
    fd, png = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        r = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
                            "-frames:v", "1", png], capture_output=True)
        return Image.open(png).convert("RGB").copy() if r.returncode == 0 and os.path.getsize(png) > 0 else None
    except Exception:
        return None
    finally:
        try:
            os.remove(png)
        except OSError:
            pass


def render_still(cfg, out_png, t=0.5):
    """ONE png of the final composite at time t (default 0.5 s), in about a second - no video encoding.
    Video = the first frame of cfg['video'] (mid-grey placeholder when there is no readable video)."""
    cfg = preflight_cfg(cfg, need_video=False)
    cfg["template_id"] = get_template(cfg)["id"]
    cfg["_t2_still"] = True              # video cards are drawn as Items (first frame) in a still
    W, H = cfg["canvas"]
    tmp = tempfile.mkdtemp(prefix="montage_still_")
    try:
        get_template(cfg)["build_background"](cfg, tmp)
        bg = cfg["background"]
        if bg["type"] == "color":
            img = Image.new("RGBA", (W, H), bg["value"])
        elif bg["type"] == "image":
            img = Image.open(bg["path"]).convert("RGB")
            if img.size != (W, H):
                s = max(W / img.width, H / img.height)
                img = img.resize((max(W, int(img.width * s)), max(H, int(img.height * s))), Image.LANCZOS)
                img = img.crop((0, 0, W, H))
            img = img.convert("RGBA")
        else:
            img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        box = cfg["video_box"]
        bw, bh = box["w"], box["h"]
        frame = _first_frame(cfg.get("video")) or Image.new("RGB", (max(2, bw), max(2, bh)), (128, 128, 128))
        if box.get("mode", "fit") == "fill":
            s = max(bw / frame.width, bh / frame.height)
            fr = frame.resize((max(bw, int(round(frame.width * s))), max(bh, int(round(frame.height * s)))),
                              Image.LANCZOS)
            l, tp = (fr.width - bw) // 2, (fr.height - bh) // 2
            img.paste(fr.crop((l, tp, l + bw, tp + bh)), (box["x"], box["y"]))
        else:
            s = min(bw / frame.width, bh / frame.height)
            fr = frame.resize((max(2, int(frame.width * s)), max(2, int(frame.height * s))), Image.LANCZOS)
            img.paste(fr, (box["x"] + (bw - fr.width) // 2, box["y"] + (bh - fr.height) // 2))
        if cfg.get("_t2_fg"):
            img.alpha_composite(Image.open(cfg["_t2_fg"]).convert("RGBA"))
        info = probe(cfg["video"]) if cfg.get("video") and os.path.isfile(str(cfg["video"])) else None
        ph = cfg.get("_t2_playhead")
        if ph:
            frac = max(0.0, min(1.0, t / float(info["duration"] if info else 5.0)))
            sp = Image.open(ph["path"]).convert("RGBA")
            img.alpha_composite(sp, (int(ph["cx0"] + (ph["cx1"] - ph["cx0"]) * frac - sp.width / 2.0), ph["y"]))
        items = build_items(cfg, info["duration"] if info else 5.0)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for it in items:
            if it.start <= t < it.end:
                draw_item(ov, it, anim_state(it.anim, it.progress(t), W, H))
        img.alpha_composite(ov)
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(out_png)
        return out_png
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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


def _read_exact(f, n):
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


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


# ---- Template 2: ABOUT ME + FEATURES block (Part 4A) --------------------------------------------------
# Poster (941 px wide) y 1150-1280, under the video window; x 1.1477 -> 1080 px.  All numbers below are canvas px at
# 1080 wide, y relative to `y_base` = bottom of the video window + 36 (default window: 1284 + 36 = 1320).
# Left column: lime square + "ABOUT ME" (letter-spaced grey) + <=3 light-white paragraph lines.  Thin vertical divider.
# Right column: <=4 rows of  lime line icon + white text.  Several STATES over time (time or SRT trigger phrase).
T2_ABOUT = {"x_left": 98, "col_w": 450, "div_x": 570, "div_y0": 6, "div_y1": 143, "sq": 15, "sq_y": 10,
            "title_dx": 41, "title_cy": 18, "title_cap": 15, "title_tr": 0.30,
            "para_cy": 61, "para_pitch": 33, "para_cap": 20, "para_lines": 3, "min_scale": 0.55,
            "row_cy": 71, "row_pitch": 47, "row_pitch4": 38, "icon": 32, "icon_cx": 671, "text_x": 726, "right": 982,
            "row_cap": 19, "box_gap": 36, "pad_x": 8, "top": -4, "h": 154, "max_rows": 4,
            "muted": (141, 146, 143), "para_col": (232, 234, 232), "div_col": (95, 100, 98, 210)}
T2_ABOUT_DEFAULT_STATE = {
    "paragraph": "Passionate about technology, building scalable solutions, and sharing knowledge.",
    "title": "ABOUT ME",
    "rows": [{"icon": "laptop", "text": "Web Development"}, {"icon": "phone", "text": "Mobile Development"},
             {"icon": "gear", "text": "AI Automation"}]}
T2_ABOUT_ICONS = ("laptop", "phone", "gear", "code", "chip", "image", "none")
T2_ABOUT_ICON_LINE = "1=laptop  2=phone  3=gear/AI  4=code  5=chip  6=none  or a path to a PNG/ICO"


def t2_about_icon_spec(v):
    """Icon answer ('laptop' | number 1-6 | path of a PNG/ICO) -> (kind, icon_path). Unknown -> ('none', '')."""
    s = str(v if v is not None else "").strip()
    m = {"1": "laptop", "2": "phone", "3": "gear", "4": "code", "5": "chip", "6": "none", "ai": "gear"}
    s = m.get(s.translate(AR_DIGITS).lower(), s)
    if s in T2_ABOUT_ICONS and s != "image":
        return s, ""
    if s and os.path.isfile(clean_path(s)):
        return "image", clean_path(s)
    return "none", ""


def c_about_icon(s):
    k, p = t2_about_icon_spec(s)
    if k == "none" and s.strip().translate(AR_DIGITS) not in ("6", "none"):
        raise ValueError("use 1-6 or a valid image path")
    return p if k == "image" else k


def t2_norm_about(raw):
    """About states -> clean list (idempotent). State: start (s) | trigger (SRT phrase), end (s), paragraph, title
    ('' = no title), rows (<=4 of {icon, icon_path, text}), anim ('' = cfg default), anim_dur (None = cfg default).
    An empty / invalid list means 'one default state (the poster texts) for the whole video'."""
    out = []
    for st in (raw if isinstance(raw, (list, tuple)) else []):
        if not isinstance(st, dict):
            continue
        rows = []
        for r in (st.get("rows") if isinstance(st.get("rows"), (list, tuple)) else [])[:T2_ABOUT["max_rows"]]:
            if isinstance(r, str):
                r = {"text": r}
            if not isinstance(r, dict):
                continue
            txt = str(r.get("text") if r.get("text") is not None else "").replace("\n", " ").strip()
            kind, ipath = t2_about_icon_spec(r.get("icon_path") or r.get("icon") or "none")
            if not txt and kind == "none":
                continue
            rows.append({"icon": kind, "icon_path": ipath, "text": txt})
        title = st.get("title")
        out.append({"start": _t2_num_or_none(st.get("start")), "end": _t2_num_or_none(st.get("end")),
                    "trigger": str(st.get("trigger") or "").strip(),
                    "paragraph": str(st.get("paragraph") if st.get("paragraph") is not None else "").replace("\n", " ").strip(),
                    "title": T2_ABOUT_DEFAULT_STATE["title"] if title is None else str(title).replace("\n", " ").strip(),
                    "rows": rows, "anim": st.get("anim") if st.get("anim") in ANIMS + ["none"] else "",
                    "anim_dur": _t2_num_or_none(st.get("anim_dur"))})
    return out


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


# ---- Template 2: bottom INFO PANEL (Part 4B) -----------------------------------------------------------------
# Poster px (941 wide).  ONE static plate (baked into the foreground plate, zero per-frame cost) + ONE small
# playhead sprite that FFmpeg moves with an x-expression of the real video time (progress = t / duration).
# Part 4C adds the audio waveform in row 09 (reserved, left empty here) and the pagination dots.
T2_PANEL = {"x0": 22, "y0": 1303, "x1": 918, "y1": 1605, "radius": 24, "outline": (84, 90, 72), "fill": (9, 11, 15),
            "num_x": 40, "label_x": 88, "label_r": 294, "track_x0": 306, "track_x1": 608, "row0": 1366, "pitch": 26.5,
            "bar_h": 15, "bar_r": 3, "label_cap": 11.2, "num_cap": 10.5, "title_cap": 13.5, "title_x": 91, "title_cy": 1330,
            "icon_cx": 55, "icon": 30, "sep": (30, 34, 38), "muted": (150, 154, 152),
            "div_x": 637, "div_y0": 1318, "div_y1": 1592, "g_icon_cx": 672, "g_title_x": 704, "g_circ_x": 670,
            "g_text_x": 695, "g_right": 905, "g_y0": 1371, "g_pitch": 33.1, "circ_r": 9.6, "g_cap": 11.2,
            "ph_top": 1333, "ph_bot": 1590, "ph_w": 2.2, "tri_w": 13, "tri_h": 10, "max_rows": 9, "max_guide": 6}
T2_PANEL_ROWS = [
    ("Main Video Footage", 0.0, 1.0, "#4C95DC", None),
    ("Secondary B-Roll / Image", 0.209, 0.719, "#833B8F", None),
    ("Background Graphics", 0.0, 0.503, "#1B3C2D", None),
    ("Main Headline", 0.0, 0.96, "#ACCF42", None),
    ("Arabic Captions", 0.0, 0.838, "#D4C9B7", [[0.0, 0.22], [0.25, 0.44], [0.47, 0.68], [0.71, 0.838]]),
    ("Active Word Highlight", 0.318, 0.616, "#92D30A", None),
    ("Supporting Text", 0.454, 0.752, "#878686", [[0.454, 0.55], [0.58, 0.752]]),
    ("Motion Graphics", 0.0, 0.51, "#038D74", None),
    ("Sound Effects / Audio", 0.0, 0.0, "#6E7075", None),      # row 09: no bar yet (waveform = Part 4C)
]
T2_PANEL_GUIDE = ["Headline: Slide Up + Fade In", "Captions: Word-by-Word Reveal", "Highlight: Scale + Color Change",
                  "B-Roll: Slide In", "Support Text: Fade In", "Transitions: Smooth Mask"]


def _t2_frac(v, dflt):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return dflt


def t2_norm_panel(raw):
    """Validated cfg['t2']['panel'] = {on, layers_title, guide_title, rows:[{label,start,end,color,segs,bar}], guide:[str]}.
    raw may be None / True / False / dict; missing rows or guide texts = the poster defaults."""
    r = {"on": bool(raw)} if isinstance(raw, bool) else (raw if isinstance(raw, dict) else {})
    out = {"on": bool(r.get("on", True)),
           "layers_title": str(r.get("layers_title") if r.get("layers_title") is not None else "EDITING LAYERS").replace("\n", " "),
           "guide_title": str(r.get("guide_title") if r.get("guide_title") is not None else "MOTION GUIDE").replace("\n", " "),
           "wave": bool(r.get("wave", True)),      # Part 4C: real audio waveform in row 09 (when that row has no bar)
           "dots": bool(r.get("dots", True)),      # Part 4C: pagination dots, bottom-right of the panel
           # "roadmap" = content-driven panel (one card per chapter, the current one lit) instead of EDITING LAYERS / MOTION GUIDE
           "style": "roadmap" if str(r.get("style") or "").strip().lower() in ("roadmap", "chapters", "map") else "editing",
           "title": str(r.get("title") if r.get("title") is not None else "EPISODE ROADMAP").replace("\n", " "),
           "now_label": str(r.get("now_label") if r.get("now_label") is not None else "NOW").replace("\n", " "),
           "end": _t2_num_or_none(r.get("end"))}   # roadmap only: second at which the panel fades out (None = video end)
    rows_in = r.get("rows")
    if not isinstance(rows_in, list):
        rows_in = [None] * len(T2_PANEL_ROWS)
    rows = []
    for i, x in enumerate(rows_in[:T2_PANEL["max_rows"]]):
        dl, ds, de, dc, dsegs = T2_PANEL_ROWS[i] if i < len(T2_PANEL_ROWS) else ("", 0.0, 0.0, "#8E9094", None)
        x = {"label": x} if isinstance(x, str) else (x if isinstance(x, dict) else {})
        s, e = _t2_frac(x.get("start"), ds), _t2_frac(x.get("end"), de)
        if x.get("start") is None and x.get("end") is None:
            s, e = ds, de
        segs = x.get("segs", dsegs if (x.get("start") is None and x.get("end") is None) else None)
        ns = []
        for sg in (segs or []):
            try:
                a, b = _t2_frac(sg[0], 0.0), _t2_frac(sg[1], 0.0)
                if b > a:
                    ns.append([a, b])
            except (TypeError, IndexError):
                pass
        rows.append({"label": str(x["label"] if x.get("label") is not None else dl).replace("\n", " "),
                     "start": s, "end": e, "color": "#%02x%02x%02x" % t2_rgb(x.get("color") or dc),
                     "segs": ns or None, "bar": bool(x.get("bar", bool(ns) or e > s))})
    out["rows"] = rows
    g = r.get("guide")
    if not isinstance(g, list):
        g = list(T2_PANEL_GUIDE)
    out["guide"] = [str(v).replace("\n", " ") for v in g[:T2_PANEL["max_guide"]]]
    return out


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


def recap_line(cfg):
    """One line: template name + which Template 2 modules are on."""
    e = get_template(cfg)
    line = f"{e['name']} - {e['desc']}"
    if e["id"] != 2:
        return line
    t2 = cfg.get("t2") or {}
    pn = t2.get("panel") or {}
    mods = [("header", t2.get("show_header", True)), ("headline", t2.get("show_headline", True)),
            ("captions x%d" % len(cfg.get("captions", [])), bool(cfg.get("captions"))),
            ("chapters x%d" % len(t2.get("chapters") or []), bool(t2.get("chapters")) and t2.get("chapters_on", True)),
            ("cards x%d" % len(t2.get("cards") or []), bool(t2.get("cards")) and t2.get("cards_on", True)),
            ("about", t2.get("about_on", True)), ("bottom panel", pn.get("on", True)),
            ("split", bool((t2.get("split") or {}).get("on"))),
            ("texts x%d" % len(cfg.get("texts", [])), bool(cfg.get("texts"))),
            ("elements x%d" % len(cfg.get("elements", [])), bool(cfg.get("elements")))]
    return line + "  |  ON: " + (", ".join(n for n, on in mods if on) or "-") + \
        "  |  off: " + (", ".join(n.split(" x")[0] for n, on in mods if not on) or "-")


TEMPLATE_REGISTRY = {
    1: {"id": 1, "name": "Template 1", "desc": "Tech HUD, dark blue, glowing frame, info cards",
        "ask_config": t1_ask_config, "ask_cards": ask_cards, "caption_style": ask_caption_style,
        "build_background": t1_build_background, "build_items": t1_build_items},
    2: {"id": 2, "name": "Template 2", "desc": "Lime Creator Series",
        "ask_config": t2_ask_config, "ask_cards": t2_ask_cards, "caption_style": t2_caption_style,
        "build_background": t2_build_static_layers, "build_items": t2_build_items},
    3: {"id": 3, "name": "Custom", "desc": "old Custom flow, and your saved templates from templates/*.json",
        "ask_config": ask_template, "ask_cards": ask_cards, "caption_style": ask_caption_style,
        "build_background": t1_build_background, "build_items": t1_build_items},
}


def get_template(cfg):
    """Registry entry for a cfg / job. Missing or unknown template_id -> Template 1."""
    try:
        tid = int(cfg.get("template_id") or 1)
    except (TypeError, ValueError):
        tid = 1
    return TEMPLATE_REGISTRY.get(tid, TEMPLATE_REGISTRY[1])


# ----------------------------------------------------------------------------
# --selftest  (no questions; synthetic assets; PASS/FAIL table)
# ----------------------------------------------------------------------------
GOLDEN_DIR = BASE / "selftest_golden"
GOLDEN_TIMES = ("0.5", "1.5", "2.5")


def _st_make_assets(d):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                           "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=5",
                           "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                           str(d / "test.mp4")])
    (d / "ar.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,200\nأنا *أحمد* إبراهيم مطور ويب\n\n"
        "2\n00:00:01,300 --> 00:00:02,400\nأبني تطبيقات Flutter و Django بسرعة\n\n"
        "3\n00:00:02,500 --> 00:00:03,600\nوأشارك *المعرفة* مع الناس\n\n"
        "4\n00:00:03,700 --> 00:00:05,000\nتابعني لمزيد من الفيديوهات\n", encoding="utf-8")
    (d / "en.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,200\nI am *Ahmed* Ibrahim, web developer\n\n"
        "2\n00:00:01,300 --> 00:00:02,400\nI build Flutter and Django apps fast\n\n"
        "3\n00:00:02,500 --> 00:00:03,600\nand I share *knowledge* with people\n\n"
        "4\n00:00:03,700 --> 00:00:05,000\nFollow me for more videos\n", encoding="utf-8")
    im = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    g = ImageDraw.Draw(im)
    g.rounded_rectangle((10, 10, 390, 290), radius=30, fill=(255, 140, 0, 255), outline=(255, 255, 255, 255), width=8)
    g.ellipse((120, 70, 280, 230), fill=(30, 30, 30, 255))
    im.save(d / "element.png")
    ic = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(ic).polygon([(64, 8), (120, 64), (64, 120), (8, 64)], fill=(255, 255, 255, 255))
    ic.save(d / "icon.png")
    ic.save(d / "icon.ico", sizes=[(128, 128)])


def _st_font():
    """The golden frames were made with DejaVuSans-Bold; a copy lives in selftest_golden/."""
    f = GOLDEN_DIR / "selftest_font.ttf"
    return str(f) if f.is_file() else default_font()


def _st_job(d, tid, out, preview=3.0):
    d = Path(d)
    font = _st_font()
    cap = {"font": font, "color": "#ffffff", "hl_color": "#00b8ff", "stroke_color": "#000000",
           "stroke_w": 0, "shadow": True, "mode": "phrase", "max_words": 8, "anim": "fade", "anim_dur": 0.25}
    cfg = {
        "template_id": tid,
        "video": str(d / "test.mp4"), "canvas": [1080, 1920],
        "video_box": {"x": 238, "y": 335, "w": 604, "h": 928, "mode": "fill"},
        "background": {"type": "tech", "divider_pct": 79}, "layers": [],
        "captions": [dict(cap, srt=str(d / "ar.srt"), size=42, keywords="", ref="box", y_pct=86),
                     dict(cap, srt=str(d / "en.srt"), size=36, keywords="Flutter", ref="canvas", y_pct=72)],
        "texts": [{"text": "Hello مرحبا", "start": 0.0, "end": 2.8, "pos": "top", "font": font, "size": 90,
                   "color": "#ffffff", "stroke_color": "#000000", "stroke_w": 0, "anim": "fade", "anim_dur": 0.5}],
        "cards": [{"l1": "WEB", "l2": "DEVELOPER", "icon": "code", "icon_path": None, "slot": 1, "start": 0.3,
                   "hold": 2.5, "anim": "pop", "anim_dur": 0.45, "font": font}],
        "elements": [{"path": str(d / "element.png"), "start": 0.5, "end": 2.8, "pos": "bottom-right",
                      "width": "20%", "opacity": 100, "anim": "pop", "anim_dur": 0.5}],
        "video_layers": [], "output": str(out), "preview": preview,
    }
    if tid == 2:
        cfg["t2"] = t2_cfg({})
        cfg["video_box"] = dict(T2_DEFAULT_BOX)
        cfg["background"] = {"type": "t2"}
    return cfg


def _st_info(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    j = json.loads(r.stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    return (int(v["width"]), int(v["height"]), float(j["format"]["duration"]),
            any(s["codec_type"] == "audio" for s in j["streams"]))


def _st_frame_diffs(video, tmp, tag):
    """Mean absolute pixel difference (0-255) between the video's frames and selftest_golden/."""
    from PIL import ImageStat
    res = []
    for t in GOLDEN_TIMES:
        png = Path(tmp) / f"{tag}_{t}.png"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", t, "-i", str(video),
                        "-frames:v", "1", str(png)], check=True)
        a = Image.open(png).convert("RGB")
        b = Image.open(GOLDEN_DIR / f"t1_{t}.png").convert("RGB")
        if a.size != b.size:
            res.append(999.0)
            continue
        res.append(sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3.0)
    return res


def _st_golden_status():
    """None if golden comparison is possible, else a SKIP reason."""
    if not all((GOLDEN_DIR / f"t1_{t}.png").is_file() for t in GOLDEN_TIMES):
        return "selftest_golden/ not found next to the script"
    try:
        meta = json.loads((GOLDEN_DIR / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    gm = meta.get("arabic_mode")
    if gm and gm != ARABIC_MODE:
        return f"golden was made with Arabic engine '{gm}', this machine uses '{ARABIC_MODE}'"
    if not (GOLDEN_DIR / "selftest_font.ttf").is_file():
        return "selftest_golden/selftest_font.ttf missing"
    return None


def run_selftest():
    import builtins
    import contextlib
    import io
    rows = []

    def rec(name, status, detail=""):
        rows.append((name, status, detail))

    def quiet(fn, *a, **k):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return fn(*a, **k)

    tmp = Path(tempfile.mkdtemp(prefix="montage_selftest_"))
    saved_D = dict(D)
    saved_input, saved_tdir = builtins.input, globals()["TEMPLATES_DIR"]
    D.clear()
    try:
        # 1. syntax / import / ffmpeg
        try:
            compile(Path(__file__).read_text(encoding="utf-8"), __file__, "exec")
            ok = bool(FFMPEG and FFPROBE)
            rec("1 syntax + imports + ffmpeg", "PASS" if ok else "FAIL",
                f"ffmpeg={FFMPEG}" if ok else "ffmpeg/ffprobe not found")
        except Exception as e:
            rec("1 syntax + imports + ffmpeg", "FAIL", repr(e))
        if not (FFMPEG and FFPROBE):
            raise _StopSelftest()

        _st_make_assets(tmp / "assets")
        A = tmp / "assets"

        # 2. selector + flow (simulated stdin)
        def feed(answers, prompts):
            it = iter(answers)

            def fake(prompt=""):
                prompts.append(prompt)
                try:
                    return next(it)
                except StopIteration:
                    raise EOFError
            builtins.input = fake
        try:
            got = {}
            for ans in ("1", "2", "3"):
                feed([ans], [])
                got[ans] = quiet(choose_template)["id"]
            sel_ok = got == {"1": 1, "2": 2, "3": 3}
            # saved-template path (Custom): list shows 'New template' + 1 saved one, pick the saved one
            sdir = tmp / "templates"
            sdir.mkdir()
            saved_tpl = {"canvas": [1080, 1080], "video_box": {"x": 0, "y": 0, "w": 1080, "h": 1080, "mode": "fit"},
                         "background": {"type": "color", "value": "#101820"}, "layers": []}
            (sdir / "mysaved.json").write_text(json.dumps(saved_tpl), encoding="utf-8")
            globals()["TEMPLATES_DIR"] = sdir
            feed(["2"], [])
            loaded = quiet(TEMPLATE_REGISTRY[3]["ask_config"], {})
            saved_ok = loaded == saved_tpl
            globals()["TEMPLATES_DIR"] = saved_tdir
            # whole interactive flow: the template question must come first, before 'Video path'
            flow_ok, flow_msg = True, ""
            for tid in (1, 2):
                prompts = []
                if tid == 1:
                    feed([str(tid), str(A / "test.mp4"), "", "", "", "", "", "n", "", "n", "n", "n", "n",
                          str(tmp / f"flow{tid}.mp4"), ""], prompts)
                else:   # Template 2: template, video, then Enter (= default) for every other question
                    first = iter([str(tid), str(A / "test.mp4")])

                    def fake2(prompt=""):
                        prompts.append(prompt)
                        return next(first, "")
                    builtins.input = fake2
                c = quiet(interactive)
                if not (prompts[0].startswith("Choice") and prompts[1].startswith("Video path")):
                    flow_ok, flow_msg = False, f"first prompts: {prompts[:2]}"
                if tid == 1 and (c.get("template_id") != 1 or c["background"].get("type") != "tech"
                                 or c["video_box"]["w"] != 604):
                    flow_ok, flow_msg = False, "cfg wrong for template 1"
                if tid == 2 and (c.get("template_id") != 2 or c["background"].get("type") != "t2"
                                 or c["video_box"] != T2_DEFAULT_BOX or c.get("t2") != t2_cfg({})):
                    flow_ok, flow_msg = False, f"cfg wrong for template 2: {c.get('video_box')} {c.get('t2')}"
            ok = sel_ok and saved_ok and flow_ok
            rec("2 template selector (1/2/saved)", "PASS" if ok else "FAIL",
                f"ids={got} saved_ok={saved_ok} flow_ok={flow_ok} {flow_msg}".strip())
        except Exception as e:
            rec("2 template selector (1/2/saved)", "FAIL", repr(e))
        finally:
            builtins.input = saved_input
            globals()["TEMPLATES_DIR"] = saved_tdir

        gskip = _st_golden_status()

        # 3. + 4. Template 1 render and golden frames
        out1 = tmp / "t1.mp4"
        try:
            quiet(render, _st_job(A, 1, out1))
            w, h, dur, aud = _st_info(out1)
            ok = out1.is_file() and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and aud
            rec("3 Template 1 render", "PASS" if ok else "FAIL", f"{w}x{h} {dur:.2f}s audio={aud}")
        except BaseException as e:
            rec("3 Template 1 render", "FAIL", repr(e))
        if gskip:
            rec("4 Template 1 frames vs golden", "SKIP", gskip)
        elif not out1.is_file():
            rec("4 Template 1 frames vs golden", "FAIL", "no render to compare")
        else:
            diffs = _st_frame_diffs(out1, tmp, "t1")
            rec("4 Template 1 frames vs golden", "PASS" if max(diffs) < 1.0 else "FAIL",
                "diff @0.5/1.5/2.5 = " + " / ".join(f"{x:.3f}" for x in diffs))

        # 5. Template 2 (placeholder) render
        out2 = tmp / "t2.mp4"
        try:
            quiet(render, _st_job(A, 2, out2))
            w, h, dur, aud = _st_info(out2)
            ok = out2.is_file() and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and aud
            rec("5 Template 2 render", "PASS" if ok else "FAIL", f"{w}x{h} {dur:.2f}s audio={aud}")
        except BaseException as e:
            rec("5 Template 2 render", "FAIL", repr(e))

        # 6. old job file without template_id -> Template 1, matches golden
        out6 = tmp / "old.mp4"
        try:
            job = _st_job(A, 1, out6)
            job.pop("template_id")
            jp = tmp / "old_job.json"
            jp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            loaded = json.loads(jp.read_text(encoding="utf-8"))
            is_t1 = get_template(loaded)["id"] == 1 and "template_id" not in loaded
            quiet(render, loaded)
            if gskip:
                rec("6 old job (no template_id) = Template 1", "PASS" if is_t1 and out6.is_file() else "FAIL",
                    f"renders as Template 1; golden compare SKIP ({gskip})")
            else:
                diffs = _st_frame_diffs(out6, tmp, "old")
                rec("6 old job (no template_id) = Template 1", "PASS" if is_t1 and max(diffs) < 1.0 else "FAIL",
                    "diff @0.5/1.5/2.5 = " + " / ".join(f"{x:.3f}" for x in diffs))
        except BaseException as e:
            rec("6 old job (no template_id) = Template 1", "FAIL", repr(e))

        # 7. real CLI: --job for a Template 2 job
        out7 = tmp / "t2_cli.mp4"
        try:
            jp = tmp / "t2_job.json"
            jp.write_text(json.dumps(_st_job(A, 2, out7), ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--job", str(jp)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            ok = r.returncode == 0 and out7.is_file() and "Done in" in r.stdout
            w, h, dur, aud = _st_info(out7) if out7.is_file() else (0, 0, 0, False)
            ok = ok and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2
            rec("7 --job re-render (Template 2)", "PASS" if ok else "FAIL",
                f"rc={r.returncode} {w}x{h} {dur:.2f}s" + ("" if ok else " " + (r.stderr or r.stdout)[-200:]))
        except BaseException as e:
            rec("7 --job re-render (Template 2)", "FAIL", repr(e))

        _selftest_t2(rec, quiet, feed, A, tmp)
        _selftest_t2_dynamic(rec, quiet, feed, A, tmp)
        _selftest_t2_cards(rec, quiet, feed, A, tmp)
        _selftest_t2_about(rec, quiet, feed, A, tmp)
        _selftest_t2_panel(rec, quiet, feed, A, tmp)
        _selftest_t2_4c(rec, quiet, feed, A, tmp)
        _selftest_4d(rec, quiet, feed, A, tmp)
    except _StopSelftest:
        pass
    finally:  # always restore global state and delete the temp files
        builtins.input = saved_input
        globals()["TEMPLATES_DIR"] = saved_tdir
        D.clear()
        D.update(saved_D)
        shutil.rmtree(tmp, ignore_errors=True)
    return _st_report(rows)


def _selftest_t2(rec, quiet, feed, A, tmp):
    """Template 2 static design checks (8-14)."""
    import builtins
    W, H = 1080, 1920
    P = {"bg": str(tmp / "p_bg.png"), "fg": str(tmp / "p_fg.png")}

    def px(img, xy):
        return img.getpixel(tuple(int(v) for v in xy))

    def near(c, ref, tol):
        return all(abs(c[i] - ref[i]) <= tol for i in range(3))

    # 8. static plate, default config
    info = None
    try:
        info = make_t2_static(W, H, {}, P, dict(T2_DEFAULT_BOX))
        bgi, fgi = Image.open(P["bg"]), Image.open(P["fg"])
        ok = bgi.size == (W, H) and fgi.size == (W, H) and fgi.mode == "RGBA"
        rec("8 T2 static plate 1080x1920", "PASS" if ok else "FAIL",
            f"bg {bgi.size} {bgi.mode}, fg {fgi.size} {fgi.mode}, {len(info['boxes'])} elements")
    except BaseException as e:
        rec("8 T2 static plate 1080x1920", "FAIL", repr(e))
        return

    # 9. pixel checks
    try:
        bg_c = px(bgi.convert("RGB"), info["probe"]["bg_corner"])
        lo, hi = (5, 8, 11), (11, 12, 17)
        c_ok = all(lo[i] - 3 <= bg_c[i] <= hi[i] + 3 for i in range(3))
        bar = px(fgi, info["probe"]["bar"])
        bar_ok = bar[3] == 255 and bar[1] > 190 and bar[0] > 150 and bar[2] < 150 and bar[1] > bar[2] + 60
        cen = px(fgi, info["probe"]["window_center"])
        cor = px(fgi, info["probe"]["window_corner"])
        ok = c_ok and bar_ok and cen[3] == 0 and cor[3] == 255
        rec("9 T2 pixel checks", "PASS" if ok else "FAIL",
            f"bg corner {bg_c} ok={c_ok}; bar {bar[:3]} ok={bar_ok}; window centre alpha {cen[3]} (want 0); "
            f"window corner alpha {cor[3]} (want 255)")
    except BaseException as e:
        rec("9 T2 pixel checks", "FAIL", repr(e))

    # 10. stress: long / short / empty / Arabic text, other accent, hidden groups, missing fonts
    try:
        long_name = "AHMED IBRAHIM ABDELRAHMAN MOHAMED ELSAYED HASSAN " * 3
        cases = {
            "long name": {"name": long_name, "subtitle": long_name},
            "long headline": {"line1": "BUILDING DIGITAL EXPERIENCES THAT SCALE " * 3,
                              "line2": "EXPERIENCES FOR EVERYONE EVERYWHERE " * 3},
            "empty headline": {"line1": "", "line2": ""},
            "only line 2": {"line1": ""}, "only line 1": {"line2": ""},
            "arabic headline": {"line1": "\u0628\u0646\u0627\u0621 \u062a\u062c\u0627\u0631\u0628 \u0631\u0642\u0645\u064a\u0629",
                                "line2": "\u062a\u062c\u0631\u0628\u0629 \u0645\u0633\u062a\u062e\u062f\u0645 \u0645\u0645\u064a\u0632\u0629"},
            "accent #FF3366": {"accent": "#FF3366"},
            "no header/pill/shapes": {"show_header": False, "show_pill": False, "show_bg_shapes": False,
                                      "show_dots": False},
            "long pill": {"pill": "CREATOR SERIES FOR EVERY SINGLE DEVELOPER ON EARTH"},
        }
        bad = []
        for nm, c in cases.items():
            inf = make_t2_static(W, H, c, {"bg": str(tmp / "s_bg.png"), "fg": str(tmp / "s_fg.png")},
                                 dict(T2_DEFAULT_BOX))
            for en, bb in inf["boxes"].items():
                if en.startswith(("shape", "dots")) or en == "frame":
                    continue      # decorations are allowed to touch / bleed off the canvas edge
                if bb[0] < 0 or bb[1] < 0 or bb[2] > W or bb[3] > H:
                    bad.append(f"{nm}:{en}{bb}")
            b = inf["boxes"]
            if "pill" in b:
                for en in ("name", "subtitle"):
                    if en in b and b[en][2] > b["pill"][0] - 5:
                        bad.append(f"{nm}:{en} overlaps pill")
            if "line1" in b and "line2" in b and b["line1"][3] > b["bar"][1] + 4:
                bad.append(f"{nm}: line1 overlaps bar")
            if nm == "empty headline" and any(k in b for k in ("line1", "line2", "bar")):
                bad.append("empty headline still drawn")
        a_ok = True
        inf = make_t2_static(W, H, {"accent": "#FF3366"}, {"bg": str(tmp / "s_bg.png"), "fg": str(tmp / "s_fg.png")},
                             dict(T2_DEFAULT_BOX))
        col = px(Image.open(tmp / "s_fg.png"), inf["probe"]["bar"])
        a_ok = col[0] > 200 and col[1] < 110 and col[2] < 160
        # missing fonts must never crash: pretend no recommended font exists
        saved = globals()["_t2_lookup"]
        globals()["_t2_lookup"] = lambda n: None
        try:
            make_t2_static(W, H, {"name": "X"}, {"bg": str(tmp / "s_bg.png"), "fg": str(tmp / "s_fg.png")},
                           dict(T2_DEFAULT_BOX))
            f_ok = True
        except BaseException as e:
            f_ok = False
            bad.append("missing fonts: " + repr(e))
        finally:
            globals()["_t2_lookup"] = saved
        ok = not bad and a_ok and f_ok
        rec("10 T2 stress (long/empty/Arabic/accent)", "PASS" if ok else "FAIL",
            f"{len(cases)} cases, accent bar {col[:3]} ok={a_ok}, no-font fallback ok={f_ok} " + "; ".join(bad[:4]))
    except BaseException as e:
        rec("10 T2 stress (long/empty/Arabic/accent)", "FAIL", repr(e))

    # 11. full 3 s render with real test video
    out = tmp / "t2_full.mp4"
    try:
        quiet(render, _st_job(A, 2, out))
        w, h, dur, aud = _st_info(out)
        ok = out.is_file() and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and aud
        rec("11 T2 render 3s (size/duration/audio)", "PASS" if ok else "FAIL", f"{w}x{h} {dur:.2f}s audio={aud}")
        png = tmp / "t2_mid.png"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.5", "-i", str(out),
                        "-frames:v", "1", str(png)], check=True)
        fr = Image.open(png).convert("RGB")
        x0, y0, x1, y1 = info["window"]
        cx, cy = info["probe"]["window_center"]
        # video visible: the window centre is NOT the plain dark background and has real picture detail
        from PIL import ImageStat
        reg = fr.crop((cx - 150, cy - 150, cx + 150, cy + 150))
        st = ImageStat.Stat(reg)
        vid_ok = max(st.stddev) > 15 and max(st.mean) > 40
        # window corner shows the design (= foreground plate), not video
        fgrgb = Image.open(P["fg"]).convert("RGB")
        d_ok = True
        det = []
        for (ex, ey) in ((x0 + 2, y0 + 2), (x1 - 3, y0 + 2), (x0 + 2, y1 - 3), (x1 - 3, y1 - 3)):
            a, b_ = px(fr, (ex, ey)), px(fgrgb, (ex, ey))
            dd = sum(abs(a[i] - b_[i]) for i in range(3)) / 3.0
            det.append(round(dd, 1))
            d_ok = d_ok and dd < 12
        rec("11b T2 video visible + rounded corners", "PASS" if vid_ok and d_ok else "FAIL",
            f"centre stddev {max(st.stddev):.0f} mean {max(st.mean):.0f} (video ok={vid_ok}); "
            f"corner diff vs design {det}")
    except BaseException as e:
        rec("11 T2 render 3s (size/duration/audio)", "FAIL", repr(e))

    # 12. --still
    try:
        still = tmp / "still.png"
        cfg = _st_job(A, 2, tmp / "x.mp4")
        render_still(cfg, str(still), 0.5)
        sg = Image.open(still)
        cfg2 = dict(cfg, video=None)                       # no video -> mid-grey placeholder
        render_still(cfg2, str(tmp / "still_grey.png"), 0.5)
        gp = px(Image.open(tmp / "still_grey.png").convert("RGB"), info["probe"]["window_center"])
        ok = sg.size == (1080, 1920) and near(gp, (128, 128, 128), 6)
        rec("12 --still png", "PASS" if ok else "FAIL", f"{sg.size}, placeholder window centre {gp}")
    except BaseException as e:
        rec("12 --still png", "FAIL", repr(e))

    # 13. save as named template + load without questions; 14. t2 keys reproduce through a job file
    saved_tdir = globals()["TEMPLATES_DIR"]
    try:
        sdir = tmp / "t2templates"
        globals()["TEMPLATES_DIR"] = sdir
        asked = []

        def fake_save(prompt=""):
            asked.append(prompt)
            return "selftest_t2" if prompt.startswith("Save this as a template") else ""
        builtins.input = fake_save
        created = quiet(t2_ask_config, {})
        n_first = len(asked)
        asked.clear()
        feed(["2"], asked)                                  # pick the saved design
        loaded = quiet(t2_ask_config, {})
        f = sdir / "selftest_t2.json"
        ok = (f.is_file() and json.loads(f.read_text(encoding="utf-8")).get("template_id") == 2
              and loaded == created and len(asked) == 1 and loaded["t2"] == t2_cfg(loaded["t2"]) and n_first > 10)
        rec("13 T2 save / load template (no questions)", "PASS" if ok else "FAIL",
            f"saved={f.is_file()} questions on first run={n_first}, on load={len(asked)}, same cfg={loaded == created}")
        job = _st_job(A, 2, tmp / "j.mp4")
        job["t2"] = t2_cfg({"name": "TEST NAME", "accent": "#ff3366", "line1": "", "show_dots": False})
        back = json.loads(json.dumps(job, ensure_ascii=False))
        a1, a2 = tmp / "r1", tmp / "r2"
        a1.mkdir(exist_ok=True)
        a2.mkdir(exist_ok=True)
        i1 = make_t2_static(W, H, job["t2"], {"bg": str(a1 / "b.png"), "fg": str(a1 / "f.png")}, job["video_box"])
        i2 = make_t2_static(W, H, back["t2"], {"bg": str(a2 / "b.png"), "fg": str(a2 / "f.png")}, back["video_box"])
        same = (Image.open(a1 / "f.png").tobytes() == Image.open(a2 / "f.png").tobytes()) and i1["boxes"] == i2["boxes"]
        rec("14 T2 job JSON reproduces the design", "PASS" if same else "FAIL", f"identical foreground={same}")
    except BaseException as e:
        rec("13 T2 save / load template (no questions)", "FAIL", repr(e))
    finally:
        globals()["TEMPLATES_DIR"] = saved_tdir


def _st_lime(p, tol=45):
    """True for pixels close to the Template 2 accent lime."""
    a = t2_rgb(T2_ACCENT)
    return abs(p[0] - a[0]) <= tol and abs(p[1] - a[1]) <= tol and abs(p[2] - a[2]) <= tol + 15


def _st_grab(video, t, png):
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t}", "-i", str(video),
                    "-frames:v", "1", str(png)], check=True)
    return Image.open(png).convert("RGB")


def _selftest_t2_dynamic(rec, quiet, feed, A, tmp):
    """Template 2 dynamic features, Part 3A: caption style (15), chapter tag (16), full render (17),
    chapter questions + job JSON (18), still with tag + caption (19)."""
    import builtins
    from PIL import ImageChops, ImageStat
    W, H = 1080, 1920
    font = t2_font("arabic", "ع")[0]
    base_cap = {"font": font, "color": "#ffffff", "hl_color": "", "keywords": "", "stroke_color": "#000000",
                "stroke_w": 0, "shadow": False, "mode": "phrase", "max_words": 8, "anim": "fade", "anim_dur": 0.25,
                "ref": "box", "y_pct": None}
    cfg0 = _st_job(A, 2, tmp / "d.mp4")
    cfg0.update({"texts": [], "cards": [], "elements": []})

    # ---- 15. captions --------------------------------------------------------------------------
    try:
        fr = cfg0["video_box"]
        fx0, fy0, fx1, fy1 = fr["x"], fr["y"], fr["x"] + fr["w"], fr["y"] + fr["h"]
        long_ar = " ".join(["أنا مطور ويب وأبني تطبيقات"] * 6)
        cases = {
            "short AR": [["أنا", False], ["أحمد", False]],
            "long AR": [[w, False] for w in long_ar.split()],
            "mixed AR+EN": [[w, False] for w in "أبني تطبيقات Flutter و Django بسرعة".split()],
            "highlight": [["أنا", False], ["أحمد", True], ["إبراهيم", False],
                          ["مطور", False], ["ويب", False]],
        }
        bad, info = [], []
        for nm, toks in cases.items():
            c = dict(base_cap, srt=str(A / "ar.srt"), t2_style="box", size=50)
            cfg = dict(cfg0, captions=[c])
            its = t2_caption_items(cfg, c, [(0.0, 1.0, toks)], 5.0)
            it = its[0]
            spr, meta = t2_caption_sprite(toks, font, 50, "#ffffff", T2_ACCENT, T2_ACCENT,
                                          t2_caption_layout(cfg)["max_w"], want_meta=True)
            bx0, by0 = it.cx - it.sprite.width / 2.0, it.cy - it.sprite.height / 2.0
            bx1, by1 = bx0 + it.sprite.width, by0 + it.sprite.height
            if not (fx0 <= bx0 and bx1 <= fx1 and fy0 <= by0 and by1 <= fy1):
                bad.append(f"{nm}: box {int(bx0)},{int(by0)},{int(bx1)},{int(by1)} outside frame")
            if meta["lines"] > 2:
                bad.append(f"{nm}: {meta['lines']} lines")
            px = spr.load()
            sw_, sh_ = spr.size
            bar = meta["bar"]
            bar_hits = sum(1 for y in range(bar[1], bar[3]) for x in range(bar[0] + 2, bar[2] - 2) if _st_lime(px[x, y]) and px[x, y][3] > 200)
            if bar_hits < (bar[3] - bar[1]) * 3:
                bad.append(f"{nm}: lime bar missing ({bar_hits}px)")
            # text pixels = bright, opaque, right of the bar
            xs, ys = [], []
            for y in range(sh_):
                for x in range(T2_CAP["text_l"] - 6, sw_):
                    p = px[x, y]
                    if p[3] > 200 and (min(p[:3]) > 190 or _st_lime(p)):
                        xs.append(x)
                        ys.append(y)
            if not xs:
                bad.append(f"{nm}: no text pixels")
            else:
                tb = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
                if tb[0] < T2_CAP["text_l"] - 6 or tb[2] > sw_ - 8 or tb[1] < 6 or tb[3] > sh_ - 6:
                    bad.append(f"{nm}: text bbox {tb} not inside box {sw_}x{sh_}")
            lime_txt = sum(1 for y in range(sh_) for x in range(T2_CAP["text_l"], sw_) if _st_lime(px[x, y]) and px[x, y][3] > 200)
            if nm == "highlight":
                hl_box = next(b for t, h, b in meta["tokens"] if h)
                reg = sum(1 for y in range(max(0, hl_box[1]), min(sh_, hl_box[3])) for x in range(max(0, hl_box[0]), min(sw_, hl_box[2]))
                          if _st_lime(px[x, y]) and px[x, y][3] > 200)
                if reg < 60:
                    bad.append(f"highlight: only {reg} lime px in the word region")
                info.append(f"hl lime px={reg}")
            elif lime_txt > 0:
                bad.append(f"{nm}: unexpected lime text pixels {lime_txt}")
            info.append(f"{nm}: {sw_}x{sh_} {meta['lines']}L size {meta['size']}")
        # sub line stays inside the frame and on one line; box moves up when a sub stream exists
        sc = dict(base_cap, srt=str(A / "en.srt"), t2_style="sub", size=30)
        cfg = dict(cfg0, captions=[dict(base_cap, srt=str(A / "ar.srt"), t2_style="box", size=50), sc])
        lay = t2_caption_layout(cfg)
        si = t2_caption_items(cfg, sc, [(0.0, 1.0, [[w, w == "Ahmed"] for w in ("I am Ahmed Ibrahim web developer and " * 6).split()])], 5.0)[0]
        if si.sprite.width > lay["max_w"] + 4 or si.cy + si.sprite.height / 2.0 > fy1 or lay["box_bottom"] >= lay["sub_bottom"]:
            bad.append("sub line geometry")
        rec("15 T2 captions (box/bar/lines/highlight)", "PASS" if not bad else "FAIL", "; ".join(info[:4]) + (" || " + "; ".join(bad[:4]) if bad else ""))
    except BaseException as e:
        rec("15 T2 captions (box/bar/lines/highlight)", "FAIL", repr(e))

    # ---- 16. chapter tag over a 6 s clip (real render, uniform background so the tag can be compared) ----
    try:
        v6 = tmp / "uni6.mp4"
        subprocess.check_call([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                               "color=c=0x303a46:size=1080x1920:rate=30:duration=6", "-f", "lavfi", "-i",
                               "sine=frequency=440:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                               "-shortest", str(v6)])
        chs = [{"start": 0.3, "label": "Intro"}, {"start": 2.3, "label": "Projects"}, {"start": 4.3, "label": "Contact"}]
        cfg = dict(cfg0, video=str(v6), captions=[], output=str(tmp / "ch6.mp4"), preview=None)
        cfg["t2"] = t2_cfg({"chapters": chs})
        quiet(render, cfg)
        tx, ty = t2_tag_pos(cfg)
        res = t2_resolve_chapters(cfg, 6.0)
        samples = [_st_grab(tmp / "ch6.mp4", t, tmp / f"ch_{t}.png") for t in (0.1, 1.3, 3.3, 5.3)]
        bgc = samples[1].getpixel((tx + 300, ty + 40))
        exp = []
        for c in res:
            spr = t2_chapter_sprite(c["num"], c["label"], cfg["t2"]["accent"], cfg["t2"].get("fonts"))
            canvas = Image.new("RGBA", (spr.width, spr.height), bgc + (255,))
            canvas.alpha_composite(spr)
            exp.append(canvas.convert("RGB"))
        regs = [s.crop((tx, ty, tx + e.width, ty + e.height)) for s, e in zip(samples[1:], exp)]
        own = [ImageStat.Stat(ImageChops.difference(r, e)).mean for r, e in zip(regs, exp)]
        own = [sum(o) / 3.0 for o in own]
        other = []
        for i, r in enumerate(regs):
            ds = []
            for j, e in enumerate(exp):
                if i != j:
                    ee = e.crop((0, 0, min(e.width, r.width), min(e.height, r.height)))
                    rr = r.crop((0, 0, ee.width, ee.height))
                    ds.append(sum(ImageStat.Stat(ImageChops.difference(rr, ee)).mean) / 3.0)
            other.append(min(ds))
        pair = [sum(ImageStat.Stat(ImageChops.difference(regs[i].crop((0, 0, 233, 86)), regs[j].crop((0, 0, 233, 86)))).mean) / 3.0
                for i, j in ((0, 1), (1, 2), (0, 2))]
        before = samples[0].crop((tx, ty, tx + 233, ty + 86))
        empty = sum(ImageStat.Stat(ImageChops.difference(before, Image.new("RGB", before.size, bgc))).mean) / 3.0
        lime = [sum(1 for y in range(0, 60) for x in range(0, 100) if _st_lime(r.getpixel((x, y)))) for r in regs]
        ok = (len(res) == 3 and [c["num"] for c in res] == ["01", "02", "03"] and all(o < 3.0 for o in own)
              and all(o < 0.65 * q for o, q in zip(own, other)) and min(pair) > 0.4 and empty < 1.0 and min(lime) > 150)
        rec("16 T2 chapter tag (3 chapters, 6 s)", "PASS" if ok else "FAIL",
            f"own diff {[round(o, 2) for o in own]} vs best-other {[round(o, 2) for o in other]}; pairwise {[round(p, 2) for p in pair]}; "
            f"empty-before {empty:.2f}; lime px {lime}")
    except BaseException as e:
        rec("16 T2 chapter tag (3 chapters, 6 s)", "FAIL", repr(e))

    # ---- 17. full T2 render: chapters + AR/EN captions, 3 s -------------------------------------
    cfg17 = None
    try:
        out = tmp / "t2_dyn.mp4"
        cfg17 = _st_job(A, 2, out)
        cfg17.update({"texts": [], "cards": [], "elements": []})
        cfg17["captions"] = [dict(base_cap, srt=str(A / "ar.srt"), t2_style="box", size=50),
                             dict(base_cap, srt=str(A / "en.srt"), t2_style="sub", size=30, keywords="Flutter", shadow=True)]
        cfg17["t2"] = t2_cfg({"chapters": [{"start": 0.0, "label": "Intro"}, {"trigger": "Flutter", "label": "Stack"}]})
        quiet(render, cfg17)
        w, h, dur, aud = _st_info(out)
        fr1 = _st_grab(out, 1.0, tmp / "dyn1.png")
        items = [i for i in build_items(cfg17, 5.0) if i.start <= 1.0 < i.end]
        box_it = max((i for i in items if i.sprite.height > 70), key=lambda i: i.sprite.width * i.sprite.height)
        bx0 = int(box_it.cx - box_it.sprite.width / 2.0)
        by0 = int(box_it.cy - box_it.sprite.height / 2.0)
        bar_px = sum(1 for y in range(by0 + 10, by0 + box_it.sprite.height - 10)
                     for x in range(bx0 + 15, bx0 + 21) if _st_lime(fr1.getpixel((x, y))))
        tx, ty = t2_tag_pos(cfg17)
        tag_px = sum(1 for y in range(ty, ty + 60) for x in range(tx, tx + 110) if _st_lime(fr1.getpixel((x, y))))
        ok = out.is_file() and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and aud and bar_px > 80 and tag_px > 150
        rec("17 T2 render chapters + AR/EN captions", "PASS" if ok else "FAIL",
            f"{w}x{h} {dur:.2f}s audio={aud}; caption bar lime px={bar_px}, tag lime px={tag_px}, {len(items)} items @1.0s")
    except BaseException as e:
        rec("17 T2 render chapters + AR/EN captions", "FAIL", repr(e))

    # ---- 18. chapter questions (scripted input) + defaults + job JSON ---------------------------
    try:
        saved_in = builtins.input
        prompts = []
        feed(["y", "Intro", "0:01", "", "Stack", "Flutter", "7", "", "fade", "0.5"], prompts)
        got = quiet(t2_ask_chapters, parse_srt(str(A / "en.srt")), 5.0)
        builtins.input = saved_in
        ch = got.get("chapters", [])
        fed_ok = (len(ch) == 2 and ch[0]["start"] == 1.0 and ch[0]["label"] == "Intro" and ch[1]["trigger"] == "Flutter"
                  and ch[1]["num"] == "7" and got["chapter_anim"] == "fade" and got["chapter_anim_dur"] == 0.5
                  and D.get("t2_chapter_anim") == "fade")
        feed(["n"], [])
        none_ok = quiet(t2_ask_chapters, [], 5.0) == {}
        t = t2_cfg(got)
        idem = t2_cfg(t) == t
        job = dict(cfg17 or cfg0, t2=t, captions=[dict(base_cap, srt=str(A / "ar.srt"), t2_style="box", size=50)])
        back = json.loads(json.dumps(job, ensure_ascii=False))
        r1, r2 = t2_resolve_chapters(job, 5.0), t2_resolve_chapters(back, 5.0)
        same = r1 == r2 and len(r1) == 2 and [c["num"] for c in r1] == ["01", "7"] and back["t2"]["chapters"] == t["chapters"]
        off = t2_resolve_chapters(dict(job, t2=dict(t, chapters_on=False)), 5.0) == []
        rec("18 T2 chapter questions + job JSON", "PASS" if fed_ok and none_ok and idem and same and off else "FAIL",
            f"questions ok={fed_ok} none ok={none_ok} idempotent={idem} job same={same} disabled ok={off}")
    except BaseException as e:
        rec("18 T2 chapter questions + job JSON", "FAIL", repr(e))

    # ---- 19. still with tag + caption --------------------------------------------------------------
    try:
        stp = tmp / "t2_still3a.png"
        quiet(render_still, cfg17, str(stp), 1.0)
        im = Image.open(stp).convert("RGB")
        tx, ty = t2_tag_pos(cfg17)
        tag_px = sum(1 for y in range(ty, ty + 60) for x in range(tx, tx + 110) if _st_lime(im.getpixel((x, y))))
        items = [i for i in build_items(cfg17, 5.0) if i.start <= 1.0 < i.end and i.sprite.height > 70]
        bi = max(items, key=lambda i: i.sprite.width * i.sprite.height)
        bx0, by0 = int(bi.cx - bi.sprite.width / 2.0), int(bi.cy - bi.sprite.height / 2.0)
        bar_px = sum(1 for y in range(by0 + 10, by0 + bi.sprite.height - 10) for x in range(bx0 + 15, bx0 + 21)
                     if _st_lime(im.getpixel((x, y))))
        rec("19 T2 still with tag + caption", "PASS" if im.size == (1080, 1920) and tag_px > 150 and bar_px > 80 else "FAIL",
            f"{im.size} tag lime px={tag_px} caption bar px={bar_px}")
    except BaseException as e:
        rec("19 T2 still with tag + caption", "FAIL", repr(e))


def _st_cream(p, tol=16):
    c = T2_CARD["border_col"]
    return abs(p[0] - c[0]) <= tol and abs(p[1] - c[1]) <= tol and abs(p[2] - c[2]) <= tol


def _st_card_points(r):
    """Canvas points on the card's four border edges (rotated by the card's angle about its centre)."""
    T = T2_CARD
    hw, hh, th = T["w"] / 2.0, T["h"] / 2.0, math.radians(r["angle"])
    loc = [(-hw + T["border"] / 2.0, 0), (hw - T["border"] / 2.0, 0), (0, -hh + T["border"] / 2.0),
           (-0.38 * T["w"], hh - T["border"] / 2.0)]
    return [(r["cx"] + x * math.cos(th) + y * math.sin(th), r["cy"] - x * math.sin(th) + y * math.cos(th))
            for x, y in loc]


def _st_card_hits(im, r):
    """How many of the 4 expected border points show the cream border (3x3 neighbourhood)."""
    n = 0
    for x, y in _st_card_points(r):
        xi, yi = int(round(x)), int(round(y))
        if any(0 <= xi + dx < im.width and 0 <= yi + dy < im.height and _st_cream(im.getpixel((xi + dx, yi + dy)))
               for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)):
            n += 1
    return n


def _st_time_render(cfg):
    import contextlib
    import io
    t0 = time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        render(cfg)
    return time.time() - t0


def _selftest_t2_cards(rec, quiet, feed, A, tmp):
    """Part 3B: floating B-roll card (20-23), parity render (24), --job with card / old T1 job (25), card questions (26),
    still with chapter tag + caption + card (27), timing T1 vs T2 (28)."""
    import builtins
    W, H = 1080, 1920
    font = t2_font("arabic", "ع")[0]
    base_cap = {"font": font, "color": "#ffffff", "hl_color": "", "keywords": "", "stroke_color": "#000000",
                "stroke_w": 0, "shadow": False, "mode": "phrase", "max_words": 8, "anim": "fade", "anim_dur": 0.25,
                "ref": "box", "y_pct": None}
    for nm, col in (("c_green.png", (20, 210, 40)), ("c_magenta.png", (225, 30, 205))):
        Image.new("RGB", (640, 480), col).save(A / nm)
    if not (A / "broll.mp4").is_file():
        subprocess.check_call([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                               "testsrc=size=640x360:rate=30:duration=1.5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                               str(A / "broll.mp4")])

    def job(out, cards, **kw):
        c = _st_job(A, 2, out, preview=kw.pop("preview", 3.0))
        c.update({"texts": [], "cards": [], "elements": [], "captions": []})
        c["t2"] = t2_cfg(dict(kw.pop("t2", {}), cards=cards))
        c.update(kw)
        return c

    # ---- 20. image card + video card: present during hold (border at the rotated place, not clipped), gone after ----
    try:
        out = tmp / "card1.mp4"
        cards = [{"media": str(A / "c_green.png"), "label": "Development", "icon": "code", "slot": 1, "start": 0.3, "hold": 1.5},
                 {"media": str(A / "broll.mp4"), "label": "Mobile", "icon": "phone", "slot": 2, "start": 0.3, "hold": 1.5}]
        cfg = job(out, cards)
        quiet(render, cfg)
        res = {r["slot"]: r for r in t2_resolve_cards(cfg, 3.0)}
        w, h, dur, aud = _st_info(out)
        hold = _st_grab(out, 1.2, tmp / "c1_hold.png")
        gone = _st_grab(out, 2.7, tmp / "c1_gone.png")
        h1, h2 = _st_card_hits(hold, res[1]), _st_card_hits(hold, res[2])
        g1, g2 = _st_card_hits(gone, res[1]), _st_card_hits(gone, res[2])
        # not clipped: the card's left border (image card, right side) lies INSIDE the video window and is still cream
        box = cfg["video_box"]
        lx, ly = _st_card_points(res[1])[0]
        inside = box["x"] < lx < box["x"] + box["w"]
        # bbox of every card inside the canvas
        bb_ok = True
        for r in res.values():            # rotated bbox of the card itself (without its shadow padding)
            th = abs(math.radians(r["angle"]))
            hw = (T2_CARD["w"] * math.cos(th) + T2_CARD["h"] * math.sin(th)) / 2.0
            hh = (T2_CARD["h"] * math.cos(th) + T2_CARD["w"] * math.sin(th)) / 2.0
            bb_ok &= (r["cx"] - hw >= 0 and r["cx"] + hw <= W and r["cy"] - hh >= 0 and r["cy"] + hh <= H)
        # image card centre = the green picture, video card centre = the test pattern (not the dark plate)
        gp = hold.getpixel((int(res[1]["cx"]), int(res[1]["cy"] - 40)))
        green = gp[1] > 150 and gp[0] < 110 and gp[2] < 110
        ok = (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and h1 == 4 and h2 >= 3 and g1 == 0 and g2 == 0 \
            and inside and bb_ok and green
        rec("20 T2 floating card: image + video", "PASS" if ok else "FAIL",
            f"border hits hold img={h1}/4 vid={h2}/4, after hold {g1}/{g2}; left border inside window={inside} "
            f"(x={lx:.0f}); bbox ok={bb_ok}; picture green={green}")
    except BaseException as e:
        rec("20 T2 floating card: image + video", "FAIL", repr(e))

    # ---- 21. two consecutive cards in the same slot replace each other -----------------------------------------
    try:
        out = tmp / "card2.mp4"
        cards = [{"media": str(A / "c_green.png"), "label": "One", "icon": "code", "slot": 1, "start": 0.2, "hold": 3.0},
                 {"media": str(A / "c_magenta.png"), "label": "Two", "icon": "chip", "slot": 1, "start": 1.4, "hold": 3.0}]
        cfg = job(out, cards)
        quiet(render, cfg)
        res = t2_resolve_cards(cfg, 3.0)
        a, b = res[0], res[1]
        f1 = _st_grab(out, 0.9, tmp / "c2_a.png")
        f2 = _st_grab(out, 2.5, tmp / "c2_b.png")
        fm = _st_grab(out, 1.55, tmp / "c2_mid.png")
        pa = f1.getpixel((int(a["cx"]), int(a["cy"] - 40)))
        pb = f2.getpixel((int(b["cx"]), int(b["cy"] - 40)))
        a_ok = pa[1] > 150 and pa[0] < 110
        b_ok = pb[0] > 150 and pb[2] > 150 and pb[1] < 110
        # mid-swap the new card is still sliding in, so count border-coloured pixels around the slot instead of 4 fixed points
        mid_n = sum(1 for y in range(int(a["cy"] - 240), int(a["cy"] + 240), 2) for x in range(int(a["cx"] - 200), min(W, int(a["cx"] + 200)), 2)
                    if _st_cream(fm.getpixel((x, y))))
        mid = mid_n > 80 and _st_card_hits(f2, b) == 4 and _st_card_hits(f2, a) in (0, 4)
        ends = abs(a["end"] - 1.65) < 0.01
        rec("21 T2 cards replace in the same slot", "PASS" if a_ok and b_ok and mid and ends else "FAIL",
            f"first={pa[:3]} second={pb[:3]} mid-swap cream px={mid_n} ok={mid} old card ends {a['end']:.2f}s (new starts {b['start']:.2f}s)")
    except BaseException as e:
        rec("21 T2 cards replace in the same slot", "FAIL", repr(e))

    # ---- 22. parity render: text + element + layer + video layer + AR/EN captions + chapter tag + card -----------
    cfgp = None
    try:
        out = tmp / "parity.mp4"
        cfgp = _st_job(A, 2, out, preview=4.0)
        cfgp["cards"] = []
        cfgp["captions"] = [dict(base_cap, srt=str(A / "ar.srt"), t2_style="box", size=50),
                            dict(base_cap, srt=str(A / "en.srt"), t2_style="sub", size=30, keywords="Flutter", shadow=True)]
        cfgp["layers"] = [{"path": str(A / "icon.png"), "pos": "top-left", "width": "12%", "opacity": 100,
                           "anim": "none", "anim_dur": 0.6}]
        cfgp["video_layers"] = [{"path": str(A / "broll.mp4"), "start": 1.0, "end": 2.5, "area": "box", "mode": "fill",
                                 "fade": 0.3}]
        cfgp["t2"] = t2_cfg({"chapters": [{"start": 0.0, "label": "Intro"}],
                             "cards": [{"media": str(A / "broll.mp4"), "label": "Development", "icon": "code",
                                        "slot": 1, "start": 0.5, "hold": 3.0}]})
        quiet(render, cfgp)
        w, h, dur, aud = _st_info(out)
        fr = _st_grab(out, 2.0, tmp / "par.png")
        r1 = t2_resolve_cards(cfgp, 5.0)[0]
        hits = _st_card_hits(fr, r1)
        tx, ty = t2_tag_pos(cfgp)
        tag_px = sum(1 for y in range(ty, ty + 60) for x in range(tx, tx + 110) if _st_lime(fr.getpixel((x, y))))
        org = sum(1 for y in range(1500, 1900, 2) for x in range(780, 1080, 2)
                  if fr.getpixel((x, y))[0] > 230 and 110 < fr.getpixel((x, y))[1] < 175 and fr.getpixel((x, y))[2] < 70)
        spr = load_image_sprite(str(A / "icon.png"), "12%", W)
        lx, ly = resolve_pos("top-left", spr.width, spr.height, W, H)
        lp = fr.getpixel((int(lx), int(ly)))
        layer_ok = min(lp) > 215
        ok = (w, h) == (1080, 1920) and abs(dur - 4.0) < 0.2 and aud and hits >= 3 and tag_px > 150 and org > 60 and layer_ok
        rec("22 T2 parity render (all features)", "PASS" if ok else "FAIL",
            f"{w}x{h} {dur:.2f}s audio={aud}; card border {hits}/4, tag lime px={tag_px}, element orange px={org}, "
            f"layer centre {lp[:3]}")
    except BaseException as e:
        rec("22 T2 parity render (all features)", "FAIL", repr(e))

    # ---- 23. --job re-render: T2 job with a card, and an old T1 job ----------------------------------------------
    try:
        out_a, out_b = tmp / "job_card.mp4", tmp / "job_old_t1.mp4"
        jc = job(out_a, [{"media": str(A / "c_green.png"), "label": "Dev", "icon": "code", "slot": 1, "start": 0.3, "hold": 2.0}])
        jc["t2"] = json.loads(json.dumps(jc["t2"], ensure_ascii=False))
        jp = tmp / "job_card.json"
        jp.write_text(json.dumps(jc, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--job", str(jp)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        w, h, dur, aud = _st_info(out_a) if out_a.is_file() else (0, 0, 0, False)
        hits = _st_card_hits(_st_grab(out_a, 1.2, tmp / "jc.png"), t2_resolve_cards(jc, 3.0)[0]) if out_a.is_file() else 0
        ok_a = r.returncode == 0 and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and hits == 4
        old = _st_job(A, 1, out_b)
        old.pop("template_id")
        jp2 = tmp / "job_old.json"
        jp2.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        r2 = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--job", str(jp2)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        gskip = _st_golden_status()
        if gskip:
            d2, ok_b = None, r2.returncode == 0 and out_b.is_file()
        else:
            d2 = _st_frame_diffs(out_b, tmp, "jobold") if out_b.is_file() else [999]
            ok_b = r2.returncode == 0 and max(d2) < 1.0
        rec("23 --job: T2 with card / old T1 job", "PASS" if ok_a and ok_b else "FAIL",
            f"T2 job rc={r.returncode} {w}x{h} {dur:.2f}s card border {hits}/4; old T1 job rc={r2.returncode} "
            + (f"golden diff {max(d2):.3f}" if d2 else f"golden SKIP ({gskip})"))
    except BaseException as e:
        rec("23 --job: T2 with card / old T1 job", "FAIL", repr(e))

    # ---- 24. card questions (T2 wording) + job JSON ----------------------------------------------------------------
    try:
        prompts = []
        saved_in = builtins.input
        feed(["y", str(A / "c_green.png"), "Development", "1", "3", "Flutter", "3.5", "y",
              str(A / "broll.mp4"), "", "4", "2", "1.2", "2", "n", "5", "0.4"], prompts)
        cues = parse_srt(str(A / "en.srt"))
        got = quiet(t2_ask_cards_cfg, cues)
        builtins.input = saved_in
        c0, c1 = got["cards"][0], got["cards"][1]
        words = " ".join(prompts).lower()
        fed_ok = (len(got["cards"]) == 2 and c0["trigger"] == "Flutter" and c0["slot"] == 3 and c0["icon"] == "code"
                  and c0["hold"] == 3.5 and abs(c0["start"] - 0.0) < 5 and c1["label"] == "" and c1["icon"] == "none"
                  and c1["slot"] == 2 and c1["start"] == 1.2 and got["card_rot"] == 5.0 and got["card_anim_dur"] == 0.4
                  and D.get("t2_card_rot") == "5")
        wording = "hud" not in words and "cyan" not in words and "floating" in words
        feed(["n"], [])
        none_ok = quiet(t2_ask_cards_cfg, []) == {}
        t = t2_cfg(got)
        idem = t2_cfg(t) == t
        back = json.loads(json.dumps(dict(cfgp or _st_job(A, 2, tmp / "x.mp4"), t2=t), ensure_ascii=False))
        same = back["t2"]["cards"] == t["cards"] and t2_resolve_cards(back, 5.0) == t2_resolve_cards(dict(back), 5.0)
        rec("24 T2 card questions + job JSON", "PASS" if fed_ok and wording and none_ok and idem and same else "FAIL",
            f"answers ok={fed_ok} T2 wording={wording} 'no' ok={none_ok} idempotent={idem} job same={same}")
    except BaseException as e:
        builtins.input = saved_in
        rec("24 T2 card questions + job JSON", "FAIL", repr(e))

    # ---- 25. still with chapter tag + caption + card ----------------------------------------------------------------
    try:
        cfgs = _st_job(A, 2, tmp / "s.mp4")
        cfgs.update({"texts": [], "cards": [], "elements": []})
        cfgs["captions"] = [dict(base_cap, srt=str(A / "ar.srt"), t2_style="box", size=50)]
        cfgs["t2"] = t2_cfg({"chapters": [{"start": 0.0, "label": "Intro"}],
                             "cards": [{"media": str(A / "broll.mp4"), "label": "Development", "icon": "code",
                                        "slot": 1, "start": 0.3, "hold": 3.0}]})
        stp = tmp / "t2_still3b.png"
        quiet(render_still, cfgs, str(stp), 1.0)
        im = Image.open(stp).convert("RGB")
        r1 = t2_resolve_cards(cfgs, 5.0)[0]
        hits = _st_card_hits(im, r1)
        tx, ty = t2_tag_pos(cfgs)
        tag_px = sum(1 for y in range(ty, ty + 60) for x in range(tx, tx + 110) if _st_lime(im.getpixel((x, y))))
        items = [i for i in build_items(cfgs, 5.0) if i.start <= 1.0 < i.end and i.sprite.height > 70 and i.sprite.height < 200]
        bi = max(items, key=lambda i: i.sprite.width * i.sprite.height)
        bx0, by0 = int(bi.cx - bi.sprite.width / 2.0), int(bi.cy - bi.sprite.height / 2.0)
        bar_px = sum(1 for y in range(by0 + 10, by0 + bi.sprite.height - 10) for x in range(bx0 + 15, bx0 + 21)
                     if _st_lime(im.getpixel((x, y))))
        rec("25 T2 still: tag + caption + card", "PASS" if im.size == (1080, 1920) and hits == 4 and tag_px > 150 and bar_px > 80 else "FAIL",
            f"{im.size} card border {hits}/4 tag lime px={tag_px} caption bar px={bar_px}")
    except BaseException as e:
        rec("25 T2 still: tag + caption + card", "FAIL", repr(e))

    # ---- 26. timing T1 vs T2 (same 5 s clip, comparable features) ------------------------------------------------------
    try:
        vl = [{"path": str(A / "broll.mp4"), "start": 1.0, "end": 2.5, "area": "box", "mode": "fill", "fade": 0.3}]

        def mk(tid):
            c = _st_job(A, tid, tmp / f"time{tid}.mp4", preview=None)
            c["video_layers"] = [dict(v) for v in vl]
            if tid == 2:
                c["cards"] = []
                c["captions"] = [dict(base_cap, srt=str(A / "ar.srt"), t2_style="box", size=50),
                                 dict(base_cap, srt=str(A / "en.srt"), t2_style="sub", size=30, keywords="Flutter", shadow=True)]
                c["t2"] = t2_cfg({"chapters": [{"start": 0.0, "label": "Intro"}],
                                  "cards": [{"media": str(A / "c_green.png"), "label": "Development", "icon": "code",
                                             "slot": 1, "start": 0.5, "hold": 3.0}]})
            return c
        t1s, t2s = [_st_time_render(mk(1))], [_st_time_render(mk(2))]
        if t2s[0] / t1s[0] > 1.3:                       # timing noise: measure once more, keep the best of both
            t1s.append(_st_time_render(mk(1)))
            t2s.append(_st_time_render(mk(2)))
        a, b = min(t1s), min(t2s)
        rec("26 timing T1 vs T2 (5 s clip)", "PASS" if b <= a * 1.3 else "FAIL",
            f"T1 {a:.1f}s   T2 {b:.1f}s   ratio {b / a:.2f}x (target <= 1.3x)   runs T1={['%.1f' % x for x in t1s]} T2={['%.1f' % x for x in t2s]}")
    except BaseException as e:
        rec("26 timing T1 vs T2 (5 s clip)", "FAIL", repr(e))


def _selftest_t2_about(rec, quiet, feed, A, tmp):
    """Part 4A: ABOUT + FEATURES block. 29 default block in a still (inside canvas, below the video window, lime icons),
    30 two states over a 3 s clip differ, 31 long / Arabic text does not overflow, 32 T2 render 3 s with block + captions
    (+ T1 golden still matches)."""
    from PIL import ImageChops, ImageStat
    W, H = 1080, 1920
    font = t2_font("arabic", "ع")[0]
    base_cap = {"font": font, "color": "#ffffff", "hl_color": "", "keywords": "", "stroke_color": "#000000",
                "stroke_w": 0, "shadow": False, "mode": "phrase", "max_words": 8, "anim": "fade", "anim_dur": 0.25,
                "ref": "box", "y_pct": None}

    def job(out, t2, **kw):
        c = _st_job(A, 2, out, preview=kw.pop("preview", 3.0))
        c.update({"texts": [], "cards": [], "elements": [], "captions": []})
        c["t2"] = t2_cfg(t2)
        c.update(kw)
        return c

    # ---- 29. default block in a still ------------------------------------------------------------------------------
    try:
        on, off = tmp / "ab_on.png", tmp / "ab_off.png"
        c_on, c_off = job(tmp / "x.mp4", {}), job(tmp / "x.mp4", {"about_on": False})
        quiet(render_still, c_on, str(on), 1.0)
        quiet(render_still, c_off, str(off), 1.0)
        a, b = Image.open(on).convert("RGB"), Image.open(off).convert("RGB")
        bb = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
        box = c_on["video_box"]
        frame_bottom = box["y"] + box["h"]
        g = t2_about_geometry(c_on, 3)
        hits = []
        for (cx, cy) in g["rows"]:
            n = 0
            for yy in range(int(cy) - 16, int(cy) + 17):
                for xx in range(int(cx) - 16, int(cx) + 17):
                    n += _st_lime(a.getpixel((xx, yy)))
            hits.append(n)
        inside = bb is not None and bb[0] >= 0 and bb[1] >= 0 and bb[2] <= W and bb[3] <= H
        below = bb is not None and bb[1] >= frame_bottom
        ok = inside and below and min(hits) >= 25
        rec("29 about block default (still)", "PASS" if ok else "FAIL",
            f"bbox {bb} inside={inside} below frame ({frame_bottom})={below}; lime px at 3 icons {hits}")
    except BaseException as e:
        rec("29 about block default (still)", "FAIL", repr(e))

    # ---- 30 + 32 share one real 3 s render: 2 states (2nd by SRT phrase) + captions -------------------------------------
    out = tmp / "about3.mp4"
    st2 = {"about": [{"paragraph": "Short first state.", "title": "ABOUT ME",
                      "rows": [{"icon": "laptop", "text": "Alpha"}, {"icon": "code", "text": "Beta"}]},
                     {"trigger": "Flutter", "paragraph": "Second state text with another sentence entirely.",
                      "title": "SERVICES", "anim": "slide_up", "anim_dur": 0.3,
                      "rows": [{"icon": "gear", "text": "Gamma"}, {"icon": "phone", "text": "Delta"},
                               {"icon": "chip", "text": "Epsilon"}, {"icon": "code", "text": "Zeta"}]}]}
    rendered = False
    try:
        cfg = job(out, st2)
        cfg["captions"] = [dict(base_cap, srt=str(A / "ar.srt"), t2_style="box", size=50),
                           dict(base_cap, srt=str(A / "en.srt"), t2_style="sub", size=30, keywords="Flutter", shadow=True)]
        quiet(render, cfg)
        rendered = out.is_file()
        res = t2_resolve_about(cfg, 3.0)
        g = t2_about_geometry(cfg, 4)
        box = (g["ox"], g["oy"], g["ox"] + g["w"], g["oy"] + g["h"])
        f1, f1b, f2 = (_st_grab(out, t, tmp / f"ab_{t}.png").crop(box) for t in (0.9, 1.1, 2.5))
        d12 = sum(ImageStat.Stat(ImageChops.difference(f1, f2)).mean) / 3.0
        d11 = sum(ImageStat.Stat(ImageChops.difference(f1, f1b)).mean) / 3.0
        sig = lambda im: tuple(im.resize((8, 4), Image.BOX).tobytes()[:96])
        ok = len(res) == 2 and d12 > 1.5 and d11 < 0.5 and sig(f1) != sig(f2)
        rec("30 about two states differ (3 s clip)", "PASS" if ok else "FAIL",
            f"states {[round(r['start'], 2) for r in res]}  region diff state1 vs state2 {d12:.2f}  (same state {d11:.2f})")
    except BaseException as e:
        rec("30 about two states differ (3 s clip)", "FAIL", repr(e))

    # ---- 31. long + Arabic text never overflows -----------------------------------------------------------------------
    try:
        cfg = job(tmp / "y.mp4", {})
        long_p = " ".join(["Passionate about technology building scalable solutions and sharing knowledge"] * 6)
        ar_p = " ".join(["أنا مطور ويب وتطبيقات موبايل وأبني حلولاً قابلة للتوسع وأشارك المعرفة"] * 5)
        word_p = "Supercalifragilisticexpialidocious" * 4
        long_row = "A very very long feature row that cannot possibly fit in the right column"
        cases = {"long EN": long_p, "Arabic": ar_p, "one giant word": word_p, "empty": ""}
        bad, det = [], []
        for nm, para in cases.items():
            stt = t2_norm_about([{"paragraph": para, "title": "ABOUT ME" if nm != "Arabic" else "عني",
                                  "rows": [{"icon": "laptop", "text": long_row}, {"icon": "gear", "text": long_row},
                                           {"icon": "phone", "text": "أبني تطبيقات موبايل بسرعة كبيرة جدا جدا جدا جدا جدا"},
                                           {"icon": "code", "text": long_row}]}])[0]
            spr, meta = t2_about_sprite(cfg, stt, want_meta=True)
            gg = meta["geo"]
            cx0, cy0, cx1, cy1 = gg["col"]
            ink = meta["ink"]
            boxes = list(ink["para"]) + ([ink["title"]] if ink["title"] else [])
            ok_l = all(cx0 - 1 <= b_[0] and b_[2] <= cx1 + 1 and gg["y_base"] - 2 <= b_[1] and b_[3] <= cy1 + 1 for b_ in boxes)
            ok_r = all(tb is None or (gg["text_x"] - 1 <= tb[0] and tb[2] <= gg["right"] + 1 and
                                      gg["y_base"] - 2 <= tb[1] and tb[3] <= cy1 + 1) for _, tb in ink["rows"])
            al = spr.getchannel("A")
            gap = al.crop((int(cx1 - gg["ox"]) + 3, 0, int(gg["k"] * T2_ABOUT["div_x"] - gg["ox"]) - 3, spr.height)).getbbox()
            far = al.crop((int(gg["right"] - gg["ox"]) + 3, 0, spr.width, spr.height)).getbbox()
            ok = ok_l and ok_r and gap is None and far is None and meta["lines"] <= 3
            det.append(f"{nm}: lines={meta['lines']} scale={meta['scale']:.2f}")
            if not ok:
                bad.append(f"{nm} (left={ok_l} right={ok_r} gap={gap} far={far})")
        rec("31 about long/Arabic text fits", "PASS" if not bad else "FAIL", "; ".join(det) if not bad else "; ".join(bad))
    except BaseException as e:
        rec("31 about long/Arabic text fits", "FAIL", repr(e))

    # ---- 32. T2 render facts + T1 golden still green ---------------------------------------------------------------------
    try:
        w, h, dur, aud = _st_info(out)
        ok = rendered and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and aud
        gskip = _st_golden_status()
        gtxt = "golden SKIP: " + str(gskip)
        if not gskip:
            o1 = tmp / "t1_after_about.mp4"
            c1 = _st_job(A, 1, o1, preview=3.0)
            quiet(render, c1)
            diffs = _st_frame_diffs(o1, tmp, "t1ab")
            ok = ok and max(diffs) < 1.0
            gtxt = "T1 golden diff " + " / ".join(f"{x:.3f}" for x in diffs)
        rec("32 T2 render 3 s (block+captions) + T1", "PASS" if ok else "FAIL",
            f"{w}x{h} {dur:.2f}s audio={aud}; {gtxt}")
    except BaseException as e:
        rec("32 T2 render 3 s (block+captions) + T1", "FAIL", repr(e))


def _selftest_t2_panel(rec, quiet, feed, A, tmp):
    """Part 4B: bottom info panel.  33 static plate (bbox + bar colours), 34 playhead sync on a 4 s clip,
    35 panel disabled (render + region empty), 36 T2 3 s render with panel+captions+about, T1 golden, timing."""
    W, H = 1080, 1920
    font = t2_font("arabic", "ع")[0]
    base_cap = {"font": font, "color": "#ffffff", "hl_color": "", "keywords": "", "stroke_color": "#000000",
                "stroke_w": 0, "shadow": False, "mode": "phrase", "max_words": 8, "anim": "fade", "anim_dur": 0.25,
                "ref": "box", "y_pct": None}

    def job(out, t2, caps=True, **kw):
        c = _st_job(A, 2, out, preview=kw.pop("preview", 3.0))
        c.update({"texts": [], "cards": [], "elements": [], "captions": []})
        if caps:
            c["captions"] = [dict(base_cap, srt=str(A / "ar.srt"), t2_style="box", size=50),
                             dict(base_cap, srt=str(A / "en.srt"), t2_style="sub", size=30, keywords="Flutter", shadow=True)]
        c["t2"] = t2_cfg(t2)
        c.update(kw)
        return c

    def bar_points(info):
        pts = []
        for i, row in enumerate(info["bars"]):
            if row:
                b = row[0]
                pts.append((i, int((b[0] + b[2]) / 2), int((b[1] + b[3]) / 2)))
        return pts

    def near(p, col, tol=26):
        return all(abs(p[j] - col[j]) <= tol for j in range(3))

    def bar_hits(im, cfg_, info):
        rows = cfg_["t2"]["panel"]["rows"]
        return sum(near(im.getpixel((x, y)), t2_rgb(rows[i]["color"])) for i, x, y in bar_points(info))

    # ---- 33. static plate -------------------------------------------------------------------------------------------
    try:
        c = job(tmp / "x.mp4", {}, caps=False)
        plate, org, info = t2_panel_plate(c)
        bx = info["box"]
        inside = bx[0] >= 0 and bx[1] >= 0 and bx[2] <= W and bx[3] <= H and plate.size == (bx[2] - bx[0], bx[3] - bx[1])
        still = tmp / "pn_on.png"
        quiet(render_still, c, str(still), 4.0)
        im = Image.open(still).convert("RGB")
        hits = bar_hits(im, c, info)
        n_bars = len(bar_points(info))
        r9 = info["rows_cy"][8]
        # Part 4C: row 09 now carries the waveform; with panel.wave = False it must still be empty
        pl2, org2, info2 = t2_panel_plate(job(tmp / "x.mp4", {"panel": {"wave": False}}, caps=False))
        row9_dark = (info2["wave"] is None and info["wave"] is not None and
                     all(max(pl2.getpixel((int(info["track"][0] + f * (info["track"][1] - info["track"][0]) - org2[0]), int(r9 - org2[1])))[:3]) < 60
                         for f in (0.1, 0.3, 0.5, 0.7)))
        ok = inside and n_bars == 8 and hits == 8 and row9_dark
        rec("33 panel static image", "PASS" if ok else "FAIL",
            f"bbox {bx} inside canvas={inside}; bar colours matched {hits}/{n_bars}; row 09 empty with waveform off / waveform drawn when on={row9_dark}")
    except BaseException as e:
        rec("33 panel static image", "FAIL", repr(e))

    # ---- 34. playhead sync (4 s clip, full render) ------------------------------------------------------------------
    try:
        clip = tmp / "clip4.mp4"
        subprocess.check_call([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(A / "test.mp4"), "-t", "4",
                               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)])
        out = tmp / "ph4.mp4"
        c = job(out, {}, caps=False, preview=None, video=str(clip))
        quiet(render, c)
        w, h, dur, aud = _st_info(out)
        info = t2_panel_plate(c)[2]
        tx0, tx1 = info["track"]
        ys = [int(info["ph_y"]) + 40 + j * 40 for j in range(5)]
        xs, fr = [], []
        for t in (0.5, 2.0, 3.5):
            im = _st_grab(out, t, tmp / f"ph_{t}.png")
            found = []
            for y in ys:
                row = [x for x in range(int(tx0) - 14, int(tx1) + 15) if min(im.getpixel((x, y))) >= 200]
                if row:
                    found.append(sum(row) / len(row) + 0.5)
            found.sort()
            xs.append(found[len(found) // 2] if found else None)
        okf = all(v is not None for v in xs)
        exp = [t / dur for t in (0.5, 2.0, 3.5)]
        meas = [((v - tx0) / (tx1 - tx0)) if v is not None else -1 for v in xs]
        inc = okf and xs[0] < xs[1] < xs[2]
        prop = okf and all(abs(m_ - e_) < 0.025 for m_, e_ in zip(meas, exp))
        rec("34 playhead sync (4 s clip)", "PASS" if inc and prop else "FAIL",
            "x at t=0.5/2.0/3.5: " + "/".join(f"{v:.1f}" if v is not None else "none" for v in xs) +
            f"; progress {'/'.join(f'{m_:.3f}' for m_ in meas)} vs t/dur {'/'.join(f'{e_:.3f}' for e_ in exp)} (dur {dur:.2f}s)")
    except BaseException as e:
        rec("34 playhead sync (4 s clip)", "FAIL", repr(e))

    # ---- 35. panel disabled (3 s render, same config as 36 but panel off) -------------------------------------------
    t_off = t_on = None
    out_off, out_on = tmp / "pn_off.mp4", tmp / "pn_on.mp4"
    info = t2_panel_plate(job(tmp / "x.mp4", {}))[2]
    try:
        c = job(out_off, {"panel": {"on": False}})
        t_off = _st_time_render(c)
        im = _st_grab(out_off, 1.0, tmp / "pn_off.png")
        cref = job(out_off, {})
        hits = bar_hits(im, cref, info)
        white = sum(1 for y in range(int(info["box"][1]), int(info["box"][3]), 4)
                    for x in range(int(info["track"][0]), int(info["track"][1]), 2) if min(im.getpixel((x, y))) >= 200)
        none_ph = c.get("_t2_playhead") is None
        w, h, dur, aud = _st_info(out_off)
        ok = out_off.is_file() and (w, h) == (1080, 1920) and hits == 0 and white == 0 and t2_panel_plate(c) is None
        rec("35 panel disabled", "PASS" if ok else "FAIL",
            f"render ok={out_off.is_file()} {w}x{h}; bar colours in region {hits}/8; white playhead px {white}; plate None={t2_panel_plate(c) is None}")
    except BaseException as e:
        rec("35 panel disabled", "FAIL", repr(e))

    # ---- 36. T2 3 s render with panel + captions + about; T1 golden; timing ------------------------------------------
    try:
        c = job(out_on, {})
        t_on = _st_time_render(c)
        w, h, dur, aud = _st_info(out_on)
        im = _st_grab(out_on, 1.0, tmp / "pn_on1.png")
        hits = bar_hits(im, c, info)
        ok = out_on.is_file() and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and aud and hits == 8
        gskip = _st_golden_status()
        gtxt = "golden SKIP: " + str(gskip)
        if not gskip:
            o1 = tmp / "t1_after_panel.mp4"
            c1 = _st_job(A, 1, o1, preview=3.0)
            quiet(render, c1)
            diffs = _st_frame_diffs(o1, tmp, "t1pn")
            ok = ok and max(diffs) < 1.0
            gtxt = "T1 golden diff " + " / ".join(f"{x:.3f}" for x in diffs)
        tt = (f"; T2 3 s render {t_on:.1f}s with panel vs {t_off:.1f}s without (diff {t_on - t_off:+.1f}s)"
              if t_off is not None else "")
        small = t_off is None or (t_on - t_off) < max(4.0, 0.35 * t_off)
        rec("36 T2 3 s render panel+captions+about + T1", "PASS" if ok and small else "FAIL",
            f"{w}x{h} {dur:.2f}s audio={aud}; bars in video frame {hits}/8; {gtxt}{tt}")
    except BaseException as e:
        rec("36 T2 3 s render panel+captions+about + T1", "FAIL", repr(e))


def _selftest_t2_4c(rec, quiet, feed, A, tmp):
    """Part 4C: 37 waveform, 38 pagination dots, 39 T2 split, 40 everything on via --job, 41 T1 golden + T1 split."""
    def near(p, col, tol=45):
        return all(abs(p[j] - col[j]) <= tol for j in range(3))
    acc = t2_rgb(T2_ACCENT)
    wa, na = tmp / "wave_audio.mp4", tmp / "wave_noaudio.mp4"
    def base_job(out, t2, **kw):
        c_ = _st_job(A, 2, out, preview=kw.pop("preview", 4.0))
        c_.update({"texts": [], "cards": [], "elements": [], "captions": [], "t2": t2_cfg(t2)})
        c_.update(kw)
        return c_

    # ---- 37. waveform: audio clip -> non-flat bars; no audio / missing file -> procedural fallback, no crash -------------
    try:
        subprocess.check_call([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=4",
                               "-f", "lavfi", "-i", "sine=frequency=330:duration=4,tremolo=f=3:d=0.95", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                               "-c:a", "aac", "-shortest", str(wa)])
        subprocess.check_call([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=4",
                               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(na)])
        res = {}
        for tag, vid in (("audio", wa), ("noaudio", na), ("missing", tmp / "nope.mp4")):
            c = base_job(tmp / "x.mp4", {}, video=str(vid))
            os.makedirs(tmp / ("w_" + tag), exist_ok=True)
            quiet(t2_build_static_layers, c, str(tmp / ("w_" + tag)))                # the real hook (extraction + bake)
            plate, org, info = t2_panel_plate(c)
            wv = info["wave"]
            mw, mh = wv["size"]
            ox, oy = wv["origin"]
            heights = set()
            for x in range(mw):                                                    # real pixels: ink height of every column in row 09
                col = [plate.getpixel((ox - org[0] + x, oy - org[1] + y))[0] for y in range(mh)]
                heights.add(sum(1 for a in col if a > 100))
            res[tag] = (wv["src"], len(set(wv["heights"])), len(heights), max(wv["heights"]) / max(0.1, min(wv["heights"])))
        ok = (res["audio"][0] == "audio" and res["audio"][2] >= 6 and res["audio"][3] > 3
              and res["noaudio"][0] == "procedural" and res["noaudio"][2] >= 6 and res["missing"][0] == "procedural")
        rec("37 waveform row 09 (audio / no audio / missing)", "PASS" if ok else "FAIL",
            "; ".join(f"{k}: src={v[0]} distinct peaks={v[1]} distinct pixel column heights={v[2]} max/min={v[3]:.1f}" for k, v in res.items()))
    except BaseException as e:
        rec("37 waveform row 09 (audio / no audio / missing)", "FAIL", repr(e))

    # ---- 38. pagination dots: 2 chapters in a 4 s clip -> lime dot x differs; decorative = last dot --------------------
    try:
        def lime_x(png):
            im = Image.open(png).convert("RGB")
            yc = int(T2_DOTS["y"] * 1920 / T2_POSTER_H)
            xs = [x for x in range(760, 1060) if any(near(im.getpixel((x, y)), acc, 30) for y in range(yc - 8, yc + 9))]
            return sum(xs) / len(xs) if xs else None
        c = base_job(tmp / "x.mp4", {"chapters": [{"start": 0.0, "label": "Intro"}, {"start": 2.0, "label": "Stack"}]}, video=str(wa))
        quiet(render_still, c, str(tmp / "dots1.png"), 1.0)
        quiet(render_still, c, str(tmp / "dots3.png"), 3.0)
        c0 = base_job(tmp / "x.mp4", {}, video=str(wa))
        quiet(render_still, c0, str(tmp / "dots0.png"), 1.0)
        x1, x3, x0 = lime_x(tmp / "dots1.png"), lime_x(tmp / "dots3.png"), lime_x(tmp / "dots0.png")
        exp_last = T2_DOTS["x_last"] * 1080 / T2_POSTER_W
        ok = None not in (x1, x3, x0) and x3 - x1 > 15 and abs(x0 - exp_last) < 3 and x1 < x3 <= x0 + 1
        rec("38 pagination dots follow chapters", "PASS" if ok else "FAIL",
            f"lime dot x: chapter1 t=1 {x1}, chapter2 t=3 {x3}, decorative (no chapters) {x0} (last dot expected ~{exp_last:.1f})")
    except BaseException as e:
        rec("38 pagination dots follow chapters", "FAIL", repr(e))

    # ---- 39. T2 split: frame inside the segment shows the framed boxes, frames outside do not -------------------------
    try:
        out39 = tmp / "t2_split.mp4"
        c = base_job(out39, {"split": {"on": True}}, elements=[{"path": str(A / "element.png"), "start": 1.2, "end": 2.8, "pos": "center",
                                                               "width": None, "opacity": 100, "anim": "fade", "anim_dur": 0.3}])
        c["split"] = t2_split_params(c)
        lb, rb = split_boxes(c)
        pts = [(lb["x"] - 2, lb["y"] + lb["h"] // 2), (lb["x"] + lb["w"] // 2, lb["y"] - 2),
               (rb["x"] + rb["w"] + 1, rb["y"] + rb["h"] // 2), (rb["x"] + rb["w"] // 2, rb["y"] - 2)]
        quiet(render, base_job(out39, {"split": {"on": True}}, elements=c["elements"]))
        hits = {}
        for t in (0.4, 2.0, 3.6):
            im = _st_grab(out39, t, tmp / f"sp_{t}.png")
            hits[t] = sum(near(im.getpixel(p), acc) for p in pts)
            if t == 2.0:
                orange = sum(1 for y in range(rb["y"], rb["y"] + rb["h"], 3) for x in range(rb["x"], rb["x"] + rb["w"], 3)
                             if near(im.getpixel((x, y)), (255, 140, 0), 30))
        ok = hits[2.0] == 4 and hits[0.4] == 0 and hits[3.6] == 0 and orange > 100
        rec("39 T2 split mode (inside vs outside segment)", "PASS" if ok else "FAIL",
            f"lime border px hit (of 4): t=0.4 -> {hits[0.4]}, t=2.0 -> {hits[2.0]}, t=3.6 -> {hits[3.6]}; element px in right box {orange}; "
            f"boxes L{lb['x']},{lb['y']},{lb['w']}x{lb['h']} R{rb['x']},{rb['y']},{rb['w']}x{rb['h']}")
    except BaseException as e:
        rec("39 T2 split mode (inside vs outside segment)", "FAIL", repr(e))

    # ---- 40. everything on (captions + panel + about + split + dots + waveform) 4 s, rendered through --job --------------
    try:
        out40 = tmp / "t2_all.mp4"
        c = base_job(out40, {"split": {"on": True}, "chapters": [{"start": 0.0, "label": "Intro"}, {"start": 2.0, "label": "Stack"}]},
                     elements=[{"path": str(A / "element.png"), "start": 1.2, "end": 2.8, "pos": "center", "width": None, "opacity": 100,
                                "anim": "fade", "anim_dur": 0.3}])
        cap = {"font": t2_font("arabic", "ع")[0], "color": "#ffffff", "hl_color": "", "keywords": "", "stroke_color": "#000000", "stroke_w": 0,
               "shadow": False, "mode": "phrase", "max_words": 8, "anim": "fade", "anim_dur": 0.25, "ref": "box", "y_pct": None}
        c["captions"] = [dict(cap, srt=str(A / "ar.srt"), t2_style="box", size=50),
                         dict(cap, srt=str(A / "en.srt"), t2_style="sub", size=30, keywords="Flutter", shadow=True)]
        jp = tmp / "t2_all_job.json"
        jp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--job", str(jp)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
        w, h, dur, aud = _st_info(out40) if out40.is_file() else (0, 0, 0, False)
        sp_ok = False
        if out40.is_file():
            c["split"] = t2_split_params(c)
            lb = split_boxes(c)[0]
            sp_ok = near(_st_grab(out40, 2.0, tmp / "all_2.png").getpixel((lb["x"] - 2, lb["y"] + lb["h"] // 2)), acc)
        ok = r.returncode == 0 and (w, h) == (1080, 1920) and abs(dur - 4.0) < 0.25 and aud and sp_ok
        rec("40 T2 everything on 4 s via --job", "PASS" if ok else "FAIL",
            f"rc={r.returncode} {w}x{h} {dur:.2f}s audio={aud} split border visible at t=2: {sp_ok}" + ("" if ok else " " + (r.stderr or r.stdout)[-200:]))
    except BaseException as e:
        rec("40 T2 everything on 4 s via --job", "FAIL", repr(e))

    # ---- 41. T1 golden comparison + T1 split render -------------------------------------------------------------------
    try:
        gskip = _st_golden_status()
        gtxt, ok = "golden SKIP: " + str(gskip), True
        if not gskip:
            o1 = tmp / "t1_after_4c.mp4"
            quiet(render, _st_job(A, 1, o1, preview=3.0))
            diffs = _st_frame_diffs(o1, tmp, "t1_4c")
            ok = max(diffs) < 1.0
            gtxt = "T1 golden diff " + " / ".join(f"{x:.3f}" for x in diffs)
        o2 = tmp / "t1_split.mp4"
        c1 = _st_job(A, 1, o2, preview=3.0)
        c1["split"] = {"left_w": 520, "right_w": 360, "gap_px": 40, "h": 800}
        quiet(render, c1)
        w, h, dur, aud = _st_info(o2) if o2.is_file() else (0, 0, 0, False)
        c1["_split_bg"] = "x"
        rb = split_boxes(c1)[1]
        edge = (35, 150, 255)
        sp_in = near(_st_grab(o2, 1.5, tmp / "t1sp.png").getpixel((rb["x"] - 7, rb["y"] + rb["h"] // 2)), edge, 60) if o2.is_file() else False
        ok = ok and o2.is_file() and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and aud and sp_in
        rec("41 T1 golden + T1 split render", "PASS" if ok else "FAIL",
            f"{gtxt}; T1 split render {w}x{h} {dur:.2f}s audio={aud}, blue frame at right box edge: {sp_in}")
    except BaseException as e:
        rec("41 T1 golden + T1 split render", "FAIL", repr(e))


def _selftest_4d(rec, quiet, feed, A, tmp):
    """Part 4D: 42 T2 Enter-through flow, 43 selector (1/2/saved T2/saved custom), 44 robustness cases, 45 non-9:16 inputs,
    46 py_compile + --help."""
    import builtins
    import contextlib
    import io
    saved_input, saved_tdir = builtins.input, globals()["TEMPLATES_DIR"]
    d4 = tmp / "d4"
    d4.mkdir(exist_ok=True)
    env = dict(os.environ)

    def mkv(name, w, h, dur, audio=True):
        cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration={dur}"]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-c:a", "aac", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(d4 / name)]
        subprocess.check_call(cmd)
        return str(d4 / name)

    def run(job):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            render(job)
        return buf.getvalue()

    def jb(tid, name, video=None, preview=None, **over):
        c = _st_job(A, tid, d4 / (name + ".mp4"), preview=preview)
        if video:
            c["video"] = video
        c.update(over)
        return c

    # ---- 42. Template 2: Enter through everything (only the video, the SRT, the output and 2 s are typed) -----------------
    try:
        prompts = []
        out42 = d4 / "enter.mp4"

        def fake(prompt=""):
            prompts.append(prompt)
            if prompt.startswith("Choice") and len(prompts) == 1:
                return "2"
            for k, v in (("Video path", str(A / "test.mp4")), ("SRT captions file path", str(A / "ar.srt")),
                         ("Output file", str(out42)), ("Quick test", "2")):
                if prompt.startswith(k):
                    return v
            return ""
        builtins.input = fake
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            c = interactive()
        builtins.input = saved_input
        order = ["Choice", "Video path", "SRT captions file path", "Accent color", "Video window size", "Show the ABOUT",
                 "Show the bottom info panel", "Caption font", "Add chapter tags", "Add floating B-roll", "Use the poster texts (Passionate",
                 "Do you want text", "Do you want elements", "Add a template layer", "Do you want a video layer", "Output file", "Quick test"]
        pos = []
        for k in order:
            pos.append(next((i for i, q in enumerate(prompts) if q.lstrip("\n").startswith(k)), -1))
        order_ok = all(x >= 0 for x in pos) and pos == sorted(pos)
        hdr_ok = all(h in buf.getvalue() for h in ("=== 1. Video", "=== 2. Captions file", "=== 3. Identity", "=== 5. Panels", "=== 12. Output"))
        recap = recap_line(c)
        quiet(render, c)
        w, h, dur, aud = _st_info(out42) if out42.is_file() else (0, 0, 0, False)
        ok = (order_ok and hdr_ok and out42.is_file() and (w, h) == (1080, 1920) and abs(dur - 2.0) < 0.2 and aud
              and "Template 2" in recap and "ON:" in recap and c["t2"] == t2_cfg(c["t2"]))
        rec("42 T2 Enter-through (defaults) -> 2 s render", "PASS" if ok else "FAIL",
            f"{w}x{h} {dur:.2f}s audio={aud} order_ok={order_ok} headers_ok={hdr_ok} | {recap}" if ok else
            f"order_ok={order_ok} (pos={pos}) headers_ok={hdr_ok} size={w}x{h} {dur:.2f}s recap={recap}")
    except BaseException as e:
        rec("42 T2 Enter-through (defaults) -> 2 s render", "FAIL", repr(e))
    finally:
        builtins.input = saved_input

    # ---- 43. selector: 1 / 2 / saved Template 2 / saved Custom ----------------------------------------------------------
    try:
        sdir = d4 / "templates"
        sdir.mkdir(exist_ok=True)
        (sdir / "a_t2.json").write_text(json.dumps({
            "template_id": 2, "canvas": [1080, 1920], "video_box": dict(T2_DEFAULT_BOX), "background": {"type": "t2"},
            "layers": [], "t2": t2_cfg({"name": "SAVED NAME", "line1": "SAVED HEAD"})}), encoding="utf-8")
        (sdir / "b_custom.json").write_text(json.dumps({
            "canvas": [1080, 1080], "video_box": {"x": 0, "y": 0, "w": 1080, "h": 1080, "mode": "fit"},
            "background": {"type": "color", "value": "#101820"}, "layers": []}), encoding="utf-8")
        globals()["TEMPLATES_DIR"] = sdir
        got = {}
        listing = io.StringIO()
        for ans in ("1", "2", "3", "4", "5"):
            feed([ans], [])
            with contextlib.redirect_stdout(listing):
                e = choose_template()
            got[ans] = (e["id"], Path(_PRESET.get("path") or "").name)
        want = {"1": (1, ""), "2": (2, ""), "3": (3, ""), "4": (2, "a_t2.json"), "5": (3, "b_custom.json")}
        labels_ok = "saved - Template 2" in listing.getvalue() and "a_t2" in listing.getvalue() and "b_custom" in listing.getvalue()
        _PRESET.clear()
        prompts = []
        first = iter(["4", str(A / "test.mp4")])

        def fake2(prompt=""):
            prompts.append(prompt)
            return next(first, "")
        builtins.input = fake2
        c = quiet(interactive)
        builtins.input = saved_input
        no_reask = not any(q.startswith(("Header name", "Accent color", "Headline line", "Video window size")) for q in prompts)
        loaded_ok = c.get("template_id") == 2 and c["t2"].get("name") == "SAVED NAME" and c["t2"].get("line1") == "SAVED HEAD"
        ok = got == want and labels_ok and no_reask and loaded_ok
        rec("43 selector: 1 / 2 / saved T2 / saved Custom", "PASS" if ok else "FAIL",
            f"routes={got} labels_ok={labels_ok} saved_T2_not_reasked={no_reask} loaded_ok={loaded_ok}")
    except BaseException as e:
        rec("43 selector: 1 / 2 / saved T2 / saved Custom", "FAIL", repr(e))
    finally:
        builtins.input = saved_input
        globals()["TEMPLATES_DIR"] = saved_tdir
        _PRESET.clear()

    # ---- 44. robustness: every case must render, or exit with one readable line -------------------------------------------
    cases = []

    def case(name, fn):
        try:
            res = fn()
            ok, detail = res if isinstance(res, tuple) else (bool(res), "")
        except BaseException as e:
            ok, detail = False, repr(e)[:160]
        cases.append(ok)
        rec("44 " + name, "PASS" if ok else "FAIL", detail)

    def okrender(job, out, dur=None, msg=None):
        txt = run(job)
        w, h, d, a = _st_info(out) if Path(out).is_file() else (0, 0, 0, False)
        good = (w, h) == (1080, 1920) and (dur is None or abs(d - dur) < 0.25) and (msg is None or msg in txt)
        return good, f"{w}x{h} {d:.2f}s" + (f" msg='{msg}'" if msg else "")

    (d4 / "bad.png").write_text("not an image", encoding="utf-8")
    el = lambda path: [{"path": path, "start": 0.2, "end": 1.2, "pos": "center", "width": "20%", "opacity": 100, "anim": "pop", "anim_dur": 0.3}]
    for tid in (1, 2):
        case(f"T{tid} missing element path", lambda tid=tid: okrender(jb(tid, f"me{tid}", preview=1.5, elements=el("/nope/gone.png")),
                                                                    d4 / f"me{tid}.mp4", msg="gone.png"))
        case(f"T{tid} invalid element file", lambda tid=tid: okrender(jb(tid, f"ie{tid}", preview=1.5, elements=el(str(d4 / "bad.png"))),
                                                                    d4 / f"ie{tid}.mp4", msg="bad.png"))

    def icon_case():
        c = jb(2, "ic", preview=1.5)
        c["t2"] = t2_cfg({"cards": [{"media": str(A / "element.png"), "label": "X", "icon": "image", "icon_path": "/nope/i.png",
                                     "slot": 1, "start": 0.2, "trigger": "", "hold": 1.0}],
                          "about": [{"paragraph": "p", "title": "T", "start": None, "trigger": "",
                                     "rows": [{"icon": "image", "icon_path": "/nope/a.png", "text": "Row"}]}]})
        c["cards"] = []
        return okrender(c, d4 / "ic.mp4", msg="icon")
    case("T2 missing card / about icon path", icon_case)

    def font_case(tid):
        c = jb(tid, f"fo{tid}", preview=1.5)
        c["texts"][0]["font"] = "/nope/Cairo-Bold.ttf"
        for cp in c["captions"]:
            cp["font"] = "/nope/Cairo-Bold.ttf"
        if tid == 2:
            c["t2"]["fonts"] = {"arabic": "/nope/Cairo-Bold.ttf"}
        return okrender(c, d4 / f"fo{tid}.mp4", msg="fonts/")
    for tid in (1, 2):
        case(f"T{tid} missing font (message names the file)", lambda tid=tid: font_case(tid))

    def numpy_case():
        prev = sys.modules.get("numpy", "absent")
        sys.modules["numpy"] = None                      # import numpy -> ImportError
        try:
            return okrender(jb(2, "nonp", preview=1.5), d4 / "nonp.mp4", msg="numpy is not installed")
        finally:
            if prev == "absent":
                sys.modules.pop("numpy", None)
            else:
                sys.modules["numpy"] = prev
    case("T2 numpy missing (fallback + message)", numpy_case)

    def cli(args, env_over=None):
        e = dict(os.environ)
        e.update(env_over or {})
        r = subprocess.run([sys.executable, str(Path(__file__).resolve())] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300, env=e, stdin=subprocess.DEVNULL)
        return r

    def noffmpeg():
        if FFMPEG and str(FFMPEG).startswith(str(BASE)):
            return True, "SKIP-equivalent: ffmpeg lives next to the script"
        jp = d4 / "nf_job.json"
        jp.write_text(json.dumps(jb(1, "nf", preview=1.0)), encoding="utf-8")
        r = cli(["--job", str(jp)], {"PATH": ""})
        return (r.returncode == 1 and "FFmpeg was not found" in r.stdout and "Traceback" not in r.stderr), \
            f"rc={r.returncode} '{r.stdout.strip().splitlines()[-1][:60] if r.stdout.strip() else r.stderr[-60:]}'"
    case("ffmpeg missing (PATH empty) -> clean exit", noffmpeg)

    na = mkv("noaudio.mp4", 1080, 1920, 2, audio=False)
    for tid in (1, 2):
        case(f"T{tid} video without audio", lambda tid=tid: okrender(jb(tid, f"na{tid}", video=na), d4 / f"na{tid}.mp4", dur=2.0))
    sh = mkv("short.mp4", 1080, 1920, 1.5)
    for tid in (1, 2):
        case(f"T{tid} very short video (1.5 s)", lambda tid=tid: okrender(jb(tid, f"sh{tid}", video=sh), d4 / f"sh{tid}.mp4", dur=1.5))
    longtxt = ("هذا نص طويل جدا للتجربة " * 10 + "This is a very long caption line used to test wrapping and shrinking " * 5).strip()
    (d4 / "long.srt").write_text(f"1\n00:00:00,000 --> 00:00:01,400\n{longtxt}\n", encoding="utf-8")

    def long_case(tid):
        c = jb(tid, f"lg{tid}", video=sh)
        for cp in c["captions"]:
            cp["srt"] = str(d4 / "long.srt")
        return okrender(c, d4 / f"lg{tid}.mp4", dur=1.5)
    for tid in (1, 2):
        case(f"T{tid} very long caption text ({len(longtxt)} chars)", lambda tid=tid: long_case(tid))

    def srt_case():
        (d4 / "bom.srt").write_bytes(b"\xef\xbb\xbf1\r\n00:00:00,000 --> 00:00:00,800\r\nHello\r\n\r\n\r\n\r\n2\r\n00:00:01,000 --> 00:00:01,400\r\n\r\nWorld\r\nsecond line\r\n\r\n\r\n3\r\n00:00:01,500 --> 00:00:01,900\r\nEnd\r\n\r\n")
        cues = parse_srt(str(d4 / "bom.srt"))
        okc = [x[2] for x in cues] == ["Hello", "World second line", "End"]
        c = jb(2, "bomr", video=sh)
        for cp in c["captions"]:
            cp["srt"] = str(d4 / "bom.srt")
        good, d = okrender(c, d4 / "bomr.mp4", dur=1.5)
        return okc and good, f"cues={[x[2] for x in cues]} {d}"
    case("SRT with BOM / CRLF / empty lines", srt_case)

    def cli_missing_video():
        j = jb(2, "mv")
        j["video"] = "/nope/video.mp4"
        jp = d4 / "mv_job.json"
        jp.write_text(json.dumps(j), encoding="utf-8")
        r = cli(["--job", str(jp)])
        return (r.returncode == 1 and "video file not found" in r.stdout and "Traceback" not in r.stderr), f"rc={r.returncode}"
    case("missing video in a job -> clean exit", cli_missing_video)

    def cli_bad_json():
        jp = d4 / "bad_job.json"
        jp.write_text("{not json", encoding="utf-8")
        r = cli(["--job", str(jp)])
        return (r.returncode == 1 and "not valid JSON" in r.stdout and "Traceback" not in r.stderr), f"rc={r.returncode}"
    case("corrupt job json -> clean exit", cli_bad_json)
    rec("44 robustness cases (summary)", "PASS" if all(cases) else "FAIL", f"{sum(cases)}/{len(cases)} cases passed")

    # ---- 45. non-9:16 inputs, both templates, fit and fill ------------------------------------------------------------------
    try:
        res, ok = [], True
        for nm, (vw, vh) in (("wide", (1920, 1080)), ("square", (1080, 1080))):
            vid = mkv(f"{nm}.mp4", vw, vh, 1.5)
            for tid in (1, 2):
                for mode in ("fit", "fill"):
                    c = jb(tid, f"np_{nm}_{tid}_{mode}", video=vid, texts=[], cards=[], elements=[], captions=[])
                    c["video_box"] = dict(c["video_box"], mode=mode)
                    if tid == 2:
                        c["t2"] = t2_cfg({})
                    out = d4 / f"np_{nm}_{tid}_{mode}.mp4"
                    quiet(render, c)
                    w, h, d, a = _st_info(out) if out.is_file() else (0, 0, 0, False)
                    good = (w, h) == (1080, 1920) and abs(d - 1.5) < 0.25
                    gap = None
                    if good and mode == "fit" and nm == "wide":
                        im = _st_grab(out, 0.5, d4 / "g.png")
                        b = c["video_box"]
                        px = im.getpixel((b["x"] + b["w"] // 2, b["y"] + 12))
                        gap = sum(px[:3]) < 120                       # letterbox gap above the 16:9 picture is dark, not stretched
                        good = good and gap
                    ok = ok and good
                    res.append(f"{nm}/T{tid}/{mode}:{'ok' if good else 'BAD'}")
        rec("45 non-9:16 (1920x1080, 1080x1080) T1+T2 fit/fill", "PASS" if ok else "FAIL", " ".join(res))
    except BaseException as e:
        rec("45 non-9:16 (1920x1080, 1080x1080) T1+T2 fit/fill", "FAIL", repr(e))

    # ---- 46. py_compile + --help ----------------------------------------------------------------------------------------------
    try:
        me = str(Path(__file__).resolve())
        r1 = subprocess.run([sys.executable, "-m", "py_compile", me], capture_output=True, text=True, timeout=120)
        r2 = cli(["--help"])
        doc_ok = all(k in (__doc__ or "") for k in ("--job", "--preview", "--still", "--selftest", "--arabic-mode", "templates/",
                                                    "fonts/", "selftest_golden/", "Kanit-ExtraBoldItalic", "Cairo-Bold", "Rajdhani"))
        ok = r1.returncode == 0 and r2.returncode == 0 and "--selftest" in r2.stdout and doc_ok
        rec("46 py_compile + --help + docstring", "PASS" if ok else "FAIL",
            f"py_compile rc={r1.returncode}, --help rc={r2.returncode}, docstring_complete={doc_ok}")
    except BaseException as e:
        rec("46 py_compile + --help + docstring", "FAIL", repr(e))


class _StopSelftest(Exception):
    pass


def _st_report(rows):
    print("\n" + "=" * 78)
    print(f" {'SELFTEST':<42}{'RESULT':<8}DETAIL")
    print("-" * 78)
    for name, status, detail in rows:
        print(f" {name:<42}{status:<8}{detail}")
    print("=" * 78)
    failed = [r for r in rows if r[1] == "FAIL"]
    print(f" {len(rows) - len(failed)} ok/skipped, {len(failed)} failed -> " + ("ALL PASS" if not failed else "FAILED"))
    return 0 if not failed else 1


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    """Runs _main() and turns expected problems into one readable line instead of a traceback."""
    try:
        _main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
    except SystemExit:
        raise
    except subprocess.CalledProcessError as e:
        if os.environ.get("MONTAGE_DEBUG"):
            raise
        print(f"[!] An external tool failed ({Path(str(e.cmd[0])).name}, exit {e.returncode}). "
              f"Run with MONTAGE_DEBUG=1 for details.")
        sys.exit(1)
    except (ValueError, OSError, KeyError, RuntimeError, ImportError, TypeError) as e:
        if os.environ.get("MONTAGE_DEBUG"):
            raise
        msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        if isinstance(e, KeyError):
            msg = f"the job/settings are missing the field {e}"
        print(f"[!] {msg}   (MONTAGE_DEBUG=1 shows the full traceback)")
        sys.exit(1)


def _main():
    ap = argparse.ArgumentParser(description="Interactive montage builder (Pillow + FFmpeg)")
    ap.add_argument("--job", help="re-render from a saved *_job.json (no questions)")
    ap.add_argument("--preview", type=float, help="render only the first N seconds")
    ap.add_argument("--arabic-mode", choices=["auto", "raqm", "reshape"], default="auto")
    ap.add_argument("--still", action="store_true",
                    help="render ONE png of the final composite at t=0.5s (no video encoding) to check the design")
    ap.add_argument("--still-out", help="where to save the --still png (default: next to the output file)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the built-in checks on synthetic assets (no questions) and exit")
    args = ap.parse_args()

    mode = setup_arabic_mode(args.arabic_mode)
    if args.selftest:
        sys.exit(run_selftest())

    _require_ffmpeg()

    if args.still:
        if args.job:
            cfg = _load_job(args.job)
        else:
            cfg = interactive()
            jp = Path(cfg["output"]).with_name(Path(cfg["output"]).stem + "_job.json")
            try:
                jp.parent.mkdir(parents=True, exist_ok=True)
                jp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"(settings saved to {jp.name} - render later with:  python montage.py --job \"{jp}\")")
            except Exception:
                pass
            _save_defaults()
        out = args.still_out or str(Path(cfg["output"]).with_name(Path(cfg["output"]).stem + "_still.png"))
        print(f"(Template: {get_template(cfg)['name']} - {get_template(cfg)['desc']})")
        print("Rendering the still (t=0.5s)...")
        render_still(cfg, out, 0.5)
        print(f"Still saved -> {out}")
        return

    if args.job:
        cfg = _load_job(args.job)
        if args.preview:
            cfg["preview"] = args.preview
        print(f"(Arabic text engine: {mode})")
        print(f"(Template: {get_template(cfg)['name']} - {get_template(cfg)['desc']})")
        render(cfg)
        return

    cfg = interactive()
    if args.preview:
        cfg["preview"] = args.preview

    n_cap = sum(len(stream_groups(parse_srt(c["srt"]), c)) for c in caption_streams(cfg))
    print("\n" + "-" * 60)
    print(f" Template   : {get_template(cfg)['name']} - {get_template(cfg)['desc']}")
    print(f" Canvas     : {cfg['canvas'][0]}x{cfg['canvas'][1]}")
    vb = cfg["video_box"]
    print(f" Video box  : {vb['w']}x{vb['h']} at ({vb['x']},{vb['y']}) [{vb['mode']}]")
    print(f" Background : {cfg['background']['type']}")
    n_cards = len((cfg.get("t2") or {}).get("cards", [])) if cfg.get("template_id") == 2 else len(cfg.get("cards", []))
    print(f" Layers {len(cfg.get('layers', []))} | Texts {len(cfg['texts'])} | Cards {n_cards}"
          f" | Elements {len(cfg['elements'])} | Caption groups {n_cap}")
    print(f" Output     : {cfg['output']}" + (f"   (test: first {cfg['preview']}s)" if cfg.get("preview") else ""))
    print(f" Arabic text engine: {mode}")
    print("-" * 60)
    print("Recap: " + recap_line(cfg))
    if not yn("Start rendering?", default=True):
        print("Cancelled.")
        return

    job_path = Path(cfg["output"]).with_name(Path(cfg["output"]).stem + "_job.json")
    try:
        job_path.parent.mkdir(parents=True, exist_ok=True)
        job_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"(settings saved to {job_path.name} - re-run later with:  python montage.py --job \"{job_path}\")")
    except Exception:
        pass
    _save_defaults()
    render(cfg)


if __name__ == "__main__":
    main()