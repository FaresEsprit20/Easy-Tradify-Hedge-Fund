import ast
import importlib
import re
from pathlib import Path

from engine_v2.config_ledger import LEDGER

ROOT = Path(__file__).resolve().parents[2] / "engine_v2"
CATEGORY_FILES = [p for p in (ROOT / "categories").glob("*.py") if not p.name.startswith("_")]


def test_no_category_imports_another_category():
    names = {p.stem for p in CATEGORY_FILES}
    for p in CATEGORY_FILES:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("engine_v2.categories."):
                other = node.module.split(".")[-1]
                assert other == "_common" or other not in names or other == p.stem, f"{p.name} imports {other}"


def test_no_scores_or_points_in_v2_code():
    pattern = re.compile(r"\b(score|scores|points|confluence_score|penalty)\b", re.IGNORECASE)
    for p in ROOT.rglob("*.py"):
        code = "\n".join(line for line in p.read_text(encoding="utf-8").splitlines()
                         if not line.strip().startswith("#"))
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.Attribute, ast.arg)):
                ident = node.id if isinstance(node, ast.Name) else (node.attr if isinstance(node, ast.Attribute) else node.arg)
                assert not pattern.fullmatch(ident), f"{p}: identifier '{ident}' looks like a score"


def test_config_ledger_matches_code_and_covers_every_constant():
    covered = set()
    for key, (value, reason, evidence) in LEDGER.items():
        mod_path, const = key.rsplit(".", 1)
        mod = importlib.import_module(f"engine_v2.{mod_path}")
        assert getattr(mod, const) == value, f"{key}: code {getattr(mod, const)} != ledger {value}"
        assert reason and evidence
        covered.add(key)
    scoped = ["market_model", "categories", "probability", "risk", "execution", "journal", "sim", "analysis"]
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).with_suffix("")
        parts = rel.parts
        if parts[0] not in scoped and rel.stem not in scoped:
            continue
        mod_name = ".".join(parts)
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name.isupper() and isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float, bool)):
                    if name in ("CATEGORY", "TF", "ZONE_TF", "TRIGGER_TF"):
                        continue
                    assert f"{mod_name}.{name}" in covered, f"{mod_name}.{name} has no ledger entry"
