# ============================================================
# ASSET ANALYSIS - SMC, FVG/ICT, WYCKOFF/SD COMPONENTS, AND
# REVERSAL/SETUP EVALUATORS
# ============================================================
# FILE: core/asset_analysis_smc.py
#
# Split out of asset_analysis.py (which had grown past 7,400 lines) to
# reduce its length -- this is a pure code-motion, not a rewrite: every
# function/constant below is byte-for-byte identical to what was in
# asset_analysis.py, just relocated together. Contains:
#   - FVG/ICT/Wyckoff/supply-demand component analyzers
#     (_analyze_ict_component, _analyze_wyckoff_component,
#     _analyze_supply_demand_component)
#   - Smart Money Concepts: market structure (BOS/CHoCH), order blocks,
#     liquidity sweeps, premium/discount, analyze_smc_structure(),
#     evaluate_smc_trade_setup(), calculate_smc_final_score(),
#     calculate_fvg_ifvg_final_score()
#   - Reversal setup evaluators: BB mean-reversion, RSI/Stochastic
#     reversal, EMA crossover, Wave-C Fibonacci, FVG/IFVG
#   - Volume-profile confluence checks (S/R, supply/demand, order
#     block, liquidity sweep, liquidity pools, Wyckoff, breakout)
#
# Kept together in ONE file rather than split further because these
# pieces have genuine, real, multi-directional dependencies on each
# other (e.g. the reversal-setup evaluators need SMC_ELITE_MIN_
# CONFLUENCE and the FVG tier constants; evaluate_smc_trade_setup()
# needs the setup evaluators' own _get_pip_value_per_pip() utility) --
# forcing them into separate files would create either a circular
# import or move constants across an arbitrary boundary. This file has
# NO dependency on asset_analysis.py or asset_analysis_indicators.py;
# only on core.asset_analysis_config, core.calculations, core.
# indicators, and core.swing_points (all pre-existing, independent
# modules). asset_analysis.py imports FROM this file, never the other
# way around, so there is no circular import.
# ============================================================

from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import logging
import MetaTrader5 as mt5

from core.calculations import _calculate_ema, calculate_lot_proper, calculate_fvg_distance_pips
from core.indicators import (
    _detect_fvg,
    detect_all_fvgs,
    get_ict_recommendation,
    _detect_supply_demand_zone,
    _detect_wyckoff_phase,
    _get_zone_touch_distance,
    _calculate_initial_touch_count,
    get_effective_zone_touch_count,
    get_zone_quality_breakdown,
)
from core.swing_points import find_swing_points, get_min_swing_size
from core.liquidity_events import detect_liquidity_events, get_primary_sweep
from core.risk_reward import rr_from_prices

from core.asset_analysis_config import (
    atr_relative_pips,
    BB_MEAN_REVERSION_EXIT_APPROACH_PCT,
    BB_MEAN_REVERSION_MAX_PIERCE_PCT_B,
    BB_MEAN_REVERSION_MIN_RR,
    BB_MEAN_REVERSION_SL_BUFFER_SPREAD_MULT,
    BB_MEAN_REVERSION_SL_MIN_BUFFER_PIPS,
    EMA_CROSSOVER_MAX_SL_ATR_MULT,
    EMA_CROSSOVER_SL_BUFFER_SPREAD_MULT,
    EMA_CROSSOVER_SL_MIN_BUFFER_PIPS,
    EMA_FAST,
    EMA_MEDIUM,
    FVG_FRESHNESS_SCORE_WEIGHT,
    FVG_IFVG_MIN_TIER_SCORE,
    FVG_IFVG_SETUP_MIN_RR,
    FVG_IFVG_SETUP_SL_BUFFER_SPREAD_MULT,
    FVG_IFVG_SETUP_SL_MIN_BUFFER_PIPS,
    FVG_IFVG_WEIGHT,
    FVG_VOLUME_SCORE_WEIGHT,
    FVG_WIDTH_SCORE_WEIGHT,
    LIQUIDITY_POOL_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    OB_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    RSI_EXTREME_OVERBOUGHT,
    RSI_EXTREME_OVERSOLD,
    RSI_REVERSAL_FIB_DEEP,
    RSI_REVERSAL_FIB_NORMAL,
    RSI_REVERSAL_MIN_RR,
    RSI_REVERSAL_SETUP_MIN_CONFIDENCE,
    RSI_REVERSAL_SL_BUFFER_SPREAD_MULT,
    RSI_REVERSAL_SL_MIN_BUFFER_PIPS,
    SD_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    SMC_SETUP_RISK_PER_TRADE,
    SMC_SETUP_TRADE_SIZE_USD,
    SR_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    STOCH_EXTREME_OVERBOUGHT,
    STOCH_EXTREME_OVERSOLD,
    STOCH_REVERSAL_FIB_DEEP,
    STOCH_REVERSAL_FIB_NORMAL,
    STOCH_REVERSAL_MIN_RR,
    STOCH_REVERSAL_SETUP_MIN_CONFIDENCE,
    STOCH_REVERSAL_SL_BUFFER_SPREAD_MULT,
    STOCH_REVERSAL_SL_MIN_BUFFER_PIPS,
    SWEEP_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    VOLUME_PROFILE_INSIDE_VA_CONFIDENCE,
    VOLUME_PROFILE_INSIDE_VA_SCORE,
    VOLUME_PROFILE_MAX_CONFIDENCE,
    VOLUME_PROFILE_MAX_SCORE,
    VOLUME_PROFILE_MIN_CONFIDENCE_AT_EDGE,
    VOLUME_PROFILE_MIN_SCORE_AT_EDGE,
    VOLUME_PROFILE_REQUIRE_CONFLUENCE,
    WAVE_C_ENTRY_ZONE_PCT,
    WAVE_C_FIB_EXTENSION,
    WAVE_C_OVEREXTENSION_TOLERANCE,
    WAVE_C_SETUP_MIN_RR,
    WAVE_C_SETUP_SL_BUFFER_SPREAD_MULT,
    WAVE_C_SETUP_SL_MIN_BUFFER_PIPS,
    WYCKOFF_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    get_ema_min_separation_pips,
)

logger = logging.getLogger(__name__)


# ✅ NEW: minimum FVG width - a 0.1 pip gap isn't a meaningful
# imbalance and shouldn't be treated the same as a real one. Tune per
# instrument category if needed (this default targets Forex majors).
MIN_FVG_WIDTH_PIPS = 0.5

# ✅ NEW: FVG age decay - an FVG formed 100 bars ago is much less
# likely to still be a valid institutional imbalance than one formed 3
# bars ago. Full strength for AGE_GRACE_BARS, then linear decay to 0
# over AGE_DECAY_BARS more, matching "strength decays after 25 bars".
FVG_AGE_GRACE_BARS = 25
FVG_AGE_DECAY_BARS = 50

# ✅ NEW: normalization caps for the tier-score components below. Not
# present in config - tuned as reasonable defaults for Forex majors,
# worth revisiting per instrument category (Gold/indices have very
# different natural FVG widths).
# ✅ SCALED. 5.0 pips is a sensible "this gap is wide" mark on an FX major
# with a 10-pip ATR. On XAGUSD it is not: 26 of 29 observed gaps were
# 5 pips or wider (range 2-116, median 21), so width_score saturated at
# 100 on nearly every gap and stopped discriminating between a 6-pip
# imbalance and a 116-pip one. That score feeds the FVG tier, which feeds
# an FVG/IFVG contribution worth up to ±15 probability.
#
# Kept as a floor and scaled by ATR at call time via atr_relative_pips.
# 0.25 ATR puts full marks at ~19 pips on a 76-ATR bar -- around the
# observed median, so the scale spans the actual distribution instead of
# pinning to its top.
FVG_TIER_MAX_WIDTH_PIPS = 5.0   # width >= this scores full marks (floor; see below)
FVG_TIER_MAX_WIDTH_ATR_FRACTION = 0.25

# MIN_FVG_WIDTH_PIPS stays absolute deliberately: it rejects sub-tick
# noise, and a 0.5-pip gap is noise on every instrument. Scaling a floor
# that low buys nothing and risks discarding real narrow gaps.
FVG_TIER_MIN_VOLUME_RATIO = 0.5  # volume_ratio <= this scores zero
FVG_TIER_MAX_VOLUME_RATIO = 1.5  # volume_ratio >= this scores full marks


def _analyze_ict_component(rates: np.ndarray, current_price: float, pip_size: float,
                            fvg_tolerance: float, volume_ratio: float = 1.0,
                            atr_pips: float = None) -> Dict[str, Any]:
    """Analyze ICT/FVG component."""
    ict_signal_type, ict_fvg_high, ict_fvg_low, ict_fvg_level, fvg_index = _detect_fvg(
        rates, atr_price=(atr_pips * pip_size) if atr_pips and pip_size else None)
    ict_signals = {"fvg": {"type": ict_signal_type, "level": ict_fvg_level}} if ict_fvg_level else {}
    
    price_above_fvg_pips = 0.0
    price_below_fvg_pips = 0.0
    distance_to_fvg_pips = 0.0
    is_price_in_fvg = False
    fvg_width_pips = 0.0
    fvg_age_bars = None
    fvg_strength = 0.0
    fvg_valid = False
    
    if ict_fvg_level is not None and ict_fvg_high is not None and ict_fvg_low is not None:
        if ict_signal_type == "BULLISH":
            price_above_fvg_pips = calculate_fvg_distance_pips(current_price, ict_fvg_level, pip_size)
            if price_above_fvg_pips < 0:
                price_below_fvg_pips = abs(price_above_fvg_pips)
                price_above_fvg_pips = 0
            distance_to_fvg_pips = abs(current_price - ict_fvg_level) / pip_size if pip_size > 0 else 0
            is_price_in_fvg = ict_fvg_low <= current_price <= ict_fvg_high
        else:
            fvg_distance = current_price - ict_fvg_level
            if fvg_distance > 0:
                price_above_fvg_pips = fvg_distance / pip_size if pip_size > 0 else 0
                price_below_fvg_pips = 0
            else:
                price_above_fvg_pips = 0
                price_below_fvg_pips = abs(fvg_distance) / pip_size if pip_size > 0 else 0
            distance_to_fvg_pips = abs(current_price - ict_fvg_level) / pip_size if pip_size > 0 else 0
            is_price_in_fvg = ict_fvg_low <= current_price <= ict_fvg_high
        
        # ✅ NEW: width filter
        fvg_width_pips = (ict_fvg_high - ict_fvg_low) / pip_size if pip_size > 0 else 0
        
        # ✅ NEW: age decay. fvg_index is _detect_fvg()'s
        # distance_from_end value - already the FVG's age in bars from
        # the most recent candle, not a raw array index (verified
        # against the real _detect_fvg() source).
        if fvg_index is not None:
            fvg_age_bars = max(0, int(fvg_index))
            if fvg_age_bars <= FVG_AGE_GRACE_BARS:
                fvg_strength = 1.0
            else:
                decayed = 1.0 - (fvg_age_bars - FVG_AGE_GRACE_BARS) / FVG_AGE_DECAY_BARS
                fvg_strength = max(0.0, decayed)
        else:
            fvg_strength = 1.0  # unknown age - don't penalize
        
        fvg_valid = (fvg_width_pips >= MIN_FVG_WIDTH_PIPS) and (fvg_strength > 0.0)
        
        if not fvg_valid:
            # Too small or too old to trust - don't let it gate entries
            is_price_in_fvg = False
    
    # ============================================================
    # ✅ NEW (FVG Tier System): combine width + freshness + volume into
    # one quality score using FVG_WIDTH_SCORE_WEIGHT (40) /
    # FVG_FRESHNESS_SCORE_WEIGHT (30) / FVG_VOLUME_SCORE_WEIGHT (20)
    # from asset_analysis_config.py - these constants existed and were
    # imported into calculations.py already, but grep confirms they
    # were never actually applied anywhere in the codebase before this.
    # ============================================================
    fvg_tier_score = 0.0
    fvg_tier = "NONE"
    if ict_fvg_level is not None:
        _tier_max_w = atr_relative_pips(FVG_TIER_MAX_WIDTH_PIPS, atr_pips, FVG_TIER_MAX_WIDTH_ATR_FRACTION)
        width_score = min(100.0, (fvg_width_pips / _tier_max_w) * 100.0)
        freshness_score = fvg_strength * 100.0
        vol_range = FVG_TIER_MAX_VOLUME_RATIO - FVG_TIER_MIN_VOLUME_RATIO
        if vol_range > 0:
            volume_score = min(100.0, max(0.0, (volume_ratio - FVG_TIER_MIN_VOLUME_RATIO) / vol_range * 100.0))
        else:
            volume_score = 50.0
        
        total_weight = FVG_WIDTH_SCORE_WEIGHT + FVG_FRESHNESS_SCORE_WEIGHT + FVG_VOLUME_SCORE_WEIGHT
        fvg_tier_score = (
            width_score * FVG_WIDTH_SCORE_WEIGHT
            + freshness_score * FVG_FRESHNESS_SCORE_WEIGHT
            + volume_score * FVG_VOLUME_SCORE_WEIGHT
        ) / total_weight if total_weight > 0 else 0.0
        
        if fvg_tier_score >= 70:
            fvg_tier = "TIER_1"
        elif fvg_tier_score >= 40:
            fvg_tier = "TIER_2"
        else:
            fvg_tier = "TIER_3"
    
    return {
        "signal_type": ict_signal_type,
        "signals": ict_signals,
        "fvg_high": ict_fvg_high,
        "fvg_low": ict_fvg_low,
        "fvg_level": ict_fvg_level,
        "fvg_index": fvg_index,
        "price_above_fvg_pips": price_above_fvg_pips,
        "price_below_fvg_pips": price_below_fvg_pips,
        "distance_to_fvg_pips": distance_to_fvg_pips,
        "is_price_in_fvg": is_price_in_fvg,
        "fvg_width_pips": round(fvg_width_pips, 2),
        "fvg_age_bars": fvg_age_bars,
        "fvg_strength": round(fvg_strength, 2),
        "fvg_valid": fvg_valid,
        "fvg_tier_score": round(fvg_tier_score, 1),
        "fvg_tier": fvg_tier,
    }


def _analyze_wyckoff_component(rates: np.ndarray, adx_value: float, trend: str, volume_ratio: float, 
                               symbol: str, pip_size: float, timeframe: str = "M1") -> Dict[str, Any]:
    """Analyze Wyckoff phase component with timeframe support."""
    wyckoff_phase = _detect_wyckoff_phase(rates, adx_value, trend, volume_ratio, symbol, pip_size, timeframe)
    wyckoff_score = 95 if wyckoff_phase in ["MARKUP_STRONG", "MARKDOWN_STRONG", "ACCUMULATION_COMPLETE", "DISTRIBUTION_COMPLETE"] else 75 if wyckoff_phase in ["MARKUP", "MARKDOWN", "ACCUMULATION_BUILDING"] else 40 if "TENTATIVE" in wyckoff_phase else 0

    # ✅ FIXED (2026-09-15): the recommendation came from MARKUP/MARKDOWN,
    # which _detect_wyckoff_phase derives from the trend label and ADX -- the
    # trend component's reading counted a second time -- while the one event
    # only Wyckoff sees, the spring, mapped to NEUTRAL. The phase label stays
    # for context; the vote is the spring (BUY) or the upthrust (SELL).
    if wyckoff_phase == "ACCUMULATION_COMPLETE":
        wyckoff_rec = "BUY"
    elif wyckoff_phase == "DISTRIBUTION_COMPLETE":
        wyckoff_rec = "SELL"
    else:
        wyckoff_rec = "NEUTRAL"
    
    return {
        "phase": wyckoff_phase,
        "score": wyckoff_score,
        "recommendation": wyckoff_rec
    }


def _analyze_supply_demand_component(
    rates: np.ndarray, 
    current_price: float, 
    pip_size: float, 
    symbol: str, 
    timeframe: str = "M1",
    volume_ratio: float = 1.0,
    adx: float = 0.0,
    spread_pips: float = 0,
    atr_pips: float = None
) -> Dict[str, Any]:
    """Analyze supply/demand zone component with timeframe support and penalties."""
    zone_type, zone_level, zone_grade, zone_multiplier, is_at_zone, zone_score = _detect_supply_demand_zone(
        rates, current_price, pip_size, symbol, timeframe,
        volume_ratio=volume_ratio,
        adx=adx,
        spread_pips=spread_pips,
        # ✅ the zone touch band is now floored at a fraction of ATR
        atr_pips=atr_pips
    )
    
    # ✅ FIXED: this was a THIRD, independent copy of the touch-counting
    # logic, and it still carried every defect the shared helper had:
    #   - read r[3] (the LOW) for every zone regardless of type
    #   - counted BARS rather than distinct visits
    #   - never passed atr_pips, so it used the un-floored 1.25-pip band
    #
    # Because the GRADE comes from _detect_supply_demand_zone() (which now
    # uses the fixed helper) while this number is only for display, the two
    # silently disagreed the moment one was fixed. Caught live: a SUPPLY
    # zone graded D -- which requires touch_count >= 2 -- while this loop
    # published touch_count 1 in the very same payload.
    #
    # Now calls the one shared implementation with the same inputs the
    # grade was derived from, so the reported count and the grade can no
    # longer tell different stories.
    # ✅ FIXED (again -- the previous fix was incomplete). Pointing this at
    # the same FUNCTION as the grade path was not enough: the grade path
    # prefers the PERSISTED count from _zone_metadata_store and only
    # computes fresh when the zone is unknown, while this recomputed every
    # time. Live 14:44: zone_grade "D" (needs >= 2) published beside
    # touch_count 0.
    #
    # get_effective_zone_touch_count() reads the store first, exactly as
    # the grade path does, so the reported number is the one that set the
    # grade.
    touch_count = get_effective_zone_touch_count(
        zone_level, zone_type, rates, symbol, pip_size, timeframe, atr_pips
    ) if zone_level else 0
    
    # ============================================================
    # ✅ FIXED: Use zone_score from detection, NEVER set to 0
    # ============================================================
    if zone_type == "DEMAND":
        if zone_grade in ["A", "B"] and is_at_zone:
            # was "IMMEDIATE_ENTRY": no direction word, so every reader parsed a
            # demand zone at price as NO vote and supply/demand only ever voted
            # SELL (3,215 demand setups silent in 19.5k study bars)
            sd_rec, sd_score = "IMMEDIATE_BUY", 98
        elif zone_grade in ["A", "B"]:
            sd_rec, sd_score = "WAIT_FOR_RETEST", 85
        elif zone_grade == "C" and is_at_zone:
            sd_rec, sd_score = "MONITOR", 40
        elif zone_grade == "C":
            sd_rec, sd_score = "MONITOR", 30
        elif zone_grade == "D" and is_at_zone:
            sd_rec, sd_score = "MONITOR", zone_score if zone_score > 0 else 50
        elif zone_grade == "D":
            sd_rec, sd_score = "MONITOR", zone_score if zone_score > 0 else 40
        else:
            sd_rec, sd_score = "AVOID", zone_score if zone_score > 0 else 35
    
    elif zone_type == "SUPPLY":
        if zone_grade in ["A", "B"] and is_at_zone:
            sd_rec, sd_score = "IMMEDIATE_SELL", 98
        elif zone_grade in ["A", "B"]:
            sd_rec, sd_score = "WAIT_FOR_RETEST", 85
        elif zone_grade == "C" and is_at_zone:
            sd_rec, sd_score = "MONITOR", 40
        elif zone_grade == "C":
            sd_rec, sd_score = "MONITOR", 30
        elif zone_grade == "D" and is_at_zone:
            sd_rec, sd_score = "MONITOR", zone_score if zone_score > 0 else 50
        elif zone_grade == "D":
            sd_rec, sd_score = "MONITOR", zone_score if zone_score > 0 else 40
        else:
            sd_rec, sd_score = "AVOID", zone_score if zone_score > 0 else 35
    
    else:
        # ✅ FIXED: No zone detected - preserve zone_score from detection
        sd_rec, sd_score = "NEUTRAL", zone_score if zone_score > 0 else 35
        zone_grade = "E"
        is_at_zone = False
    
    return {
        "zone_type": zone_type,
        "zone_level": zone_level,
        "zone_grade": zone_grade,
        "zone_multiplier": zone_multiplier,
        "is_at_zone": is_at_zone,
        "touch_count": touch_count,
        # ✅ Why this zone graded as it did -- freshness, displacement,
        # touch and volume sub-scores plus the composite. The old
        # touch-only grader had nothing to explain; this one does, and the
        # coherence validator reads it to check the grade against the
        # model that actually produced it.
        "quality_breakdown": get_zone_quality_breakdown(zone_level, zone_type, symbol),
        # ✅ What the LEVEL earned vs what its LOCATION cost it. The
        # single collapsed grade could not express the difference
        # between a weak zone and a strong zone in a poor place.
        "quality_grade": (get_zone_quality_breakdown(zone_level, zone_type, symbol) or {}).get("quality_grade"),
        "recommendation": sd_rec,
        "score": sd_score
    }


SMC_STRUCTURE_LOOKBACK = 5          # swing detection lookback (bars each side)
SMC_ORDER_BLOCK_LOOKBACK = 50        # bars scanned for order blocks
SMC_ORDER_BLOCK_IMPULSE_ATR_MULT = 1.5  # candle range vs avg range to count as "displacement"
SMC_LIQUIDITY_SWEEP_LOOKBACK = 20    # bars scanned for a sweep setup
SMC_PREMIUM_DISCOUNT_LOOKBACK = 50   # bars defining the active range
SMC_MIN_SIGNALS_FOR_DIRECTION = 2    # min agreeing signals before calling BULLISH/BEARISH at all
SMC_TOTAL_POSSIBLE_SIGNALS = 6       # structure, BOS/CHoCH, order block, sweep, premium/discount, FVG/IFVG
# Tunable weight/threshold for calculate_smc_final_score - not present in
# asset_analysis_config.py, defined locally like the FVG tier constants
# above. Matches GNN_WEIGHT's rough magnitude so the two subsystems
# contribute comparably; revisit once you have real trade-history data
# to calibrate against (see the earlier discussion on backtesting before
# trusting any of these numbers).
SMC_WEIGHT = 0.15
# ✅ FIXED: was a hardcoded 40, documented as "< 2/5 signals". That was
# correct when SMC_TOTAL_POSSIBLE_SIGNALS was 5: two signals scored
# exactly 40.0 and sat on the gate. The signal set has since grown to 6
# (structure, BOS/CHoCH, order block, sweep, premium/discount, FVG/IFVG),
# so two signals now score 33.3 and fall UNDER it -- the effective bar
# moved from 2 signals to 3 without the constant, or the comment, ever
# changing.
#
# Live: a 2/6 BULLISH read at score 33.3 contributed exactly 0 to
# probability, while a 3/6 read at 50.0 contributed 7.5.
#
# Derived from the signal count instead of hardcoded, so the intent
# ("fewer than 2 confirming signals is not confluence") survives the next
# time a signal is added or removed.
SMC_MIN_CONFLUENCE_SIGNALS = 2
SMC_MIN_CONFLUENCE_SCORE = round((SMC_MIN_CONFLUENCE_SIGNALS / SMC_TOTAL_POSSIBLE_SIGNALS) * 100, 1)


def _get_smc_swing_sequence(rates: np.ndarray, timeframe: str = "M1", lookback: int = SMC_STRUCTURE_LOOKBACK, pip_size: float = None,
                            atr_pips: float = None) -> List[Dict]:
    """
    Chronological sequence of confirmed swing highs/lows (with bar index)
    built from the shared, amplitude-filtered detector in
    core.swing_points — the same single source of truth already used
    for supply/demand zone candidates and Elliott Wave legs elsewhere
    in this codebase, so "what counts as a real swing" stays consistent
    across every consumer.

    ✅ FIXED: this used to call find_swing_points() TWICE, independently
    — once over the high column, once over the low column — each with
    its OWN amplitude filter checked only against prior points of its
    OWN column. That's the exact same bug already found and fixed in
    indicators.py's old detect_abc_correction(): a high pivot and a low
    pivot could each legitimately clear their own column's amplitude
    filter yet coincidentally land at nearly the same PRICE despite
    being dozens of bars apart, since neither scan had any awareness of
    the other's accepted points. Verified directly against 60 seeds of
    synthetic choppy-market data (the regime this system leans on
    structure/CHoCH analysis most heavily): spurious same-price,
    far-apart-in-time cross-type pairs dropped from 48 to 22 after this
    fix, with the remainder consistent with genuinely tight-ranging
    price action revisiting similar levels rather than a detection
    artifact. This directly corrupted market_structure's HH/HL/LH/LL
    classification and CHoCH/BOS detection, both of which depend on
    comparing consecutive swing prices that are supposed to represent
    genuinely separated turning points.

    Fixed by finding raw local extrema on each column with NO
    per-column amplitude filter, merging by bar index, then applying
    ONE amplitude filter pass across the merged, time-ordered sequence
    — checking each candidate against the last ACCEPTED point of
    EITHER type, exactly like find_swing_points()'s own single-series
    logic, just applied post-merge so high/low (wick) semantics are
    preserved instead of collapsing to a single close-price series.
    """
    if rates is None or len(rates) < (2 * lookback + 1):
        return []
    
    # ✅ pip_size threaded through -- the min-swing table is in pips and
    # must be converted against this instrument's pip size (see
    # swing_points.get_min_swing_size).
    min_amp = get_min_swing_size(timeframe, pip_size, atr_pips)   # ATR-scaled: 0.5 ATR on every instrument
    highs_series = [float(r[2]) for r in rates]
    lows_series = [float(r[3]) for r in rates]
    
    raw_highs = find_swing_points(highs_series, lookback=lookback, min_amplitude=0.0)
    raw_lows = find_swing_points(lows_series, lookback=lookback, min_amplitude=0.0)
    
    candidates = [{"type": "high", "price": p["price"], "index": p["index"]} for p in raw_highs if p["type"] == "high"]
    candidates += [{"type": "low", "price": p["price"], "index": p["index"]} for p in raw_lows if p["type"] == "low"]
    candidates.sort(key=lambda x: x["index"])

    sequence: List[Dict] = []
    last_accepted_price: Optional[float] = None
    for c in candidates:
        if last_accepted_price is None or abs(c["price"] - last_accepted_price) >= min_amp:
            sequence.append(c)
            last_accepted_price = c["price"]
    return sequence


def _detect_market_structure(rates: np.ndarray, current_price: float, timeframe: str = "M1", pip_size: float = None,
                             atr_pips: float = None) -> Dict[str, Any]:
    """
    Classify market structure as BULLISH (higher highs + higher lows),
    BEARISH (lower highs + lower lows), or RANGING, then detect the most
    recent Break of Structure (BOS - continuation) or Change of
    Character (CHoCH - price breaking the "wrong way" against the
    established structure, an early reversal signal).
    """
    swing_seq = _get_smc_swing_sequence(rates, timeframe, pip_size=pip_size, atr_pips=atr_pips)
    if len(swing_seq) < 4:
        return {"structure": "UNKNOWN", "last_event": None, "last_swing_high": None, "last_swing_low": None, "swing_count": len(swing_seq)}
    
    # Collapse consecutive same-type swings to the more extreme one, so we
    # get a real alternating zigzag (high, low, high, low, ...) instead of
    # e.g. two swing highs in a row from a choppy multi-bar top.
    cleaned = [swing_seq[0]]
    for s in swing_seq[1:]:
        if s["type"] == cleaned[-1]["type"]:
            if (s["type"] == "high" and s["price"] > cleaned[-1]["price"]) or \
               (s["type"] == "low" and s["price"] < cleaned[-1]["price"]):
                cleaned[-1] = s
        else:
            cleaned.append(s)
    
    if len(cleaned) < 4:
        return {"structure": "UNKNOWN", "last_event": None, "last_swing_high": None, "last_swing_low": None, "swing_count": len(cleaned)}
    
    last4 = cleaned[-4:]
    types = [s["type"] for s in last4]
    structure = "RANGING"
    
    if types == ["low", "high", "low", "high"]:
        l1, h1, l2, h2 = last4
        if h2["price"] > h1["price"] and l2["price"] > l1["price"]:
            structure = "BULLISH"
        elif h2["price"] < h1["price"] and l2["price"] < l1["price"]:
            structure = "BEARISH"
    elif types == ["high", "low", "high", "low"]:
        h1, l1, h2, l2 = last4
        if h2["price"] > h1["price"] and l2["price"] > l1["price"]:
            structure = "BULLISH"
        elif h2["price"] < h1["price"] and l2["price"] < l1["price"]:
            structure = "BEARISH"
    
    last_swing_high = next((s for s in reversed(cleaned) if s["type"] == "high"), None)
    last_swing_low = next((s for s in reversed(cleaned) if s["type"] == "low"), None)
    
    event = None
    if structure == "BULLISH" and last_swing_low and current_price < last_swing_low["price"]:
        event = "BEARISH_CHoCH"  # broke below the last higher-low -> possible reversal
    elif structure == "BEARISH" and last_swing_high and current_price > last_swing_high["price"]:
        event = "BULLISH_CHoCH"  # broke above the last lower-high -> possible reversal
    elif structure == "BULLISH" and last_swing_high and current_price > last_swing_high["price"]:
        event = "BULLISH_BOS"    # continuation break above the last high
    elif structure == "BEARISH" and last_swing_low and current_price < last_swing_low["price"]:
        event = "BEARISH_BOS"    # continuation break below the last low
    
    # ✅ FIXED (2026-09-15): a change of character IS the structure changing.
    # The label used to stay on the old swings' reading, so a bar that broke
    # the last higher low reported structure BULLISH next to BEARISH_CHoCH --
    # and every consumer reading `structure` got the invalidated side.
    swing_structure = structure
    if event == "BEARISH_CHoCH":
        structure = "BEARISH"
    elif event == "BULLISH_CHoCH":
        structure = "BULLISH"

    return {
        "structure": structure,
        "swing_structure": swing_structure,
        "last_event": event,
        "last_swing_high": round(last_swing_high["price"], 5) if last_swing_high else None,
        "last_swing_low": round(last_swing_low["price"], 5) if last_swing_low else None,
        "swing_count": len(cleaned),
    }


def _detect_order_blocks(rates: np.ndarray, lookback_bars: int = SMC_ORDER_BLOCK_LOOKBACK,
                          impulse_mult: float = SMC_ORDER_BLOCK_IMPULSE_ATR_MULT) -> Dict[str, Any]:
    """
    An order block is the last opposing candle before a strong
    (displacement) impulsive move — the last down-close candle before a
    sharp bullish move (bullish OB), or the last up-close candle before a
    sharp bearish move (bearish OB). Distinct from the FVG detected in
    the ICT component above (a price gap, not a candle).
    Returns the MOST RECENT qualifying block of each type within the
    lookback window.
    """
    if rates is None or len(rates) < 10:
        return {"bullish_ob": None, "bearish_ob": None}
    
    window = rates[-lookback_bars:] if len(rates) > lookback_bars else rates
    n = len(window)
    if n < 3:
        return {"bullish_ob": None, "bearish_ob": None}
    
    ranges = [float(window[i][2]) - float(window[i][3]) for i in range(n)]
    avg_range = sum(ranges) / len(ranges) if ranges else 0.0
    if avg_range <= 0:
        return {"bullish_ob": None, "bearish_ob": None}
    
    bullish_ob = None
    bearish_ob = None
    
    for i in range(1, n):
        o, h, l, c = float(window[i][1]), float(window[i][2]), float(window[i][3]), float(window[i][4])
        candle_range = h - l
        is_bullish_impulse = (c > o) and candle_range > avg_range * impulse_mult
        is_bearish_impulse = (c < o) and candle_range > avg_range * impulse_mult
        
        prev = window[i - 1]
        po, pc = float(prev[1]), float(prev[4])
        
        if is_bullish_impulse and pc < po:
            bullish_ob = {"high": round(float(prev[2]), 5), "low": round(float(prev[3]), 5), "bars_ago": n - i}
        if is_bearish_impulse and pc > po:
            bearish_ob = {"high": round(float(prev[2]), 5), "low": round(float(prev[3]), 5), "bars_ago": n - i}
    
    return {"bullish_ob": bullish_ob, "bearish_ob": bearish_ob}


def _detect_liquidity_sweep(rates: np.ndarray, lookback: int = SMC_LIQUIDITY_SWEEP_LOOKBACK,
                             pip_size: float = None, timeframe: str = "M1",
                             atr_pips: float = None, spread_pips: float = 0.0) -> Dict[str, Any]:
    """
    Liquidity sweep, delegated to the canonical engine.

    ✅ This function used to implement its own detection: any of the last
    3 bars wicking beyond a 20-bar max/min, with all 3 closing back
    inside, and NO minimum sweep size — a 0.1-pip poke qualified.
    order_flow_forensics.detect_stop_hunts() implemented the same idea
    differently: real ATR-filtered swing points, a sweep floor measured
    against the spread, an explicit reclaim window.

    Two definitions of one market event, disagreeing on the same bar.
    SMC could report "no sweep" while order flow reported five, and
    nothing reconciled them — so SL placement, the SMC confluence count
    and the order-flow probability adjustment could each be acting on a
    different view of the same tape.

    Both now read core/liquidity_events.py. The return shape is unchanged
    so every existing consumer keeps working; `event` is added for
    callers that want the strength, reclaim speed and size the legacy
    version never exposed.

    pip_size/atr_pips/spread_pips default to None/0 so an un-updated
    caller still gets sane behaviour — without them the engine falls back
    to its own floors rather than guessing.
    """
    if pip_size is None:
        try:
            pip_size = float(rates[-1][4]) * 1e-5 if rates is not None and len(rates) else 0.0001
        except (IndexError, TypeError, ValueError):
            pip_size = 0.0001

    try:
        events = detect_liquidity_events(
            rates, pip_size, timeframe,
            atr_pips=atr_pips, spread_pips=spread_pips,   # significant levels, one definition
        )
        return get_primary_sweep(events)
    except Exception as e:
        logger.debug(f"[SMC] liquidity sweep delegation failed: {e}")
        return {"swept": False, "type": None, "level": None, "event": None}

def _calculate_premium_discount(rates: np.ndarray, current_price: float,
                                 lookback: int = SMC_PREMIUM_DISCOUNT_LOOKBACK) -> Dict[str, Any]:
    """
    Where is price sitting within its recent range? Below 30% = discount
    (favor BUYs — "on sale"), above 70% = premium (favor SELLs —
    "expensive"), 30-70% = equilibrium. Also flags the classic ICT "OTE"
    (Optimal Trade Entry) 61.8%-79% Fibonacci retracement zone in both
    directions.
    """
    window = rates[-lookback:] if rates is not None and len(rates) > lookback else rates
    if window is None or len(window) < 5:
        return {"zone": "UNKNOWN", "range_high": None, "range_low": None, "position_pct": 50.0,
                "in_ote_discount": False, "in_ote_premium": False}
    
    range_high = max(float(r[2]) for r in window)
    range_low = min(float(r[3]) for r in window)
    
    if range_high <= range_low:
        return {"zone": "EQUILIBRIUM", "range_high": range_high, "range_low": range_low, "position_pct": 50.0,
                "in_ote_discount": False, "in_ote_premium": False}
    
    position_pct = (current_price - range_low) / (range_high - range_low) * 100
    
    if position_pct <= 30:
        zone = "DISCOUNT"
    elif position_pct >= 70:
        zone = "PREMIUM"
    else:
        zone = "EQUILIBRIUM"
    
    return {
        "zone": zone,
        "range_high": round(range_high, 5),
        "range_low": round(range_low, 5),
        "position_pct": round(position_pct, 1),
        # 61.8%-79% retracement of a bullish leg (measured from the top) ==
        # 21%-38.2% position from the bottom of the range.
        "in_ote_discount": 21.0 <= position_pct <= 38.2,
        "in_ote_premium": 61.8 <= position_pct <= 79.0,
    }


def analyze_smc_structure(rates: np.ndarray, current_price: float, pip_size: float,
                           symbol: str, timeframe: str = "M1",
                           fvg_ifvg: Optional[Dict[str, Any]] = None,
                           atr_pips: float = None,
                           spread_pips: float = 0.0) -> Dict[str, Any]:
    """
    ✅ ELITE SMC: combines Market Structure (BOS/CHoCH), Order Blocks,
    Liquidity Sweeps, Premium/Discount zones, and FVG/IFVG into one
    confluence-scored recommendation. Requires at least
    SMC_MIN_SIGNALS_FOR_DIRECTION independent signals to agree before
    calling a direction at all — a single piece (e.g. "price is in an
    order block") is not, on its own, treated as a trade signal, exactly
    the confluence discipline real SMC trading is built on.

    ✅ FIXED: FVG/IFVG used to be completely absent from this vote — the
    "fvg" field in the returned dict was a literal pointer saying "see
    the ICT component elsewhere", and fair value gaps never counted
    toward confluence_count/reasons/score here at all, despite FVG zones
    being as core a Smart Money Concept as order blocks or liquidity
    sweeps. That meant SMC's own explanation of itself (reasons,
    confluence_count) could be silently incomplete: the separate
    probability chain elsewhere DID apply FVG/IFVG's own adjustment
    afterward, but SMC's internal read never acknowledged it, so a case
    where FVG strongly disagreed with SMC's structure-based read wasn't
    visible in SMC's own reasoning at all. Fixed by accepting the
    already-computed FVG/IFVG indicator (score_fvg_ifvg_indicator's
    output — not recomputed here) as a genuine confluence vote, on equal
    footing with the other four signal types.
    """
    structure = _detect_market_structure(rates, current_price, timeframe, pip_size=pip_size, atr_pips=atr_pips)
    order_blocks = _detect_order_blocks(rates)
    # ✅ pip_size/atr/spread passed through so the canonical engine can
    # apply its spread and ATR floors. Without them a sub-spread poke
    # counts as a sweep -- the bug that had a 6-pip "stop hunt" driving a
    # -12.0 adjustment against a 20-pip spread.
    sweep = _detect_liquidity_sweep(rates, pip_size=pip_size, timeframe=timeframe,
                                    atr_pips=atr_pips, spread_pips=spread_pips)
    premium_discount = _calculate_premium_discount(rates, current_price)
    fvg_ifvg = fvg_ifvg or {}
    
    bullish_signals = 0
    bearish_signals = 0
    reasons = []
    
    # ✅ FIXED: a CHoCH specifically means the prior structure classification
    # just broke - counting a vote for that structure AND its own CHoCH
    # reversal in the same tally double-counts a now-invalidated signal,
    # and can let a stale structure label outvote a fresh reversal signal
    # (confirmed via testing: a BULLISH structure + BEARISH_CHoCH scenario
    # incorrectly netted out to a BULLISH recommendation before this fix).
    # BOS (continuation) legitimately still reinforces the structure vote,
    # since it confirms the existing trend rather than breaking it.
    if structure["last_event"] == "BULLISH_CHoCH":
        bullish_signals += 1
        reasons.append("BULLISH CHoCH (structure reversal)")
    elif structure["last_event"] == "BEARISH_CHoCH":
        bearish_signals += 1
        reasons.append("BEARISH CHoCH (structure reversal)")
    else:
        if structure["last_event"] == "BULLISH_BOS":
            bullish_signals += 1
            reasons.append("BULLISH BOS (continuation)")
        elif structure["last_event"] == "BEARISH_BOS":
            bearish_signals += 1
            reasons.append("BEARISH BOS (continuation)")
        
        if structure["structure"] == "BULLISH":
            bullish_signals += 1
            reasons.append("Bullish market structure (HH + HL)")
        elif structure["structure"] == "BEARISH":
            bearish_signals += 1
            reasons.append("Bearish market structure (LH + LL)")
    
    bullish_ob = order_blocks.get("bullish_ob")
    bearish_ob = order_blocks.get("bearish_ob")
    price_in_bullish_ob = bool(bullish_ob and bullish_ob["low"] <= current_price <= bullish_ob["high"])
    price_in_bearish_ob = bool(bearish_ob and bearish_ob["low"] <= current_price <= bearish_ob["high"])
    if price_in_bullish_ob:
        bullish_signals += 1
        reasons.append("Price at bullish order block")
    if price_in_bearish_ob:
        bearish_signals += 1
        reasons.append("Price at bearish order block")
    
    if sweep["type"] == "BULLISH_SWEEP":
        bullish_signals += 1
        reasons.append("Liquidity swept below prior lows, reversing up")
    elif sweep["type"] == "BEARISH_SWEEP":
        bearish_signals += 1
        reasons.append("Liquidity swept above prior highs, reversing down")
    
    if premium_discount["zone"] == "DISCOUNT":
        bullish_signals += 1
        reasons.append("Price in discount zone")
    elif premium_discount["zone"] == "PREMIUM":
        bearish_signals += 1
        reasons.append("Price in premium zone")

    fvg_direction = fvg_ifvg.get("recommendation")
    if fvg_direction == "BUY":
        bullish_signals += 1
        reasons.append(f"FVG/IFVG bullish: {fvg_ifvg.get('reason', '')}")
    elif fvg_direction == "SELL":
        bearish_signals += 1
        reasons.append(f"FVG/IFVG bearish: {fvg_ifvg.get('reason', '')}")
    
    if bullish_signals > bearish_signals and bullish_signals >= SMC_MIN_SIGNALS_FOR_DIRECTION:
        recommendation = "BULLISH"
        confluence_count = bullish_signals
    elif bearish_signals > bullish_signals and bearish_signals >= SMC_MIN_SIGNALS_FOR_DIRECTION:
        recommendation = "BEARISH"
        confluence_count = bearish_signals
    else:
        recommendation = "NEUTRAL"
        confluence_count = max(bullish_signals, bearish_signals)
    
    confluence_score = round((confluence_count / SMC_TOTAL_POSSIBLE_SIGNALS) * 100, 1) if recommendation != "NEUTRAL" else 0.0
    
    return {
        "available": True,
        "recommendation": recommendation,
        "score": confluence_score,
        "confluence_count": confluence_count,
        "total_possible_signals": SMC_TOTAL_POSSIBLE_SIGNALS,
        "reasons": reasons,
        "market_structure": structure,
        "order_blocks": {
            "bullish_ob": bullish_ob,
            "bearish_ob": bearish_ob,
            "price_in_bullish_ob": price_in_bullish_ob,
            "price_in_bearish_ob": price_in_bearish_ob,
        },
        "fvg": {
            "available": bool(fvg_direction),
            "recommendation": fvg_direction or "NEUTRAL",
            "score": fvg_ifvg.get("score", 0),
            "confidence": fvg_ifvg.get("confidence", 0),
            "reason": fvg_ifvg.get("reason", ""),
            "counted_in_confluence": fvg_direction in ("BUY", "SELL"),
        },
        "liquidity_sweep": sweep,
        "premium_discount": premium_discount,
    }


def calculate_smc_final_score(smc_analysis: Dict[str, Any], base_probability: float, best_direction: str = "BUY") -> Dict[str, Any]:
    """
    Calculate SMC's contribution to the final trade score. Deliberately
    mirrors calculate_gnn_final_score()'s architecture (bounded
    contribution, direction-alignment check, confidence-scaled weight)
    so the two analytical subsystems compose predictably instead of each
    inventing its own blending rule — and, per the wiring bug found and
    fixed in the GNN pipeline this session, the caller MUST apply
    final_score back onto best_probability, not just log it.

    `best_direction` ("BUY" or "SELL") is required to correctly interpret
    alignment, for the same reason it's required in calculate_gnn_final_score:
    base_probability is the probability the CHOSEN direction is correct, not
    an absolute bullish/bearish market read, so alignment must be judged
    against best_direction rather than against base_probability > 50.
    """
    if not smc_analysis.get("available", False):
        return {
            "smc_recommendation": "UNAVAILABLE",
            "smc_score": 0,
            "smc_contribution": 0,
            "final_score": base_probability,
            "smc_weight_used": 0,
            "aligned": True,
        }
    
    smc_recommendation = smc_analysis.get("recommendation", "NEUTRAL")
    confluence_score = smc_analysis.get("score", 0)
    
    # ✅ FIXED: previously `smc_weight = SMC_WEIGHT * (confluence_score / 100.0)`
    # here, and the contribution formula below ALSO multiplies by
    # `(confluence_score / 100)` -- confluence_score was being applied
    # twice (quadratically), silently crushing SMC's real impact relative
    # to GNN, which this function's own docstring says it's meant to
    # mirror. At confluence_score=40 (2/5 signals, right at the gate),
    # that squaring alone cuts the intended contribution to ~40% of what
    # an equally-weighted GNN read would get, before the (separate,
    # intentional) misalignment penalty below even applies. SMC_WEIGHT is
    # now the actual weight, exactly like GNN_WEIGHT is in
    # calculate_gnn_final_score -- confluence_score still scales the
    # final contribution once, in the formula below, same as before.
    smc_weight = SMC_WEIGHT
    
    if confluence_score < SMC_MIN_CONFLUENCE_SCORE:
        confluence_score = 0
        smc_weight = 0
    
    # ✅ FIXED: same base_probability > 50 inversion described in
    # calculate_gnn_final_score() -- judged against best_direction now.
    agree_label = "BULLISH" if best_direction == "BUY" else "BEARISH"
    oppose_label = "BEARISH" if best_direction == "BUY" else "BULLISH"

    aligned = True

    if smc_recommendation == oppose_label:
        aligned = False
        smc_weight = smc_weight * 0.2
    
    if smc_recommendation == agree_label:
        smc_contribution = (confluence_score / 100) * smc_weight * 100
    elif smc_recommendation == oppose_label:
        smc_contribution = -(confluence_score / 100) * smc_weight * 100
    else:
        smc_contribution = 0
    
    max_contribution = smc_weight * 100
    smc_contribution = max(-max_contribution, min(max_contribution, smc_contribution))
    
    final_score = base_probability + smc_contribution
    final_score = max(5.0, min(95.0, final_score))
    
    return {
        "smc_recommendation": smc_recommendation,
        "smc_score": confluence_score,
        "smc_contribution": round(smc_contribution, 2),
        "final_score": round(final_score, 2),
        "smc_weight_used": round(smc_weight * 100, 1),
        "aligned": aligned,
    }


def calculate_fvg_ifvg_final_score(fvg_ifvg_result: Dict[str, Any], base_probability: float, best_direction: str = "BUY") -> Dict[str, Any]:
    """
    FVG/IFVG's contribution to the final trade score. Mirrors
    calculate_smc_final_score()/calculate_gnn_final_score()'s architecture
    (bounded contribution, direction-alignment check, confidence-scaled
    weight) for the same reason SMC does: score_fvg_ifvg_indicator()
    already produces a real recommendation + signed score every run, but
    previously had no path into best_probability at all -- unlike the
    single-nearest-gap FVG read already wired into the ICT component (via
    calculate_real_probability's ict_signal_type/price_above_fvg_pips/
    price_below_fvg_pips), the richer multi-gap, tier-scored,
    inversion-aware read from score_fvg_ifvg_indicator() was computed and
    displayed but never actually counted toward the trade's probability.

    Unlike GNN/SMC ("BULLISH"/"BEARISH") and pattern (its own direction
    field), score_fvg_ifvg_indicator()'s `recommendation` is already
    "BUY"/"SELL" -- the same vocabulary as best_direction -- so alignment
    is a direct string comparison, no BULLISH/BEARISH mapping needed.
    Its `score` is also already signed on a bounded -25..+25 scale
    (positive favors BUY, negative favors SELL), unlike its siblings'
    unsigned 0-100 scores paired with a separate recommendation label, so
    it's normalized to the same 0-100 magnitude the contribution formula
    below expects.
    """
    recommendation = fvg_ifvg_result.get("recommendation", "NEUTRAL")
    raw_score = fvg_ifvg_result.get("score", 0)

    if recommendation not in ("BUY", "SELL") or raw_score == 0:
        return {
            "fvg_ifvg_recommendation": recommendation,
            "fvg_ifvg_score": raw_score,
            "fvg_ifvg_contribution": 0,
            "final_score": base_probability,
            "fvg_ifvg_weight_used": 0,
            "aligned": True,
        }

    weight = FVG_IFVG_WEIGHT
    magnitude = min(100.0, (abs(raw_score) / 25.0) * 100.0)

    aligned = recommendation == best_direction
    if not aligned:
        weight = weight * 0.2

    fvg_ifvg_contribution = (magnitude / 100) * weight * 100
    if not aligned:
        fvg_ifvg_contribution = -fvg_ifvg_contribution

    max_contribution = weight * 100
    fvg_ifvg_contribution = max(-max_contribution, min(max_contribution, fvg_ifvg_contribution))

    final_score = base_probability + fvg_ifvg_contribution
    final_score = max(5.0, min(95.0, final_score))

    return {
        "fvg_ifvg_recommendation": recommendation,
        "fvg_ifvg_score": raw_score,
        "fvg_ifvg_contribution": round(fvg_ifvg_contribution, 2),
        "final_score": round(final_score, 2),
        "fvg_ifvg_weight_used": round(weight * 100, 1),
        "aligned": aligned,
    }


# ✅ NEW: minimum confluence required to call something a "perfect setup"
# worth a concrete trade plan - below this, evaluate_smc_trade_setup()
# returns is_perfect_setup=False with no price levels at all, rather
# than manufacturing SL/TP for a mediocre read.
# ✅ comment corrected: SMC_TOTAL_POSSIBLE_SIGNALS is 6, not 5. The
# constant itself is a signal COUNT (not a percentage) so it did not
# drift the way SMC_MIN_CONFLUENCE_SCORE did -- 4 of 6 is stricter than
# 4 of 5 was, which is a real change in behaviour, but a coherent one.
SMC_ELITE_MIN_CONFLUENCE = 4  # out of SMC_TOTAL_POSSIBLE_SIGNALS (6)

# Buffer placed beyond the structural SL level so the order isn't
# stopped out by ordinary spread/noise sitting exactly on the level.
# Derived from the symbol's own live spread (not ATR, not a flat
# guess) since spread is the one thing guaranteed to matter at the
# exact moment of a fill.
SMC_SL_BUFFER_SPREAD_MULT = 1.5
SMC_SL_MIN_BUFFER_PIPS = 1.0


def _get_pip_value_per_pip(symbol: str, lot: float, current_price: float, direction: str, pip_size: float) -> Optional[float]:
    """
    Dollar value of a 1-pip move for `lot` lots of `symbol`, via the same
    mt5.order_calc_profit() approach calculate_lot_proper() already uses
    elsewhere in this codebase (kept consistent rather than inventing a
    second pip-value formula).
    """
    try:
        order_type_mt5 = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL
        test_price = current_price + pip_size if direction.upper() == "BUY" else current_price - pip_size
        pip_value = mt5.order_calc_profit(order_type_mt5, symbol, lot, current_price, test_price)
        if pip_value and pip_value > 0:
            return abs(pip_value)
    except Exception as e:
        logger.debug(f"[SMC SETUP] pip value calc failed for {symbol}: {e}")
    
    # Fallback: standard forex-style approximation
    info = mt5.symbol_info(symbol)
    contract_size = float(info.trade_contract_size) if info and info.trade_contract_size else 100000
    return lot * contract_size * pip_size


def _describe_sl_basis(direction: str, order_blocks: Dict, sweep: Dict, structure: Dict, sl_source: str) -> str:
    parts = []
    if sl_source == "order_block":
        parts.append("bullish order block low" if direction == "BUY" else "bearish order block high")
    elif sl_source == "liquidity_sweep":
        parts.append("liquidity sweep level")
    elif sl_source == "swing_point":
        parts.append("last opposing swing point" )
    return f"{parts[0]} (nearest structural level to entry - the specific zone this setup is based on) + spread buffer" if parts else "structural level + spread buffer"


def evaluate_smc_trade_setup(
    smc_analysis: Dict[str, Any],
    symbol: str,
    order_type: str,
    current_price: float,
    pip_size: float,
    spread_pips: float,
    margin_safe_lot: float,
    target_risk_usd: float = None,
) -> Dict[str, Any]:
    """
    ✅ ELITE SMC TRADE SETUP: turns confluence-scored SMC analysis into a
    concrete MARKET ORDER plan - exact entry, stop loss, take profit, and
    a lot size that respects real account margin - but ONLY when
    confluence is genuinely elite (>= SMC_ELITE_MIN_CONFLUENCE) and every
    price level traces back to real market structure.
    
    Design contract:
    - SL and TP come ONLY from SMC structure: the order block boundary /
      liquidity sweep level / last swing point, using whichever is
      NEAREST to entry (the specific, tightest invalidation point for
      this exact setup) for SL, and the next opposing structure swing
      point for TP. No ATR, no fixed R:R fallback, no arbitrary pip
      counts. If no structural level exists for either side, this
      returns is_perfect_setup=False rather than inventing one.
    - Lot size: margin_safe_lot (passed in - the real-leverage,
      real-margin-safe ceiling calculate_lot_proper() already computed
      elsewhere in this pipeline) is the STARTING ceiling, never
      exceeded. Because margin_safe_lot was originally sized against
      calculate_lot_proper()'s OWN internally-derived SL distance (a
      margin-maximizing calculation, not this structural one), the
      actual dollar risk this structural SL produces on that lot is
      checked explicitly and the lot is scaled DOWN (never up) if it
      would risk more than target_risk_usd - so you get calculate_lot_
      proper()'s margin safety AND a real, bounded dollar risk, with
      SL/TP driven purely by SMC structure as requested.
    """
    if target_risk_usd is None:
        target_risk_usd = SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE
    
    if not smc_analysis or not smc_analysis.get("available"):
        return {"is_perfect_setup": False, "reason": "SMC data unavailable"}
    
    recommendation = smc_analysis.get("recommendation", "NEUTRAL")
    confluence_count = smc_analysis.get("confluence_count", 0)
    
    if recommendation == "NEUTRAL" or confluence_count < SMC_ELITE_MIN_CONFLUENCE:
        return {
            "is_perfect_setup": False,
            "reason": f"Confluence {confluence_count}/{SMC_TOTAL_POSSIBLE_SIGNALS} below elite threshold ({SMC_ELITE_MIN_CONFLUENCE}/{SMC_TOTAL_POSSIBLE_SIGNALS})",
            "confluence_count": confluence_count,
        }
    
    direction = "BUY" if recommendation == "BULLISH" else "SELL"
    if order_type and order_type.upper() not in (direction, "AUTO", "BOTH", ""):
        return {
            "is_perfect_setup": False,
            "reason": f"SMC direction ({direction}) conflicts with the system's own measured best direction ({order_type})",
            "confluence_count": confluence_count,
        }
    
    structure = smc_analysis.get("market_structure", {})
    order_blocks = smc_analysis.get("order_blocks", {})
    sweep = smc_analysis.get("liquidity_sweep", {})
    
    buffer_price = max(spread_pips * SMC_SL_BUFFER_SPREAD_MULT, SMC_SL_MIN_BUFFER_PIPS) * pip_size
    
    # Gather (level, source_label) candidates so we can report which one
    # actually determined the SL, not just the number.
    invalidation_candidates: List[Tuple[float, str]] = []
    tp_candidate = None
    
    if direction == "BUY":
        ob = order_blocks.get("bullish_ob")
        if ob and order_blocks.get("price_in_bullish_ob"):
            invalidation_candidates.append((ob["low"], "order_block"))
        if sweep.get("type") == "BULLISH_SWEEP" and sweep.get("level") is not None:
            invalidation_candidates.append((sweep["level"], "liquidity_sweep"))
        if structure.get("last_swing_low") is not None:
            invalidation_candidates.append((structure["last_swing_low"], "swing_point"))
        
        if not invalidation_candidates:
            return {"is_perfect_setup": False, "reason": "No SMC structural level available for stop loss", "confluence_count": confluence_count}
        
        # ✅ FIXED (via testing): the NEAREST structural level to entry is
        # the precise, specific invalidation point for THIS setup (usually
        # the order block that's the actual reason for entering here) -
        # min() was picking the FURTHEST level (often an old swing low far
        # below), producing an imprecise, needlessly wide stop instead of
        # a tight one tied to the actual entry premise. Confirmed via test:
        # a scenario with OB low 3 pips away and a swing low 33 pips away
        # was picking the 33-pip stop before this fix.
        sl_base, sl_source = max(invalidation_candidates, key=lambda x: x[0])
        stop_loss = round(sl_base - buffer_price, 5)
        risk_pips = (current_price - stop_loss) / pip_size
        
        tp_candidate = structure.get("last_swing_high")
        take_profit = round(tp_candidate - buffer_price, 5) if tp_candidate is not None else None
        
    else:  # SELL
        ob = order_blocks.get("bearish_ob")
        if ob and order_blocks.get("price_in_bearish_ob"):
            invalidation_candidates.append((ob["high"], "order_block"))
        if sweep.get("type") == "BEARISH_SWEEP" and sweep.get("level") is not None:
            invalidation_candidates.append((sweep["level"], "liquidity_sweep"))
        if structure.get("last_swing_high") is not None:
            invalidation_candidates.append((structure["last_swing_high"], "swing_point"))
        
        if not invalidation_candidates:
            return {"is_perfect_setup": False, "reason": "No SMC structural level available for stop loss", "confluence_count": confluence_count}
        
        # Mirror of the BUY-side fix above: nearest structural level
        # (smallest, closest to entry from above) is the precise
        # invalidation point, not the furthest/widest one.
        sl_base, sl_source = min(invalidation_candidates, key=lambda x: x[0])
        stop_loss = round(sl_base + buffer_price, 5)
        risk_pips = (stop_loss - current_price) / pip_size
        
        tp_candidate = structure.get("last_swing_low")
        take_profit = round(tp_candidate + buffer_price, 5) if tp_candidate is not None else None
    
    if risk_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Computed stop loss is on the wrong side of entry - setup invalid", "confluence_count": confluence_count}
    
    if take_profit is None:
        return {
            "is_perfect_setup": False,
            "reason": "No opposing market-structure swing point available for take profit - cannot give a precise SMC-only target",
            "stop_loss_would_be": stop_loss,
            "confluence_count": confluence_count,
        }
    
    # ✅ FIXED (Phase 2, defect D-04): was
    #     reward_pips = abs(take_profit - current_price) / pip_size
    # abs() is never negative, so the `reward_pips <= 0` guard directly
    # below it was unreachable dead code. A take-profit on the WRONG side
    # of entry -- a BUY whose target sits below the entry price, which is
    # exactly what happens when last_swing_high is stale or price has
    # already run past it -- was turned into a healthy positive distance
    # and reported as a healthy R:R. The other five setup evaluators in
    # this file (evaluate_bb_mean_reversion_setup, evaluate_rsi_reversal_
    # setup, the two fib evaluators, evaluate_wave_setup and the swing
    # evaluator) all use signed, direction-aware arithmetic already; this
    # function was the odd one out, and it is the PRIMARY SMC perfect-
    # setup evaluator.
    #
    # Now delegated to core/risk_reward.py, which enforces the geometry
    # for both directions and fails closed. Regression test:
    # tests/test_risk_reward.py::TestD04_DirectionalGeometry.
    rr = rr_from_prices(direction, current_price, stop_loss, take_profit, pip_size)
    if not rr.valid:
        return {
            "is_perfect_setup": False,
            "reason": f"Invalid trade geometry: {rr.reason}",
            "confluence_count": confluence_count,
            "direction": direction,
        }

    reward_pips = rr.reward_pips
    risk_reward_ratio = round(rr.ratio, 2)
    
    # ---- Risk reconciliation against the margin-safe lot ceiling ----
    pip_value_per_pip = _get_pip_value_per_pip(symbol, margin_safe_lot, current_price, direction, pip_size)
    projected_risk_usd = margin_safe_lot * risk_pips * pip_value_per_pip if pip_value_per_pip else None
    final_lot = margin_safe_lot
    risk_note = "within target risk budget"
    
    if projected_risk_usd and target_risk_usd and projected_risk_usd > target_risk_usd:
        scale = target_risk_usd / projected_risk_usd
        final_lot = max(0.01, round(margin_safe_lot * scale, 2))
        risk_note = (
            f"lot reduced from {margin_safe_lot} to {final_lot} to keep risk at the "
            f"${target_risk_usd:.2f} target — this SMC stop ({risk_pips:.1f} pips) is wider "
            f"than the distance calculate_lot_proper()'s own sizing assumed"
        )
        if pip_value_per_pip:
            projected_risk_usd = final_lot * risk_pips * pip_value_per_pip
    
    return {
        "is_perfect_setup": True,
        "direction": direction,
        "confluence_count": confluence_count,
        "confluence_score": smc_analysis.get("score", 0),
        "reasons": smc_analysis.get("reasons", []),
        "entry_type": "MARKET",
        "entry_price": round(current_price, 5),
        "stop_loss": stop_loss,
        "stop_loss_basis": _describe_sl_basis(direction, order_blocks, sweep, structure, sl_source),
        "take_profit": take_profit,
        "take_profit_basis": "next opposing market-structure swing point",
        "risk_pips": round(risk_pips, 1),
        "reward_pips": round(reward_pips, 1),
        "risk_reward_ratio": f"1:{risk_reward_ratio}",
        "lot_size": final_lot,
        "margin_safe_lot_ceiling": margin_safe_lot,
        "projected_risk_usd": round(projected_risk_usd, 2) if projected_risk_usd else None,
        "target_risk_usd": round(target_risk_usd, 2) if target_risk_usd else None,
        "risk_note": risk_note,
        "buffer_pips_applied": round(buffer_price / pip_size, 1),
        "invalidation_note": (
            "stop_loss sits just beyond the nearest real structural invalidation "
            "point for this setup, plus a small spread-based buffer — not an "
            "arbitrary pip count. take_profit is the nearest opposing swing point "
            "the market has already shown it respects, not a fixed R:R guess. "
            "Not backtested — see earlier discussion on validating against real "
            "trade history before trusting this for live sizing."
        ),
    }


def _check_volume_profile_confluence(direction: str, volume_profile_data: Optional[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
    """
    Shared confluence gate for the mean-reversion-style "perfect entry"
    setups. A BUY reversal is only confirmed if price is trading below
    the value area (VAL) - i.e. away from where recent volume actually
    transacted, not just "oscillator says oversold" while price sits in
    the normal range. Mirror for SELL against VAH.

    Fails open: if volume profile data isn't available, returns
    confluent=True with a note, rather than blocking the setup on
    missing data.
    """
    if not VOLUME_PROFILE_REQUIRE_CONFLUENCE:
        return {"confluent": True, "note": "volume profile confluence check disabled in config"}

    if not volume_profile_data or not volume_profile_data.get("available"):
        return {"confluent": True, "note": "volume profile unavailable — confluence check skipped"}

    vah = volume_profile_data.get("vah")
    val = volume_profile_data.get("val")
    poc = volume_profile_data.get("poc")
    if vah is None or val is None:
        return {"confluent": True, "note": "volume profile incomplete — confluence check skipped"}

    if direction == "BUY":
        if current_price < val:
            return {"confluent": True, "note": f"price below value area low (VAL {val}) — confirms extension away from POC {poc}", "vah": vah, "val": val, "poc": poc}
        return {"confluent": False, "note": f"price ({current_price}) is inside/above the value area (VAL {val}) — no volume-profile confirmation of the extension", "vah": vah, "val": val, "poc": poc}
    else:  # SELL
        if current_price > vah:
            return {"confluent": True, "note": f"price above value area high (VAH {vah}) — confirms extension away from POC {poc}", "vah": vah, "val": val, "poc": poc}
        return {"confluent": False, "note": f"price ({current_price}) is inside/below the value area (VAH {vah}) — no volume-profile confirmation of the extension", "vah": vah, "val": val, "poc": poc}


def evaluate_bb_mean_reversion_setup(
    bollinger_data: Dict[str, Any],
    symbol: str,
    order_type: str,
    current_price: float,
    pip_size: float,
    spread_pips: float,
    margin_safe_lot: float,
    target_risk_usd: float = None,
    volume_profile_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    BOLLINGER BANDS MEAN-REVERSION SETUP: turns a genuine band-extreme
    reading into a concrete MARKET ORDER plan, same contract as
    evaluate_smc_trade_setup() — real entry/SL/TP and a lot size
    reconciled against the real margin-safe ceiling — but only when the
    setup is a real mean-reversion extreme, not just "leaning toward one
    side of the bands".

    Design contract:
    - Entry ONLY when price has actually touched/pierced the band
      (percent_b <= BB_MEAN_REVERSION_MAX_PIERCE_PCT_B for BUY, or the
      mirror for SELL) AND the bands are NOT in a squeeze (a squeeze
      usually precedes a breakout, not a reversion — reverting into a
      squeeze is the classic way this setup gets run over).
    - SL: the far side of the same band being pierced, plus a small
      spread-based buffer — a further breach of the extreme invalidates
      the mean-reversion premise entirely.
    - TP: NOT the exact middle band. Price statistically stalls just
      short of touching the mean, so TP sits BB_MEAN_REVERSION_EXIT_
      APPROACH_PCT of the band's half-width short of the middle, in the
      direction of travel — i.e. "very close to middle", not "at
      middle".
    - Lot size: margin_safe_lot is the starting ceiling (never exceeded),
      then scaled down (never up) if this setup's SL distance would risk
      more than target_risk_usd — identical reconciliation logic to
      evaluate_smc_trade_setup().
    """
    if target_risk_usd is None:
        target_risk_usd = SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE

    upper = bollinger_data.get("upper")
    middle = bollinger_data.get("middle")
    lower = bollinger_data.get("lower")
    is_squeeze = bollinger_data.get("is_squeeze", False)
    percent_b = bollinger_data.get("percent_b")

    if upper is None or middle is None or lower is None or upper <= lower or percent_b is None:
        return {"is_perfect_setup": False, "reason": "Invalid or incomplete Bollinger Band data"}

    if is_squeeze:
        return {"is_perfect_setup": False, "reason": "Bands are in a squeeze — not a valid mean-reversion setup (squeeze precedes breakout, not reversion)"}

    half_width = (upper - middle)  # == (middle - lower) for a standard BB

    if percent_b <= BB_MEAN_REVERSION_MAX_PIERCE_PCT_B:
        direction = "BUY"
    elif percent_b >= (1.0 - BB_MEAN_REVERSION_MAX_PIERCE_PCT_B):
        direction = "SELL"
    else:
        return {
            "is_perfect_setup": False,
            "reason": f"Price has not touched/pierced a band (percent_b={percent_b:.2f}) — no mean-reversion extreme yet",
            "percent_b": round(percent_b, 3),
        }

    if order_type and order_type.upper() not in (direction, "AUTO", "BOTH", ""):
        return {
            "is_perfect_setup": False,
            "reason": f"BB mean-reversion direction ({direction}) conflicts with the system's own measured best direction ({order_type})",
            "percent_b": round(percent_b, 3),
        }

    vp_confluence = _check_volume_profile_confluence(direction, volume_profile_data, current_price)
    if not vp_confluence["confluent"]:
        return {
            "is_perfect_setup": False,
            "reason": f"Band extreme not confirmed by volume profile: {vp_confluence['note']}",
            "percent_b": round(percent_b, 3),
            "direction": direction,
        }

    buffer_price = max(spread_pips * BB_MEAN_REVERSION_SL_BUFFER_SPREAD_MULT, BB_MEAN_REVERSION_SL_MIN_BUFFER_PIPS) * pip_size
    approach_offset = half_width * BB_MEAN_REVERSION_EXIT_APPROACH_PCT

    if direction == "BUY":
        stop_loss = round(lower - buffer_price, 5)
        take_profit = round(middle - approach_offset, 5)
        risk_pips = (current_price - stop_loss) / pip_size
        reward_pips = (take_profit - current_price) / pip_size
    else:  # SELL
        stop_loss = round(upper + buffer_price, 5)
        take_profit = round(middle + approach_offset, 5)
        risk_pips = (stop_loss - current_price) / pip_size
        reward_pips = (current_price - take_profit) / pip_size

    if risk_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Computed stop loss is on the wrong side of entry - setup invalid", "percent_b": round(percent_b, 3)}

    if reward_pips <= 0:
        return {
            "is_perfect_setup": False,
            "reason": "Middle band approach target is not beyond entry — price is already past the exit zone",
            "stop_loss_would_be": stop_loss,
            "percent_b": round(percent_b, 3),
        }

    risk_reward_ratio = round(reward_pips / risk_pips, 2)
    if risk_reward_ratio < BB_MEAN_REVERSION_MIN_RR:
        return {
            "is_perfect_setup": False,
            "reason": f"Risk:reward {risk_reward_ratio} below minimum {BB_MEAN_REVERSION_MIN_RR} for this setup",
            "stop_loss_would_be": stop_loss,
            "take_profit_would_be": take_profit,
            "percent_b": round(percent_b, 3),
        }

    pip_value_per_pip = _get_pip_value_per_pip(symbol, margin_safe_lot, current_price, direction, pip_size)
    projected_risk_usd = margin_safe_lot * risk_pips * pip_value_per_pip if pip_value_per_pip else None
    final_lot = margin_safe_lot
    risk_note = "within target risk budget"

    if projected_risk_usd and target_risk_usd and projected_risk_usd > target_risk_usd:
        scale = target_risk_usd / projected_risk_usd
        final_lot = max(0.01, round(margin_safe_lot * scale, 2))
        risk_note = (
            f"lot reduced from {margin_safe_lot} to {final_lot} to keep risk at the "
            f"${target_risk_usd:.2f} target — this band's SL distance ({risk_pips:.1f} pips) "
            f"is wider than the distance calculate_lot_proper()'s own sizing assumed"
        )
        if pip_value_per_pip:
            projected_risk_usd = final_lot * risk_pips * pip_value_per_pip

    return {
        "is_perfect_setup": True,
        "direction": direction,
        "percent_b": round(percent_b, 3),
        "band_width": round(upper - lower, 5),
        "volume_profile_confluence": vp_confluence,
        "entry_type": "MARKET",
        "entry_price": round(current_price, 5),
        "stop_loss": stop_loss,
        "stop_loss_basis": f"far side of the pierced {'lower' if direction == 'BUY' else 'upper'} band + spread buffer",
        "take_profit": take_profit,
        "take_profit_basis": f"{BB_MEAN_REVERSION_EXIT_APPROACH_PCT*100:.0f}% of band half-width short of the middle band, not the exact mean",
        "risk_pips": round(risk_pips, 1),
        "reward_pips": round(reward_pips, 1),
        "risk_reward_ratio": f"1:{risk_reward_ratio}",
        "lot_size": final_lot,
        "margin_safe_lot_ceiling": margin_safe_lot,
        "projected_risk_usd": round(projected_risk_usd, 2) if projected_risk_usd else None,
        "target_risk_usd": round(target_risk_usd, 2) if target_risk_usd else None,
        "risk_note": risk_note,
        "buffer_pips_applied": round(buffer_price / pip_size, 1),
        "invalidation_note": (
            "stop_loss sits just beyond the far side of the pierced band — a deeper "
            "breach means the extreme wasn't respected and the reversion premise is "
            "dead. take_profit is deliberately short of the exact middle band, since "
            "price statistically stalls before touching the mean. Not backtested — "
            "see earlier discussion on validating against real trade history before "
            "trusting this for live sizing."
        ),
    }


def _fib_reversal_target(
    direction: str,
    recent_swing_high: Optional[float],
    recent_swing_low: Optional[float],
    fib_ratio: float,
) -> Optional[float]:
    """
    Shared helper for the RSI/Stochastic reversal setups: projects a TP as
    a Fibonacci retracement of the swing leg (recent_swing_low <->
    recent_swing_high) the divergence formed against. Not the exact same
    thing as an SMC swing-point target - this is a fraction OF the leg,
    not the leg's endpoint itself.
    """
    if recent_swing_high is None or recent_swing_low is None or recent_swing_high <= recent_swing_low:
        return None
    leg = recent_swing_high - recent_swing_low
    if direction == "BUY":
        return recent_swing_low + fib_ratio * leg
    else:
        return recent_swing_high - fib_ratio * leg


def evaluate_rsi_reversal_setup(
    rsi_indicator: Dict[str, Any],
    rsi_value: float,
    symbol: str,
    order_type: str,
    current_price: float,
    pip_size: float,
    spread_pips: float,
    margin_safe_lot: float,
    recent_swing_high: Optional[float],
    recent_swing_low: Optional[float],
    target_risk_usd: float = None,
    volume_profile_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    RSI REVERSAL SETUP: fires only when raw RSI and its divergence
    DISAGREE on direction and the divergence wins - e.g. RSI is oversold
    (says BUY on its own) but a REGULAR_BEARISH divergence says SELL.
    That disagreement, at an extreme, is score_rsi_indicator_with_
    divergence()'s highest-confidence read (confidence=95) - this
    function does not re-derive that logic, it just gates on the
    confidence that logic already produced, so there's exactly one
    definition of "RSI says X but divergence reverses it to Y".

    Exit rule is RSI-specific, not generic: since RSI has no price of its
    own, TP is a Fibonacci retracement of the swing leg the divergence
    formed against, sized by how extreme RSI was (deeper extreme -> the
    0.618 target instead of 0.5). SL sits beyond the swing extreme that
    produced the reading plus a spread buffer.
    """
    if target_risk_usd is None:
        target_risk_usd = SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE

    if not rsi_indicator or rsi_indicator.get("confidence", 0) < RSI_REVERSAL_SETUP_MIN_CONFIDENCE:
        return {
            "is_perfect_setup": False,
            "reason": f"RSI/divergence confidence {rsi_indicator.get('confidence', 0) if rsi_indicator else 0} below reversal threshold ({RSI_REVERSAL_SETUP_MIN_CONFIDENCE}) — this isn't the raw-vs-divergence disagreement case",
        }

    direction = rsi_indicator.get("recommendation")
    if direction not in ("BUY", "SELL"):
        return {"is_perfect_setup": False, "reason": "RSI/divergence merge did not resolve to a clear direction"}

    if order_type and order_type.upper() not in (direction, "AUTO", "BOTH", ""):
        return {"is_perfect_setup": False, "reason": f"RSI reversal direction ({direction}) conflicts with the system's own measured best direction ({order_type})"}

    vp_confluence = _check_volume_profile_confluence(direction, volume_profile_data, current_price)
    if not vp_confluence["confluent"]:
        return {
            "is_perfect_setup": False,
            "reason": f"RSI reversal not confirmed by volume profile: {vp_confluence['note']}",
            "direction": direction,
        }

    if direction == "BUY":
        fib_ratio = RSI_REVERSAL_FIB_DEEP if rsi_value < RSI_EXTREME_OVERSOLD else RSI_REVERSAL_FIB_NORMAL
    else:
        fib_ratio = RSI_REVERSAL_FIB_DEEP if rsi_value > RSI_EXTREME_OVERBOUGHT else RSI_REVERSAL_FIB_NORMAL

    if recent_swing_high is None or recent_swing_low is None or recent_swing_high <= recent_swing_low:
        return {"is_perfect_setup": False, "reason": "No valid swing leg available to size the RSI reversal exit against", "direction": direction}

    buffer_price = max(spread_pips * RSI_REVERSAL_SL_BUFFER_SPREAD_MULT, RSI_REVERSAL_SL_MIN_BUFFER_PIPS) * pip_size
    take_profit = round(_fib_reversal_target(direction, recent_swing_high, recent_swing_low, fib_ratio), 5)

    if direction == "BUY":
        stop_loss = round(recent_swing_low - buffer_price, 5)
        risk_pips = (current_price - stop_loss) / pip_size
        reward_pips = (take_profit - current_price) / pip_size
    else:
        stop_loss = round(recent_swing_high + buffer_price, 5)
        risk_pips = (stop_loss - current_price) / pip_size
        reward_pips = (current_price - take_profit) / pip_size

    if risk_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Computed stop loss is on the wrong side of entry - setup invalid", "direction": direction}
    if reward_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Fibonacci retracement target is not beyond entry - swing leg too tight or already retraced", "direction": direction}

    risk_reward_ratio = round(reward_pips / risk_pips, 2)
    if risk_reward_ratio < RSI_REVERSAL_MIN_RR:
        return {
            "is_perfect_setup": False,
            "reason": f"Risk:reward {risk_reward_ratio} below minimum {RSI_REVERSAL_MIN_RR} for this setup",
            "direction": direction,
        }

    pip_value_per_pip = _get_pip_value_per_pip(symbol, margin_safe_lot, current_price, direction, pip_size)
    projected_risk_usd = margin_safe_lot * risk_pips * pip_value_per_pip if pip_value_per_pip else None
    final_lot = margin_safe_lot
    risk_note = "within target risk budget"

    if projected_risk_usd and target_risk_usd and projected_risk_usd > target_risk_usd:
        scale = target_risk_usd / projected_risk_usd
        final_lot = max(0.01, round(margin_safe_lot * scale, 2))
        risk_note = f"lot reduced from {margin_safe_lot} to {final_lot} to keep risk at the ${target_risk_usd:.2f} target"
        if pip_value_per_pip:
            projected_risk_usd = final_lot * risk_pips * pip_value_per_pip

    return {
        "is_perfect_setup": True,
        "direction": direction,
        "rsi_value": round(rsi_value, 1),
        "divergence_confidence": rsi_indicator.get("confidence"),
        "reasons": [rsi_indicator.get("reason", "")],
        "volume_profile_confluence": vp_confluence,
        "entry_type": "MARKET",
        "entry_price": round(current_price, 5),
        "stop_loss": stop_loss,
        "stop_loss_basis": "swing extreme that produced the RSI reading + spread buffer",
        "take_profit": take_profit,
        "take_profit_basis": f"{fib_ratio*100:.1f}% Fibonacci retracement of the divergence swing leg (RSI extremity-scaled)",
        "risk_pips": round(risk_pips, 1),
        "reward_pips": round(reward_pips, 1),
        "risk_reward_ratio": f"1:{risk_reward_ratio}",
        "lot_size": final_lot,
        "margin_safe_lot_ceiling": margin_safe_lot,
        "projected_risk_usd": round(projected_risk_usd, 2) if projected_risk_usd else None,
        "target_risk_usd": round(target_risk_usd, 2) if target_risk_usd else None,
        "risk_note": risk_note,
        "buffer_pips_applied": round(buffer_price / pip_size, 1),
        "invalidation_note": (
            "This fires only when raw RSI level and its divergence disagree and the "
            "divergence wins the direction — RSI 'boom' entries. TP is a Fibonacci "
            "retracement of the swing leg, not a literal RSI-value target (RSI has "
            "no price of its own). Not backtested."
        ),
    }


def evaluate_stochastic_reversal_setup(
    stoch_indicator: Dict[str, Any],
    k_value: float,
    symbol: str,
    order_type: str,
    current_price: float,
    pip_size: float,
    spread_pips: float,
    margin_safe_lot: float,
    recent_swing_high: Optional[float],
    recent_swing_low: Optional[float],
    target_risk_usd: float = None,
    volume_profile_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    STOCHASTIC REVERSAL SETUP: mirror of evaluate_rsi_reversal_setup(),
    for Stochastic %K + its own divergence merge
    (score_stochastic_indicator_with_divergence). Same contract: fires
    only on the raw-vs-divergence disagreement at an extreme, exit is a
    Fibonacci retracement of the swing leg scaled by how extreme %K was.
    """
    if target_risk_usd is None:
        target_risk_usd = SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE

    if not stoch_indicator or stoch_indicator.get("confidence", 0) < STOCH_REVERSAL_SETUP_MIN_CONFIDENCE:
        return {
            "is_perfect_setup": False,
            "reason": f"Stochastic/divergence confidence {stoch_indicator.get('confidence', 0) if stoch_indicator else 0} below reversal threshold ({STOCH_REVERSAL_SETUP_MIN_CONFIDENCE}) — this isn't the raw-vs-divergence disagreement case",
        }

    direction = stoch_indicator.get("recommendation")
    if direction not in ("BUY", "SELL"):
        return {"is_perfect_setup": False, "reason": "Stochastic/divergence merge did not resolve to a clear direction"}

    if order_type and order_type.upper() not in (direction, "AUTO", "BOTH", ""):
        return {"is_perfect_setup": False, "reason": f"Stochastic reversal direction ({direction}) conflicts with the system's own measured best direction ({order_type})"}

    vp_confluence = _check_volume_profile_confluence(direction, volume_profile_data, current_price)
    if not vp_confluence["confluent"]:
        return {
            "is_perfect_setup": False,
            "reason": f"Stochastic reversal not confirmed by volume profile: {vp_confluence['note']}",
            "direction": direction,
        }

    if direction == "BUY":
        fib_ratio = STOCH_REVERSAL_FIB_DEEP if k_value < STOCH_EXTREME_OVERSOLD else STOCH_REVERSAL_FIB_NORMAL
    else:
        fib_ratio = STOCH_REVERSAL_FIB_DEEP if k_value > STOCH_EXTREME_OVERBOUGHT else STOCH_REVERSAL_FIB_NORMAL

    if recent_swing_high is None or recent_swing_low is None or recent_swing_high <= recent_swing_low:
        return {"is_perfect_setup": False, "reason": "No valid swing leg available to size the Stochastic reversal exit against", "direction": direction}

    buffer_price = max(spread_pips * STOCH_REVERSAL_SL_BUFFER_SPREAD_MULT, STOCH_REVERSAL_SL_MIN_BUFFER_PIPS) * pip_size
    take_profit = round(_fib_reversal_target(direction, recent_swing_high, recent_swing_low, fib_ratio), 5)

    if direction == "BUY":
        stop_loss = round(recent_swing_low - buffer_price, 5)
        risk_pips = (current_price - stop_loss) / pip_size
        reward_pips = (take_profit - current_price) / pip_size
    else:
        stop_loss = round(recent_swing_high + buffer_price, 5)
        risk_pips = (stop_loss - current_price) / pip_size
        reward_pips = (current_price - take_profit) / pip_size

    if risk_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Computed stop loss is on the wrong side of entry - setup invalid", "direction": direction}
    if reward_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Fibonacci retracement target is not beyond entry - swing leg too tight or already retraced", "direction": direction}

    risk_reward_ratio = round(reward_pips / risk_pips, 2)
    if risk_reward_ratio < STOCH_REVERSAL_MIN_RR:
        return {
            "is_perfect_setup": False,
            "reason": f"Risk:reward {risk_reward_ratio} below minimum {STOCH_REVERSAL_MIN_RR} for this setup",
            "direction": direction,
        }

    pip_value_per_pip = _get_pip_value_per_pip(symbol, margin_safe_lot, current_price, direction, pip_size)
    projected_risk_usd = margin_safe_lot * risk_pips * pip_value_per_pip if pip_value_per_pip else None
    final_lot = margin_safe_lot
    risk_note = "within target risk budget"

    if projected_risk_usd and target_risk_usd and projected_risk_usd > target_risk_usd:
        scale = target_risk_usd / projected_risk_usd
        final_lot = max(0.01, round(margin_safe_lot * scale, 2))
        risk_note = f"lot reduced from {margin_safe_lot} to {final_lot} to keep risk at the ${target_risk_usd:.2f} target"
        if pip_value_per_pip:
            projected_risk_usd = final_lot * risk_pips * pip_value_per_pip

    return {
        "is_perfect_setup": True,
        "direction": direction,
        "k_value": round(k_value, 1),
        "divergence_confidence": stoch_indicator.get("confidence"),
        "reasons": [stoch_indicator.get("reason", "")],
        "volume_profile_confluence": vp_confluence,
        "entry_type": "MARKET",
        "entry_price": round(current_price, 5),
        "stop_loss": stop_loss,
        "stop_loss_basis": "swing extreme that produced the Stochastic reading + spread buffer",
        "take_profit": take_profit,
        "take_profit_basis": f"{fib_ratio*100:.1f}% Fibonacci retracement of the divergence swing leg (%K extremity-scaled)",
        "risk_pips": round(risk_pips, 1),
        "reward_pips": round(reward_pips, 1),
        "risk_reward_ratio": f"1:{risk_reward_ratio}",
        "lot_size": final_lot,
        "margin_safe_lot_ceiling": margin_safe_lot,
        "projected_risk_usd": round(projected_risk_usd, 2) if projected_risk_usd else None,
        "target_risk_usd": round(target_risk_usd, 2) if target_risk_usd else None,
        "risk_note": risk_note,
        "buffer_pips_applied": round(buffer_price / pip_size, 1),
        "invalidation_note": (
            "This fires only when raw Stochastic %K level and its divergence disagree "
            "and the divergence wins the direction. TP is a Fibonacci retracement of "
            "the swing leg, not a literal %K-value target. Not backtested."
        ),
    }


def evaluate_ema_crossover_setup(
    close_prices: List[float],
    symbol: str,
    order_type: str,
    current_price: float,
    pip_size: float,
    spread_pips: float,
    atr_pips: float,
    margin_safe_lot: float,
    fast_period: int = EMA_FAST,
    slow_period: int = EMA_MEDIUM,
    target_risk_usd: float = None,
    volume_profile_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    EMA CROSSOVER SETUP: fires only on a FRESH crossover (the fast EMA
    crossed the slow EMA on the most recently closed bar, not "fast is
    currently above slow" which could be many bars stale).

    Design contract — deliberately different shape from the other
    setups:
    - Entry: fast EMA crosses the slow EMA this bar. Direction = BUY if
      fast crossed above, SELL if fast crossed below.
    - SL: beyond the slow EMA (the level whose reclaim invalidates the
      cross) plus a spread buffer. Rejected if that distance is already
      more than EMA_CROSSOVER_MAX_SL_ATR_MULT x ATR — a stale/extended
      cross, not a fresh tight-risk entry.
    - Exit is a SIGNAL, not a price: close when the fast EMA crosses back
      through the slow EMA in the opposite direction. There is deliberately
      NO take_profit price here (unlike the other setups) — trend-following
      exits are open-ended by design. This setup does NOT produce a
      complete "set it and forget it" broker order the way the others do;
      whatever runs this needs to keep re-checking the crossover condition
      on each new bar and close the position when it flips. Treat
      "take_profit": None as "not applicable", not as a missing value.
    """
    if target_risk_usd is None:
        target_risk_usd = SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE

    if len(close_prices) < slow_period + 2:
        return {"is_perfect_setup": False, "reason": "Not enough bars to evaluate EMA crossover freshness"}

    ema_fast_now = _calculate_ema(close_prices, fast_period)
    ema_slow_now = _calculate_ema(close_prices, slow_period)
    ema_fast_prev = _calculate_ema(close_prices[:-1], fast_period)
    ema_slow_prev = _calculate_ema(close_prices[:-1], slow_period)

    crossed_up = ema_fast_prev <= ema_slow_prev and ema_fast_now > ema_slow_now
    crossed_down = ema_fast_prev >= ema_slow_prev and ema_fast_now < ema_slow_now

    if crossed_up:
        direction = "BUY"
    elif crossed_down:
        direction = "SELL"
    else:
        return {
            "is_perfect_setup": False,
            "reason": "No fresh EMA crossover on the most recent bar",
            "ema_fast": round(ema_fast_now, 5),
            "ema_slow": round(ema_slow_now, 5),
        }

    if order_type and order_type.upper() not in (direction, "AUTO", "BOTH", ""):
        return {"is_perfect_setup": False, "reason": f"EMA crossover direction ({direction}) conflicts with the system's own measured best direction ({order_type})"}

    min_separation_price = get_ema_min_separation_pips(symbol) * pip_size
    if abs(ema_fast_now - ema_slow_now) < min_separation_price:
        return {
            "is_perfect_setup": False,
            "reason": f"Post-cross separation too thin ({abs(ema_fast_now - ema_slow_now) / pip_size:.1f} pips) — whipsaw risk, not a confirmed cross",
            "direction": direction,
        }

    buffer_price = max(spread_pips * EMA_CROSSOVER_SL_BUFFER_SPREAD_MULT, EMA_CROSSOVER_SL_MIN_BUFFER_PIPS) * pip_size

    if direction == "BUY":
        stop_loss = round(ema_slow_now - buffer_price, 5)
        risk_pips = (current_price - stop_loss) / pip_size
    else:
        stop_loss = round(ema_slow_now + buffer_price, 5)
        risk_pips = (stop_loss - current_price) / pip_size

    if risk_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Computed stop loss is on the wrong side of entry - setup invalid", "direction": direction}

    if atr_pips and atr_pips > 0 and risk_pips > EMA_CROSSOVER_MAX_SL_ATR_MULT * atr_pips:
        return {
            "is_perfect_setup": False,
            "reason": f"SL distance ({risk_pips:.1f} pips) exceeds {EMA_CROSSOVER_MAX_SL_ATR_MULT}x ATR ({atr_pips:.1f} pips) — cross is already extended, not fresh/tight",
            "direction": direction,
            "stop_loss_would_be": stop_loss,
        }

    pip_value_per_pip = _get_pip_value_per_pip(symbol, margin_safe_lot, current_price, direction, pip_size)
    projected_risk_usd = margin_safe_lot * risk_pips * pip_value_per_pip if pip_value_per_pip else None
    final_lot = margin_safe_lot
    risk_note = "within target risk budget"

    if projected_risk_usd and target_risk_usd and projected_risk_usd > target_risk_usd:
        scale = target_risk_usd / projected_risk_usd
        final_lot = max(0.01, round(margin_safe_lot * scale, 2))
        risk_note = f"lot reduced from {margin_safe_lot} to {final_lot} to keep risk at the ${target_risk_usd:.2f} target"
        if pip_value_per_pip:
            projected_risk_usd = final_lot * risk_pips * pip_value_per_pip

    return {
        "is_perfect_setup": True,
        "direction": direction,
        "ema_fast": round(ema_fast_now, 5),
        "ema_slow": round(ema_slow_now, 5),
        "fast_period": fast_period,
        "slow_period": slow_period,
        "entry_type": "MARKET",
        "entry_price": round(current_price, 5),
        "stop_loss": stop_loss,
        "stop_loss_basis": f"slow EMA ({slow_period}) + spread buffer",
        "take_profit": None,
        "take_profit_basis": None,
        "exit_type": "SIGNAL_EXIT",
        "exit_condition": f"close when EMA{fast_period} crosses back {'below' if direction == 'BUY' else 'above'} EMA{slow_period}",
        "volume_profile_confluence": _check_volume_profile_breakout_confluence(direction, volume_profile_data, current_price),
        "requires_ongoing_monitoring": True,
        "risk_pips": round(risk_pips, 1),
        "lot_size": final_lot,
        "margin_safe_lot_ceiling": margin_safe_lot,
        "projected_risk_usd": round(projected_risk_usd, 2) if projected_risk_usd else None,
        "target_risk_usd": round(target_risk_usd, 2) if target_risk_usd else None,
        "risk_note": risk_note,
        "buffer_pips_applied": round(buffer_price / pip_size, 1),
        "invalidation_note": (
            "This setup has no fixed take_profit by design — the exit is the opposite "
            "EMA crossover, which can happen on any future bar. Unlike the other "
            "setups here, this one is not a fire-and-forget SL/TP order: whatever "
            "places this trade must keep re-evaluating the crossover condition and "
            "close manually when it flips. SL is fixed and does protect capital "
            "immediately. Not backtested."
        ),
    }


def score_volume_profile_indicator(vp_data: Dict[str, Any], current_price: float, pip_size: float) -> Dict[str, Any]:
    """
    VOLUME PROFILE / POC scoring: single merged result (recommendation +
    score + confidence + reason), same shape as every other indicator's
    result here.

    Own rule, not borrowed from any other indicator: price beyond the
    Value Area (VAH/VAL) is "trading away from where the market has
    actually transacted volume" - the further beyond, the more extended
    relative to accepted fair value, scaled as a fraction of the
    profile's own range. Inside the value area is fair value - a mild,
    low-confidence pull toward the POC, not a directional call.
    """
    if not vp_data or not vp_data.get("available"):
        reason = vp_data.get("reason", "Volume profile unavailable") if vp_data else "Volume profile unavailable"
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": reason}

    poc = vp_data["poc"]
    vah = vp_data["vah"]
    val = vp_data["val"]
    range_size = vp_data["range_high"] - vp_data["range_low"]

    if range_size <= 0:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": "Degenerate volume profile range"}

    poc_distance_pips = abs(current_price - poc) / pip_size if pip_size else 0
    # ✅ ADDED: distance past the VALUE AREA EDGE, which is what the two
    # "extended beyond fair value" branches below are actually measuring.
    # They previously printed poc_distance_pips into a sentence that named
    # VAH/VAL, so the number and the label described different things.
    # Live XAGUSD: price 68.262 with VAL 68.27642 is 14.4 pips below the
    # value area, but the reason read "113.0 pips below value area low" --
    # that 113.0 is the distance to POC (68.37504). An 8x overstatement,
    # and it propagates verbatim into decision_snapshot's bull/bear case
    # and the human-readable `explained` block.
    #
    # score/confidence were never affected -- they use extension_pct,
    # which is correctly measured from the edge. This is the reason string
    # only.
    vah_distance_pips = (current_price - vah) / pip_size if pip_size else 0
    val_distance_pips = (val - current_price) / pip_size if pip_size else 0

    if current_price > vah:
        extension_pct = min(1.0, (current_price - vah) / range_size)
        score = VOLUME_PROFILE_MIN_SCORE_AT_EDGE + extension_pct * (VOLUME_PROFILE_MAX_SCORE - VOLUME_PROFILE_MIN_SCORE_AT_EDGE)
        confidence = VOLUME_PROFILE_MIN_CONFIDENCE_AT_EDGE + extension_pct * (VOLUME_PROFILE_MAX_CONFIDENCE - VOLUME_PROFILE_MIN_CONFIDENCE_AT_EDGE)
        return {
            "recommendation": "SELL",
            "score": round(-score, 1),
            "confidence": round(confidence, 1),
            "reason": (
                f"Price {vah_distance_pips:.1f} pips above value area high (VAH {vah}) — "
                f"{extension_pct:.0%} of profile range beyond accepted fair value, "
                f"POC {poc_distance_pips:.1f} pips away at {poc}"
            ),
        }
    elif current_price < val:
        extension_pct = min(1.0, (val - current_price) / range_size)
        score = VOLUME_PROFILE_MIN_SCORE_AT_EDGE + extension_pct * (VOLUME_PROFILE_MAX_SCORE - VOLUME_PROFILE_MIN_SCORE_AT_EDGE)
        confidence = VOLUME_PROFILE_MIN_CONFIDENCE_AT_EDGE + extension_pct * (VOLUME_PROFILE_MAX_CONFIDENCE - VOLUME_PROFILE_MIN_CONFIDENCE_AT_EDGE)
        return {
            "recommendation": "BUY",
            "score": round(score, 1),
            "confidence": round(confidence, 1),
            "reason": (
                f"Price {val_distance_pips:.1f} pips below value area low (VAL {val}) — "
                f"{extension_pct:.0%} of profile range beyond accepted fair value, "
                f"POC {poc_distance_pips:.1f} pips away at {poc}"
            ),
        }
    elif current_price > poc:
        return {
            "recommendation": "NEUTRAL",
            "score": -VOLUME_PROFILE_INSIDE_VA_SCORE,
            "confidence": VOLUME_PROFILE_INSIDE_VA_CONFIDENCE,
            "reason": f"Inside value area, {poc_distance_pips:.1f} pips above POC ({poc}) — fair value, mild pull toward POC",
        }
    elif current_price < poc:
        return {
            "recommendation": "NEUTRAL",
            "score": VOLUME_PROFILE_INSIDE_VA_SCORE,
            "confidence": VOLUME_PROFILE_INSIDE_VA_CONFIDENCE,
            "reason": f"Inside value area, {poc_distance_pips:.1f} pips below POC ({poc}) — fair value, mild pull toward POC",
        }
    else:
        return {
            "recommendation": "NEUTRAL",
            "score": 0,
            "confidence": VOLUME_PROFILE_INSIDE_VA_CONFIDENCE - 5,
            "reason": f"At POC ({poc}) — price trading exactly at the most-transacted level",
        }


def score_wave_c_fibonacci_indicator(wave_c_data: Dict[str, Any], current_price: float, pip_size: float) -> Dict[str, Any]:
    """
    WAVE C / A-B-C CORRECTION scoring: single merged result. Measures how
    far price has traveled through the developing wave C (as a multiple
    of wave A's length) and only turns directional once that puts price
    inside the Fibonacci target zone (short of 100% through 161.8%) -
    where an A-B-C correction is statistically expected to complete and
    reverse back toward the original trend. Confidence is higher when
    wave B's retracement was in the textbook 50-61.8% zone.
    """
    if not wave_c_data or not wave_c_data.get("available"):
        reason = wave_c_data.get("reason", "No valid A-B-C structure detected") if wave_c_data else "No valid A-B-C structure detected"
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": reason}

    point2_price = wave_c_data["point2"]["price"]
    wave_a_length = wave_c_data["wave_a_length"]
    correction_direction = wave_c_data["correction_direction"]
    reversal_direction = wave_c_data["reversal_direction"]
    is_ideal_b = wave_c_data["is_ideal_b_retracement"]

    if wave_a_length <= 0:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": "Degenerate wave A length"}

    c_sign = -1 if correction_direction == "DOWN" else 1
    c_progress = (current_price - point2_price) * c_sign / wave_a_length

    if c_progress < 0:
        return {
            "recommendation": "NEUTRAL", "score": 0, "confidence": 15,
            "reason": f"Wave C has not started developing yet — price is still near the wave B pivot ({point2_price})",
        }

    entry_zone_start = 1.0 - WAVE_C_ENTRY_ZONE_PCT

    if c_progress < entry_zone_start:
        return {
            "recommendation": "NEUTRAL", "score": 0, "confidence": 25,
            "reason": f"Wave C in progress ({c_progress:.0%} of wave A's length) — not yet near the Fibonacci target zone",
        }

    if c_progress > WAVE_C_FIB_EXTENSION * WAVE_C_OVEREXTENSION_TOLERANCE:
        return {
            "recommendation": "NEUTRAL", "score": 0, "confidence": 20,
            "reason": f"Price has moved well beyond the 161.8% wave C extension ({c_progress:.0%} of wave A) — A-B-C interpretation is likely invalidated",
        }

    zone_span = WAVE_C_FIB_EXTENSION - entry_zone_start
    depth_in_zone = min(1.0, max(0.0, (c_progress - entry_zone_start) / zone_span)) if zone_span > 0 else 0.5

    confidence = 55 + depth_in_zone * 25
    score = 12 + depth_in_zone * 13
    if is_ideal_b:
        confidence += 10
        score += 5
    confidence = round(min(90, confidence), 1)
    score = round(min(30, score), 1)

    return {
        "recommendation": reversal_direction,
        "score": score if reversal_direction == "BUY" else -score,
        "confidence": confidence,
        "reason": (
            f"Wave C {c_progress:.0%} through its Fibonacci projection "
            f"({'ideal' if is_ideal_b else 'acceptable'} {wave_c_data['wave_b_retracement_pct']:.0%} B retracement) "
            f"— {correction_direction} correction approaching completion, expecting reversal toward {reversal_direction}"
        ),
    }


def evaluate_wave_c_reversal_setup(
    wave_c_data: Dict[str, Any],
    wave_c_indicator: Dict[str, Any],
    symbol: str,
    order_type: str,
    current_price: float,
    pip_size: float,
    spread_pips: float,
    margin_safe_lot: float,
    target_risk_usd: float = None,
    volume_profile_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    WAVE C REVERSAL SETUP: fires only when price is inside the Fibonacci
    target zone of a valid A-B-C correction with an ideal (50-61.8%)
    wave B retracement — the cleanest read score_wave_c_fibonacci_
    indicator() can produce.

    - Direction: the expected reversal back toward the pre-correction
      trend (reversal_direction from the A-B-C detection).
    - SL: beyond the 161.8% extension target, plus a spread buffer — a
      breach that far past the equality target means this isn't a
      normal A-B-C correction, and the setup is void.
    - TP: back to point1 (the wave B pivot — the origin of wave C, and a
      standard technical target for an A-B-C reversal trade).
    - Same shared $200/5% risk budget and lot-scaling-down logic as the
      other setups here. Also requires the same volume-profile
      confluence gate as the mean-reversion setups (price should be
      outside the value area, confirming the wave C extreme).
    """
    if target_risk_usd is None:
        target_risk_usd = SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE

    if not wave_c_data or not wave_c_data.get("available"):
        return {"is_perfect_setup": False, "reason": wave_c_data.get("reason", "No valid A-B-C structure") if wave_c_data else "No valid A-B-C structure"}

    if not wave_c_indicator or wave_c_indicator.get("recommendation") not in ("BUY", "SELL") or not wave_c_data.get("is_ideal_b_retracement"):
        return {
            "is_perfect_setup": False,
            "reason": "Wave C not in its ideal target zone with an ideal wave B retracement — not a clean enough read for a market order",
        }

    direction = wave_c_indicator["recommendation"]

    if order_type and order_type.upper() not in (direction, "AUTO", "BOTH", ""):
        return {"is_perfect_setup": False, "reason": f"Wave C reversal direction ({direction}) conflicts with the system's own measured best direction ({order_type})"}

    vp_confluence = _check_volume_profile_confluence(direction, volume_profile_data, current_price)
    if not vp_confluence["confluent"]:
        return {
            "is_perfect_setup": False,
            "reason": f"Wave C reversal not confirmed by volume profile: {vp_confluence['note']}",
            "direction": direction,
        }

    point1_price = wave_c_data["point1"]["price"]
    target_c_161 = wave_c_data["target_c_161"]
    buffer_price = max(spread_pips * WAVE_C_SETUP_SL_BUFFER_SPREAD_MULT, WAVE_C_SETUP_SL_MIN_BUFFER_PIPS) * pip_size

    if direction == "BUY":
        stop_loss = round(target_c_161 - buffer_price, 5)
        take_profit = round(point1_price, 5)
        risk_pips = (current_price - stop_loss) / pip_size
        reward_pips = (take_profit - current_price) / pip_size
    else:
        stop_loss = round(target_c_161 + buffer_price, 5)
        take_profit = round(point1_price, 5)
        risk_pips = (stop_loss - current_price) / pip_size
        reward_pips = (current_price - take_profit) / pip_size

    if risk_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Computed stop loss is on the wrong side of entry - setup invalid", "direction": direction}
    if reward_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Wave B pivot target is not beyond entry — too little room left for this trade", "direction": direction}

    risk_reward_ratio = round(reward_pips / risk_pips, 2)
    if risk_reward_ratio < WAVE_C_SETUP_MIN_RR:
        return {
            "is_perfect_setup": False,
            "reason": f"Risk:reward {risk_reward_ratio} below minimum {WAVE_C_SETUP_MIN_RR} for this setup",
            "direction": direction,
        }

    pip_value_per_pip = _get_pip_value_per_pip(symbol, margin_safe_lot, current_price, direction, pip_size)
    projected_risk_usd = margin_safe_lot * risk_pips * pip_value_per_pip if pip_value_per_pip else None
    final_lot = margin_safe_lot
    risk_note = "within target risk budget"

    if projected_risk_usd and target_risk_usd and projected_risk_usd > target_risk_usd:
        scale = target_risk_usd / projected_risk_usd
        final_lot = max(0.01, round(margin_safe_lot * scale, 2))
        risk_note = f"lot reduced from {margin_safe_lot} to {final_lot} to keep risk at the ${target_risk_usd:.2f} target"
        if pip_value_per_pip:
            projected_risk_usd = final_lot * risk_pips * pip_value_per_pip

    return {
        "is_perfect_setup": True,
        "direction": direction,
        "correction_direction": wave_c_data["correction_direction"],
        "wave_b_retracement_pct": wave_c_data["wave_b_retracement_pct"],
        "volume_profile_confluence": vp_confluence,
        "entry_type": "MARKET",
        "entry_price": round(current_price, 5),
        "stop_loss": stop_loss,
        "stop_loss_basis": "161.8% wave C extension target + spread buffer",
        "take_profit": take_profit,
        "take_profit_basis": "wave B pivot (origin of wave C) — standard A-B-C reversal target",
        "risk_pips": round(risk_pips, 1),
        "reward_pips": round(reward_pips, 1),
        "risk_reward_ratio": f"1:{risk_reward_ratio}",
        "lot_size": final_lot,
        "margin_safe_lot_ceiling": margin_safe_lot,
        "projected_risk_usd": round(projected_risk_usd, 2) if projected_risk_usd else None,
        "target_risk_usd": round(target_risk_usd, 2) if target_risk_usd else None,
        "risk_note": risk_note,
        "buffer_pips_applied": round(buffer_price / pip_size, 1),
        "invalidation_note": (
            "This is a standalone A-B-C detector built on top of shared swing points, "
            "not an extension of the separate Elliott Wave engine (patterns.py) — the "
            "two may occasionally disagree on wave counts. Not backtested."
        ),
    }


def _fvg_tier_score(gap: Dict[str, Any], pip_size: float, volume_ratio: float,
                    atr_pips: float = None) -> float:
    """
    Shared quality score for a single gap/IFVG - same width/freshness/
    volume weighted formula as get_ict_recommendation()'s existing FVG
    tier score (reuses MIN_FVG_WIDTH_PIPS / FVG_AGE_GRACE_BARS /
    FVG_AGE_DECAY_BARS / FVG_TIER_MAX_WIDTH_PIPS / FVG_TIER_MIN_VOLUME_
    RATIO / FVG_TIER_MAX_VOLUME_RATIO / the three *_SCORE_WEIGHT
    constants already defined in this module), just applied per-gap
    across the full active-gap list instead of only the single nearest
    one _detect_fvg() returns.
    """
    width_pips = gap["width"] / pip_size if pip_size else 0
    if width_pips < MIN_FVG_WIDTH_PIPS:
        return 0.0

    age_bars = gap["age_bars"]
    if age_bars <= FVG_AGE_GRACE_BARS:
        freshness = 1.0
    else:
        freshness = max(0.0, 1.0 - (age_bars - FVG_AGE_GRACE_BARS) / FVG_AGE_DECAY_BARS)

    _tier_max_w = atr_relative_pips(FVG_TIER_MAX_WIDTH_PIPS, atr_pips, FVG_TIER_MAX_WIDTH_ATR_FRACTION)
    width_score = min(100.0, (width_pips / _tier_max_w) * 100.0)
    freshness_score = freshness * 100.0
    vol_range = FVG_TIER_MAX_VOLUME_RATIO - FVG_TIER_MIN_VOLUME_RATIO
    if vol_range > 0:
        volume_score = min(100.0, max(0.0, (volume_ratio - FVG_TIER_MIN_VOLUME_RATIO) / vol_range * 100.0))
    else:
        volume_score = 50.0

    total_weight = FVG_WIDTH_SCORE_WEIGHT + FVG_FRESHNESS_SCORE_WEIGHT + FVG_VOLUME_SCORE_WEIGHT
    if total_weight <= 0:
        return 0.0
    return (
        width_score * FVG_WIDTH_SCORE_WEIGHT
        + freshness_score * FVG_FRESHNESS_SCORE_WEIGHT
        + volume_score * FVG_VOLUME_SCORE_WEIGHT
    ) / total_weight


FVG_IFVG_REACH_ATR = 0.25   # a gap votes only while price is inside it or within this of it


def score_fvg_ifvg_indicator(
    fvg_list: List[Dict[str, Any]], current_price: float, pip_size: float, volume_ratio: float,
    atr_pips: float = None
) -> Dict[str, Any]:
    """
    FVG / IFVG scoring: single merged result across ALL active gaps
    (fresh FVGs and inverted IFVGs together), not just one. Prioritizes
    whichever active gap is currently being retested (price inside the
    zone) over merely the nearest one — that's the actionable moment.
    Direction comes from the gap's polarity (an IFVG's polarity is
    already flipped from its original type by detect_all_fvgs()).
    """
    if not fvg_list:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": "No active FVG or IFVG zones nearby"}

    scored = []
    for gap in fvg_list:
        tier_score = _fvg_tier_score(gap, pip_size, volume_ratio, atr_pips)
        if tier_score < FVG_IFVG_MIN_TIER_SCORE:
            continue
        is_inside = gap["low"] <= current_price <= gap["high"]
        distance_pips = 0.0 if is_inside else min(abs(current_price - gap["high"]), abs(current_price - gap["low"])) / pip_size
        scored.append({**gap, "tier_score": tier_score, "is_inside": is_inside, "distance_pips": distance_pips})

    if not scored:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": f"No FVG/IFVG zone clears the minimum quality tier ({FVG_IFVG_MIN_TIER_SCORE})"}

    # Prioritize an active retest (price inside the zone right now), then nearest, then highest tier score
    scored.sort(key=lambda g: (not g["is_inside"], g["distance_pips"], -g["tier_score"]))
    best = scored[0]

    # ✅ FIXED (2026-09-15): the nearest active gap set the direction however
    # far away it was -- a gap 40 ATR below still voted BUY -- so this
    # indicator carried a direction on 86% of study bars. A gap is a setup
    # only while price is in it or about to be.
    _reach_pips = FVG_IFVG_REACH_ATR * atr_pips if atr_pips else None
    if not best["is_inside"] and _reach_pips is not None and best["distance_pips"] > _reach_pips:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 30,
                "reason": f"nearest active gap is {best['distance_pips']:.1f} pips away "
                          f"(beyond {FVG_IFVG_REACH_ATR} ATR)",
                "active_gap": best}

    # ✅ FIXED: was `"BUY" if best["polarity"] == "BULLISH" else "SELL"`,
    # so EVERY value that was not exactly the string "BULLISH" produced a
    # SELL -- at full magnitude, not as a neutral fallback:
    #
    #     None      -> SELL -22.8      NEUTRAL -> SELL -22.8
    #     "bullish" -> SELL -22.8      ""      -> SELL -22.8
    #
    # The lowercase case is the dangerous one: a polarity that differs
    # only in case becomes a maximum-confidence signal in the exact
    # OPPOSITE direction, with a reason string that still reads
    # correctly. Nothing downstream could detect it.
    #
    # Same shape as two bugs already fixed here -- the stochastic
    # tie-break and MACD's missing mirror branch. An ambiguous input has
    # to resolve to NEUTRAL, never to a direction, because "not
    # recognised" is not evidence for the other side.
    _polarity = str(best.get("polarity") or "").strip().upper()
    if _polarity == "BULLISH":
        direction = "BUY"
    elif _polarity == "BEARISH":
        direction = "SELL"
    else:
        logger.warning(
            f"[FVG] unrecognised gap polarity {best.get('polarity')!r} "
            f"[{best.get('low')}-{best.get('high')}] -- scoring NEUTRAL. "
            f"Previously this produced a full-strength SELL.")
        return {
            "recommendation": "NEUTRAL",
            "score": 0,
            "confidence": 0,
            "reason": (f"FVG/IFVG zone has unrecognised polarity "
                       f"{best.get('polarity')!r} -- cannot assign a direction"),
            "active_gap": best,
        }
    confidence = round(min(90, best["tier_score"] * (1.15 if best["is_inside"] else 0.85)), 1)
    score = round(min(25, best["tier_score"] * 0.25), 1)

    kind = "IFVG (inverted)" if best["is_inverse_fvg"] else "FVG"
    location = "price is currently inside the zone" if best["is_inside"] else f"{best['distance_pips']:.1f} pips away"

    return {
        "recommendation": direction,
        "score": score if direction == "BUY" else -score,
        "confidence": confidence,
        "reason": f"{kind} [{best['low']}-{best['high']}], tier score {best['tier_score']:.0f}, {location}",
        "active_gap": best,
    }


def evaluate_fvg_ifvg_setup(
    fvg_list: List[Dict[str, Any]],
    fvg_indicator: Dict[str, Any],
    symbol: str,
    order_type: str,
    current_price: float,
    pip_size: float,
    spread_pips: float,
    margin_safe_lot: float,
    recent_swing_high: Optional[float],
    recent_swing_low: Optional[float],
    target_risk_usd: float = None,
    volume_profile_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    FVG/IFVG SETUP: fires only when price is actively retesting the
    best-scored active gap/IFVG from score_fvg_ifvg_indicator() — not
    just "there's a decent gap somewhere nearby".

    - SL: the far side of the zone being retested, plus a spread buffer
      — a full close through that side is exactly detect_all_fvgs()'s
      own inversion condition, so a further breach means this zone has
      itself just become an IFVG and the original premise is dead.
    - TP: nearest opposing swing point (recent_swing_high/low) — the
      standard ICT liquidity target, same technique evaluate_smc_trade_
      setup() uses.
    - Also requires volume-profile confluence, same as the other
      reversal-style setups.
    """
    if target_risk_usd is None:
        target_risk_usd = SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE

    if not fvg_indicator or fvg_indicator.get("recommendation") not in ("BUY", "SELL") or not fvg_indicator.get("active_gap"):
        return {"is_perfect_setup": False, "reason": "No qualifying FVG/IFVG zone to trade"}

    active_gap = fvg_indicator["active_gap"]
    if not active_gap.get("is_inside"):
        return {
            "is_perfect_setup": False,
            "reason": f"Best zone is {active_gap.get('distance_pips', 0):.1f} pips away — not an active retest yet",
        }

    direction = fvg_indicator["recommendation"]

    if order_type and order_type.upper() not in (direction, "AUTO", "BOTH", ""):
        return {"is_perfect_setup": False, "reason": f"FVG/IFVG direction ({direction}) conflicts with the system's own measured best direction ({order_type})"}

    vp_confluence = _check_volume_profile_confluence(direction, volume_profile_data, current_price)
    if not vp_confluence["confluent"]:
        return {
            "is_perfect_setup": False,
            "reason": f"FVG/IFVG retest not confirmed by volume profile: {vp_confluence['note']}",
            "direction": direction,
        }

    buffer_price = max(spread_pips * FVG_IFVG_SETUP_SL_BUFFER_SPREAD_MULT, FVG_IFVG_SETUP_SL_MIN_BUFFER_PIPS) * pip_size

    if direction == "BUY":
        stop_loss = round(active_gap["low"] - buffer_price, 5)
        take_profit = round(recent_swing_high, 5) if recent_swing_high else None
    else:
        stop_loss = round(active_gap["high"] + buffer_price, 5)
        take_profit = round(recent_swing_low, 5) if recent_swing_low else None

    if take_profit is None:
        return {"is_perfect_setup": False, "reason": "No recent swing point available to size the exit target against", "direction": direction}

    if direction == "BUY":
        risk_pips = (current_price - stop_loss) / pip_size
        reward_pips = (take_profit - current_price) / pip_size
    else:
        risk_pips = (stop_loss - current_price) / pip_size
        reward_pips = (current_price - take_profit) / pip_size

    if risk_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Computed stop loss is on the wrong side of entry - setup invalid", "direction": direction}
    if reward_pips <= 0:
        return {"is_perfect_setup": False, "reason": "Nearest swing point target is not beyond entry - too little room left", "direction": direction}

    risk_reward_ratio = round(reward_pips / risk_pips, 2)
    if risk_reward_ratio < FVG_IFVG_SETUP_MIN_RR:
        return {
            "is_perfect_setup": False,
            "reason": f"Risk:reward {risk_reward_ratio} below minimum {FVG_IFVG_SETUP_MIN_RR} for this setup",
            "direction": direction,
        }

    pip_value_per_pip = _get_pip_value_per_pip(symbol, margin_safe_lot, current_price, direction, pip_size)
    projected_risk_usd = margin_safe_lot * risk_pips * pip_value_per_pip if pip_value_per_pip else None
    final_lot = margin_safe_lot
    risk_note = "within target risk budget"

    if projected_risk_usd and target_risk_usd and projected_risk_usd > target_risk_usd:
        scale = target_risk_usd / projected_risk_usd
        final_lot = max(0.01, round(margin_safe_lot * scale, 2))
        risk_note = f"lot reduced from {margin_safe_lot} to {final_lot} to keep risk at the ${target_risk_usd:.2f} target"
        if pip_value_per_pip:
            projected_risk_usd = final_lot * risk_pips * pip_value_per_pip

    return {
        "is_perfect_setup": True,
        "direction": direction,
        "zone_type": "IFVG" if active_gap["is_inverse_fvg"] else "FVG",
        "zone": {"high": active_gap["high"], "low": active_gap["low"]},
        "tier_score": round(active_gap["tier_score"], 1),
        "volume_profile_confluence": vp_confluence,
        "entry_type": "MARKET",
        "entry_price": round(current_price, 5),
        "stop_loss": stop_loss,
        "stop_loss_basis": "far side of the retested zone + spread buffer (a breach here is the zone's own inversion condition)",
        "take_profit": take_profit,
        "take_profit_basis": "nearest opposing swing point (liquidity target)",
        "risk_pips": round(risk_pips, 1),
        "reward_pips": round(reward_pips, 1),
        "risk_reward_ratio": f"1:{risk_reward_ratio}",
        "lot_size": final_lot,
        "margin_safe_lot_ceiling": margin_safe_lot,
        "projected_risk_usd": round(projected_risk_usd, 2) if projected_risk_usd else None,
        "target_risk_usd": round(target_risk_usd, 2) if target_risk_usd else None,
        "risk_note": risk_note,
        "buffer_pips_applied": round(buffer_price / pip_size, 1),
        "invalidation_note": "Not backtested.",
    }


def score_sr_volume_profile_confluence(
    sr_data: Dict[str, Any], volume_profile_data: Dict[str, Any], pip_size: float
) -> Dict[str, Any]:
    """
    Advisory-only cross-check between the pivot-based S/R levels
    (calculate_pivot_levels — pure price formula, no volume input) and
    the volume-profile levels (POC/VAH/VAL — empirical, from where
    volume actually transacted). Flags which pivot levels have real
    transacted-volume backing nearby versus which don't.

    ✅ Feeds back into sr_data's "score" (see the caller, shortly after
    this is computed) -- each confirmed level adds a small amount of
    confidence, scaled by how many of the levels checked are confirmed.
    No longer purely advisory.
    """
    if not volume_profile_data or not volume_profile_data.get("available"):
        return {"available": False, "reason": "Volume profile unavailable"}

    poc = volume_profile_data.get("poc")
    vah = volume_profile_data.get("vah")
    val = volume_profile_data.get("val")
    vp_levels = [("POC", poc), ("VAH", vah), ("VAL", val)]
    tolerance_price = SR_VOLUME_CONFLUENCE_TOLERANCE_PIPS * pip_size

    levels = {}
    for level_name in ("pivot", "r1", "r2", "r3", "s1", "s2", "s3"):
        level_price = sr_data.get(level_name)
        if level_price is None:
            continue
        matches = {vp_name: round(abs(level_price - vp_price) / pip_size, 1)
                   for vp_name, vp_price in vp_levels
                   if vp_price is not None and abs(level_price - vp_price) <= tolerance_price}
        levels[level_name] = {
            "price": level_price,
            "volume_confirmed": len(matches) > 0,
            "confirming_levels": matches,
        }

    confirmed_count = sum(1 for v in levels.values() if v["volume_confirmed"])

    return {
        "available": True,
        "tolerance_pips": SR_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
        "levels": levels,
        "confirmed_count": confirmed_count,
        "total_levels_checked": len(levels),
    }


def score_sd_volume_profile_confluence(
    sd_data: Dict[str, Any], volume_profile_data: Dict[str, Any], pip_size: float
) -> Dict[str, Any]:
    """
    Advisory-only cross-check between the active supply/demand zone
    (_detect_supply_demand_zone — graded A-E purely on touch count, zero
    volume input) and the volume-profile levels (POC/VAH/VAL). Flags
    whether the zone also has real transacted-volume backing nearby.

    ✅ Feeds back into sd_data's "score" (see the caller, shortly after
    this is computed), alongside order_block_mitigation status for the
    same zone. zone_grade (the trade-eligibility gate) is deliberately
    left untouched. No longer purely advisory.
    """
    if not volume_profile_data or not volume_profile_data.get("available"):
        return {"available": False, "reason": "Volume profile unavailable"}

    zone_level = sd_data.get("zone_level")
    zone_type = sd_data.get("zone_type")
    if zone_level is None or zone_type not in ("DEMAND", "SUPPLY"):
        return {"available": False, "reason": "No active supply/demand zone to check"}

    poc = volume_profile_data.get("poc")
    vah = volume_profile_data.get("vah")
    val = volume_profile_data.get("val")
    vp_levels = [("POC", poc), ("VAH", vah), ("VAL", val)]
    tolerance_price = SD_VOLUME_CONFLUENCE_TOLERANCE_PIPS * pip_size

    matches = {vp_name: round(abs(zone_level - vp_price) / pip_size, 1)
               for vp_name, vp_price in vp_levels
               if vp_price is not None and abs(zone_level - vp_price) <= tolerance_price}

    return {
        "available": True,
        "tolerance_pips": SD_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
        "zone_type": zone_type,
        "zone_level": zone_level,
        "zone_grade": sd_data.get("zone_grade"),
        "volume_confirmed": len(matches) > 0,
        "confirming_levels": matches,
    }


def score_ob_volume_profile_confluence(
    order_blocks: Dict[str, Any], volume_profile_data: Dict[str, Any], pip_size: float
) -> Dict[str, Any]:
    """
    Advisory-only cross-check between SMC order blocks (_detect_order_
    blocks — judged purely by candle-range displacement, zero volume-node
    input) and the volume-profile levels (POC/VAH/VAL). Checks both the
    bullish and bearish order block if present, flags whether each has
    real transacted-volume backing nearby.

    Does NOT touch evaluate_smc_trade_setup()'s own entry/SL logic,
    which already uses these order blocks directly — this is purely
    additional information surfaced in the report.
    """
    if not volume_profile_data or not volume_profile_data.get("available"):
        return {"available": False, "reason": "Volume profile unavailable"}

    if not order_blocks or (not order_blocks.get("bullish_ob") and not order_blocks.get("bearish_ob")):
        return {"available": False, "reason": "No active order block to check"}

    poc = volume_profile_data.get("poc")
    vah = volume_profile_data.get("vah")
    val = volume_profile_data.get("val")
    vp_levels = [("POC", poc), ("VAH", vah), ("VAL", val)]
    tolerance_price = OB_VOLUME_CONFLUENCE_TOLERANCE_PIPS * pip_size

    def _check_ob(ob: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not ob:
            return None
        ob_mid = (ob["high"] + ob["low"]) / 2.0
        matches = {vp_name: round(abs(ob_mid - vp_price) / pip_size, 1)
                   for vp_name, vp_price in vp_levels
                   if vp_price is not None and abs(ob_mid - vp_price) <= tolerance_price}
        return {"high": ob["high"], "low": ob["low"], "volume_confirmed": len(matches) > 0, "confirming_levels": matches}

    return {
        "available": True,
        "tolerance_pips": OB_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
        "bullish_ob": _check_ob(order_blocks.get("bullish_ob")),
        "bearish_ob": _check_ob(order_blocks.get("bearish_ob")),
    }


def score_sweep_volume_profile_confluence(
    sweep: Dict[str, Any], volume_profile_data: Dict[str, Any], pip_size: float
) -> Dict[str, Any]:
    """
    Advisory-only cross-check between a detected liquidity sweep
    (_detect_liquidity_sweep — judged purely by wick-beyond-prior-swing
    + close-back-inside, zero volume-node input) and the volume-profile
    levels (POC/VAH/VAL). A swept level near VAH/VAL is a more
    convincing "real resting stops got taken out" read than one in a
    thin area.

    Does NOT touch evaluate_smc_trade_setup()'s own use of the sweep
    level for SL placement — this is purely additional information
    surfaced in the report.
    """
    if not volume_profile_data or not volume_profile_data.get("available"):
        return {"available": False, "reason": "Volume profile unavailable"}

    if not sweep or not sweep.get("swept") or sweep.get("level") is None:
        return {"available": False, "reason": "No active liquidity sweep to check"}

    level = sweep["level"]
    poc = volume_profile_data.get("poc")
    vah = volume_profile_data.get("vah")
    val = volume_profile_data.get("val")
    vp_levels = [("POC", poc), ("VAH", vah), ("VAL", val)]
    tolerance_price = SWEEP_VOLUME_CONFLUENCE_TOLERANCE_PIPS * pip_size

    matches = {vp_name: round(abs(level - vp_price) / pip_size, 1)
               for vp_name, vp_price in vp_levels
               if vp_price is not None and abs(level - vp_price) <= tolerance_price}

    return {
        "available": True,
        "tolerance_pips": SWEEP_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
        "sweep_type": sweep.get("type"),
        "sweep_level": level,
        "volume_confirmed": len(matches) > 0,
        "confirming_levels": matches,
    }


def _check_volume_profile_breakout_confluence(
    direction: str, volume_profile_data: Optional[Dict[str, Any]], current_price: float
) -> Dict[str, Any]:
    """
    Inverted counterpart to _check_volume_profile_confluence(). That
    helper gates the mean-reversion setups: price OUTSIDE the value area
    confirms an extreme worth fading. For a trend/breakout setup, the
    same fact means the opposite thing - price outside the value area
    means real momentum has carried it beyond where the market
    previously accepted fair value, which CONFIRMS the breakout rather
    than warning against it.

    Informational only, never gates entry - breakout setups (EMA
    crossover especially) are meant to catch moves early, often before
    price has cleared the value area at all, so requiring this would
    defeat the point.
    """
    if not volume_profile_data or not volume_profile_data.get("available"):
        return {"confirmed": None, "note": "volume profile unavailable"}

    vah = volume_profile_data.get("vah")
    val = volume_profile_data.get("val")
    poc = volume_profile_data.get("poc")
    if vah is None or val is None:
        return {"confirmed": None, "note": "volume profile incomplete"}

    if direction == "BUY":
        confirmed = current_price > vah
        note = (
            f"price above value area high (VAH {vah}) — confirms breakout beyond prior fair value"
            if confirmed else
            f"price ({current_price}) still inside/below the value area (VAH {vah}) — breakout not yet "
            f"confirmed by volume profile, may just be an early entry"
        )
    else:
        confirmed = current_price < val
        note = (
            f"price below value area low (VAL {val}) — confirms breakdown beyond prior fair value"
            if confirmed else
            f"price ({current_price}) still inside/above the value area (VAL {val}) — breakdown not yet "
            f"confirmed by volume profile, may just be an early entry"
        )

    return {"confirmed": confirmed, "note": note, "vah": vah, "val": val, "poc": poc}


def score_liquidity_pools_volume_profile_confluence(
    liquidity_pools: Dict[str, Any], volume_profile_data: Dict[str, Any], pip_size: float
) -> Dict[str, Any]:
    """
    Advisory-only cross-check between order_flow_forensics.py's equal-
    highs/equal-lows liquidity pools (clustered swing points, zero
    volume-node input) and POC/VAH/VAL. Same "does this level have real
    volume behind it" question already answered for SMC order blocks
    and liquidity sweeps, applied to this separate pool concept.
    """
    if not volume_profile_data or not volume_profile_data.get("available"):
        return {"available": False, "reason": "Volume profile unavailable"}
    if not liquidity_pools or not liquidity_pools.get("available"):
        return {"available": False, "reason": "No liquidity pool data to check"}

    poc = volume_profile_data.get("poc")
    vah = volume_profile_data.get("vah")
    val = volume_profile_data.get("val")
    vp_levels = [("POC", poc), ("VAH", vah), ("VAL", val)]
    tolerance_price = LIQUIDITY_POOL_VOLUME_CONFLUENCE_TOLERANCE_PIPS * pip_size

    def _check_pools(pools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        checked = []
        for pool in pools:
            level = pool.get("level")
            if level is None:
                continue
            matches = {vp_name: round(abs(level - vp_price) / pip_size, 1)
                       for vp_name, vp_price in vp_levels
                       if vp_price is not None and abs(level - vp_price) <= tolerance_price}
            checked.append({
                "level": level,
                "touch_count": pool.get("touch_count"),
                "volume_confirmed": len(matches) > 0,
                "confirming_levels": matches,
            })
        return checked

    return {
        "available": True,
        "tolerance_pips": LIQUIDITY_POOL_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
        "equal_highs_pools": _check_pools(liquidity_pools.get("equal_highs_pools", [])),
        "equal_lows_pools": _check_pools(liquidity_pools.get("equal_lows_pools", [])),
    }


def score_wyckoff_volume_profile_confluence(
    wyckoff_data: Dict[str, Any], volume_profile_data: Dict[str, Any], current_price: float, pip_size: float
) -> Dict[str, Any]:
    """
    Advisory-only cross-check between the Wyckoff phase call
    (_detect_wyckoff_phase — judged from ADX/trend/volume-ratio pattern
    shape, no volume-NODE input) and the volume profile.

    Wyckoff phase has no discrete price level to check the way S/R or
    order blocks do, so this uses the phase's own logic instead:
    - ACCUMULATION/DISTRIBUTION (basing) phases: expect price to be
      trading NEAR the POC — a real base should be forming where volume
      has actually concentrated, not floating in a vacuum.
    - MARKUP/MARKDOWN (trending) phases: expect price to be OUTSIDE the
      value area in the trend's direction — same breakout-confirmation
      logic as EMA crossover, since a genuine markup/markdown should
      have carried price beyond the prior basing range by now.
    - TENTATIVE phases: no clear check applies, reported as such.
    """
    if not volume_profile_data or not volume_profile_data.get("available"):
        return {"available": False, "reason": "Volume profile unavailable"}

    phase = wyckoff_data.get("phase", "") if wyckoff_data else ""
    poc = volume_profile_data.get("poc")

    if "ACCUMULATION" in phase or "DISTRIBUTION" in phase:
        if poc is None:
            return {"available": False, "reason": "No POC to check basing phase against"}
        tolerance_price = WYCKOFF_VOLUME_CONFLUENCE_TOLERANCE_PIPS * pip_size
        distance_pips = abs(current_price - poc) / pip_size
        confirmed = abs(current_price - poc) <= tolerance_price
        return {
            "available": True,
            "check_type": "basing_near_poc",
            "phase": phase,
            "poc": poc,
            "distance_pips": round(distance_pips, 1),
            "volume_confirmed": confirmed,
            "note": (
                f"price {distance_pips:.1f} pips from POC ({poc}) — "
                + ("consistent with a real base forming at the volume node" if confirmed
                   else "basing phase called, but price isn't actually near where volume has concentrated")
            ),
        }
    elif "MARKUP" in phase or "MARKDOWN" in phase:
        direction = "BUY" if "MARKUP" in phase else "SELL"
        breakout = _check_volume_profile_breakout_confluence(direction, volume_profile_data, current_price)
        return {
            "available": True,
            "check_type": "breakout_beyond_value_area",
            "phase": phase,
            "volume_confirmed": breakout.get("confirmed"),
            "note": breakout.get("note"),
        }
    else:
        return {"available": False, "reason": f"No volume-profile check defined for phase '{phase}' (tentative/undetermined)"}