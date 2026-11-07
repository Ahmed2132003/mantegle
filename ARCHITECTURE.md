# ARCHITECTURE (read this first)

`montage.py` = thin entry (argparse + dispatch, ~140 lines). Everything else is the package `mt/`.
Rule for every change: **no behavior change without a golden check** (`python montage.py --selftest`, T1 + T2 goldens must stay 0.000 diff).

## 1. Module map (dependency order, low -> high; an arrow never points back up)
| Module | Lines | Role |
|---|---|---|
| `mt/common.py` | ~390 | imports/consts, `BASE`, defaults file `D`, input helpers (`ask`, `yn`, `c_*`), ffmpeg/ffprobe discovery, `probe`, **`TEMPLATE_REGISTRY` (empty dict) + `get_template`** |
| `mt/fonts.py` | ~320 | font discovery, Arabic shaping (`ARABIC_MODE`, `setup_arabic_mode`), `t2_font` |
| `mt/anim.py` | ~75 | animation presets + `anim_state` (pure maths) |
| `mt/draw.py` | ~910 | Pillow helpers (masks, gradients, glow), `Item`/`draw_item` sprites, T2 config layer (`t2_cfg`, `t2_norm_*`) |
| `mt/ask.py` | ~235 | GENERIC questions: video/SRT/output/preview, texts, elements, template layers, video layers, saved-template IO (`_PRESET`, `list_templates`) |
| `mt/captions.py` | ~590 | SRT parse, keyword markup, caption groups/sprites, both caption styles, `find_trigger` |
| `mt/split.py` | ~110 | split-screen geometry (`split_boxes`, `compute_splits`, `make_split_background`) |
| `mt/render.py` | ~540 | the pipeline: `preflight_cfg`, `build_items`, `build_ffmpeg_cmd`, `render`, `render_still`, `_load_job` |
| `mt/templates/t1_tech.py` | ~320 | Template 1 (Tech HUD) + the Custom flow: HUD cards, `ask_template`, `t1_*` hooks |
| `mt/templates/t2_lime.py` | ~1720 | Template 2 (Lime Creator Series): static plates, chapters, cards, about, panel, roadmap, `t2_ask_*`, `_interactive_t2` (**over 1500 lines - split candidate**) |
| `mt/templates/__init__.py` | ~140 | fills `TEMPLATE_REGISTRY`, `choose_template` (selector), `interactive` orchestrator, `recap_line` |
| `mt/flow.py` | ~70 | CLI plumbing: `guarded` (error -> one readable line), `recap_and_confirm` |
| `mt/selftest.py` | ~1700 | `run_selftest`, synthetic assets, golden compare, **`@selftest_check` registry** |

`render.py` never imports templates: it dispatches through `get_template(cfg)` (registry in `mt.common`). Importing `mt.templates`
(done by `montage.py`, `mt.flow` and `mt.selftest`) is what fills the registry.

## 2. Selector ids (stable - they are stored in job files as `template_id`)
`1` Template 1 | `2` Template 2 | `3` Template 3 "Editorial Orange" = **live** (package `mt/templates/t3/`, see sections 10-14) | `4` Custom (old flow + saved `templates/*.json`).
Saved templates are numbered after the fixed ids (5, 6, ...). Old job files with `template_id: 3` (Custom before S4) are migrated to 4 in `_load_job` ONLY when they have no `t3` key and `background.type != "t3"` (real Template 3 jobs carry `cfg["t3"]`). Saved `templates/*.json` with `template_id` 3 are Template 3 designs.
Missing/unknown `template_id` -> Template 1.

## 3. TEMPLATE HOOK CONTRACT
A registry entry is a dict in `TEMPLATE_REGISTRY[id]`. `id`, `name`, `desc` are required for display; hooks below are called by the generic code.
| Key | Signature | Called by / when | Returns |
|---|---|---|---|
| `ask_config` | `(video_info) -> dict` | `_interactive_core`, after video + SRT questions | `{"canvas":[W,H], "video_box":{x,y,w,h,mode}, "background":{type,...}, "layers":[...], optional "t2": {...}}` |
| `ask_cards` | `(cues) -> list` | `_interactive_core`, after texts (non-T2 templates; T2 asks its own cards in `_interactive_t2`) | list of card dicts, stored in `cfg["cards"]` |
| `caption_style` | `(idx, srt_path) -> dict` | once per SRT file | one caption-stream dict for `cfg["captions"]` (font, size, colors, animation, keywords...) |
| `build_background` | `(cfg, tmp)` | start of `render()` and `render_still()` | nothing; writes plate PNGs into `tmp` and rewrites `cfg["background"]` (and `cfg["_t2_fg"]` for a foreground plate) |
| `build_items` | `(cfg, duration, splits, lbox, rbox) -> list[Item]` | `build_items()` in render.py, after texts/elements, before captions | timeline `Item`s (cards, chapter tags, about, panel dots, roadmap) |
| `prepare_layers` *(optional)* | `(cfg, video_info, tmp) -> list` | `render()` after `prepare_video_layers` | extra video layers (e.g. baked video cards), appended on top; today render.py calls it only when `template_id == 2` |
Not hooks but T2-aware spots in generic code (known, keep or generalise deliberately): `preflight_cfg` (T2 numpy/fonts check, `id == 2`),
`render()` (`prepare_layers` guard), `_interactive_core` (branches on `id == 2`), `recap_line`.

## 4. How things plug in
- **Static layers**: `build_background` draws into `tmp` once per render; background plate = under the video, foreground plate (`cfg["_t2_fg"]`) = over it. Cache big plates (see `_T2_CACHE_DIR`).
- **Dynamic overlays**: return `Item(sprite, start, end, cx, cy, anim, anim_dur, ...)` from `build_items`; animation is `mt.anim.anim_state` via `draw_item`. No per-frame Python outside `Item`.
- **Captions**: `caption_style` returns the stream dict; the sprite/layout code lives in `mt/captions.py` (`t2_caption_*` for T2). Generic code calls `caption_streams(cfg)` + `stream_groups`.
- **Cards**: image cards = `Item`s from `build_items`; video cards = baked alpha clips returned by `prepare_layers`. Triggers by spoken phrase use `find_trigger(cues, phrase)`.
- **Split**: geometry in `mt/split.py` (`cfg["t2"]["split"]` / T1 split); the template's `build_background` draws the split background; `build_items` receives `splits, lbox, rbox`.
- **Selftest checks**: `from mt.selftest import selftest_check`, then `@selftest_check("name") def _check(rec, quiet, feed, A, tmp)`.
  `rec(name, "PASS"/"FAIL"/"SKIP", detail)` records; `quiet(fn,*a)` runs with stdout muted; `feed(answers, prompts)` scripts `input()`; `A` = synthetic asset dir; `tmp` = scratch dir.
  Checks run in registration order after the environment gate (check 1). A crashing check becomes FAIL, not an abort. Patch module state on the OWNING module (`mt.ask.TEMPLATES_DIR`, `mt.fonts._t2_lookup`), never via `globals()`.

## 5. Rule: BASE_DIR comes from the entry folder
`mt.common.BASE` (alias `BASE_DIR`) = the folder that contains `montage.py` (= parent of the `mt/` package). Templates dir, fonts dir, defaults file, local ffmpeg,
`selftest_golden/` and `selftest_golden_t2/` are all resolved from it. Never use `__file__` of an `mt` module for data paths; subprocess re-invocations use `BASE / "montage.py"`.
Run from any cwd: nothing depends on the current directory.

## 6. State that must not be rebound
`D`, `_PRESET`, `TEMPLATE_REGISTRY`, font caches are shared mutable objects: mutate (`.update`, `.clear`), never `x = {}` in another module.
`ARABIC_MODE` is rebound by `setup_arabic_mode`: read it as `fonts.ARABIC_MODE`, never `from mt.fonts import ARABIC_MODE` in new code.

## 7. Add a new template in 10 steps (example: Template 3)
1. Create `mt/templates/t3_name.py`; import only from `mt.common/fonts/draw/ask/captions/split/render` (not from `mt.templates`).
2. Write `t3_ask_config(video_info)` -> canvas/video_box/background/layers (use `ask_layers`, `ask_pos`, `ask_font` from `mt.ask`).
3. Write `t3_build_background(cfg, tmp)`; draw plates with `mt.draw` helpers; point `cfg["background"]` at the PNG.
4. Write `t3_build_items(cfg, duration, splits, lbox, rbox)` returning `Item`s (reuse `t1_build_items` only if you want HUD cards).
5. Reuse `ask_caption_style` or write `t3_caption_style(idx, srt)` (sprite code goes to `mt/captions.py`).
6. Write `t3_ask_cards(cues)` (or reuse `ask_cards`); add `prepare_layers` only if you bake video layers.
7. In `mt/templates/__init__.py` replace the id-3 placeholder (`"coming_soon": True`) by the real entry with these hooks.
8. Add `@selftest_check("T3 ...")` checks in your module or in `mt/selftest.py`: render 1.5 s, check size/duration/audio, one pixel/geometry assertion.
9. Make a golden: `tools/mt_make_golden_t2.py` is the model (3 PNG frames + job json into `selftest_golden_t3/`); compare in a check with `_st_frame_diffs` (< 1.0 mean diff).
10. Run `python montage.py --selftest` (all T1/T2 goldens still 0.000), `--job`, `--still`, `--preview 2`, Enter-through stdin and the selector test; update this file.

## 8. Tools (`tools/`)
`mt_move.py` (AST-based mover, keeps compat re-exports; `--list`), `mt_quick.py` (compile + imports + T1/T2 `--job` vs goldens), `mt_audit.py`, `mt_plan*.py` (old split plan),
`mt_make_golden_t2.py`, `mt_s1_jobtests.py`. History: `S1_NOTES.md`..`S4_NOTES.md`, `SPLIT_PLAN.md`.

## 9. Known debt
`t2_lime.py` > 1500 lines (split into static / chapters / cards / about / panel / ask when needed); the `id == 2` special cases in section 3; `t2_*` names in `mt/draw.py` and `mt/captions.py` are generic or T2-only helpers kept for compatibility.

## 10. Template 3 (T3-1: static plates)
`mt/templates/t3/static.py`: `t3_cfg` (normaliser; keys: accent, name1, name2, roles[3], tagline, footer, signature, watermark, show_bg, show_header, show_footer, fonts), `t3_font(role, text, overrides)`, `make_t3_static(W,H,cfg_t3,video,out_paths)`, `t3_build_static_layers` (hook: bg plate under the video -> `cfg["background"]`; header+footer RGBA plate over the video -> `cfg["_t2_fg"]`, the pipeline's generic foreground slot, same as T2; `cfg["_t3_info"]` = element boxes).
Generic helpers added to `mt/draw.py`: `paper_texture`, `paper_fill`, `rotated_mask`, `draw_dotted_line`. Selftest checks `T3-1 ...` at the end of `mt/selftest.py` (cannot live in the t3 package: `mt.selftest` imports `mt.templates`).
Video window is a placeholder (`VIDEO_BOX`) until T3-2. Fonts: Playfair Display Bold, Rajdhani (SemiBold / Light), Mrs Saint Delafield or Allura, Cairo; each falls back with one message naming the file for `fonts/`.

## 11. Template 3 adaptive layout (T3-5)
`mt/templates/t3/layout.py`. `cfg["t3"]["layout"]` = `{on: False, mode: "auto"|"manual", start: "S0", trans: 0.5, events: [{at | trigger, state}]}` (normalised by `t3_layout_cfg`, called from `t3_cfg`). `on` False = old fixed poster geometry (no behaviour change).
States S0 none / S1 strip / S2 panel / S3 both (= poster); two presence tracks s(t), p(t) drive frame bottom `1520-310p-245s-10ps` (poster px). `t3_layout(state | 0..3 float | (s,p), base_box=None)` -> `{sp, frame(x,y,w,h), strip|None, panel|None}`; `t3_layout_at(cfg, t)` for a job time.
Pipeline hooks: `t3_build_static_layers` -> `t3_layout_prepare` (plates + band PNGs + ffmpeg expressions into `cfg["_t3_lay"]`; `--still` bakes plate + bands at the still time `cfg["_t3_still_t"]`); `t3_build_items` -> `t3_layout_items` (items re-anchored per frame, pieces); `build_ffmpeg_cmd` -> `t3_layout_video/inputs/graph` (only when `_t3_lay` is set).
Bands (T3-6/7/8): `register_band("strip"|"panel", ranges=fn(cfg, duration)->[(a,b)], content=fn(cfg, w, h)->RGBA|None)`; `t3_band_active_ranges` merges the providers (AUTO mode). Until registered a dim "STRIP"/"PANEL" placeholder is drawn.

## 12. Template 3 centre slot (T3-8)
`mt/templates/t3/slot.py` fills the bottom panel's CENTER column (`t3_panel_center_rect`). `cfg["t3"]["slot"]` = `{on, title "KEY POINTS", icon layers|star|bulb|chart|tag, anim, anim_dur, blocks:[...]}` (`t3_slot_cfg`, called from `t3_cfg`; blocks missing = 3 demo blocks, `[]` = empty slot, header hidden). Block types: `points` (lines, bullet dot|number, reveal stagger|trigger|all), `stat` (value, label, sub, count_up), `media` (image | video file | original-video segment seg_start/seg_end, caption), `chips` (chips [{text, trigger}]); each has start | trigger | hold. Only drawn when `panel.on`.
Hooks: `panel_band_content` (header / old placeholder), `panel_items` (+`slot_items`), `t3_prepare_card_layers` wrapper in `t3/__init__.py` (+`slot_prepare_layers`: media video segments baked as alpha clips like floating cards), `t3_ask_panel` (+`t3_ask_slot`).

## 13. Template 3 split mode S4 + saved styles (T3-9)
`layout.py`: the layout engine has a third presence track `x` (split). `t3_layout(state)` accepts `'S4'` / `(s, p, x)`: frame width = `1 - x * 0.44` (left 56 %), `["right"]` = matching right frame box (gap 5 %), `["x"]` = progress. Timeline: `t3_layout_timeline` adds the `x` track from `split_windows(cfg, duration)` and cuts the band ranges (AUTO mode) so strip/panel are hidden while S4 is on; `_spx_at(tl, t)` -> (s, p, x) (`_sp_at` unchanged, 2-tuple). Plates: `_plate(..., right=, x=)` + `_right_frame` (headline fades out with x, dark panel + cream border + orange bracket on the right); ffmpeg: video width expression `bwx`. Content: `split_items` (image Items, quad-masked) + `split_prepare_layers` (video media baked to alpha clips; hooked in `t3/__init__.py`). `t3_split_clip` cuts band items (strip tiles, panel rows, slot blocks) during S4. `_base(cfg)` = `cfg["_t3_base"]` (frame x/y/w before any shrink).
`cfg["t3"]["split"] = {on, merge, segments:[{start | trigger, end | hold, media, mode fill|fit}]}` (`t3_split_cfg`, `t3_ask_split`).
Saved styles: `t3_ask_config` saves only `STYLE_KEYS` (palette, fonts, texts, frame, toggles; file has `"t3_style": true`, template_id 3); loading one skips the style questions and still asks the content questions. Old full saved templates (no `t3_style`) load as before.


## 14. Template 3 summary (T3-10: polish + robustness)
**Modules** (`mt/templates/t3/`): `static.py` (config normaliser `t3_cfg`, fonts `t3_font`, `t3_warn` once-per-render messages, plates, frame, headline) | `dynamic.py` (chapter tags, frame-relative captions, floating cards, `t3_ask_chapters`) | `layout.py` (adaptive layout engine: presence tracks s / p / x, plates, ffmpeg expressions, split S4 + `t3_ask_split`) | `panels.py` (strip band, bottom panel) | `slot.py` (panel centre content slot) | `__init__.py` (hooks + question steps).
**Hooks** (registry id 3): `ask_config` = `t3_ask_config` (style + layout mode + modules in one call; used by saved designs and tests), `ask_cards`, `caption_style` = `t3_caption_style`, `build_background` = `t3_build_static_layers` (-> `t3_layout_prepare` when layout is on), `build_items` = `t3_build_items`, `prepare_layers` = `t3_prepare_card_layers` (floating video cards + slot media clips + split video clips). The interview itself is `mt.templates._interactive_t3` (generic questions live in `mt.ask`); `recap_line` prints the modules that are on.
**Question flow**: template -> 1 video -> 2 SRT(s) -> 3 identity / header / footer -> 4 headline -> 5 frame style (named STYLE can be saved here) -> 6 layout mode AUTO / MANUAL (+ events) -> 7 chapters -> 8 captions -> 9 floating cards -> 10 strip -> 11 panel (gallery, slot, checklist) -> 12 split -> 13 texts / elements / template layers / video layers -> 14 output + quick test -> recap -> "Start rendering?". Enter everywhere = a valid default video.
**`cfg["t3"]` keys**: style: accent, show_bg, watermark, show_header, name1, name2, roles[3], tagline, show_footer, footer, signature, frame_style, frame_skew, video_fit, show_headline, headline[3], headline_colors[3], headline_underline, tag_lines[3], fonts{role: path} | chapters_on, chapters[{start|trigger, label, num}], chapter_anim, chapter_anim_dur | cards_on, cards[{media, label, slot, start|trigger, hold}], card_rot, card_anim_dur | layout{on, mode auto|manual, start, trans, events[{at|trigger, state}]} | strip{on, sets[...]} | panel{on, start|trigger, end, left_title, thumbs, right_title, rows, reveal...} | slot{on, title, icon, anim, blocks[...]} | split{on, merge, segments[{start|trigger, end|hold, media, mode}]}.
**Robustness rules**: nothing may raise on bad user data - a missing image / icon / element / video layer / card media is dropped or replaced by a gray picture with one `[!]` line; a trigger phrase not found is reported once and skipped (`t3_warn`); a block timed after the end of the video is simply not shown; overlapping layout events are serialised (each transition lasts `trans`); missing fonts fall back with a message naming the file for `fonts/`; numpy is NOT needed by Template 3; any input aspect ratio is fitted (fill / fit), never stretched.
