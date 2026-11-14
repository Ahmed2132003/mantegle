#!/usr/bin/env python3
"""AST audit of montage.py -> JSON (read-only). Usage: mt_audit.py montage.py out.json"""
import ast, sys, json, re
src = open(sys.argv[1], encoding="utf-8").read()
lines = src.splitlines()
tree = ast.parse(src)
items = []  # top-level defs/classes/assigns
def tnames(t):
    out = []
    for n in ast.walk(t):
        if isinstance(n, ast.Name): out.append(n.id)
    return out
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
        kind = "class" if isinstance(node, ast.ClassDef) else "def"; names = [node.name]
    elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        tg = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [n for t in tg for n in tnames(t)]; kind = "global"
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        kind = "import"; names = [(a.asname or a.name).split(".")[0] for a in node.names]
    elif isinstance(node, ast.Try):
        kind = "try"; names = []
        for n in ast.walk(node):
            if isinstance(n, (ast.Import, ast.ImportFrom)): names += [(a.asname or a.name).split(".")[0] for a in n.names]
            if isinstance(n, ast.Assign):
                for t in n.targets: names += tnames(t)
    elif isinstance(node, ast.If):
        kind = "if"; names = []
    else:
        kind = type(node).__name__; names = []
    start = (node.decorator_list[0].lineno if getattr(node, "decorator_list", None) else node.lineno)
    items.append(dict(kind=kind, names=names, start=start, end=node.end_lineno, node=node))
defined = {}
for it in items:
    if it["kind"] in ("def", "class", "global", "try"):
        for n in it["names"]: defined[n] = it
imports = {n for it in items if it["kind"] == "import" for n in it["names"]}
MUT = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
out = []
for it in items:
    node = it["node"]
    own = set(it["names"])
    refs, globs, pathuse, cwd = set(), set(), [], []
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in defined and n.id not in own:
            refs.add(n.id)
        if isinstance(n, ast.Global): globs.update(n.names)
        if isinstance(n, ast.Name) and n.id == "__file__": pathuse.append(n.lineno)
        if isinstance(n, ast.Name) and n.id == "BASE": pathuse.append(n.lineno)
        if isinstance(n, ast.Call):
            f = ast.unparse(n.func)
            if f in ("os.getcwd", "Path.cwd", "os.chdir", "Path"): 
                if f != "Path": cwd.append(n.lineno)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.match(r"^(\./|\.\./|[\w\-]+/[\w\-./]+\.\w+)$", n.value) and not n.value.startswith("http"):
            cwd.append(n.lineno)
    mutable = False
    if it["kind"] == "global":
        v = getattr(node, "value", None)
        mutable = isinstance(v, MUT) or (isinstance(v, ast.Call) and ast.unparse(v.func) in ("set", "dict", "list", "defaultdict", "OrderedDict", "deque"))
    usedimp = sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name) and n.id in imports})
    usedimp += sorted({ast.unparse(n.value).split(".")[0] for n in ast.walk(node) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in imports})
    out.append(dict(kind=it["kind"], names=it["names"], start=it["start"], end=it["end"], n=it["end"] - it["start"] + 1,
                    refs=sorted(refs), globals_stmt=sorted(globs), mutable=mutable, path_lines=sorted(set(pathuse)), cwd_rel_lines=sorted(set(cwd)),
                    imports_used=sorted(set(usedimp)),
                    doc=(ast.get_docstring(node) or "").split("\n")[0][:90] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else "",
                    src=ast.get_source_segment(src, node)[:160].split("\n")[0] if it["kind"] == "global" else ""))
json.dump(out, open(sys.argv[2], "w"), indent=1)
print(len(out), "top-level items")
