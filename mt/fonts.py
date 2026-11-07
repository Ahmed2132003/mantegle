"""mt.fonts - moved from montage.py by tools/mt_move.py"""
from mt.common import FONTS_DIR, _warn, clean_path
import re
import arabic_reshaper
from PIL import ImageFont, features
import unicodedata
try:
    from bidi import get_display  # noqa: E402
except ImportError:
    from bidi.algorithm import get_display  # noqa: E402
import os
import sys
from pathlib import Path
from mt.common import _t2_norm


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
