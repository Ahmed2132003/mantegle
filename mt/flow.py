"""mt.flow - CLI plumbing used by the thin entry script montage.py: error guard + recap/confirm/save step."""
import os
import sys
import subprocess
from pathlib import Path
import json

from mt.common import _save_defaults, get_template, yn
from mt.captions import caption_streams, parse_srt, stream_groups
from mt.templates import recap_line


def guarded(run):
    """Runs run() and turns expected problems into one readable line instead of a traceback."""
    try:
        run()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
    except SystemExit:
        raise
    except subprocess.CalledProcessError as e:
        if os.environ.get("MONTAGE_DEBUG"):
            raise
        print(f"[!] An external tool failed ({Path(str(e.cmd[0])).name}, exit {e.returncode}). "
              f"Run with MONTAGE_DEBUG=1 for details.")
        sys.exit(1)
    except (ValueError, OSError, KeyError, RuntimeError, ImportError, TypeError) as e:
        if os.environ.get("MONTAGE_DEBUG"):
            raise
        msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        if isinstance(e, KeyError):
            msg = f"the job/settings are missing the field {e}"
        print(f"[!] {msg}   (MONTAGE_DEBUG=1 shows the full traceback)")
        sys.exit(1)


def recap_and_confirm(cfg, mode):
    """Interactive path: print the summary + recap, ask 'Start rendering?', save <output>_job.json and the defaults.
    Returns False when the user cancels."""
    n_cap = sum(len(stream_groups(parse_srt(c["srt"]), c)) for c in caption_streams(cfg))
    print("\n" + "-" * 60)
    print(f" Template   : {get_template(cfg)['name']} - {get_template(cfg)['desc']}")
    print(f" Canvas     : {cfg['canvas'][0]}x{cfg['canvas'][1]}")
    vb = cfg["video_box"]
    print(f" Video box  : {vb['w']}x{vb['h']} at ({vb['x']},{vb['y']}) [{vb['mode']}]")
    print(f" Background : {cfg['background']['type']}")
    n_cards = (len((cfg.get("t2") or {}).get("cards", [])) if cfg.get("template_id") == 2 else
               len((cfg.get("t3") or {}).get("cards", [])) if cfg.get("template_id") == 3 else len(cfg.get("cards", [])))
    print(f" Layers {len(cfg.get('layers', []))} | Texts {len(cfg['texts'])} | Cards {n_cards}"
          f" | Elements {len(cfg['elements'])} | Caption groups {n_cap}")
    print(f" Output     : {cfg['output']}" + (f"   (test: first {cfg['preview']}s)" if cfg.get("preview") else ""))
    print(f" Arabic text engine: {mode}")
    print("-" * 60)
    print("Recap: " + recap_line(cfg))
    if not yn("Start rendering?", default=True):
        print("Cancelled.")
        return False

    job_path = Path(cfg["output"]).with_name(Path(cfg["output"]).stem + "_job.json")
    try:
        job_path.parent.mkdir(parents=True, exist_ok=True)
        job_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"(settings saved to {job_path.name} - re-run later with:  python montage.py --job \"{job_path}\")")
    except Exception:
        pass
    _save_defaults()
    return True
