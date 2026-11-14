"""mt.templates.t4.timing - Template 4: when does an overlay module show? Pure functions, no drawing.
t4_time(entry, cues, duration, default_hold) -> (start, end) | None;  t4_stagger(n, step) -> [delay];  t4_ask_when(prompt, default_hold).
t4_warn / t4_warn_reset live in t4/warn.py (P2, once per render - the same pattern as t3_warn) and are re-exported here so every
timing user imports from one place; a second message set would print the same warning twice."""
import math

from mt.captions import find_trigger
from mt.common import ask, ask_choice, c_float, c_time
from mt.templates.t4.warn import t4_warn, t4_warn_reset  # noqa: F401  (re-export)

MIN_SPAN = 0.05                                  # a window shorter than this is not worth drawing


def _num(v):
    """Seconds from a number or '12', '0:45', '3s' -> float; anything else (None, bool, nan, junk) -> None. Never raises."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(c_time(v)) if isinstance(v, str) else float(v)
    except (ValueError, TypeError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def _streams(cues):
    """cues = one SRT cue list [(s, e, text)] or a list of such lists (every caption stream) -> list of cue lists."""
    try:
        if cues and isinstance(cues[0], (list, tuple)) and cues[0] and isinstance(cues[0][0], (list, tuple)):
            return [c for c in cues if c]
        return [cues] if cues else []
    except (TypeError, IndexError, KeyError):
        return []


def _find(cues, phrase):
    """First stream that contains the phrase wins -> its start time, else None. Never raises."""
    for st in _streams(cues):
        try:
            t = find_trigger(st, phrase)
        except Exception:
            t = None
        if t is not None:
            return float(t)
    return None


def _label(entry):
    for k in ("label", "name", "title", "text", "trigger"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return "'%s'" % v.strip()[:40]
    return "entry"


def _start(entry, cues, lab):
    """trigger (spoken phrase) first, else the fixed start; None + one warning when neither gives a time."""
    fixed = _num(entry.get("start"))
    phrase = entry.get("trigger")
    phrase = phrase.strip() if isinstance(phrase, str) else ""
    if phrase:
        t = _find(cues, phrase)
        if t is not None:
            return t
        if fixed is None:
            t4_warn("%s: phrase '%s' not found in the captions and no start time - skipped." % (lab, phrase))
            return None
        t4_warn("%s: phrase '%s' not found in the captions - using its start time." % (lab, phrase))
    if fixed is None:
        t4_warn("%s: no start time and no trigger phrase - skipped." % lab)
    return fixed


def t4_time(entry, cues, duration, default_hold):
    """-> (start, end) in seconds, or None (skip the entry).
    start: `trigger` (spoken phrase found in cues via find_trigger; cues = one cue list or a list of streams) else `start`.
    end:   `end` (absolute, must be after start) else start + `hold` else start + default_hold (None / <= 0 -> to the video end).
    Start at or after the video end -> None; an end past the video end is clamped to `duration` (duration None / <= 0 = unknown,
    no clamping). A negative start becomes 0. Junk input never raises (one t4_warn line, None)."""
    if not isinstance(entry, dict):
        t4_warn("timing: entry is not a dict - skipped.")
        return None
    lab = _label(entry)
    st = _start(entry, cues, lab)
    if st is None:
        return None
    st = max(0.0, st)
    dur = _num(duration)
    dur = dur if dur and dur > 0 else None
    if dur is not None and st >= dur:
        t4_warn("%s: starts at %.2f s, after the video end (%.2f s) - skipped." % (lab, st, dur))
        return None
    en = _num(entry.get("end"))
    if en is not None and en <= st + MIN_SPAN:
        t4_warn("%s: end %.2f s is not after the start %.2f s - using the hold time." % (lab, en, st))
        en = None
    if en is None:
        hold = _num(entry.get("hold"))
        if hold is None or hold <= 0:
            hold = _num(default_hold)
        en = st + hold if hold and hold > 0 else (dur if dur is not None else None)
    if en is None:
        t4_warn("%s: no end / hold and the video length is unknown - skipped." % lab)
        return None
    if dur is not None:
        en = min(en, dur)
    return (st, en) if en - st >= MIN_SPAN else None


def t4_stagger(n, step):
    """Entry delays for n items that appear one after another: [0, step, 2*step, ...]. n <= 0 -> []; bad step -> 0.0."""
    try:
        n = max(0, int(n))
    except (ValueError, TypeError, OverflowError):
        return []
    s = _num(step)
    s = s if s is not None and s > 0 else 0.0
    return [round(i * s, 6) for i in range(n)]


def _c_hold(s):
    v = c_float(s)
    if not v > 0:
        raise ValueError("enter a number of seconds above 0")
    return v


def t4_ask_when(prompt, default_hold=4.0, key=None):
    """The one shared 'when does it show' question. -> {"start": seconds, "hold": s} or {"trigger": phrase, "hold": s}
    (both shapes are accepted by t4_time). key = optional prefix that remembers the answers (mt.common.D)."""
    k = (lambda n: key + n) if key else (lambda n: None)
    mode = ask_choice(f"{prompt} - when should it appear?",
                      ["At a fixed time (seconds or mm:ss)", "When a phrase is spoken (it must be in the captions)"],
                      default=1, key=k("_mode"))
    if mode == 1:
        out = {"start": ask("Start at  (seconds or mm:ss)", default=0, key=k("_start"), cast=c_time)}
    else:
        out = {"trigger": ask("Spoken phrase", key=k("_trigger")).strip()}
    out["hold"] = ask("Keep it on screen for how many seconds", default=default_hold, key=k("_hold"), cast=_c_hold)
    return out
