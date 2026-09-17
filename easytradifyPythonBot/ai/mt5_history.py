# ============================================================
# MT5 HISTORY -> REPLAY INPUT
# ============================================================
#
# WHY THIS EXISTS
# ---------------
# The `trades` collection in Firestore is empty, so replay had nothing to
# read. The trades themselves were never missing -- they are in the MT5
# account history, 246 closed positions of them. They simply never reached
# Firebase, because the analysis layer that writes those documents was not
# running (or was writing into the offline queue that never flushed).
#
# This reconstructs a replayable trade from what the broker kept.
#
# WHAT IS RECOVERABLE, AND WHAT IS NOT
# ------------------------------------
# The broker records the ORDER, not the reasoning:
#
#   recoverable   entry price, exit price, direction, volume, open and close
#                 times, realised profit, SL and TP as submitted
#   reconstructed the price path between open and close, from M5 bars
#   ABSENT        analysis_at_open -- every SMC read, indicator, session,
#                 volume-profile and probability the bot computed at decision
#                 time
#
# That last line decides what can be measured. Any model whose features come
# from the decision snapshot (abstention's conditions, calibration's stated
# probability, GNN context, trade quality) CANNOT run on this history, and
# this module says so rather than substituting a plausible default. Models
# that read the PATH -- exit, target, stress, counterfactuals -- run normally,
# and those are precisely the ones that target payoff asymmetry.
#
# THE PATH IS BARS, NOT TICKS
# ---------------------------
# `price_evolution` here is reconstructed from M5 closes, not from the live
# tick stream the bot would have recorded. It is an approximation of what the
# trade experienced: a stop touched intrabar between two M5 closes is invisible
# to it. Every trade produced here is stamped `path_source: "m5_bars"` so a
# result computed on it can never be mistaken for one computed on recorded
# ticks.
# ============================================================

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MT5_HISTORY_VERSION = "1.0"

# M5 keeps a 246-trade backfill fast while still resolving intraday shape.
DEFAULT_TIMEFRAME = "M5"

# Bars either side of the trade, so a path is never a single point.
PATH_PADDING_BARS = 2


def _mt5():
    import MetaTrader5 as mt5
    return mt5


def _timeframe(mt5: Any, name: str) -> int:
    return {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
    }.get(str(name).upper(), mt5.TIMEFRAME_M5)


def _iso(epoch: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
    except Exception:
        return None


def ensure_connected() -> bool:
    """True when MT5 is reachable. Never raises: absence is a normal state."""
    try:
        mt5 = _mt5()
        return bool(mt5.initialize())
    except Exception:
        return False


def load_positions(days: int = 365,
                   start: Optional[datetime] = None,
                   end: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Closed positions, built by pairing each IN deal with its OUT deal.

    Paired on `position_id` rather than by order of arrival: partial closes and
    reversals put several deals on one position, and pairing positionally would
    silently mis-attribute an exit to the wrong entry.
    """
    if not ensure_connected():
        return []

    mt5 = _mt5()
    end = end or datetime.now()
    start = start or (end - timedelta(days=days))

    deals = mt5.history_deals_get(start, end) or []
    orders = mt5.history_orders_get(start, end) or []

    # SL and TP live on the ORDER, never on the deal.
    protection: Dict[int, Dict[str, float]] = {}
    for order in orders:
        position_id = getattr(order, "position_id", 0)
        if not position_id:
            continue
        stop = float(getattr(order, "sl", 0.0) or 0.0)
        target = float(getattr(order, "tp", 0.0) or 0.0)
        existing = protection.setdefault(position_id, {"sl": 0.0, "tp": 0.0})
        # Keep the first non-zero of each: a later modification would overwrite
        # the level the trade was actually opened against.
        if stop and not existing["sl"]:
            existing["sl"] = stop
        if target and not existing["tp"]:
            existing["tp"] = target

    grouped: Dict[int, Dict[str, Any]] = {}
    for deal in deals:
        position_id = getattr(deal, "position_id", 0)
        if not position_id:
            continue
        entry = getattr(deal, "entry", None)
        bucket = grouped.setdefault(position_id, {"in": [], "out": []})
        if entry == 0:
            bucket["in"].append(deal)
        elif entry == 1:
            bucket["out"].append(deal)

    positions: List[Dict[str, Any]] = []
    for position_id, bucket in grouped.items():
        if not bucket["in"] or not bucket["out"]:
            continue   # still open, or an unpaired fragment
        opener = bucket["in"][0]
        closer = bucket["out"][-1]
        levels = protection.get(position_id, {})

        positions.append({
            "position_id": position_id,
            "symbol": opener.symbol,
            # MT5 deal type 0 is BUY, 1 is SELL.
            "direction": "BUY" if opener.type == 0 else "SELL",
            "entry_price": float(opener.price),
            "exit_price": float(closer.price),
            "volume": float(opener.volume),
            "opened_at": _iso(opener.time),
            "closed_at": _iso(closer.time),
            "opened_epoch": int(opener.time),
            "closed_epoch": int(closer.time),
            "profit": float(sum(d.profit for d in bucket["out"])),
            "commission": float(sum(getattr(d, "commission", 0.0) for d in deals
                                    if getattr(d, "position_id", 0) == position_id)),
            "swap": float(sum(getattr(d, "swap", 0.0) for d in bucket["out"])),
            "stop_loss": levels.get("sl") or None,
            "take_profit": levels.get("tp") or None,
            "close_reason": _close_reason(closer),
            "partial_closes": len(bucket["out"]) - 1,
        })

    positions.sort(key=lambda p: p["opened_epoch"])
    return positions


def _close_reason(deal: Any) -> str:
    """
    MT5 reason codes, mapped to the vocabulary the rest of the package uses.

    Code 4 is a stop-loss hit and 5 a take-profit; both are far more
    informative than "CLOSED", because exit_model and target_model are
    entirely about which of the two happened and when.
    """
    reason = getattr(deal, "reason", None)
    return {
        0: "CLIENT", 1: "MOBILE", 2: "WEB", 3: "EXPERT",
        4: "STOP_LOSS", 5: "TAKE_PROFIT", 6: "STOP_OUT",
    }.get(reason, "CLOSED")


def fetch_path(symbol: str, opened_epoch: int, closed_epoch: int,
               timeframe: str = DEFAULT_TIMEFRAME) -> List[Dict[str, Any]]:
    """
    The price path a trade lived through, from M5 bars.

    Bars, not ticks: a stop touched and released between two closes does not
    appear here. That limitation is stamped on every trade this module emits.
    """
    if not ensure_connected():
        return []
    mt5 = _mt5()

    try:
        span = mt5.TIMEFRAME_M5 if timeframe.upper() == "M5" else _timeframe(
            mt5, timeframe)
        minutes = 5 if timeframe.upper() == "M5" else 1
        start = datetime.fromtimestamp(
            opened_epoch - PATH_PADDING_BARS * minutes * 60, tz=timezone.utc)
        end = datetime.fromtimestamp(
            closed_epoch + PATH_PADDING_BARS * minutes * 60, tz=timezone.utc)
        rates = mt5.copy_rates_range(symbol, span, start, end)
    except Exception:
        return []

    if rates is None or not len(rates):
        return []

    path: List[Dict[str, Any]] = []
    for bar in rates:
        timestamp = _iso(bar["time"])
        if timestamp is None:
            continue
        path.append({
            "timestamp": timestamp,
            "price": float(bar["close"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "volume": {"tick_volume": int(bar["tick_volume"])},
        })
    return path


def to_trade(position: Mapping[str, Any],
             path: Optional[Sequence[Mapping[str, Any]]] = None
             ) -> Dict[str, Any]:
    """
    One MT5 position as a stored-trade document the bridge can decode.

    `analysis_at_open` is deliberately EMPTY, not a plausible placeholder. The
    reasoning behind these trades was never recorded, and inventing a snapshot
    would hand every downstream model fabricated features that look exactly
    like measured ones.
    """
    entry_price = position.get("entry_price")
    stop = position.get("stop_loss")
    profit = position.get("profit") or 0.0

    return {
        "trade_id": str(position.get("position_id")),
        "ticket": position.get("position_id"),
        "symbol": position.get("symbol"),
        "direction": position.get("direction"),
        "status": "CLOSED",
        "opened_at": position.get("opened_at"),
        "closed_at": position.get("closed_at"),
        "entry": {
            "price": entry_price,
            "volume": position.get("volume"),
            "stop_loss": stop,
            "take_profit": position.get("take_profit"),
        },
        # Absent, and said so. See the module header.
        "analysis_at_open": {},
        "price_evolution": list(path or []),
        "close_data": {
            "close_price": position.get("exit_price"),
            "close_reason": position.get("close_reason"),
            "profit_usd": profit,
            "is_winning": profit > 0,
            "duration_seconds": max(
                0, (position.get("closed_epoch") or 0)
                - (position.get("opened_epoch") or 0)),
        },
        "source": "mt5_history",
        "path_source": "m5_bars",
        "has_decision_snapshot": False,
        "partial_closes": position.get("partial_closes", 0),
    }


def load_trades(days: int = 365, limit: Optional[int] = None,
                with_paths: bool = True,
                require_stop: bool = True) -> List[Dict[str, Any]]:
    """
    Replay-ready trades from MT5 history.

    `require_stop` defaults True because R is defined as the distance to the
    stop. A trade with no stop has no R, and every expectancy figure in this
    package is denominated in R -- including one silently treated as 1.0 would
    corrupt every mean it entered.
    """
    positions = load_positions(days=days)
    trades: List[Dict[str, Any]] = []
    for position in positions:
        if require_stop and not position.get("stop_loss"):
            continue
        path = (fetch_path(position["symbol"], position["opened_epoch"],
                           position["closed_epoch"]) if with_paths else [])
        trades.append(to_trade(position, path))
        if limit and len(trades) >= limit:
            break
    return trades


def coverage(days: int = 365) -> Dict[str, Any]:
    """
    What this history can and cannot support, before anything is run on it.

    Exists so the limits are a measurement taken up front rather than a
    surprise discovered halfway through a promotion report.
    """
    positions = load_positions(days=days)
    if not positions:
        return {"available": False,
                "reason": "MT5 unreachable or no closed positions in range"}

    with_stop = [p for p in positions if p.get("stop_loss")]
    with_target = [p for p in positions if p.get("take_profit")]
    wins = [p for p in positions if (p.get("profit") or 0) > 0]

    return {
        "available": True,
        "version": MT5_HISTORY_VERSION,
        "positions": len(positions),
        "with_stop_loss": len(with_stop),
        "with_take_profit": len(with_target),
        "usable_for_r_metrics": len(with_stop),
        "win_rate": round(len(wins) / len(positions), 4),
        "total_profit": round(sum(p.get("profit") or 0 for p in positions), 2),
        "date_range": [positions[0]["opened_at"], positions[-1]["closed_at"]],
        "symbols": sorted({p["symbol"] for p in positions}),
        "has_decision_snapshots": False,
        "cannot_evaluate": [
            "abstention_model (conditions come from analysis_at_open)",
            "calibration_model (no stated probability was recorded)",
            "gnn / trade_quality (no decision-time context)",
        ],
        "can_evaluate": [
            "exit_model", "target_model", "stress replay",
            "counterfactual branching", "performance scorecards",
        ],
        "path_source": "m5_bars, not recorded ticks",
    }


def get_status() -> Dict[str, Any]:
    return {
        "component": "mt5_history",
        "version": MT5_HISTORY_VERSION,
        "connected": ensure_connected(),
        "recovers": ["entry", "exit", "direction", "volume", "times",
                     "profit", "sl", "tp"],
        "reconstructs": ["price_evolution from M5 bars"],
        "cannot_recover": ["analysis_at_open (the reasoning was never stored)"],
        "invents_missing_analysis": False,
        "path_source": "m5_bars",
        "intrabar_limitation": (
            "a stop touched and released between two M5 closes is invisible; "
            "results here are an approximation of what the trade experienced"),
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the pairing, the R denominator and the honesty of the empty snapshot.

    `analysis_is_empty_not_invented` is load-bearing: a fabricated decision
    snapshot would give every downstream model features that look measured and
    are not, which is the one failure this package cannot detect after the
    fact.
    """
    report: Dict[str, Any] = {
        "component": "mt5_history", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        checks["mt5_connected"] = ensure_connected()
        if not checks["mt5_connected"]:
            report["ok"] = None
            report["reason"] = "MT5 not reachable; nothing to adapt"
            return report

        positions = load_positions(days=365)
        checks["positions_found"] = len(positions)
        if not positions:
            report["ok"] = None
            report["reason"] = "MT5 reachable but no closed positions in range"
            return report

        # Every paired position must have both legs and a sane direction.
        checks["all_have_both_legs"] = all(
            p.get("entry_price") and p.get("exit_price") for p in positions)
        checks["directions_valid"] = all(
            p.get("direction") in ("BUY", "SELL") for p in positions)
        checks["times_ordered"] = all(
            p["closed_epoch"] >= p["opened_epoch"] for p in positions)

        sample = next((p for p in positions if p.get("stop_loss")), None)
        checks["some_have_stops"] = sample is not None
        if sample:
            trade = to_trade(sample, fetch_path(
                sample["symbol"], sample["opened_epoch"], sample["closed_epoch"]))
            checks["analysis_is_empty_not_invented"] = (
                trade["analysis_at_open"] == {})
            checks["path_source_declared"] = trade["path_source"] == "m5_bars"
            checks["path_has_points"] = len(trade["price_evolution"]) > 0

            # The whole point: it has to survive the decode boundary.
            from .price_evolution_bridge import PriceEvolutionBridge

            canonical = PriceEvolutionBridge().to_canonical(dict(trade))
            checks["decodes_through_the_bridge"] = bool(
                (canonical.get("entry") or {}).get("price"))
            checks["risk_is_defined"] = bool(
                (canonical.get("entry") or {}).get("stop_loss"))

        required = ("all_have_both_legs", "directions_valid", "times_ordered",
                    "some_have_stops", "analysis_is_empty_not_invented",
                    "path_source_declared", "decodes_through_the_bridge")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "MT5_HISTORY_VERSION", "ensure_connected", "load_positions", "fetch_path",
    "to_trade", "load_trades", "coverage", "get_status", "self_check",
]
