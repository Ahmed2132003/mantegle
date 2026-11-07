# S1 notes - leaf modules moved (mt/common, mt/fonts, mt/draw, mt/anim)
Lines: montage.py 6947 -> 5839 (-1108) | mt/__init__ 1, anim 76, common 376, fonts 238, draw 496 = 1187 | total 7026.
Moved with tools/mt_move.py (improved: source-order, trimmed `from X import a,b` to used names only, `mt.*` imports first). Montage re-imports all moved names (compat re-export lines marked `# moved by mt_move`).
Decisions / deviations from SPLIT_PLAN.md:
- BASE: `mt/common.py` -> `BASE = Path(__file__).resolve().parent.parent` (+ alias `BASE_DIR`). montage re-exports BASE, TEMPLATES_DIR, FONTS_DIR, DEFAULTS_FILE (selftest still patches TEMPLATES_DIR in montage's globals; all readers are still in montage in S1).
- `_ensure_python_packages()` is called at import of mt.common, before the first PIL import (kept montage's own call too: second call is a no-op). `ImageColor` import in common is placed after that call.
- `_img_ok` -> draw.py (needs PIL; plan said common). `_vid_ok` stays in common.
- ARABIC_MODE is rebound inside mt.fonts; the only outside reader (selftest `_st_golden_status`) now reads `_mt_fonts.ARABIC_MODE` (live value). This is the one edit to existing code in montage.py.
- captions/split (planned for S1) NOT moved: this step was limited to the 4 modules.
