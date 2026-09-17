# ============================================================
# COMPONENT RULES -- validated repairs, evaluated on a live analysis
# ============================================================
# FILE: core/component_rules.py
#
# ai/component_repair.py searches each component's own internal fields for the
# conditions under which its direction is right often enough, and profitably
# enough, on the calendar half the rule was not found on. The passing rules
# are exported to core/component_rules.json as plain conditions:
#
#   {"vote": "indicators.supply_demand.recommendation", "orientation": "as-is",
#    "conditions": ["edges.hour_utc >= 13.0", "(indicators.supply_demand.zone_level - price)/ATR <= 0.25"]}
#
# This module evaluates them on core/result_leaves.model_row -- the same row
# shape the search ran on -- so a rule reads identically live and in the study.
# A rule that holds gives a reading: the vote's direction (flipped when
# "inverted"); a rule that does not hold is silent.
# ============================================================

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

RULES_PATH = Path(__file__).with_name("component_rules.json")
_cache: Dict[str, Any] = {}


def load_rules(path: Path = RULES_PATH) -> Optional[Dict[str, Any]]:
    key = str(path)
    if key not in _cache:
        try:
            _cache[key] = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            _cache[key] = None
    return _cache[key]


def _direction(value: Any) -> Optional[int]:
    from core.strategy_groups import market_direction
    if isinstance(value, bool):
        return 1 if value else -1
    return market_direction(value)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def condition_holds(condition: str, row: Mapping[str, Any]) -> bool:
    for op in (" <= ", " >= ", " == "):
        if op in condition:
            left, right = condition.split(op, 1)
            break
    else:
        return False
    left = left.strip()
    if left.startswith("(") and left.endswith(" - price)/ATR"):
        field = left[1:-len(" - price)/ATR")]
        level, close = _number(row.get(field)), _number(row.get("close"))
        atr, pip = _number(row.get("atr_pips")), _number(row.get("pip"))
        if None in (level, close, atr, pip) or atr <= 0 or pip <= 0:
            return False
        value: Any = (level - close) / (atr * pip)
    else:
        value = row.get(left)
    if op == " == ":
        num_right = _number(right)
        num_value = _number(value)
        if num_right is not None and num_value is not None:
            return num_value == num_right
        return value is not None and str(value) == right
    num_value, num_right = _number(value), _number(right)
    if num_value is None or num_right is None:
        return False
    return num_value <= num_right if op == " <= " else num_value >= num_right


def rule_reading(rule: Mapping[str, Any], row: Mapping[str, Any]) -> Optional[int]:
    """+1 / -1 when the rule holds and its vote has a direction, else None."""
    d = _direction(row.get(rule.get("vote")))
    if not d:
        return None
    if not all(condition_holds(c, row) for c in rule.get("conditions") or []):
        return None
    return -d if rule.get("orientation") == "inverted" else d


def readings(row: Mapping[str, Any], rules: Optional[Mapping[str, Any]] = None) -> Dict[str, int]:
    """Every holding rule as r_<component>_<index> -> direction."""
    rules = rules if rules is not None else load_rules()
    out: Dict[str, int] = {}
    for component, items in ((rules or {}).get("components") or {}).items():
        for i, rule in enumerate(items):
            r = rule_reading(rule, row)
            if r:
                out[f"r_{component}_{i}"] = r
    return out


def get_status() -> Dict[str, Any]:
    rules = load_rules()
    return {"component": "component_rules", "installed": bool(rules),
            "components": len((rules or {}).get("components") or {})}
