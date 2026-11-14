"""mt.templates - template registry + selector + the interactive orchestrator.

Importing this package fills mt.common.TEMPLATE_REGISTRY (the dict lives in mt.common so mt.render can dispatch
without importing templates). Ids: 1 = Template 1, 2 = Template 2, 3 = Template 3 (Editorial Orange), 4 = Custom/saved."""
from mt.common import AR_DIGITS, D, TEMPLATE_REGISTRY, ask
from mt.ask import _PRESET, _saved_templates
from mt.captions import ask_caption_style, t2_caption_style
from mt.templates.t1_tech import ask_cards, ask_template, t1_ask_config, t1_build_background, t1_build_items
from mt.templates.t2_lime import (t2_ask_cards, t2_ask_config, t2_build_items, t2_build_static_layers,
                                  t2_prepare_card_layers)

from mt.templates.t3 import t3_ask_cards, t3_ask_config, t3_build_items, t3_build_static_layers, t3_caption_style
from mt.templates.t3 import t3_ask_cards_cfg, t3_prepare_card_layers
from mt.templates.t3.static import t3_cfg
from mt.templates.t2_lime import _interactive_t2, t2_ask_about, t2_ask_cards_cfg, t2_ask_chapters, t2_ask_panel, t2_ask_split
from mt.ask import ask_output_options, ask_srt_paths, ask_video_path, ask_elements, ask_layers, ask_texts, ask_video_layers
from mt.draw import t2_cfg
from mt.captions import parse_srt
from mt.common import get_template
from mt.templates.t4 import t4_ask_cards, t4_ask_config, t4_build_items, t4_build_static_layers, t4_caption_style, t4_prepare_card_layers
from mt.templates.t4.cfg import T4_MODULES, t4_cfg

TEMPLATE_REGISTRY.update({
    1: {"id": 1, "name": "Template 1", "desc": "Tech HUD, dark blue, glowing frame, info cards",
        "ask_config": t1_ask_config, "ask_cards": ask_cards, "caption_style": ask_caption_style,
        "build_background": t1_build_background, "build_items": t1_build_items},
    2: {"id": 2, "name": "Template 2", "desc": "Lime Creator Series",
        "ask_config": t2_ask_config, "ask_cards": t2_ask_cards, "caption_style": t2_caption_style,
        "build_background": t2_build_static_layers, "build_items": t2_build_items,
        "prepare_layers": t2_prepare_card_layers},
    3: {"id": 3, "name": "Template 3", "desc": "Editorial Orange",
        "ask_config": t3_ask_config, "ask_cards": t3_ask_cards, "caption_style": t3_caption_style,
        "build_background": t3_build_static_layers, "build_items": t3_build_items,
        "prepare_layers": t3_prepare_card_layers},
    4: {"id": 4, "name": "Custom", "desc": "old Custom flow, and your saved templates from templates/*.json",
        "ask_config": ask_template, "ask_cards": ask_cards, "caption_style": ask_caption_style,
        "build_background": t1_build_background, "build_items": t1_build_items},
    5: {"id": 5, "name": "Template 4", "desc": "Overlay Studio - the video is the base, every design element is a layer",
        "ask_config": t4_ask_config, "ask_cards": t4_ask_cards, "caption_style": t4_caption_style,
        "build_background": t4_build_static_layers, "build_items": t4_build_items,
        "prepare_layers": t4_prepare_card_layers},
})

_SAVED_LABEL = {2: 'Template 2, Lime Creator Series', 3: 'Template 3, Editorial Orange', 5: 'Template 4, Overlay Studio'}


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
            print(f"   {n} = {p.stem:<10}  (saved - {_SAVED_LABEL.get(tid, 'Template 1 / Custom')})")
    last = len(ids) + len(saved)

    def _c(s):
        v = int(s.translate(AR_DIGITS))
        if TEMPLATE_REGISTRY.get(v, {}).get("coming_soon"):
            raise ValueError(f"{TEMPLATE_REGISTRY[v]['name']} is coming soon - please choose another")
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


def _interactive_core():
    print("=" * 60)
    print("  Montage builder  (Pillow + FFmpeg)")
    print("=" * 60)
    cfg = {}
    tpl_entry = choose_template()
    cfg["template_id"] = tpl_entry["id"]
    if tpl_entry["id"] == 2:
        return _interactive_t2(cfg, tpl_entry)
    if tpl_entry["id"] == 3:
        return _interactive_t3(cfg, tpl_entry)
    if tpl_entry["id"] == 5:
        return _interactive_t4(cfg, tpl_entry)
    cfg["video"], info = ask_video_path()
    srt_paths = ask_srt_paths(parse_srt)

    tpl = tpl_entry["ask_config"](info)
    cfg.update({k: tpl[k] for k in ("canvas", "video_box", "background")})
    cfg["layers"] = tpl.get("layers", [])
    if tpl_entry["id"] == 3:
        cfg["t3"] = dict(tpl.get("t3") or {})          # the T3 settings must reach the job (they were never stored before T3-4)
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
    elif tpl_entry["id"] == 3:
        cfg["cards"] = []
        cfg["t3"].update(t3_ask_cards_cfg(parse_srt(srt_paths[0]) if srt_paths else []))
        cfg["t3"] = t3_cfg(cfg["t3"])
    else:
        cfg["cards"] = tpl_entry["ask_cards"](parse_srt(srt_paths[0]) if srt_paths else [])
    cfg["elements"] = ask_elements(info["duration"])
    cfg["video_layers"] = ask_video_layers(info["duration"])
    if tpl_entry["id"] == 2:
        if cfg["elements"] or any(v.get("area", "box") == "box" for v in cfg["video_layers"]):
            cfg["t2"].update(t2_ask_split())
            cfg["t2"] = t2_cfg(cfg["t2"])

    ask_output_options(cfg)
    return cfg


def _interactive_t3(cfg, tpl_entry):
    """Template 3 question flow, grouped under headers:
    video -> SRT(s) -> identity/header/footer -> headline -> frame -> layout mode -> chapters -> captions -> cards -> strip ->
    panel (gallery, content slot, checklist) -> split -> texts/elements/layers/video layers -> output -> preview."""
    from mt.templates.t3 import (_hdr, _t3_ask_modules, _t3_finish_layout, _base_tpl, t3_ask_layout_mode, t3_ask_style)
    from mt.templates.t3.dynamic import t3_ask_chapters
    _hdr(1, "Video")
    cfg["video"], info = ask_video_path()
    if info["duration"] < 3:
        print(f"   [i] very short video ({info['duration']:.1f} s): anything timed after the end is simply not shown.")
    if abs(info["w"] / float(info["h"]) - 9 / 16.0) > 0.02:
        print("   [i] not 9:16 - the video is fitted into the frame ('fit' = whole video, 'fill' = cropped); it is never stretched.")
    _hdr(2, "Captions file (SRT)")
    srt_paths = ask_srt_paths(parse_srt)
    cues0 = parse_srt(srt_paths[0]) if srt_paths else []
    t3, full = t3_ask_style(info)                              # groups 3 identity, 4 headline, 5 frame
    if full:                                                   # old saved template: it carries its own content settings
        tpl, t3 = t3, dict(t3["t3"])
        lm = None
    else:
        tpl, lm = None, t3_ask_layout_mode()                   # group 6
        from mt.templates.t3 import _hdr as _h
        _h(7, "Chapter tags")
        t3.update(t3_ask_chapters())
    cfg.update({"canvas": [1080, 1920], "layers": []})
    _hdr(8, "Captions")
    if srt_paths:
        cfg["captions"] = [tpl_entry["caption_style"](i, p) for i, p in enumerate(srt_paths)]
    else:
        cfg["captions"] = []
        print("   (no SRT given - no captions)")
    _hdr(9, "Floating cards")
    cfg["cards"] = []
    t3.update(t3_ask_cards_cfg(cues0))
    if not full:
        t3 = _t3_ask_modules(t3)                               # groups 10 strip, 11 panel, 12 split
        t3 = _t3_finish_layout(t3, lm)
    base = tpl or _base_tpl(t3)
    cfg.update({k: base[k] for k in ("video_box", "background")})
    cfg["t3"] = t3_cfg(t3)
    _hdr(13, "Texts / elements / template layers / video layers")
    cfg["texts"] = ask_texts(info["duration"])
    cfg["elements"] = ask_elements(info["duration"])
    cfg["layers"] = ask_layers(*cfg["canvas"])
    cfg["video_layers"] = ask_video_layers(info["duration"])
    _hdr(14, "Output + quick test")
    ask_output_options(cfg)
    return cfg


def _interactive_t4(cfg, tpl_entry):
    """Template 4 flow: video -> SRT(s) -> canvas + fit/fill -> captions -> texts / elements / layers / video layers -> output."""
    cfg["video"], info = ask_video_path()
    srt_paths = ask_srt_paths(parse_srt)
    tpl = tpl_entry["ask_config"](info)
    cfg.update({k: tpl[k] for k in ("canvas", "video_box", "background", "t4")})
    cfg["layers"] = []
    cfg["captions"] = [tpl_entry["caption_style"](i, p) for i, p in enumerate(srt_paths)]
    cfg["cards"] = []
    cfg["texts"] = ask_texts(info["duration"])
    cfg["elements"] = ask_elements(info["duration"])
    cfg["layers"] = ask_layers(*cfg["canvas"])
    cfg["video_layers"] = ask_video_layers(info["duration"])
    ask_output_options(cfg)
    return cfg


def interactive():
    try:
        return _interactive_core()
    finally:
        _PRESET.clear()


def recap_line(cfg):
    """One line: template name + which Template 2 modules are on."""
    e = get_template(cfg)
    line = f"{e['name']} - {e['desc']}"
    if e["id"] == 3:
        t3 = t3_cfg(cfg.get("t3"))
        pn, sl, st, sp = t3["panel"], t3["slot"], t3["strip"], t3["split"]
        mods = [("header", t3["show_header"]), ("headline", t3["show_headline"]), ("footer", t3["show_footer"]),
                ("captions x%d" % len(cfg.get("captions", [])), bool(cfg.get("captions"))),
                ("chapters x%d" % len(t3.get("chapters") or []), bool(t3.get("chapters")) and t3.get("chapters_on", True)),
                ("cards x%d" % len(t3.get("cards") or []), bool(t3.get("cards")) and t3.get("cards_on", True)),
                ("strip", bool(st["on"]) and t3["layout"]["on"]), ("panel", bool(pn["on"]) and t3["layout"]["on"]),
                ("centre slot", bool(sl["on"]) and bool(pn["on"])), ("split", bool(sp["on"]) and bool(sp["segments"])),
                ("layout " + t3["layout"]["mode"].upper(), bool(t3["layout"]["on"])),
                ("texts x%d" % len(cfg.get("texts", [])), bool(cfg.get("texts"))),
                ("elements x%d" % len(cfg.get("elements", [])), bool(cfg.get("elements")))]
        return line + "  |  ON: " + (", ".join(n for n, on in mods if on) or "-") + \
            "  |  off: " + (", ".join(n.split(" x")[0] for n, on in mods if not on) or "-")
    if e["id"] == 5:
        t4 = t4_cfg(cfg.get("t4"))
        cv = cfg.get("canvas") or ["?", "?"]
        mods = [(m, bool(t4[m]["on"])) for m in T4_MODULES] + [
            ("captions x%d" % len(cfg.get("captions", [])), bool(cfg.get("captions"))),
            ("texts x%d" % len(cfg.get("texts", [])), bool(cfg.get("texts"))),
            ("elements x%d" % len(cfg.get("elements", [])), bool(cfg.get("elements")))]
        return line + f"  |  {cv[0]}x{cv[1]} {t4['fit']}  |  ON: " + (", ".join(n for n, on in mods if on) or "-") + \
            "  |  off: " + (", ".join(n.split(" x")[0] for n, on in mods if not on) or "-")
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
