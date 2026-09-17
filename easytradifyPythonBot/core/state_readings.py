# ============================================================
# STATE READINGS -- what each group SEES, on every bar
# ============================================================
# FILE: core/state_readings.py
#
# A component's label is neutral almost always (supply/demand says MONITOR on
# 96% of bars, support/resistance NEUTRAL on 70%), so its group has nothing to
# report: STRUCTURE produced a score on 2.1% of bars, ORDER_FLOW on 5.9%,
# WAVE on 12.9%. The state behind the label exists on every bar -- price IS
# somewhere relative to the zone, the level, the value area.
#
# These readings turn that state into a side, so every group states what it
# sees. They are PUBLISHED, NOT SCORED: measured on the live market-stop trade
# (ai/state_readings.py, 110,603 snapshots, tick-accurate fills) the best of
# them wins 45.9% against a 44.6% baseline and still loses 0.13R per trade.
# A reading starts moving the probability only when it clears the five-star
# line -- 65% wins and +0.2R on validation AND holdout.
#
# `readings(result)` returns {group: {name: {"side", "value"}}}, and each
# entry carries what it was worth on the unseen period, so nobody has to
# re-derive whether it means anything.
# ============================================================

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

# name -> (group, what it measured on the holdout: win %, net R, coverage %)
MEASURED: Dict[str, Dict[str, Any]] = {
    "rsi_from_50": {"group": "MEAN_REVERSION", "won_pct": 45.3, "net_r": -0.143, "covers_pct": 39.3},
    "liquidity_pool_side": {"group": "ORDER_FLOW", "won_pct": 45.4, "net_r": -0.121, "covers_pct": 9.8},
    "value_area_side": {"group": "ORDER_FLOW", "won_pct": 45.3, "net_r": -0.141, "covers_pct": 44.3},
    "poc_side": {"group": "ORDER_FLOW", "won_pct": 44.8, "net_r": -0.154, "covers_pct": 98.7},
    "macd_histogram": {"group": "MOMENTUM", "won_pct": 45.1, "net_r": -0.145, "covers_pct": 85.1},
    "premium_discount": {"group": "SMC", "won_pct": 45.0, "net_r": -0.147, "covers_pct": 54.9},
    "fvg_side": {"group": "SMC", "won_pct": 44.7, "net_r": -0.153, "covers_pct": 92.8},
    "bollinger_percent_b": {"group": "MEAN_REVERSION", "won_pct": 45.0, "net_r": -0.143, "covers_pct": 12.9},
    "nearer_pivot_level": {"group": "STRUCTURE", "won_pct": 44.8, "net_r": -0.154, "covers_pct": 98.6},
    "supply_demand_side": {"group": "STRUCTURE", "won_pct": 44.7, "net_r": -0.155, "covers_pct": 100.0},
    "ema200_side": {"group": "TREND", "won_pct": 44.8, "net_r": -0.155, "covers_pct": 99.3},
    "ema_gap": {"group": "TREND", "won_pct": 44.8, "net_r": -0.153, "covers_pct": 80.0},
    "correction_direction": {"group": "WAVE", "won_pct": 44.2, "net_r": -0.165, "covers_pct": 86.9},
}
BASELINE_WIN_PCT = 44.6
FIVE_STAR_WIN_PCT = 65.0
FIVE_STAR_NET_R = 0.2


def _num(node: Any) -> Optional[float]:
    if isinstance(node, bool) or node is None:
        return None if not isinstance(node, bool) else float(node)
    return float(node) if isinstance(node, (int, float)) else None


def _get(payload: Mapping[str, Any], path: str) -> Any:
    from core.analysis_groups import resolve

    for candidate in (path, resolve(path)):
        node: Any = payload
        for part in candidate.split("."):
            if not isinstance(node, Mapping) or part not in node:
                node = None
                break
            node = node[part]
        if node is not None:
            return node
    return None


def _side(value: Optional[float], positive_means: int = 1) -> Optional[int]:
    if value is None:
        return None
    if value > 0:
        return positive_means
    if value < 0:
        return -positive_means
    return None


def readings(result: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Every group's state as a side, whether or not its label said anything."""
    price = _num(_get(result, "entry_details.entry_price")) or _num(_get(result, "final_verdict.entry_price"))
    atr_pips = _num(_get(result, "global_anticheat.atr_pips"))
    out: Dict[str, Dict[str, Any]] = {}

    def add(name: str, side: Optional[int], value: Any = None) -> None:
        if side is None:
            return
        spec = MEASURED.get(name, {})
        group = spec.get("group", "CONTEXT")
        out.setdefault(group, {})[name] = {
            "side": "BUY" if side > 0 else "SELL",
            "value": round(value, 5) if isinstance(value, float) else value,
            "holdout_won_pct": spec.get("won_pct"),
            "holdout_net_r": spec.get("net_r"),
            "scored": False,
        }

    # STRUCTURE
    is_demand = _num(_get(result, "indicators.supply_demand.debug.is_demand_zone"))
    dist_zone = _num(_get(result, "indicators.supply_demand.debug.distance_to_zone_pips"))
    if is_demand is not None:
        add("supply_demand_side", 1 if is_demand > 0 else -1,
            round(dist_zone / atr_pips, 2) if dist_zone is not None and atr_pips else dist_zone)
    r1, s1 = _num(_get(result, "indicators.support_resistance.r1")), _num(_get(result, "indicators.support_resistance.s1"))
    if price and r1 is not None and s1 is not None:
        to_r, to_s = abs(r1 - price), abs(price - s1)
        add("nearer_pivot_level", 1 if to_s < to_r else -1 if to_r < to_s else None, round(to_s - to_r, 5))

    # ORDER FLOW
    vah, val = _num(_get(result, "indicators.volume_profile.vah")), _num(_get(result, "indicators.volume_profile.val"))
    if price and vah is not None and val is not None:
        add("value_area_side", -1 if price > vah else 1 if price < val else None, price)
    poc = _num(_get(result, "indicators.volume_profile.poc"))
    if price and poc is not None:
        add("poc_side", _side(poc - price), round(price - poc, 5))
    hi = _get(result, "order_flow_forensics.liquidity_pools.equal_highs_pools") or []
    lo = _get(result, "order_flow_forensics.liquidity_pools.equal_lows_pools") or []
    if isinstance(hi, list) and isinstance(lo, list) and (hi or lo):
        add("liquidity_pool_side", _side(len(hi) - len(lo)), len(hi) - len(lo))

    # SMC
    pos = _num(_get(result, "smc.analysis.premium_discount.position_pct"))
    if pos is not None:
        add("premium_discount", 1 if pos <= 25 else -1 if pos >= 75 else None, pos)
    above = _num(_get(result, "indicators.ict_concepts.price_above_fvg_pips"))
    below = _num(_get(result, "indicators.ict_concepts.price_below_fvg_pips"))
    if above is not None or below is not None:
        add("fvg_side", -1 if (above or 0) > 0 else 1 if (below or 0) > 0 else None, above or below)

    # TREND (both read inverted against the move: measured, not assumed)
    ema200 = _num(_get(result, "indicators.trend.ema.ema_200"))
    if price and ema200 is not None:
        add("ema200_side", _side(ema200 - price), round(price - ema200, 5))
    ema20 = _num(_get(result, "indicators.trend.ema.ema_20"))
    if ema20 is not None and ema200 is not None and atr_pips:
        pip = _num(_get(result, "entry_details.spread_pips"))
        gap_atr = (ema20 - ema200)
        add("ema_gap", _side(-gap_atr), round(gap_atr, 5))

    # MOMENTUM / MEAN REVERSION
    hist = _num(_get(result, "indicators.macd.histogram"))
    if hist is not None:
        add("macd_histogram", _side(-hist), hist)
    rsi = _num(_get(result, "indicators.rsi.rsi_14"))
    if rsi is not None:
        add("rsi_from_50", -1 if rsi >= 60 else 1 if rsi <= 40 else None, rsi)
    pb = _num(_get(result, "indicators.bollinger_bands.debug.percent_b"))
    if pb is not None:
        add("bollinger_percent_b", -1 if pb >= 0.9 else 1 if pb <= 0.1 else None, pb)

    # WAVE
    corr = _get(result, "indicators.wave_c.data.correction_direction")
    if isinstance(corr, str) and corr.upper() in ("UP", "DOWN"):
        add("correction_direction", -1 if corr.upper() == "UP" else 1, corr.upper())
    return out


def summary(state: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """How many groups stated something, and how that compares with the labels."""
    return {"groups_with_a_reading": len(state),
            "readings": sum(len(v) for v in state.values()),
            "scored": False,
            "note": (f"published, not scored: the best of these wins {max(m['won_pct'] for m in MEASURED.values())}% "
                     f"on the holdout against a {BASELINE_WIN_PCT}% baseline. A reading is scored once it clears "
                     f"{FIVE_STAR_WIN_PCT}% wins and +{FIVE_STAR_NET_R}R on validation and holdout.")}


def get_status() -> Dict[str, Any]:
    return {"component": "state_readings", "readings": len(MEASURED), "scored": False,
            "baseline_win_pct": BASELINE_WIN_PCT}


def self_check() -> Dict[str, Any]:
    payload = {
        "entry_details": {"entry_price": 1.1000},
        "global_anticheat": {"atr_pips": 1.0},
        "indicators": {
            "supply_demand": {"debug": {"is_demand_zone": 1, "distance_to_zone_pips": 2.0}},
            "support_resistance": {"r1": 1.1050, "s1": 1.0990},
            "volume_profile": {"poc": 1.1010, "vah": 1.1020, "val": 1.1005},
            "trend": {"ema": {"ema_20": 1.1002, "ema_200": 1.1008}},
            "macd": {"histogram": -0.00002},
            "rsi": {"rsi_14": 72.0},
            "bollinger_bands": {"debug": {"percent_b": 0.95}},
            "ict_concepts": {"price_above_fvg_pips": 0.0, "price_below_fvg_pips": 1.2},
            "wave_c": {"data": {"correction_direction": "UP"}},
        },
        "smc": {"analysis": {"premium_discount": {"position_pct": 12.0}}},
        "order_flow_forensics": {"liquidity_pools": {"equal_highs_pools": [1, 2, 3], "equal_lows_pools": [1]}},
    }
    s = readings(payload)
    assert s["STRUCTURE"]["supply_demand_side"]["side"] == "BUY"          # demand zone
    assert s["STRUCTURE"]["nearer_pivot_level"]["side"] == "BUY"          # support is closer
    assert s["ORDER_FLOW"]["value_area_side"]["side"] == "BUY"            # below the value area (1.1000 < VAL)
    assert s["ORDER_FLOW"]["poc_side"]["side"] == "BUY"                   # price below the POC
    assert s["ORDER_FLOW"]["liquidity_pool_side"]["side"] == "BUY"        # more resting highs
    assert s["SMC"]["premium_discount"]["side"] == "BUY"                  # deep discount
    assert s["SMC"]["fvg_side"]["side"] == "BUY"                          # price below the gap, read inverted
    assert s["TREND"]["ema200_side"]["side"] == "BUY"                     # below EMA200, read inverted
    assert s["MOMENTUM"]["macd_histogram"]["side"] == "BUY"               # negative histogram, read inverted
    assert s["MEAN_REVERSION"]["rsi_from_50"]["side"] == "SELL"           # RSI 72
    assert s["WAVE"]["correction_direction"]["side"] == "SELL"            # an UP correction ends down
    assert all(r["scored"] is False for g in s.values() for r in g.values())
    assert summary(s)["groups_with_a_reading"] == 7
    return {"ok": True}
