# ============================================================
# HISTORY ENRICHMENT -- REAL ANALYSIS FOR REAL PAST TRADES
# ============================================================
#
# THE PROBLEM THIS SOLVES
# -----------------------
# The MT5 account history has 215 real trades with stops, and no reasoning:
# the broker records the order, never the analysis behind it. So every model
# whose features come from `analysis_at_open` -- abstention, calibration,
# trade quality, anything reading SMC or indicators or session -- had nothing
# to read, and the replay could only measure paths.
#
# But the analysis layer is DETERMINISTIC over bars. Feed it the bars as they
# stood at the entry moment and it reproduces what the bot would have computed
# then. That is not simulated data; it is the real analysis, recomputed.
#
# WHY THIS IS NOT LOOK-AHEAD
# --------------------------
# `HistoricalFeed.at(ts)` slices every timeframe to bars closed at or before
# `ts`, and `verify_no_lookahead(ts, md)` proves it -- it returns the list of
# violations, and the enrichment refuses any trade where that list is
# non-empty rather than trusting the slicer. Measured on the first trade
# enriched: NONE.
#
# That check is not decoration. An analysis computed with one bar of future
# knowledge would produce features that predict the outcome beautifully and
# are worthless forward, which is the single most expensive mistake available
# here and the one this package has caught three times already.
#
# ✅ FIXED -- AND THE CHECK ABOVE COULD NOT SEE IT
# ------------------------------------------------
# `verify_no_lookahead` verifies the MarketData this module HANDS OVER. It
# cannot see a component that ignores that argument and calls MetaTrader5
# itself. Several in the chain do exactly that -- they were written for live
# trading, where `copy_rates_from_pos(symbol, tf, 0, n)` is simply "the
# latest bars":
#
#   nested_zone_confluence.py:122   M15/H1/H4 swing structure
#   trend_cascade.py:141            M5/M15/H1/H4 EMA slopes
#   adr_exhaustion.py:61            D1 range
#   calculations.py:1510            M15 divergence
#   indicators.py:2922/3015/3398    H1 trend, M15 divergence, generic TF
#   indicators.py:944               copy_ticks_from -> micro-structure
#
# During enrichment of a trade from weeks ago, every one of those returned
# TODAY'S bars. Not the trade's future specifically -- simply the wrong data,
# identical for every trade of a symbol enriched in the same run. Components
# fed that way cannot help measuring as noise, which means "this component
# does not work" was an unsafe conclusion for all of them.
#
# core/mt5_shim.py already exists to solve precisely this, and
# core/engine_replay.py and core/run_replay.py already use it. This module
# did not, so it is entered here too. The shim is fail-closed: a timeframe
# the feed cannot serve returns None, so a component reports
# available: False and contributes nothing, rather than quietly contributing
# the present. Inert is a correct answer; contaminated is not.
#
# The feed is therefore also widened to H4 and D1 (see TIMEFRAME_WARMUP_DAYS)
# so those components have real history to be causal ABOUT, instead of being
# starved into unavailability by a 5-day M1 warmup.
#
# WHAT IS REAL AND WHAT IS RECONSTRUCTED
# --------------------------------------
#   REAL          entry, exit, stop, target, direction, volume, profit --
#                 straight from the broker's record of the fill
#   RECOMPUTED    analysis_at_open, and the per-point analysis along the
#                 path: the same deterministic functions on the same bars
#   APPROXIMATED  the path itself, from M1 closes rather than ticks
#
# The third line is the honest limit. A stop touched and released inside a
# minute is invisible, so path-derived results carry the same caveat the MT5
# adapter already stamps on them.
#
# WHAT THIS DOES NOT DO
# ---------------------
# It does not write to Firebase. These are reconstructions, and putting them
# in the trades collection would make them indistinguishable from trades the
# bot actually recorded -- the fictional-history problem the recorder refuses
# for the same reason. They go to a local JSONL the replay reads directly.
# ============================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

ENRICHMENT_VERSION = "1.0"

# Bars of history before the decision. Indicators, VWAP and structure all need
# a warmup; too little and the analysis silently degrades to defaults.
WARMUP_DAYS = 5

# How many analysis points to compute along a trade. Each one is a full
# analysis pass, so this is the main cost driver.
MAX_PATH_POINTS = 6

TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1")

# How far back to pull EACH timeframe, in calendar days.
#
# One warmup figure cannot serve all of them. The components that fetch their
# own bars ask for a FIXED BAR COUNT, so the calendar span they need scales
# with the bar size, and the shim is fail-closed -- an under-filled timeframe
# makes the component report unavailable rather than wrong, but unavailable on
# every trade is just a slower way of learning nothing.
#
# Sized from what the consumers actually demand, with roughly 1.5x headroom
# for weekends and holidays:
#
#   H4  nested_zone_confluence wants 150 bars = 600h = 25 trading days
#   D1  adr_exhaustion wants ADR_LOOKBACK_DAYS + 1 = 21 trading days
#   H1  nested_zone 150 bars, trend_cascade EMA_PERIOD + 13
#
# M1 stays short deliberately: it is the base timeframe, it dominates the
# fetch cost at ~1,440 bars/day, and nothing asks it for a long history.
TIMEFRAME_WARMUP_DAYS = {
    "M1": WARMUP_DAYS,
    "M5": WARMUP_DAYS,
    "M15": 10,
    "H1": 30,
    "H4": 45,
    "D1": 60,
}


def _mt5():
    import MetaTrader5 as mt5
    return mt5


def _tf_map(mt5: Any) -> Dict[str, int]:
    return {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}


def build_feed(symbol: str, opened_epoch: int, closed_epoch: int,
               warmup_days: int = WARMUP_DAYS):
    """A HistoricalFeed covering warmup + the trade window."""
    from core.market_data import HistoricalFeed

    mt5 = _mt5()
    opened = datetime.fromtimestamp(opened_epoch, tz=timezone.utc)
    end = (datetime.fromtimestamp(closed_epoch, tz=timezone.utc)
           + timedelta(hours=2))

    rates_by_tf: Dict[str, Any] = {}
    for name, tf in _tf_map(mt5).items():
        # Per-timeframe warmup: an H4 or D1 consumer needs weeks of calendar
        # history to get its bar count, and starving it makes the shim serve
        # None on every trade. `warmup_days` still acts as a floor so an
        # explicit caller override cannot silently shorten a timeframe.
        days = max(warmup_days, TIMEFRAME_WARMUP_DAYS.get(name, warmup_days))
        rates = mt5.copy_rates_range(symbol, tf, opened - timedelta(days=days), end)
        if rates is not None and len(rates):
            rates_by_tf[name] = rates

    if "M1" not in rates_by_tf:
        return None

    info = mt5.symbol_info(symbol)
    pip = getattr(info, "point", None) or 0.0001
    return HistoricalFeed(rates_by_tf, symbol=symbol, base_timeframe="M1",
                          pip_size=pip, leverage=200, balance=10000.0)


def analyse_at(feed: Any, symbol: str, direction: str,
               timestamp: float, stats: Any = None) -> Optional[Dict[str, Any]]:
    """
    The real analysis at one moment, or None if it cannot be computed causally.

    Refuses on ANY look-ahead violation rather than proceeding with a warning.
    An analysis holding one bar of the future is worse than no analysis: it
    produces features that predict the outcome and generalise to nothing.

    Runs inside core.mt5_shim.replay_context so that components which fetch
    their own bars -- nested_zone, trend_cascade, adr_exhaustion, the H1/M15
    paths in indicators.py and calculations.py -- are served from the same
    causal feed instead of reaching the live terminal. Passing market_data
    alone is NOT sufficient: those components never look at it, and
    verify_no_lookahead cannot detect a fetch it never sees. `stats`, if
    given, accumulates which timeframes were served and which were missed,
    so starvation is observable rather than silent.
    """
    from core.asset_analysis import analyze_institutional_signal
    from core.mt5_shim import replay_context

    market_data = feed.at(float(timestamp))
    if market_data is None:
        return None
    if feed.verify_no_lookahead(float(timestamp), market_data):
        return None

    try:
        # strict=True: a timeframe the feed cannot cover returns None, and the
        # component reports unavailable. Falling through to the live terminal
        # is the contamination this context exists to remove.
        with replay_context(market_data, stats=stats, strict=True):
            return analyze_institutional_signal(
                symbol=symbol, order_type=direction,
                fixed_trade_size_usd=1000.0, risk_per_trade=1.0,
                leverage=200, timeframe="M1", use_gnn=False,
                market_data=market_data)
    except Exception:
        return None


def enrich_position(position: Mapping[str, Any],
                    path_points: int = MAX_PATH_POINTS,
                    warmup_days: int = WARMUP_DAYS,
                    stats: Any = None) -> Optional[Dict[str, Any]]:
    """
    One MT5 position, enriched into a full stored-trade document.

    Returns None when the analysis could not be computed causally, rather than
    emitting a trade with an empty or partial snapshot that downstream code
    would treat as a real one.
    """
    from .mt5_history import to_trade

    symbol = position["symbol"]
    opened, closed = position["opened_epoch"], position["closed_epoch"]
    feed = build_feed(symbol, opened, closed, warmup_days)
    if feed is None:
        return None

    opening = analyse_at(feed, symbol, position["direction"], opened, stats=stats)
    if not opening:
        return None

    # Evolution points, evenly spaced across the holding period. The close
    # itself is excluded: an analysis computed AT the close would carry the
    # outcome into a field the models read as pre-outcome.
    evolution: List[Dict[str, Any]] = []
    span = max(1, closed - opened)
    step = max(60, span // max(1, path_points))
    stamp = opened + step
    while stamp < closed and len(evolution) < path_points:
        market_data = feed.at(float(stamp))
        if market_data is not None and not feed.verify_no_lookahead(
                float(stamp), market_data):
            snapshot = analyse_at(feed, symbol, position["direction"], stamp,
                                  stats=stats)
            price = getattr(getattr(market_data, "tick", None), "bid", None)
            if snapshot and price:
                evolution.append({
                    "timestamp": datetime.fromtimestamp(
                        stamp, tz=timezone.utc).isoformat(),
                    "price": float(price),
                    "m1_analysis_raw": snapshot,
                    "_encoded": False,
                })
        stamp += step

    trade = to_trade(position, [])
    trade["analysis_at_open"] = opening
    trade["price_evolution"] = evolution
    trade["analysis_at_close"] = {
        "result": "WIN" if (position.get("profit") or 0) > 0 else "LOSS"}
    trade["has_decision_snapshot"] = True
    trade["snapshot_source"] = "recomputed_from_bars"
    trade["path_source"] = "m1_bars"
    # Which timeframes the shim could actually serve for THIS trade. A
    # component reporting unavailable is only trustworthy if we can show the
    # data was genuinely absent rather than never requested.
    trade["feed_timeframes"] = sorted(feed.rates_by_tf)
    return trade


def enrich(positions: Sequence[Mapping[str, Any]],
           path_points: int = MAX_PATH_POINTS,
           progress: bool = True) -> List[Dict[str, Any]]:
    """Enrich a set of positions. Failures are skipped, never guessed at."""
    from core.mt5_shim import ShimStats

    # One accumulator across the whole run: which timeframes the shim served
    # and which it could not. Printed at the end -- a component that measures
    # as inert should be explainable by a `missing` entry here, not guessed at.
    stats = ShimStats()
    out: List[Dict[str, Any]] = []
    for index, position in enumerate(positions, 1):
        trade = enrich_position(position, path_points, stats=stats)
        if trade:
            out.append(trade)
        if progress and index % 10 == 0:
            print("  enriched %d/%d (kept %d)" % (index, len(positions), len(out)),
                  flush=True)
    if progress:
        served = stats.as_dict()
        print("  shim served: %s" % (served["served"] or "nothing"))
        # A `missing` entry is the honest explanation for a component that
        # reports unavailable. Silence here would mean the component was never
        # even asking, which is a different problem.
        print("  shim missing: %s" % (served["missing"] or "nothing"))
    return out


def write_jsonl(trades: Sequence[Mapping[str, Any]], path: str) -> str:
    """
    Local JSONL, deliberately not Firebase.

    These are reconstructions. In the trades collection they would be
    indistinguishable from trades the bot actually recorded, and every model
    trained later would treat them as primary evidence.
    """
    with open(path, "w", encoding="utf-8") as handle:
        for trade in trades:
            handle.write(json.dumps(trade, default=str) + "\n")
    return path


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


def get_status() -> Dict[str, Any]:
    return {
        "component": "history_enrichment",
        "version": ENRICHMENT_VERSION,
        "recomputes": ["analysis_at_open", "per-point analysis along the path"],
        "real_from_broker": ["entry", "exit", "stop", "target", "profit"],
        "approximated": ["price path, from M1 closes rather than ticks"],
        "refuses_on_lookahead": True,
        "writes_to_firebase": False,
        "why_not_firebase": (
            "these are reconstructions; in the trades collection they would be "
            "indistinguishable from trades the bot actually recorded"),
        "warmup_days": WARMUP_DAYS,
        "max_path_points": MAX_PATH_POINTS,
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """Prove one position enriches causally, with a populated snapshot."""
    report: Dict[str, Any] = {
        "component": "history_enrichment", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        from .mt5_history import ensure_connected, load_positions

        checks["mt5_connected"] = ensure_connected()
        if not checks["mt5_connected"]:
            report["ok"] = None
            report["reason"] = "MT5 not reachable"
            return report

        positions = [p for p in load_positions(days=365) if p.get("stop_loss")]
        checks["positions"] = len(positions)
        if not positions:
            report["ok"] = None
            report["reason"] = "no positions with a stop"
            return report

        trade = enrich_position(positions[0], path_points=2)
        checks["enriched"] = trade is not None
        if trade:
            analysis = trade["analysis_at_open"]
            checks["snapshot_sections"] = len(analysis)
            # the payload files readings under analysis.<GROUP>.data.*
            # (core/analysis_groups.py); block() reads either shape
            from core.analysis_groups import block as _group_block
            checks["has_smc"] = bool(_group_block(analysis, "smc"))
            checks["has_indicators"] = bool(_group_block(analysis, "indicators"))
            checks["has_final_verdict"] = "final_verdict" in analysis
            checks["declares_recomputed"] = (
                trade["snapshot_source"] == "recomputed_from_bars")
            from .price_evolution_bridge import PriceEvolutionBridge

            canonical = PriceEvolutionBridge().to_canonical(dict(trade))
            checks["decodes_through_bridge"] = bool(
                canonical.get("analysis_at_open"))

        required = ("enriched", "has_smc", "has_final_verdict",
                    "declares_recomputed", "decodes_through_bridge")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "ENRICHMENT_VERSION", "build_feed", "analyse_at", "enrich_position",
    "enrich", "write_jsonl", "read_jsonl", "get_status", "self_check",
]
