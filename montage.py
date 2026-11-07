#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
montage.py  -  Interactive montage builder (Pillow + FFmpeg), one entry script, three templates + Custom.

TEMPLATES (the FIRST question of the program; saved templates from templates/*.json are listed there too)
  1 = Template 1  "Tech HUD": dark blue tech background, glowing video frame, info cards, 1080x1920.
  2 = Template 2  "Lime Creator Series": dark poster look with lime accents - header (logo / name / subtitle / pill),
      two-line headline, rounded glowing video window, chapter tag ("01 INTRO"), word-by-word captions (Arabic box +
      small second line), floating B-roll card, ABOUT ME + feature rows, bottom EDITING LAYERS / MOTION GUIDE panel with
      a moving playhead, audio waveform and pagination dots, optional split screen.  1080x1920.
  3 = Template 3  "Editorial Orange": cream/orange editorial poster - name header, skewed video cut-out with an orange
      corner bracket, headline column (BEYOND / THE / CODE.), chapter tag, Arabic + English captions, tilted floating photo /
      video cards, an adaptive layout (the frame shrinks and bands slide in): photo-tiles STRIP, bottom PANEL (gallery +
      CENTER content slot with key points / big stat / image-or-video / keyword chips + checklist), and a SPLIT screen
      (video left, image / video right).  Layout AUTO (follows the content) or MANUAL (your state changes).  1080x1920.
  4 = Custom      the old free-form flow (any canvas size / background) + your saved templates.
  5.. = your saved templates (templates/<name>.json).  A saved Template 2 design restores its style and static texts;
      a saved Template 3 STYLE (palette, fonts, texts, frame, toggles) skips the style questions; everything else is asked.

QUESTION FLOW  (every question has a default: Enter = default / your last answer; the only required answer is the video)
  Template 1 / Custom:  template -> video -> SRT(s) -> template questions -> caption style -> texts -> cards ->
                        elements -> video layers -> split -> output -> quick-test seconds -> recap -> render.
  Template 3 (grouped under numbered headers):
      template -> 1 video -> 2 SRT(s) -> 3 identity / header / footer -> 4 headline -> 5 frame style (+ save the style) ->
      6 layout mode (AUTO / MANUAL) -> 7 chapter tags -> 8 captions -> 9 floating cards -> 10 photo strip ->
      11 bottom panel (gallery, centre content slot, checklist) -> 12 split screen -> 13 texts / elements / template
      layers / video layers -> 14 output + quick-test seconds -> one-line recap (template + modules on) -> "Start rendering?"
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

FONTS Template 3 looks best with (put these files in fonts/; a missing one is replaced by an installed font and the
message names the file to add):
  serif    : Playfair Display Bold = PlayfairDisplay-Bold.ttf                                   (name, headline accents)
  headline : Kanit-BlackItalic.ttf  or  Kanit-ExtraBoldItalic.ttf       (big italic words, stat numbers)
  UI text  : Rajdhani-SemiBold.ttf + Rajdhani-Light.ttf                 (roles, tagline, panel text)
  Arabic   : Cairo-ExtraBold.ttf                                        (Arabic captions and texts)
  script   : MrsSaintDelafield-Regular.ttf  or  Allura-Regular.ttf     (signature)
FONTS Template 2 looks best with (put these files in fonts/; without them it falls back to installed fonts and says which)
  headline : Kanit-ExtraBoldItalic.ttf   (or Montserrat-ExtraBoldItalic.ttf / BarlowCondensed-ExtraBoldItalic.ttf)
  UI text  : Rajdhani-Medium.ttf + Rajdhani-SemiBold.ttf   (or Barlow-Medium.ttf / Montserrat-Medium.ttf)
  Arabic   : Cairo-Bold.ttf              (or Tajawal-Bold.ttf / IBMPlexSansArabic-Bold.ttf)

INPUT NOTES
  * The video may have any size: it is fitted into its window ("fit" = whole video, "fill" = cropped), never stretched.
  * No audio is fine (silent output, procedural waveform).  SRT: UTF-8 with/without BOM, blank lines, CRLF are accepted.
  * Template 3 notes: a trigger phrase that is not in the SRT is reported and skipped; a block that starts after the end of
    the video is simply not shown; any 16:9 / 1:1 / 9:16 input works with the skewed or the straight frame.
  * Missing elements / icons / fonts / SRTs are skipped or replaced with a one-line [!] message; the render continues.
  * Captions are shown word by word (or N words at a time).  Texts and elements appear at an exact time with one of
    10 built-in animations.  Arabic + English supported (arabic-reshaper + python-bidi, or Raqm when available).
  * Requires: Python 3.9+, Pillow, arabic-reshaper, python-bidi, fonttools, FFmpeg.  numpy is optional (only Template 2's faster waveform).
"""
import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from mt.common import _require_ffmpeg, _save_defaults, get_template   # also runs the import-time pip check
from mt.fonts import setup_arabic_mode
from mt.flow import guarded, recap_and_confirm
from mt.render import _load_job, render, render_still
from mt.selftest import run_selftest
from mt.templates import interactive   # importing mt.templates fills TEMPLATE_REGISTRY (T1, T2, T3, Custom, T4)


def _main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    if recap_and_confirm(cfg, mode):
        render(cfg)


def main():
    guarded(_main)


if __name__ == "__main__":
    main()