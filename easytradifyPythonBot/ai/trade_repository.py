# ============================================================
# TRADE REPOSITORY -- THE BRIDGE BETWEEN THE TRADING DB AND THE AI
# ============================================================
# FILE: ai/trade_repository.py
#
# Every model in ai/ reads trades THROUGH this module. It is the one place
# that knows both halves: how the live system writes a trade, and what shape
# the models expect to read.
#
# WHY IT HAS TO EXIST
# -------------------
# The two shapes are not the same, and the gap between them was silent. What
# the monitor writes today:
#
#   analysis_at_open = {"m1_analysis_raw": <the analysis>, "_encoded": False, ...}
#   price_evolution  = [{"analysis": {"m1": <compact blob>}, "_encoded": True,
#                        "risk_state": {...}, ...}]
#
# What every model reads:
#
#   trade["analysis_at_open"]["final_verdict"]["probability_ledger"]
#   trade["price_evolution"][i]["analysis"]["m1"]["final_verdict"]
#
# Neither path resolved. `analysis_at_open` was an envelope nothing unwrapped,
# and `_canonical_point` tested for `_encoded` INSIDE `analysis` while the
# writer puts it beside `analysis` -- so every price point decoded to
# {"m1": {}, "m5": {}, "h1": {}}. A model walking the forward walk received a
# well-formed row with an empty analysis on every step, which reads as "this
# trade had no analysis" rather than "the decoder looked in the wrong place".
#
# Both are fixed in ai/price_evolution_bridge.py; this module is the seam that
# guarantees they are always applied, so no consumer can accidentally read the
# raw document and get the empty version.
#
# THE LEAKAGE BOUNDARY, RESTATED HERE BECAUSE IT IS EASY TO LOSE
# --------------------------------------------------------------
#   analysis_at_open + entry   what was known at T0   -> FEATURES
#   price_evolution            the forward walk       -> PATH / EXITS
#   close_data + analysis_at_close  the outcome       -> LABELS ONLY
#
# `load_training_set` returns those three separately rather than one merged
# dict, so a feature builder cannot reach outcome data by accident. Merging
# them and trusting discipline is how a model ends up predicting the past.
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional

logger = logging.getLogger(__name__)

TRADE_REPOSITORY_VERSION = "1.0"

# Fields that carry the outcome. Never part of a feature view.
OUTCOME_FIELDS = ("close_data", "analysis_at_close", "closed_at")


def _bridge():
    from ai.price_evolution_bridge import PriceEvolutionBridge
    return PriceEvolutionBridge()


def _service():
    from core.mongo import get_trades_service
    return get_trades_service()


# ============================================================
# READING
# ============================================================

def canonicalise(trade: Mapping[str, Any]) -> Dict[str, Any]:
    """
    One stored trade in the shape models read.

    Flattens the analysis envelope and decodes every price point. Public
    because the replay and enrichment paths hold trades that never went
    through Mongo and need the identical treatment.
    """
    if not isinstance(trade, Mapping):
        return {}
    return _bridge().to_canonical(dict(trade))


def load_trades(*, limit: Optional[int] = None, symbol: Optional[str] = None,
                status: Optional[str] = "CLOSED",
                opened_from: Optional[str] = None,
                opened_to: Optional[str] = None,
                include_deleted: bool = False) -> List[Dict[str, Any]]:
    """
    Trades from the live database, canonicalised, oldest first.

    Defaults to CLOSED because a model needs an outcome. An OPEN trade has no
    label, and including one silently adds a row whose target is missing --
    pass status=None deliberately if that is what you want.

    Chronological order is not cosmetic: every train/test split in this
    package is chronological, and a shuffled load would make an ordered split
    impossible to do correctly.
    """
    filters: Dict[str, Any] = {}
    if symbol:
        filters["symbol"] = symbol
    if status:
        filters["status"] = status

    rows: List[Dict[str, Any]] = []
    for doc in _service().iter_trades(
            filters=filters, opened_from=opened_from, opened_to=opened_to,
            include_deleted=include_deleted, include_heavy=True):
        rows.append(canonicalise(doc))
        if limit and len(rows) >= int(limit):
            break

    rows.sort(key=lambda t: str(t.get("opened_at") or ""))
    return rows


def iter_trades(*, symbol: Optional[str] = None,
                status: Optional[str] = "CLOSED",
                batch_size: int = 25, **kwargs) -> Iterator[Dict[str, Any]]:
    """
    Stream canonicalised trades without materialising them all.

    A trade with its forward walk is megabytes; 200 of them at once is
    gigabytes resident for no reason. Use this for training passes over the
    whole collection and `load_trades` when the set is small and order matters.
    """
    filters: Dict[str, Any] = {}
    if symbol:
        filters["symbol"] = symbol
    if status:
        filters["status"] = status
    for doc in _service().iter_trades(filters=filters, batch_size=batch_size,
                                      include_heavy=True, **kwargs):
        yield canonicalise(doc)


def get_trade(trade_id: Any) -> Dict[str, Any]:
    """One canonicalised trade."""
    return canonicalise(_service().get_trade(trade_id))


# ============================================================
# THE LEAKAGE-SAFE VIEW
# ============================================================

def load_training_set(**kwargs) -> Dict[str, Any]:
    """
    Trades split into the three views the firewall defines.

    Returns {"features": [...], "path": [...], "labels": [...]} with one entry
    per trade at the same index. Kept SEPARATE rather than merged: a feature
    builder handed a merged dict can reach close_data with a typo, and the
    resulting model looks excellent and generalises to nothing. This package
    has caught that failure more than once, which is why the separation is
    structural instead of a convention.
    """
    trades = load_trades(**kwargs)
    features, path, labels = [], [], []

    for trade in trades:
        features.append({
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol"),
            "direction": trade.get("direction"),
            "opened_at": trade.get("opened_at"),
            "entry": trade.get("entry") or {},
            "analysis_at_open": trade.get("analysis_at_open") or {},
        })
        path.append({
            "trade_id": trade.get("trade_id"),
            "price_evolution": trade.get("price_evolution") or [],
        })
        close = trade.get("close_data") or {}
        labels.append({
            "trade_id": trade.get("trade_id"),
            "profit_usd": close.get("profit_usd"),
            "close_price": close.get("close_price"),
            "close_reason": close.get("close_reason"),
            "r_multiple": _r_multiple(trade),
            "is_win": (close.get("profit_usd") or 0) > 0,
        })

    return {"features": features, "path": path, "labels": labels,
            "count": len(trades)}


def _r_multiple(trade: Mapping[str, Any]) -> Optional[float]:
    """
    Outcome in R -- the only cross-symbol comparable measure.

    $10 on gold and $10 on EURUSD are not the same risk, so averaging dollars
    across symbols produces a number describing neither.
    """
    entry = trade.get("entry") or {}
    close = trade.get("close_data") or {}
    ep, sl, cp = entry.get("price"), entry.get("stop_loss"), close.get("close_price")
    if not all(isinstance(v, (int, float)) for v in (ep, sl, cp)):
        return None
    risk = abs(ep - sl)
    if not risk:
        return None
    sign = 1 if trade.get("direction") == "BUY" else -1
    return round(sign * (cp - ep) / risk, 6)


def ledger_of(trade: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """
    The probability ledger from a canonicalised trade.

    Every component measurement in this package starts here, and it is the
    field that was unreachable in the stored shape -- so it gets a named
    accessor rather than being re-derived at each call site.
    """
    analysis = trade.get("analysis_at_open") or {}
    verdict = analysis.get("final_verdict") or {}
    return [s for s in (verdict.get("probability_ledger") or [])
            if isinstance(s, dict) and s.get("step")]


def best_direction_of(trade: Mapping[str, Any]) -> Optional[str]:
    """
    The direction the ANALYSIS chose, which is not always the one traded.

    Every chained scorer signs its contribution against best_direction, so a
    ledger delta cannot be interpreted without it. Measured on 215 real
    trades, reading the deltas in the wrong frame turned a +0.49R component
    edge into an apparent sign error -- and best_direction differed from the
    traded direction on 19% of them.
    """
    analysis = trade.get("analysis_at_open") or {}
    if analysis.get("best_direction"):
        return analysis["best_direction"]
    for value in analysis.values():
        if isinstance(value, dict) and value.get("best_direction"):
            return value["best_direction"]
    return None


# ============================================================
# STATUS / SELF CHECK -- the convention every module here follows
# ============================================================

def get_status() -> Dict[str, Any]:
    """What this bridge is connected to and how much it can see."""
    status: Dict[str, Any] = {
        "component": "trade_repository",
        "version": TRADE_REPOSITORY_VERSION,
        "source": "mongodb",
    }
    try:
        service = _service()
        status["healthy"] = service.is_healthy()
        if status["healthy"]:
            status["trades_total"] = service.count_trades()
            status["trades_closed"] = service.count_trades(
                filters={"status": "CLOSED"})
            status["trades_open"] = service.count_trades(
                filters={"status": "OPEN"})
    except Exception as exc:
        status["healthy"] = False
        status["error"] = str(exc)
    return status


def self_check(trades: Optional[Iterable[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the bridge actually resolves the live shape.

    `ok` is TRI-STATE. None means "not exercised" -- an empty database cannot
    demonstrate that decoding works, and reporting True there would be a check
    that cannot fail, which is indistinguishable from a stub returning success.
    """
    report: Dict[str, Any] = {
        "component": "trade_repository",
        "version": TRADE_REPOSITORY_VERSION,
        "ok": None,
        "checks": {},
    }
    checks = report["checks"]

    try:
        rows = list(trades) if trades is not None else load_trades(limit=5,
                                                                   status=None)
    except Exception as exc:
        report["ok"] = False
        report["error"] = f"could not load trades: {exc}"
        return report

    checks["trades_examined"] = len(rows)
    if not rows:
        report["reason"] = ("no trades in the database; decoding was not "
                            "exercised")
        return report

    with_open = [t for t in rows if (t.get("analysis_at_open") or {})]
    with_verdict = [t for t in with_open
                    if (t.get("analysis_at_open") or {}).get("final_verdict")]
    with_ledger = [t for t in with_open if ledger_of(t)]
    with_points = [t for t in rows if (t.get("price_evolution") or [])]

    decoded_points = 0
    empty_points = 0
    for trade in with_points:
        for point in trade["price_evolution"]:
            m1 = ((point.get("analysis") or {}).get("m1")) or {}
            if m1.get("final_verdict"):
                decoded_points += 1
            else:
                empty_points += 1

    checks["analysis_at_open_present"] = len(with_open)
    checks["analysis_at_open_flattened"] = len(with_verdict)
    checks["probability_ledger_reachable"] = len(with_ledger)
    checks["trades_with_price_points"] = len(with_points)
    checks["price_points_decoded"] = decoded_points
    checks["price_points_empty"] = empty_points
    checks["best_direction_resolved"] = sum(
        1 for t in rows if best_direction_of(t))

    problems = []
    if with_open and not with_verdict:
        problems.append(
            "analysis_at_open is present but final_verdict is unreachable -- "
            "the envelope is not being flattened")
    if with_points and decoded_points == 0:
        problems.append(
            "price points exist but none decoded to an analysis -- the "
            "forward walk is arriving empty, which every model reads as "
            "'this trade had no analysis'")

    report["problems"] = problems
    report["ok"] = not problems
    return report
