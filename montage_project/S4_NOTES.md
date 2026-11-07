# S4 notes - templates moved, thin entry, docs
Base: the S3 state (the zip attached to the S4 request was an older snapshot: 5839-line montage.py, mt/ without captions/split/render/ask/selftest).
- mt/templates/t1_tech.py (T1 + Custom flow), t2_lime.py (T2, 1724 lines: over ~1500, NOT split), __init__.py (registry fill, `choose_template`, `interactive`, `_interactive_core`, `recap_line`).
- `TEMPLATE_REGISTRY` dict + `get_template` stay in mt.common (render.py dispatches without importing templates); mt.templates fills it.
- Selector: 1 T1, 2 T2, 3 Template 3 (coming soon: message + asks again; `get_template` raises a clean RuntimeError for a job asking for it), 4 Custom; saved templates from 5. Custom was id 3 before: old jobs with template_id 3 are migrated to 4 in `_load_job` (only behavior-visible change: the id number).
- montage.py = docstring + argparse + dispatch (143 lines). New mt/flow.py: `guarded` (old `main` error wrapper) and `recap_and_confirm` (old recap/save block of `_main`), code moved verbatim. All flags unchanged.
- find_trigger moved to mt/captions.py (shared by T1 and T2). selftest: host binding removed, imports templates directly; docstring check reads montage.py via ast.
- tools mt_quick / mt_make_golden_t2 / mt_s1_jobtests use a small shim (`M`) over mt.* instead of `import montage`.
- Check 26 (timing T1 vs T2, ratio <= 1.3x) is machine-load sensitive (known from the baseline).
