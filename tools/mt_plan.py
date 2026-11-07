#!/usr/bin/env python3
"""Classify audit.json items into target modules; emit plan_map.json + dependency analysis (read-only)."""
import json, re, sys
a = json.load(open(sys.argv[1]))
S = lambda s: set(s.split())
M = {
"common": S("""os sys re json math shutil argparse subprocess tempfile time Fraction Path unicodedata BASE TEMPLATES_DIR FONTS_DIR DEFAULTS_FILE VIDEO_EXTS IMAGE_EXTS
 _ensure_python_packages _find_tool _require_ffmpeg FFMPEG FFPROBE _load_defaults _save_defaults D AR_DIGITS AR_COLORS YES NO clean_path ask yn c_float c_int c_time c_color
 c_size_wh c_existing_file c_text c_percent ask_time ask_choice _warn _WARNED probe _hex0x _img_ok _vid_ok _read_exact _t2_frac _t2_num_or_none _t2_norm T2_ACCENT"""),
"fonts": S("""has_arabic is_rtl_text ARABIC_RE ARABIC_MODE _reshaper setup_arabic_mode _CUR_FONT _cmap_cache _font_cmap _fix_missing shape _font_cache load_font
 font_supports_arabic _system_font_dirs _font_index _build_font_index list_local_fonts find_font default_font wrap_lines _font_ok _font_or_fallback"""),
"draw": S("""CYAN CYAN_TXT _draw_icon load_image_sprite make_text_sprite Item _paste draw_item resolve_pos t2_rgb t2_mix t2_lighten t2_darken t2_draw_mask t2_rrect_mask
 t2_poly_mask t2_polys_mask t2_line_mask t2_dots_mask t2_mask_sub t2_mask_full t2_place t2_ramp t2_gradient t2_grad _t2_alpha_paste t2_paint t2_glow t2_shear_mask
 t2_text_mask t2_fit_text t2_size_for_cap T2_SS _chamfer"""),
"anim": S("_out_cubic _out_back _out_bounce anim_state ANIMS PRESETS"),
"captions": S("""norm_tok parse_markup split_keywords kw_sequences find_sequences apply_keywords flatten_tokens phrase_groups _tok_dir visual_order make_rich_sprite _TASH
 TIME_RE _ts parse_srt caption_groups stream_groups caption_streams"""),
"split": S("SPLIT_T split_boxes compute_splits split_at"),
"render": S("""build_ffmpeg_cmd video_layer_area prepare_video_layers render _render render_still _first_frame _draw_frame _load_job preflight_cfg build_items"""),
"ask": S("""ask_font ask_anim c_anim ask_pos c_pos ANIM_LINE POS_LINE ask_caption_style ask_layers ask_texts ask_elements ask_video_layers find_trigger ICON_LINE list_templates maybe_save_template _saved_templates _PRESET _tpl_template_id"""),
"selftest": S("""GOLDEN_DIR GOLDEN_TIMES _StopSelftest _st_report run_selftest _selftest_t2 _selftest_t2_dynamic _selftest_t2_cards _selftest_t2_about _selftest_t2_panel
 _selftest_t2_4c _selftest_4d _st_make_assets _st_font _st_job _st_info _st_frame_diffs _st_golden_status _st_lime _st_grab _st_cream _st_card_points _st_card_hits _st_time_render"""),
"templates/__init__": S("choose_template interactive _interactive_core TEMPLATE_REGISTRY get_template recap_line"),
"templates/t1_tech": S("""make_tech_background make_card_sprite make_split_background t1_build_items t1_build_background t1_ask_config PALETTES ask_cards SLOT_LINE SLOTS ask_hud_template ask_template"""),
"montage": S("main _main"),
}
owner = {n: m for m, ns in M.items() for n in ns}
def target(it):
    ns = it["names"]
    for n in ns:
        if n in owner: return owner[n]
    if it["kind"] in ("Expr", "try", "import", "if") :
        if it["start"] == 3: return "montage(docstring)"
        if it["start"] == 129: return "common"
        if it["start"] in (76, 131, 132, 134): return "common"
        if it["kind"] == "if": return "montage"
        return "common"
    if any(re.match(r"^_?[tT]2", n) or "t2" in n.lower() for n in ns): return "templates/t2_lime"
    if ns and ns[0] in ("c_card_icon","c_about_icon","_hdr"): return "templates/t2_lime"
    return "UNASSIGNED"
for it in a: it["target"] = target(it); it["tpl"] = ("T1" if it["target"] == "templates/t1_tech" else "T2" if it["target"] == "templates/t2_lime" else "generic")
# generic-but-t1-ish markers
# dependency edges
where = {}
for it in a:
    for n in it["names"]: where[n] = it["target"]
edges = {}
for it in a:
    for r in it["refs"]:
        t = where.get(r)
        if t and t != it["target"]:
            edges.setdefault((it["target"], t), set()).add((it["names"][0], r))
order = ["common","fonts","draw","anim","captions","split","ask","render","templates/t1_tech","templates/t2_lime","templates/__init__","selftest","montage"]
out = dict(items=a, edges={f"{k[0]} -> {k[1]}": sorted(map(list, v)) for k, v in edges.items()})
json.dump(out, open(sys.argv[2], "w"), indent=1)
print("UNASSIGNED:", [(i["start"], i["names"]) for i in a if i["target"] == "UNASSIGNED"])
mods = sorted({i["target"] for i in a})
deps = {m: sorted({k[1] for k in edges if k[0] == m}) for m in mods}
for m in mods: print(m, "->", deps[m])
# cycles (SCCs)
import itertools
idx = {}; low = {}; st = []; on = set(); sccs = []; c = [0]
def sc(v):
    idx[v] = low[v] = c[0]; c[0] += 1; st.append(v); on.add(v)
    for w in deps.get(v, []):
        if w not in idx: sc(w); low[v] = min(low[v], low[w])
        elif w in on: low[v] = min(low[v], idx[w])
    if low[v] == idx[v]:
        comp = []
        while True:
            w = st.pop(); on.discard(w); comp.append(w)
            if w == v: break
        if len(comp) > 1: sccs.append(comp)
for m in mods:
    if m not in idx: sc(m)
print("CYCLES:", sccs)
