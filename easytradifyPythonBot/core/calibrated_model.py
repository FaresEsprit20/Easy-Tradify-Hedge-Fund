# ============================================================
# CALIBRATED MODEL -- strategy-group probabilities measured on price history
# ============================================================
# FILE: core/calibrated_model.py
#
# The hand-built group score (50 +/- 45 x agreement, then max, opposition and
# context points) was not monotone: on the price-history study a higher final
# probability did not mean a higher hit rate, and several group scores were
# flat or inverted. ai/component_calibration.py replaces those hand weights
# with weights MEASURED on the study (first half of the calendar fitted,
# second half tested, readings kept only when validated out of sample with
# FDR control):
#
#   group P(up)  = logistic(intercept + sum coef_i x reading_i)
#                  over the group's validated readings -- member readings
#                  (direction x strength) and bar-computed edge features
#   final P(up)  = logistic(intercept + sum w_g x logit(group P(up)))
#   probability  = 100 x P(side) for the side being scored
#
# A logistic model is monotone in every reading by construction, and the
# study checks the result is monotone bin by bin on the test half.
#
# The weights live in core/calibrated_model.json, written by
#   python -m ai.component_calibration --export
# and this module only evaluates them, so the SAME function scores a live
# analysis and a study snapshot.
# ============================================================

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).with_name("calibrated_model.json")
DISCRETE_EDGES = ("asia_break", "prev_day_break", "sweep_reclaim")

_model_cache: Dict[str, Any] = {}


def load_model(path: Path = MODEL_PATH) -> Optional[Dict[str, Any]]:
    key = str(path)
    if key in _model_cache:
        return _model_cache[key]
    try:
        model = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        model = None
    _model_cache[key] = model
    return model


def raw_reader(reader: Callable) -> Callable:
    """The member's reader underneath its repair wrapper (trend-confirmed,
    continuation, regime-only, reversion), or the reader itself."""
    qual = getattr(reader, "__qualname__", "")
    if qual.startswith(("_trend_confirmed.", "_as_continuation.", "_in_regime.",
                        "_ou_gated.")) and reader.__closure__:
        for cell in reader.__closure__:
            inner = cell.cell_contents
            if callable(inner):
                return raw_reader(inner)
    return reader


def slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# Conditions a reading can be restricted to. ai/component_calibration.py
# vectorises exactly these thresholds; a reading "x@newyork" is x during
# 13:00-21:00 UTC and absent otherwise.
SESSIONS_UTC = {"asia": (0, 7), "london": (7, 13), "newyork": (13, 21)}
COMPRESSED_BELOW = 0.8
EXPANDED_ABOVE = 1.25


def condition_flags(regime: Any, hour_utc: Any, compression: Any) -> Dict[str, bool]:
    state = str(regime or "")
    flags = {"trending": state.startswith("TREND"), "ranging": state.startswith("RANGING")}
    for name, (a, b) in SESSIONS_UTC.items():
        flags[name] = isinstance(hour_utc, (int, float)) and a <= hour_utc < b
    flags["compressed"] = isinstance(compression, (int, float)) and compression < COMPRESSED_BELOW
    flags["expanded"] = isinstance(compression, (int, float)) and compression > EXPANDED_ABOVE
    return flags


def readings(payload: Mapping[str, Any], edges: Optional[Mapping[str, Any]] = None) -> Dict[str, float]:
    """Every reading the model can use, keyed like the study columns:
    m_raw_<member>, m_used_<member> (direction x strength), e_<edge>, and
    each raw/edge reading restricted to a condition: <key>@<condition>."""
    from core.strategy_groups import MEMBERS, _get

    out: Dict[str, float] = {}
    for _group, name, reader in MEMBERS:
        for kind, fn in (("used", reader), ("raw", raw_reader(reader))):
            try:
                r = fn(payload)
            except Exception:
                r = None
            if r is not None:
                out[f"m_{kind}_{slug(name)}"] = float(r[0]) * max(0.0, min(1.0, float(r[1])))
    for k, v in (edges or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and k != "version" and math.isfinite(v):
            out[f"e_{k}"] = float(v)
    edges = edges or {}
    flags = condition_flags(_get(payload, "volatility_protection.trading_regime.state"),
                            edges.get("hour_utc"), edges.get("compression"))
    for key in [k for k in out if k.startswith("m_raw_") or k.startswith("e_")]:
        for cond, on in flags.items():
            if on:
                out[f"{key}@{cond}"] = out[key]
    return out


def _base_name(name: str) -> str:
    return name.split("@", 1)[0].split("~", 1)[0]


def _transform(value: float, name: str, scale: float) -> float:
    name = _base_name(name)
    if name.startswith("e_") and name[2:] not in DISCRETE_EDGES:
        return math.tanh(value / (2.0 * (scale or 1.0)))
    return value


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _logit(p: float) -> float:
    p = min(1 - 1e-4, max(1e-4, p))
    return math.log(p / (1 - p))


def score(payload: Mapping[str, Any], direction: str, edges: Optional[Mapping[str, Any]] = None,
          model: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Calibrated probability for `direction`, or None when no model is installed."""
    model = model if model is not None else load_model()
    if not model or not model.get("groups"):
        return None
    side = 1 if str(direction).upper() == "BUY" else -1 if str(direction).upper() == "SELL" else 0
    values = readings(payload, edges)
    groups: Dict[str, Any] = {}
    logits = []
    for g in model["group_order"]:
        spec = model["groups"][g]
        z = spec["intercept"]
        present = 0
        for name, coef, scale in zip(spec["features"], spec["coef"], spec.get("scales") or [1.0] * len(spec["features"])):
            if name in values:
                z += coef * _transform(values[name], name, scale)
                present += 1
        p_up = _sigmoid(z)
        groups[g] = {"p_up": round(p_up, 4), "readings": present,
                     "score": round(100 * (p_up if side >= 0 else 1 - p_up), 1)}
        logits.append(_logit(p_up))
    stack = model["stack"]
    z = stack["intercept"] + sum(w * l for w, l in zip(stack["coef"], logits))
    p_up = _sigmoid(z)
    p_side = p_up if side > 0 else 1 - p_up if side < 0 else None
    preferred = "BUY" if p_up >= 0.5 else "SELL"
    return {
        "version": model.get("version"),
        "p_up": round(p_up, 4),
        "probability": None if p_side is None else round(100 * p_side, 1),
        "preferred_direction": preferred,
        "preferred_probability": round(100 * max(p_up, 1 - p_up), 1),
        "groups": groups,
    }


def get_status() -> Dict[str, Any]:
    model = load_model()
    return {"component": "calibrated_model", "installed": bool(model),
            "version": (model or {}).get("version")}


# ============================================================
# ENTRY DECISION (decision_mode = "calibrated")
# ============================================================
# The legacy entry funnel (golden signals -> discount -> confirmation ->
# probability tiers) was measured on the price-history study: its entries were
# right 46% on the test half against 49.5% for every bar -- it selected nothing.
# When the installed model says decision_mode "calibrated", the model decides:
# its side (if model_decides_direction), its probability against its own floor
# (chosen on net R after cost). Only hard safety checks remain: a closed or
# restricted session, news, a spread over the instrument's limit, extreme
# volatility. Everything else is evidence already inside the probability.

HARD_SAFETY_CHECKS = ("session_veto", "news_veto", "extreme_volatility")


def entry_decision(result: Mapping[str, Any], calibrated: Mapping[str, Any],
                   model: Mapping[str, Any]) -> Dict[str, Any]:
    traded = str(((result.get("config") or {}).get("executed_direction")
                  or (result.get("direction_decision") or {}).get("traded_direction") or "")).upper()
    if model.get("model_decides_direction"):
        side = calibrated.get("preferred_direction")
        probability = calibrated.get("preferred_probability")
    else:
        side = traded
        probability = calibrated.get("probability")
    floor = float(model.get("entry_floor", 100.0))
    out: Dict[str, Any] = {"side": side, "probability": probability, "floor": floor,
                           "flipped": bool(side and traded and side != traded), "enter": False}
    if side not in ("BUY", "SELL") or probability is None:
        out["reason"] = "no calibrated side"
        return out
    checks = ((result.get("vetos") or {}).get("checks") or {})
    blocked = [c for c in HARD_SAFETY_CHECKS if checks.get(c)]
    if (result.get("global_anticheat") or {}).get("spread_valid") is False:
        blocked.append("high_spread")
    if blocked:
        out["reason"] = f"hard safety: {', '.join(blocked)}"
        return out
    max_cost = model.get("max_cost_r")
    cost_r = (((result.get("strategy_groups") or {}).get("cost") or {}).get("cost_r"))
    if max_cost is not None and isinstance(cost_r, (int, float)) and cost_r > max_cost:
        out["reason"] = f"cost {cost_r:.2f}R above the {max_cost:.2f}R the policy was priced at"
        return out
    if probability < floor:
        out["reason"] = f"calibrated P({side}) {probability:.1f}% below the {floor:.1f}% floor"
        return out
    out.update(enter=True, reason=f"calibrated P({side}) {probability:.1f}% >= {floor:.1f}% floor")
    return out


def apply_entry(result: Dict[str, Any], decision: Mapping[str, Any]) -> None:
    """Write an ENTER for decision['side'] everywhere the monitor and the
    executor read it. The executor re-anchors stop and target to the live price
    by DISTANCE, so a flipped side only needs the levels mirrored around entry."""
    side = decision["side"]
    fv = result.setdefault("final_verdict", {})
    cfg = result.setdefault("config", {})
    entry = fv.get("entry_price")
    if decision.get("flipped") and isinstance(entry, (int, float)):
        for key in ("stop_loss", "take_profit_1", "take_profit_2", "take_profit_3"):
            level = fv.get(key)
            if isinstance(level, (int, float)):
                fv[key] = round(2 * entry - level, 8)
        for key, fkey in (("🛑 STOP_LOSS", "stop_loss"), ("🎯 TAKE_PROFIT_1", "take_profit_1"),
                          ("🎯 TAKE_PROFIT_2", "take_profit_2"), ("🎯 TAKE_PROFIT_3", "take_profit_3")):
            if key in result and fkey in fv:
                result[key] = fv[fkey]
    cfg["executed_direction"] = side
    cfg["min_probability_for_entry"] = decision["floor"]
    ea = result.setdefault("entry_analysis", {})
    ea.update(should_enter=True, simple_action="ENTER NOW", execution="EXECUTE_MARKET_ORDER",
              final_decision=f"{side} NOW", reason=decision["reason"], entry_status="CALIBRATED_ENTRY")
    fv.update(should_enter=True, verdict=f"{side} NOW", action=side, simple_action="ENTER NOW",
              execution="EXECUTE_MARKET_ORDER", probability_percent=round(float(decision["probability"]), 1))
    result["FINAL_DECISION"] = f"{side} NOW"
    result["🎯 FINAL_DECISION"] = f"{side} NOW"
    result["🚀 SIMPLE_ACTION"] = "ENTER NOW"


# ============================================================
# VERSION 2 -- features evaluated on core/result_leaves.model_row
# ============================================================

def _feature_value(spec: Mapping[str, Any], row: Mapping[str, Any], flags: Mapping[str, bool],
                   rules: Optional[Mapping[str, Any]]) -> float:
    cond = spec.get("condition")
    if cond and not flags.get(cond):
        return 0.0
    kind = spec.get("kind")
    if kind == "field":
        from core.component_rules import _direction
        d = _direction(row.get(spec["field"]))
        return float(d) if d else 0.0
    if kind == "rule":
        from core.component_rules import rule_reading
        items = ((rules or {}).get("components") or {}).get(spec["component"]) or []
        if spec["index"] >= len(items):
            return 0.0
        d = rule_reading(items[spec["index"]], row)
        return float(d) if d else 0.0
    if kind == "edge":
        v = row.get(f"edges.{spec['edge']}")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return 0.0
        if spec.get("discrete"):
            return float(v)
        return math.tanh(float(v) / (2.0 * (spec.get("scale") or 1.0)))
    return 0.0


def score_row(row: Mapping[str, Any], direction: str, model: Mapping[str, Any],
              rules: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Version-2 calibrated probability for `direction` from a model row."""
    if rules is None:
        from core.component_rules import load_rules
        rules = load_rules()
    flags = condition_flags(row.get("ctx.regime"), row.get("edges.hour_utc"), row.get("edges.compression"))
    side = 1 if str(direction).upper() == "BUY" else -1 if str(direction).upper() == "SELL" else 0
    groups, logits = {}, []
    for g in model["group_order"]:
        spec = model["groups"][g]
        z = spec["intercept"]
        active = 0
        for feat, coef in zip(spec["features"], spec["coef"]):
            v = _feature_value(feat, row, flags, rules)
            if v:
                active += 1
            z += coef * v
        p = _sigmoid(z)
        groups[g] = {"p_up": round(p, 4), "readings": active, "score": round(100 * (p if side >= 0 else 1 - p), 1)}
        logits.append(_logit(p))
    stack = model["stack"]
    p_up = _sigmoid(stack["intercept"] + sum(w * l for w, l in zip(stack["coef"], logits)))
    return {"version": 2, "p_up": round(p_up, 4),
            "probability": None if side == 0 else round(100 * (p_up if side > 0 else 1 - p_up), 1),
            "preferred_direction": "BUY" if p_up >= 0.5 else "SELL",
            "preferred_probability": round(100 * max(p_up, 1 - p_up), 1), "groups": groups}
