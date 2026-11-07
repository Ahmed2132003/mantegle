"""mt.templates.t3 - Template 3 "Editorial Orange" (T3-1: static background, header, footer).
Hooks for the registry entry id 3; the config namespace is cfg["t3"] (see static.t3_cfg for the keys)."""
import json
import os
from pathlib import Path

from mt.ask import _PRESET, _tpl_template_id, list_templates, maybe_save_template
from mt.common import D, ask, ask_choice, c_color, yn
from mt.templates.t3.dynamic import (t3_anchor, t3_ask_cards_cfg, t3_ask_chapters, t3_caption_style,  # noqa: F401
                                     t3_card_items, t3_card_quad, t3_card_sprite, t3_dynamic_items, t3_prepare_card_layers)
from mt.templates.t3.static import (DEFAULTS, VIDEO_BOX, make_t3_static, t3_build_static_layers, t3_bracket_polygon,  # noqa: F401
                                    t3_cfg, t3_frame_layer, t3_frame_quad, t3_headline_layer)


def _c_text(s):
    s = s.strip()
    return "" if s == "-" else s


def _on(key, question, default):
    v = yn(question, default=D.get(key, "y" if default else "n") == "y")
    D[key] = "y" if v else "n"
    return v


def _c_colors(s):
    """'cream, cream, accent' -> 3 names/hex values (a '-' or empty keeps the default for that line)."""
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 3:
        raise ValueError("give 3 colors separated by commas, e.g. cream,cream,accent")
    return parts


def _hdr(n, title):
    print("\n=== %s. %s %s" % (n, title, "=" * max(4, 56 - len(title))))


def _base_tpl(t3):
    return {"template_id": 3, "canvas": [1080, 1920], "video_box": dict(VIDEO_BOX, mode=t3_cfg(t3)["video_fit"]),
            "background": {"type": "t3"}, "layers": [], "t3": t3_cfg(t3)}


def t3_ask_style(video_info=None):
    """STYLE questions in groups 3-5 (identity / header / footer, headline, frame style), then the optional named-style save.
    Returns (t3 dict, full) - full = an OLD saved template (everything stored) was picked: its tpl dict is returned instead of t3."""
    W, H = 1080, 1920
    pp = _PRESET.pop("path", None)
    loaded = None
    if pp and os.path.isfile(pp):                          # saved Template 3 design picked in the selector
        tpl = json.loads(Path(pp).read_text(encoding="utf-8-sig"))
        if not tpl.get("t3_style"):                        # old full template (everything saved): used as is
            tpl["t3"] = t3_cfg(tpl.get("t3"))
            tpl.setdefault("canvas", [W, H])
            tpl.setdefault("layers", [])
            tpl["background"] = {"type": "t3"}
            tpl["template_id"] = 3
            print(f"   Loaded saved template '{Path(pp).stem}' (style + texts).")
            return tpl, True
        loaded = {k: v for k, v in (tpl.get("t3") or {}).items() if k in STYLE_KEYS}
        print(f"   Loaded saved style '{Path(pp).stem}' (palette, fonts, texts, frame, toggles) - style questions skipped.")
        return loaded, False
    print("\n=== Template 3 - Editorial Orange (1080x1920) ===")
    print("   (Enter = the poster default / your last answer.   '-' = hide that element)")
    d = DEFAULTS
    t3 = {}
    _hdr(3, "Identity / header / footer")
    t3["accent"] = ask("Accent color (hex or name)", default=d["accent"], key="t3_accent", cast=c_color)
    t3["show_bg"] = _on("t3_show_bg", "Show the background design (polygons, paper, slash, skyline)?", True)
    if t3["show_bg"]:
        t3["watermark"] = _on("t3_watermark", "Faint face watermark (top-right, from your video)?", True)
    t3["show_header"] = _on("t3_show_header", "Show the header (name, roles, tagline)?", True)
    if t3["show_header"]:
        t3["name1"] = ask("Name line 1", default=d["name1"], key="t3_name1", cast=_c_text)
        t3["name2"] = ask("Name line 2 (accent color)", default=d["name2"], key="t3_name2", cast=_c_text)
        t3["roles"] = [ask(f"Role line {i + 1}", default=d["roles"][i], key=f"t3_role{i + 1}", cast=_c_text)
                       for i in range(3)]
        t3["tagline"] = ask("Top-right tagline (use \u2022 between words)", default=d["tagline"], key="t3_tagline",
                            cast=_c_text)
    t3["show_footer"] = _on("t3_show_footer", "Show the footer (words, line, signature)?", True)
    if t3["show_footer"]:
        t3["footer"] = ask("Footer words (use \u2022 between words)", default=d["footer"], key="t3_footer", cast=_c_text)
        t3["signature"] = ask("Signature text", default=d["signature"], key="t3_signature", cast=_c_text)
    _hdr(4, "Headline")
    t3["show_headline"] = _on("t3_show_headline", "Show the headline column (BEYOND / THE / CODE. + tagline)?", True)
    if t3["show_headline"]:
        t3["headline"] = [ask(f"Headline line {i + 1}", default=d["headline"][i], key=f"t3_head{i + 1}", cast=_c_text)
                          for i in range(3)]
        t3["headline_colors"] = ask("Headline line colors (cream / accent / hex, 3 values)",
                                    default=",".join(d["headline_colors"]), key="t3_head_colors", cast=_c_colors)
        t3["headline_underline"] = _on("t3_head_underline", "Thin accent underline under the headline?", True)
        t3["tag_lines"] = [ask(f"Small tagline line {i + 1}", default=d["tag_lines"][i], key=f"t3_tag{i + 1}",
                               cast=_c_text) for i in range(3)]
    _hdr(5, "Frame style")
    fs = ask_choice("Video frame style:", ["Skewed editorial cut-out (poster)", "Straight rectangle"], default=1,
                    key="t3_frame_style")
    t3["frame_style"] = "skewed" if fs == 1 else "straight"
    vf = ask_choice("Video fit inside the frame:", ["Fill (crop to the frame)", "Fit (whole video, letterboxed)"],
                    default=1, key="t3_video_fit")
    t3["video_fit"] = "fill" if vf == 1 else "fit"
    style = {k: t3[k] for k in STYLE_KEYS if k in t3}
    maybe_save_template({"template_id": 3, "t3_style": True, "canvas": [W, H], "background": {"type": "t3"}, "layers": [],
                         "t3": style})                      # T3-9: named STYLE (palette, fonts, texts, frame, toggles) - not the content
    return t3, False


def t3_ask_layout_mode():
    """Group 6: AUTO (bands / split appear when their content starts) or MANUAL (+ optional layout events). -> {mode, events}."""
    from mt.templates.t3.dynamic import _c_start
    _hdr(6, "Layout mode")
    m = ask_choice("Layout mode (how the video frame resizes for the strip / panel / split):",
                   ["AUTO (follows the content, recommended)", "MANUAL (you give state changes)"], default=1, key="t3_layout_mode")
    if m == 1:
        return {"mode": "auto", "events": []}
    print("   States: S0 none | S1 strip | S2 panel | S3 strip + panel.  A change at a time (seconds / mm:ss) or a spoken phrase.")
    events = []
    while len(events) < 12 and yn("Add a layout change?", default=False if not events else False):
        kind, val = ask("  At (seconds / mm:ss / spoken phrase)", cast=_c_start)
        st = ask_choice("  New state:", ["S0 none", "S1 strip", "S2 panel", "S3 both"], default=1, key=f"t3_lay_state{len(events)}") - 1
        events.append({"at": val if kind == "t" else None, "trigger": val if kind == "p" else "", "state": f"S{st}"})
    return {"mode": "manual", "events": events}


def _t3_finish_layout(t3, lm):
    """Merge the layout mode / events into t3['layout'] (bands / split switch the layout on; manual events do too)."""
    lay = dict(t3.get("layout") or {})
    if lm["mode"] == "manual":
        lay.update(mode="manual", events=lm["events"], on=bool(lay.get("on")) or bool(lm["events"]))
    elif lay:
        lay["mode"] = "auto"
    if lay:
        t3["layout"] = lay
    return t3


def t3_ask_config(video_info):
    """Template 3 questions as ONE call (registry hook / saved designs): style -> layout mode -> content questions.
    The full interview with group headers and the generic questions in between lives in templates._interactive_t3."""
    t3, full = t3_ask_style(video_info)
    if full:
        return t3
    lm = t3_ask_layout_mode()
    t3 = _t3_ask_content(t3)
    return _base_tpl(_t3_finish_layout(t3, lm))


STYLE_KEYS = ("accent", "show_bg", "watermark", "show_header", "name1", "name2", "roles", "tagline", "show_footer", "footer",
              "signature", "frame_style", "frame_skew", "video_fit", "show_headline", "headline", "headline_colors",
              "headline_underline", "tag_lines", "fonts")


def _t3_ask_content(t3):
    """Content questions (chapters, strip, panel + centre slot, split): asked even when a saved style is loaded."""
    _hdr(7, "Chapter tags")
    t3.update(t3_ask_chapters())
    t3 = _t3_ask_modules(t3)
    return t3


def _t3_ask_modules(t3, cues=None):
    """Groups 10-12: photo strip, bottom panel (gallery + centre slot + checklist), split screen."""
    _hdr(10, "Photo-tiles strip")
    from mt.templates.t3.panels import t3_ask_strip           # T3-6: photo-tiles strip (turns the adaptive layout on, AUTO mode)
    t3.update(t3_ask_strip())
    _hdr(11, "Bottom panel (gallery, centre content slot, checklist)")
    from mt.templates.t3.panels import t3_ask_panel           # T3-7/8: bottom panel (gallery + checklist + centre slot)
    pn = t3_ask_panel()
    if pn:
        t3.update(pn)
    _hdr(12, "Split screen")
    from mt.templates.t3.layout import t3_ask_split           # T3-9: split screen (S4)
    sp = t3_ask_split()
    if sp:
        lay = dict(t3.get("layout") or {})
        t3["split"] = sp["split"]
        t3["layout"] = dict(lay, on=True, mode=lay.get("mode", "auto"))
    return t3


def t3_ask_cards(cues):
    return []                       # T3-2 will add its own cards; T3-1 has none


def t3_build_items(cfg, duration, splits, lbox, rbox):
    if cfg.get("_t3_lay"):                          # T3-5: layout on -> items follow the moving frame
        from mt.templates.t3.layout import t3_layout_items
        return t3_layout_items(cfg, duration)
    return t3_dynamic_items(cfg, duration)          # T3-3: chapter tags + frame-relative captions


from mt.templates.t3 import panels as _panels  # noqa: E402,F401  (registers the strip band with the layout engine)
from mt.templates.t3.panels import (strip_items, strip_ranges, strip_resolve, strip_tile_sprite, t3_ask_strip,  # noqa: E402,F401
                                    panel_items, panel_ranges, panel_resolve, t3_ask_panel, t3_panel_cfg, t3_panel_center_rect,
                                    t3_strip_cfg)


def _t3_layers_with_slot(_cards):
    def hook(cfg, info, tmp):                        # T3-8: baked slot media clips go on top of the card clips
        from mt.templates.t3.layout import split_prepare_layers, t3_side_video_prepare
        from mt.templates.t3.slot import slot_prepare_layers
        return (_cards(cfg, info, tmp) + t3_side_video_prepare(cfg, info, tmp) + slot_prepare_layers(cfg, info, tmp)
                + split_prepare_layers(cfg, info, tmp))
    return hook


t3_prepare_card_layers = _t3_layers_with_slot(t3_prepare_card_layers)       # noqa: F811  (registry imports this name)
from mt.templates.t3.slot import t3_ask_slot, t3_slot_cfg, slot_items, slot_resolve  # noqa: E402,F401
