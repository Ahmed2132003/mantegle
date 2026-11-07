# S3 notes - ask + selftest moved
Lines: montage.py 4138 -> 2320. see line counts in the report. Backup of the pre-S3 entry script is not included.
## Decisions
- mt/ask.py got: POS_LINE c_pos ask_pos ask_layers ask_texts ask_elements ask_video_layers + saved-template IO (list_templates maybe_save_template _PRESET _tpl_template_id _saved_templates) + choose_template (selector; reads only mt.common's registry).
- NEW helpers (verbatim extractions from `_interactive_core`, which stays in montage because it calls `_interactive_t2`/t2_* - S4): ask_video_path(), ask_srt_paths(parse_srt), ask_output_options(cfg). parse_srt is passed in because mt.captions imports mt.ask (no cycle, no lazy import).
- Template-specific questions (ask_cards, ask_template, ask_hud_template, t1/t2_ask_*, _interactive_t2) stay in montage.py for S4. `interactive`, `_interactive_core`, `recap_line` stay too.
- selftest: `SELFTEST_CHECKS` + `@selftest_check("name")` (mt/selftest.py). Registered, in order: core 2-7, T2 static, T2 dynamic, T2 cards, T2 about, T2 panel, T2 4c, 4d. Check 1 (env gate) stays inline in run_selftest because it can stop the run. A crashing check is recorded as FAIL instead of aborting. Template modules register by importing `selftest_check` (registration order = import order).
- Transitional host binding: selftest still needs ~19 t2_* names defined in montage.py. They are listed in `_HOST_NAMES` and bound into mt.selftest's globals at the start of run_selftest (`_bind_host`), instead of a circular `from montage import`. S4: delete `_HOST_NAMES`/`_bind_host` and import from the template modules.
- TEMPLATES_DIR is now read by mt.ask, so the selftest patches `mt.ask.TEMPLATES_DIR` (was globals()["TEMPLATES_DIR"]).
- `__file__` -> `_SCRIPT = BASE / "montage.py"`; check 1 compiles montage.py + all mt/*.py; check 46 py_compiles montage.py + mt/*.py and checks montage's docstring via the host module.
