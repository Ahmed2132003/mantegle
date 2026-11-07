## P1 - T4 skeleton (assumed task number)
- DONE: mt/templates/t4/{__init__,cfg}.py; registry id 5 'Template 4'; _interactive_t4, _SAVED_LABEL[5], recap_line branch; render.py prepare_layers guard (2,3,5); tools/mt_t4_quick.py (9/9 PASS); selftest check 43 renumbered (saved templates now start at 6).
- Public: t4_cfg, t4_canvas, T4_DEFAULTS, T4_MODULES, t4_ask_config, t4_ask_cards, t4_caption_style, t4_build_static_layers, t4_build_items. Comment-only edit in montage.py.
- cfg['t4'] keys: canvas_mode auto|reels|youtube, fit fill|fit, backdrop{type:color,value}, frame/nameplate/tags/tiles/cards/scenes/split/broll {on:False}; unknown keys survive.
- t4_build_static_layers forces video_box = full canvas and derives canvas from canvas_mode + video shape if a job has none.
- Verified: mt_quick T1/T2 goldens diff 0.0; mt_t3_quick 49/50 (T3-6 fails identically on the untouched zip: missing fonts here); full selftest = same 2 pre-existing fails (26 timing, T3-6) + check 43 fixed. Stills: out/t4/p1_reels.png, p1_youtube.png (fit + #112233 letterbox on reels, fill on youtube).
- ENV: no arabic-reshaper/python-bidi here; ran with identity stub modules on PYTHONPATH (outside the project). Real packages on your machine = no stubs needed.
- GAPS: no t4_warn yet; saved T4 designs map to Custom in ask._saved_templates (only ids 2,3 mapped); render_still needs cfg['canvas'] present (ask flow always stores it).

## P2 - base video modes + backdrops (assumed task number, ref R3)
- DONE: fill (cover) / fit (centred whole video) via the full-canvas video_box; backdrops colour / image / blur (fit only; fill never shows one). Questions in t4_ask_config (called by _interactive_t4): canvas, fill|fit, then backdrop type + colour / image / blur strength 1-10.
- Files: t4/base.py (t4_apply_backdrop, t4_blur_params, t4_blur_filter, t4_blur_still), t4/warn.py (t4_warn, t4_warn_reset - closes the P1 gap), cfg.py backdrop = {type color|image|blur, value, path, strength}.
- render.py (guarded template_id == 5, 3 spots): build_ffmpeg_cmd takes the blur from cfg['_t4_blur'] (extra split output [rb] -> 1/8-size cover scale+crop, boxblur lr:2, scale up -> [bg]; input 0 stays an unused colour so numbering is unchanged); render_still draws the PIL twin. Other ids: byte-identical command.
- Verified: tools/mt_t4_quick.py 22/22 (T4-2: 9:16 on 16:9 fit -> columns 656-1262, black sides; 16:9 on 9:16 fit -> band 656-1263; fill covers both canvases; blur sides lit+smooth, video column unchanged; image + missing image (1 warning); --still blur on both canvases). mt_quick T1/T2 diff 0.0; mt_t3_quick 49/50 (T3-6 = pre-existing). Stills: out/t4/p2_{youtube,reels}_fit_{black,blur}.png vs R3: same layout (video centred, pure black sides).
- Remaining diffs vs R3: R3's clip is ~4:5 not 9:16 (aspect is the clip's own); captions / glow in R3 are a later task. Blur look differs slightly between ffmpeg boxblur and the still's PIL BoxBlur.
- GAPS: blur has no dim / tint option; blur backdrop is built per render (not cached) - cost is small (1/8-size).

## P3 - T4 kit (assumed task number; refs R1 / R5 / R10)
- DONE: t4/kit.py (334 lines) + t4/kit_icons.py (169; vector icons + soft_erode). Additive only: no generic file touched.
- Public (kit): PALETTE{cyan,blue,yellow,glass=(6,16,40,199),white}, chamfer_rect(size, cut|4-tuple) -> mask, neon_stroke(mask, color, width, glow), glass_panel(size, radius, tint, border, cut=0, border_w, glow), connector(points, color, end_dot True|'both'|'start'|False, width, glow), hex_badge(size, icon_name, color, glow), hazard_stripes(size, angle, color, glow, stripe, gap), icon(name, size, color), neon_icon(name, size, color, glow), kit_paste(base, sprite, x, y), kit_sheet(out_png). CLI: python -m mt.templates.t4.kit out.png
- Sprite convention: RGBA incl. glow margin; sprite.info["origin"] = where local (0,0) sits; kit_paste() aligns it. Masks = mt.draw masks.
- Icons: ICON_NAMES = code laptop phone gear globe database server cloud bulb chip shield. Reused _draw_icon (at 4x): code, phone, chip, shield. Own vectors: laptop gear database server cloud(+upload arrow) bulb globe (old globe clogged at 96 px). Unknown name -> t4_warn + empty icon. No cfg keys.
- Verified: out/t4/kit_sheet.png viewed + zoomed (crisp edges, soft glow, smooth icons at 96/48/32/24 px); bad input never raises; mt_t4_quick 22/22. mt_quick / mt_t3_quick not re-run (no existing file changed).
- ENV: ran with identity stubs for arabic-reshaper / python-bidi (outside the project).
- GAPS: no Arabic / text helper in the kit (later task); glow is blur based (no additive blend); R1's tapered neon "swoosh" lines are not covered.

## P4 - T4 timing (assumed task number)
- DONE: t4/timing.py (pure, no drawing) + 9 unit checks 'T4-3' in tools/mt_t4_quick.py (31/31 PASS; only the new checks were run + the existing T4-1/2 ones).
- Public: t4_time(entry, cues, duration, default_hold) -> (start, end) | None; t4_stagger(n, step) -> [0, step, ...]; t4_ask_when(prompt, default_hold, key=None) -> {"start", "hold"} | {"trigger", "hold"}; t4_warn / t4_warn_reset re-exported from t4/warn.py (already existed since P2 - one message set, so no duplicate prints).
- Rules: start = trigger (find_trigger; cues = one cue list OR a list of streams, first stream with a hit wins) else `start`; end = `end` (must be > start) else start + `hold` else start + default_hold (None -> video end). start >= duration -> None; end clamped to duration; negative start -> 0; numbers or '0:45' / '3s' strings; junk never raises (one t4_warn, None).
- Trigger missing + start given -> start is used (one warning); missing and no start -> None (one warning). No cfg keys.
- GAPS: no offset / pre-roll option; windows shorter than 0.05 s are dropped; t4_ask_when is not wired into any module yet.

## P5 - T4 caption style 'pill' (assumed task number, ref R2; R9 for the reels height)
- DONE: t4/captions.py (~290 lines). t4_caption_style (registry hook, re-exported by t4/__init__) asks: style (1 Pill | 2 Plain = the classic ask_caption_style) -> font -> size -> text colour -> keyword colour (default #FFC21A) -> underline glow colour (#19D3FF) -> keywords -> word-by-word / phrases (+ words per group / max words) -> y% -> animation + duration. t4_build_items now returns t4_caption_items(cfg, duration).
- Stream keys: t4_style "pill", ref "canvas", font, size, color, hl_color, neon, keywords, mode words|phrase, words_per_group / max_words, y_pct (None = default), anim, anim_dur. No cfg["t4"] keys.
- Look: dark glass pill (alpha ~0.8, gradient), thin neon underline on the bottom edge (blue wide + cyan core, faded at both ends, built with kit.connector), white bold text, keyword = hl colour, x1.18 size + soft glow. Regular (non-bold) font -> thin same-colour stroke = faux bold. Pill radius ~0.36 size, <= 2 lines (shrinks to 50 % of the size, then stops).
- Geometry (px at short side 1080, scaled for other canvases): pill width <= 84 % of the canvas width; y_pct = the PILL'S BOTTOM EDGE in % of the canvas height, grows upward; defaults reels 84 (R9), youtube 91.5 (R2); never closer than 48 px to the canvas edge. Size default 56 (40 for 2nd+ streams).
- Reuse: stream_groups (parse_markup + keyword matching + grouping), t4_tokens = parse_markup + apply_keywords, visual_order + shape (word-level bidi, same as make_rich_sprite), kit.connector / kit_paste. make_rich_sprite itself is NOT used (one size per sprite, no glow).
- render.py: ONE guarded line (generic caption loop skips t4_style == "pill", next to t3_style). Other templates: same behaviour (T1 diff 0.0).
- Verified: 'T4-4' in tools/mt_t4_quick.py (12 checks: tokens, 84 % width + bottom edge + safe margin on both canvases for an Arabic and an English SRT, drawn once via build_items, keywords by list and *stars*, wrap / shrink, missing SRT / font / junk values warn once, no canvas, question flow pill and plain) -> 43/43. Stills (--still, Tajawal-Bold, real arabic-reshaper + python-bidi) on 1920x1080 and 1080x1920 for Arabic, English, mixed AR/EN and long 2-line cues, viewed: joined RTL letters, keyword on the correct end, balanced lines, pill inside 84 %.
- Bug caught by the checks: a '%' in the y-position question crashed the prompt (fixed: f-string).
- Regression: mt_quick T1 diff 0.0; T2 diff 0.074-0.114 - identical with the ORIGINAL render.py (A/B), so not from this task (env / earlier state). mt_t3_quick 49/50 (T3-6 = pre-existing, same as P1).
- ENV: pip works here -> real arabic-reshaper + python-bidi installed (no stubs needed for these runs). Test font Tajawal-Bold.ttf from google/fonts, kept outside the project (put Cairo / Tajawal Bold in fonts/ on your machine).
- GAPS: a mixed AR/EN line whose first word is Latin is laid out LTR (is_rtl_text rule, same as every other caption style); a 2nd pill stream needs its own y_pct (no automatic stacking); no word-by-word keyword pop; the underline is a fixed 80 % of the pill width.
