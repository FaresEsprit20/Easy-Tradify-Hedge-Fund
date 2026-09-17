# ============================================================
# MICROSTRUCTURE FEATURES -- THE CHANNEL THIS SYSTEM WAS BLIND TO
# ============================================================
# FILE: core/microstructure_features.py
#
# WHY THIS EXISTS
# ---------------
# Every feature this system trades on is derived from M1 BARS. A bar is a
# summary of hundreds or thousands of ticks: on XAUUSD, 28,647 ticks arrive in
# thirty minutes and the analysis reduces them to one scalar,
# `timing_confidence`, which then falls back to a constant 50 whenever the
# tick fetch fails. So the richest, fastest information the broker provides is
# either compressed to a single number or discarded entirely.
#
# That matters because of what was measured on 215 real trades: direction
# entropy 1.0000. The bar-level features carry NO directional information.
# Seven separate hypotheses over those features -- component inversion, 82
# entry filters, 2,560 rule configurations, exit geometry, MAE early warning,
# log-odds aggregation, probability inversion -- all died in walk-forward
# validation.
#
# They died for the same reason: they were all re-slicing the SAME
# information. 215 trades x ~20 bar features has a finite information content,
# and no technique redistributes it into an edge. A different edge needs
# different information, and tick microstructure is the largest untapped
# source available -- it operates on a timescale the system currently cannot
# see at all.
#
# WHAT IS COMPUTED, AND WHY EACH ONE
# ----------------------------------
# Order flow imbalance    who is crossing the spread. Aggressive buyers lift
#                         the ask, aggressive sellers hit the bid. This is the
#                         closest thing to seeing intent in retail data, and
#                         it is invisible in a bar.
# Spread dynamics         spread widens before volatility and around news.
#                         Already recorded on every price point and used by
#                         nothing.
# Tick intensity          arrival rate against its own baseline. A burst is
#                         participation; silence before a level is not.
# Micro-momentum          tick-VWAP against the current mid -- where volume
#                         actually traded, not where the bar happened to close.
# Realised volatility     tick-scale variance, which leads bar-scale range.
# Price resilience        how much of a move is retained rather than reverted.
#                         Absorption looks identical to breakout in a bar.
#
# HONEST LIMITS
# -------------
# Retail MT5 ticks carry no true trade direction and often no real volume, so
# aggression is INFERRED with the tick rule (price relative to the previous
# mid). That is a proxy, not exchange order flow, and it is labelled as such
# rather than presented as certainty. `flags` is deliberately not trusted:
# brokers populate it inconsistently, and a feature that means different
# things at different brokers is worse than no feature.
#
# LEAKAGE
# -------
# Every feature is computed from ticks STRICTLY BEFORE the decision moment.
# `as_of` is required for exactly that reason; nothing here may see a tick
# that had not yet printed.
# ============================================================

from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

MICROSTRUCTURE_VERSION = "1.0"

# Windows, in seconds, over which every feature is computed. Several, because
# the horizon that matters is unknown -- and a feature that only exists at one
# arbitrary window is a tuned parameter pretending to be a measurement.
DEFAULT_WINDOWS = (30, 120, 600)

MIN_TICKS = 20


def _mt5():
    import MetaTrader5 as mt5
    return mt5


def fetch_ticks(symbol: str, as_of: Optional[datetime] = None,
                lookback_seconds: int = 900) -> List[Tuple]:
    """
    Ticks in the window ending at `as_of`, oldest first.

    `as_of` defaults to now for live use and MUST be supplied when replaying,
    or the features would be computed from ticks that had not yet printed.
    """
    mt5 = _mt5()
    end = as_of or datetime.now(timezone.utc)
    start = end - timedelta(seconds=int(lookback_seconds))
    try:
        ticks = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)
    except Exception as exc:
        logger.debug("tick fetch failed for %s: %s", symbol, exc)
        return []
    if ticks is None:
        return []
    return list(ticks)


def _mid(tick) -> Optional[float]:
    try:
        bid, ask = float(tick[1]), float(tick[2])
    except Exception:
        return None
    if bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2.0


def _spread(tick) -> Optional[float]:
    try:
        bid, ask = float(tick[1]), float(tick[2])
    except Exception:
        return None
    if bid <= 0 or ask <= 0:
        return None
    return ask - bid


def _epoch(tick) -> Optional[float]:
    try:
        msc = tick[5]
        if msc:
            return float(msc) / 1000.0
        return float(tick[0])
    except Exception:
        return None


def compute(ticks: Sequence[Tuple], pip_size: float,
            windows: Sequence[int] = DEFAULT_WINDOWS) -> Dict[str, Any]:
    """
    Microstructure features from a tick window.

    Returns `available: False` with a reason rather than zeros when there is
    not enough data. A zeroed feature is indistinguishable from a real reading
    of zero, and this project has repeatedly been bitten by exactly that: a
    fallback constant that looked like a measurement.
    """
    out: Dict[str, Any] = {
        "available": False,
        "version": MICROSTRUCTURE_VERSION,
        "tick_count": len(ticks or []),
    }
    if not ticks or len(ticks) < MIN_TICKS:
        out["reason"] = "insufficient ticks (%d < %d)" % (len(ticks or []), MIN_TICKS)
        return out
    if not pip_size or pip_size <= 0:
        out["reason"] = "invalid pip_size"
        return out

    rows = []
    for tick in ticks:
        t, mid, spread = _epoch(tick), _mid(tick), _spread(tick)
        if t is None or mid is None or spread is None:
            continue
        rows.append((t, mid, spread))
    if len(rows) < MIN_TICKS:
        out["reason"] = "insufficient parseable ticks"
        return out
    rows.sort(key=lambda r: r[0])

    latest = rows[-1][0]
    out["available"] = True
    out["as_of_epoch"] = latest
    out["windows"] = {}

    for window in windows:
        subset = [r for r in rows if r[0] >= latest - window]
        if len(subset) < MIN_TICKS:
            continue
        out["windows"][str(window)] = _window_features(subset, pip_size, window)

    if not out["windows"]:
        out["available"] = False
        out["reason"] = "no window had enough ticks"
    else:
        out.update(_summary(out["windows"]))
    return out


def _window_features(rows: Sequence[Tuple[float, float, float]],
                     pip_size: float, window: int) -> Dict[str, Any]:
    mids = [r[1] for r in rows]
    spreads = [r[2] for r in rows]

    # ---- order flow imbalance, by the tick rule ------------------------
    # No true trade direction in retail MT5 ticks, so aggression is inferred
    # from whether the mid rose or fell. A proxy, and named as one.
    up = down = flat = 0
    for i in range(1, len(mids)):
        if mids[i] > mids[i - 1]:
            up += 1
        elif mids[i] < mids[i - 1]:
            down += 1
        else:
            flat += 1
    directional = up + down
    imbalance = ((up - down) / directional) if directional else 0.0

    # ---- micro-momentum: tick VWAP vs the current mid -------------------
    # Unweighted because retail tick volume is unreliable; this is the mean
    # traded level, which is still where the activity actually happened
    # rather than where the bar happened to close.
    vwap = statistics.mean(mids)
    momentum_pips = (mids[-1] - vwap) / pip_size

    # ---- realised volatility at tick scale ------------------------------
    returns = [(mids[i] - mids[i - 1]) / pip_size for i in range(1, len(mids))]
    realised = statistics.pstdev(returns) if len(returns) > 1 else 0.0

    # ---- resilience: net move against total path travelled --------------
    # 1.0 = every tick moved the same way (a real move). Near 0 = the market
    # went nowhere expensively, which is absorption. A bar cannot tell these
    # apart; both look like a range.
    travelled = sum(abs(r) for r in returns)
    net = abs(mids[-1] - mids[0]) / pip_size
    resilience = (net / travelled) if travelled > 0 else 0.0

    span = max(1e-6, rows[-1][0] - rows[0][0])

    return {
        "ticks": len(rows),
        "intensity_per_second": round(len(rows) / span, 3),
        "order_flow_imbalance": round(imbalance, 4),
        "upticks": up, "downticks": down, "flat_ticks": flat,
        "micro_momentum_pips": round(momentum_pips, 3),
        "realised_vol_pips": round(realised, 4),
        "resilience": round(resilience, 4),
        "net_move_pips": round((mids[-1] - mids[0]) / pip_size, 3),
        "path_travelled_pips": round(travelled, 3),
        "spread_mean_pips": round(statistics.mean(spreads) / pip_size, 4),
        "spread_max_pips": round(max(spreads) / pip_size, 4),
        "spread_volatility": round(
            statistics.pstdev(spreads) / pip_size, 4) if len(spreads) > 1 else 0.0,
        "spread_now_pips": round(spreads[-1] / pip_size, 4),
    }


def _summary(windows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Cross-window readings -- the part a single window cannot express.

    Acceleration is the useful one: short-window intensity against the long
    baseline says whether participation is arriving NOW, which is precisely
    the question a bar cannot answer.
    """
    keys = sorted(windows, key=lambda k: int(k))
    short, long = windows[keys[0]], windows[keys[-1]]

    def ratio(a, b):
        return round(a / b, 3) if b else None

    return {
        "intensity_acceleration": ratio(short["intensity_per_second"],
                                        long["intensity_per_second"]),
        "volatility_acceleration": ratio(short["realised_vol_pips"],
                                         long["realised_vol_pips"]),
        "spread_stress": ratio(short["spread_mean_pips"],
                               long["spread_mean_pips"]),
        "imbalance_short": short["order_flow_imbalance"],
        "imbalance_long": long["order_flow_imbalance"],
        # Agreement across horizons. Persistent pressure is a different
        # animal from a momentary burst, and only the cross-window view
        # separates them.
        "imbalance_agreement": (
            short["order_flow_imbalance"] * long["order_flow_imbalance"] > 0),
    }


def analyse(symbol: str, pip_size: float, *,
            as_of: Optional[datetime] = None,
            lookback_seconds: int = 900,
            windows: Sequence[int] = DEFAULT_WINDOWS) -> Dict[str, Any]:
    """Fetch and compute in one call. The live entry point."""
    ticks = fetch_ticks(symbol, as_of=as_of, lookback_seconds=lookback_seconds)
    result = compute(ticks, pip_size, windows)
    result["symbol"] = symbol
    return result


def directional_bias(features: Dict[str, Any],
                     direction: str) -> Dict[str, Any]:
    """
    How the microstructure sits relative to a proposed trade.

    Signed against the TRADE, not against the market. `pattern` was inverted
    on every SELL for exactly this reason -- a component that reports a market
    read and lets the caller sign it will eventually be signed wrong.
    """
    if not features.get("available"):
        return {"available": False, "reason": features.get("reason")}

    sign = 1 if str(direction).upper() == "BUY" else -1
    short = features.get("imbalance_short") or 0.0
    long = features.get("imbalance_long") or 0.0

    return {
        "available": True,
        "flow_with_trade_short": round(sign * short, 4),
        "flow_with_trade_long": round(sign * long, 4),
        "flow_supports_trade": (sign * short) > 0 and (sign * long) > 0,
        "flow_opposes_trade": (sign * short) < 0 and (sign * long) < 0,
        "intensity_acceleration": features.get("intensity_acceleration"),
        "spread_stress": features.get("spread_stress"),
        # Deliberately NOT turned into a probability adjustment yet. It has
        # never been measured against outcomes on this account, and adding an
        # unvalidated contributor to the probability chain is how `pattern`
        # came to push 12 points the wrong way on 26% of trades.
        "contribution": 0.0,
        "note": "measurement only; not wired into probability until validated",
    }


def get_status() -> Dict[str, Any]:
    return {"component": "microstructure_features",
            "version": MICROSTRUCTURE_VERSION,
            "windows": list(DEFAULT_WINDOWS),
            "min_ticks": MIN_TICKS,
            "wired_into_probability": False}


def self_check(ticks: Optional[Sequence[Tuple]] = None) -> Dict[str, Any]:
    """
    Prove the features respond to structure and refuse garbage.

    Two synthetic tapes: one trending up on every tick, one pure alternation.
    A trending tape must show positive imbalance and high resilience; an
    alternating tape must show neither. A feature set that cannot tell those
    apart is measuring nothing.
    """
    base = 1.1000
    trend = [(1000.0 + i, base + i * 0.00001, base + i * 0.00001 + 0.00002)
             for i in range(200)]
    chop = [(1000.0 + i,
             base + (0.00001 if i % 2 else -0.00001),
             base + (0.00001 if i % 2 else -0.00001) + 0.00002)
            for i in range(200)]

    def as_ticks(rows):
        return [(int(t), bid, ask, 0.0, 0, int(t * 1000), 0, 0.0)
                for t, bid, ask in rows]

    up = compute(as_ticks(trend), 0.0001)
    side = compute(as_ticks(chop), 0.0001)
    empty = compute([], 0.0001)

    up_w = (up.get("windows") or {}).get("600") or {}
    side_w = (side.get("windows") or {}).get("600") or {}

    checks = {
        "trending_tape_available": up.get("available") is True,
        "trending_imbalance_positive": up_w.get("order_flow_imbalance", 0) > 0.9,
        "trending_resilience_high": up_w.get("resilience", 0) > 0.9,
        "choppy_imbalance_near_zero": abs(side_w.get("order_flow_imbalance", 1)) < 0.2,
        "choppy_resilience_low": side_w.get("resilience", 1) < 0.2,
        "empty_refused": empty.get("available") is False,
        "empty_gives_reason": bool(empty.get("reason")),
    }
    return {"component": "microstructure_features",
            "version": MICROSTRUCTURE_VERSION,
            "checks": checks,
            "ok": all(checks.values())}
