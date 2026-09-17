"""
LIQUIDITY EVENT ENGINE
======================
FILE: core/liquidity_events.py

One canonical definition of a liquidity sweep, consumed by SMC, order
flow and entry logic.

THE PROBLEM THIS REPLACES

Two independent implementations described the same market event and
disagreed on the same bar:

  asset_analysis_smc._detect_liquidity_sweep()
      any of the last 3 bars wicks beyond the max/min of a 20-bar window,
      and all 3 close back inside. No minimum sweep size at all — a
      0.1-pip poke counted. Returns ONE sweep or nothing.

  order_flow_forensics.detect_stop_hunts()
      real swing points (ATR-filtered), a sweep floor measured against
      the spread, an explicit reclaim window. Returns a LIST of events.

Same phenomenon, two definitions, two vocabularies (BULLISH_SWEEP vs
STOP_HUNT_BUY_SIDE_TRAP), two lookbacks. SMC could report "no sweep"
while order flow reported five, and nothing reconciled them — so
SL placement, the SMC confluence count and the order-flow adjustment
could each be acting on a different view of the same tape.

That is the duplicate-logic pattern that produced most of the
contradictions in this system. Fixing it in one place is worth more than
tuning either copy.

THE CANONICAL DEFINITION

A liquidity event is: price traded through a level where stops rest,
then came back. Three things must be true, and the previous
implementations each checked only some of them:

  1. The level is real structure — a swing point that passed an
     ATR-relative amplitude filter, not any local high.
  2. The breach is bigger than the spread — a sweep narrower than the
     bid-ask gap did not fill anyone's stop, because that price never
     genuinely traded.
  3. Price returned within a bounded window — a breach that never comes
     back is a breakout, not a sweep. This is the distinction that
     matters most and the one SMC's version approximated with "all 3
     bars closed back inside".

Both legacy shapes are still emitted, so existing consumers keep working
while reading from one source of truth.
"""

from typing import Dict, Any, List, Tuple, Optional
import logging

from core.swing_points import find_swing_points_ohlc, get_min_swing_size
from core.asset_analysis_config import atr_relative_pips

logger = logging.getLogger(__name__)

# A breach smaller than this is noise even when it clears the spread.
# ATR-relative, because "meaningful breach" scales with what the
# instrument moves — the lesson of every absolute-pip constant in this
# codebase.
# A stop run has to travel further than the bar-to-bar noise around the
# level. At 0.05 ATR (the previous value) a poke a twentieth of an average
# bar counted, so a "sweep" existed on 97% of study bars.
SWEEP_MIN_ATR_FRACTION = 0.25
# Only sweeps this recent describe the market now. The summary used to take
# its bias from every sweep in the 100-bar scan, and the primary sweep fell
# back to ANY event when none was recent -- so a sweep 99 bars old still set
# the SMC and order-flow reading.
SWEEP_RECENT_BARS = 15
SWEEP_LEVEL_LOOKBACK = 10          # bars each side for a swing to be a stop level
SWEEP_LEVEL_MIN_SWING_MULT = 2.0   # x the standard minimum swing (1 ATR on M1)

# How long price has to come back for the breach to count as a sweep
# rather than a breakout.
SWEEP_RECLAIM_BARS = 3

# Only events originating this recently are "current order flow".
SWEEP_SCAN_LOOKBACK = 100

SWEEP_MAX_EVENTS = 5


def _classify(side: str) -> Tuple[str, str, str]:
    """(canonical type, SMC vocabulary, order-flow vocabulary).

    A swept HIGH traps breakout buyers and usually precedes a move DOWN,
    so its trade implication is bearish. The two legacy vocabularies name
    that same event from opposite ends — SMC by the resulting direction,
    order flow by which side got trapped — which is precisely why they
    were never obviously the same thing.
    """
    if side == "HIGH":
        return "BUY_SIDE_SWEEP", "BEARISH_SWEEP", "STOP_HUNT_BUY_SIDE_TRAP"
    return "SELL_SIDE_SWEEP", "BULLISH_SWEEP", "STOP_HUNT_SELL_SIDE_TRAP"


def detect_liquidity_events(
    rates,
    pip_size: float,
    timeframe: str = "M1",
    atr_pips: float = None,
    spread_pips: float = 0.0,
    lookback: int = None,
    reclaim_within_bars: int = SWEEP_RECLAIM_BARS,
    scan_lookback_bars: int = SWEEP_SCAN_LOOKBACK,
    max_events: int = SWEEP_MAX_EVENTS,
) -> List[Dict[str, Any]]:
    """
    Every liquidity sweep in the recent window, newest first.

    Deduplicated by level: a choppy market crossing the same old level
    repeatedly is one story, not a new event per crossing.
    """
    lookback = lookback or SWEEP_LEVEL_LOOKBACK
    if rates is None or len(rates) < (2 * lookback + 5) or not pip_size or pip_size <= 0:
        return []

    # Stops rest beyond SIGNIFICANT swings. With 5-bar pivots every minor
    # wiggle was a level, so one move through a cluster of them registered
    # as up to five "sweeps" and a recent sweep existed on 92% of bars.
    min_amp = SWEEP_LEVEL_MIN_SWING_MULT * get_min_swing_size(timeframe, pip_size, atr_pips)
    try:
        swing_highs, high_times = find_swing_points_ohlc(rates, use_high=True,
                                                         lookback=lookback, min_amplitude=min_amp)
        swing_lows, low_times = find_swing_points_ohlc(rates, use_high=False,
                                                       lookback=lookback, min_amplitude=min_amp)
    except Exception as e:
        logger.debug(f"[LIQUIDITY] swing detection failed: {e}")
        return []

    # A sweep must clear BOTH the spread and a fraction of ATR. The spread
    # floor is a hard physical requirement; the ATR floor is what stops a
    # tight-spread instrument accepting sub-noise breaches.
    min_sweep = max(
        float(spread_pips or 0.0),
        atr_relative_pips(1.0, atr_pips, SWEEP_MIN_ATR_FRACTION),
    )

    n = len(rates)
    scan_start = max(0, n - scan_lookback_bars)
    best: Dict[Tuple[str, float], Dict[str, Any]] = {}

    index_of_time = {int(rates[k][0]): k for k in range(n)}
    for side, levels, times, is_high in (("HIGH", swing_highs, high_times, True),
                                         ("LOW", swing_lows, low_times, False)):
        for level, t in zip(levels, times):
            # ✅ FIXED (2026-09-15): every bar of the scan window was tested
            # against every level, including bars BEFORE the swing formed --
            # price above a high that did not exist yet counted as sweeping
            # it. A level can be swept only once it is a confirmed swing.
            swing_index = index_of_time.get(int(t), -1)
            # Only the FIRST time price trades beyond the level can be a sweep:
            # that is when the resting stops fill. Afterwards the level is
            # spent -- price oscillating around an old broken level used to
            # register a fresh "sweep" on every crossing.
            first_bar = swing_index + lookback + 1 if swing_index >= 0 else scan_start
            first_touch = None
            for i in range(max(0, first_bar), n - 1):
                try:
                    extreme = float(rates[i][2]) if is_high else float(rates[i][3])
                except (IndexError, TypeError, ValueError):
                    continue
                beyond = extreme > level if is_high else extreme < level
                if beyond:
                    first_touch = i
                    break
            if first_touch is None or first_touch < scan_start:
                continue
            for i in (first_touch,):
                extreme = float(rates[i][2]) if is_high else float(rates[i][3])
                breach = (extreme - level) / pip_size if is_high else (level - extreme) / pip_size
                if breach < min_sweep:
                    continue

                # Did price come back? A breach that never returns is a
                # breakout, and calling it a sweep is how a trend gets
                # traded as a reversal.
                reclaimed, bars_to_reclaim = False, None
                for j in range(i, min(i + reclaim_within_bars + 1, n)):
                    try:
                        close = float(rates[j][4])
                    except (IndexError, TypeError, ValueError):
                        continue
                    if (is_high and close < level) or ((not is_high) and close > level):
                        reclaimed, bars_to_reclaim = True, j - i
                        break
                if not reclaimed:
                    continue

                canonical, smc_type, of_type = _classify(side)
                key = (side, round(level, 5))
                event = {
                    "type": canonical,
                    "smc_type": smc_type,
                    "order_flow_type": of_type,
                    "side_swept": side,
                    "level": round(level, 5),
                    "sweep_size_pips": round(breach, 1),
                    "bars_to_reclaim": bars_to_reclaim,
                    "bar_index": i,
                    "bars_ago": n - 1 - i,
                    # Strength blends how far past the level price went with
                    # how fast it snapped back. A deep breach reclaimed
                    # immediately is the strongest signature; a shallow one
                    # that took the full window is the weakest.
                    "strength": round(
                        min(1.0, breach / max(min_sweep * 4.0, 1e-9))
                        * (1.0 - (bars_to_reclaim / max(reclaim_within_bars, 1)) * 0.5),
                        3,
                    ),
                    # Direction this event IMPLIES for a trade.
                    "implied_direction": "SELL" if is_high else "BUY",
                }
                prev = best.get(key)
                if prev is None or event["bar_index"] > prev["bar_index"]:
                    best[key] = event

    events = sorted(best.values(), key=lambda e: e["bar_index"], reverse=True)
    return events[:max_events]


def get_primary_sweep(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    The single most relevant event, in the shape SMC's
    _detect_liquidity_sweep() returned.

    "Most relevant" is the strongest RECENT event, not simply the newest.
    The legacy SMC version only ever looked at the last 3 bars, so a
    powerful sweep 6 bars back was invisible to it while a trivial poke
    on the last bar was not.
    """
    if not events:
        return {"swept": False, "type": None, "level": None, "event": None}

    recent = [e for e in events if e["bars_ago"] <= SWEEP_RECENT_BARS]
    if not recent:
        return {"swept": False, "type": None, "level": None, "event": None}
    top = max(recent, key=lambda e: e["strength"])
    return {
        "swept": True,
        "type": top["smc_type"],
        "level": top["level"],
        "event": top,
    }


def to_order_flow_shape(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The same events in the shape detect_stop_hunts() returned."""
    return [
        {
            "type": e["order_flow_type"],
            "swept_level": e["level"],
            "sweep_size_pips": e["sweep_size_pips"],
            "bars_to_reclaim": e["bars_to_reclaim"],
            "sweep_bar_index": e["bar_index"],
            "strength": e["strength"],
            "implied_direction": e["implied_direction"],
            "bars_ago": e.get("bars_ago"),
        }
        for e in events
    ]


# Probability effect of the sweep bias. Until 2026-09-15 the bias was written
# into the output and never entered the probability chain.
#
# Measured on the 111 stored trades with tick paths (ai/component_forensics):
# trade direction right 65.7% when the bias agreed vs 40.6% when it opposed
# (lift +25.1 pts, p=0.017), in both halves of the sample. Sized just below
# the trend cascade (+12 / -18), whose lift is similar (+29.8 pts).
LIQUIDITY_MAX_BONUS = 10.0
LIQUIDITY_MAX_PENALTY = -15.0


def calculate_liquidity_final_score(summary: Dict[str, Any], base_probability: float,
                                    best_direction: str) -> Dict[str, Any]:
    """Probability adjustment from the sweep bias, in the chain's usual shape.

    A bias that agrees with the side adds LIQUIDITY_MAX_BONUS, one that opposes
    it adds LIQUIDITY_MAX_PENALTY. No sweeps, an unavailable summary or an
    unknown side leave probability unchanged.
    """
    base = float(base_probability)
    unchanged = {"final_score": base, "intended": base, "adjustment": 0.0, "aligned": None}
    if not isinstance(summary, dict) or not summary.get("available"):
        return {**unchanged, "reason": "liquidity sweeps unavailable"}
    bias = summary.get("bias")
    if bias not in ("BULLISH", "BEARISH") or best_direction not in ("BUY", "SELL"):
        return {**unchanged, "reason": summary.get("reason") or "no qualifying liquidity sweeps"}

    aligned = (best_direction == "BUY") == (bias == "BULLISH")
    adjustment = LIQUIDITY_MAX_BONUS if aligned else LIQUIDITY_MAX_PENALTY
    intended = base + adjustment
    return {
        "final_score": round(max(5.0, min(95.0, intended)), 2),
        "intended": round(intended, 2),
        "adjustment": adjustment,
        "aligned": aligned,
        "reason": f"{best_direction} {'with' if aligned else 'against'} {bias} sweep bias "
                  f"({summary.get('buy_side_sweeps', 0)} buy-side / {summary.get('sell_side_sweeps', 0)} "
                  f"sell-side) {adjustment:+.0f}",
    }


def summarize_liquidity(events: List[Dict[str, Any]], direction: str = None) -> Dict[str, Any]:
    """
    What the liquidity picture says, as one readable verdict.

    Both legacy implementations left interpretation to their callers,
    which is why SMC and order flow could act on the same events in
    contradictory ways.
    """
    events = [e for e in (events or []) if e.get("bars_ago", 0) <= SWEEP_RECENT_BARS]
    if not events:
        return {"available": True, "event_count": 0, "bias": "NONE",
                "reason": f"no liquidity sweep in the last {SWEEP_RECENT_BARS} bars"}

    buy_side = [e for e in events if e["side_swept"] == "HIGH"]
    sell_side = [e for e in events if e["side_swept"] == "LOW"]
    strongest = max(events, key=lambda e: e["strength"])

    if len(buy_side) > len(sell_side):
        bias = "BEARISH"
    elif len(sell_side) > len(buy_side):
        bias = "BULLISH"
    else:
        bias = "BULLISH" if strongest["side_swept"] == "LOW" else "BEARISH"

    aligned = None
    if direction:
        aligned = ((direction.upper() == "BUY" and bias == "BULLISH")
                   or (direction.upper() == "SELL" and bias == "BEARISH"))

    return {
        "available": True,
        "event_count": len(events),
        "buy_side_sweeps": len(buy_side),
        "sell_side_sweeps": len(sell_side),
        "bias": bias,
        "aligned_with_direction": aligned,
        "strongest": strongest,
        "reason": (f"{len(buy_side)} buy-side / {len(sell_side)} sell-side sweeps, "
                   f"strongest {strongest['sweep_size_pips']}p reclaimed in "
                   f"{strongest['bars_to_reclaim']} bar(s) -> {bias}"),
    }