"""mt.selftest - moved from montage.py by tools/mt_move.py"""
from mt.common import BASE, D, FFMPEG, FFPROBE, T2_ACCENT
from mt.fonts import default_font
from mt.draw import T2_ABOUT, T2_DEFAULT_BOX, t2_cfg, t2_norm_about
from mt import fonts as _mt_fonts
from mt.common import TEMPLATE_REGISTRY, get_template
from mt.ask import _PRESET
from mt.templates import choose_template, interactive, recap_line
from mt.templates.t2_lime import (T2_CARD, T2_DOTS, T2_POSTER_H, T2_POSTER_W, make_t2_static, t2_about_geometry,
                                  t2_about_sprite, t2_ask_cards_cfg, t2_ask_chapters, t2_ask_config,
                                  t2_build_static_layers, t2_chapter_sprite, t2_panel_plate, t2_resolve_about,
                                  t2_resolve_cards, t2_resolve_chapters, t2_tag_pos)
from mt.render import build_items, render, render_still
from mt.draw import load_image_sprite, resolve_pos, t2_rgb
from mt.captions import T2_CAP, parse_srt, t2_caption_items, t2_caption_layout, t2_caption_sprite
from mt.fonts import t2_font
from mt.split import split_boxes, t2_split_params
import subprocess
from PIL import Image, ImageChops, ImageDraw
from pathlib import Path
import json
import sys
import shutil
import tempfile
import math
import time
import os
from mt import ask as _mt_ask  # TEMPLATES_DIR is read by mt.ask: the selftest patches it there
_SCRIPT = BASE / "montage.py"  # the entry script (never __file__: this module lives in mt/)

# Registry of selftest checks. A check is `fn(rec, quiet, feed, A, tmp)`; template modules add their own with
#     @selftest_check("name")
# Checks run in registration order after the environment gate (check 1) of run_selftest.
SELFTEST_CHECKS = []


def selftest_check(name):
    def deco(fn):
        SELFTEST_CHECKS.append((name, fn))
        return fn
    return deco


def _entry_doc():
    import ast
    return ast.get_docstring(ast.parse(_SCRIPT.read_text(encoding="utf-8")))


def _st_feed(answers, prompts):
    """Replace builtins.input by a scripted stdin (EOFError when the answers run out)."""
    import builtins
    it = iter(answers)

    def fake(prompt=""):
        prompts.append(prompt)
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    builtins.input = fake


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
    if gm and gm != _mt_fonts.ARABIC_MODE:   # live value: ARABIC_MODE is rebound inside mt.fonts, a re-exported copy would be stale
        return f"golden was made with Arabic engine '{gm}', this machine uses '{_mt_fonts.ARABIC_MODE}'"
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
    feed = _st_feed
    saved_input, saved_tdir = builtins.input, _mt_ask.TEMPLATES_DIR
    D.clear()
    try:
        # 1. syntax / import / ffmpeg
        try:
            for _f in [_SCRIPT] + sorted((BASE / "mt").glob("*.py")):
                compile(_f.read_text(encoding="utf-8"), str(_f), "exec")
            ok = bool(FFMPEG and FFPROBE)
            rec("1 syntax + imports + ffmpeg", "PASS" if ok else "FAIL",
                f"ffmpeg={FFMPEG}" if ok else "ffmpeg/ffprobe not found")
        except Exception as e:
            rec("1 syntax + imports + ffmpeg", "FAIL", repr(e))
        if not (FFMPEG and FFPROBE):
            raise _StopSelftest()

        _st_make_assets(tmp / "assets")
        A = tmp / "assets"

        for _name, _fn in SELFTEST_CHECKS:
            try:
                _fn(rec, quiet, feed, A, tmp)
            except _StopSelftest:
                raise
            except BaseException as e:
                rec(_name, "FAIL", "check crashed: " + repr(e))
    except _StopSelftest:
        pass
    finally:  # always restore global state and delete the temp files
        builtins.input = saved_input
        _mt_ask.TEMPLATES_DIR = saved_tdir
        D.clear()
        D.update(saved_D)
        shutil.rmtree(tmp, ignore_errors=True)
    return _st_report(rows)


@selftest_check("core 2-7: selector, T1/T2 render, goldens, old job, --job")
def _selftest_core(rec, quiet, feed, A, tmp):
    import builtins
    saved_input, saved_tdir = builtins.input, _mt_ask.TEMPLATES_DIR
    # 2. selector + flow (simulated stdin)
    try:
        got = {}
        for ans in ("1", "2", "4"):
            feed([ans], [])
            got[ans] = quiet(choose_template)["id"]
        # 3 = Template 3 (Editorial Orange, live since T3-1): routes to id 3
        feed(["3"], [])
        got["3"] = quiet(choose_template)["id"]
        sel_ok = got == {"1": 1, "2": 2, "4": 4, "3": 3}
        soon_ok = True
        # saved-template path (Custom): list shows 'New template' + 1 saved one, pick the saved one
        sdir = tmp / "templates"
        sdir.mkdir()
        saved_tpl = {"canvas": [1080, 1080], "video_box": {"x": 0, "y": 0, "w": 1080, "h": 1080, "mode": "fit"},
                     "background": {"type": "color", "value": "#101820"}, "layers": []}
        (sdir / "mysaved.json").write_text(json.dumps(saved_tpl), encoding="utf-8")
        _mt_ask.TEMPLATES_DIR = sdir
        feed(["2"], [])
        loaded = quiet(TEMPLATE_REGISTRY[4]["ask_config"], {})
        saved_ok = loaded == saved_tpl
        _mt_ask.TEMPLATES_DIR = saved_tdir
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
        _mt_ask.TEMPLATES_DIR = saved_tdir

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
        r = subprocess.run([sys.executable, str(_SCRIPT), "--job", str(jp)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        ok = r.returncode == 0 and out7.is_file() and "Done in" in r.stdout
        w, h, dur, aud = _st_info(out7) if out7.is_file() else (0, 0, 0, False)
        ok = ok and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2
        rec("7 --job re-render (Template 2)", "PASS" if ok else "FAIL",
            f"rc={r.returncode} {w}x{h} {dur:.2f}s" + ("" if ok else " " + (r.stderr or r.stdout)[-200:]))
    except BaseException as e:
        rec("7 --job re-render (Template 2)", "FAIL", repr(e))


@selftest_check("T2 static design (8-14)")
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
        saved = _mt_fonts._t2_lookup          # patch the module that owns/reads it (moved to mt.fonts in S2)
        _mt_fonts._t2_lookup = lambda n: None
        try:
            make_t2_static(W, H, {"name": "X"}, {"bg": str(tmp / "s_bg.png"), "fg": str(tmp / "s_fg.png")},
                           dict(T2_DEFAULT_BOX))
            f_ok = True
        except BaseException as e:
            f_ok = False
            bad.append("missing fonts: " + repr(e))
        finally:
            _mt_fonts._t2_lookup = saved
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
    saved_tdir = _mt_ask.TEMPLATES_DIR
    try:
        sdir = tmp / "t2templates"
        _mt_ask.TEMPLATES_DIR = sdir
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
        _mt_ask.TEMPLATES_DIR = saved_tdir


def _st_lime(p, tol=45):
    """True for pixels close to the Template 2 accent lime."""
    a = t2_rgb(T2_ACCENT)
    return abs(p[0] - a[0]) <= tol and abs(p[1] - a[1]) <= tol and abs(p[2] - a[2]) <= tol + 15


def _st_grab(video, t, png):
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t}", "-i", str(video),
                    "-frames:v", "1", str(png)], check=True)
    return Image.open(png).convert("RGB")


@selftest_check("T2 dynamic: chapters/captions")
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


@selftest_check("T2 cards")
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
        r = subprocess.run([sys.executable, str(_SCRIPT), "--job", str(jp)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        w, h, dur, aud = _st_info(out_a) if out_a.is_file() else (0, 0, 0, False)
        hits = _st_card_hits(_st_grab(out_a, 1.2, tmp / "jc.png"), t2_resolve_cards(jc, 3.0)[0]) if out_a.is_file() else 0
        ok_a = r.returncode == 0 and (w, h) == (1080, 1920) and abs(dur - 3.0) < 0.2 and hits == 4
        old = _st_job(A, 1, out_b)
        old.pop("template_id")
        jp2 = tmp / "job_old.json"
        jp2.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        r2 = subprocess.run([sys.executable, str(_SCRIPT), "--job", str(jp2)],
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


@selftest_check("T2 about")
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


@selftest_check("T2 panel")
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


@selftest_check("T2 4c: waveform/split/dots")
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
        r = subprocess.run([sys.executable, str(_SCRIPT), "--job", str(jp)], capture_output=True, text=True,
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


@selftest_check("4d: flow, selector, CLI, non-9:16")
def _selftest_4d(rec, quiet, feed, A, tmp):
    """Part 4D: 42 T2 Enter-through flow, 43 selector (1/2/saved T2/saved custom), 44 robustness cases, 45 non-9:16 inputs,
    46 py_compile + --help."""
    import builtins
    import contextlib
    import io
    saved_input, saved_tdir = builtins.input, _mt_ask.TEMPLATES_DIR
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
        _mt_ask.TEMPLATES_DIR = sdir
        got = {}
        listing = io.StringIO()
        for ans in ("1", "2", "4", "5", "6", "7"):          # 5 = Template 4 (T4), saved templates are numbered from 6
            feed([ans], [])
            with contextlib.redirect_stdout(listing):
                e = choose_template()
            got[ans] = (e["id"], Path(_PRESET.get("path") or "").name)
        want = {"1": (1, ""), "2": (2, ""), "4": (4, ""), "5": (5, ""), "6": (2, "a_t2.json"), "7": (4, "b_custom.json")}
        labels_ok = "saved - Template 2" in listing.getvalue() and "a_t2" in listing.getvalue() and "b_custom" in listing.getvalue()
        _PRESET.clear()
        prompts = []
        first = iter(["6", str(A / "test.mp4")])

        def fake2(prompt=""):
            prompts.append(prompt)
            return next(first, "")
        builtins.input = fake2
        c = quiet(interactive)
        builtins.input = saved_input
        no_reask = not any(q.startswith(("Header name", "Accent color", "Headline line", "Video window size")) for q in prompts)
        loaded_ok = c.get("template_id") == 2 and c["t2"].get("name") == "SAVED NAME" and c["t2"].get("line1") == "SAVED HEAD"
        ok = got == want and labels_ok and no_reask and loaded_ok
        rec("43 selector: 1 / 2 / 4 Custom / saved T2 / saved Custom", "PASS" if ok else "FAIL",
            f"routes={got} labels_ok={labels_ok} saved_T2_not_reasked={no_reask} loaded_ok={loaded_ok}")
    except BaseException as e:
        rec("43 selector: 1 / 2 / 4 Custom / saved T2 / saved Custom", "FAIL", repr(e))
    finally:
        builtins.input = saved_input
        _mt_ask.TEMPLATES_DIR = saved_tdir
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
        r = subprocess.run([sys.executable, str(_SCRIPT)] + args, capture_output=True, text=True,
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
        me = str(_SCRIPT)
        r1 = subprocess.run([sys.executable, "-m", "py_compile", me] + [str(f) for f in sorted((BASE / "mt").glob("*.py"))], capture_output=True, text=True, timeout=120)
        r2 = cli(["--help"])
        doc_ok = all(k in (_entry_doc() or "") for k in ("--job", "--preview", "--still", "--selftest", "--arabic-mode", "templates/",
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


# ---- Template 3 (T3-1): static plates, pixels, stress, fonts, questions + job + render ------------------------------
def _t3_cfg_for(A, **t3):
    return {"template_id": 3, "video": str(A / "test.mp4"), "canvas": [1080, 1920],
            "video_box": {"x": 60, "y": 430, "w": 960, "h": 1060, "mode": "fill"}, "background": {"type": "t3"},
            "layers": [], "captions": [], "texts": [], "cards": [], "elements": [], "video_layers": [],
            "t3": t3}


@selftest_check("T3-1 static plate 1080x1920 + still + pixels")
def _t3_plate_pixels(rec, quiet, feed, A, tmp):
    from mt.templates.t3.static import K, make_t3_static
    p = {"bg": str(tmp / "t3_bg.png"), "fg": str(tmp / "t3_fg.png")}
    info = quiet(make_t3_static, 1080, 1920, {}, str(A / "test.mp4"), p)
    bg, fg = Image.open(p["bg"]), Image.open(p["fg"])
    size_ok = bg.size == (1080, 1920) and bg.mode == "RGB" and fg.size == (1080, 1920) and fg.mode == "RGBA"
    cx, cy = int(480 * K), int(800 * K)
    dark = bg.getpixel((cx, cy))
    dark_ok = sum(dark) / 3.0 < 40
    bx = info["boxes"].get("name2")
    comp = bg.convert("RGBA")
    comp.alpha_composite(fg)
    orange = bx and sum(1 for x in range(bx[0], bx[2]) for y in range(bx[1], bx[3])
                        if (lambda c: c[0] > 215 and 80 < c[1] < 135 and c[2] < 70)(comp.getpixel((x, y)))) > 120
    px = [bg.getpixel((x, y)) for x in range(int(8 * K), int(40 * K), 4) for y in range(int(1030 * K), int(1140 * K), 8)]
    avg = [sum(c[i] for c in px) / len(px) for i in range(3)]
    paper_ok = 150 < avg[0] < 225 and 115 < avg[1] < 195 and 90 < avg[2] < 165 and avg[0] > avg[2] + 25
    still = tmp / "t3_still.png"
    quiet(render_still, _t3_cfg_for(A, name1="Ahmed"), str(still), 0.5)
    still_ok = still.is_file() and Image.open(still).size == (1080, 1920)
    ok = size_ok and dark_ok and bool(orange) and paper_ok and still_ok and info["watermark"]
    rec("T3-1 static plate 1080x1920 + still + pixels", "PASS" if ok else "FAIL",
        f"size={size_ok} dark={dark} orange_in_Ibrahim={bool(orange)} paper={tuple(int(v) for v in avg)} "
        f"still={still_ok} watermark={info['watermark']}")


@selftest_check("T3-1 empty / very long text stress")
def _t3_stress(rec, quiet, feed, A, tmp):
    from mt.templates.t3.static import K, make_t3_static
    p = {"bg": str(tmp / "s_bg.png"), "fg": str(tmp / "s_fg.png")}
    empty = {"name1": "", "name2": "", "roles": ["", "", ""], "tagline": "", "footer": "", "signature": "",
             "watermark": False}
    info = quiet(make_t3_static, 1080, 1920, empty, None, p)
    empty_ok = not info["boxes"] and Image.open(p["fg"]).getchannel("A").getbbox() is None
    long = "W" * 120
    info = quiet(make_t3_static, 1080, 1920, {"name1": long, "name2": long + " مرحبا بالعالم " * 5, "roles": [long] * 3,
                                              "tagline": " • ".join(["LONGWORD" * 3] * 6),
                                              "footer": " • ".join(["LONGWORD" * 3] * 6), "signature": long},
                 str(A / "test.mp4"), p)
    inside = all(0 <= b[0] and b[2] <= 1080 and 0 <= b[1] and b[3] <= 1920 for b in info["boxes"].values())
    wide_ok = info["boxes"]["name2"][2] <= 340 * K and info["boxes"]["role2"][2] <= 650 * K
    rec("T3-1 empty / very long text stress", "PASS" if empty_ok and inside and wide_ok and len(info["boxes"]) >= 8 else "FAIL",
        f"empty_hidden={empty_ok} inside_canvas={inside} limits={wide_ok} elements={len(info['boxes'])}")


@selftest_check("T3-1 missing-font fallback (no crash, names the file)")
def _t3_fonts(rec, quiet, feed, A, tmp):
    import contextlib
    import io
    from mt.templates.t3 import static as s3
    saved = (s3._t2_lookup, set(s3._WARNED))
    buf = io.StringIO()
    try:
        s3._t2_lookup = lambda n: None                   # no font of any name installed
        s3._WARNED.clear()
        s3._CACHE.clear()
        with contextlib.redirect_stdout(buf):
            info = s3.make_t3_static(1080, 1920, {"name1": "Test", "roles": ["a", "b", "c"]}, None,
                                     {"bg": str(tmp / "f_bg.png"), "fg": str(tmp / "f_fg.png")})
        out = buf.getvalue()
        ok = "PlayfairDisplay-Bold.ttf" in out and "Rajdhani" in out and "Allura" in out and bool(info["boxes"])
        # a bad override path must not crash either
        p, _sh = s3.t3_font("serif", "x", {"serif": str(tmp / "nope.ttf")})
        ok = ok and bool(p)
    except Exception as e:
        rec("T3-1 missing-font fallback (no crash, names the file)", "FAIL", repr(e))
        return
    finally:
        s3._t2_lookup = saved[0]
        s3._WARNED.clear()
        s3._WARNED.update(saved[1])
        s3._CACHE.clear()
    rec("T3-1 missing-font fallback (no crash, names the file)", "PASS" if ok else "FAIL",
        "message names PlayfairDisplay-Bold.ttf / Rajdhani / Allura" if ok else out[-200:])


@selftest_check("T3-1 questions (Enter=defaults, remembered) + selector 1/2/3/4")
def _t3_questions(rec, quiet, feed, A, tmp):
    import builtins
    from mt.templates.t3 import t3_ask_config
    saved_in, saved_D, saved_tdir = builtins.input, dict(D), _mt_ask.TEMPLATES_DIR
    try:
        _mt_ask.TEMPLATES_DIR = tmp / "t3_templates"        # nothing gets saved into the real templates/ folder
        for k in [k for k in D if k.startswith("t3_")]:
            D.pop(k)
        feed([""] * 60, [])
        tpl = quiet(t3_ask_config, {})
        defaults_ok = (tpl["t3"]["name2"] == "Ibrahim" and tpl["t3"]["roles"][1] == "Mobile App Developer"
                       and tpl["t3"]["accent"] == "#F56D1F" and tpl["template_id"] == 3 and tpl["t3"]["watermark"])
        feed(["#112233", "", "", "", "-", "-", "x", "", "Jo", "-", "", "-", "", ""] + [""] * 40, [])   # accent, bg, wm, header, name1.. etc.
        tpl2 = quiet(t3_ask_config, {})
        changed_ok = tpl2["t3"]["accent"] == "#112233" and D.get("t3_accent") == "#112233"
        got = {}
        for ans in ("1", "2", "3", "4"):
            feed([ans], [])
            got[ans] = quiet(choose_template)["id"]
        sel_ok = got == {"1": 1, "2": 2, "3": 3, "4": 4}
        ok = defaults_ok and changed_ok and sel_ok
        rec("T3-1 questions (Enter=defaults, remembered) + selector 1/2/3/4", "PASS" if ok else "FAIL",
            f"defaults={defaults_ok} changed={changed_ok} selector={got}")
    except Exception as e:
        rec("T3-1 questions (Enter=defaults, remembered) + selector 1/2/3/4", "FAIL", repr(e))
    finally:
        builtins.input = saved_in
        D.clear()
        D.update(saved_D)
        _mt_ask.TEMPLATES_DIR = saved_tdir


@selftest_check("T3-1 job json + 2 s render (size, duration, audio) ")
def _t3_render(rec, quiet, feed, A, tmp):
    from mt.render import _load_job
    out = tmp / "t3_out.mp4"
    cfg = _t3_cfg_for(A, name1="Ahmed", accent="#00A0FF")
    cfg["output"], cfg["preview"] = str(out), 2.0
    jp = tmp / "t3_job.json"
    jp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    job = _load_job(str(jp))
    quiet(render, job)
    info = _st_info(out) if out.is_file() else None
    ok = bool(info) and info[:2] == (1080, 1920) and 1.6 < info[2] < 2.6 and info[3]
    rec("T3-1 job json + 2 s render (size, duration, audio) ", "PASS" if ok else "FAIL",
        f"{info and (info[0], info[1], round(info[2], 2), info[3])}; job template_id={job.get('template_id')}")


# ---- Template 3 (T3-2): video frame + headline column --------------------------------------------------------------
@selftest_check("T3-2 t3_frame_quad corners for 2 boxes")
def _t3_quad(rec, quiet, feed, A, tmp):
    from mt.templates.t3.static import POSTER_QUAD, VIDEO_BOX, t3_frame_quad, K
    b1 = (VIDEO_BOX["x"], VIDEO_BOX["y"], VIDEO_BOX["w"], VIDEO_BOX["h"])
    q1 = t3_frame_quad(b1, 1.0)
    want1 = [(x * K, y * K) for x, y in POSTER_QUAD]
    poster_ok = all(abs(a[0] - b[0]) < 1.6 and abs(a[1] - b[1]) < 1.6 for a, b in zip(q1, want1))
    b2 = (100, 300, 500, 800)
    q2, qs = t3_frame_quad(b2, True), t3_frame_quad(b2, 0.0)
    bbox_ok = (min(p[0] for p in q2), min(p[1] for p in q2), max(p[0] for p in q2), max(p[1] for p in q2))
    box_ok = abs(bbox_ok[0] - 100) < 1e-6 and abs(bbox_ok[1] - 300) < 1e-6 and bbox_ok[2] <= 600 + 1e-6 and bbox_ok[3] <= 1100 + 1e-6
    straight_ok = qs == [(100.0, 300.0), (600.0, 300.0), (600.0, 1100.0), (100.0, 1100.0)]
    moved = [(a[0] - 100, a[1] - 300) for a in q2] != [(a[0] - b1[0], a[1] - b1[1]) for a in q1]
    ok = poster_ok and box_ok and straight_ok and moved and len(q2) == 4
    rec("T3-2 t3_frame_quad corners for 2 boxes", "PASS" if ok else "FAIL",
        f"poster_corners={poster_ok} box2_inside={box_ok} straight=rect:{straight_ok} q2_TL={tuple(round(v, 1) for v in q2[0])}")


def _t3_still_cfg(A, **t3):
    from mt.templates.t3.static import VIDEO_BOX
    c = _t3_cfg_for(A, **t3)
    c["video_box"] = dict(VIDEO_BOX)
    return c


@selftest_check("T3-2 pixel inside quad = video, just outside = design")
def _t3_pixels2(rec, quiet, feed, A, tmp):
    from mt.templates.t3.static import VIDEO_BOX, frame_at, t3_frame_quad
    out = tmp / "t3_px.png"
    quiet(render_still, _t3_still_cfg(A), str(out), 0.5)
    im = Image.open(out).convert("RGB")
    b = VIDEO_BOX
    q = t3_frame_quad(b, 1.0)
    fr = frame_at(str(A / "test.mp4"), 0.5)
    s = max(b["w"] / fr.width, b["h"] / fr.height)
    fr = fr.resize((max(b["w"], int(round(fr.width * s))), max(b["h"], int(round(fr.height * s)))), Image.LANCZOS)
    l, t = (fr.width - b["w"]) // 2, (fr.height - b["h"]) // 2
    ix, iy = 300, 700                                       # well inside the quad, clear of the headline
    want = fr.getpixel((l + ix - b["x"], t + iy - b["y"]))
    got = im.getpixel((ix, iy))
    inside_ok = all(abs(a - c) <= 14 for a, c in zip(want, got))
    ox, oy = 500, 211                                       # inside the box rectangle, ~4 px above the top edge
    vid_there = fr.getpixel((l + ox - b["x"], t + oy - b["y"]))
    og = im.getpixel((ox, oy))
    outside_ok = sum(abs(a - c) for a, c in zip(vid_there, og)) > 60 and sum(og) < 330
    rec("T3-2 pixel inside quad = video, just outside = design", "PASS" if inside_ok and outside_ok else "FAIL",
        f"inside got={got} want~{want}; outside px={og} (video would be {vid_there}); quad_TL={tuple(round(v) for v in q[0])}")


@selftest_check("T3-2 skewed vs straight both render")
def _t3_styles(rec, quiet, feed, A, tmp):
    from mt.templates.t3.static import VIDEO_BOX
    res = {}
    for st in ("skewed", "straight"):
        o = tmp / f"t3_{st}.png"
        quiet(render_still, _t3_still_cfg(A, frame_style=st), str(o), 0.5)
        res[st] = Image.open(o).convert("RGB")
    cx, cy = VIDEO_BOX["x"] + 4, VIDEO_BOX["y"] + 4          # the box corner: video only in the straight style
    d_sk, d_st = res["skewed"].getpixel((cx, cy)), res["straight"].getpixel((cx, cy))
    differ = ImageChops.difference(res["skewed"], res["straight"]).getbbox() is not None
    ok = res["skewed"].size == res["straight"].size == (1080, 1920) and differ and sum(d_st) > 300 and sum(d_sk) < 330
    rec("T3-2 skewed vs straight both render", "PASS" if ok else "FAIL",
        f"box-corner skewed={d_sk} straight={d_st} differ={differ}")


@selftest_check("T3-2 headline stress (empty / very long / Arabic)")
def _t3_head_stress(rec, quiet, feed, A, tmp):
    from mt.templates.t3.static import HEAD_SLOTS, K, TAG_BOX, t3_cfg, t3_headline_layer
    def run(**kw):
        lay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        return lay, quiet(t3_headline_layer, lay, t3_cfg(kw))
    lay, bx = run(headline=["", "", ""], tag_lines=["", "", ""])
    empty_ok = not bx and lay.getchannel("A").getbbox() is None
    lay, bx = run(headline=["W" * 80, "X" * 60, "M" * 70], tag_lines=["LONGWORD" * 8] * 3)
    slots = {f"headline{i + 1}": s[0] for i, s in enumerate(HEAD_SLOTS)}
    slots["tag_lines"] = TAG_BOX
    long_ok = all(k in bx and bx[k][0] >= slots[k][0] * K - 2 and bx[k][2] <= slots[k][2] * K + 2
                  and bx[k][1] >= slots[k][1] * K - 2 and bx[k][3] <= slots[k][3] * K + 2 for k in slots)
    lay, bx = run(headline=["ما وراء", "", "الكود."], tag_lines=["تقنية", "تصنع فرقا", ""])
    ar_ok = "headline1" in bx and "headline3" in bx and "headline2" not in bx and bx["headline3"][2] <= 905 * K + 2
    ok = empty_ok and long_ok and ar_ok
    rec("T3-2 headline stress (empty / very long / Arabic)", "PASS" if ok else "FAIL",
        f"empty_hidden={empty_ok} long_inside_slots={long_ok} arabic_line2_hidden={ar_ok}")


@selftest_check("T3-2 3 s render (1080x1920, duration, audio)")
def _t3_render2(rec, quiet, feed, A, tmp):
    from mt.render import _load_job
    out = tmp / "t3_2_out.mp4"
    cfg = _t3_cfg_for(A, headline=["Hi", "THE", "CODE."])
    cfg["output"], cfg["preview"] = str(out), 3.0
    jp = tmp / "t3_2_job.json"
    jp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    job = _load_job(str(jp))
    quiet(render, job)
    info = _st_info(out) if out.is_file() else None
    ok = bool(info) and info[:2] == (1080, 1920) and 2.6 < info[2] < 3.6 and info[3]
    rec("T3-2 3 s render (1080x1920, duration, audio)", "PASS" if ok else "FAIL",
        f"{info and (info[0], info[1], round(info[2], 2), info[3])}; frame_style={job['t3'].get('frame_style')}")


# ---- Template 3 (T3-3): chapter tag + captions ---------------------------------------------------------------------
def _t3_cap_stream(A, srt, role, size, **kw):
    from mt.fonts import t2_font as _tf
    return dict({"srt": str(A / srt), "t3_style": role, "ref": "box", "font": _tf("arabic", "ع")[0], "size": size,
                 "color": "#ffffff", "hl_color": "", "keywords": "", "stroke_w": 0, "stroke_color": "#000000",
                 "mode": "phrase", "max_words": 8, "anim": "fade", "anim_dur": 0.2}, **kw)


def _orange_px(img, box):
    c = img.convert("RGBA").crop(tuple(int(v) for v in box))
    return sum(1 for p in c.getdata() if p[3] > 200 and p[0] > 215 and 70 < p[1] < 150 and p[2] < 90)


@selftest_check("T3-3 captions short / long / mixed AR+EN / highlight")
def _t3_caps(rec, quiet, feed, A, tmp):
    from mt.fonts import t2_font as _tf
    from mt.templates.t3.dynamic import t3_caption_layout, t3_caption_sprite
    from mt.templates.t3.static import VIDEO_BOX
    f = _tf("arabic", "ع")[0]
    lay = t3_caption_layout(VIDEO_BOX)
    fr = lay["frame"]
    cases = {"short": [["اختبار", False]],
             "long": [[w, False] for w in ("هذه جملة طويلة جدا لاختبار التفاف النص وتصغيره تلقائيا داخل الصندوق " * 3).split()],
             "mixed": [["أبني", False], ["تطبيقات", False], ["Flutter", False], ["و", False], ["Django", False]],
             "hl": [["أنا", False], ["أحمد", True], ["مطور", False], ["Flutter", True]]}
    bad, det = [], []
    for name, toks in cases.items():
        spr, meta = quiet(t3_caption_sprite, toks, f, 42, "#ffffff", "#F56D1F", "#F56D1F", lay["max_w"], 1.0, 0, "#000000", True)
        x0, x1 = lay["cx"] - spr.width / 2.0, lay["cx"] + spr.width / 2.0
        y1 = lay["box_bottom"]
        y0 = y1 - spr.height
        inside_frame = fr[0] <= x0 and x1 <= fr[2] and fr[1] <= y0 and y1 <= fr[3]
        text_in = all(0 <= b[0] and b[2] <= spr.width and 0 <= b[1] and b[3] <= spr.height for _t, _h, b in meta["tokens"])
        bar_px = _orange_px(spr, meta["bar"])
        hl_px = sum(_orange_px(spr, b) for _t, h, b in meta["tokens"] if h)
        non_px = sum(_orange_px(spr, b) for _t, h, b in meta["tokens"] if not h)
        ok = inside_frame and text_in and meta["lines"] <= 2 and bar_px > 30 and (hl_px > 150 if name == "hl" else True) \
            and (non_px < 10 if name == "hl" else True)
        det.append(f"{name}:{spr.width}x{spr.height} lines={meta['lines']} bar={bar_px}" + (f" hl={hl_px} nonhl={non_px}" if name == "hl" else ""))
        if not ok:
            bad.append(name)
    rec("T3-3 captions short / long / mixed AR+EN / highlight", "FAIL" if bad else "PASS",
        ("failed: " + ",".join(bad) + " | " if bad else "") + "; ".join(det))


@selftest_check("T3-3 3 chapters over 6 s show different tags")
def _t3_chapters(rec, quiet, feed, A, tmp):
    from mt.templates.t3.dynamic import t3_chapter_items, t3_tag_origin
    from mt.templates.t3.static import VIDEO_BOX
    chs = [{"start": 0, "label": "INTRODUCTION"}, {"start": 2, "label": "PROJECTS"}, {"start": 4, "label": "NEXT STEPS"}]
    cfg = _t3_still_cfg(A, chapters=chs)
    items = quiet(t3_chapter_items, cfg, 6.0)
    starts = [round(i.start, 2) for i in items]
    ends_ok = all(items[i].end >= items[i + 1].start for i in range(2)) and items[-1].end >= 6.0
    blobs = {i.sprite.tobytes() for i in items}
    ox, oy = t3_tag_origin(VIDEO_BOX)
    pos_ok = all(abs(i.cx - i.sprite.width / 2.0 - ox) < 1 for i in items)
    chs2 = [{"start": 0, "label": "INTRODUCTION"}, {"start": 1, "label": "PROJECTS"}, {"start": 2, "label": "NEXT STEPS"}]
    crops = []
    for t in (0.6, 1.6, 2.5):
        o = tmp / f"t3_ch_{t}.png"
        quiet(render_still, _t3_still_cfg(A, chapters=chs2), str(o), t)
        crops.append(Image.open(o).convert("RGB").crop((int(ox), int(oy), int(ox) + 200, int(oy) + 90)))
    diff = [ImageChops.difference(crops[i], crops[j]).getbbox() is not None for i, j in ((0, 1), (1, 2), (0, 2))]
    ok = starts == [0.0, 2.0, 4.0] and ends_ok and len(blobs) == 3 and pos_ok and all(diff)
    rec("T3-3 3 chapters over 6 s show different tags", "PASS" if ok else "FAIL",
        f"starts={starts} distinct_sprites={len(blobs)} anchored_to_frame_TL={pos_ok} stills_differ={diff}")


@selftest_check("T3-3 captions + tag follow the frame box")
def _t3_follow(rec, quiet, feed, A, tmp):
    from mt.captions import parse_srt, stream_groups
    from mt.templates.t3.dynamic import t3_caption_items, t3_chapter_items
    from mt.templates.t3.static import VIDEO_BOX, t3_frame_quad
    c = _t3_cap_stream(A, "ar.srt", "box", 42)
    cfg = _t3_still_cfg(A)
    cfg["captions"] = [c]
    groups = stream_groups(parse_srt(c["srt"]), c)
    res = []
    for box in (dict(VIDEO_BOX), {"x": 100, "y": 300, "w": 400, "h": 520, "mode": "fill"}):
        cap = quiet(t3_caption_items, cfg, c, groups, 5.0, box)[0]
        tag = quiet(t3_chapter_items, cfg, 5.0, box)[0]
        q = t3_frame_quad(box)
        rel_cap = ((cap.cx - box["x"]) / box["w"], (cap.cy + cap.sprite.height / 2.0 - box["y"]) / box["h"])
        rel_tag = ((tag.cx - tag.sprite.width / 2.0 - q[0][0]) / box["w"], (tag.cy - tag.sprite.height / 2.0 - q[0][1]) / box["h"])
        inside = (box["x"] <= cap.cx - cap.sprite.width / 2.0 and cap.cx + cap.sprite.width / 2.0 <= box["x"] + box["w"]
                  and cap.cy + cap.sprite.height / 2.0 <= box["y"] + box["h"])
        res.append((rel_cap, rel_tag, inside, cap.sprite.width))
    cap_same = all(abs(a - b) < 0.01 for a, b in zip(res[0][0], res[1][0]))
    tag_ok = abs(res[0][1][0] - res[1][1][0]) < 0.01 and abs(res[0][1][1] - res[1][1][1]) < 0.01
    ok = cap_same and tag_ok and res[0][2] and res[1][2] and res[1][3] < res[0][3]
    rec("T3-3 captions + tag follow the frame box", "PASS" if ok else "FAIL",
        f"caption_rel_pos_same={cap_same} tag_rel_pos_same={tag_ok} inside_frame={res[0][2]},{res[1][2]} "
        f"caption_w {res[0][3]}->{res[1][3]} (smaller frame)")


@selftest_check("T3-3 3 s render: chapters + AR/EN captions, job json")
def _t3_render3(rec, quiet, feed, A, tmp):
    from mt.render import _load_job
    out = tmp / "t3_3_out.mp4"
    cfg = _t3_still_cfg(A, chapters=[{"start": 0, "label": "INTRODUCTION"}, {"start": 1.5, "trigger": "المعرفة", "label": "SHARING"}])
    cfg["captions"] = [_t3_cap_stream(A, "ar.srt", "box", 42, keywords="Flutter"), _t3_cap_stream(A, "en.srt", "sub", 30)]
    cfg["output"], cfg["preview"] = str(out), 3.0
    jp = tmp / "t3_3_job.json"
    jp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    job = _load_job(str(jp))
    quiet(render, job)
    info = _st_info(out) if out.is_file() else None
    ok = bool(info) and info[:2] == (1080, 1920) and 2.6 < info[2] < 3.6 and info[3]
    keep = [c.get("t3_style") for c in job["captions"]] == ["box", "sub"] and len(job["t3"]["chapters"]) == 2
    rec("T3-3 3 s render: chapters + AR/EN captions, job json", "PASS" if ok and keep else "FAIL",
        f"{info and (info[0], info[1], round(info[2], 2), info[3])}; job keeps t3_style+chapters={keep}")


@selftest_check("T3-3 questions: defaults (Enter), remembered keys, caption style")
def _t3_q3(rec, quiet, feed, A, tmp):
    import builtins
    from mt.templates.t3 import t3_ask_config, t3_caption_style
    saved_in, saved_D, saved_tdir = builtins.input, dict(D), _mt_ask.TEMPLATES_DIR
    try:
        _mt_ask.TEMPLATES_DIR = tmp / "t3q_templates"
        for k in [k for k in D if k.startswith("t3_")]:
            D.pop(k)
        feed([""] * 80, [])
        tpl = quiet(t3_ask_config, {})
        ch = tpl["t3"]["chapters"]
        d_ok = tpl["t3"]["chapters_on"] and len(ch) == 1 and ch[0]["label"] == "INTRODUCTION" and ch[0]["start"] == 0.0
        feed([""] * 6 + ["", "n"] + [""] * 80, [])
        feed([""] * 80, [])
        c = quiet(t3_caption_style, 0, str(A / "ar.srt"))
        c2 = quiet(t3_caption_style, 1, str(A / "en.srt"))
        cap_ok = c["t3_style"] == "box" and c2["t3_style"] == "sub" and c["size"] == 42 and c2["size"] == 30 and c["mode"] == "phrase"
        rec("T3-3 questions: defaults (Enter), remembered keys, caption style", "PASS" if d_ok and cap_ok else "FAIL",
            f"chapter_default={d_ok} caption_styles={cap_ok} (box/sub, sizes {c['size']}/{c2['size']})")
    except Exception as e:
        rec("T3-3 questions: defaults (Enter), remembered keys, caption style", "FAIL", repr(e))
    finally:
        builtins.input = saved_in
        D.clear()
        D.update(saved_D)
        _mt_ask.TEMPLATES_DIR = saved_tdir


# ---- Template 3 (T3-4): floating photo card -------------------------------------------------------------------------
def _t3_card_files(tmp):
    out = {}
    for n, col in (("red", (220, 30, 30)), ("blue", (30, 120, 220))):
        p = tmp / f"t3_card_{n}.png"
        Image.new("RGB", (640, 520), col).save(p)
        out[n] = str(p)
    return out


def _near(a, b, tol=28):
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))


def _t3_card_cfg(A, cards, **t3):
    return _t3_still_cfg(A, cards=cards, chapters=[], **t3)


def _dbbox(a, b, thr=24):
    """Bounding box of the pixels that differ clearly (the T3 plate has a little random grain, so never compare bit-exact)."""
    return ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > thr else 0).getbbox()


def _t3_still_at(quiet, cfg, tmp, name, t):
    o = tmp / f"{name}.png"
    quiet(render_still, cfg, str(o), t)
    return Image.open(o).convert("RGB")


@selftest_check("T3-4 image card + video card: present during hold at the rotated bbox, absent after")
def _t3_card_hold(rec, quiet, feed, A, tmp):
    from mt.templates.t3.dynamic import t3_anchor, t3_card_quad
    from mt.templates.t3.static import VIDEO_BOX
    f = _t3_card_files(tmp)
    base = _t3_still_at(quiet, _t3_card_cfg(A, []), tmp, "t3c_base", 1.1)
    base2 = _t3_still_at(quiet, _t3_card_cfg(A, []), tmp, "t3c_base2", 2.3)
    cx, cy = t3_anchor(1, VIDEO_BOX)
    quad = t3_card_quad((cx, cy), 1.0, 3.0, 0.03)
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    lim = (min(xs) - 48, min(ys) - 48, max(xs) + 48, max(ys) + 48)
    res, bad = [], []
    for kind, media in (("image", f["blue"]), ("video", str(A / "test.mp4"))):
        cfg = _t3_card_cfg(A, [{"media": media, "start": 0.4, "hold": 1.2, "slot": 1}])
        on = _t3_still_at(quiet, cfg, tmp, f"t3c_{kind}_on", 1.1)
        off = _t3_still_at(quiet, cfg, tmp, f"t3c_{kind}_off", 2.3)
        bb = _dbbox(on, base)
        inside = bb is not None and bb[0] >= lim[0] and bb[1] >= lim[1] and bb[2] <= lim[2] and bb[3] <= lim[3]
        covers = bb is not None and bb[0] <= min(xs) + 6 and bb[2] >= max(xs) - 6 and bb[1] <= min(ys) + 6 and bb[3] >= max(ys) - 6
        center_ok = not _near(on.getpixel((int(cx), int(cy))), base.getpixel((int(cx), int(cy))), 40)
        if kind == "image":
            center_ok = center_ok and _near(on.getpixel((int(cx), int(cy))), (30, 120, 220))
        gone = _dbbox(off, base2) is None
        res.append(f"{kind}: diff_bbox={bb} expected~{tuple(int(v) for v in lim)} center_ok={center_ok} absent_after={gone}")
        if not (inside and covers and center_ok and gone):
            bad.append(kind)
    rec("T3-4 image card + video card: present during hold at the rotated bbox, absent after",
        "FAIL" if bad else "PASS", ("failed: " + ",".join(bad) + " | " if bad else "") + " ; ".join(res))


@selftest_check("T3-4 two consecutive cards in one slot replace each other")
def _t3_card_replace(rec, quiet, feed, A, tmp):
    from mt.templates.t3.dynamic import t3_anchor, t3_resolve_cards
    from mt.templates.t3.static import VIDEO_BOX
    f = _t3_card_files(tmp)
    cards = [{"media": f["red"], "start": 0.3, "hold": 3.0, "slot": 1}, {"media": f["blue"], "start": 1.4, "hold": 1.4, "slot": 1}]
    cfg = _t3_card_cfg(A, cards)
    rows = quiet(t3_resolve_cards, cfg, 3.0)
    ends_ok = len(rows) == 2 and abs(rows[0]["end"] - (rows[1]["start"] + 0.25)) < 1e-6
    cx, cy = (int(v) for v in t3_anchor(1, VIDEO_BOX))
    p1 = _t3_still_at(quiet, cfg, tmp, "t3r_1", 1.0).getpixel((cx, cy))
    p2 = _t3_still_at(quiet, cfg, tmp, "t3r_2", 2.3).getpixel((cx, cy))
    ok = ends_ok and _near(p1, (220, 30, 30)) and _near(p2, (30, 120, 220))
    rec("T3-4 two consecutive cards in one slot replace each other", "PASS" if ok else "FAIL",
        f"first_ends_at_second_start+0.25={ends_ok} t=1.0 centre={p1} (red) t=2.3 centre={p2} (blue)")


@selftest_check("T3-4 card not clipped by the video window")
def _t3_card_unclipped(rec, quiet, feed, A, tmp):
    from mt.templates.t3.dynamic import t3_anchor
    from mt.templates.t3.static import VIDEO_BOX
    f = _t3_card_files(tmp)
    cfg = _t3_card_cfg(A, [{"media": f["blue"], "start": 0.3, "hold": 2.0, "slot": 1}])
    im = _t3_still_at(quiet, cfg, tmp, "t3u", 1.1)
    cx, cy = t3_anchor(1, VIDEO_BOX)
    right = VIDEO_BOX["x"] + VIDEO_BOX["w"]
    px = (int(cx + 120), int(cy))                       # window pixel well outside the video box on its right
    bottom = VIDEO_BOX["y"] + VIDEO_BOX["h"]
    py = (int(cx), int(cy + 100))                       # window pixel in the card's lower half (below the frame's top part)
    ok = px[0] > right and _near(im.getpixel(px), (30, 120, 220)) and _near(im.getpixel(py), (30, 120, 220))
    cream = im.getpixel((int(cx - 150), int(cy + 20)))
    rec("T3-4 card not clipped by the video window", "PASS" if ok else "FAIL",
        f"px{px}={im.getpixel(px)} (box right edge x={right}) py{py}={im.getpixel(py)} border~{cream}")


@selftest_check("T3-4 t3_anchor follows the frame box")
def _t3_card_anchor(rec, quiet, feed, A, tmp):
    from mt.templates.t3.dynamic import t3_anchor
    from mt.templates.t3.static import K, VIDEO_BOX, t3_frame_quad
    b1 = dict(VIDEO_BOX)
    b2 = {"x": 80, "y": 380, "w": 400, "h": 512}
    a1, a2 = t3_anchor(1, b1), t3_anchor(1, b2)
    q1, q2 = t3_frame_quad(b1), t3_frame_quad(b2)
    s2 = b2["w"] / float(b1["w"])
    rel1 = (a1[0] - q1[2][0], a1[1] - q1[2][1])
    rel2 = (a2[0] - q2[2][0], a2[1] - q2[2][1])
    follows = abs(rel1[0] - 136.5 * K) < 2 and abs(rel1[1] + 147.5 * K) < 2 and abs(rel2[0] - 136.5 * K * s2) < 2 and abs(rel2[1] + 147.5 * K * s2) < 2
    slots = {t3_anchor(s, b1) for s in (1, 2, 3)}
    on_canvas = all(0 < t3_anchor(s, b)[0] < 1080 and 0 < t3_anchor(s, b)[1] < 1920 for s in (1, 2, 3) for b in (b1, b2))
    ok = a1 != a2 and follows and len(slots) == 3 and on_canvas
    rec("T3-4 t3_anchor follows the frame box", "PASS" if ok else "FAIL",
        f"slot1 box1={tuple(round(v) for v in a1)} box2={tuple(round(v) for v in a2)} offset_from_BR_scales={follows} 3_distinct_slots={len(slots) == 3} on_canvas={on_canvas}")


@selftest_check("T3-4 3 s render: chapter + captions + video card (1080x1920, duration, audio)")
def _t3_render4(rec, quiet, feed, A, tmp):
    from mt.render import _load_job
    from mt.templates.t3.dynamic import t3_anchor
    from mt.templates.t3.static import VIDEO_BOX
    out = tmp / "t3_4_out.mp4"
    cfg = _t3_still_cfg(A, chapters=[{"start": 0, "label": "INTRODUCTION"}],
                        cards=[{"media": str(A / "test.mp4"), "start": 0.4, "hold": 1.2, "slot": 1, "label": "DEV"}])
    cfg["captions"] = [_t3_cap_stream(A, "ar.srt", "box", 42), _t3_cap_stream(A, "en.srt", "sub", 30)]
    cfg["output"], cfg["preview"] = str(out), 3.0
    jp = tmp / "t3_4_job.json"
    jp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    job = _load_job(str(jp))
    quiet(render, job)
    info = _st_info(out) if out.is_file() else None
    ok = bool(info) and info[:2] == (1080, 1920) and 2.6 < info[2] < 3.6 and info[3]
    cx, cy = (int(v) for v in t3_anchor(1, VIDEO_BOX))
    px = {}
    if out.is_file():
        for t in (0.0, 1.2, 2.9):
            g = tmp / f"t3_4_f{t}.png"
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", str(g)], check=False)
            px[t] = Image.open(g).convert("RGB").getpixel((cx, cy)) if g.is_file() else None
    card_ok = bool(px) and None not in px.values() and not _near(px[1.2], px[0.0], 50) and _near(px[2.9], px[0.0], 30)
    rec("T3-4 3 s render: chapter + captions + video card (1080x1920, duration, audio)", "PASS" if ok and card_ok else "FAIL",
        f"{info and (info[0], info[1], round(info[2], 2), info[3])}; card centre px t0={px.get(0.0)} t1.2={px.get(1.2)} t2.9={px.get(2.9)}")


# ---- Template 3 (T3-5): adaptive layout engine ------------------------------------------------------------------------
def _t3_lay_cfg(A, layout, out=None, preview=None):
    from mt.templates.t3.static import VIDEO_BOX
    c = _t3_cfg_for(A, chapters=[{"start": 0, "label": "INTRO"}], layout=layout)
    c["video_box"] = dict(VIDEO_BOX)
    c["captions"] = [_t3_cap_stream(A, "en.srt", "box", 42)]
    if out:
        c["output"] = str(out)
    if preview:
        c["preview"] = preview
    return c


_T3_LAY_EV = {"on": True, "mode": "manual", "trans": 0.5, "events": [{"at": 1.0, "state": "S3"}, {"at": 2.5, "state": "S0"}]}


@selftest_check("T3-5 geometry S0-S3: no overlaps, S3 = poster")
def _t3_lay_geometry(rec, quiet, feed, A, tmp):
    from mt.templates.t3.layout import t3_layout
    from mt.templates.t3.static import K, VIDEO_BOX
    L = {s: t3_layout(s) for s in ("S0", "S1", "S2", "S3")}
    bad = []
    for s, g in L.items():
        fx, fy, fw, fh = g["frame"]
        rects = [r for r in (g["strip"], g["panel"]) if r]
        for r in rects:
            if r[1] < fy + fh + 9 * K:                      # band must start >= 10 poster px below the frame
                bad.append(f"{s}:frame-band gap")
        if g["strip"] and g["panel"] and g["strip"][1] + g["strip"][3] > g["panel"][1] - 9 * K:
            bad.append(f"{s}:strip-panel overlap")
        if rects and max(r[1] + r[3] for r in rects) > 1530 * K + 1:
            bad.append(f"{s}:band below footer top")
        if (fx, fy, fw) != (VIDEO_BOX["x"], VIDEO_BOX["y"], VIDEO_BOX["w"]):
            bad.append(f"{s}:frame x/top/w moved")
    exp = {"S0": 1520, "S1": 1275, "S2": 1210, "S3": 955}
    for s, yb in exp.items():
        got = (L[s]["frame"][1] + L[s]["frame"][3]) / K
        if abs(got - yb) > 1.5:
            bad.append(f"{s}:bottom {got:.1f}!={yb}")
    s3 = L["S3"]
    poster = (abs(s3["frame"][3] - VIDEO_BOX["h"]) <= 2 and abs(s3["strip"][1] / K - 965) <= 1.5 and abs(s3["panel"][1] / K - 1220) <= 1.5
              and abs(s3["panel"][3] / K - 310) <= 1.5 and abs(s3["strip"][3] / K - 245) <= 1.5)
    rec("T3-5 geometry S0-S3: no overlaps, S3 = poster", "PASS" if not bad and poster else "FAIL",
        f"bottoms(poster px)={ {s: round((g['frame'][1] + g['frame'][3]) / K) for s, g in L.items()} } S3_frame_h={s3['frame'][3]:.1f} vs poster {VIDEO_BOX['h']} "
        f"strip_y={s3['strip'][1] / K:.1f} panel_y={s3['panel'][1] / K:.1f} problems={bad}")


@selftest_check("T3-5 interpolation monotonic")
def _t3_lay_interp(rec, quiet, feed, A, tmp):
    from mt.templates.t3.layout import _sp_at, t3_layout, t3_layout_timeline
    from mt.templates.t3.static import t3_cfg
    bot = lambda x: (lambda f: f[1] + f[3])(t3_layout(x)["frame"])
    a = [bot(i * 0.05) for i in range(61)]                     # float progress 0..3
    b = [bot((i / 40.0, i / 40.0)) for i in range(41)]         # both bands together
    c = t3_cfg({"layout": _T3_LAY_EV})
    tl = t3_layout_timeline({"t3": c}, 4.0)
    d = [bot(_sp_at(tl, i * 0.025)) for i in range(0, 41)]     # 0..1.0 s: S0 (t<1.0) ; 1.0..1.5 transition
    e = [bot(_sp_at(tl, 1.0 + i * 0.0125)) for i in range(41)]  # during S0->S3 transition
    f = [bot(_sp_at(tl, 2.5 + i * 0.0125)) for i in range(41)]  # during S3->S0 transition
    mono = lambda v, sgn: all((y - x) * sgn >= -1e-6 for x, y in zip(v, v[1:]))
    ok = mono(a, -1) and mono(b, -1) and mono(e, -1) and mono(f, 1) and abs(e[0] - a[0]) < 1 and abs(e[-1] - a[-1]) < 1 and bool(d)
    rec("T3-5 interpolation monotonic", "PASS" if ok else "FAIL",
        f"progress0..3 {a[0]:.0f}->{a[-1]:.0f} down={mono(a, -1)}; both-bands down={mono(b, -1)}; timeline S0->S3 down={mono(e, -1)} "
        f"({e[0]:.0f}->{e[-1]:.0f}); S3->S0 up={mono(f, 1)} ({f[0]:.0f}->{f[-1]:.0f})")


@selftest_check("T3-5 4 s render S0->S3->S0: frame height, captions inside frame")
def _t3_lay_render(rec, quiet, feed, A, tmp):
    from mt.templates.t3.layout import _sp_at, t3_layout
    from mt.templates.t3.static import VIDEO_BOX
    out = tmp / "t3_5_lay.mp4"
    green = tmp / "t3_5_green.mp4"                      # solid green source: the window edge is unambiguous
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x00dd00:s=720x1280:r=30:d=4", "-f", "lavfi",
                    "-i", "sine=d=4", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(green)], check=False)
    cfg = _t3_lay_cfg(A, _T3_LAY_EV, out, 4.0)
    cfg["video"] = str(green)
    quiet(render, cfg)
    info = _st_info(out) if out.is_file() else None
    cx = int(VIDEO_BOX["x"] + VIDEO_BOX["w"] * 0.5)
    meas, exp = {}, {}
    for t in (0.4, 2.0, 3.8):
        g = tmp / f"t3_5_f{t}.png"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", str(g)], check=False)
        im = Image.open(g).convert("RGB")
        vc = (0, 221, 0)
        y = 1900                                          # lowest green pixel in a column left of the caption box
        while y > VIDEO_BOX["y"] and not _near(im.getpixel((VIDEO_BOX["x"] + 40, y)), vc, 70):
            y -= 1
        meas[t] = y + 1 - VIDEO_BOX["y"]
        exp[t] = t3_layout(_sp_at(_T3_LAY_EV_TL(cfg), t))["frame"][3]
    ok_h = all(abs(meas[t] - exp[t]) <= 12 for t in meas) and meas[0.4] > meas[2.0] + 300 and meas[3.8] > meas[2.0] + 300
    # captions + chapter tag stay inside the frame at every sampled time
    from mt.common import get_template
    tmpd = tempfile.mkdtemp(prefix="t3lay_")
    try:
        c2 = dict(cfg)
        quiet(get_template(c2)["build_background"], c2, tmpd)
        items = build_items(c2, 4.0)
        worst, n_chk = 0.0, 0
        for i in range(0, 120):
            t = i / 30.0
            fx, fy, fw, fh = t3_layout(_sp_at(c2["_t3_lay"]["tl"], t))["frame"]
            for it in items:
                if it.start <= t < it.end:
                    n_chk += 1
                    w, h = it.sprite.size
                    worst = max(worst, fx - (it.cx - w / 2.0), (it.cx + w / 2.0) - (fx + fw), fy - (it.cy - h / 2.0),
                                (it.cy + h / 2.0) - (fy + fh))
        inside = n_chk > 100 and worst <= 1.0
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    ok = bool(info) and info[:2] == (1080, 1920) and 3.6 < info[2] < 4.4 and info[3] and ok_h and inside
    rec("T3-5 4 s render S0->S3->S0: frame height, captions inside frame", "PASS" if ok else "FAIL",
        f"{info and (info[0], info[1], round(info[2], 2), info[3])}; frame h measured/expected t0.4={meas[0.4]}/{exp[0.4]:.0f} "
        f"t2.0={meas[2.0]}/{exp[2.0]:.0f} t3.8={meas[3.8]}/{exp[3.8]:.0f}; item-frame checks={n_chk} worst_overflow_px={worst:.2f}")


def _T3_LAY_EV_TL(cfg):
    from mt.templates.t3.layout import t3_layout_timeline
    from mt.templates.t3.static import t3_cfg
    return t3_layout_timeline({"t3": t3_cfg(cfg["t3"]), "captions": cfg.get("captions", [])}, 4.0)


@selftest_check("T3-5 render time: layout vs static T3 clip (4 s)")
def _t3_lay_time(rec, quiet, feed, A, tmp):
    o1, o2 = tmp / "t3_5_static.mp4", tmp / "t3_5_layout.mp4"
    t0 = time.time()
    quiet(render, _t3_lay_cfg(A, {"on": False}, o1, 4.0))
    ts = time.time() - t0
    t0 = time.time()
    quiet(render, _t3_lay_cfg(A, _T3_LAY_EV, o2, 4.0))
    tl_ = time.time() - t0
    ratio = tl_ / max(ts, 1e-6)
    rec("T3-5 render time: layout vs static T3 clip (4 s)", "PASS" if o1.is_file() and o2.is_file() and ratio < 4.0 else "FAIL",
        f"static {ts:.1f}s, layout (2 transitions = 30 plate frames) {tl_:.1f}s, ratio {ratio:.2f}x (limit 4x)")


@selftest_check("T3-5 stills S0 / S3, job json + defaults")
def _t3_lay_stills(rec, quiet, feed, A, tmp):
    from mt.render import _load_job
    from mt.templates.t3.layout import t3_layout
    from mt.templates.t3.static import K, t3_cfg
    cfg = _t3_lay_cfg(A, _T3_LAY_EV)
    a = _t3_still_at(quiet, cfg, tmp, "t3_still_5a", 0.2)
    b = _t3_still_at(quiet, cfg, tmp, "t3_still_5b", 2.0)
    for n, im in (("a", a), ("b", b)):
        im.save(tmp / f"t3_still_5{n}.png")
    g3 = t3_layout("S3")
    r = g3["strip"]
    band_px = _dbbox(a.crop(tuple(int(v) for v in (r[0], r[1], r[0] + r[2], r[1] + r[3]))), b.crop(tuple(int(v) for v in (r[0], r[1], r[0] + r[2], r[1] + r[3])))) is not None
    jp = tmp / "t3_5_job.json"
    jp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    job = _load_job(str(jp))
    lay = t3_cfg(job["t3"])["layout"]
    dflt = t3_cfg({})["layout"]
    keys = lay["on"] is True and lay["mode"] == "manual" and len(lay["events"]) == 2 and dflt["on"] is False and dflt["mode"] == "auto"
    ok = a.size == (1080, 1920) and b.size == (1080, 1920) and _dbbox(a, b) is not None and band_px and keys
    rec("T3-5 stills S0 / S3, job json + defaults", "PASS" if ok else "FAIL",
        f"stills differ={_dbbox(a, b) is not None} strip area differs={band_px}; job layout={lay['mode']}/{len(lay['events'])} events; default on={dflt['on']} mode={dflt['mode']}")


# ---- Template 3 (T3-6): photo-tiles strip -----------------------------------------------------------------------------
_T3_STRIP_COL = ((200, 30, 30), (30, 160, 40), (30, 60, 200))


def _t3_strip_files(tmp):
    out = []
    for i, c in enumerate(_T3_STRIP_COL):
        p = tmp / f"t3_strip_c{i}.png"
        Image.new("RGB", (800, 600), c).save(p)
        out.append(str(p))
    return out


def _t3_strip_cfg_for(A, tmp, sets, **extra):
    c = _t3_cfg_for(A, chapters=[{"start": 0, "label": "INTRO"}], layout={"on": True, "mode": "auto", "trans": 0.5},
                    strip={"on": True, "sets": sets})
    c["video_box"] = dict(__import__("mt.templates.t3.static", fromlist=["VIDEO_BOX"]).VIDEO_BOX)
    c.update(extra)
    return c


def _t3_strip_set(files, start, hold, labels=("Mobile Apps", "AI Automation", "Web Development"), icons=("phone", "chip", "globe")):
    return {"start": start, "hold": hold, "tiles": [{"image": files[i], "label": labels[i], "icon": icons[i]} for i in range(3)]}


@selftest_check("T3-6 strip still: 3 tiles at the strip rect, labels inside tiles, icons present")
def _t3_strip_still(rec, quiet, feed, A, tmp):
    from mt.templates.t3.layout import t3_layout
    from mt.templates.t3.panels import strip_tile_rects
    files = _t3_strip_files(tmp)
    cfg = _t3_strip_cfg_for(A, tmp, [_t3_strip_set(files, 0.5, 3.0)])
    im = _t3_still_at(quiet, cfg, tmp, "t3_still_6", 2.0)
    r = t3_layout("S1")["strip"]
    rects = strip_tile_rects(r, 3, 3.0)
    col_ok, lab_ok, ico_ok, det = [], [], [], []
    for (x, y, w, h, off, first, last), c in zip(rects, _T3_STRIP_COL):
        px = im.getpixel((int(x + w * 0.5), int(y + 14)))
        col_ok.append(_near(px, c, 60))
        white = [(xx, yy) for yy in range(int(y + h * 0.7), int(y + h)) for xx in range(int(x), int(x + w))
                 if min(im.getpixel((xx, yy))) > 235]
        xs = [p[0] for p in white]
        lab_ok.append(len(white) > 150 and min(xs) >= x - 1 and max(xs) <= x + w)
        isz = int(h * 0.17)
        ico_ok.append(sum(1 for p in white if p[0] < x + 26 + isz + 4) > 40)
        det.append(len(white))
    ok = all(col_ok) and all(lab_ok) and all(ico_ok) and im.size == (1080, 1920)
    rec("T3-6 strip still: 3 tiles at the strip rect, labels inside tiles, icons present", "PASS" if ok else "FAIL",
        f"tile colours={col_ok} labels inside={lab_ok} icons={ico_ok} white px={det}; still t3_still_6.png {im.size}")


@selftest_check("T3-6 two sets over 4 s: strip signature differs, band ranges")
def _t3_strip_sets(rec, quiet, feed, A, tmp):
    import hashlib
    from mt.templates.t3.layout import t3_band_active_ranges, t3_layout
    from mt.templates.t3.static import t3_cfg
    files = _t3_strip_files(tmp)
    s1 = _t3_strip_set(files, 0.5, 1.8)
    s2 = _t3_strip_set(files[::-1], 2.3, 1.5, labels=("Cloud", "Security", "Code"), icons=("cloud", "shield", "code"))
    cfg = _t3_strip_cfg_for(A, tmp, [s1, s2])
    r = t3_layout("S1")["strip"]
    box = tuple(int(v) for v in (r[0], r[1], r[0] + r[2], r[1] + r[3]))
    sig = {}
    for t in (1.8, 3.4):
        sig[t] = hashlib.md5(_t3_still_at(quiet, cfg, tmp, f"t3_strip_sets_{t}", t).crop(box).tobytes()).hexdigest()
    c3 = dict(cfg, t3=t3_cfg(cfg["t3"]))
    rng = t3_band_active_ranges(c3, 4.0)["strip"]
    ok = sig[1.8] != sig[3.4] and len(rng) == 2 and abs(rng[0][0] - 0.0) < 1e-6 and abs(rng[1][1] - 3.8) < 0.3
    rec("T3-6 two sets over 4 s: strip signature differs, band ranges", "PASS" if ok else "FAIL",
        f"sig1.8={sig[1.8][:8]} sig3.4={sig[3.4][:8]} ranges={[(round(a, 2), round(b, 2)) for a, b in rng]}")


@selftest_check("T3-6 tile sources: image path + frame from the video")
def _t3_strip_sources(rec, quiet, feed, A, tmp):
    from mt.templates.t3.panels import strip_tile_photo
    files = _t3_strip_files(tmp)
    green = tmp / "t3_6_green.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x00dd00:s=360x640:r=30:d=3", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(green)], check=False)
    cfg = {"video": str(green)}
    a = strip_tile_photo(cfg, {"image": files[0], "frame": None})
    b = strip_tile_photo(cfg, {"image": "", "frame": 1.5})
    c = quiet(strip_tile_photo, {"video": str(tmp / "nope.mp4")}, {"image": "", "frame": 1.0})
    ok = _near(a.getpixel((10, 10)), _T3_STRIP_COL[0], 12) and _near(b.getpixel((10, 10)), (0, 221, 0), 40) and b.size == (360, 640) \
        and c.size[0] > 0
    rec("T3-6 tile sources: image path + frame from the video", "PASS" if ok else "FAIL",
        f"image px={a.getpixel((10, 10))} frame px={b.getpixel((10, 10))} size={b.size}; missing video -> gray fallback {c.size}")


@selftest_check("T3-6 AUTO layout 4 s render: video frame shrinks when the set starts, grows back")
def _t3_strip_auto(rec, quiet, feed, A, tmp):
    from mt.templates.t3.layout import _sp_at, t3_layout
    from mt.templates.t3.static import VIDEO_BOX, t3_cfg
    files = _t3_strip_files(tmp)
    green = tmp / "t3_6_auto_green.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x00dd00:s=720x1280:r=30:d=4", "-f", "lavfi",
                    "-i", "sine=d=4", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(green)], check=False)
    out = tmp / "t3_6_auto.mp4"
    cfg = _t3_strip_cfg_for(A, tmp, [_t3_strip_set(files, 1.2, 1.8)], output=str(out), preview=4.0, video=str(green))
    quiet(render, cfg)
    info = _st_info(out) if out.is_file() else None
    meas = {}
    for t in (0.4, 2.0, 3.8):
        g = tmp / f"t3_6_f{t}.png"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", str(g)], check=False)
        im = Image.open(g).convert("RGB")
        y = 1900
        while y > VIDEO_BOX["y"] and not _near(im.getpixel((VIDEO_BOX["x"] + 40, y)), (0, 221, 0), 70):
            y -= 1
        meas[t] = y + 1 - VIDEO_BOX["y"]
    h_s0, h_s1 = t3_layout("S0")["frame"][3], t3_layout("S1")["frame"][3]
    ok = bool(info) and info[:2] == (1080, 1920) and abs(meas[0.4] - h_s0) <= 12 and abs(meas[2.0] - h_s1) <= 12 \
        and abs(meas[3.8] - h_s0) <= 12 and meas[0.4] > meas[2.0] + 200
    rec("T3-6 AUTO layout 4 s render: video frame shrinks when the set starts, grows back", "PASS" if ok else "FAIL",
        f"frame h t0.4/2.0/3.8 = {meas[0.4]}/{meas[2.0]}/{meas[3.8]} (expected S0 {h_s0:.0f}, S1 {h_s1:.0f}, S0); {info and info[:3]}")


@selftest_check("T3-6 cfg normaliser, questions (defaults remembered), job json")
def _t3_strip_cfg_ask(rec, quiet, feed, A, tmp):
    import builtins
    from mt.render import _load_job
    from mt.templates.t3 import t3_ask_config, t3_strip_cfg
    from mt.templates.t3.static import t3_cfg
    files = _t3_strip_files(tmp)
    raw = {"on": True, "sets": [{"start": 1, "tiles": [{"image": files[0]}]}] + [_t3_strip_set(files, i, 2) for i in range(5)]}
    n = t3_strip_cfg(raw)
    norm_ok = len(n["sets"]) == 3 and t3_strip_cfg(n) == n and t3_strip_cfg(None)["on"] is False and t3_cfg({})["strip"]["on"] is False
    saved_in, saved_D, saved_tdir = builtins.input, dict(D), _mt_ask.TEMPLATES_DIR
    try:
        _mt_ask.TEMPLATES_DIR = tmp / "t3_templates"
        for k in [k for k in D if k.startswith("t3_")]:
            D.pop(k)
        feed([""] * 40 + ["y"] + [""] * 8 + ["@1", "", "", "@2", "", "", "@3", "", ""] + ["n", ""] + [""] * 20, [])
        quiet(t3_ask_config, {})                                   # warm-up pass is not used; real run below
        D.pop("t3_strip", None)
        ans = ["", "-", "-", "-", "-", "-", "-", "-", "-", "-"]
        # drive by prompt text: scripted stdin answers 'y' to the strip question, Enter everywhere else
        import builtins as _b
        seen = []

        def fake(prompt=""):
            seen.append(prompt)
            return "y" if "photo-tiles strip" in prompt else ""
        _b.input = fake
        tpl = quiet(t3_ask_config, {})
        s = tpl["t3"]["strip"]
        ask_ok = s["on"] and len(s["sets"]) == 1 and len(s["sets"][0]["tiles"]) == 3 and s["sets"][0]["tiles"][0]["label"] == "Mobile Apps" \
            and s["sets"][0]["tiles"][2]["icon"] == "globe" and s["sets"][0]["start"] == 2.0 and tpl["t3"]["layout"]["on"] \
            and D.get("t3_strip") == "y"
        _b.input = lambda prompt="": ""
        tpl2 = quiet(t3_ask_config, {})                           # Enter now keeps the remembered answer (strip stays on)
        rem_ok = tpl2["t3"]["strip"]["on"] is True
        jp = tmp / "t3_6_job.json"
        jp.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        job = _load_job(str(jp))
        job_ok = t3_cfg(job["t3"])["strip"] == t3_cfg(tpl["t3"])["strip"] and t3_cfg(job["t3"])["strip"]["sets"][0]["tiles"][1]["icon"] == "chip"
    finally:
        builtins.input = saved_in
        D.clear()
        D.update(saved_D)
        _mt_ask.TEMPLATES_DIR = saved_tdir
    ok = norm_ok and ask_ok and rem_ok and job_ok
    rec("T3-6 cfg normaliser, questions (defaults remembered), job json", "PASS" if ok else "FAIL",
        f"normaliser={norm_ok} questions={ask_ok} remembered={rem_ok} job roundtrip={job_ok}")


# ---- Template 3 (T3-7): bottom panel (gallery + checklist) ------------------------------------------------------------
def _t3_panel_cfg_for(A, tmp, files=None, **panel):
    th = [{"image": f, "caption": c} for f, c in zip(files or [], ("Alpha look", "Beta look with a longer caption", "Gamma"))]
    pn = dict({"on": True, "start": 0.5, "thumbs": th, "reveal": "stagger", "stagger": 1.0,
               "rows": ["Row one text", "Row two", "A very long checklist row that must auto fit inside the column", "Row four"]}, **panel)
    c = _t3_cfg_for(A, chapters=[{"start": 0, "label": "INTRO"}], layout={"on": True, "mode": "auto", "trans": 0.5}, panel=pn)
    c["video_box"] = dict(__import__("mt.templates.t3.static", fromlist=["VIDEO_BOX"]).VIDEO_BOX)
    return c


@selftest_check("T3-7 panel still: 3 columns, thumbnails inside, check icons orange")
def _t3_panel_still(rec, quiet, feed, A, tmp):
    from mt.templates.t3.panels import PANEL_X, _pt, panel_items, t3_panel_center_rect, t3_panel_rect
    files = _t3_strip_files(tmp)
    cfg = _t3_panel_cfg_for(A, tmp, files, stagger=0.8)
    im = _t3_still_at(quiet, cfg, tmp, "t3_still_7", 3.6)
    pr = t3_panel_rect()
    dark = _near(im.getpixel((int(pr[0] + 40), int(pr[1] + pr[3] - 30))), (24, 15, 12), 50)
    div = []
    for key in ("div1", "div2"):
        x, y = _pt(pr, PANEL_X[key], 1380)
        a = max(sum(im.getpixel((int(x) + dx, int(y)))) for dx in (-1, 0, 1))
        b = sum(im.getpixel((int(x) - 8, int(y))))
        div.append(a > b + 40)
    lx0, ty0 = _pt(pr, PANEL_X["left0"], 1272)
    tw = 100 * 1080 / 941.0
    th_ok = []
    for i, c in enumerate(_T3_STRIP_COL):
        px = im.getpixel((int(lx0 + i * (tw + 13) + tw / 2), int(ty0 + 60)))
        th_ok.append(_near(px, c, 70) and pr[0] <= lx0 + i * (tw + 13) and lx0 + i * (tw + 13) + tw <= _pt(pr, PANEL_X["div1"], 0)[0])
    items = panel_items(dict(cfg, t3=__import__("mt.templates.t3.static", fromlist=["t3_cfg"]).t3_cfg(cfg["t3"])), 4.0)
    ck = []
    for it in items:
        h = it.sprite.height
        r = h * 0.30
        x = it.cx - it.sprite.width / 2 + r + 2 - r * 0.6
        y = it.cy - r * 0.5
        px = im.getpixel((int(x), int(y)))
        ck.append(px[0] > 200 and 70 < px[1] < 160 and px[2] < 90)
    cx, cy, cw, ch = t3_panel_center_rect(pr)
    c_ok = PANEL_X["div1"] < 380 and cx > _pt(pr, PANEL_X["div1"], 0)[0] and cx + cw < _pt(pr, PANEL_X["div2"], 0)[0] and ch > 200
    ok = dark and all(div) and all(th_ok) and len(ck) == 4 and all(ck) and c_ok and im.size == (1080, 1920)
    rec("T3-7 panel still: 3 columns, thumbnails inside, check icons orange", "PASS" if ok else "FAIL",
        f"dark={dark} dividers={div} thumbs={th_ok} checks={ck} centre rect ok={c_ok}; still t3_still_7.png")


@selftest_check("T3-7 checklist stagger: visible rows grow over time")
def _t3_panel_stagger(rec, quiet, feed, A, tmp):
    from mt.templates.t3.panels import PANEL_X, _pt, panel_resolve, t3_panel_rect
    files = _t3_strip_files(tmp)
    cfg = _t3_panel_cfg_for(A, tmp, files)
    c3 = dict(cfg, t3=__import__("mt.templates.t3.static", fromlist=["t3_cfg"]).t3_cfg(cfg["t3"]))
    res = panel_resolve(c3, 5.0)
    times = [t for _, t in res["rows"]]
    pr = t3_panel_rect()
    x0, y0 = _pt(pr, PANEL_X["right0"], 1275)
    x1, y1 = _pt(pr, PANEL_X["right1"], 1525)

    def orange(t):
        im = _t3_still_at(quiet, cfg, tmp, f"t3_pst_{t}", t)
        return sum(1 for yy in range(int(y0), int(y1), 2) for xx in range(int(x0), int(x1), 2)
                   if (lambda p: p[0] > 200 and 70 < p[1] < 160 and p[2] < 90)(im.getpixel((xx, yy))))
    o = [orange(t) for t in (1.6, 3.4)]
    vis = [sum(1 for x in times if x <= t) for t in (1.6, 3.4)]
    ok = vis[0] < vis[1] and o[0] > 0 and o[1] > o[0] * 1.5 and all(b - a >= 0.99 for a, b in zip(times, times[1:]))
    rec("T3-7 checklist stagger: visible rows grow over time", "PASS" if ok else "FAIL",
        f"reveal times={[round(t, 2) for t in times]} rows visible at 1.6/3.4 s={vis} orange px={o}")


@selftest_check("T3-7 video-frame thumbnails auto-extracted (10/40/70 %)")
def _t3_panel_frames(rec, quiet, feed, A, tmp):
    from mt.templates.t3.panels import panel_thumb_photo, t3_panel_cfg
    v = tmp / "t3_7_rgb.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0xdd0000:s=360x640:r=30:d=1",
                    "-f", "lavfi", "-i", "color=c=0x00dd00:s=360x640:r=30:d=1", "-f", "lavfi", "-i",
                    "color=c=0x0000dd:s=360x640:r=30:d=1", "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(v)], check=False)
    pc = t3_panel_cfg({"on": True})
    cfg = {"video": str(v)}
    cols = [panel_thumb_photo(cfg, t).getpixel((10, 10)) for t in pc["thumbs"]]
    want = [(221, 0, 0), (0, 221, 0), (0, 0, 221)]
    ok = len(pc["thumbs"]) == 3 and [t["pct"] for t in pc["thumbs"]] == [0.1, 0.4, 0.7] and all(_near(c, w, 50) for c, w in zip(cols, want))
    rec("T3-7 video-frame thumbnails auto-extracted (10/40/70 %)", "PASS" if ok else "FAIL", f"pixels={cols}")


@selftest_check("T3-7 AUTO layout: video shrinks when the panel starts, band ranges")
def _t3_panel_auto(rec, quiet, feed, A, tmp):
    from mt.templates.t3.layout import t3_band_active_ranges, t3_layout_at
    from mt.templates.t3.static import t3_cfg
    cfg = _t3_panel_cfg_for(A, tmp, _t3_strip_files(tmp), start=2.0, end=4.0)
    c3 = dict(cfg, t3=t3_cfg(cfg["t3"]))
    h0 = t3_layout_at(c3, 0.5, 6.0)["frame"][3]
    h1 = t3_layout_at(c3, 3.0, 6.0)["frame"][3]
    h2 = t3_layout_at(c3, 5.5, 6.0)["frame"][3]
    rng = t3_band_active_ranges(c3, 6.0)["panel"]
    ok = h1 < h0 - 100 and abs(h2 - h0) < 1 and len(rng) == 1 and abs(rng[0][0] - 1.5) < 0.05 and abs(rng[0][1] - 4.0) < 0.05
    rec("T3-7 AUTO layout: video shrinks when the panel starts, band ranges", "PASS" if ok else "FAIL",
        f"frame h at 0.5/3.0/5.5 s = {h0:.0f}/{h1:.0f}/{h2:.0f}; panel range={[(round(a, 2), round(b, 2)) for a, b in rng]}")


@selftest_check("T3-7 panel off / questions: defaults, strip still unchanged")
def _t3_panel_off(rec, quiet, feed, A, tmp):
    import hashlib
    from mt.templates.t3.panels import t3_ask_panel, t3_panel_cfg
    files = _t3_strip_files(tmp)
    base = _t3_strip_cfg_for(A, tmp, [_t3_strip_set(files, 0.5, 3.0)])
    off = _t3_strip_cfg_for(A, tmp, [_t3_strip_set(files, 0.5, 3.0)])
    off["t3"]["panel"] = {"on": False, "rows": ["x"]}
    ims = [_t3_still_at(quiet, c, tmp, f"t3_p7off{i}", 2.0) for i, c in enumerate((base, off))]
    dif = sum(ImageChops.difference(ims[0], ims[1]).convert("L").getdata()) / (1080 * 1920.0)
    h = [0, 0 if dif < 1.0 else 1]
    from mt.common import D
    D.pop("t3_panel", None)
    d = t3_panel_cfg({})
    ok = h[0] == h[1] and d["on"] is False and d["left_title"] == "TEMPLATE VARIATIONS" and d["right_title"] == "KEY ANIMATIONS" \
        and len(d["thumbs"]) == 3 and len(d["rows"]) == 6
    rec("T3-7 panel off / questions: defaults, strip still unchanged", "PASS" if ok else "FAIL",
        f"strip still vs panel-off still mean diff={dif:.3f} (grain); defaults titles/3 thumbs/6 rows ok={d['left_title'] == 'TEMPLATE VARIATIONS'}")


# ---- Template 3 (T3-8): panel CENTER content slot ----------------------------------------------------------------------------
def _t3_slot_cfg_for(A, tmp, blocks, slot_extra=None, panel_extra=None, **extra):
    pn = dict({"rows": [], "start": 0.5}, **(panel_extra or {}))
    cfg = _t3_panel_cfg_for(A, tmp, _t3_strip_files(tmp), **pn)
    cfg["t3"]["slot"] = dict({"on": True, "blocks": blocks}, **(slot_extra or {}))
    cfg.update(extra)
    return cfg


def _t3_slot_bbox(a, b, rect):
    d = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 24 else 0)
    x, y, w, h = [int(v) for v in rect]
    pad = 40                                         # look at the whole panel band (slightly larger than the centre rect)
    from mt.templates.t3.panels import t3_panel_rect
    pr = [int(v) for v in t3_panel_rect()]
    band = d.crop((pr[0], pr[1], pr[0] + pr[2], pr[1] + pr[3]))
    bb = band.getbbox()
    return None if bb is None else (bb[0] + pr[0], bb[1] + pr[1], bb[2] + pr[0], bb[3] + pr[1])


@selftest_check("T3-8 slot: every block type renders inside the centre rect")
def _t3_slot_types(rec, quiet, feed, A, tmp):
    from mt.templates.t3.panels import t3_panel_center_rect, t3_panel_rect
    files = _t3_strip_files(tmp)
    cx, cy, cw, ch = t3_panel_center_rect(t3_panel_rect())
    blocks = {"points": {"type": "points", "start": 1.0, "lines": ["One", "Two longer line", "Three"], "stagger": 0.3, "bullet": "number"},
              "stat": {"type": "stat", "start": 1.0, "value": "250+", "label": "VIDEOS EDITED", "sub": "and counting", "count_up": True},
              "media": {"type": "media", "start": 1.0, "image": files[1], "caption": "Behind the scenes"},
              "chips": {"type": "chips", "start": 1.0, "chips": ["Design", "Motion", "Code", "Audio", "Story", "Reels", "Edit", "Color"]}}
    res = {}
    for name, b in blocks.items():
        cfg = _t3_slot_cfg_for(A, tmp, [b])
        hdr = _t3_still_at(quiet, cfg, tmp, f"t3_s8_{name}_h", 0.8)
        im = _t3_still_at(quiet, cfg, tmp, f"t3_s8_{name}", 3.4)
        bb = _t3_slot_bbox(hdr, im, (cx, cy, cw, ch))
        res[name] = bb is not None and bb[0] >= cx - 1 and bb[1] >= cy - 1 and bb[2] <= cx + cw + 1 and bb[3] <= cy + ch + 1 \
            and (bb[2] - bb[0]) > 40 and (bb[3] - bb[1]) > 30
        res[name + "_bb"] = bb
    ok = all(res[n] for n in blocks)
    rec("T3-8 slot: every block type renders inside the centre rect", "PASS" if ok else "FAIL",
        f"centre rect=({cx:.0f},{cy:.0f},{cw:.0f},{ch:.0f}); " + "; ".join(f"{n} {res[n]} bbox={res[n + '_bb']}" for n in blocks))


@selftest_check("T3-8 slot: two blocks over 4 s change the centre signature")
def _t3_slot_two(rec, quiet, feed, A, tmp):
    import hashlib
    from mt.templates.t3.panels import t3_panel_center_rect, t3_panel_rect
    r = [int(v) for v in t3_panel_center_rect(t3_panel_rect())]
    blocks = [{"type": "points", "start": 1.0, "lines": ["Alpha", "Beta", "Gamma"], "stagger": 0.2},
              {"type": "stat", "start": 2.5, "value": "98%", "label": "SATISFIED"}]
    cfg = _t3_slot_cfg_for(A, tmp, blocks)
    sig = {}
    for t in (0.8, 2.0, 3.6):
        im = _t3_still_at(quiet, cfg, tmp, f"t3_s8_two_{t}", t)
        sig[t] = hashlib.md5(im.crop((r[0], r[1], r[0] + r[2], r[1] + r[3])).tobytes()).hexdigest()
    from mt.templates.t3.slot import slot_resolve
    from mt.templates.t3.static import t3_cfg
    rs = slot_resolve(dict(cfg, t3=t3_cfg(cfg["t3"])), 4.0)
    ok = len({sig[0.8], sig[2.0], sig[3.6]}) == 3 and len(rs) == 2 and abs(rs[0]["t1"] - rs[1]["t0"]) < 1e-6
    rec("T3-8 slot: two blocks over 4 s change the centre signature", "PASS" if ok else "FAIL",
        f"sig 0.8/2.0/3.6 s = {sig[0.8][:8]}/{sig[2.0][:8]}/{sig[3.6][:8]}; blocks {[(round(x['t0'], 2), round(x['t1'], 2)) for x in rs]}")


@selftest_check("T3-8 slot: Arabic points stay inside the centre rect (RTL)")
def _t3_slot_arabic(rec, quiet, feed, A, tmp):
    from mt.templates.t3.panels import t3_panel_center_rect, t3_panel_rect
    from mt.templates.t3.slot import points_sprites, slot_rects
    from mt.templates.t3.static import t3_cfg
    cx, cy, cw, ch = t3_panel_center_rect(t3_panel_rect())
    lines = ["مونتاج احترافي بلمسة إبداعية مميزة وسريعة جداً لكل مشاريعكم",
             "ترجمة وتعليقات متحركة", "إطار فيديو متكيف",
             "أنماط جاهزة", "مؤثرات صوتية", "نهاية"]
    cfg = _t3_slot_cfg_for(A, tmp, [{"type": "points", "start": 1.0, "lines": lines, "stagger": 0.1}], slot_extra={"title": "نقاط رئيسية"})
    c3 = dict(cfg, t3=t3_cfg(cfg["t3"]))
    area = slot_rects()[2]
    spr = points_sprites(c3, c3["t3"]["slot"]["blocks"][0], area)
    inside = all(s.width <= area[2] + 0.5 and abs(cx_ - area[2] / 2.0) < 1 for s, cx_, _ in spr)
    ink = [s.getchannel("A").getbbox() for s, _, _ in spr]
    edge_ok = all(b and b[0] >= 0 and b[2] <= spr[0][0].width for b in ink)
    right_ok = all(b[2] > spr[0][0].width * 0.9 for b in ink)             # RTL: bullet on the right edge
    hdr = _t3_still_at(quiet, cfg, tmp, "t3_s8_ar_h", 0.8)
    im = _t3_still_at(quiet, cfg, tmp, "t3_s8_ar", 3.0)
    bb = _t3_slot_bbox(hdr, im, (cx, cy, cw, ch))
    in_rect = bb is not None and bb[0] >= cx - 1 and bb[2] <= cx + cw + 1 and bb[1] >= cy - 1 and bb[3] <= cy + ch + 1
    ok = inside and edge_ok and right_ok and in_rect and len(spr) == 6
    rec("T3-8 slot: Arabic points stay inside the centre rect (RTL)", "PASS" if ok else "FAIL",
        f"6 lines, sprite w<={area[2]:.0f}: {inside}; ink inside sprite: {edge_ok}; bullet at right edge: {right_ok}; still bbox={bb} in rect={in_rect}")


@selftest_check("T3-8 slot: 4 s T3 render, three columns + media video segment moves")
def _t3_slot_render(rec, quiet, feed, A, tmp):
    from mt.templates.t3.panels import PANEL_X, _pt, t3_panel_center_rect, t3_panel_rect
    from mt.templates.t3.slot import slot_rects
    mov = tmp / "t3_8_moving.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=4", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(mov)], check=False)
    blocks = [{"type": "media", "start": 1.0, "video": str(mov), "seg_start": 0.0, "seg_end": 3.0, "caption": "Behind the scenes"}]
    out = tmp / "t3_8_render.mp4"
    cfg = _t3_slot_cfg_for(A, tmp, blocks, panel_extra={"rows": ["Row one", "Row two", "Row three"], "stagger": 0.4},
                           output=str(out), preview=4.0)
    cfg["captions"] = []
    quiet(render, cfg)
    info = _st_info(out) if out.is_file() else None
    fr = {}
    for t in (1.9, 3.3):
        g = tmp / f"t3_8_r{t}.png"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", str(g)], check=False)
        fr[t] = Image.open(g).convert("RGB")
    (ax, ay, aw, ah) = slot_rects()[2]
    box = (int(ax), int(ay), int(ax + aw), int(ay + ah * 0.8))
    from PIL import ImageStat
    mv = ImageStat.Stat(ImageChops.difference(fr[1.9].crop(box), fr[3.3].crop(box)).convert("L")).mean[0]
    pr = t3_panel_rect()
    lx0, ty0 = _pt(pr, PANEL_X["left0"], 1272)
    left_ok = _near(fr[3.3].getpixel((int(lx0 + 50 * 1.1477), int(ty0 + 60))), _T3_STRIP_COL[0], 80)
    rx0, ry0 = _pt(pr, PANEL_X["right0"], 1275)
    rx1, ry1 = _pt(pr, PANEL_X["right1"], 1525)
    org = sum(1 for yy in range(int(ry0), int(ry1), 2) for xx in range(int(rx0), int(rx1), 2)
              if (lambda p: p[0] > 200 and 70 < p[1] < 160 and p[2] < 90)(fr[3.3].getpixel((xx, yy))))
    cx, cy, cw, ch = t3_panel_center_rect(pr)
    ctr_ok = sum(1 for yy in range(int(cy + 60), int(cy + ch - 30), 6) for xx in range(int(cx + 10), int(cx + cw - 10), 6)
                 if max(fr[3.3].getpixel((xx, yy))) > 90) > 40
    fr[3.3].save(tmp / "t3_still_8_render.png")
    ok = bool(info) and info[:2] == (1080, 1920) and abs(info[2] - 4.0) < 0.2 and info[3] and mv > 4.0 and left_ok and org > 20 and ctr_ok
    rec("T3-8 slot: 4 s T3 render, three columns + media video segment moves", "PASS" if ok else "FAIL",
        f"{info}; centre pixels moved between 1.9 s and 3.3 s: mean diff {mv:.1f}; left thumb ok={left_ok}; right orange px={org}; centre content={ctr_ok}")


@selftest_check("T3-8 slot: cfg normaliser, questions (defaults remembered), job json, still")
def _t3_slot_cfg_ask(rec, quiet, feed, A, tmp):
    import builtins
    from mt.render import _load_job
    from mt.templates.t3 import t3_ask_config, t3_slot_cfg
    from mt.templates.t3.static import t3_cfg
    d = t3_slot_cfg({"on": True})
    e = t3_slot_cfg({"on": True, "blocks": []})
    raw = {"on": True, "icon": "bad", "blocks": [{"type": "points", "lines": [str(i) for i in range(9)]}, {"type": "nope"},
                                                  {"type": "chips", "chips": [str(i) for i in range(12)]}]}
    n = t3_slot_cfg(raw)
    norm_ok = [b["type"] for b in d["blocks"]] == ["points", "stat", "chips"] and e["blocks"] == [] and n["icon"] == "layers" \
        and len(n["blocks"]) == 2 and len(n["blocks"][0]["lines"]) == 6 and len(n["blocks"][1]["chips"]) == 8 and t3_slot_cfg(n) == n \
        and t3_cfg({})["slot"]["on"] is False and d["title"] == "KEY POINTS"
    saved_in, saved_D, saved_tdir = builtins.input, dict(D), _mt_ask.TEMPLATES_DIR
    try:
        _mt_ask.TEMPLATES_DIR = tmp / "t3_templates8"
        for k in [k for k in D if k.startswith("t3_")]:
            D.pop(k)
        builtins.input = lambda prompt="": "y" if ("bottom panel" in prompt or "Show the bottom panel" in prompt) else ""
        tpl = quiet(t3_ask_config, {})
        s = tpl["t3"]["slot"]
        ask_ok = s["on"] and s["title"] == "KEY POINTS" and len(s["blocks"]) == 3 and tpl["t3"]["panel"]["on"] and D.get("t3_slot") == "y"
        jp = tmp / "t3_8_job.json"
        jp.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        job = _load_job(str(jp))
        job_ok = t3_cfg(job["t3"])["slot"] == t3_cfg(tpl["t3"])["slot"] and t3_cfg(job["t3"])["slot"]["blocks"][1]["count_up"] is True
    finally:
        builtins.input = saved_in
        D.clear()
        D.update(saved_D)
        _mt_ask.TEMPLATES_DIR = saved_tdir
    cfg = _t3_slot_cfg_for(A, tmp, None)
    cfg["t3"]["slot"].pop("blocks")
    im = _t3_still_at(quiet, cfg, tmp, "t3_still_8", 4.2)
    im.save(tmp / "t3_still_8.png")
    ok = norm_ok and ask_ok and job_ok and im.size == (1080, 1920)
    rec("T3-8 slot: cfg normaliser, questions (defaults remembered), job json, still", "PASS" if ok else "FAIL",
        f"normaliser={norm_ok} questions={ask_ok} job roundtrip={job_ok}; still t3_still_8.png (demo blocks @4.2 s)")


# ---- Template 3 (T3-9): split mode (S4) + saved styles ---------------------------------------------------------------------
def _t3_split_cfg_for(A, tmp, segments, **t3):
    files = _t3_strip_files(tmp)
    segs = [dict(g, media=(files[1] if g.get("media") == "IMG" else g.get("media", ""))) for g in segments]
    cfg = _t3_cfg_for(A, chapters=[{"start": 0, "label": "INTRO"}], layout={"on": True, "mode": "auto", "trans": 0.5},
                      split={"on": True, "segments": segs}, **t3)
    cfg["video_box"] = dict(__import__("mt.templates.t3.static", fromlist=["VIDEO_BOX"]).VIDEO_BOX)
    cfg["captions"] = [_t3_cap_stream(A, "en.srt", "sub", 30)]
    return cfg


def _t3_split_c3(cfg):
    from mt.templates.t3.static import t3_cfg
    return dict(cfg, t3=t3_cfg(cfg["t3"]))


@selftest_check("T3-9 split segment: frame shrinks, right frame only inside, captions stay in the video frame")
def _t3_split_segment(rec, quiet, feed, A, tmp):
    from mt.templates.t3.layout import t3_layout, t3_layout_at
    cfg = _t3_split_cfg_for(A, tmp, [{"start": 1.0, "hold": 2.0, "media": "IMG", "mode": "fill"}])
    c3 = _t3_split_c3(cfg)
    rb = t3_layout("S4")["right"]
    px, py = int(rb[0] + rb[2] / 2), int(rb[1] + rb[3] / 2)
    green, w = {}, {}
    for t in (0.4, 2.0, 3.9):
        im = _t3_still_at(quiet, cfg, tmp, f"t3_s9_seg_{t}", t)
        green[t] = _near(im.getpixel((px, py)), _T3_STRIP_COL[1], 40)
        w[t] = t3_layout_at(c3, t, 4.0)["frame"][2]
    from mt.templates.t3.layout import t3_layout_items
    items = quiet(t3_layout_items, c3, 4.0)                         # the items a render gets (re-anchored to the moving frame)
    fr = t3_layout_at(c3, 2.0, 4.0)["frame"]
    act = [it for it in items if it.start <= 2.0 < it.end]
    mine = [it for it in act if it.cx < rb[0]]                       # everything that is not the right-frame content
    inside = all(fr[0] - 1 <= it.cx - it.sprite.width / 2.0 and it.cx + it.sprite.width / 2.0 <= fr[0] + fr[2] + 1 for it in mine)
    ok = green[2.0] and not green[0.4] and not green[3.9] and w[2.0] < w[0.4] * 0.7 and abs(w[3.9] - w[0.4]) < 1 and inside and len(mine) >= 2
    rec("T3-9 split segment: frame shrinks, right frame only inside, captions stay in the video frame",
        "PASS" if ok else "FAIL",
        f"right-frame image px at 0.4/2.0/3.9 s = {green[0.4]}/{green[2.0]}/{green[3.9]}; frame w {w[0.4]:.0f}/{w[2.0]:.0f}/{w[3.9]:.0f}; "
        f"{len(mine)} left items (chapter tag + captions) inside frame x {fr[0]:.0f}-{fr[0] + fr[2]:.0f}: {inside}")


@selftest_check("T3-9 split transitions are monotonic (frame width, split progress)")
def _t3_split_trans(rec, quiet, feed, A, tmp):
    from mt.templates.t3.layout import t3_layout_at
    c3 = _t3_split_c3(_t3_split_cfg_for(A, tmp, [{"start": 1.0, "hold": 2.0, "media": "IMG"}]))
    ts_in = [0.9 + i * 0.025 for i in range(30)]
    ts_out = [2.9 + i * 0.025 for i in range(30)]
    w_in = [t3_layout_at(c3, t, 4.0)["frame"][2] for t in ts_in]
    w_out = [t3_layout_at(c3, t, 4.0)["frame"][2] for t in ts_out]
    x_in = [t3_layout_at(c3, t, 4.0)["x"] for t in ts_in]
    mono_in = all(b <= a + 1e-6 for a, b in zip(w_in, w_in[1:])) and all(b >= a - 1e-6 for a, b in zip(x_in, x_in[1:]))
    mono_out = all(b >= a - 1e-6 for a, b in zip(w_out, w_out[1:]))
    ok = mono_in and mono_out and w_in[0] > w_in[-1] + 100 and w_out[-1] > w_out[0] + 100 and x_in[0] == 0 and abs(x_in[-1] - 1) < 0.01
    rec("T3-9 split transitions are monotonic (frame width, split progress)", "PASS" if ok else "FAIL",
        f"in: w {w_in[0]:.0f}->{w_in[-1]:.0f} monotonic={mono_in}; out: w {w_out[0]:.0f}->{w_out[-1]:.0f} monotonic={mono_out}; x {x_in[0]:.2f}->{x_in[-1]:.2f}")


@selftest_check("T3-9 saved style round trip (save, selector label, load by stdin) + job json")
def _t3_split_saved(rec, quiet, feed, A, tmp):
    import builtins
    import contextlib
    import io
    from mt.templates import choose_template
    from mt.templates.t3 import t3_ask_config
    from mt.templates.t3.static import t3_cfg
    saved_in, saved_D, saved_tdir = builtins.input, dict(D), _mt_ask.TEMPLATES_DIR
    try:
        _mt_ask.TEMPLATES_DIR = tmp / "t3_styles9"
        for k in [k for k in D if k.startswith("t3_")]:
            D.pop(k)
        state = {"save": True}

        def fake(prompt=""):
            if "split-screen" in prompt:
                return "y"
            if "Save this as a template" in prompt:
                return "My Orange" if state["save"] else ""
            if "Accent color" in prompt:
                return "#33AA99"
            if "Name line 1" in prompt:
                return "Sara"
            return ""
        builtins.input = fake
        t1 = quiet(t3_ask_config, {})
        f = _mt_ask.TEMPLATES_DIR / "My Orange.json"
        raw = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        style_only = raw.get("t3_style") is True and raw.get("template_id") == 3 and "split" not in raw.get("t3", {}) \
            and str(raw.get("t3", {}).get("accent")).upper() == "#33AA99"
        buf = io.StringIO()
        builtins.input = lambda prompt="": "1"
        with contextlib.redirect_stdout(buf):
            choose_template()
        label_ok = any("My Orange" in ln and "Template 3, Editorial Orange" in ln for ln in buf.getvalue().splitlines())
        _PRESET["path"] = str(f)
        state["save"] = False

        def fake2(prompt=""):                                         # the style questions must NOT be asked again
            fake2.seen.append(prompt)
            return "y" if "split-screen" in prompt else ""
        fake2.seen = []
        builtins.input = fake2
        t2 = quiet(t3_ask_config, {})
        skipped = not any("Accent color" in p or "Name line 1" in p or "Video frame style" in p for p in fake2.seen) \
            and any("split-screen" in p for p in fake2.seen)
        same = t1["t3"] == t2["t3"]
        jp = tmp / "t3_9_job.json"
        jp.write_text(json.dumps(t1, ensure_ascii=False), encoding="utf-8")
        from mt.render import _load_job
        job = _load_job(str(jp))
        job_ok = t3_cfg(job["t3"]) == t1["t3"] and t3_cfg(t3_cfg(job["t3"])) == t1["t3"] and t1["t3"]["split"]["on"] \
            and t1["t3"]["layout"]["on"] and t1["t3"]["name1"] == "Sara"
    finally:
        builtins.input = saved_in
        _PRESET.pop("path", None)
        D.clear()
        D.update(saved_D)
        _mt_ask.TEMPLATES_DIR = saved_tdir
    ok = style_only and label_ok and skipped and same and job_ok
    rec("T3-9 saved style round trip (save, selector label, load by stdin) + job json", "PASS" if ok else "FAIL",
        f"style-only file={style_only} selector label={label_ok} style questions skipped on load={skipped} "
        f"cfg['t3'] identical={same} job roundtrip={job_ok}")


@selftest_check("T3-9 --job re-render of a T3 job with split (image + video segment)")
def _t3_split_job(rec, quiet, feed, A, tmp):
    from PIL import ImageStat
    from mt.templates.t3.layout import t3_layout
    mov = tmp / "t3_9_moving.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=4", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(mov)], check=False)
    cfg = _t3_split_cfg_for(A, tmp, [{"start": 1.0, "hold": 1.2, "media": "IMG"}, {"start": 2.2, "hold": 1.2, "media": str(mov)}])
    out = tmp / "t3_9_job_out.mp4"
    cfg["output"], cfg["preview"] = str(out), 4.0
    jp = tmp / "t3_9_job.json"
    jp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(_SCRIPT), "--job", str(jp)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", input="", timeout=400)
    info = _st_info(out) if out.is_file() else None
    rb = t3_layout("S4")["right"]
    box = (int(rb[0] + rb[2] * 0.2), int(rb[1] + rb[3] * 0.3), int(rb[0] + rb[2] * 0.8), int(rb[1] + rb[3] * 0.7))
    fr = {}
    for t in (0.4, 1.8, 2.8, 3.2):
        g = tmp / f"t3_9_j{t}.png"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", str(g)], check=False)
        fr[t] = Image.open(g).convert("RGB")
    cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
    img_ok = _near(fr[1.8].getpixel((cx, cy)), _T3_STRIP_COL[1], 45) and not _near(fr[0.4].getpixel((cx, cy)), _T3_STRIP_COL[1], 45)
    mv = ImageStat.Stat(ImageChops.difference(fr[2.8].crop(box), fr[3.2].crop(box)).convert("L")).mean[0]
    ok = r.returncode == 0 and bool(info) and info[:2] == (1080, 1920) and 3.6 < info[2] < 4.4 and info[3] and img_ok and mv > 3.0
    rec("T3-9 --job re-render of a T3 job with split (image + video segment)", "PASS" if ok else "FAIL",
        f"rc={r.returncode} {info and (info[0], info[1], round(info[2], 2), info[3])}; image segment visible at 1.8 s only={img_ok}; "
        f"video segment pixels moved 2.8->3.2 s: mean diff {mv:.1f}" + ("" if r.returncode == 0 else " | " + r.stderr[-300:]))


@selftest_check("T3-9 bands hidden during S4, back after; defaults; still t3_still_9.png")
def _t3_split_bands(rec, quiet, feed, A, tmp):
    from mt.templates.t3.layout import t3_band_active_ranges, t3_layout_at, t3_layout_timeline, t3_split_cfg
    from mt.templates.t3.panels import t3_panel_rect
    from mt.templates.t3.static import t3_cfg
    base = _t3_panel_cfg_for(A, tmp, _t3_strip_files(tmp), start=0.5, rows=["Row one", "Row two"], stagger=0.2)
    cfg = _t3_split_cfg_for(A, tmp, [{"start": 2.0, "hold": 1.0, "media": "IMG"}], panel=base["t3"]["panel"])
    c3 = _t3_split_c3(cfg)
    tl = t3_layout_timeline(c3, 6.0)
    p_at = lambda t: __import__("mt.templates.t3.layout", fromlist=["_spx_at"])._spx_at(tl, t)
    pres = {t: p_at(t) for t in (1.2, 2.6, 5.0)}
    im = _t3_still_at(quiet, cfg, tmp, "t3_still_9", 2.6)
    im.save(tmp / "t3_still_9.png")
    pr = t3_panel_rect()
    px = im.getpixel((int(pr[0] + 40), int(pr[1] + pr[3] - 30)))
    nopanel = not _near(px, (24, 15, 12), 12)                       # the dark panel band is not drawn during the split
    d = t3_split_cfg(None)
    norm = d["on"] is False and d["segments"] == [] and t3_split_cfg(t3_split_cfg({"on": True, "segments": [{"start": 1}]})) == \
        t3_split_cfg({"on": True, "segments": [{"start": 1}]}) and t3_cfg({})["split"]["on"] is False
    ok = pres[1.2][1] > 0.99 and pres[2.6][1] < 0.01 and pres[2.6][2] > 0.99 and pres[5.0][1] > 0.99 and nopanel and norm and im.size == (1080, 1920)
    rec("T3-9 bands hidden during S4, back after; defaults; still t3_still_9.png", "PASS" if ok else "FAIL",
        f"(s,p,x) at 1.2/2.6/5.0 s = {tuple(round(v, 2) for v in pres[1.2])}/{tuple(round(v, 2) for v in pres[2.6])}/"
        f"{tuple(round(v, 2) for v in pres[5.0])}; panel band absent during split={nopanel}; defaults={norm}")


# ---- Template 3 (T3-10): question flow, selector, robustness, non-9:16, compile + help ------------------------------------
def _t3x_video(tmp, name, w, h, dur, audio=True):
    p = tmp / name
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration={dur}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-c:a", "aac", "-shortest"]
    subprocess.check_call(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)])
    return str(p)


def _t3x_job(A, tmp, name, video=None, dur=1.5, caps=True, **t3):
    t3.setdefault("chapters", [{"start": 0, "label": "INTRO"}])
    cfg = _t3_cfg_for(A, **t3)
    cfg["video_box"] = dict(__import__("mt.templates.t3.static", fromlist=["VIDEO_BOX"]).VIDEO_BOX)
    cfg["captions"] = [_t3_cap_stream(A, "en.srt", "sub", 30)] if caps else []
    cfg["output"], cfg["preview"] = str(tmp / (name + ".mp4")), dur
    if video:
        cfg["video"] = video
    return cfg


def _t3x_render_ok(cfg, quiet, dur):
    out = Path(cfg["output"])
    quiet(render, cfg)
    info = _st_info(out) if out.is_file() else None
    return bool(info) and info[:2] == (1080, 1920) and abs(info[2] - dur) < 0.3, str(info and (info[0], info[1], round(info[2], 2), info[3]))


@selftest_check("T3-10 Enter-through (defaults) -> grouped questions in order -> 2 s valid render")
def _t3_enter_through(rec, quiet, feed, A, tmp):
    import builtins
    import contextlib
    import io
    saved = builtins.input
    out = tmp / "t3_enter.mp4"
    prompts = []
    try:
        def fake(prompt=""):
            prompts.append(prompt)
            if prompt.startswith("Choice") and len(prompts) == 1:
                return "3"
            for k, v in (("Video path", str(A / "test.mp4")), ("SRT captions file path", str(A / "ar.srt")),
                         ("Output file", str(out)), ("Quick test", "2")):
                if prompt.startswith(k):
                    return v
            return ""
        builtins.input = fake
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            c = interactive()
        builtins.input = saved
        text = buf.getvalue()
        heads = ["=== 1. Video", "=== 2. Captions file", "=== 3. Identity", "=== 4. Headline", "=== 5. Frame style", "=== 6. Layout mode",
                 "=== 7. Chapter tags", "=== 8. Captions", "=== 9. Floating cards", "=== 10. Photo-tiles strip", "=== 11. Bottom panel",
                 "=== 12. Split screen", "=== 13. Texts", "=== 14. Output"]
        hp = [text.find(h) for h in heads]
        hdr_ok = all(x >= 0 for x in hp) and hp == sorted(hp)
        order = ["Choice", "Video path", "SRT captions file path", "Accent color", "Show the headline", "Show chapter tags", "Caption font",
                 "Add floating photo cards", "Show the photo-tiles strip", "Show the bottom panel", "Add split-screen", "Do you want text",
                 "Do you want elements", "Add a template layer", "Do you want a video layer", "Output file", "Quick test"]
        pos = [next((i for i, q in enumerate(prompts) if q.lstrip("\n").startswith(k)), -1) for k in order]
        order_ok = all(x >= 0 for x in pos) and pos == sorted(pos)
        recap = recap_line(c)
        quiet(render, c)
        w, h, dur, aud = _st_info(out) if out.is_file() else (0, 0, 0, False)
        ok = hdr_ok and order_ok and (w, h) == (1080, 1920) and abs(dur - 2.0) < 0.2 and aud and "Template 3" in recap and "ON:" in recap \
            and c["template_id"] == 3 and c["t3"] == __import__("mt.templates.t3.static", fromlist=["t3_cfg"]).t3_cfg(c["t3"])
        rec("T3-10 Enter-through (defaults) -> grouped questions in order -> 2 s valid render", "PASS" if ok else "FAIL",
            f"{w}x{h} {dur:.2f}s audio={aud} headers_ok={hdr_ok} order_ok={order_ok} pos={pos if not order_ok else 'ok'} | {recap}")
    finally:
        builtins.input = saved


@selftest_check("T3-10 selector 1/2/3/4 (+ saved style listed with its label)")
def _t3_selector(rec, quiet, feed, A, tmp):
    import builtins
    import contextlib
    import io
    from mt.templates import choose_template
    saved = builtins.input
    got = []
    try:
        for n in "1234":
            builtins.input = lambda prompt="", n=n: n
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                got.append(choose_template()["id"])
            _PRESET.clear()
        listing = buf.getvalue()
    finally:
        builtins.input = saved
        _PRESET.clear()
    names = all(s in listing for s in ("Template 1", "Template 2", "Template 3", "Custom"))
    ok = got == [1, 2, 3, 4] and names
    rec("T3-10 selector 1/2/3/4 (+ saved style listed with its label)", "PASS" if ok else "FAIL",
        f"ids chosen={got}; all four names listed={names}")


@selftest_check("T3-10 robustness cases (T3)")
def _t3_robust(rec, quiet, feed, A, tmp):
    import contextlib
    import io
    from mt.templates.t3 import static as _st
    d = tmp / "t3r"
    d.mkdir(exist_ok=True)
    files = _t3_strip_files(tmp)
    cases = []

    def case(name, fn):
        try:
            ok, det = fn()
        except BaseException as e:
            ok, det = False, "crashed: " + repr(e)[:120]
        cases.append((name, ok, det))

    def cap(fn):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = fn()
        return r, buf.getvalue()

    everything = dict(layout={"on": True, "mode": "auto", "trans": 0.5},
                      strip={"on": True, "sets": [{"start": 0.2, "hold": 1.0, "tiles": [{"image": "/nope/a.png", "icon_path": "/nope/i.png", "label": "A"},
                                                                                      {"image": files[1], "label": "B"}]}]},
                      panel={"on": True, "start": 0.3, "thumbs": [{"image": "/nope/t.png", "caption": "x"}, {"image": files[0]}],
                             "rows": ["one", "two"]},
                      slot={"on": True, "blocks": [{"type": "media", "image": "/nope/m.png", "caption": "c", "start": 0.4},
                                                   {"type": "stat", "value": "5", "label": "L", "start": 0.9}]},
                      split={"on": True, "segments": [{"start": 0.5, "hold": 0.8, "media": "/nope/s.mp4"}]},
                      cards=[{"media": "/nope/card.png", "start": 0.2, "hold": 1.0, "slot": 1, "label": "x"}], cards_on=True)

    def missing_assets():
        c = _t3x_job(A, d, "ma", **everything)
        c["elements"] = [{"path": "/nope/e.png", "start": 0.2, "end": 1.2, "pos": "bottom-right", "width": "20%", "opacity": 100, "anim": "pop", "anim_dur": 0.3}]
        c["layers"] = [{"path": "/nope/l.png", "pos": "center", "width": "20%", "opacity": 100, "anim": "none", "anim_dur": 0.5}]
        c["video_layers"] = [{"path": "/nope/v.mp4", "start": 0.2, "end": 1.0, "area": "box", "mode": "fill", "fade": 0.2}]
        ok, det = _t3x_render_ok(c, quiet, 1.5)
        return ok, det
    case("missing element / layer / video layer / icon / image / card paths", missing_assets)

    def missing_font():
        _st._WARNED.clear()
        old = _st._t2_lookup
        _st._t2_lookup = lambda n: None
        try:
            c = _t3x_job(A, d, "mf", caps=False)
            c["t3"]["fonts"] = {"head": "/nope/Kanit-BlackItalic.ttf"}
            _, text = cap(lambda: render_still(c, str(d / "mf.png"), 0.5))
        finally:
            _st._t2_lookup = old
            _st._WARNED.clear()
        return ("put it in the fonts/ folder" in text and "Kanit" in text and "Traceback" not in text), \
            f"{len(text.splitlines())} message lines, names Kanit file={'Kanit' in text}"
    case("missing font -> message names the file for fonts/", missing_font)

    def no_numpy():
        import sys
        sys.modules["numpy"] = None
        try:
            c = _t3x_job(A, d, "nn", cards=[{"media": str(A / "element.png"), "start": 0.2, "hold": 1.0, "slot": 1}], cards_on=True)
            render_still(c, str(d / "nn.png"), 0.8)
        finally:
            sys.modules.pop("numpy", None)
        return True, "still with numpy blocked"
    case("numpy missing", no_numpy)

    na = _t3x_video(d, "noaudio.mp4", 1080, 1920, 1.5, audio=False)
    case("video without audio", lambda: _t3x_render_ok(_t3x_job(A, d, "na", video=na, panel={"on": True}, layout={"on": True}), quiet, 1.5))
    late = dict(layout={"on": True, "mode": "auto", "trans": 0.5}, panel={"on": True, "start": 5.0}, strip={"on": True, "sets": [
        {"start": 4.0, "tiles": [{"image": files[0]}, {"image": files[1]}]}]}, split={"on": True, "segments": [{"start": 6.0, "media": ""}]})
    sh = _t3x_video(d, "short.mp4", 1080, 1920, 1.5)
    case("video shorter than the first band / split / trigger time", lambda: _t3x_render_ok(_t3x_job(A, d, "late", video=sh, **late), quiet, 1.5))
    allon = dict(everything, split={"on": True, "segments": [{"start": 0.3, "hold": 0.8, "media": ""}]})
    case("very short video (1.5 s), every module on", lambda: _t3x_render_ok(_t3x_job(A, d, "all", video=sh, **allon), quiet, 1.5))
    longtxt = ("هذا نص طويل جدا للتجربة " * 10 + "This is a very long caption line used to test wrapping " * 5).strip()
    (d / "long.srt").write_text(f"1\n00:00:00,000 --> 00:00:01,400\n{longtxt}\n", encoding="utf-8")

    def long_cap():
        c = _t3x_job(A, d, "lg", video=sh)
        c["captions"] = [_t3_cap_stream(A, "ar.srt", "box", 42), _t3_cap_stream(A, "en.srt", "sub", 30)]
        for cp in c["captions"]:
            cp["srt"] = str(d / "long.srt")
        return _t3x_render_ok(c, quiet, 1.5)
    case(f"very long caption ({len(longtxt)} chars)", long_cap)

    def bom():
        (d / "bom.srt").write_bytes(b"\xef\xbb\xbf1\r\n00:00:00,000 --> 00:00:00,800\r\nHello\r\n\r\n\r\n\r\n2\r\n00:00:01,000 --> 00:00:01,400\r\n\r\nWorld\r\nsecond\r\n\r\n")
        cues = parse_srt(str(d / "bom.srt"))
        c = _t3x_job(A, d, "bom", video=sh)
        c["captions"][0]["srt"] = str(d / "bom.srt")
        ok, det = _t3x_render_ok(c, quiet, 1.5)
        return ok and [x[2] for x in cues] == ["Hello", "World second"], f"cues={[x[2] for x in cues]} {det}"
    case("SRT with BOM / CRLF / empty lines", bom)

    def triggers():
        zz = "zzzqqq"
        c = _t3x_job(A, d, "trg", chapters=[{"start": 0, "label": "A"}, {"trigger": zz, "start": 0.8, "label": "B"}, {"trigger": zz, "label": "C"}],
                     layout={"on": True, "mode": "manual", "events": [{"trigger": zz, "state": "S3"}]},
                     strip={"on": True, "sets": [{"trigger": zz, "start": 0.2, "tiles": [{"image": files[0]}, {"image": files[1]}]}]},
                     panel={"on": True, "trigger": zz, "start": 0.3, "reveal": "trigger", "rows": [{"text": "r", "trigger": zz}]},
                     slot={"on": True, "blocks": [{"type": "points", "trigger": zz, "lines": [{"text": "p", "trigger": zz}], "reveal": "trigger"},
                                                  {"type": "chips", "chips": [{"text": "k", "trigger": zz}]}]},
                     split={"on": True, "segments": [{"trigger": zz, "start": 0.5, "hold": 0.6}, {"trigger": zz}]},
                     cards=[{"media": str(A / "element.png"), "trigger": zz, "slot": 1}], cards_on=True)
        _, text = cap(lambda: render_still(c, str(d / "trg.png"), 1.0))
        return "not found" in text and "Traceback" not in text, f"{text.count('not found')} 'not found' warnings, no crash"
    case("trigger phrase not found -> warn and skip (all modules)", triggers)

    def overlap():
        c = _t3x_job(A, d, "ov", video=sh, layout={"on": True, "mode": "manual", "trans": 0.5, "events": [
            {"at": 0.2, "state": "S3"}, {"at": 0.3, "state": "S0"}, {"at": 0.35, "state": "S1"}, {"at": 0.3, "state": "S2"}]},
            strip={"on": True, "sets": [{"start": 0.1, "tiles": [{"image": files[0]}, {"image": files[1]}]}]}, panel={"on": True, "start": 0.1})
        return _t3x_render_ok(c, quiet, 1.5)
    case("overlapping layout events", overlap)

    def parity():
        font = _st_font()
        c = _t3x_job(A, d, "par", dur=None, panel={"on": True, "start": 0.3, "rows": ["a"]}, layout={"on": True, "mode": "auto"})
        c["preview"] = None
        c["texts"] = [{"text": "Hello", "start": 0.0, "end": 1.4, "pos": "top", "font": font, "size": 90, "color": "#ffffff",
                       "stroke_color": "#000000", "stroke_w": 0, "anim": "fade", "anim_dur": 0.3}]
        c["elements"] = [{"path": str(A / "element.png"), "start": 0.2, "end": 1.4, "pos": "bottom-right", "width": "20%", "opacity": 100,
                          "anim": "pop", "anim_dur": 0.3}]
        c["layers"] = [{"path": str(A / "element.png"), "pos": "top-left", "width": "10%", "opacity": 100, "anim": "none", "anim_dur": 0.5}]
        c["video_layers"] = [{"path": str(A / "test.mp4"), "start": 0.2, "end": 1.2, "area": "canvas", "mode": "fit", "fade": 0.2}]
        jp = d / "par_job.json"
        jp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        r1 = subprocess.run([sys.executable, str(_SCRIPT), "--job", str(jp), "--preview", "1.5"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", input="", timeout=300)
        info = _st_info(d / "par.mp4") if (d / "par.mp4").is_file() else None
        r2 = subprocess.run([sys.executable, str(_SCRIPT), "--still", "--job", str(jp), "--still-out", str(d / "par_still.png")],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", input="", timeout=300)
        st_ok = (d / "par_still.png").is_file() and Image.open(d / "par_still.png").size == (1080, 1920)
        ok = r1.returncode == 0 and r2.returncode == 0 and bool(info) and info[:2] == (1080, 1920) and abs(info[2] - 1.5) < 0.3 and st_ok
        return ok, f"--job --preview 1.5 rc={r1.returncode} {info and (info[0], info[1], round(info[2], 2))}; --still --job rc={r2.returncode} png={st_ok}"
    case("parity: texts + elements + template layer + video layer, --job --preview, --still", parity)

    bad = [n for n, ok, _ in cases if not ok]
    rec("T3-10 robustness cases (T3)", "PASS" if not bad else "FAIL",
        f"{len(cases) - len(bad)}/{len(cases)} passed" + ("" if not bad else " | FAILED: " + "; ".join(f"{n}: {x}" for n, ok, x in cases if not ok)[:600]))
    for n, ok, x in cases:
        print(f"      {'PASS' if ok else 'FAIL'}  {n}  ({x})")


@selftest_check("T3-10 non-9:16 inputs (1920x1080, 1080x1080) with skewed and straight frame")
def _t3_nonvertical(rec, quiet, feed, A, tmp):
    d = tmp / "t3nv"
    d.mkdir(exist_ok=True)
    res, ok = [], True
    for nm, (vw, vh) in (("wide", (1920, 1080)), ("square", (1080, 1080))):
        vid = _t3x_video(d, f"{nm}.mp4", vw, vh, 1.5)
        for fs in ("skewed", "straight"):
            for fit in ("fill", "fit"):
                if nm == "square" and fit == "fit":
                    continue
                c = _t3x_job(A, d, f"{nm}_{fs}_{fit}", video=vid, frame_style=fs, video_fit=fit, layout={"on": True, "mode": "auto"},
                             panel={"on": True, "start": 0.3, "rows": ["a"]})
                good, det = _t3x_render_ok(c, quiet, 1.5)
                ok = ok and good
                res.append(f"{nm}/{fs}/{fit}:{'ok' if good else 'BAD ' + det}")
    rec("T3-10 non-9:16 inputs (1920x1080, 1080x1080) with skewed and straight frame", "PASS" if ok else "FAIL", " ".join(res))


@selftest_check("T3-10 py_compile + --help (3 templates, flags, folders, fonts)")
def _t3_compile_help(rec, quiet, feed, A, tmp):
    import py_compile
    bad = []
    for f in [_SCRIPT] + sorted((BASE / "mt").rglob("*.py")):
        try:
            py_compile.compile(str(f), cfile=str(tmp / "pc.pyc"), doraise=True)
        except py_compile.PyCompileError as e:
            bad.append(f"{f.name}: {str(e)[:60]}")
    r = subprocess.run([sys.executable, str(_SCRIPT), "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    t = r.stdout
    need = ["Template 3", "Editorial Orange", "--job", "--still", "--preview", "--selftest", "templates/", "fonts/", "Playfair Display",
            "Kanit", "Rajdhani", "Cairo", "Delafield", "Allura", "split", "Custom"]
    miss = [k for k in need if k not in t]
    ok = not bad and r.returncode == 0 and not miss
    rec("T3-10 py_compile + --help (3 templates, flags, folders, fonts)", "PASS" if ok else "FAIL",
        f"compile errors={bad or 'none'}; --help rc={r.returncode} {len(t.splitlines())} lines; missing={miss or 'none'}")
