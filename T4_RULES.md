# T4 RULES

1. Scope: Template 4 = registry id 5, package mt/templates/t4/, config namespace cfg['t4']. Never change behaviour of ids 1-4. Generic files (render.py, draw.py, captions.py, ask.py, common.py) get only minimal guarded edits (if template_id == 5) or purely additive helpers.
2. Concept: the user's video is the BASE and fills the canvas. Everything else is an overlay layer. No opaque plate over the video centre unless the module is an explicit takeover (split, b-roll).
3. Canvases: reels 1080x1920 and youtube 1920x1080 (short side always 1080). Author layouts in pixels, safe margin 48 px. Every visual module must work and be checked on BOTH canvases.
4. Size: new files <= 500 lines, functions <= 80 lines, one responsibility per file, names t4_*.
5. Robustness: normalisers never raise; missing media -> gray placeholder + one t4_warn line; trigger phrase not found -> warn once and skip.
6. Arabic/RTL: use mt.fonts.shape and is_rtl_text; test every text module with Arabic and English strings.
7. Performance: static design goes to the foreground plate (cfg['_t2_fg']) or one sprite Item; cache plates; no per-frame Python drawing beyond Item animations.
8. Verification per task: (a) tools/mt_quick.py, tools/mt_t3_quick.py, tools/mt_t4_quick.py pass; (b) render --still on both canvases to out/t4/<task>_<canvas>.png, VIEW the images, compare with the cited R-image, fix once, re-check once, record remaining differences in T4_NOTES.md. Full --selftest only in P0, P22, P23.
9. Finish: append <= 12 lines to T4_NOTES.md (done / public functions / cfg keys / known gaps), git commit 'T4-Pn' if a repo exists. Do NOT start the next task. If running out of room, write RESUME HERE + the exact next step in T4_NOTES.md.
