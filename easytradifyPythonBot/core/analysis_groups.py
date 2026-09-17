# ============================================================
# ANALYSIS GROUPS -- one home for every reading the engine produces
# ============================================================
# FILE: core/analysis_groups.py
#
# The analysis payload grew one top-level key per detector: 53 of them, with
# `indicators` holding unrelated families (RSI next to supply/demand next to
# Wyckoff), the same reading published two or three times, and sections no
# reader has ever consumed. Nothing said which strategy a reading belonged to,
# so "why did the WAVE group not score?" could not be answered from the
# payload itself.
#
# Here every reading is filed under the strategy group that trades it -- the
# same groups the scorer uses (core/strategy_groups.GROUP_TITLES) -- plus
# CONTEXT for readings that describe the session rather than a direction:
#
#   analysis.TREND.data.trend / cascade / higher_timeframe / ...
#   analysis.STRUCTURE.data.supply_demand / support_resistance / ...
#
# Each group also carries its score, direction and members from the scorer, so
# a group that did not score says so in place, next to the readings that
# should have produced one.
#
# `reshape()` MOVES the keys (it never copies), drops TRASH, and leaves the
# decision itself at the top level. `resolve()` translates a legacy dotted
# path to its new home so the calibrated model, the component rules and the
# price-history study keep reading the same values.
# ============================================================

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# group -> (key in the group's `data`, where it lives in the legacy payload)
GROUPS: Dict[str, List[Tuple[str, str]]] = {
    "TREND": [("trend", "indicators.trend"), ("cascade", "trend_cascade"),
              ("higher_timeframe", "higher_timeframe"), ("confirmation", "trend_confirmation")],
    "MOMENTUM": [("macd", "indicators.macd"), ("stochastic", "indicators.stochastic"),
                 ("ttm_squeeze", "ttm_squeeze"), ("ttm_squeeze_setup", "ttm_squeeze_setup"),
                 ("rvam", "rvam"), ("vwap", "vwap"), ("vwap_context", "vwap_context")],
    "MEAN_REVERSION": [("rsi", "indicators.rsi"), ("bollinger_bands", "indicators.bollinger_bands"),
                       ("adaptive_disagreement", "indicators.adaptive_disagreement")],
    "STRUCTURE": [("supply_demand", "indicators.supply_demand"),
                  ("retest_confirmation", "indicators.retest_confirmation"),
                  ("support_resistance", "indicators.support_resistance"),
                  ("breakout", "indicators.breakout"), ("fib_confluence", "indicators.fib_confluence"),
                  ("round_numbers", "indicators.round_numbers")],
    "SMC": [("analysis", "smc.analysis"), ("trade_setup", "smc.trade_setup"), ("order_block_volume_profile", "smc.order_block_volume_profile_confluence"),
            ("sweep_volume_profile", "smc.sweep_volume_profile_confluence"),
            ("ict_concepts", "indicators.ict_concepts"), ("fvg_ifvg", "indicators.fvg_ifvg")],
    "ORDER_FLOW": [("volume", "indicators.volume"), ("volume_profile", "indicators.volume_profile"),
                   ("forensics", "order_flow_forensics"), ("liquidity_events", "liquidity_events"),
                   ("liquidity_score", "liquidity_final_score")],
    "WAVE": [("patterns", "pattern_analysis"), ("lattice", "wave_lattice"),
             ("wyckoff", "indicators.wyckoff"), ("candlestick", "indicators.candlestick"),
             ("wave_c", "indicators.wave_c")],
    "CROSS_ASSET": [("gnn", "gnn"), ("ohlc_gnn", "ohlc_gnn")],
    "CONTEXT": [("expected_value", "indicators.expected_value"), ("session", "session_analysis"), ("news", "news_analysis"),
                ("adr_exhaustion", "adr_exhaustion"), ("gap_slippage", "gap_slippage_analysis"),
                ("volatility", "volatility_protection"), ("market", "global_anticheat")],
}

# Sections measured to carry nothing a reader or the bot can use.
#   components          a second copy of each indicator's recommendation/score
#   symbolic_gate       legacy gate, never consulted
#   hard_disagreement   a bare flag the decision no longer reads
#   indicators.cot_report   always "EXCLUDED (M1/M5)" on these timeframes
#   smc.available           a flag beside the block it describes
# `success` is NOT trash: it is the API's ok-flag (api/execution_controller.py
# and four other readers test it), and dropping it made every /trade/analyse
# call answer {"success": false} while the analysis itself was fine.
TRASH = ("components", "symbolic_gate", "hard_disagreement",
         "indicators.cot_report", "smc.available")

# What stays at the top level: the decision and what it was made with.
DECISION_KEYS = ("symbol", "timeframe", "timestamp", "config", "account_info", "entry_details", "entry_analysis",
                 "final_verdict", "directional_analysis", "direction_decision", "strategy_groups",
                 "calibrated_decision", "decision_snapshot", "position_management", "vetos")

_LEGACY_TO_NEW: Dict[str, str] = {}
for _group, _items in GROUPS.items():
    for _key, _legacy in _items:
        _LEGACY_TO_NEW[_legacy] = f"analysis.{_group}.data.{_key}"


def resolve(path: str) -> str:
    """A legacy dotted path translated to its new home (unchanged if not moved)."""
    for legacy, new in _LEGACY_TO_NEW.items():
        if path == legacy:
            return new
        if path.startswith(legacy + "."):
            return new + path[len(legacy):]
    return path


_NEW_TO_LEGACY: Dict[str, str] = {v: k for k, v in _LEGACY_TO_NEW.items()}


def to_legacy(path: str) -> str:
    """The reverse of resolve(): a grouped path spelled the flat way.

    The study stores whatever the payload calls a leaf, while the component
    registry and the fitted rules are written in the flat spelling. Column
    names are normalised through this so a capture taken after the grouping
    reads the same as one taken before it.
    """
    for new, legacy in _NEW_TO_LEGACY.items():
        if path == new:
            return legacy
        if path.startswith(new + "."):
            return legacy + path[len(new):]
    return path


def legacy_paths() -> Iterable[str]:
    return _LEGACY_TO_NEW.keys()


def _take(result: Dict[str, Any], path: str) -> Optional[Any]:
    """Pop `path` out of the payload (dotted, one level of nesting)."""
    head, _, tail = path.partition(".")
    if head not in result:
        return None
    if not tail:
        return result.pop(head)
    holder = result.get(head)
    if not isinstance(holder, dict) or tail not in holder:
        return None
    value = holder.pop(tail)
    if not holder:
        result.pop(head, None)
    return value


def reshape(result: Dict[str, Any], scores: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """File every reading under its strategy group, in place.

    `scores` is the scorer's `groups` block (core/strategy_groups.score_groups),
    so each group states its own score, direction and members beside its data.
    """
    if not isinstance(result, dict) or "analysis" in result:
        return result
    for key in TRASH:
        if "." in key:
            _take(result, key)
        else:
            result.pop(key, None)
    scores = scores or {}
    analysis: Dict[str, Any] = {}
    for group, items in GROUPS.items():
        data = {}
        for key, legacy in items:
            value = _take(result, legacy)
            if value is not None:
                data[key] = value
        score = scores.get(group) or {}
        entry: Dict[str, Any] = {"data": data}
        if score:
            entry["score"] = score.get("score")
            entry["direction"] = score.get("direction")
            entry["scored"] = bool(score.get("scored"))
            entry["members"] = score.get("members")
            if score.get("reason"):
                entry["reason"] = score.get("reason")
        analysis[group] = entry
    result["analysis"] = analysis
    # whatever the map does not mention keeps its place, so a new detector is
    # visible (and obviously unfiled) until it is added to GROUPS
    return result


def block(result: Mapping[str, Any], legacy_top: str) -> Dict[str, Any]:
    """A legacy top-level block (`indicators`, `smc`, `gnn`, ...) whether the
    payload is grouped or flat.

    Readers written against the flat shape keep working after reshape(): the
    block is reassembled from the groups, pointing at the same objects rather
    than copying them.
    """
    direct = result.get(legacy_top)
    if isinstance(direct, dict) and direct:
        return direct
    analysis = result.get("analysis") or {}
    out: Dict[str, Any] = {}
    prefix = legacy_top + "."
    for group, items in GROUPS.items():
        data = (analysis.get(group) or {}).get("data") or {}
        for key, legacy in items:
            if key in data:
                if legacy == legacy_top:
                    return data[key]
                if legacy.startswith(prefix):
                    out[legacy[len(prefix):]] = data[key]
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "analysis_groups", "groups": list(GROUPS), "moved_paths": len(_LEGACY_TO_NEW),
            "trash": list(TRASH)}


def self_check() -> Dict[str, Any]:
    payload = {"indicators": {"rsi": {"recommendation": "BUY"}, "trend": {"recommendation": "SELL"}},
               "smc": {"analysis": {"recommendation": "BUY"}}, "components": {"x": 1}, "symbol": "EURUSD"}
    out = reshape(payload, {"MEAN_REVERSION": {"score": 70.0, "scored": True, "direction": "BUY"}})
    assert out["analysis"]["MEAN_REVERSION"]["data"]["rsi"]["recommendation"] == "BUY"
    assert out["analysis"]["MEAN_REVERSION"]["score"] == 70.0
    assert out["analysis"]["TREND"]["data"]["trend"]["recommendation"] == "SELL"
    assert out["analysis"]["SMC"]["data"]["analysis"]["recommendation"] == "BUY"
    assert "components" not in out and "indicators" not in out and out["symbol"] == "EURUSD"
    assert reshape({"success": True, "symbol": "X"})["success"] is True   # the API's ok-flag survives
    assert resolve("indicators.rsi.rsi_14") == "analysis.MEAN_REVERSION.data.rsi.rsi_14"
    assert to_legacy("analysis.MEAN_REVERSION.data.rsi.rsi_14") == "indicators.rsi.rsi_14"
    assert to_legacy("final_verdict.probability_percent") == "final_verdict.probability_percent"
    assert resolve("smc.analysis.premium_discount.zone") == "analysis.SMC.data.analysis.premium_discount.zone"
    assert resolve("final_verdict.probability_percent") == "final_verdict.probability_percent"
    # readers written against the flat shape keep working
    assert block(out, "indicators")["rsi"]["recommendation"] == "BUY"
    assert block(out, "smc")["analysis"]["recommendation"] == "BUY"
    assert block({"indicators": {"rsi": {"x": 1}}}, "indicators")["rsi"]["x"] == 1
    return {"ok": True}
