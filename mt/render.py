"""mt.render - moved from montage.py by tools/mt_move.py"""
from mt.common import get_template
from mt.draw import Item, _img_ok, draw_item, load_image_sprite, make_text_sprite, resolve_pos
from mt.fonts import _font_ok, _font_or_fallback, default_font, is_rtl_text
from mt.common import FFMPEG, _WARNED, _hex0x, _require_ffmpeg, _vid_ok, _warn, probe
from mt.captions import caption_streams, make_rich_sprite, parse_srt, stream_groups, t2_caption_items
from mt.split import SPLIT_T, compute_splits, split_at, split_boxes
from mt.anim import anim_state
import os
from pathlib import Path
import json
from PIL import Image
import subprocess
import tempfile
import shutil
import math
import time


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
    if get_template(cfg)["id"] == 3:                  # Template 3: font overrides that are not files -> one message, automatic choice
        fonts = (cfg.get("t3") or {}).get("fonts") or {}
        for role in list(fonts):
            if not _font_ok(fonts[role]):
                _warn(f"Template 3 font override '{Path(str(fonts[role])).name}' not found - put it in the fonts/ folder "
                      f"(using the automatic choice)")
                fonts.pop(role)
    return cfg


def _load_job(path):
    try:
        job = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if (isinstance(job, dict) and job.get("template_id") == 3 and "t3" not in job
                and (job.get("background") or {}).get("type") != "t3"):
            job["template_id"] = 4      # jobs saved before S4 used id 3 for Custom; real Template 3 jobs carry cfg["t3"]
        return job
    except FileNotFoundError:
        raise ValueError(f"job file not found: {path}")
    except ValueError as e:
        raise ValueError(f"job file '{Path(path).name}' is not valid JSON ({e})")


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
        if get_template(cfg)["id"] == 3:                  # T3: style "card" (default) sits inside the real frame
            from mt.templates.t3.layout import t3_element_items      # (lazy: render.py never imports templates at top level)
            t3_items = t3_element_items(cfg, e, duration)            # None for style "plain" -> old path below
            if t3_items is not None:
                items += t3_items
                continue
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

    if get_template(cfg)["id"] == 3 and cfg.get("_t2_still") and cfg.get("video_layers"):      # T3 still: side video layers as first-frame cards
        from mt.templates.t3.layout import t3_side_video_items
        items += t3_side_video_items(cfg, duration)

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
        if c.get("t3_style") in ("box", "sub") or c.get("t4_style") == "pill":      # T3 / T4 captions come from their build_items hook
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


def build_ffmpeg_cmd(cfg, info, duration, out_path, preview, overlay_path):
    W, H = cfg["canvas"]
    box = cfg["video_box"]
    fps = info["fps"]
    fps_s = f"{fps.numerator}/{fps.denominator}" if fps.denominator != 1 else str(fps.numerator)
    bg = cfg["background"]
    T = SPLIT_T
    splits = compute_splits(cfg, duration)
    lbox, rbox = split_boxes(cfg) if splits else (None, None)

    lay3 = cfg.get("_t3_lay")            # Template 3 adaptive layout: animated frame (see mt/templates/t3/layout.py)
    lay3 = lay3 if lay3 and not lay3.get("still") else None
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
    blur4 = cfg.get("_t4_blur") if cfg.get("template_id") == 5 else None      # Template 4 blur backdrop (see mt/templates/t4/base.py)
    if blur4:
        from mt.templates.t4.base import t4_blur_filter
        bg_f = f"[rb]{t4_blur_filter(blur4)}[bg]"                              # input 0 stays an unused solid colour (keeps input numbering)
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

    lay_idx = 3 + len(vl) + (1 if splits else 0) + (1 if rg_idx is not None else 0) + (1 if fg_idx is not None else 0) \
        + (1 if ph_idx is not None else 0)
    if lay3:
        from mt.templates.t3.layout import t3_layout_inputs
        cmd += t3_layout_inputs(cfg, fps_s, duration)
    bw, bh = box["w"], box["h"]
    vw, vh = info["w"], info["h"]
    ns = 1 + len(splits)
    if ns > 1 or blur4:
        src = (f"[1:v]fps={fps_s},setpts=PTS-STARTPTS,split={ns + (1 if blur4 else 0)}"
               + "".join(f"[r{i}]" for i in range(ns)) + ("[rb]" if blur4 else ""))
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

    if lay3:
        from mt.templates.t3.layout import t3_layout_video
        _vf, ox, oy = t3_layout_video(cfg)
        v_f = f"[r0]{_vf}[v]"
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
    if fg_idx is not None or lay3:
        # layers over the video box go UNDER the rounded frame (clipped by it), full-canvas layers above it
        seq = ([x for x in seq if x[1].get("area", "box") != "canvas"] + [(None, None)]
               + [x for x in seq if x[1].get("area", "box") == "canvas"])
    for i, L in seq:
        if i is None and lay3:
            from mt.templates.t3.layout import t3_layout_graph
            _frag, cur = t3_layout_graph(cfg, cur, lay_idx)
            fc += _frag
            continue
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
        if cfg["template_id"] == 3 and cfg.get("video_layers"):       # T3: video layers with place "side" become baked cards beside the frame
            from mt.templates.t3.layout import t3_split_side_video_layers
            cfg["video_layers"], cfg["_t3_side_vl"] = t3_split_side_video_layers(cfg)
        pre = prepare_video_layers(cfg, probe(cfg["video"]), tmp) if cfg.get("video_layers") else None
        _hook = get_template(cfg).get("prepare_layers")      # only Template 2 registers one (t2_prepare_card_layers); render.py must not import template code
        cards = _hook(cfg, probe(cfg["video"]), tmp) if _hook and cfg["template_id"] in (2, 3, 5) else []
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
    cfg["_t3_still_t"] = t               # Template 3 layout: which layout state to preview
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
        if cfg.get("template_id") == 5 and cfg.get("_t4_blur"):                # Template 4 blur backdrop: blurred cover copy of the frame
            from mt.templates.t4.base import t4_blur_still
            img = t4_blur_still(frame, W, H, cfg["_t4_blur"])
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
