"""
Static audit for the bug classes that actually showed up in this codebase.

    python audit_codebase.py [path/to/core]

Pure source inspection -- no MetaTrader5, no network, no imports of the
code under test. Safe to run anywhere, any time.

Every check here exists because the corresponding bug was found by hand,
in a payload, after it had been live for a while. The point is to make
the next instance surface without anyone having to notice it by eye.

    1. IGNORED PARAMETERS
       A parameter accepted and never referenced. Found live:
       get_zone_adjusted_score() had no volume_confirmed parameter and
       passed a hardcoded False into a penalty that needed it, making
       zone grade A permanently unreachable.

    2. DEAD FUNCTIONS
       Defined, complete, called from nowhere. Found live:
       get_zone_volume_profile() computed exactly the volume_confirmed
       that (1) was missing -- the producer and the consumer both
       existed and were never connected.

    3. RELATIONSHIP COMMENTS
       A constant whose comment explains it in terms of another
       constant. Found live: SMC_MIN_CONFLUENCE_SCORE = 40, commented
       "< 2/5 signals", while SMC_TOTAL_POSSIBLE_SIGNALS had grown to 6
       -- silently moving the gate from 2 signals to 3.

    4. DUPLICATE CONSTANTS
       The same constant defined in two modules. Found live:
       _NORMAL_ATR_RANGES in both config and calculations, with
       asset_analysis importing the name from both -- the second import
       silently winning and the first becoming a decoy.

    5. BYPASSED GETTERS
       A timeframe/symbol-aware getter exists, but a call site passes a
       hardcoded value instead. Found live: classify_trading_regime()
       used period=20, std_dev=2.0 while get_bb_period/get_bb_std
       resolve 50/2.5 on M1 -- two different Bollinger bandwidths in the
       same payload, one of them feeding the regime weights.

Findings are reported, never auto-fixed. Most are benign (uniform
dispatch interfaces, intentional defaults); this narrows where to look,
it does not decide anything.
"""

import ast
import os
import re
import sys
from collections import defaultdict

SKIP_PARAMS = {"self", "cls", "kwargs", "args", "_"}


def py_files(root):
    if os.path.isfile(root):
        return [root]
    return sorted(
        os.path.join(dp, f)
        for dp, _, fs in os.walk(root)
        for f in fs
        if f.endswith(".py") and "__pycache__" not in dp
    )


def parse(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        return src, ast.parse(src)
    except (SyntaxError, OSError) as e:
        print(f"  ! could not parse {path}: {e}")
        return None, None


def ignored_parameters(files):
    out = []
    for path in files:
        src, tree = parse(path)
        if tree is None:
            continue
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            params = [a.arg for a in fn.args.args + fn.args.kwonlyargs
                      if a.arg not in SKIP_PARAMS]
            used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            used |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            for kw in [k for k in ast.walk(fn) if isinstance(k, ast.keyword)]:
                if isinstance(kw.value, ast.Name):
                    used.add(kw.value.id)
            unused = [p for p in params if p not in used]
            if unused:
                out.append((path, fn.lineno, fn.name, unused))
    return out


def dead_functions(files):
    defined, called = {}, set()
    for path in files:
        src, tree = parse(path)
        if tree is None:
            continue
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            # module-level only; methods are reached via instances
            if not any(fn in getattr(p, "body", []) for p in [tree]):
                continue
            if fn.name.startswith("__"):
                continue
            defined[fn.name] = (path, fn.lineno)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name):
                    called.add(f.id)
                elif isinstance(f, ast.Attribute):
                    called.add(f.attr)
            elif isinstance(node, ast.Name):
                called.add(node.id)      # passed as a reference
            elif isinstance(node, ast.Attribute):
                called.add(node.attr)
    # Entry points, operational tooling and public API will always look
    # "dead" here because their callers live outside the audited tree.
    # Filtering them keeps the signal readable -- the interesting hits are
    # ordinary helpers, especially ones that duplicate a live private copy.
    NOISE = re.compile(
        r"^(analyze_institutional_signal|attach_outcome|explain_|"
        r"reset_|clear_|warmup_|force_refresh_|get_.*_(stats|health|status)$|"
        r"update_.*_thresholds$)"
    )
    return [(p, ln, n) for n, (p, ln) in sorted(defined.items())
            if n not in called and not NOISE.match(n)]


RELATION = re.compile(r"[A-Z_]{4,}|\b\d+\s*/\s*\d+\b|\bout of\b|\bmatches\b|\bsame as\b")
CONST_LINE = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*=\s*([\d.]+)\s*#\s*(.+)$")


def relationship_comments(files):
    out = []
    for path in files:
        src, _ = parse(path)
        if src is None:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            m = CONST_LINE.match(line.strip("\r"))
            if m and RELATION.search(m.group(3)):
                out.append((path, i, m.group(1), m.group(2), m.group(3).strip()))
    return out


def duplicate_constants(files):
    seen = defaultdict(list)
    for path in files:
        src, _ = parse(path)
        if src is None:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            m = re.match(r"^([A-Z_][A-Z0-9_]{3,})\s*=\s*[\{\[\d\"']", line.strip("\r"))
            if m:
                seen[m.group(1)].append((os.path.basename(path), i))
    return {k: v for k, v in seen.items() if len({f for f, _ in v}) > 1}


GETTER = re.compile(r"^def (get_[a-z_]+)\((?:[^)]*)(timeframe|symbol)")


def bypassed_getters(files):
    getters = {}
    for path in files:
        src, _ = parse(path)
        if src is None:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            m = GETTER.match(line.strip("\r"))
            if m:
                getters[m.group(1)] = (os.path.basename(path), i)
    # a getter with exactly one call site is suspicious: something else
    # probably hardcodes what it resolves
    counts = defaultdict(int)
    for path in files:
        src, _ = parse(path)
        if src is None:
            continue
        for g in getters:
            counts[g] += len(re.findall(rf"\b{g}\s*\(", src))
    return [(g, getters[g], counts[g] - 1) for g in sorted(getters)
            if counts[g] - 1 <= 1]


def section(title, note):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}\n{note}\n")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ("core" if os.path.isdir("core") else ".")
    files = py_files(root)
    print(f"Auditing {len(files)} file(s) under {os.path.abspath(root)}")

    section("1. IGNORED PARAMETERS",
            "Accepted and never referenced. Benign for uniform dispatch\n"
            "interfaces; a real gap when the parameter names something the\n"
            "function is supposed to honour.")
    rows = ignored_parameters(files)
    for p, ln, n, u in rows:
        print(f"  {os.path.basename(p)}:{ln}  {n}()  ->  {', '.join(u)}")
    print(f"\n  {len(rows)} found")

    section("2. DEAD MODULE-LEVEL FUNCTIONS",
            "Defined and never referenced anywhere in the audited tree.\n"
            "Entry points and operational tooling are filtered out -- their\n"
            "callers are outside this tree. Watch especially for a public\n"
            "name shadowed by a live private copy (get_x vs _get_x): that is\n"
            "the duplicate-constant failure in function form.")
    rows = dead_functions(files)
    for p, ln, n in rows:
        print(f"  {os.path.basename(p)}:{ln}  {n}()")
    print(f"\n  {len(rows)} found")

    section("3. CONSTANTS WITH RELATIONSHIP COMMENTS",
            "The comment asserts a relationship the code does not enforce.\n"
            "Verify each against the constant it references.")
    rows = relationship_comments(files)
    for p, ln, n, v, c in rows:
        print(f"  {os.path.basename(p)}:{ln}  {n} = {v}")
        print(f"      # {c[:90]}")
    print(f"\n  {len(rows)} found")

    section("4. CONSTANTS DEFINED IN MORE THAN ONE MODULE",
            "Two copies agree until one is edited. If both are imported\n"
            "into the same module, the second silently wins.")
    dupes = duplicate_constants(files)
    for k, v in sorted(dupes.items()):
        print(f"  {k}")
        for f, ln in v:
            print(f"      {f}:{ln}")
    print(f"\n  {len(dupes)} found")

    section("5. GETTERS WITH ~NO CALL SITES",
            "A timeframe/symbol-aware getter that nothing calls usually\n"
            "means the value it resolves is hardcoded somewhere instead.")
    rows = bypassed_getters(files)
    for g, (f, ln), n in rows:
        print(f"  {g}()  defined {f}:{ln}  ->  {n} call site(s)")
    print(f"\n  {len(rows)} found")

    print("\nNothing here is automatically a bug. Each is a place where two\n"
          "things that should agree might not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())