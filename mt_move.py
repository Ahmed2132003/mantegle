#!/usr/bin/env python3
"""mt_move.py - move top-level defs/classes/constants between modules using ast + line ranges.

  mt_move.py SRC.py --list                       list movable top-level items (line range, size, deps)
  mt_move.py SRC.py TARGET.py NAME [NAME ...]    move names SRC -> TARGET (creates TARGET, and its package __init__.py)
        --dry-run      show what would happen, write nothing
        --allow-src-deps   permit moved code that uses names still defined in SRC (target then does
                           `from <src> import X`, a circular import - only for temporary/lazy use)
        --no-reexport  do not import the moved names back into SRC (default: compat re-export ON)

Behaviour: the exact source text (including decorators and the comment block directly above) is cut from SRC and
appended to TARGET. Imports the moved code needs (matched by names used, taken from SRC's own import statements,
including try/except import blocks) are added to TARGET. SRC gets `from <target module> import a, b  # moved` at the
position of the first removed item, so every old call site keeps working. Warnings are printed for: `global` rebinding,
BASE/__file__/cwd use, moved names that other SRC code rebinds, and dependencies on SRC-defined names.
Module names are derived from the file paths relative to SRC's folder (mt/common.py -> mt.common).
"""
import ast, sys, argparse, os
from pathlib import Path

def load(path):
    src = Path(path).read_text(encoding="utf-8")
    return src, src.splitlines(keepends=True), ast.parse(src)

def tnames(t):
    return [n.id for n in ast.walk(t) if isinstance(n, ast.Name)]

def top_items(tree, lines):
    """-> list of dict(kind, names, start, end(1-based inclusive, incl. decorators + leading comment block), node)"""
    items = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind, names = "def", [node.name]
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            tg = node.targets if isinstance(node, ast.Assign) else [node.target]
            kind, names = "global", [n for t in tg for n in tnames(t)]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            kind = "import"; names = [(a.asname or a.name).split(".")[0] for a in node.names]
        elif isinstance(node, ast.Try):
            kind = "try"; names = []
            for n in ast.walk(node):
                if isinstance(n, (ast.Import, ast.ImportFrom)): names += [(a.asname or a.name).split(".")[0] for a in n.names]
        else:
            kind, names = type(node).__name__, []
        start = node.decorator_list[0].lineno if getattr(node, "decorator_list", None) else node.lineno
        while start > 1 and lines[start - 2].lstrip().startswith("#") and not lines[start - 2].strip() == "":
            start -= 1          # leading comment block directly above (no blank line between)
        items.append(dict(kind=kind, names=names, start=start, end=node.end_lineno, node=node))
    return items

def used_names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("target", nargs="?"); ap.add_argument("names", nargs="*")
    ap.add_argument("--list", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-src-deps", action="store_true"); ap.add_argument("--no-reexport", action="store_true")
    a = ap.parse_args()
    src_path = Path(a.src).resolve()
    text, lines, tree = load(src_path)
    items = top_items(tree, lines)
    defined = {n: it for it in items if it["kind"] in ("def", "global") for n in it["names"]}
    imp_items = [it for it in items if it["kind"] in ("import", "try") and it["names"]]
    imp_of = {}
    for it in imp_items:
        for n in it["names"]: imp_of.setdefault(n, it)

    if a.list or not a.target:
        for it in items:
            if it["kind"] in ("def", "global"):
                deps = sorted((used_names(it["node"]) & set(defined)) - set(it["names"]))
                print(f"{it['start']:>5}-{it['end']:<5} {it['end']-it['start']+1:>4}  {it['kind']:<6} {','.join(it['names'])[:40]:<40} deps={','.join(deps)[:80]}")
        return
    names = a.names
    if not names: sys.exit("no NAMEs given")
    pick = []
    for n in names:
        it = defined.get(n)
        if not it: sys.exit(f"[!] '{n}' is not a top-level def/class/assignment in {src_path.name}")
        if it not in pick: pick.append(it)
    pick.sort(key=lambda it: it["start"])          # keep original source order (needed for e.g. FFMPEG = _find_tool(..))
    moved = {n for it in pick for n in it["names"]}
    src_mod = src_path.stem
    tgt_path = Path(a.target).resolve()
    rel = tgt_path.relative_to(src_path.parent)
    tgt_mod = ".".join(rel.with_suffix("").parts)
    if tgt_mod.endswith(".__init__"): tgt_mod = tgt_mod[: -len(".__init__")]

    # ---- analysis ------------------------------------------------------------------------------------
    warn = []
    need_imports, src_deps, used_imp = [], set(), set()
    for it in pick:
        for n in used_names(it["node"]):
            if n in moved: continue
            if n in imp_of:
                used_imp.add(n)
                if imp_of[n] not in need_imports: need_imports.append(imp_of[n])
            elif n in defined:
                src_deps.add(n)
        for n in ast.walk(it["node"]):
            if isinstance(n, ast.Global):
                bad = [g for g in n.names if g not in moved]
                if bad: warn.append(f"{it['names'][0]}: `global {', '.join(bad)}` rebinds a name that is NOT moving with it")
            if isinstance(n, ast.Name) and n.id == "__file__": warn.append(f"{it['names'][0]}: uses __file__ (path will change when moved)")
            if isinstance(n, ast.Name) and n.id == "BASE" : warn.append(f"{it['names'][0]}: uses BASE (must stay the montage.py folder)")
            if isinstance(n, ast.Call) and ast.unparse(n.func) in ("os.getcwd", "Path.cwd", "os.chdir"): warn.append(f"{it['names'][0]}: uses cwd")
    # moved names rebound elsewhere in SRC via `global`
    for it in items:
        if it in pick: continue
        for n in ast.walk(it["node"]):
            if isinstance(n, ast.Global):
                for g in n.names:
                    if g in moved: warn.append(f"{it['names'][0] if it['names'] else it['kind']}: rebinds moved global '{g}' -> re-exported copy in SRC goes stale; move this function too")
    if src_deps and not a.allow_src_deps:
        print(f"[!] REFUSED: moved code uses names still defined in {src_path.name}: {sorted(src_deps)}\n"
              f"    Move those first (leaf-first order), or pass --allow-src-deps for a temporary circular import.")
        sys.exit(2)
    if src_deps: warn.append(f"circular import: {tgt_mod} will `from {src_mod} import {', '.join(sorted(src_deps))}`")

    # ---- build target text -----------------------------------------------------------------------------
    chunks = ["".join(lines[it["start"] - 1: it["end"]]).rstrip("\n") + "\n" for it in pick]
    imp_lines = []
    for it in need_imports:
        nd = it["node"]
        if isinstance(nd, (ast.Import, ast.ImportFrom)):      # keep only the names the moved code really uses
            keep = [al for al in nd.names if (al.asname or al.name).split(".")[0] in used_imp or al.name == "*"]
            nd2 = ast.Import(names=keep) if isinstance(nd, ast.Import) else ast.ImportFrom(module=nd.module, names=keep, level=nd.level)
            txt = ast.unparse(ast.fix_missing_locations(nd2))
        else:
            txt = "".join(lines[it["start"] - 1: it["end"]]).rstrip("\n")     # try/except import blocks are copied whole
        if txt.startswith(f"from {tgt_mod} import "): continue      # names already live in the target (came via SRC's re-export line)
        if txt not in imp_lines: imp_lines.append(txt)
    imp_lines.sort(key=lambda l: 0 if l.startswith("from mt.") or l.startswith("from mt import") else 1)   # package-internal first (runs the pip check before PIL)
    if src_deps: imp_lines.append(f"from {src_mod} import {', '.join(sorted(src_deps))}")
    tgt_exists = tgt_path.exists()
    if tgt_exists:
        ttext = tgt_path.read_text(encoding="utf-8"); ttree = ast.parse(ttext); tl = ttext.splitlines(keepends=True)
        tdef = {n for it in top_items(ttree, tl) if it["kind"] in ("def", "global") for n in it["names"]}
        clash = moved & tdef
        if clash: sys.exit(f"[!] already defined in {tgt_path.name}: {sorted(clash)}")
        have = {ast.get_source_segment(ttext, n).strip() for n in ttree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.Try))}
        add = [l for l in imp_lines if l.strip() not in have]
        last_imp = max([n.end_lineno for n in ttree.body if isinstance(n, (ast.Import, ast.ImportFrom))] or [0])
        if not last_imp and ttree.body and isinstance(ttree.body[0], ast.Expr) and isinstance(getattr(ttree.body[0], "value", None), ast.Constant):
            last_imp = ttree.body[0].end_lineno
        new_t = "".join(tl[:last_imp]) + ("\n".join(add) + "\n" if add else "") + "".join(tl[last_imp:]).rstrip("\n") + "\n\n\n" + "\n\n".join(chunks)
    else:
        new_t = f'"""{tgt_mod} - moved from {src_path.name} by tools/mt_move.py"""\n' + "\n".join(imp_lines) + ("\n" if imp_lines else "") + "\n\n" + "\n\n".join(chunks)

    # ---- rewrite source ----------------------------------------------------------------------------------
    first = min(it["start"] for it in pick)
    drop = set()
    for it in pick: drop.update(range(it["start"], it["end"] + 1))
    reexp = f"from {tgt_mod} import {', '.join(sorted(moved))}  # moved by mt_move (compat re-export)\n" if not a.no_reexport else ""
    out = []
    for i, l in enumerate(lines, 1):
        if i == first and reexp: out.append(reexp)
        if i in drop: continue
        out.append(l)
    new_s = "".join(out)
    # collapse >2 consecutive blank lines created by removal
    import re
    new_s = re.sub(r"\n{4,}", "\n\n\n", new_s)

    # ---- report / write ------------------------------------------------------------------------------------
    print(f"{'DRY-RUN ' if a.dry_run else ''}move {sorted(moved)}  {src_path.name} -> {tgt_mod}  ({'append to existing' if tgt_exists else 'new module'})")
    for it in pick: print(f"   lines {it['start']}-{it['end']} ({it['end']-it['start']+1}) {it['names']}")
    print(f"   imports added to target: {[l.splitlines()[0] for l in imp_lines] or 'none'}")
    print(f"   source: -{len(drop)} lines, +{1 if reexp else 0} re-export line")
    for w in warn: print("   WARNING:", w)
    if a.dry_run: return
    new_t_ok = compile(new_t, str(tgt_path), "exec"); new_s_ok = compile(new_s, str(src_path), "exec")   # both must compile
    tgt_path.parent.mkdir(parents=True, exist_ok=True)
    for d in {tgt_path.parent, *[p for p in tgt_path.parents if p != src_path.parent and src_path.parent in p.parents]}:
        init = d / "__init__.py"
        if d != src_path.parent and not init.exists() and tgt_path.name != "__init__.py": init.write_text("", encoding="utf-8")
    tgt_path.write_text(new_t, encoding="utf-8"); src_path.write_text(new_s, encoding="utf-8")
    print("   written; both files compile.")

if __name__ == "__main__":
    main()
