# ============================================================
# ITEM #6 — ORDER-FLOW / MICROSTRUCTURE FORENSICS
# ============================================================
# FILE: core/order_flow_forensics.py
#
# Extends the existing micro_structure block (absorption, iceberg, spread
# collapse) with three always-on, first-class outputs, built purely from
# the raw OHLC `rates` array asset_analysis.py already holds and
# swing_points.py's existing swing detector -- no new data source.
#
# rates column convention (matches swing_points.py / indicators.py usage
# elsewhere in this codebase): [time, open, high, low, close, tick_volume, ...]
#   index 0 = time, 1 = open, 2 = high, 3 = low, 4 = close, 5 = tick_volume
# ============================================================

from typing import Dict, Any, List, Tuple, Optional
import numpy as np

from core.swing_points import find_swing_points_ohlc, get_min_swing_size
from core.liquidity_events import detect_liquidity_events, to_order_flow_shape
from core.asset_analysis_config import atr_relative_pips

import logging

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# 1. STOP-HUNT DETECTION
# ------------------------------------------------------------
# A stop-hunt: price wicks through a prior swing high/low (sweeping the
# liquidity resting just beyond it) and then closes back on the
# "wrong" side of that level within the same bar or the next one --
# i.e. the sweep gets immediately reclaimed rather than confirmed.

def detect_stop_hunts(
    rates,
    pip_size: float,
    lookback: int = 5,
    min_sweep_pips: float = 0.5,
    reclaim_within_bars: int = 2,
    scan_lookback_bars: int = 100,
    max_events: int = 5,
    spread_pips: float = 0.0,
    timeframe: str = "M1",
    atr_pips: float = None,
) -> List[Dict[str, Any]]:
    """
    Stop hunts, delegated to the canonical liquidity engine.

    ✅ This implementation and asset_analysis_smc._detect_liquidity_sweep()
    were two definitions of the same market event. This one used real
    swing points, a spread-relative sweep floor and an explicit reclaim
    window; SMC's used a 20-bar max/min with no size test at all. They
    disagreed on the same bar, and the SMC confluence count, SL placement
    and this module's probability adjustment could each be acting on a
    different view of the tape.

    Both now read core/liquidity_events.py. The return shape is unchanged.

    min_sweep_pips is retained in the signature for callers that pass it,
    but the engine's floor is max(spread, ATR fraction) -- a sweep that
    does not clear the spread did not fill anyone's stop, whatever the
    caller asked for.
    """
    try:
        events = detect_liquidity_events(
            rates, pip_size, timeframe,
            atr_pips=atr_pips,
            spread_pips=max(float(spread_pips or 0.0), float(min_sweep_pips or 0.0)),
            reclaim_within_bars=reclaim_within_bars,
            scan_lookback_bars=scan_lookback_bars,
            max_events=max_events,
        )
        return to_order_flow_shape(events)
    except Exception as e:
        logger.debug(f"[ORDER FLOW] liquidity delegation failed: {e}")
        return []

def calculate_order_block_mitigation(
    rates: np.ndarray,
    zone_level: float,
    zone_type: str,  # "DEMAND" or "SUPPLY"
    pip_size: float,
    touch_buffer_pips: float = 1.0,
    exclude_current_bar: bool = True,
) -> Dict[str, Any]:
    """
    How many times this zone was mitigated BEFORE the current bar.

    ✅ FIXED: the scan ran over every bar including the most recent one --
    the bar price is on right now. But a zone you are about to trade at is,
    by definition, being touched by that bar, so its own arrival was counted
    as a prior mitigation. Two consequences, both measured on 215 real trades:

      * VIRGIN (mitigation_count == 0) became UNREACHABLE for any zone being
        traded. It occurred 0 times in 215 trades while carrying the largest
        magnitude in the component (+55). Dead code by construction.
      * every zone was classified one category staler than it was, so
        "LIKELY_EXHAUSTED" (>3 visits) actually meant "touched 3+ times
        before this entry" -- and 84% of trades landed there.

    The measured ordering is monotone and correct (first touch +0.346R,
    partially mitigated +0.240R, likely exhausted -0.083R), so the component
    grades freshness properly; it was just being handed a stale count.

    `exclude_current_bar=False` restores the old behaviour.
    """
    if rates is None or len(rates) == 0:
        return {"available": False, "reason": "no rate data"}

    buffer_price = touch_buffer_pips * pip_size
    touches = []

    scan = rates[:-1] if (exclude_current_bar and len(rates) > 1) else rates

    # ✅ FIXED 2026-09-15: count visits only AFTER the zone formed.
    #
    # The scan used to start at the first fetched bar, so every time price
    # had traded through this level BEFORE the swing that created the zone
    # counted as a "mitigation". 101 of 111 stored trades were therefore at a
    # "LIKELY_EXHAUSTED" zone, and live reads showed 9-11 visits on zones
    # formed minutes earlier.
    #
    # The zone level IS the swing extreme that formed it (supply = a swing
    # high, demand = a swing low -- see indicators._detect_supply_demand_zone),
    # so the formation bar is the most recent bar whose high (supply) or low
    # (demand) sits on the level. Visits are counted from the bar after it.
    # If no bar matches (a level supplied from elsewhere), the whole window is
    # scanned as before and `formation_found` says so.
    extreme_col = 2 if zone_type == "SUPPLY" else 3
    formation_tolerance = max(1e-9, 0.05 * pip_size)
    formation_index = None
    for i in range(len(scan) - 1, -1, -1):
        if abs(float(scan[i][extreme_col]) - zone_level) <= formation_tolerance:
            formation_index = i
            break
    start = formation_index + 1 if formation_index is not None else 0

    for i, bar in enumerate(scan):
        if i < start:
            continue
        bar_high, bar_low = float(bar[2]), float(bar[3])
        if zone_type == "DEMAND":
            touched = bar_low <= zone_level + buffer_price
        else:  # SUPPLY
            touched = bar_high >= zone_level - buffer_price
        if touched:
            touches.append(i)

    # Collapse consecutive touching bars into distinct "visits" -- a zone
    # sat on for 5 bars in a row is one visit, not five separate mitigations.
    visits = []
    for idx in touches:
        if visits and idx - visits[-1][-1] <= 1:
            visits[-1].append(idx)
        else:
            visits.append([idx])

    mitigation_count = len(visits)
    if mitigation_count == 0:
        status = "VIRGIN"  # never touched -- freshest possible zone
    elif mitigation_count == 1:
        status = "FIRST_TOUCH"
    elif mitigation_count <= 3:
        status = "PARTIALLY_MITIGATED"
    else:
        status = "LIKELY_EXHAUSTED"

    return {
        "available": True,
        "zone_level": zone_level,
        "zone_type": zone_type,
        "mitigation_count": mitigation_count,
        "status": status,
        "formation_found": formation_index is not None,
        "bars_since_formation": (len(scan) - 1 - formation_index) if formation_index is not None else None,
        "visit_bar_ranges": [(v[0], v[-1]) for v in visits],
        "note": (
            "First-touch zones are structurally stronger than heavily-revisited "
            "ones -- each additional visit is evidence resting orders at this "
            "level have already been consumed."
        ),
    }


# ------------------------------------------------------------
# 3. LIQUIDITY POOL MAPPING
# ------------------------------------------------------------
# Equal highs / equal lows (within tolerance) cluster resting stop orders
# into a "pool" that acts as a magnet target. Session high/low included
# as a first-class pool too.

def map_liquidity_pools(
    rates: np.ndarray,
    pip_size: float,
    lookback: int = 5,
    equal_level_tolerance_pips: float = 1.5,
    timeframe: str = "M1",
    atr_pips: float = None,
) -> Dict[str, Any]:
    if rates is None or len(rates) < (2 * lookback + 5):
        return {"available": False, "reason": "insufficient bars"}

    # ✅ Both fixes that detect_stop_hunts() already received, applied here
    # too -- this function was left with the original defects because it
    # is not sweep detection and did not look like the same bug.
    #
    #   1. min_amplitude was omitted, so it defaulted to 0.0: every 5-bar
    #      pivot counted as a level worth pooling.
    #   2. equal_level_tolerance_pips is absolute. 1.5 pips decides whether
    #      two highs are "equal" -- reasonable on EURUSD, meaningless on an
    #      instrument with a 20-pip spread, where two levels 1.5 pips apart
    #      are the same price.
    min_amp = get_min_swing_size(timeframe, pip_size)
    swing_highs, _ = find_swing_points_ohlc(rates, use_high=True, lookback=lookback,
                                            min_amplitude=min_amp)
    swing_lows, _ = find_swing_points_ohlc(rates, use_high=False, lookback=lookback,
                                           min_amplitude=min_amp)
    tol = atr_relative_pips(equal_level_tolerance_pips, atr_pips, 0.03) * pip_size

    def cluster(levels: List[float]) -> List[Dict[str, Any]]:
        pools = []
        used = [False] * len(levels)
        for i, lvl in enumerate(levels):
            if used[i]:
                continue
            group = [lvl]
            used[i] = True
            for j in range(i + 1, len(levels)):
                if used[j]:
                    continue
                if abs(levels[j] - lvl) <= tol:
                    group.append(levels[j])
                    used[j] = True
            if len(group) >= 2:  # a "pool" needs at least two roughly-equal levels
                pools.append({
                    "level": round(sum(group) / len(group), 5),
                    "touch_count": len(group),
                    "spread_pips": round((max(group) - min(group)) / pip_size, 2),
                })
        return sorted(pools, key=lambda p: p["touch_count"], reverse=True)[:5]

    equal_highs = cluster(swing_highs)
    equal_lows = cluster(swing_lows)

    # rates from mt5.copy_rates_from_pos() is a 1-D structured array
    # (array of records), so 2-D slicing like rates[:, 2] raises
    # "too many indices for array". Access each record's field by index
    # instead, consistent with find_swing_points_ohlc() / detect_stop_hunts().
    session_high = float(np.max([float(r[2]) for r in rates]))
    session_low = float(np.min([float(r[3]) for r in rates]))

    return {
        "available": True,
        "equal_highs_pools": equal_highs,
        "equal_lows_pools": equal_lows,
        "session_high": session_high,
        "session_low": session_low,
        "note": (
            "Equal-level pools are magnet targets -- price is statistically more "
            "likely to be drawn toward clustered resting liquidity than an "
            "isolated single swing point."
        ),
    }


# ------------------------------------------------------------
# TOP-LEVEL: bundle all three as one always-on block
# ------------------------------------------------------------

def build_order_flow_forensics(
    rates: np.ndarray,
    pip_size: float,
    zone_level: float = None,
    zone_type: str = None,
    spread_pips: float = 0.0,
    timeframe: str = "M1",
    atr_pips: float = None,
) -> Dict[str, Any]:
    # ✅ atr_pips threaded so the canonical engine can apply its
    # ATR-relative sweep floor as well as the spread floor.
    stop_hunts = detect_stop_hunts(
        rates, pip_size, spread_pips=spread_pips, timeframe=timeframe,
        atr_pips=atr_pips
    )
    result = {
        "stop_hunts": stop_hunts,
        # ✅ FIXED: each event used to carry its own full-sentence
        # "implication" text (identical for every event of the same
        # type) - with dozens of events that meant the same sentence
        # repeated dozens of times. One shared legend now, only included
        # when there's actually at least one event to explain.
        "stop_hunt_legend": (
            {
                # Matches core/liquidity_events._classify, which emits these
                # events. The legend used to describe the two the other way
                # round, and the scorer below followed the legend.
                "STOP_HUNT_BUY_SIDE_TRAP": "Buy-side liquidity above a prior swing high was taken and price reclaimed below it — often precedes a move down.",
                "STOP_HUNT_SELL_SIDE_TRAP": "Sell-side liquidity below a prior swing low was taken and price reclaimed above it — often precedes a move up.",
            } if stop_hunts else {}
        ),
        "liquidity_pools": map_liquidity_pools(rates, pip_size),
    }
    if zone_level is not None and zone_type is not None:
        result["order_block_mitigation"] = calculate_order_block_mitigation(
            rates, zone_level, zone_type, pip_size
        )
    else:
        result["order_block_mitigation"] = {"available": False, "reason": "no zone_level/zone_type supplied"}
    return result


# ------------------------------------------------------------
# 4. PROBABILITY-CHAIN CONTRIBUTION (✅ NEW)
# ------------------------------------------------------------
# ✅ NEW (per explicit request): everything in this module used to be
# computed, displayed, and read by nothing else -- detect_stop_hunts()'s
# output was never referenced outside this file and asset_analysis.py's
# output-assembly dict; map_liquidity_pools() the same. calculate_order_
# block_mitigation()'s status DID reach asset_analysis.py's sd_data["score"]
# (a real, separate wiring point added earlier), but that path terminates
# in calculate_unified_indicator_score()'s DIAGNOSTIC layer only -- the
# function that actually produces buy_probability/sell_probability
# (calculate_real_probability in calculations.py) never took a zone_score
# parameter at all, only the letter zone_grade, so no order-flow signal of
# any kind reached the real trade decision, in any zone grade.
#
# This function closes that gap the same way pattern/GNN/SMC/FVG-IFVG
# already do: a bounded, direction-checked contribution the caller chains
# onto best_probability. Mirrors calculate_smc_final_score()'s contract
# exactly (recommendation/score/contribution/final_score/weight_used/
# aligned) so it composes predictably with the rest of the chain.
#
# ORDER_FLOW_WEIGHT is a reasoned default, not a fitted coefficient --
# same caveat that already applies to SMC_WEIGHT/GNN_WEIGHT/PATTERN_WEIGHT
# elsewhere in this codebase (see the repeated "Not backtested" notes).
# Revisit once real outcome data from attach_outcome() exists to calibrate
# against.
ORDER_FLOW_WEIGHT = 0.12

# Magnitude of the vote AGAINST a zone classed LIKELY_EXHAUSTED. Was 45.
#
# Set to 0 on 2026-09-15. The mitigation count scans the whole fetched
# history, including bars from before the zone formed, so 101 of 111 stored
# trades were at a "LIKELY_EXHAUSTED" zone. The 45-point counter-vote then
# flipped order flow AGAINST the trade's own zone -- and those trades were
# right 63.8% of the time (n=69), versus 50% when order flow agreed. Order flow
# as a whole called the market right 40% (CI 31-50%): inverted by this term.
#
# The count now starts at the zone's formation (calculate_order_block_
# mitigation). Re-based on the same stored trades the statuses become 45 first
# touch / 34 partially mitigated / 30 exhausted, and they rank correctly:
# first touch 67% right, +0.23R; partially mitigated 54%, -0.55R; exhausted
# 59%, -0.83R (current bracket, zone on the trade's side). An exhausted zone
# is weaker support, not evidence AGAINST the trade -- 59% is still better
# than a coin -- so the counter-vote stays at 0 while the fresh-zone bonuses
# now reach the trades they were meant for.
LIKELY_EXHAUSTED_COUNTER_VOTE = 0.0


ORDER_BLOCK_REACH_ATR = 0.5   # an order block counts while price is within this of it


def _hunt_direction(hunt: Dict[str, Any]) -> Optional[str]:
    """Market direction a stop hunt implies, from the event's own
    implied_direction (core/liquidity_events is the one definition)."""
    implied = str(hunt.get("implied_direction") or "").upper()
    if implied == "BUY":
        return "BULLISH"
    if implied == "SELL":
        return "BEARISH"
    hunt_type = hunt.get("type")
    return ("BEARISH" if hunt_type == "STOP_HUNT_BUY_SIDE_TRAP"
            else "BULLISH" if hunt_type == "STOP_HUNT_SELL_SIDE_TRAP" else None)


def calculate_order_flow_final_score(
    order_flow_forensics_data: Dict[str, Any],
    base_probability: float,
    best_direction: str = "BUY",
    current_price: Optional[float] = None,
    pip_size: Optional[float] = None,
    wyckoff_phase: Optional[str] = None,
    atr_pips: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Stop hunts, order-block freshness, liquidity-pool draw and Wyckoff
    spring/UTAD as ONE market reading (positive = bullish), then judged
    against best_direction for the probability contribution.

    ✅ FIXED (2026-09-15), two defects:
      * stop hunts were read backwards: the scorer mapped
        STOP_HUNT_BUY_SIDE_TRAP -> BULLISH, while core/liquidity_events (which
        emits the events) defines it as the highs swept -> SELL. Spring/UTAD
        confluence inherited the inversion.
      * the reading depended on the side being scored: liquidity pools only
        ever counted FOR best_direction (equal highs when BUY, equal lows when
        SELL), so order flow echoed the engine's own choice back as
        confirmation and carried a direction on 99.8% of study bars.
    """
    from core.liquidity_events import SWEEP_RECENT_BARS

    agree_label = "BULLISH" if best_direction == "BUY" else "BEARISH"
    oppose_label = "BEARISH" if best_direction == "BUY" else "BULLISH"

    net = 0.0              # market-relative: + bullish, - bearish
    max_possible = 0.0
    reasons: List[str] = []

    # --- 1. Stop hunt: the most recent one, if it is recent. ---
    stop_hunts = order_flow_forensics_data.get("stop_hunts") or []
    most_recent_hunt = next((h for h in stop_hunts
                             if h.get("bars_ago") is None or h.get("bars_ago") <= SWEEP_RECENT_BARS), None)
    if most_recent_hunt:
        hunt_dir = _hunt_direction(most_recent_hunt)
        sweep_pips = most_recent_hunt.get("sweep_size_pips", 0) or 0
        bars_to_reclaim = most_recent_hunt.get("bars_to_reclaim", 2) or 0
        if hunt_dir:
            magnitude = max(15.0, min(70.0, 25.0 + sweep_pips * 15.0 - bars_to_reclaim * 3.0))
            net += magnitude if hunt_dir == "BULLISH" else -magnitude
            max_possible += magnitude
            reasons.append(f"{hunt_dir.lower()} {most_recent_hunt.get('type')} "
                           f"({sweep_pips:.1f}p swept, reclaimed in {bars_to_reclaim} bar(s))")

    # --- 2. Order-block freshness: a fresh zone points its own way. ---
    ob = order_flow_forensics_data.get("order_block_mitigation") or {}
    # A block's freshness is a reading only while price is at the block: the
    # nearest zone always has a status, so it voted on every bar.
    _zone = ob.get("zone_level")
    if (ob.get("available") and _zone is not None and current_price is not None and pip_size
            and atr_pips and abs(current_price - _zone) / pip_size > ORDER_BLOCK_REACH_ATR * atr_pips):
        ob = {}
    if ob.get("available"):
        status = ob.get("status")
        zone_type = ob.get("zone_type")
        zone_sign = 1.0 if zone_type == "DEMAND" else -1.0 if zone_type == "SUPPLY" else 0.0
        magnitude = {"VIRGIN": 55.0, "FIRST_TOUCH": 30.0, "PARTIALLY_MITIGATED": 10.0}.get(status, 0.0)
        if status == "LIKELY_EXHAUSTED":
            zone_sign, magnitude = -zone_sign, LIKELY_EXHAUSTED_COUNTER_VOTE
        if zone_sign and magnitude > 0:
            net += zone_sign * magnitude
            max_possible += magnitude
            reasons.append(f"{zone_type} order block is {status.replace('_', ' ').lower()}")

    # --- 3. Liquidity pools on BOTH sides: the stronger draw wins. ---
    pools = order_flow_forensics_data.get("liquidity_pools") or {}
    if pools.get("available") and current_price is not None and pip_size:
        for key, above, sign in (("equal_highs_pools", True, 1.0), ("equal_lows_pools", False, -1.0)):
            for pool in pools.get(key, []):
                level = pool.get("level")
                if level is None or (level > current_price) != above:
                    continue
                magnitude = min(25.0, (pool.get("touch_count", 0) or 0) * 4.0)
                if magnitude > 0:
                    net += sign * magnitude
                    max_possible += magnitude
                    reasons.append(f"liquidity pool at {level:.5f} ({pool.get('touch_count')} touches) "
                                   f"{'above' if above else 'below'} price")
                break

    # --- 4. Wyckoff spring (accumulation + sweep of the lows, reclaimed up)
    # or UTAD (distribution + sweep of the highs, reclaimed down). ---
    if wyckoff_phase and most_recent_hunt:
        phase_upper = wyckoff_phase.upper()
        hunt_dir = _hunt_direction(most_recent_hunt)
        is_spring = "ACCUMULATION" in phase_upper and hunt_dir == "BULLISH"
        is_utad = "DISTRIBUTION" in phase_upper and hunt_dir == "BEARISH"
        if is_spring or is_utad:
            magnitude = 35.0
            net += magnitude if is_spring else -magnitude
            max_possible += magnitude
            reasons.append(f"Wyckoff {'spring' if is_spring else 'UTAD'}: {phase_upper} phase + {most_recent_hunt.get('type')}")

    # Liquidity pools alone are a draw, not a trade reading: equal highs and
    # lows exist on nearly every bar, which kept a direction on 99.8% of
    # study bars. Without a recent stop hunt or an order-block reading there
    # is no order-flow call.
    if not most_recent_hunt and not (ob.get("available") and ob.get("status")):
        net, max_possible = 0.0, 0.0

    # judged against the side being scored
    net = net if best_direction == "BUY" else -net

    if max_possible == 0:
        return {
            "order_flow_recommendation": "NEUTRAL",
            "order_flow_score": 0,
            "order_flow_contribution": 0,
            "final_score": round(base_probability, 2),
            "order_flow_weight_used": 0,
            "aligned": True,
            "reasons": [],
        }

    order_flow_score = min(100.0, abs(net))
    order_flow_recommendation = agree_label if net > 0 else (oppose_label if net < 0 else "NEUTRAL")
    weight = ORDER_FLOW_WEIGHT
    aligned = net >= 0

    if order_flow_recommendation == agree_label:
        contribution = (order_flow_score / 100) * weight * 100
    elif order_flow_recommendation == oppose_label:
        contribution = -(order_flow_score / 100) * weight * 100
    else:
        contribution = 0.0

    max_contribution = weight * 100
    contribution = max(-max_contribution, min(max_contribution, contribution))

    final_score = max(5.0, min(95.0, base_probability + contribution))

    return {
        "order_flow_recommendation": order_flow_recommendation,
        "order_flow_score": round(order_flow_score, 1),
        "order_flow_contribution": round(contribution, 2),
        "final_score": round(final_score, 2),
        "order_flow_weight_used": round(weight * 100, 1),
        "aligned": aligned,
        "reasons": reasons,
    }