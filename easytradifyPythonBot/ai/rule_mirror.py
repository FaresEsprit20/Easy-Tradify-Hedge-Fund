# ai/rule_mirror.py
"""
Mirror a component rule into its opposite-side twin.

A rule found on history can only describe the situations history offered. The
study window drifted down, so the repair search found many sell-side rules --
"strong UP momentum late in New York -> SELL" -- without their buy-side twins,
and the category models ended up able to reach high confidence only on SELLs
(25:1). A rule about price structure should read the same when the market is
turned upside down. This builds that twin:

  text values      BUY<->SELL, BULLISH<->BEARISH, UP<->DOWN, SUPPLY<->DEMAND,
                   PREMIUM<->DISCOUNT, HIGH<->LOW, ABOVE<->BELOW, H<->L
  field names      high<->low, highs<->lows, vah<->val, resistance<->support,
                   upper<->lower, bullish<->bearish, buy<->sell
  signed numbers   x <= q  ->  x >= -q     (a column that takes both signs)
  unsigned numbers unchanged               (distances, hours, ranges, counts)
  price distances  (level - price)/ATR <= q  ->  (mirrored level - price)/ATR >= -q
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Mapping, Optional

_VALUE_SWAPS = [("STRONG_BUY", "STRONG_SELL"), ("BUY NOW", "SELL NOW"), ("BUY", "SELL"), ("BULLISH", "BEARISH"),
                ("SUPPLY", "DEMAND"), ("PREMIUM", "DISCOUNT"), ("ABOVE", "BELOW"), ("HIGH", "LOW"),
                ("UP", "DOWN"), ("RISING", "FALLING")]
_NAME_SWAPS = [("highs", "lows"), ("high", "low"), ("vah", "val"), ("resistance", "support"), ("upper", "lower"),
               ("bullish", "bearish"), ("buy", "sell"), ("demand", "supply"), ("premium", "discount")]
_EXACT_VALUE_SWAPS = {"H": "L", "L": "H"}


def _swap_tokens(text: str, pairs, flags=0) -> str:
    placeholder = {}
    out = text
    for i, (a, b) in enumerate(pairs):
        ka, kb = f"\x00{i}a\x00", f"\x00{i}b\x00"
        out = re.sub(re.escape(a), ka, out, flags=flags)
        out = re.sub(re.escape(b), kb, out, flags=flags)
        placeholder[ka], placeholder[kb] = b, a
    for k, v in placeholder.items():
        out = out.replace(k, v)
    return out


_VALUE_TOKEN_SWAPS = {}
for _a, _b in _VALUE_SWAPS:
    if "_" not in _a and " " not in _a:
        _VALUE_TOKEN_SWAPS[_a], _VALUE_TOKEN_SWAPS[_b] = _b, _a


def mirror_value(value: str) -> str:
    if value in _EXACT_VALUE_SWAPS:
        return _EXACT_VALUE_SWAPS[value]
    parts = re.split(r"([_ ])", value)
    return "".join(_VALUE_TOKEN_SWAPS.get(p, p) for p in parts)


_NAME_TOKEN_SWAPS = {}
for _a, _b in _NAME_SWAPS:
    _NAME_TOKEN_SWAPS[_a], _NAME_TOKEN_SWAPS[_b] = _b, _a


def mirror_field(name: str) -> str:
    """Swap whole name tokens only (split on _ . [ ]): 'flow' in
    'order_flow_forensics' is not 'low'."""
    parts = re.split(r"([._\[\]])", name)
    return "".join(_NAME_TOKEN_SWAPS.get(p, p) for p in parts)


def mirror_condition(condition: str, is_signed: Callable[[str], bool]) -> Optional[str]:
    for op in (" <= ", " >= ", " == "):
        if op in condition:
            left, right = condition.split(op, 1)
            break
    else:
        return None
    if left.startswith("(") and left.endswith(" - price)/ATR"):
        field = mirror_field(left[1:-len(" - price)/ATR")])
        flipped = {" <= ": " >= ", " >= ": " <= ", " == ": " == "}[op]
        return f"({field} - price)/ATR{flipped}{-float(right)!r}"
    field = mirror_field(left)
    if op == " == ":
        try:
            num = float(right)
        except ValueError:
            return f"{field} == {mirror_value(right)}"
        return f"{field} == {(-num if is_signed(left) else num)!r}"
    if is_signed(left):
        flipped = " >= " if op == " <= " else " <= "
        return f"{field}{flipped}{-float(right)!r}"
    return f"{field}{op}{right}"


def mirror_rule(rule: Mapping[str, Any], is_signed: Callable[[str], bool]) -> Optional[Dict[str, Any]]:
    conditions = [mirror_condition(c, is_signed) for c in rule.get("conditions") or []]
    if any(c is None for c in conditions):
        return None
    twin = dict(rule)
    twin["conditions"] = conditions
    twin["vote"] = mirror_field(rule["vote"])
    return twin


def self_check() -> Dict[str, Any]:
    signed = lambda f: f.startswith("edges.mom") or f.endswith(".score")
    assert mirror_condition("indicators.trend.recommendation == SELL", signed) == "indicators.trend.recommendation == BUY"
    assert mirror_condition("edges.mom_agreement >= 4.0", signed) == "edges.mom_agreement <= -4.0"
    assert mirror_condition("edges.hour_utc >= 19.0", signed) == "edges.hour_utc >= 19.0"
    assert mirror_condition("(smc.analysis.market_structure.last_swing_low - price)/ATR <= -3.0", signed) == \
        "(smc.analysis.market_structure.last_swing_high - price)/ATR >= 3.0"
    assert mirror_condition("indicators.wave_c.data.point0.type == H", signed) == "indicators.wave_c.data.point0.type == L"
    assert mirror_condition("pattern_analysis.elliott_waves[0].action == BUY NOW", signed).endswith("SELL NOW")
    assert mirror_field("order_flow_forensics.liquidity_pools.equal_highs_pools[0].level") == \
        "order_flow_forensics.liquidity_pools.equal_lows_pools[0].level"
    return {"ok": True}


def get_status() -> Dict[str, Any]:
    return {"component": "rule_mirror"}
