"""
Compare the two parallel configuration modules for value drift.

    python compare_configs.py [core_dir]

The audit found ~130 constants defined in BOTH core/config.py and
core/asset_analysis_config.py. Two copies of the same constant agree
until one of them is edited -- at which point whichever module a given
importer happens to read decides its behaviour, silently.

This script answers three questions without importing or running
anything:

    1. Which constants exist in both, and do their VALUES still match?
    2. Which modules import from which config?
    3. Does any single module import from both?

Only literal values are compared (numbers, strings, dicts, lists, tuples,
booleans, None). Computed or derived values are reported as
NOT-COMPARABLE rather than guessed at.
"""

import ast
import os
import re
import sys

CONFIG_A = "config.py"
CONFIG_B = "asset_analysis_config.py"


def literal_constants(path):
    """Every module-level NAME = <literal> in the file."""
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
    except (SyntaxError, OSError) as e:
        print(f"  ! cannot parse {path}: {e}")
        return out, {}
    noncomparable = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        name = tgt.id
        if not re.match(r"^_?[A-Z][A-Z0-9_]*$", name):
            continue
        try:
            out[name] = (ast.literal_eval(node.value), node.lineno)
        except (ValueError, SyntaxError, TypeError):
            noncomparable[name] = node.lineno
    return out, noncomparable


def function_bodies(path):
    """Every module-level function, normalised to its source lines.

    compare_configs originally checked only literal constants -- but a
    config can also export FUNCTIONS, and veto_engine.py imports two of
    them (get_volume_threshold, get_wick_reversal_ratio) from config.py
    while nine other modules import same-named functions from
    asset_analysis_config.py. Identical constants do not guarantee
    identical logic around them.
    """
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read().replace("\r\n", "\n")
        tree = ast.parse(src)
    except (SyntaxError, OSError):
        return out
    lines = src.split("\n")
    doc_marks = (chr(34) * 3, chr(39) * 3)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            end = getattr(node, "end_lineno", None) or node.lineno
            body = [l.rstrip() for l in lines[node.lineno - 1:end]
                    if l.strip() and not l.strip().startswith("#")]
            body = [l for l in body if not l.strip().startswith(doc_marks)]
            out[node.name] = (body, node.lineno)
    return out


def import_map(core_dir):
    """module -> set of config modules it imports from.

    Walks the WHOLE project, not just core/. The first version of this
    scan only listed core/, which is how the question "is it safe to
    delete config.py" got answered with half the evidence -- execution.py,
    firebase_service.py, thread_monitor.py, mt5_connector.py and others
    sit outside core/ and can import it just as easily. A module that
    imports a config from two directories up is exactly as bound to it
    as a sibling is.
    """
    root = os.path.abspath(os.path.join(core_dir, ".."))
    # if core_dir isn't nested, scan it directly
    if not os.path.isdir(os.path.join(root, os.path.basename(core_dir))):
        root = os.path.abspath(core_dir)

    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", ".git", ".venv", "venv", "node_modules")]
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            if fn in (CONFIG_A, CONFIG_B) and os.path.dirname(rel) in ("core", ""):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    src = fh.read()
            except OSError:
                continue
            srcs = set()
            if re.search(r"^\s*from\s+(\w+\.)*config\s+import", src, re.M) or \
               re.search(r"^\s*import\s+(\w+\.)*config\b", src, re.M):
                srcs.add(CONFIG_A)
            if re.search(r"^\s*from\s+(\w+\.)*asset_analysis_config\s+import", src, re.M) or \
               re.search(r"^\s*import\s+(\w+\.)*asset_analysis_config\b", src, re.M):
                srcs.add(CONFIG_B)
            if srcs:
                out[rel.replace("\\", "/")] = srcs
    return out


def fmt(v):
    s = repr(v)
    return s if len(s) <= 60 else s[:57] + "..."


def main():
    core = sys.argv[1] if len(sys.argv) > 1 else ("." if os.path.exists(CONFIG_A) else "core")
    pa, pb = os.path.join(core, CONFIG_A), os.path.join(core, CONFIG_B)
    for p in (pa, pb):
        if not os.path.isfile(p):
            print(f"Not found: {p}")
            return 1

    a, a_nc = literal_constants(pa)
    b, b_nc = literal_constants(pb)
    shared = sorted(set(a) & set(b))

    print(f"{CONFIG_A}: {len(a)} literal constants")
    print(f"{CONFIG_B}: {len(b)} literal constants")
    print(f"defined in BOTH: {len(shared)}\n")

    drifted, same = [], []
    for k in shared:
        (va, la), (vb, lb) = a[k], b[k]
        (same if va == vb else drifted).append((k, va, la, vb, lb))

    print("=" * 70)
    print("VALUES THAT HAVE DRIFTED APART")
    print("=" * 70)
    if not drifted:
        print("\n  None. Every shared constant still holds the same value.")
        print("  That is the BEST case and it is temporary -- the next edit to")
        print("  either file breaks it, with no error.\n")
    else:
        print(f"\n  {len(drifted)} constant(s) now disagree. Whichever module an")
        print("  importer reads decides its behaviour.\n")
        for k, va, la, vb, lb in drifted:
            print(f"  {k}")
            print(f"      {CONFIG_A}:{la}  = {fmt(va)}")
            print(f"      {CONFIG_B}:{lb}  = {fmt(vb)}")
        print()

    fa, fb = function_bodies(pa), function_bodies(pb)
    shared_fns = sorted(set(fa) & set(fb))
    fn_drift = [(k, fa[k][1], fb[k][1]) for k in shared_fns if fa[k][0] != fb[k][0]]

    print("=" * 70)
    print("FUNCTIONS DEFINED IN BOTH CONFIGS")
    print("=" * 70)
    print("\n  %d shared, %d with differing bodies\n" % (len(shared_fns), len(fn_drift)))
    for k, la, lb in fn_drift:
        print("  %s()" % k)
        print("      %s:%d  differs from  %s:%d" % (CONFIG_A, la, CONFIG_B, lb))
    if shared_fns and not fn_drift:
        print("  All shared function bodies are identical (docstrings ignored).")
    print()

    print("=" * 70)
    print("WHO IMPORTS WHICH CONFIG  (whole project, not just core/)")
    print("=" * 70 + "\n")
    imports = import_map(core)
    both = {m: s for m, s in imports.items() if len(s) > 1}
    only_a = sorted(m for m, s in imports.items() if s == {CONFIG_A})
    only_b = sorted(m for m, s in imports.items() if s == {CONFIG_B})

    print(f"  imports {CONFIG_B} only : {len(only_b)}")
    for m in only_b:
        print(f"      {m}")
    print(f"\n  imports {CONFIG_A} only : {len(only_a)}")
    for m in only_a:
        print(f"      {m}")
    print(f"\n  imports BOTH : {len(both)}")
    for m in sorted(both):
        print(f"      {m}   <-- second import wins for any shared name")

    print("\n" + "=" * 70)
    print("READ THIS")
    print("=" * 70)
    if only_a and only_b:
        print(f"""
  {len(only_a)} module(s) read {CONFIG_A} and {len(only_b)} read {CONFIG_B}.
  They are running on SEPARATE copies of the same settings. Editing one
  config changes the behaviour of only half the system, and nothing
  reports the split.

  Before changing any threshold, check which config the code path that
  consumes it actually imports.""")
    elif only_b and not only_a:
        print(f"""
  Nothing imports {CONFIG_A}. It is a complete, uncalled duplicate --
  a decoy. Edits made there have no effect anywhere, which is its own
  hazard: it looks exactly like the live config.""")
    elif only_a and not only_b:
        print(f"""
  Nothing imports {CONFIG_B}. Every change made to that file this
  session -- zone grade thresholds, SMC confluence gate, adaptive band
  switches, ATR touch fraction -- is INERT. They must be reapplied to
  {CONFIG_A} to take effect.""")

    if a_nc or b_nc:
        print(f"\n  Not compared (non-literal values): "
              f"{len(a_nc)} in {CONFIG_A}, {len(b_nc)} in {CONFIG_B}")
    return 0


if __name__ == "__main__":
    sys.exit(main())