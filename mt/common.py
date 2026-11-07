"""mt.common - moved from montage.py by tools/mt_move.py"""
from pathlib import Path
import sys
import subprocess
import shutil
import os
import json
import re
from fractions import Fraction


BASE = Path(__file__).resolve().parent.parent   # entry folder = parent of the mt/ package (NOT mt/ itself)
BASE_DIR = BASE


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


# pip check runs on import, BEFORE the first PIL import (same order as the original montage.py: check, then Pillow)
_ensure_python_packages()
from PIL import ImageColor  # noqa: E402  (used by c_color)


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
# Robustness: validate every path / font BEFORE rendering (one-line messages, never a traceback)
# ----------------------------------------------------------------------------
_WARNED = set()


def _warn(msg):
    if msg not in _WARNED:
        _WARNED.add(msg)
        print("[!] " + msg)


def _vid_ok(path, what):
    if path and os.path.isfile(str(path)):
        return True
    _warn(f"{what} '{Path(str(path)).name if path else '(empty path)'}' not found - skipped")
    return False


def _hex0x(c):
    return "0x" + c.lstrip("#")


T2_ACCENT = "#BDDE38"                          # sampled from the poster (median of the lime headline bar)


def _t2_num_or_none(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _t2_norm(s):
    return re.sub(r"[^a-z]", "", s.lower())


def _read_exact(f, n):
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _t2_frac(v, dflt):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return dflt


# Template registry container. It is defined here (leaf module) and FILLED in montage.py (later: mt/templates/__init__.py)
# with TEMPLATE_REGISTRY.update({...}); never rebound. This lets mt/render.py dispatch templates without importing them.
TEMPLATE_REGISTRY = {}


def get_template(cfg):
    """Registry entry for a cfg / job. Missing or unknown template_id -> Template 1."""
    try:
        tid = int(cfg.get("template_id") or 1)
    except (TypeError, ValueError):
        tid = 1
    e = TEMPLATE_REGISTRY.get(tid, TEMPLATE_REGISTRY[1])
    if e.get("coming_soon"):
        raise RuntimeError(f"{e['name']} is coming soon - it is not implemented yet. Use Template 1, 2 or Custom.")
    return e
