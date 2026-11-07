# S2 notes - captions, split, render moved
Lines: montage.py 5839 -> 4138 (-1701). mt/: __init__ 1, anim 76, ask 53 (new), captions 582, common 390, draw 914, fonts 322, render 537, split 107 = 2982. Total 7120.
Each move was followed by tools/mt_quick.py (compile + isolated imports + T1/T2 --job vs goldens, 0.000 diffs). No lazy imports were added.
## Decisions
- Cycle breakers (moved DOWN, not lazy): the T2 config layer (t2_cfg, t2_norm_*, T2_DEFAULTS/ABOUT/PANEL..., t2_about_icon_spec) -> mt/draw.py; t2_font/_t2_lookup/T2_FONTS/_t2_font_idx/_T2_WARNED -> mt/fonts.py; make_tech_background + _draw_frame -> mt/draw.py; ask_font/ask_anim/c_anim/ANIM_LINE -> mt/ask.py (new; needed by the caption styles, depends only on common/fonts/anim).
- Template registry: `TEMPLATE_REGISTRY = {}` and `get_template` live in mt/common.py. montage.py FILLS it with `TEMPLATE_REGISTRY.update({...})` (never rebinds) so mt/render.py dispatches templates without importing them. Entry 2 got one extra key `prepare_layers: t2_prepare_card_layers`; `render()` calls `get_template(cfg).get("prepare_layers")` instead of naming t2_prepare_card_layers (same behaviour: only T2 has it, still guarded by template_id == 2).
- Selftest edit (needed): `globals()["_t2_lookup"]` patch (test 44) now patches `mt.fonts._t2_lookup`, the module that owns and reads it. `globals()["TEMPLATES_DIR"]` patches still work because every reader of TEMPLATES_DIR is still in montage.py.
- tools/mt_move.py fix: skips self-imports (names that already live in the target and arrive via the source's re-export line).
- Both caption styles (ask_caption_style, t2_caption_style) moved into captions.py as asked; they import mt.ask (leaf).
- T1/T2 split: split.py has SPLIT_T, split_boxes, compute_splits, split_at, make_split_background, t2_split_params, t2_make_split_ring. t2_ask_split stays in montage (interactive, S3).
- Not moved (S3): everything template-specific (t1_*, t2_* sprites/cards/about/panel/roadmap), TEMPLATE_REGISTRY filling, interactive flows, selftest.
