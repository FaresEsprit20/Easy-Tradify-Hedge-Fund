# ============================================================
# EXPOSURE RISK -- WHAT UNLIMITED CONCURRENCY ACTUALLY COSTS
# ============================================================
# FILE: core/exposure_risk.py
#
# WHY THIS EXISTS
# ---------------
# MAX_SIMULTANEOUS_TRADES and MAX_TRADES_PER_SYMBOL were raised to 100000 to
# collect data faster. That change is sound for throughput and has two
# consequences nobody asked about, both of which get worse the better it works:
#
# 1. RISK. Ten EURUSD longs opened within minutes are not ten independent
#    trades at 1% risk each. They are ONE bet at 10% risk. Every position
#    sizing calculation in this system reasons per-trade, so the account can
#    be carrying ten times its intended exposure while every individual
#    number looks correct. Nothing in the codebase measures this.
#
# 2. STATISTICS. Those same ten trades carry roughly ONE trade's worth of
#    information about whether the strategy works. Treating them as ten
#    independent samples shrinks every confidence interval by ~sqrt(10) and
#    makes noise look significant. Given that the whole point of the
#    collection run is to resolve edges that currently sit at p=0.08, this
#    would actively produce false discoveries -- the failure mode this
#    project has hit repeatedly.
#
# WHAT IT MEASURES
# ----------------
#   concurrent_exposure   summed risk of everything open right now, and the
#                         same figure grouped by symbol and by correlation
#                         cluster
#   effective_bets        how many INDEPENDENT bets that exposure represents.
#                         Ten identical trades is one bet; ten uncorrelated
#                         trades is ten.
#   uniqueness            per trade, the fraction of its life during which it
#                         was NOT overlapped by a correlated trade. This is
#                         the weight downstream statistics must use.
#
# The uniqueness weighting follows the standard treatment of overlapping
# labels in financial ML: a sample that shares its outcome window with others
# should not count as a full observation.
#
# THIS MODULE DOES NOT BLOCK TRADES. It measures and reports. Turning a
# measurement into a veto without validating it is how this codebase acquired
# several of the defects found this session.
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

EXPOSURE_RISK_VERSION = "1.0"

# Instruments sharing a dominant currency move together. This is a coarse
# grouping, not a correlation matrix: a fabricated precise correlation would
# be worse than an honest approximation, and the currency legs are the part
# that is genuinely knowable without estimation.
CURRENCY_GROUPS = ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF",
                   "XAU", "XAG")

# How much of a position's risk counts as shared with another in the same
# cluster. Same symbol is 1.0 by definition; a shared currency leg is
# partial and deliberately conservative -- overstating independence is the
# dangerous direction.
SAME_SYMBOL_OVERLAP = 1.0
SHARED_CURRENCY_OVERLAP = 0.5


def currencies_of(symbol: str) -> Tuple[str, ...]:
    """The currency legs in a symbol, e.g. EURUSD -> (EUR, USD)."""
    upper = str(symbol or "").upper()
    return tuple(c for c in CURRENCY_GROUPS if c in upper)


def correlation_weight(a: str, b: str) -> float:
    """
    How much two positions overlap, in [0, 1].

    1.0 = the same instrument, so the risks add exactly.
    0.5 = a shared currency leg, e.g. EURUSD and GBPUSD.
    0.0 = no shared leg.

    Direction is handled by the caller: two LONGS on EURUSD add, a long and a
    short partially offset, and conflating those would report a hedged book as
    a concentrated one.
    """
    if not a or not b:
        return 0.0
    if str(a).upper() == str(b).upper():
        return SAME_SYMBOL_OVERLAP
    shared = set(currencies_of(a)) & set(currencies_of(b))
    return SHARED_CURRENCY_OVERLAP if shared else 0.0


def _direction_sign(position: Mapping[str, Any]) -> int:
    value = position.get("direction") or position.get("type")
    if isinstance(value, str):
        return 1 if value.upper() == "BUY" else -1
    # MT5 position type: 0 = buy, 1 = sell
    return 1 if value == 0 else -1


def concurrent_exposure(positions: Sequence[Mapping[str, Any]]
                        ) -> Dict[str, Any]:
    """
    True exposure of a set of simultaneously open positions.

    `risk` per position is whatever the caller records as money at risk
    (actual_risk_usd, or volume as a proxy). The point is not the absolute
    figure but the RATIO between nominal and correlation-adjusted risk: when
    that ratio is 1.0 the book is diversified, and when it approaches the
    position count the book is one bet wearing many hats.
    """
    rows = [p for p in (positions or []) if p.get("symbol")]
    if not rows:
        return {"positions": 0, "nominal_risk": 0.0,
                "correlated_risk": 0.0, "concentration": None,
                "effective_bets": 0.0, "by_symbol": {}}

    def risk_of(p):
        for key in ("actual_risk_usd", "risk_usd", "volume"):
            value = p.get(key)
            if isinstance(value, (int, float)) and value:
                return abs(float(value))
        return 1.0

    nominal = sum(risk_of(p) for p in rows)

    # Correlation-adjusted: sum over every PAIR, so ten identical positions
    # cost what ten identical positions actually cost rather than ten times
    # one position's isolated risk.
    total = 0.0
    for i, a in enumerate(rows):
        for j, b in enumerate(rows):
            weight = correlation_weight(a["symbol"], b["symbol"])
            if i != j:
                # Opposite directions on correlated instruments offset.
                weight *= 1.0 if _direction_sign(a) == _direction_sign(b) else -1.0
            total += weight * risk_of(a) * risk_of(b)
    correlated = max(0.0, total) ** 0.5

    by_symbol: Dict[str, Dict[str, Any]] = {}
    for p in rows:
        entry = by_symbol.setdefault(p["symbol"], {"count": 0, "risk": 0.0,
                                                   "net_direction": 0})
        entry["count"] += 1
        entry["risk"] += risk_of(p)
        entry["net_direction"] += _direction_sign(p)

    # Effective independent bets = (sum of risks)^2 / (portfolio risk)^2.
    #
    # ✅ FIXED: this was (correlated / per_position)^2, which is INVERTED --
    # ten identical positions reported 100 independent bets instead of 1, the
    # exact opposite of the truth, and would have described a tenfold
    # concentrated book as maximally diversified. Caught by self_check, which
    # requires an identical book to report ~1 bet.
    #
    # Sanity: N identical positions -> (Ns)^2/(Ns)^2 = 1 bet.
    #         N uncorrelated ones   -> (Ns)^2/(s*sqrt(N))^2 = N bets.
    effective = (nominal / correlated) ** 2 if correlated else 0.0

    return {
        "positions": len(rows),
        "nominal_risk": round(nominal, 2),
        "correlated_risk": round(correlated, 2),
        # >1 means the book is more concentrated than the position count
        # suggests. This is the number that matters.
        "concentration": round(correlated / nominal, 3) if nominal else None,
        "effective_bets": round(effective, 2),
        "independence": round(effective / len(rows), 3) if rows else None,
        "by_symbol": {k: {"count": v["count"], "risk": round(v["risk"], 2),
                          "net_direction": v["net_direction"]}
                      for k, v in sorted(by_symbol.items())},
        "largest_symbol_share": round(
            max(v["risk"] for v in by_symbol.values()) / nominal, 3
        ) if nominal else None,
    }


# ============================================================
# UNIQUENESS -- the weight downstream statistics must use
# ============================================================

def _epoch(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except Exception:
        return None


def trade_uniqueness(trades: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """
    Per trade, what fraction of its life was NOT shared with a correlated trade.

    A trade overlapped for its whole life by a correlated one is worth ~0.5 of
    an observation, not 1.0. Two hundred heavily overlapping trades can carry
    the information of fifty, and treating them as two hundred shrinks every
    confidence interval by ~2x -- which manufactures significance exactly where
    the current edges sit (p=0.077, p=0.018).

    Returns a weight in (0, 1] per trade, to be used in every downstream
    expectancy, win-rate and permutation calculation once concurrency is high.
    """
    rows = []
    for trade in trades or []:
        start = _epoch(trade.get("opened_at") or trade.get("opened_epoch"))
        end = _epoch(trade.get("closed_at") or trade.get("closed_epoch"))
        if start is None or end is None or end <= start:
            continue
        rows.append({"trade_id": trade.get("trade_id"),
                     "symbol": trade.get("symbol"),
                     "start": start, "end": end,
                     "sign": _direction_sign(trade)})
    if not rows:
        return []

    out = []
    for row in rows:
        span = row["end"] - row["start"]
        # Concurrency measured on a grid across the trade's life: at each
        # moment, how much correlated exposure was alongside it.
        steps = 20
        loads = []
        for k in range(steps):
            moment = row["start"] + span * (k + 0.5) / steps
            load = 1.0
            for other in rows:
                if other is row:
                    continue
                if other["start"] <= moment <= other["end"]:
                    weight = correlation_weight(row["symbol"], other["symbol"])
                    if weight and other["sign"] == row["sign"]:
                        load += weight
            loads.append(load)
        average_load = sum(loads) / len(loads)
        out.append({
            "trade_id": row["trade_id"],
            "symbol": row["symbol"],
            "average_concurrent_load": round(average_load, 3),
            # The standard treatment: a sample sharing its window with others
            # counts for a fraction of an observation.
            "uniqueness": round(1.0 / average_load, 4),
        })
    return out


def effective_sample_size(trades: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    How many INDEPENDENT trades a set really represents.

    The single most important number for interpreting any statistic computed
    on a high-concurrency collection run. If 1,000 trades have an effective
    sample size of 300, then every p-value computed as if n=1000 is wrong by
    the square root of three.
    """
    weights = trade_uniqueness(trades)
    if not weights:
        return {"trades": 0, "effective": 0.0, "ratio": None}
    total = sum(w["uniqueness"] for w in weights)
    return {
        "trades": len(weights),
        "effective": round(total, 1),
        "ratio": round(total / len(weights), 3),
        "mean_concurrent_load": round(
            sum(w["average_concurrent_load"] for w in weights) / len(weights), 3),
        "note": ("statistics computed as if every trade were independent are "
                 "overconfident by roughly sqrt(trades / effective)"),
    }


# ============================================================
# LIVE SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    """Exposure of what is open at the broker right now."""
    try:
        import MetaTrader5 as mt5
        positions = mt5.positions_get()
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    if positions is None:
        return {"available": False, "reason": "MT5 returned no positions"}

    rows = []
    for p in positions:
        rows.append({"symbol": getattr(p, "symbol", None),
                     "type": getattr(p, "type", 0),
                     "volume": getattr(p, "volume", 0.0)})
    report = concurrent_exposure(rows)
    report["available"] = True
    return report


def get_status() -> Dict[str, Any]:
    return {"component": "exposure_risk", "version": EXPOSURE_RISK_VERSION,
            "same_symbol_overlap": SAME_SYMBOL_OVERLAP,
            "shared_currency_overlap": SHARED_CURRENCY_OVERLAP,
            "blocks_trades": False}


def self_check() -> Dict[str, Any]:
    """
    Prove the measure distinguishes a concentrated book from a diversified one.

    Ten identical positions must report ~1 effective bet; ten unrelated ones
    must report ~10. A measure that cannot tell those apart would report a 10x
    concentrated account as safe.
    """
    same = [{"symbol": "EURUSD", "direction": "BUY", "volume": 1.0}
            for _ in range(10)]
    varied = [{"symbol": s, "direction": "BUY", "volume": 1.0}
              for s in ("EURUSD", "XAUUSD", "US30", "NAS100", "UKOIL",
                        "SPX500", "DAX40", "AAPL", "MSFT", "NVDA")]
    hedged = ([{"symbol": "EURUSD", "direction": "BUY", "volume": 1.0}] * 5 +
              [{"symbol": "EURUSD", "direction": "SELL", "volume": 1.0}] * 5)

    a = concurrent_exposure(same)
    b = concurrent_exposure(varied)
    c = concurrent_exposure(hedged)

    # overlapping trades must weigh less than one observation each
    overlapping = [{"trade_id": "t%d" % i, "symbol": "EURUSD",
                    "direction": "BUY", "opened_at": 1000, "closed_at": 2000}
                   for i in range(5)]
    ess = effective_sample_size(overlapping)

    checks = {
        "identical_book_is_one_bet": a["effective_bets"] <= 1.5,
        "varied_book_is_many_bets": b["effective_bets"] >= 5.0,
        "hedged_book_nets_down": c["correlated_risk"] < a["correlated_risk"],
        "overlap_reduces_sample": ess["effective"] < 2.0,
        "identical_effective_bets": a["effective_bets"],
        "varied_effective_bets": b["effective_bets"],
        "overlapping_effective_n": ess["effective"],
    }
    return {"component": "exposure_risk", "version": EXPOSURE_RISK_VERSION,
            "checks": checks,
            "ok": (checks["identical_book_is_one_bet"]
                   and checks["varied_book_is_many_bets"]
                   and checks["hedged_book_nets_down"]
                   and checks["overlap_reduces_sample"])}
