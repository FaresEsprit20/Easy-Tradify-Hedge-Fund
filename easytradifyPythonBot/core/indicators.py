"""
TECHNICAL INDICATORS - DETECTION AND ANALYSIS FUNCTIONS ONLY
Raw calculations (RSI, MACD, BB, Stochastic, ATR) are in calculations.py

✅ MERGED: All helper functions moved here, helpers.py DELETED
✅ FIXED: get_zone_grade_and_size() now uses ZONE_GRADE_THRESHOLDS from config
✅ FIXED: apply_zone_penalties() now uses config values
✅ FIXED: No more duplication between helpers and indicators
✅ FIXED: Single source of truth for zone grading
"""

import MetaTrader5 as mt5
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
import math
import logging
import time
import copy
import threading
from threading import Lock
from datetime import datetime
logger = logging.getLogger(__name__)

# ============================================================
# IMPORT FROM UNIFIED CONFIG
# ============================================================
from core.asset_analysis_config import (
    # Decision thresholds
    DECISION_STRONG_ENTRY,
    DECISION_ENTRY_WITH_ZONE,
    DECISION_WAIT_THRESHOLD,
    DECISION_MONITOR_THRESHOLD,
    STAR_5_THRESHOLD,
    STAR_4_THRESHOLD,
    STAR_3_THRESHOLD,
    STAR_2_THRESHOLD,
    VOLUME_SPIKE_THRESHOLD_M1,
    get_bb_period,
    get_bb_std,
    VOLUME_LOW_THRESHOLD_M1,
    # ADX thresholds
    ADX_THRESHOLDS,
    ADX_EXTREME_THRESHOLDS,
    ADX_STRONG_TREND_THRESHOLD,
    # EMA settings
    EMA_MIN_SEPARATION_PIPS,
    _EMA_SEPARATION_MULTIPLIERS,
    # Zone settings
    ZONE_AT_ZONE_PIPS,
    ZONE_TOUCH_COUNT_THRESHOLD,
    ZONE_RESET_AFTER_HOURS,
    ZONE_MAX_TOUCHES_FOR_GRADE,
    ZONE_TOUCH_ATR_FRACTION,
    ZONE_QUALITY_WEIGHTS,
    ZONE_TOUCH_QUALITY_CURVE,
    ZONE_TOUCH_QUALITY_FLOOR,
    ZONE_QUALITY_GRADE_THRESHOLDS,
    ZONE_PERSISTENCE_SECONDS,
    ZONE_GRADE_THRESHOLDS,      # ✅ SINGLE SOURCE OF TRUTH
    ZONE_TIME_DECAY_CONFIG,
    ZONE_LOOKBACK_BARS,
    ZONE_TOUCH_DISTANCE_PIPS,
    ZONE_GRADE_SCORES,          # ✅ SINGLE SOURCE OF TRUTH
    ZONE_GRADE_MULTIPLIERS,     # ✅ SINGLE SOURCE OF TRUTH
    STOCH_K,
    STOCH_D,
    # Wyckoff settings
    WYCKOFF_MARKUP_STRONG_MIN_VOL,
    WYCKOFF_MARKUP_MIN_VOL,
    WYCKOFF_MARKDOWN_STRONG_MIN_VOL,
    WYCKOFF_MARKDOWN_MIN_VOL,
    WYCKOFF_SPIKE_THRESHOLDS,
    WYCKOFF_CONSOLIDATION_VOLUME_THRESHOLD,
    WYCKOFF_LOOKBACK_BARS,
    WYCKOFF_UPGRADE_ADX_THRESHOLD,
    # Momentum thresholds
    MOMENTUM_THRESHOLDS,
    # Divergence settings
    DIVERGENCE_LOOKBACK,
    DEFAULT_DIVERGENCE_LOOKBACK,
    M15_FALLBACK_ENABLED,
    # Min bars for trend
    MIN_BARS_FOR_TREND,
    # Pin bar threshold
    PIN_BAR_THRESHOLD,
    # MACD settings - FAST MACD (5,13,6)
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
    MACD_BULLISH_THRESHOLD,
    MACD_BEARISH_THRESHOLD,
    # Helper functions
    get_zone_proximity_pips,
    get_ema_min_separation_pips,
    # Spread settings
    MAX_SPREAD_PIPS,
    TYPICAL_SPREADS,
    # Volume settings
    VOLUME_BASELINE_BARS,
    # Micro-structure settings
    SPREAD_COLLAPSE_ABSOLUTE_THRESHOLD_PIPS,
    SPREAD_COLLAPSE_PERCENTAGE_THRESHOLD,
    SPREAD_COLLAPSE_METALS_THRESHOLD,
    MICRO_STRUCTURE_PROBABILITY_THRESHOLD,
    MICRO_STRUCTURE_MOMENTUM_THRESHOLD,
    MICRO_STRUCTURE_MOMENTUM_ACCELERATION,
    MICRO_STRUCTURE_MOMENTUM_MIN_RATE,
    MICRO_STRUCTURE_ICEBERG_MIN_VOLUME,
    MICRO_STRUCTURE_ICEBERG_MAX_PRANGE_PIPS,
    MICRO_STRUCTURE_ICEBERG_MIN_TICKS,
    MICRO_STRUCTURE_VOLUME_IMBALANCE_CONFIRM_RATIO,
    MIN_ACTIVITY_SECONDS,
)

# ============================================================
# IMPORT FROM CALCULATIONS (for raw calculations)
# ============================================================
from core.calculations import (
    calculate_correct_atr,
    _calculate_rsi,
    _calculate_ema,
    _calculate_adx,
    _calculate_macd,
    _calculate_stochastic,
    _calculate_bollinger_bands,
)

# ✅ Single source of truth for swing-high/low detection — shared with
# patterns.py's Elliott Wave / chart-pattern swing legs instead of each
# file keeping its own (previously divergent, both buggy) copy.
from core.swing_points import find_swing_points, find_swing_points_ohlc, get_min_swing_size

# ✅ Zone touch-distance timeframe scaling (see _get_zone_touch_distance).
ZONE_TOUCH_DISTANCE_TF_MULTIPLIER = {
    "M1": 0.25,
    "M5": 0.4,
    "M15": 0.6,
    "M30": 0.8,
    "H1": 1.0,
}

logger = logging.getLogger(__name__)

# ============================================================
# GLOBAL STATE (Thread-safe with locks where needed)
# ============================================================

_TICK_VOLUME_WARNING_LOGGED_PER_SYMBOL = {}
_TICK_VOLUME_LOCK = threading.Lock()
_VOLUME_WARNING_LOGGED = False
_VOLUME_WARNING_LOCK = threading.Lock()


# ============================================================
# JSON SAFE CONVERSION
# ============================================================

def make_json_safe(obj: Any) -> Any:
    """Convert numpy types and other non-JSON objects to JSON-safe types."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
        return obj
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        val = float(obj)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, dict):
        return {make_json_safe(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_json_safe(item) for item in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


# ============================================================
# VOLUME RATIO (FIXED - Candle Progress Aware)
# ============================================================

def get_volume_ratio(volumes: List[float], timeframe: str = "M1", candle_progress_pct: float = 100) -> Tuple[float, bool, bool]:
    """
    Volume ratio with instrument/timeframe-aware baseline.
    For M1, uses 200-bar baseline for better statistical significance.
    """
    global _VOLUME_WARNING_LOGGED
    
    if not volumes:
        logger.debug("[VOLUME] Empty volumes list provided")
        return 1.0, False, False
    
    baseline_bars = VOLUME_BASELINE_BARS.get(timeframe.upper(), VOLUME_BASELINE_BARS["DEFAULT"])
    
    if len(volumes) >= baseline_bars:
        zero_count = sum(1 for v in volumes[-baseline_bars:] if v == 0)
        if zero_count > baseline_bars // 2:
            with _VOLUME_WARNING_LOCK:
                if not _VOLUME_WARNING_LOGGED:
                    logger.warning(f"[VOLUME] High percentage of zero volume bars: {zero_count}/{baseline_bars}")
                    _VOLUME_WARNING_LOGGED = True
    
    if len(volumes) < baseline_bars:
        if len(volumes) < 20:
            return 1.0, False, False
        avg_volume = sum(volumes[-20:]) / 20
    else:
        avg_volume = sum(volumes[-baseline_bars:]) / baseline_bars
    
    current_volume = volumes[-1] if volumes else 0
    
    if candle_progress_pct < 10:
        expected_volume = avg_volume * (candle_progress_pct / 100)
        if expected_volume < 1:
            expected_volume = 1
        ratio = current_volume / expected_volume if expected_volume > 0 else 1.0
    else:
        if avg_volume == 0:
            ratio = 1.0
        else:
            ratio = current_volume / avg_volume
    
    is_spike = ratio >= 1.5
    
    is_increasing = False
    if len(volumes) >= 4:
        if volumes[-1] > volumes[-2] > volumes[-3] > volumes[-4]:
            is_increasing = True
    
    if candle_progress_pct > 10 and current_volume == 0 and avg_volume > 0:
        with _VOLUME_WARNING_LOCK:
            if not _VOLUME_WARNING_LOGGED:
                logger.warning(f"[VOLUME] Zero volume in established candle (progress {candle_progress_pct:.0f}%)")
                _VOLUME_WARNING_LOGGED = True
    
    return ratio, is_spike, is_increasing


# ============================================================
# CANDLE PROGRESS (Simple time utility)
# ============================================================

def get_candle_progress_fixed(rates: np.ndarray, selected_tf: int, symbol: str) -> Tuple[float, bool]:
    """Get candle progress percentage and whether candle is ready for trading."""
    if rates is None or len(rates) == 0:
        return 0.0, False
    
    last_candle_time = int(rates[-1][0])
    tick = mt5.symbol_info_tick(symbol)
    current_time = tick.time if tick else int(time.time())
    
    tf_minutes = {
        mt5.TIMEFRAME_M1: 1, mt5.TIMEFRAME_M5: 5, mt5.TIMEFRAME_M15: 15,
        mt5.TIMEFRAME_M30: 30, mt5.TIMEFRAME_H1: 60, mt5.TIMEFRAME_H4: 240, mt5.TIMEFRAME_D1: 1440
    }
    
    minutes = tf_minutes.get(selected_tf, 1)
    candle_duration_seconds = minutes * 60
    elapsed = current_time - last_candle_time
    # rates now ends with the last CLOSED bar (core/closed_bars.py); the bar
    # in progress opened one duration after it.
    if elapsed > candle_duration_seconds:
        elapsed -= candle_duration_seconds
    progress = elapsed / candle_duration_seconds if candle_duration_seconds > 0 else 1
    progress = min(1.0, max(0.0, progress))
    
    return progress, progress >= 0.75


# ============================================================
# ✅ FIXED: ZONE GRADE AND SIZE - USES CONFIG VALUES
# ============================================================

def get_zone_grade_and_size_strict(touch_count: int) -> Tuple[str, float, int]:
    """
    Get zone grade based on touch count - STRICT version.
    ✅ FIXED: Uses same config thresholds as regular (no multiplier)
    """
    effective_touch_count = min(touch_count, ZONE_MAX_TOUCHES_FOR_GRADE)
    
    # ✅ FIXED: Use same thresholds as regular (no 1.1x multiplier)
    if effective_touch_count >= ZONE_GRADE_THRESHOLDS["A"]:
        grade = "A"
    elif effective_touch_count >= ZONE_GRADE_THRESHOLDS["B"]:
        grade = "B"
    elif effective_touch_count >= ZONE_GRADE_THRESHOLDS["C"]:
        grade = "C"
    elif effective_touch_count >= ZONE_GRADE_THRESHOLDS["D"]:
        grade = "D"
    else:
        grade = "E"
    
    multiplier = ZONE_GRADE_MULTIPLIERS.get(grade, 0.35)
    score = ZONE_GRADE_SCORES.get(grade, 35)
    
    return grade, multiplier, score

# ============================================================
# ZONE POSITION VALIDITY
# ============================================================

def get_zone_position_validity(
    zone_level: float,
    range_high: float,
    range_low: float,
    zone_type: str
) -> Tuple[bool, str, float, float]:
    """Validate zone position within the range.

    ✅ FIXED: now also returns a continuous `severity` (0.0 = ideal
    position, growing as the zone drifts past the boundary) instead of
    only a hard True/False. Previously a demand zone at 41% of the range
    was treated identically to one at 90% — both instantly collapsed the
    zone grade to D via apply_zone_penalties(). On M1, where the recent
    range can be a handful of pips wide, that boundary flips on trivial
    price noise. Downstream, the penalty is now graduated by severity
    instead of an instant drop to D for any overshoot, however small.
    """
    if range_high <= range_low:
        return True, "Unable to determine range", 0.5, 0.0

    position_pct = (zone_level - range_low) / (range_high - range_low)

    if zone_type == "DEMAND":
        severity = max(0.0, position_pct - 0.4)
        if position_pct > 0.4:
            return False, f"Demand zone too high in range ({position_pct:.1%})", position_pct, severity
        elif position_pct > 0.3:
            return True, f"Demand zone in lower-mid range ({position_pct:.1%})", position_pct, severity
        else:
            return True, f"Demand zone in ideal position ({position_pct:.1%})", position_pct, severity

    elif zone_type == "SUPPLY":
        severity = max(0.0, 0.6 - position_pct)
        if position_pct < 0.6:
            return False, f"Supply zone too low in range ({position_pct:.1%})", position_pct, severity
        elif position_pct < 0.7:
            return True, f"Supply zone in upper-mid range ({position_pct:.1%})", position_pct, severity
        else:
            return True, f"Supply zone in ideal position ({position_pct:.1%})", position_pct, severity

    return True, "Neutral zone position", position_pct, 0.0


# ============================================================
# ZONE VOLUME PROFILE
# ============================================================

def get_zone_volume_profile(
    prices: List[float],
    volumes: List[float],
    zone_level: float,
    pip_size: float,
    atr_pips: float = None
) -> Dict[str, Any]:
    """Analyze volume profile around a zone level.

    ✅ This function was DEAD CODE -- defined, complete, and called from
    nowhere in the codebase. Meanwhile apply_zone_penalties()'s PENALTY 5
    needed exactly the `volume_confirmed` it produces, and was being fed a
    hardcoded False. The computation existed and the consumer existed;
    they were simply never connected.

    ✅ atr_pips: the sampling band below was `pip_size * 2` -- a flat
    2-pip window, the same absolute-units mistake as the zone touch band
    and the swing filter. On XAGUSD with a 63-pip ATR, almost no bar close
    lands within 2 pips of the level, so zone_touches came out 0,
    zone_volume_ratio 0, and the verdict was VERY_WEAK / not confirmed
    regardless of what volume actually did there. Floored at a fraction of
    ATR (never narrowed) so the window means something comparable across
    instruments.
    """
    if len(prices) < 20 or len(volumes) < 20:
        return {
            "zone_volume_ratio": 0.5,
            "touches_at_zone": 0,
            "volume_confirmed": False,
            "profile_strength": "UNKNOWN"
        }
    
    avg_volume = sum(volumes[-50:]) / 50 if len(volumes) >= 50 else sum(volumes) / len(volumes)
    
    zone_volume = 0
    zone_touches = 0
    band_pips = 2.0
    if atr_pips and atr_pips > 0:
        band_pips = max(band_pips, atr_pips * ZONE_TOUCH_ATR_FRACTION)
    zone_price_zone = band_pips * pip_size
    
    for i, price in enumerate(prices):
        if abs(price - zone_level) < zone_price_zone:
            if i < len(volumes):
                zone_volume += volumes[i]
                zone_touches += 1
    
    if zone_touches > 0:
        avg_zone_volume = zone_volume / zone_touches
        zone_volume_ratio = avg_zone_volume / avg_volume if avg_volume > 0 else 0
    else:
        zone_volume_ratio = 0
    
    if zone_volume_ratio > 1.5:
        profile_strength = "STRONG"
        volume_confirmed = True
    elif zone_volume_ratio > 0.8:
        profile_strength = "MODERATE"
        volume_confirmed = True
    elif zone_volume_ratio > 0.4:
        profile_strength = "WEAK"
        volume_confirmed = False
    else:
        profile_strength = "VERY_WEAK"
        volume_confirmed = False
    
    return {
        "zone_volume_ratio": round(zone_volume_ratio, 2),
        "touches_at_zone": zone_touches,
        "volume_confirmed": volume_confirmed,
        "profile_strength": profile_strength,
        "sampling_band_pips": round(band_pips, 2),
    }


# ============================================================
# ✅ FIXED: APPLY ZONE PENALTIES - USES CONFIG VALUES
# ============================================================
def apply_zone_penalties(
    zone_grade: str,
    volume_ratio: float,
    adx: float,
    touch_count: int,
    spread_pips: float,
    pip_size: float = 0.001,
    position_valid: bool = True,
    position_pct: float = 0.5,
    volume_confirmed: bool = False,
    position_severity: float = 0.0
) -> Tuple[str, float, int, str]:
    """
    Apply penalties to zone grade based on market conditions.
    ✅ FIXED: MUCH LESS AGGRESSIVE penalties - uses config values
    ✅ FIXED: position penalty is now graduated by `position_severity`
    (see get_zone_position_validity) instead of an instant drop to D for
    any overshoot past the boundary. Downgrade also now works from
    whatever grade the zone currently holds (A, B, C, or D) — the old
    code only handled downgrading from A or B and silently did nothing
    if the zone was already C or D.
    """
    grade = zone_grade
    multiplier = ZONE_GRADE_MULTIPLIERS.get(zone_grade, 0.35)
    score = ZONE_GRADE_SCORES.get(zone_grade, 35)
    reason = ""
    penalties_applied = []

    _GRADE_ORDER = ["A", "B", "C", "D", "E"]

    def _downgrade(current_grade: str, steps: int) -> str:
        idx = _GRADE_ORDER.index(current_grade) if current_grade in _GRADE_ORDER else len(_GRADE_ORDER) - 1
        idx = min(idx + steps, len(_GRADE_ORDER) - 1)
        return _GRADE_ORDER[idx]
    
    # ============================================================
    # PENALTY 1: Volume penalty (MUCH LESS AGGRESSIVE)
    # ============================================================
    if volume_ratio < 0.02:  # WAS 0.05 - only extreme cases
        penalties_applied.append("extremely low volume")
        grade = "D"
        multiplier = ZONE_GRADE_MULTIPLIERS.get("D", 0.50)
        score = ZONE_GRADE_SCORES.get("D", 50)
    elif volume_ratio < 0.05:  # WAS 0.10
        penalties_applied.append("very low volume")
        if grade == "A":
            grade = "B"
            multiplier = ZONE_GRADE_MULTIPLIERS.get("B", 0.85)
            score = ZONE_GRADE_SCORES.get("B", 85)
        elif grade == "B":
            grade = "C"
            multiplier = ZONE_GRADE_MULTIPLIERS.get("C", 0.70)
            score = ZONE_GRADE_SCORES.get("C", 70)
    elif volume_ratio < 0.10:  # WAS 0.20
        penalties_applied.append("low volume")
        if grade == "A":
            grade = "B"
            multiplier = ZONE_GRADE_MULTIPLIERS.get("B", 0.85)
            score = ZONE_GRADE_SCORES.get("B", 85)
    
    # ============================================================
    # PENALTY 2: Trend penalty (MUCH LESS AGGRESSIVE)
    # ============================================================
    if adx > 95:  # WAS 90 - only extreme ADX
        penalties_applied.append("extreme strong trend")
        grade = "D"
        multiplier = ZONE_GRADE_MULTIPLIERS.get("D", 0.50)
        score = ZONE_GRADE_SCORES.get("D", 50)
    elif adx > 85:  # WAS 80
        penalties_applied.append("very strong trend")
        if grade == "A":
            grade = "B"
            multiplier = ZONE_GRADE_MULTIPLIERS.get("B", 0.85)
            score = ZONE_GRADE_SCORES.get("B", 85)
        elif grade == "B":
            grade = "C"
            multiplier = ZONE_GRADE_MULTIPLIERS.get("C", 0.70)
            score = ZONE_GRADE_SCORES.get("C", 70)
    elif adx > 75:  # WAS 70
        penalties_applied.append("strong trend")
        if grade == "A":
            grade = "B"
            multiplier = ZONE_GRADE_MULTIPLIERS.get("B", 0.85)
            score = ZONE_GRADE_SCORES.get("B", 85)
    
    # ============================================================
    # PENALTY 3: Spread penalty (MUCH LESS AGGRESSIVE)
    # ============================================================
    if spread_pips > 150:  # WAS 100
        penalties_applied.append("extreme high spread")
        grade = "D"
        multiplier = ZONE_GRADE_MULTIPLIERS.get("D", 0.50)
        score = ZONE_GRADE_SCORES.get("D", 50)
    elif spread_pips > 100:  # WAS 70
        penalties_applied.append("high spread")
        if grade == "A":
            grade = "B"
            multiplier = ZONE_GRADE_MULTIPLIERS.get("B", 0.85)
            score = ZONE_GRADE_SCORES.get("B", 85)
        elif grade == "B":
            grade = "C"
            multiplier = ZONE_GRADE_MULTIPLIERS.get("C", 0.70)
            score = ZONE_GRADE_SCORES.get("C", 70)
    elif spread_pips > 75:  # WAS 50
        penalties_applied.append("elevated spread")
        if grade == "A":
            grade = "B"
            multiplier = ZONE_GRADE_MULTIPLIERS.get("B", 0.85)
            score = ZONE_GRADE_SCORES.get("B", 85)
    
    # ============================================================
    # PENALTY 4: Position penalty (graduated by severity, not a cliff)
    # ============================================================
    if position_severity > 0.15:
        penalties_applied.append(f"badly misplaced zone position (severity {position_severity:.2f})")
        grade = "D"
        multiplier = ZONE_GRADE_MULTIPLIERS.get("D", 0.50)
        score = ZONE_GRADE_SCORES.get("D", 50)
    elif position_severity > 0.05:
        penalties_applied.append(f"poor zone position (severity {position_severity:.2f})")
        grade = _downgrade(grade, 2)
        multiplier = ZONE_GRADE_MULTIPLIERS.get(grade, 0.35)
        score = ZONE_GRADE_SCORES.get(grade, 35)
    elif position_severity > 0.0:
        penalties_applied.append(f"borderline zone position (severity {position_severity:.2f})")
        grade = _downgrade(grade, 1)
        multiplier = ZONE_GRADE_MULTIPLIERS.get(grade, 0.35)
        score = ZONE_GRADE_SCORES.get(grade, 35)
    elif position_pct > 0.80 or position_pct < 0.20:
        penalties_applied.append("suboptimal zone position")
        grade = _downgrade(grade, 1)
        multiplier = ZONE_GRADE_MULTIPLIERS.get(grade, 0.35)
        score = ZONE_GRADE_SCORES.get(grade, 35)
    
    # ============================================================
    # PENALTY 5: Volume confirmation penalty (LESS AGGRESSIVE)
    # ============================================================
    if not volume_confirmed and grade == "A":
        penalties_applied.append("no volume confirmation")
        grade = "B"
        multiplier = ZONE_GRADE_MULTIPLIERS.get("B", 0.85)
        score = ZONE_GRADE_SCORES.get("B", 85)
    
    # ============================================================
    # Ensure score is NEVER 0
    # ============================================================
    if score <= 0:
        score = ZONE_GRADE_SCORES.get(grade, 35)
    
    if penalties_applied:
        reason = f"Penalties: {', '.join(penalties_applied)}"
        logger.debug(f"[ZONE_PENALTY] {zone_grade} → {grade}: {reason}")
    else:
        reason = f"No penalties applied ({zone_grade} grade maintained)"
    
    return grade, multiplier, score, reason


def _touch_quality(touch_count: int) -> float:
    """Touch count -> 0-1 sub-score, humped rather than monotonic.

    A level that has held once or twice is proven. A level touched eight
    times has had its resting liquidity consumed and is more likely to
    break than to hold. The old ladder scored the second case highest.
    """
    tc = max(0, int(touch_count or 0))
    return ZONE_TOUCH_QUALITY_CURVE.get(tc, ZONE_TOUCH_QUALITY_FLOOR)


def get_zone_quality_grade(
    touch_count: int,
    freshness: float = None,
    displacement: float = None,
    volume_quality: float = None,
) -> Tuple[str, float, int, Dict[str, Any]]:
    """
    ✅ Composite zone grade. Replaces grading on touch_count alone.

    freshness / displacement / volume_quality are 0-1. Any passed as None
    is EXCLUDED and the remaining weights are renormalised, so a caller
    that only knows the touch count gets a defensible grade instead of
    being penalised for missing inputs it was never given.

    Returns (grade, multiplier, score, breakdown) -- the breakdown so the
    payload can show WHY a zone graded as it did, which the old single-
    input version could never explain.
    """
    parts = {
        "touch": (_touch_quality(touch_count), ZONE_QUALITY_WEIGHTS["touch"]),
        "freshness": (freshness, ZONE_QUALITY_WEIGHTS["freshness"]),
        "displacement": (displacement, ZONE_QUALITY_WEIGHTS["displacement"]),
        "volume": (volume_quality, ZONE_QUALITY_WEIGHTS["volume"]),
    }
    live = {k: (max(0.0, min(1.0, float(v))), w)
            for k, (v, w) in parts.items() if v is not None}
    total_w = sum(w for _, w in live.values())
    if total_w <= 0:
        return "E", ZONE_GRADE_MULTIPLIERS["E"], ZONE_GRADE_SCORES["E"], {"reason": "no inputs"}

    composite = sum(v * w for v, w in live.values()) / total_w * 100.0

    grade = "E"
    for g in ("A", "B", "C", "D"):
        if composite >= ZONE_QUALITY_GRADE_THRESHOLDS[g]:
            grade = g
            break

    breakdown = {k: round(v, 3) for k, (v, _) in live.items()}
    breakdown["composite"] = round(composite, 1)
    breakdown["weights_used"] = {k: round(w / total_w, 3) for k, (_, w) in live.items()}
    breakdown["inputs_missing"] = [k for k in parts if k not in live]

    return grade, ZONE_GRADE_MULTIPLIERS.get(grade, 0.35), ZONE_GRADE_SCORES.get(grade, 35), breakdown


def get_zone_grade_and_size(touch_count: int) -> Tuple[str, float, int]:
    """
    ⚠️ LEGACY -- grades on touch_count alone. Superseded by
    get_zone_quality_grade(). Kept because external callers may still use
    it; do not wire new code to this.
    """
    effective_touch_count = min(touch_count, ZONE_MAX_TOUCHES_FOR_GRADE)
    
    if effective_touch_count >= ZONE_GRADE_THRESHOLDS["A"]:
        grade = "A"
    elif effective_touch_count >= ZONE_GRADE_THRESHOLDS["B"]:
        grade = "B"
    elif effective_touch_count >= ZONE_GRADE_THRESHOLDS["C"]:
        grade = "C"
    elif effective_touch_count >= ZONE_GRADE_THRESHOLDS["D"]:
        grade = "D"
    else:
        grade = "E"
    
    multiplier = ZONE_GRADE_MULTIPLIERS.get(grade, 0.35)
    score = ZONE_GRADE_SCORES.get(grade, 35)
    
    return grade, multiplier, score

# ============================================================
# ✅ FIXED: ZONE ADJUSTED SCORE - USES CONFIG VALUES
# ============================================================

def get_zone_adjusted_score(
    touch_count: int,
    volume_ratio: float,
    adx: float,
    spread_pips: float,
    pip_size: float = 0.001,
    zone_type: str = "DEMAND",
    range_high: float = None,
    range_low: float = None,
    zone_level: float = None,
    use_strict: bool = False,
    volume_confirmed: bool = False,
    freshness: float = None,
    displacement: float = None,
    volume_quality: float = None
) -> Tuple[str, float, int, str, Dict[str, Any]]:
    """Get comprehensive adjusted zone score with all penalties.

    ✅ volume_confirmed: apply_zone_penalties()'s PENALTY 5 demotes a
    grade-A zone to B when volume doesn't confirm it -- but this function
    had no such parameter and passed a hardcoded False straight through.
    That penalty therefore fired on EVERY grade-A zone unconditionally,
    making A unreachable: any zone that earned A was immediately demoted
    to B, permanently, with no input able to prevent it.

    It went unnoticed because nothing came close to A while the touch band
    was broken (touch_count was 0-1 on every payload for hours). Now that
    the band is ATR-scaled and counts are reaching 4, A is reachable and
    the ceiling would start to bite.

    Defaults to False, so passing nothing reproduces the old behaviour
    exactly.
    """
    quality_breakdown = None
    if use_strict:
        grade, multiplier, score = get_zone_grade_and_size_strict(touch_count)
    elif freshness is None and displacement is None and volume_quality is None:
        # No composite inputs supplied -- legacy touch-only path, so an
        # un-updated caller behaves exactly as before.
        grade, multiplier, score = get_zone_grade_and_size(touch_count)
    else:
        # ✅ Composite grade: freshness and displacement quality now count,
        # so a fresh zone price has just left decisively is no longer
        # rejected purely for being untested.
        grade, multiplier, score, quality_breakdown = get_zone_quality_grade(
            touch_count, freshness, displacement, volume_quality
        )
    
    details = {
        "quality_breakdown": quality_breakdown,
        "base_grade": grade,
        "base_multiplier": multiplier,
        "base_score": score,
        "touch_count": touch_count,
        "volume_ratio": volume_ratio,
        "adx": adx,
        "spread_pips": spread_pips
    }
    
    position_valid = True
    position_pct = 0.5
    position_reason = ""
    position_severity = 0.0
    
    if range_high is not None and range_low is not None and zone_level is not None:
        position_valid, position_reason, position_pct, position_severity = get_zone_position_validity(
            zone_level, range_high, range_low, zone_type
        )
        details["position_valid"] = position_valid
        details["position_pct"] = position_pct
        details["position_severity"] = position_severity
        details["position_reason"] = position_reason
    
    adjusted_grade, adjusted_multiplier, adjusted_score, penalty_reason = apply_zone_penalties(
        grade, volume_ratio, adx, touch_count, spread_pips, pip_size,
        position_valid, position_pct, volume_confirmed=volume_confirmed,
        position_severity=position_severity
    )
    
    details["volume_confirmed"] = volume_confirmed
    details["adjusted_grade"] = adjusted_grade
    details["adjusted_multiplier"] = adjusted_multiplier
    details["adjusted_score"] = adjusted_score
    details["penalty_reason"] = penalty_reason
    
    if adjusted_score <= 0:
        adjusted_score = ZONE_GRADE_SCORES.get(adjusted_grade, 35)
    
    if adjusted_grade != grade:
        logger.info(f"[ZONE_ADJUSTED] {grade} → {adjusted_grade}: {penalty_reason}")
    
    return adjusted_grade, adjusted_multiplier, adjusted_score, penalty_reason, details


def get_zone_recommendation(zone_grade: str, is_at_zone: bool, touch_count: int) -> Tuple[str, int]:
    """Get zone-based recommendation with confidence score."""
    if is_at_zone:
        if zone_grade == "A":
            return "IMMEDIATE_ENTRY", 98
        elif zone_grade == "B":
            return "IMMEDIATE_ENTRY", 95
        elif zone_grade == "C":
            return "BUY_OR_SELL", 80
        elif zone_grade == "D":
            if touch_count > 10:
                return "WAIT_FOR_RETEST", 65
            else:
                return "MONITOR", 50
        else:  # E
            return "MONITOR", 40
    else:
        if zone_grade == "A":
            return "WAIT_FOR_RETEST", 85
        elif zone_grade == "B":
            return "WAIT_FOR_RETEST", 75
        elif zone_grade == "C":
            return "WATCH", 55
        elif zone_grade == "D":
            if touch_count > 10:
                return "WATCH", 45
            else:
                return "MONITOR", 35
        else:  # E
            return "MONITOR", 30


# ============================================================
# RECOMMENDATION FUNCTIONS
# ============================================================

def get_ict_recommendation(ict_type: str, trend: str) -> Tuple[str, int]:
    """Get ICT recommendation based on signal type and trend."""
    if ict_type == "NONE":
        return "HOLD", 0
    
    if ict_type == "BULLISH":
        ict_direction = "BUY"
        base_score = 80
    elif ict_type == "BEARISH":
        ict_direction = "SELL"
        base_score = 80
    else:
        return "HOLD", 0
    
    if trend in ["STRONG_BEARISH", "BEARISH"] and ict_type == "BULLISH":
        return "HOLD", 0
    
    if trend in ["STRONG_BULLISH", "BULLISH"] and ict_type == "BEARISH":
        return "HOLD", 0
    
    return ict_direction, base_score


def get_sr_recommendation(is_breakout: bool, trend: str, current_price: float, pivot: float, volume_ratio: float = 1.0) -> Tuple[str, int]:
    """Get support/resistance recommendation."""
    if current_price > pivot:
        sr_bias = "BULLISH"
    elif current_price < pivot:
        sr_bias = "BEARISH"
    else:
        sr_bias = "NEUTRAL"
    
    if is_breakout:
        if volume_ratio >= 1.2:
            if trend in ["BULLISH", "STRONG_BULLISH"]:
                return "BREAKOUT_BUY", 85
            elif trend in ["BEARISH", "STRONG_BEARISH"]:
                return "BREAKOUT_SELL", 85
            else:
                return "BREAKOUT", 70
        else:
            if trend in ["BULLISH", "STRONG_BULLISH"]:
                return "BREAKOUT_WEAK_BUY", 40
            elif trend in ["BEARISH", "STRONG_BEARISH"]:
                return "BREAKOUT_WEAK_SELL", 40
            else:
                return "BREAKOUT_WEAK", 30
    
    if sr_bias == "BULLISH" and trend in ["BULLISH", "STRONG_BULLISH"]:
        return "BUY", 70
    elif sr_bias == "BEARISH" and trend in ["BEARISH", "STRONG_BEARISH"]:
        return "SELL", 70
    elif sr_bias == "BULLISH":
        return "WATCH_BULLISH", 40
    elif sr_bias == "BEARISH":
        return "WATCH_BEARISH", 40
    else:
        return "NEUTRAL", 0


# ============================================================
# MICRO-STRUCTURE ANALYSIS
# ============================================================

# Floor on how far from a zone the tape may sit and still count as
# absorbing AT it. The tolerance normally scales with the instrument's
# own absorption threshold; this stops that collapsing to nearly zero
# on a very tight instrument, where any real quote jitter would then
# read as "not at the zone" and absorption could never fire at all.
ABSORPTION_ZONE_TOLERANCE_MIN_PIPS = 3.0


def _get_absorption_threshold(symbol: str, pip_size: float) -> float:
    """Get instrument-specific absorption threshold in price units."""
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        threshold_pips = 10.0
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        threshold_pips = 8.0
    else:
        threshold_pips = 5.0
    return threshold_pips * pip_size


def _get_dynamic_min_activity(symbol: str, tick_frequency: float, default: int = 30) -> int:
    """Instrument-aware dynamic minimum activity."""
    symbol_upper = symbol.upper()
    
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        seconds_needed = MIN_ACTIVITY_SECONDS.get("XAUUSD", 5)
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        seconds_needed = MIN_ACTIVITY_SECONDS.get("XAGUSD", 4)
    else:
        seconds_needed = MIN_ACTIVITY_SECONDS.get("DEFAULT", 3)
    
    if tick_frequency > 0:
        dynamic_min = max(10, int(tick_frequency * seconds_needed))
        return dynamic_min
    return default


def _detect_spread_collapse(current_spread: float, avg_spread: float, pip_size: float, symbol: str = "EURUSD") -> Tuple[bool, str]:
    """Instrument-aware spread collapse detection."""
    symbol_upper = symbol.upper()
    
    avg_spread_pips = avg_spread / pip_size if pip_size > 0 else avg_spread
    current_spread_pips = current_spread / pip_size if pip_size > 0 else current_spread
    
    is_metal = "XAU" in symbol_upper or "XAG" in symbol_upper or "GOLD" in symbol_upper or "SILVER" in symbol_upper
    
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        absolute_threshold_pips = SPREAD_COLLAPSE_ABSOLUTE_THRESHOLD_PIPS.get("XAUUSD", 5.0)
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        absolute_threshold_pips = SPREAD_COLLAPSE_ABSOLUTE_THRESHOLD_PIPS.get("XAGUSD", 3.0)
    else:
        absolute_threshold_pips = SPREAD_COLLAPSE_ABSOLUTE_THRESHOLD_PIPS.get("DEFAULT", 0.5)
    
    if avg_spread_pips < absolute_threshold_pips:
        is_collapsed = current_spread <= avg_spread
        reason = f"Low spread regime ({symbol}): avg {avg_spread_pips:.2f}p - current {current_spread_pips:.2f}p <= avg"
        return is_collapsed, reason
    
    if is_metal:
        threshold_ratio = SPREAD_COLLAPSE_METALS_THRESHOLD
    else:
        threshold_ratio = SPREAD_COLLAPSE_PERCENTAGE_THRESHOLD
    
    threshold = avg_spread * threshold_ratio
    is_collapsed = current_spread < threshold
    reason = f"Current {current_spread_pips:.2f}p < {threshold_ratio*100:.0f}% of avg {avg_spread_pips:.2f}p"
    
    return is_collapsed, reason


def analyze_micro_structure(symbol: str, zone_level: float, current_price: float, order_type: str, probability: float = 50.0, pip_size: float = 0.01) -> Dict[str, Any]:
    """Full micro-structure analysis with instrument-aware thresholds."""
    try:
        ticks = mt5.copy_ticks_from(symbol, datetime.now(), 200, mt5.COPY_TICKS_ALL)
        
        if ticks is None or len(ticks) < 30:
            # ✅ FIXED: This was a SILENT fallback — timing_confidence was hardcoded
            # to 50 here with no logging at all, so it could fire on every single
            # call for every symbol and be indistinguishable from a real neutral
            # score. Now it's logged at WARNING so it's visible in normal output.
            tick_count = len(ticks) if ticks is not None else 0
            last_error = mt5.last_error() if hasattr(mt5, "last_error") else "unknown"
            logger.warning(
                f"[MICRO_STRUCTURE] {symbol}: FALLBACK timing_confidence=50 — "
                f"insufficient tick data ({tick_count}/30 min). mt5.last_error()={last_error}. "
                f"Symbol may be outside market hours, not subscribed, or lacking tick history."
            )
            return {
                "available": False,
                "reason": "Insufficient tick data",
                # ✅ FIXED: were 0 / 50 -- indistinguishable from a genuine
                # "had enough ticks, found nothing" result (entry_confidence
                # legitimately starts at 0 on the real path too; see below).
                # None signals "not computed" so a downstream consumer can
                # exclude this slot from any average instead of silently
                # blending in a fabricated neutral reading. Mirrors the
                # same fix already applied one layer up, at the
                # entry_result.timing_confidence call site in
                # asset_analysis.py (was default-50, now None + explicit
                # "N/A" handling).
                "entry_confidence": None,
                "absorption_detected": False,
                "momentum_burst": False,
                "spread_collapse": False,
                "iceberg_detected": False,
                "volume_imbalance_confirms": False,
                "volume_imbalance_direction": "UNKNOWN",
                "timing_confidence": None,
                "timing_ready": False,
                "triggers": [],
                "debug": {"ticks_received": tick_count, "minimum_required": 30}
            }
        
        tick_list = []
        bids = []
        asks = []
        timestamps = []
        
        for tick in ticks:
            if hasattr(tick, 'time'):
                tick_dict = {
                    "time": tick.time,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "last": tick.last,
                    "volume": tick.volume if hasattr(tick, 'volume') else 0,
                    "flags": tick.flags
                }
                if tick.bid and tick.bid > 0:
                    bids.append(tick.bid)
                if tick.ask and tick.ask > 0:
                    asks.append(tick.ask)
                timestamps.append(tick.time)
            else:
                tick_dict = {
                    "time": tick[0] if len(tick) > 0 else 0,
                    "bid": tick[1] if len(tick) > 1 else 0,
                    "ask": tick[2] if len(tick) > 2 else 0,
                    "last": tick[3] if len(tick) > 3 else 0,
                    "volume": tick[4] if len(tick) > 4 else 0,
                    "flags": tick[5] if len(tick) > 5 else 0
                }
                if tick_dict["bid"] > 0:
                    bids.append(tick_dict["bid"])
                if tick_dict["ask"] > 0:
                    asks.append(tick_dict["ask"])
                if tick_dict["time"] > 0:
                    timestamps.append(tick_dict["time"])
            tick_list.append(tick_dict)
        
        bid_tick_count = sum(1 for tick in tick_list if tick["flags"] & mt5.TICK_FLAG_BID)
        ask_tick_count = sum(1 for tick in tick_list if tick["flags"] & mt5.TICK_FLAG_ASK)
        
        total_volume = max(1, bid_tick_count + ask_tick_count)
        bid_volume = bid_tick_count
        ask_volume = ask_tick_count
        
        if len(timestamps) >= 2:
            time_span_seconds = timestamps[-1] - timestamps[0]
            tick_frequency = len(tick_list) / max(time_span_seconds, 1)
        else:
            tick_frequency = 0
        
        if bid_volume > 0:
            volume_imbalance = ask_volume / bid_volume
        elif ask_volume > 0:
            volume_imbalance = 100.0
        else:
            volume_imbalance = 1.0
        
        avg_tick_volume = total_volume / max(len(tick_list), 1)
        
        absorption_threshold_price = _get_absorption_threshold(symbol, pip_size)
        absorption_min_activity = _get_dynamic_min_activity(symbol, tick_frequency, 30)
        
        asks_filtered = [t["ask"] for t in tick_list if t["ask"] and t["ask"] > 0]
        if len(asks_filtered) >= 10:
            price_range = max(asks_filtered[-20:]) - min(asks_filtered[-20:]) if len(asks_filtered) >= 20 else max(asks_filtered) - min(asks_filtered)
            price_range_pips = price_range / pip_size if pip_size > 0 else 0
        else:
            price_range = absorption_threshold_price + 0.00001
            price_range_pips = 0
        
        price_stuck = price_range < absorption_threshold_price
        high_activity = total_volume > absorption_min_activity or tick_frequency > 5

        # Is the stalling happening AT THE ZONE, or just somewhere?
        #
        # zone_level and current_price were accepted by this function and
        # never referenced -- across all 345 lines of it. "Absorption"
        # means buyers are absorbing supply AT A LEVEL: the level is the
        # entire claim. Without it this detects "price went quiet while
        # ticks kept arriving", which happens constantly in thin hours
        # and at no particular price, and then reports it as evidence
        # for a setup at a zone it never looked at.
        #
        # It fed signal_count (a golden signal) and timing_confidence,
        # both of which gate entry, on 94% of decisions once the tick
        # archive made micro-structure live.
        #
        # Absent a zone the old behaviour is kept exactly: a missing
        # level is not evidence of distance, so inventing a rejection
        # would be as wrong as ignoring the parameter was.
        at_zone = True
        distance_to_zone_pips = None
        if zone_level and pip_size and pip_size > 0:
            reference = None
            if asks_filtered:
                reference = sum(asks_filtered[-20:]) / len(asks_filtered[-20:])
            elif current_price:
                reference = current_price
            if reference is not None:
                distance_to_zone_pips = abs(reference - zone_level) / pip_size
                # The zone is a band, not a line. Tolerance is the same
                # distance that counts as "stuck" plus a small buffer, so
                # a tape genuinely coiling at the level still qualifies
                # while one coiling 40 pips away does not.
                tolerance_pips = max(
                    ABSORPTION_ZONE_TOLERANCE_MIN_PIPS,
                    (absorption_threshold_price / pip_size) * 2.0)
                at_zone = distance_to_zone_pips <= tolerance_pips

        # bool(), not the raw numpy scalar. price_range comes from
        # numpy, so `price_stuck` is a np.bool_ and the conjunction
        # inherits it -- which silently breaks `is True` identity checks
        # in callers and can fail JSON serialisation on the way into a
        # replay record.
        absorption = bool(price_stuck and high_activity and at_zone)

        # ✅ FIXED: volume_imbalance (ask_volume/bid_volume, real
        # tape-level buy/sell aggression) was computed above and then
        # never read again anywhere in the codebase -- buried in the
        # "debug" sub-dict of this function's return value with no
        # consumer. `order_type` (this function's own parameter) is
        # already the direction being evaluated, so this turns it into
        # a real, actionable directional confirmation: a BUY needs
        # aggressive buying (ask-side ticks dominating), a SELL needs
        # aggressive selling (bid-side ticks dominating) -- gated on
        # high_activity so a thin handful of ticks can't produce a
        # misleadingly extreme ratio.
        if order_type and order_type.upper() == "BUY":
            volume_imbalance_confirms = bool(high_activity and volume_imbalance >= MICRO_STRUCTURE_VOLUME_IMBALANCE_CONFIRM_RATIO)
        elif order_type and order_type.upper() == "SELL":
            volume_imbalance_confirms = bool(high_activity and volume_imbalance <= (1.0 / MICRO_STRUCTURE_VOLUME_IMBALANCE_CONFIRM_RATIO))
        else:
            volume_imbalance_confirms = False

        if volume_imbalance >= MICRO_STRUCTURE_VOLUME_IMBALANCE_CONFIRM_RATIO:
            volume_imbalance_direction = "BUY_PRESSURE"
        elif volume_imbalance <= (1.0 / MICRO_STRUCTURE_VOLUME_IMBALANCE_CONFIRM_RATIO):
            volume_imbalance_direction = "SELL_PRESSURE"
        else:
            volume_imbalance_direction = "BALANCED"

        spreads = []
        for tick in tick_list:
            if tick["ask"] and tick["bid"] and tick["ask"] > 0 and tick["bid"] > 0:
                spread_val = abs(tick["ask"] - tick["bid"])
                spreads.append(spread_val)
        
        if spreads:
            avg_spread = sum(spreads) / len(spreads)
            current_spread_val = spreads[-1] if spreads else avg_spread
            spread_collapse, spread_collapse_reason = _detect_spread_collapse(current_spread_val, avg_spread, pip_size, symbol)
        else:
            avg_spread = 0
            current_spread_val = 0
            spread_collapse = False
            spread_collapse_reason = "No spread data"
        
        # ✅ FIXED: was `ticks_per_second > 10`, an absolute rate. Tick rate
        # is a property of the broker feed more than of the market -- live
        # XAGUSD ran 1.32-2.63 ticks/s, so this had never fired once.
        #
        # A burst is ACCELERATION. Comparing the second half of the tick
        # window against the first half asks whether activity is picking up
        # right now, which is the actual question, and needs no per-broker
        # calibration. The absolute floor stops a dead-quiet window
        # reporting a burst for going 0.1 -> 0.3 ticks/s.
        momentum_acceleration = None
        if len(timestamps) >= 2:
            time_span = timestamps[-1] - timestamps[0]
            ticks_per_second = len(timestamps) / max(time_span, 1)

            mid = len(timestamps) // 2
            first_span = timestamps[mid] - timestamps[0]
            second_span = timestamps[-1] - timestamps[mid]
            if mid >= 2 and first_span > 0 and second_span > 0:
                first_rate = mid / first_span
                second_rate = (len(timestamps) - mid) / second_span
                momentum_acceleration = second_rate / first_rate if first_rate > 0 else None
                momentum_burst = (
                    momentum_acceleration is not None
                    and momentum_acceleration >= MICRO_STRUCTURE_MOMENTUM_ACCELERATION
                    and second_rate >= MICRO_STRUCTURE_MOMENTUM_MIN_RATE
                )
            else:
                # Not enough ticks to split the window -- fall back to the
                # old absolute rule rather than guessing.
                momentum_burst = ticks_per_second > MICRO_STRUCTURE_MOMENTUM_THRESHOLD
        else:
            ticks_per_second = 0
            momentum_burst = False
        
        # ✅ avg_tick_volume is bid_tick_count + ask_tick_count divided by the
        # tick count, so it is bounded in [1.0, 2.0] BY CONSTRUCTION -- a
        # tick carries the BID flag, the ASK flag, or both. The threshold of
        # 5 is 2.5x that maximum, so this could never be True for any input.
        # It compares flag DENSITY to order SIZE, and MT5 tick_volume on
        # this feed is a tick count rather than traded volume, so the
        # quantity an iceberg would appear in simply isn't in the data.
        #
        # Reported as unavailable rather than False: "no iceberg detected"
        # is a claim this feed cannot support, and silently returning False
        # is what let it sit unnoticed. Retuning the number would make it
        # fire on noise instead of on icebergs.
        iceberg_available = avg_tick_volume > 2.0  # only true if the feed reports real volume
        iceberg_detected = (iceberg_available and
                           avg_tick_volume > MICRO_STRUCTURE_ICEBERG_MIN_VOLUME and
                           price_range_pips < MICRO_STRUCTURE_ICEBERG_MAX_PRANGE_PIPS and
                           len(tick_list) > MICRO_STRUCTURE_ICEBERG_MIN_TICKS)
        
        triggers = []
        entry_confidence = 0
        
        timing_confidence = 50
        if absorption:
            timing_confidence = max(timing_confidence, 85)
        if spread_collapse:
            timing_confidence = max(timing_confidence, 70)
        if momentum_burst:
            timing_confidence = max(timing_confidence, 65)
        if iceberg_detected:
            timing_confidence = max(timing_confidence, 60)
        if volume_imbalance_confirms:
            timing_confidence = max(timing_confidence, 65)
        
        timing_ready = timing_confidence >= MICRO_STRUCTURE_PROBABILITY_THRESHOLD
        
        if probability >= MICRO_STRUCTURE_PROBABILITY_THRESHOLD:
            if absorption:
                triggers.append({
                    "type": "ABSORPTION",
                    "what_it_means": f"Price stuck within {price_range_pips:.1f} pips with high activity",
                    "action": "ENTER ON NEXT UPTICK",
                    "confidence": 85
                })
                entry_confidence = max(entry_confidence, 85)
            
            if momentum_burst:
                triggers.append({
                    "type": "MOMENTUM_BURST",
                    "what_it_means": f"High tick velocity ({ticks_per_second:.1f} ticks/sec)",
                    "action": "ENTER ON BREAKOUT",
                    "confidence": 65
                })
                entry_confidence = max(entry_confidence, 65)
            
            if spread_collapse:
                triggers.append({
                    "type": "SPREAD_COLLAPSE",
                    "what_it_means": spread_collapse_reason,
                    "action": "ENTER NOW",
                    "confidence": 70
                })
                entry_confidence = max(entry_confidence, 70)
            
            if iceberg_detected:
                triggers.append({
                    "type": "ICEBERG",
                    "what_it_means": "Large volume with small price movement - hidden order detection",
                    "action": "MONITOR FOR ABSORPTION",
                    "confidence": 60
                })
                entry_confidence = max(entry_confidence, 60)

            if volume_imbalance_confirms:
                triggers.append({
                    "type": "VOLUME_IMBALANCE",
                    "what_it_means": (
                        f"Tape-level {volume_imbalance_direction.replace('_', ' ').lower()}: "
                        f"{'ask' if volume_imbalance_direction == 'BUY_PRESSURE' else 'bid'} volume "
                        f"{volume_imbalance:.2f}x the other side, confirming {order_type.upper()}"
                    ),
                    "action": "CONFIRMS DIRECTION",
                    "confidence": 65
                })
                entry_confidence = max(entry_confidence, 65)
        
        # ✅ Diagnostic trace for the REAL computation path — this lets you tell a
        # genuine "no signals detected, neutral 50" apart from the FALLBACK 50
        # cases above (which are now tagged with "FALLBACK" and logged as WARNING).
        logger.debug(
            f"[MICRO_STRUCTURE] {symbol}: REAL timing_confidence={timing_confidence} "
            f"(absorption={absorption}, spread_collapse={spread_collapse}, "
            f"momentum_burst={momentum_burst}, iceberg={iceberg_detected}, "
            f"ticks={len(tick_list)}, tick_freq={tick_frequency:.2f}/s)"
        )
        
        return {
            "available": True,
            "entry_confidence": entry_confidence,
            "absorption_detected": absorption,
            "iceberg_detected": iceberg_detected,
            # ✅ False here means "this feed reports tick COUNTS, not traded
            # volume, so an iceberg is not detectable from it" -- distinct
            # from iceberg_detected=False meaning "looked, found none".
            "iceberg_available": iceberg_available,
            "momentum_burst": momentum_burst,
            # ✅ second-half tick rate / first-half tick rate. None when the
            # window was too short to split.
            "momentum_acceleration": round(momentum_acceleration, 2) if momentum_acceleration else None,
            "spread_collapse": spread_collapse,
            # ✅ NEW: promoted out of "debug" -- volume_imbalance itself
            # (the raw ask/bid ratio) was already in debug and stays
            # there too for backward compatibility, but the actionable
            # boolean/label derived from it now live at the top level
            # alongside the other three tape-level signals.
            "volume_imbalance_confirms": volume_imbalance_confirms,
            "volume_imbalance_direction": volume_imbalance_direction,
            "timing_confidence": timing_confidence,
            "timing_ready": timing_ready,
            "triggers": triggers,
            "debug": {
                "tick_frequency": round(tick_frequency, 2),
                "ticks_per_second": round(ticks_per_second, 2),
                "bid_volume": bid_volume,
                "ask_volume": ask_volume,
                "total_volume": total_volume,
                "volume_imbalance": round(volume_imbalance, 2),
                "avg_tick_volume": round(avg_tick_volume, 2),
                "spreads": {
                    "current_spread_pips": round(current_spread_val / pip_size, 1) if pip_size > 0 else 0,
                    "avg_spread_pips": round(avg_spread / pip_size, 2) if pip_size > 0 else 0,
                    "spread_collapse_triggered": spread_collapse
                }
            }
        }
        
    except Exception as e:
        logger.error(f"[MICRO_STRUCTURE] {symbol}: FALLBACK timing_confidence=50 — exception: {e}", exc_info=True)
        return {
            "available": False,
            "reason": f"Error: {str(e)}",
            # ✅ FIXED: same reasoning as the insufficient-tick-data branch
            # above -- None instead of a fabricated 0/50 neutral reading.
            "entry_confidence": None,
            "absorption_detected": False,
            "momentum_burst": False,
            "spread_collapse": False,
            "iceberg_detected": False,
            "volume_imbalance_confirms": False,
            "volume_imbalance_direction": "UNKNOWN",
            "timing_confidence": None,
            "timing_ready": False,
            "triggers": [],
            "debug": {"error": str(e)}
        }


# ============================================================
# RESET FUNCTIONS FOR TESTING
# ============================================================

def reset_volume_warning_flag():
    """Reset the global volume warning flag."""
    global _VOLUME_WARNING_LOGGED
    with _VOLUME_WARNING_LOCK:
        _VOLUME_WARNING_LOGGED = False


def reset_tick_volume_warning_per_symbol(symbol: str = None):
    """Reset tick volume warning for a specific symbol or all symbols."""
    with _TICK_VOLUME_LOCK:
        if symbol:
            _TICK_VOLUME_WARNING_LOGGED_PER_SYMBOL.pop(symbol, None)
        else:
            _TICK_VOLUME_WARNING_LOGGED_PER_SYMBOL.clear()


# ============================================================
# MACD SCORING HELPER - ✅ FIXED FOR FAST MACD
# ============================================================

def _score_macd_with_recovery(
    macd_line: float, 
    signal_line: float, 
    histogram: float, 
    prev_histogram: float,
    macd_signal: str,
    trend_strength: float = 0
) -> Dict[str, Any]:
    """Score MACD with recovery detection."""
    confidence = 40
    recommendation = "NEUTRAL"
    score = 0
    reason = "MACD neutral"
    
    hist_improving = histogram > prev_histogram if prev_histogram is not None else False
    
    is_recovering = False
    if macd_line < signal_line and hist_improving:
        is_recovering = True
    
    if is_recovering:
        diff = abs(macd_line - signal_line)
        if diff < 0.0005:
            confidence = 60
            recommendation = "NEUTRAL"
            score = -3
            reason = f"MACD recovering (near crossover, diff={diff:.6f})"
        elif diff < 0.001:
            confidence = 55
            recommendation = "NEUTRAL"
            score = -5
            reason = f"MACD bearish but recovering (diff={diff:.6f})"
        else:
            confidence = 50
            recommendation = "NEUTRAL"
            score = -8
            reason = f"MACD bearish but slowly improving (diff={diff:.6f})"
        
        if trend_strength > 50:
            score = score * 0.6
            confidence = confidence * 0.7
            reason += " (reduced weight in strong trend)"
        
        return {
            "confidence": confidence,
            "recommendation": recommendation,
            "score": score,
            "reason": reason,
            "is_recovering": True,
            "hist_improving": hist_improving
        }
    
    if macd_signal in ["BULLISH", "NEUTRAL_BULLISH"]:
        if histogram > 0:
            if macd_line > signal_line * 1.5 and histogram > 0.001:
                confidence = 80
                recommendation = "BUY"
                score = 20
                reason = f"Strong BULLISH MACD (line={macd_line:.6f}, hist={histogram:.6f})"
            elif macd_line > signal_line and histogram > 0.0005:
                confidence = 65
                recommendation = "BUY"
                score = 15
                reason = f"BULLISH MACD (line > signal, hist={histogram:.6f})"
            else:
                confidence = 50
                recommendation = "BUY"
                score = 10
                reason = "Weak BULLISH MACD"
        else:
            if abs(histogram) < 0.0005:
                confidence = 45
                recommendation = "NEUTRAL"
                score = 5
                reason = "MACD near crossover"
            else:
                confidence = 40
                recommendation = "NEUTRAL"
                score = 3
                reason = "MACD bullish but losing momentum"
    
    elif macd_signal in ["BEARISH", "NEUTRAL_BEARISH"]:
        if histogram < 0:
            if macd_line < signal_line * 0.5 and histogram < -0.001:
                confidence = 80
                recommendation = "SELL"
                score = -20
                reason = f"Strong BEARISH MACD (line={macd_line:.6f}, hist={histogram:.6f})"
            elif macd_line < signal_line and histogram < -0.0005:
                confidence = 65
                recommendation = "SELL"
                score = -15
                reason = f"BEARISH MACD (line < signal, hist={histogram:.6f})"
            else:
                confidence = 50
                recommendation = "SELL"
                score = -10
                reason = "Weak BEARISH MACD"
        else:
            if abs(histogram) < 0.0005:
                confidence = 45
                recommendation = "NEUTRAL"
                score = -5
                reason = "MACD near crossover"
            else:
                confidence = 40
                recommendation = "NEUTRAL"
                score = -3
                reason = "MACD bearish but losing momentum"
    
    else:
        if abs(macd_line - signal_line) < 0.0005:
            confidence = 50
            recommendation = "NEUTRAL"
            score = 0
            reason = "MACD at crossover, key decision point"
        else:
            confidence = 40
            recommendation = "NEUTRAL"
            score = 0
            reason = "MACD neutral"
    
    if trend_strength > 50:
        score = score * 0.6
        confidence = confidence * 0.7
        reason += " (reduced weight in strong trend)"
    
    return {
        "confidence": confidence,
        "recommendation": recommendation,
        "score": score,
        "reason": reason,
        "is_recovering": False,
        "hist_improving": hist_improving
    }


def _score_macd(macd_line: float, signal_line: float, histogram: float, macd_signal: str) -> Dict[str, Any]:
    """Legacy MACD scoring."""
    result = _score_macd_with_recovery(
        macd_line, signal_line, histogram, None, macd_signal, 0
    )
    return {
        "confidence": result["confidence"],
        "recommendation": result["recommendation"],
        "score": result["score"],
        "reason": result["reason"]
    }


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _get_divergence_lookback(timeframe: str = "M1") -> int:
    return DIVERGENCE_LOOKBACK.get(timeframe.upper(), DEFAULT_DIVERGENCE_LOOKBACK)


def _get_swing_window(timeframe: str, lookback_bars: int) -> int:
    tf_upper = timeframe.upper()
    if tf_upper == "M1":
        return 3
    elif tf_upper in ["M5", "M15"]:
        return 5
    elif tf_upper in ["M30", "H1"]:
        return 8
    else:
        return max(5, int(lookback_bars * 0.1))


def _get_ema_min_separation(symbol: str, pip_size: float) -> float:
    return get_ema_min_separation_pips(symbol) * pip_size


def _get_wyckoff_spike_threshold(symbol: str) -> float:
    symbol_upper = symbol.upper()
    for key in WYCKOFF_SPIKE_THRESHOLDS:
        if key in symbol_upper:
            return WYCKOFF_SPIKE_THRESHOLDS[key]
    return WYCKOFF_SPIKE_THRESHOLDS["DEFAULT"]


def _get_momentum_threshold(symbol: str) -> float:
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        return MOMENTUM_THRESHOLDS["XAUUSD"]
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        return MOMENTUM_THRESHOLDS["XAGUSD"]
    else:
        return MOMENTUM_THRESHOLDS["DEFAULT"]


def _get_zone_touch_distance(symbol: str, pip_size: float, timeframe: str = "M1", atr_pips: float = None) -> float:
    """
    ✅ FIXED: touch distance now scales with timeframe, not just symbol.
    The old flat pip distance (e.g. 2.0 pips for EURUSD) applied equally
    to M1 and H1. On M1, where ATR can be a fraction of a pip, a 2-pip
    tolerance band is several times the average bar range — virtually any
    quiet consolidation saturates touch_count toward the grading cap
    regardless of whether the zone is genuinely significant. On H1 the
    same band is comparatively tight and appropriately selective. Scale
    it down on lower timeframes so "touched" means something similar in
    ATR terms across timeframes.
    """
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        distance_pips = ZONE_TOUCH_DISTANCE_PIPS["XAUUSD"]
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        distance_pips = ZONE_TOUCH_DISTANCE_PIPS["XAGUSD"]
    else:
        distance_pips = ZONE_TOUCH_DISTANCE_PIPS["DEFAULT"]

    tf_multiplier = ZONE_TOUCH_DISTANCE_TF_MULTIPLIER.get((timeframe or "M1").upper(), 1.0)
    band_pips = distance_pips * tf_multiplier

    # ✅ FIXED: the band above is absolute pips and does not scale with how
    # much the instrument actually moves. XAGUSD M1 resolves to 1.25 pips
    # against a live ATR of 24-66 pips -- a touch had to land inside ~2-5%
    # of one bar's average range. touch_count came back 0 or 1 on every
    # payload, and because grade derives ENTIRELY from touch_count, every
    # zone graded E and every bar ended "SKIP - INVALID ZONE".
    #
    # Floored at a fraction of ATR so "touched" means something comparable
    # across instruments. Never SHRINKS the band -- max(), not replace --
    # so an instrument the table already suits is unaffected.
    # ✅ (2026-09-15) ATR known -> the ATR fraction alone. max() kept the
    # 2-pip table value on currency pairs, a 2-ATR "touch" band.
    if atr_pips and atr_pips > 0:
        band_pips = atr_pips * ZONE_TOUCH_ATR_FRACTION

    return band_pips * pip_size


def _get_adx_thresholds(symbol: str) -> Dict[str, int]:
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        base = ADX_THRESHOLDS["XAUUSD"]
        extreme = ADX_EXTREME_THRESHOLDS["XAUUSD"]
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        base = ADX_THRESHOLDS["XAGUSD"]
        extreme = ADX_EXTREME_THRESHOLDS["XAGUSD"]
    else:
        base = ADX_THRESHOLDS["DEFAULT"]
        extreme = ADX_EXTREME_THRESHOLDS["DEFAULT"]
    return {**base, "extreme": extreme}


def _get_zone_time_decay_config(symbol: str) -> Dict[str, float]:
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        return ZONE_TIME_DECAY_CONFIG["XAUUSD"]
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        return ZONE_TIME_DECAY_CONFIG["XAGUSD"]
    else:
        return ZONE_TIME_DECAY_CONFIG["DEFAULT"]


def _get_min_bars_for_trend(timeframe: str) -> int:
    return MIN_BARS_FOR_TREND.get(timeframe.upper(), MIN_BARS_FOR_TREND["DEFAULT"])


def _get_zone_lookback_bars(timeframe: str) -> int:
    return ZONE_LOOKBACK_BARS.get(timeframe.upper(), ZONE_LOOKBACK_BARS["DEFAULT"])


def _get_wyckoff_lookback_bars(timeframe: str) -> int:
    return WYCKOFF_LOOKBACK_BARS.get(timeframe.upper(), WYCKOFF_LOOKBACK_BARS["DEFAULT"])


def _extract_price_arrays(rates: np.ndarray) -> Dict[str, Any]:
    if rates is None or len(rates) == 0:
        return {"high": [], "low": [], "close": [], "volume": [], "time": []}
    
    return {
        "high": [float(r[2]) for r in rates],
        "low": [float(r[3]) for r in rates],
        "close": [float(r[4]) for r in rates],
        "volume": [float(r[5]) for r in rates],
        "time": [int(r[0]) for r in rates]
    }


def _find_swing_points(rates: np.ndarray, use_high: bool = True, lookback_bars: int = None, timeframe: str = "M1", pip_size: float = None) -> Tuple[List[float], List[int]]:
    """Find swing highs/lows for zone-level candidates.

    ✅ Delegates to core/swing_points.py — the single shared swing
    detector also used by patterns.py's Elliott Wave detection. The old
    local version here had NO amplitude filter at all: every 5-bar pivot
    counted regardless of size, so on M1 (where ATR can be a fraction of
    a pip) sub-pip noise was accepted as a legitimate zone candidate.
    Now timeframe-aware, matching the same min-swing-size table used for
    pattern detection.

    ✅ pip_size: the min-swing table is expressed in PIPS and has to be
    converted against the instrument's own pip size. Omitting it falls
    back to the 5-decimal-FX assumption, which is ~10x too permissive on
    metals and ~100x on JPY pairs and equities -- i.e. the filter this
    docstring describes stops filtering anything.
    """
    if rates is None or len(rates) < 10:
        return [], []
    lookback = lookback_bars if lookback_bars else 5
    min_amp = get_min_swing_size(timeframe, pip_size)
    return find_swing_points_ohlc(rates, use_high=use_high, lookback=lookback, min_amplitude=min_amp)


def _find_swing_points_detailed(data: List[float], lookback: int = 3) -> Dict[str, List[Tuple[int, float]]]:
    """Find swing highs/lows for oscillator divergence detection (RSI/Stochastic).

    ✅ Delegates to core/swing_points.py. No amplitude filter here (matches
    prior behavior) — oscillator swings are already bounded 0-100, so the
    same pip-based filter used for price series doesn't apply.
    """
    raw = find_swing_points(data, lookback=lookback, min_amplitude=0.0)
    highs = [(p['index'], p['price']) for p in raw if p['type'] == 'high']
    lows = [(p['index'], p['price']) for p in raw if p['type'] == 'low']
    return {'highs': highs, 'lows': lows}


# ✅ Last composite quality breakdown per zone, so the payload can show
# WHY a zone graded as it did. _detect_supply_demand_zone returns a fixed
# 6-tuple that external callers unpack positionally, so widening it would
# break them; this is the same accessor pattern already used for touch
# counts. Bounded to avoid unbounded growth across symbols/zones.
_zone_quality_breakdowns = {}
_ZONE_QUALITY_CACHE_MAX = 500


def _zone_key(zone_level, zone_type, symbol=None):
    return f"{symbol or ''}|{round(zone_level, 5)}_{zone_type}"


def _record_zone_quality(zone_level, zone_type, breakdown, symbol=None):
    if breakdown is None or zone_level is None:
        return
    if len(_zone_quality_breakdowns) > _ZONE_QUALITY_CACHE_MAX:
        _zone_quality_breakdowns.clear()
    _zone_quality_breakdowns[_zone_key(zone_level, zone_type, symbol)] = breakdown


def get_zone_quality_breakdown(zone_level, zone_type, symbol=None):
    """The inputs that produced this zone's grade (touches, age, freshness,
    displacement and the composite), from the last detection of this zone
    for this symbol."""
    if zone_level is None:
        return None
    return _zone_quality_breakdowns.get(_zone_key(zone_level, zone_type, symbol))


def get_effective_zone_touch_count(
    zone_level: float,
    zone_type: str,
    rates,
    symbol: str,
    pip_size: float,
    timeframe: str = "M1",
    atr_pips: float = None,
) -> int:
    """The touch count that produced the zone grade: the one detection
    measured for this symbol's zone (visits since the swing formed)."""
    if zone_level is None or not zone_type:
        return 0
    facts = get_zone_quality_breakdown(zone_level, zone_type, symbol) or {}
    if "touch_count" in facts:
        return int(facts["touch_count"])
    try:
        touch_distance = _get_zone_touch_distance(symbol, pip_size, timeframe, atr_pips)
        return _calculate_initial_touch_count(rates, zone_level, touch_distance, zone_type)
    except (IndexError, TypeError, ValueError, KeyError) as e:
        logger.debug(f"[ZONE] effective touch count unavailable: {e}")
        return 0


def _calculate_initial_touch_count(
    rates: np.ndarray,
    zone_level: float,
    touch_distance: float,
    zone_type: str = None,
) -> int:
    """
    How many times price has come to this zone in the recent window.

    ✅ FIXED, two defects:

    1. It read r[3] -- the bar LOW -- for every zone regardless of type.
       Price touches a SUPPLY zone (resistance, above price) with its
       HIGH; requiring the LOW to reach it means the zone only counts a
       touch once price has traded clean THROUGH it, which is precisely
       when the zone stops mattering. Supply zones were structurally
       undercounted.

    2. It counted BARS, not touch events. A quiet stretch parked inside
       the band added one "touch" per bar, so the same single visit could
       register 40 times. Harmless while the band was too narrow to ever
       trigger, but it becomes an over-count the moment the band is
       widened to a sane size -- which the ATR floor above now does. A
       run of consecutive bars inside the band is one touch.
    """
    touch_count = 0
    was_inside = False

    zt = (zone_type or "").upper()
    for r in rates[-100:]:
        high, low = float(r[2]), float(r[3])
        if zt == "SUPPLY":
            probe = high
        elif zt == "DEMAND":
            probe = low
        else:
            # Unknown type: the bar counts if its RANGE reaches the level,
            # which is the type-agnostic reading and never worse than
            # picking the wrong single column.
            probe = None

        if probe is None:
            inside = (low - touch_distance) <= zone_level <= (high + touch_distance)
        else:
            inside = abs(probe - zone_level) <= touch_distance

        if inside and not was_inside:
            touch_count += 1
        was_inside = inside

    return min(touch_count, ZONE_MAX_TOUCHES_FOR_GRADE)


# ============================================================
# VOLUME PROFILE / POINT OF CONTROL
# ============================================================

def calculate_volume_profile(
    rates: np.ndarray,
    num_bins: int,
    lookback_bars: int,
    value_area_pct: float,
) -> Dict[str, Any]:
    """
    Build a volume profile from the last `lookback_bars` bars: each bar's
    volume is distributed across the price bins its high-low range
    touches (not just dumped on its close), then:
    - POC (Point of Control): the single bin with the most volume
    - Value Area: the tightest contiguous band of bins containing
      `value_area_pct` of total volume, built by expanding outward from
      the POC bin and always adding whichever neighbor (above/below) has
      more volume — the standard volume-profile construction.
    """
    price_arrays = _extract_price_arrays(rates)
    highs = price_arrays["high"][-lookback_bars:]
    lows = price_arrays["low"][-lookback_bars:]
    volumes = price_arrays["volume"][-lookback_bars:]

    if not highs or not lows or not volumes or len(highs) < 5:
        return {"available": False, "reason": "Insufficient bar data for volume profile"}

    range_high = max(highs)
    range_low = min(lows)
    if range_high <= range_low:
        return {"available": False, "reason": "Degenerate price range (no volatility in lookback window)"}

    bin_size = (range_high - range_low) / num_bins
    bin_volumes = [0.0] * num_bins

    for h, l, v in zip(highs, lows, volumes):
        if v <= 0:
            continue
        bar_high = min(h, range_high)
        bar_low = max(l, range_low)
        if bar_high <= bar_low:
            idx = min(num_bins - 1, max(0, int((bar_high - range_low) / bin_size)))
            bin_volumes[idx] += v
            continue
        start_idx = max(0, min(num_bins - 1, int((bar_low - range_low) / bin_size)))
        end_idx = max(0, min(num_bins - 1, int((bar_high - range_low) / bin_size)))
        span_bins = max(1, end_idx - start_idx + 1)
        per_bin = v / span_bins
        for idx in range(start_idx, end_idx + 1):
            bin_volumes[idx] += per_bin

    total_volume = sum(bin_volumes)
    if total_volume <= 0:
        return {"available": False, "reason": "No volume data in lookback window"}

    poc_idx = max(range(num_bins), key=lambda i: bin_volumes[i])
    poc_price = range_low + (poc_idx + 0.5) * bin_size

    low_idx, high_idx = poc_idx, poc_idx
    included_volume = bin_volumes[poc_idx]
    target_volume = total_volume * value_area_pct

    while included_volume < target_volume and (low_idx > 0 or high_idx < num_bins - 1):
        next_low_vol = bin_volumes[low_idx - 1] if low_idx > 0 else -1.0
        next_high_vol = bin_volumes[high_idx + 1] if high_idx < num_bins - 1 else -1.0
        if next_high_vol >= next_low_vol:
            high_idx += 1
            included_volume += bin_volumes[high_idx]
        else:
            low_idx -= 1
            included_volume += bin_volumes[low_idx]

    vah_price = range_low + (high_idx + 1) * bin_size
    val_price = range_low + low_idx * bin_size

    return {
        "available": True,
        "poc": round(poc_price, 5),
        "vah": round(vah_price, 5),
        "val": round(val_price, 5),
        "range_high": round(range_high, 5),
        "range_low": round(range_low, 5),
        "bin_size": round(bin_size, 5),
        "total_volume": round(total_volume, 1),
        "value_area_volume_pct": round(included_volume / total_volume, 3) if total_volume > 0 else 0,
        "num_bins": num_bins,
        "lookback_bars": len(highs),
    }


# ============================================================
# ABC CORRECTION / WAVE C FIBONACCI PROJECTION
# ============================================================

def detect_abc_correction(
    rates: np.ndarray,
    min_retracement_b: float,
    max_retracement_b: float,
    ideal_retracement_min: float,
    ideal_retracement_max: float,
    fib_equality: float,
    fib_extension: float,
    timeframe: str = "M1",
    pip_size: float = None,
) -> Dict[str, Any]:
    """
    Standalone A-B-C corrective wave detector, built from the shared
    swing-point detector (find_swing_points — the same one patterns.py's
    Elliott Wave engine uses), NOT from patterns.py itself (that module
    only exposes wave labels, not the price points needed for a
    Fibonacci projection).

    Finds the most recent 3 alternating swing pivots:
    - point0 -> point1 = wave A
    - point1 -> point2 = wave B (the retracement of wave A)
    Validates wave B's retracement falls in a plausible corrective range,
    then projects wave C's Fibonacci targets (100% and 161.8% of wave
    A's length) from point2, in wave A's original direction — the
    standard "C often equals A, sometimes extends to 1.618x A" rule.

    ✅ FIXED: this used to build its pivot list from TWO INDEPENDENT
    scans -- find_swing_points_ohlc(..., use_high=True) and again with
    use_high=False -- each amplitude-filtered only against prior pivots
    of its OWN type, then merged by bar index and deduplicated for
    consecutive same-type entries only. Nothing ever validated that two
    ADJACENT pivots of DIFFERENT types (a high next to a low in the
    merged list) were actually part of one coherent swing: a high pivot
    and a low pivot could each independently clear their own type's
    amplitude filter yet coincidentally land at nearly the same PRICE
    despite being dozens of bars apart in time, since each was only ever
    compared to prior points of its own type. That produces a
    near-zero-length "wave A" denominator, and dividing a perfectly
    normal wave B by it is exactly how this was producing retracements
    of 300%, 1000%, even 2500%+ -- verified directly by reproducing a
    2545% retracement from a high and low 62 bars apart that happened to
    sit 0.06 pips from each other. This was most likely to bite in
    exactly the low-ADX, choppy conditions where wave-count analysis
    gets used most, which is consistent with it showing up repeatedly in
    practice rather than as a rare fluke.

    Fixed by building the pivot list from ONE unified, single-pass scan
    (find_swing_points over close prices) instead -- the same function
    patterns.py's Elliott Wave detectors use, which checks amplitude
    against the last ACCEPTED pivot of EITHER type, guaranteeing every
    adjacent pair in the result -- high-to-low or otherwise -- is
    genuinely separated and represents one coherent zigzag. This also
    means point0/point1/point2 can no longer disagree with what
    patterns.py's own corrective-wave detectors see, since both now read
    the same swing structure the same way.
    """
    closes = [float(r[4]) for r in rates] if rates is not None else []
    min_amp = get_min_swing_size(timeframe, pip_size)
    raw_pivots = find_swing_points(closes, lookback=2, min_amplitude=min_amp)

    if len(raw_pivots) < 3:
        return {"available": False, "reason": "Not enough swing pivots to form an A-B-C structure"}

    # find_swing_points already enforces amplitude against the last
    # accepted point of EITHER type in a single pass, so consecutive
    # entries already alternate high/low by construction -- no separate
    # zigzag-dedup pass needed (unlike the old two-independent-scans
    # version, which required one to paper over the cross-type gap the
    # independent scans left open).
    zigzag = [(p['index'], p['price'], 'H' if p['type'] == 'high' else 'L') for p in raw_pivots]

    # ✅ FIXED: this used to always take zigzag[-3], zigzag[-2], zigzag[-1]
    # -- the exact same rigid-trailing-window bug already found and fixed
    # in patterns.py's two sibling corrective-wave detectors. The instant
    # one small new pivot confirms after a real, valid A-B-C completes --
    # ordinary market behavior, not an edge case -- that window slides
    # past the correction and it becomes invisible even though it's still
    # sitting right there a pivot or two back. Searches backward through
    # a bounded recent window (6 candidates) for the most recent
    # combination that actually validates, instead of only ever checking
    # the literal tail.
    found = None
    max_candidates = min(6, len(zigzag) - 2)
    for offset in range(max_candidates):
        end = len(zigzag) - offset
        start = end - 3
        cand0, cand1, cand2 = zigzag[start], zigzag[start + 1], zigzag[start + 2]
        if cand0[2] != cand2[2] or cand1[2] == cand0[2]:
            continue
        cand_a_len = abs(cand1[1] - cand0[1])
        if cand_a_len <= 0:
            continue
        cand_ratio = abs(cand2[1] - cand1[1]) / cand_a_len
        if min_retracement_b <= cand_ratio <= max_retracement_b:
            found = (cand0, cand1, cand2)
            break

    if found is None:
        return {"available": False, "reason": "No recent 3-pivot sequence forms a valid A-B-C structure in range"}

    point0_idx, point0_price, point0_type = found[0]
    point1_idx, point1_price, point1_type = found[1]
    point2_idx, point2_price, point2_type = found[2]

    wave_a_length = abs(point1_price - point0_price)
    wave_b_length = abs(point2_price - point1_price)
    wave_b_retracement = wave_b_length / wave_a_length

    # point0 is a High -> wave A moved DOWN (H->L); point0 is a Low -> wave A moved UP (L->H)
    correction_direction = "DOWN" if point0_type == "H" else "UP"
    reversal_direction = "BUY" if correction_direction == "DOWN" else "SELL"
    c_sign = -1 if correction_direction == "DOWN" else 1

    target_c_100 = point2_price + c_sign * wave_a_length * fib_equality
    target_c_161 = point2_price + c_sign * wave_a_length * fib_extension

    is_ideal_b = ideal_retracement_min <= wave_b_retracement <= ideal_retracement_max

    return {
        "available": True,
        "correction_direction": correction_direction,
        "reversal_direction": reversal_direction,
        "point0": {"price": round(point0_price, 5), "bar_index": point0_idx, "type": point0_type},
        "point1": {"price": round(point1_price, 5), "bar_index": point1_idx, "type": point1_type},
        "point2": {"price": round(point2_price, 5), "bar_index": point2_idx, "type": point2_type},
        "wave_a_length": round(wave_a_length, 5),
        "wave_b_retracement_pct": round(wave_b_retracement, 3),
        "is_ideal_b_retracement": is_ideal_b,
        "target_c_100": round(target_c_100, 5),
        "target_c_161": round(target_c_161, 5),
    }


# ============================================================
# FVG DETECTION
# ============================================================

FVG_MAX_AGE_BARS = 75          # grace 25 + decay 50 in asset_analysis_smc: older gaps carry no weight
FVG_MIN_WIDTH_ATR = 0.10       # a gap narrower than this is quote noise


def _detect_fvg(rates: np.ndarray, atr_price: float = None) -> Tuple[str, Optional[float], Optional[float], Optional[float], Optional[int]]:
    """The most recent 3-candle fair value gap that price has NOT filled.

    ✅ FIXED (2026-09-15), three defects:
      * the scan started at len(rates) - 5, so the four newest bars -- the
        freshest gaps -- were never examined;
      * the newest gap anywhere in the 1000-bar window was returned even when
        later bars had already traded through it, so "ICT type" described a
        gap that no longer existed and was set on 93% of study bars;
      * no size floor relative to volatility.
    A bullish gap is filled once a later low reaches its bottom; a bearish gap
    once a later high reaches its top.
    """
    n = len(rates)
    min_width = (atr_price or 0.0) * FVG_MIN_WIDTH_ATR
    for i in range(n - 1, max(2, n - FVG_MAX_AGE_BARS) - 1, -1):
        left_high, left_low = float(rates[i - 2][2]), float(rates[i - 2][3])
        right_high, right_low = float(rates[i][2]), float(rates[i][3])
        if left_high < right_low:
            gap_type, gap_high, gap_low = "BULLISH", right_low, left_high
        elif right_high < left_low:
            gap_type, gap_high, gap_low = "BEARISH", left_low, right_high
        else:
            continue
        if gap_high - gap_low < min_width:
            continue
        later = rates[i + 1:]
        if gap_type == "BULLISH" and any(float(r[3]) <= gap_low for r in later):
            continue
        if gap_type == "BEARISH" and any(float(r[2]) >= gap_high for r in later):
            continue
        age = n - i
        level = gap_high if gap_type == "BULLISH" else gap_low
        return gap_type, round(gap_high, 5), round(gap_low, 5), round(level, 5), age
    return "NONE", None, None, None, None


def detect_all_fvgs(
    rates: np.ndarray,
    max_gaps: int,
    lookback_bars: int,
    mitigation_full_threshold: float,
) -> List[Dict[str, Any]]:
    """
    Finds ALL 3-candle Fair Value Gaps within the lookback window — not
    just the single nearest one _detect_fvg() returns — and tracks each
    gap's mitigation history:

    - mitigation_pct: how far subsequent price wicks have traded INTO
      the gap (0 = untouched, 1.0 = fully filled).
    - is_mitigated: mitigation_pct >= mitigation_full_threshold.
    - is_inverse_fvg (IFVG): a full candle CLOSE (not just a wick) has
      traded through the FAR side of the gap — the gap failed to hold
      as support/resistance entirely, which in ICT terms means it's
      expected to flip and act as the OPPOSITE polarity zone on a
      future retest (a bullish FVG that gets closed below becomes
      resistance; a bearish FVG closed above becomes support).

    Returns active gaps only (unmitigated, OR mitigated-but-inverted —
    an inverted gap is a live opposite-polarity zone even though the
    original gap is used up), newest first, capped at max_gaps.
    """
    n = len(rates)
    if n < 5:
        return []

    start_i = max(2, n - lookback_bars)
    raw_gaps = []

    for i in range(start_i, n):
        left_high = float(rates[i - 2][2])
        left_low = float(rates[i - 2][3])
        right_high = float(rates[i][2])
        right_low = float(rates[i][3])

        if left_high < right_low:
            gap_type = "BULLISH"
            gap_high = right_low
            gap_low = left_high
        elif right_high < left_low:
            gap_type = "BEARISH"
            gap_high = left_low
            gap_low = right_high
        else:
            continue

        gap_width = gap_high - gap_low
        if gap_width <= 0:
            continue

        raw_gaps.append({"formed_index": i, "type": gap_type, "high": gap_high, "low": gap_low, "width": gap_width})

    results = []
    for g in raw_gaps:
        formed_index = g["formed_index"]
        gap_type = g["type"]
        gap_high = g["high"]
        gap_low = g["low"]
        gap_width = g["width"]

        deepest_fill = 0.0
        is_inverted = False
        inverted_at_index = None

        for j in range(formed_index + 1, n):
            bar_high = float(rates[j][2])
            bar_low = float(rates[j][3])
            bar_close = float(rates[j][4])

            if gap_type == "BULLISH":
                if bar_low < gap_high:
                    fill = (gap_high - max(bar_low, gap_low)) / gap_width
                    deepest_fill = max(deepest_fill, min(1.0, fill))
                if bar_close < gap_low and not is_inverted:
                    is_inverted = True
                    inverted_at_index = j
            else:  # BEARISH
                if bar_high > gap_low:
                    fill = (min(bar_high, gap_high) - gap_low) / gap_width
                    deepest_fill = max(deepest_fill, min(1.0, fill))
                if bar_close > gap_high and not is_inverted:
                    is_inverted = True
                    inverted_at_index = j

        is_mitigated = deepest_fill >= mitigation_full_threshold or is_inverted

        results.append({
            "type": gap_type,
            "polarity": ("BEARISH" if gap_type == "BULLISH" else "BULLISH") if is_inverted else gap_type,
            "is_inverse_fvg": is_inverted,
            "high": round(gap_high, 5),
            "low": round(gap_low, 5),
            "width": round(gap_width, 5),
            "formed_bar_index": formed_index,
            "inverted_bar_index": inverted_at_index,
            "age_bars": n - 1 - formed_index,
            "mitigation_pct": round(min(1.0, deepest_fill), 3),
            "is_mitigated": is_mitigated,
        })

    active = [g for g in results if not g["is_mitigated"] or g["is_inverse_fvg"]]
    active.sort(key=lambda g: g["formed_bar_index"], reverse=True)
    return active[:max_gaps]


# ============================================================
# RSI DIVERGENCE DETECTION
# ============================================================

def _detect_rsi_divergence(prices: List[float], rsi: List[float], timeframe: str = "M1", 
                           rsi_14: float = None, rsi_21: float = None) -> Dict[str, Any]:
    lookback_bars = _get_divergence_lookback(timeframe)
    
    if len(prices) < lookback_bars or len(rsi) < lookback_bars:
        return {"type": "NONE", "score": 0, "period_divergence": {"type": "NONE", "score": 0}}
    
    prices_window = prices[-lookback_bars:]
    rsi_window = rsi[-lookback_bars:]
    swing_window = _get_swing_window(timeframe, lookback_bars)
    
    price_lows, rsi_lows, price_highs, rsi_highs = [], [], [], []
    
    for i in range(swing_window, len(prices_window) - swing_window):
        is_price_low = True
        for j in range(1, swing_window + 1):
            if i - j >= 0 and prices_window[i] >= prices_window[i - j]:
                is_price_low = False
                break
            if i + j < len(prices_window) and prices_window[i] >= prices_window[i + j]:
                is_price_low = False
                break
        if is_price_low:
            price_lows.append((i, prices_window[i]))
        
        is_price_high = True
        for j in range(1, swing_window + 1):
            if i - j >= 0 and prices_window[i] <= prices_window[i - j]:
                is_price_high = False
                break
            if i + j < len(prices_window) and prices_window[i] <= prices_window[i + j]:
                is_price_high = False
                break
        if is_price_high:
            price_highs.append((i, prices_window[i]))
        
        rsi_swing = max(2, swing_window // 2)
        is_rsi_low = True
        for j in range(1, rsi_swing + 1):
            if i - j >= 0 and rsi_window[i] >= rsi_window[i - j]:
                is_rsi_low = False
                break
            if i + j < len(rsi_window) and rsi_window[i] >= rsi_window[i + j]:
                is_rsi_low = False
                break
        if is_rsi_low:
            rsi_lows.append((i, rsi_window[i]))
        
        is_rsi_high = True
        for j in range(1, rsi_swing + 1):
            if i - j >= 0 and rsi_window[i] <= rsi_window[i - j]:
                is_rsi_high = False
                break
            if i + j < len(rsi_window) and rsi_window[i] <= rsi_window[i + j]:
                is_rsi_high = False
                break
        if is_rsi_high:
            rsi_highs.append((i, rsi_window[i]))
    
    result = {"type": "NONE", "score": 0, "period_divergence": {"type": "NONE", "score": 0}}
    
    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        price_low_vals = [p[1] for p in price_lows[-2:]]
        rsi_low_vals = [r[1] for r in rsi_lows[-2:]]
        if price_low_vals[-1] < price_low_vals[-2] and rsi_low_vals[-1] > rsi_low_vals[-2]:
            if abs(price_lows[-1][0] - rsi_lows[-1][0]) <= swing_window:
                result = {"type": "REGULAR_BULLISH", "score": 85}
    
    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        price_high_vals = [p[1] for p in price_highs[-2:]]
        rsi_high_vals = [r[1] for r in rsi_highs[-2:]]
        if price_high_vals[-1] > price_high_vals[-2] and rsi_high_vals[-1] < rsi_high_vals[-2]:
            if abs(price_highs[-1][0] - rsi_highs[-1][0]) <= swing_window:
                result = {"type": "REGULAR_BEARISH", "score": -85}
    
    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        price_low_vals = [p[1] for p in price_lows[-2:]]
        rsi_low_vals = [r[1] for r in rsi_lows[-2:]]
        if price_low_vals[-1] > price_low_vals[-2] and rsi_low_vals[-1] < rsi_low_vals[-2]:
            result = {"type": "HIDDEN_BULLISH", "score": 50}
    
    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        price_high_vals = [p[1] for p in price_highs[-2:]]
        rsi_high_vals = [r[1] for r in rsi_highs[-2:]]
        if price_high_vals[-1] < price_high_vals[-2] and rsi_high_vals[-1] > rsi_high_vals[-2]:
            result = {"type": "HIDDEN_BEARISH", "score": -50}
    
    if rsi_14 is not None and rsi_21 is not None:
        period_divergence = _detect_rsi_period_divergence(rsi_14, rsi_21)
        result["period_divergence"] = period_divergence
        if result["type"] == "NONE" and period_divergence["type"] != "NONE":
            result["type"] = period_divergence["type"]
            result["score"] = period_divergence["score"]
    
    return result


def _detect_rsi_period_divergence(rsi_14: float, rsi_21: float) -> Dict[str, Any]:
    diff = rsi_14 - rsi_21
    
    if diff > 10:
        return {"type": "PERIOD_BULLISH", "score": 10, "description": "RSI 14 > RSI 21 by 10+"}
    elif diff > 5:
        return {"type": "PERIOD_BULLISH", "score": 5, "description": "RSI 14 > RSI 21 by 5+"}
    elif diff < -10:
        return {"type": "PERIOD_BEARISH", "score": -10, "description": "RSI 14 < RSI 21 by 10+"}
    elif diff < -5:
        return {"type": "PERIOD_BEARISH", "score": -5, "description": "RSI 14 < RSI 21 by 5+"}
    else:
        return {"type": "NONE", "score": 0, "description": "No period divergence"}


# ============================================================
# STOCHASTIC DIVERGENCE DETECTION
# ============================================================

def _detect_stochastic_divergence(
    prices: List[float],
    stoch_k: List[float],
    timeframe: str = "M1"
) -> Dict[str, Any]:
    lookback_bars = _get_divergence_lookback(timeframe)
    
    if len(prices) < lookback_bars or len(stoch_k) < lookback_bars:
        return {"type": "NONE", "score": 0}
    
    prices_window = prices[-lookback_bars:]
    stoch_window = stoch_k[-lookback_bars:]
    swing_window = _get_swing_window(timeframe, lookback_bars)
    
    price_swings = _find_swing_points_detailed(prices_window, swing_window)
    stoch_swings = _find_swing_points_detailed(stoch_window, max(2, swing_window // 2))
    
    price_lows = price_swings['lows']
    price_highs = price_swings['highs']
    stoch_lows = stoch_swings['lows']
    stoch_highs = stoch_swings['highs']
    
    result = {"type": "NONE", "score": 0}
    
    if len(price_lows) >= 2 and len(stoch_lows) >= 2:
        price_low_1, price_low_2 = price_lows[-2][1], price_lows[-1][1]
        stoch_low_1, stoch_low_2 = stoch_lows[-2][1], stoch_lows[-1][1]
        if price_low_2 < price_low_1 and stoch_low_2 > stoch_low_1:
            if abs(price_lows[-1][0] - stoch_lows[-1][0]) <= swing_window:
                result = {"type": "REGULAR_BULLISH", "score": 85}
    
    if result["type"] == "NONE" and len(price_highs) >= 2 and len(stoch_highs) >= 2:
        price_high_1, price_high_2 = price_highs[-2][1], price_highs[-1][1]
        stoch_high_1, stoch_high_2 = stoch_highs[-2][1], stoch_highs[-1][1]
        if price_high_2 > price_high_1 and stoch_high_2 < stoch_high_1:
            if abs(price_highs[-1][0] - stoch_highs[-1][0]) <= swing_window:
                result = {"type": "REGULAR_BEARISH", "score": -85}
    
    if result["type"] == "NONE" and len(price_lows) >= 2 and len(stoch_lows) >= 2:
        price_low_1, price_low_2 = price_lows[-2][1], price_lows[-1][1]
        stoch_low_1, stoch_low_2 = stoch_lows[-2][1], stoch_lows[-1][1]
        if price_low_2 > price_low_1 and stoch_low_2 < stoch_low_1:
            if abs(price_lows[-1][0] - stoch_lows[-1][0]) <= swing_window:
                result = {"type": "HIDDEN_BULLISH", "score": 50}
    
    if result["type"] == "NONE" and len(price_highs) >= 2 and len(stoch_highs) >= 2:
        price_high_1, price_high_2 = price_highs[-2][1], price_highs[-1][1]
        stoch_high_1, stoch_high_2 = stoch_highs[-2][1], stoch_highs[-1][1]
        if price_high_2 < price_high_1 and stoch_high_2 > stoch_high_1:
            if abs(price_highs[-1][0] - stoch_highs[-1][0]) <= swing_window:
                result = {"type": "HIDDEN_BEARISH", "score": -50}
    
    return result


# ============================================================
# CANDLESTICK PATTERN DETECTION
# ============================================================

def _detect_candle_pattern(open_price: float, high_price: float, low_price: float, close_price: float, pip_size: float = 0.1) -> Tuple[str, str, float]:
    body = abs(close_price - open_price)
    total_range = high_price - low_price
    
    if total_range == 0:
        return "doji", "NEUTRAL", 0
    
    body_ratio = body / total_range
    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price
    
    if upper_wick > body * PIN_BAR_THRESHOLD and lower_wick < body * 0.5:
        return ("pin_bar_bullish", "BULLISH", 20) if close_price > open_price else ("pin_bar_bearish", "BEARISH", -20)
    elif lower_wick > body * PIN_BAR_THRESHOLD and upper_wick < body * 0.5:
        return ("pin_bar_bullish", "BULLISH", 20) if close_price > open_price else ("pin_bar_bearish", "BEARISH", -20)
    
    if body_ratio < 0.1:
        return "doji", "NEUTRAL", 0
    
    upper_wick_ratio = upper_wick / total_range
    lower_wick_ratio = lower_wick / total_range
    
    if lower_wick_ratio > 0.6 and upper_wick_ratio < 0.2:
        return "hammer", "BULLISH", 25
    elif upper_wick_ratio > 0.6 and lower_wick_ratio < 0.2:
        return "shooting_star", "BEARISH", -25
    elif body_ratio > 0.7:
        return ("marubozu_bullish", "STRONG_BULLISH", 25) if close_price > open_price else ("marubozu_bearish", "STRONG_BEARISH", -25)
    elif body_ratio > 0.3:
        return ("normal_bullish", "BULLISH", 10) if close_price > open_price else ("normal_bearish", "BEARISH", -10)
    else:
        return "spinning_top", "NEUTRAL", 0


# ============================================================
# WYCKOFF PHASE DETECTION
# ============================================================

def _detect_wyckoff_phase(rates: np.ndarray, adx_value: float, trend: str, volume_ratio: float = 1.0, 
                          symbol: str = "XAUUSD", pip_size: float = 0.01, timeframe: str = "M1") -> str:
    spike_threshold = _get_wyckoff_spike_threshold(symbol)
    momentum_threshold = _get_momentum_threshold(symbol)
    adx_thresholds = _get_adx_thresholds(symbol)
    strong_trend_threshold = adx_thresholds["strong_trend"]
    trend_threshold = adx_thresholds["trend"]
    wyckoff_lookback = _get_wyckoff_lookback_bars(timeframe)
    
    if adx_value > strong_trend_threshold:
        if len(rates) >= wyckoff_lookback:
            volume = [float(r[5]) for r in rates]
            avg_vol_5 = sum(volume[-5:]) / 5 if len(volume) >= 5 else volume[-1]
            avg_vol_20 = sum(volume[-wyckoff_lookback:]) / wyckoff_lookback if len(volume) >= wyckoff_lookback else avg_vol_5
            is_volume_spike = avg_vol_5 > avg_vol_20 * spike_threshold
        else:
            is_volume_spike = volume_ratio >= spike_threshold
        
        if trend == "STRONG_BEARISH":
            return "MARKDOWN_STRONG" if is_volume_spike else "MARKDOWN"
        elif trend == "STRONG_BULLISH":
            return "MARKUP_STRONG" if is_volume_spike else "MARKUP"
    
    if adx_value > trend_threshold:
        if trend == "BEARISH":
            if adx_value > WYCKOFF_UPGRADE_ADX_THRESHOLD:
                return "MARKDOWN"
            return "MARKDOWN" if volume_ratio >= WYCKOFF_MARKDOWN_MIN_VOL else "MARKDOWN_TENTATIVE"
        elif trend == "BULLISH":
            if adx_value > WYCKOFF_UPGRADE_ADX_THRESHOLD:
                return "MARKUP"
            return "MARKUP" if volume_ratio >= WYCKOFF_MARKUP_MIN_VOL else "MARKUP_TENTATIVE"
    
    if len(rates) < wyckoff_lookback:
        return "CONSOLIDATION"
    
    price_arrays = _extract_price_arrays(rates)
    close = price_arrays["close"]
    volume = price_arrays["volume"]
    
    if len(close) < wyckoff_lookback:
        return "CONSOLIDATION"
    
    avg_vol_5 = sum(volume[-5:]) / 5 if len(volume) >= 5 else volume[-1]
    avg_vol_20 = sum(volume[-wyckoff_lookback:]) / wyckoff_lookback if len(volume) >= wyckoff_lookback else avg_vol_5
    # ✅ FIXED: range_high/range_low were computed over rates[-wyckoff_
    # lookback:], which INCLUDES the current bar (rates[-1]) itself. The
    # spring check below then compared rates[-1][3] < range_low -- but a
    # value can never be strictly less than the minimum of a set that
    # already contains it, so `spring` was always False regardless of
    # what the price data actually showed, making ACCUMULATION_COMPLETE
    # (Wyckoff's highest-conviction phase) permanently unreachable.
    # Verified directly: current < min(set including current) is a
    # mathematical impossibility, not just an unlikely case. Now
    # excludes the current bar from the range so a genuine "price dipped
    # below the established range, then reclaimed on this bar" spring
    # can actually be detected.
    prior_bars = rates[-wyckoff_lookback:-1] if len(rates) > wyckoff_lookback else rates[:-1]
    range_high = max([float(r[2]) for r in prior_bars]) if len(prior_bars) > 0 else float(rates[-1][2])
    range_low = min([float(r[3]) for r in prior_bars]) if len(prior_bars) > 0 else float(rates[-1][3])
    momentum = (close[-1] - close[-20]) / close[-20] if len(close) >= 20 else 0
    spring = rates[-1][3] < range_low and rates[-1][4] > range_low
    # The mirror event (2026-09-15): a push above the range that closes back
    # inside -- Wyckoff's upthrust after distribution. Only the spring was
    # ever checked, so the component could see accumulation but never
    # distribution.
    upthrust = rates[-1][2] > range_high and rates[-1][4] < range_high
    is_high_volume = avg_vol_5 > avg_vol_20 * spike_threshold
    # Checked before momentum: the reclaim bar itself often leaves 20-bar
    # momentum past the threshold, which labelled the event as trend.
    if spring and is_high_volume:
        return "ACCUMULATION_COMPLETE"
    if upthrust and is_high_volume:
        return "DISTRIBUTION_COMPLETE"
    
    if momentum > momentum_threshold:
        return "MARKUP_STRONG" if is_high_volume else "MARKUP_TENTATIVE"
    elif momentum < -momentum_threshold:
        return "MARKDOWN_STRONG" if is_high_volume else "MARKDOWN_TENTATIVE"
    elif spring and is_high_volume:
        return "ACCUMULATION_COMPLETE"
    else:
        return "ACCUMULATION_BUILDING" if volume[-1] < avg_vol_20 * WYCKOFF_CONSOLIDATION_VOLUME_THRESHOLD else "CONSOLIDATION"


# ============================================================
# TREND BIAS DETECTION
# ============================================================

TREND_EMA_SEPARATION_ATR = 0.25   # EMA20-EMA200 gap needed for a low-ADX trend call


def _detect_trend_bias(rates: np.ndarray, symbol: str = "XAUUSD", pip_size: float = 0.01, timeframe: str = "M1") -> Tuple[str, float, float, float, float]:
    min_bars = _get_min_bars_for_trend(timeframe)
    
    if len(rates) < min_bars:
        return "NEUTRAL", 0.0, 0.0, 0.0, 0.0
    
    price_arrays = _extract_price_arrays(rates)
    close = price_arrays["close"]
    high = price_arrays["high"]
    low = price_arrays["low"]
    
    if len(close) < 200:
        return "NEUTRAL", 0.0, 0.0, 0.0, 0.0
    
    current = close[-1]
    ema_20 = _calculate_ema(close, 20)
    ema_50 = _calculate_ema(close, 50)
    ema_200 = _calculate_ema(close, 200)
    adx_val = _calculate_adx(high, low, close, 14)
    
    adx_thresholds = _get_adx_thresholds(symbol)
    trend_threshold = adx_thresholds["trend"]
    strong_trend_threshold = adx_thresholds["strong_trend"]
    
    if adx_val > trend_threshold:
        if current > ema_200:
            trend = "STRONG_BULLISH" if adx_val > strong_trend_threshold else "BULLISH"
        elif current < ema_200:
            trend = "STRONG_BEARISH" if adx_val > strong_trend_threshold else "BEARISH"
        else:
            trend = "NEUTRAL"
        return trend, ema_20, ema_50, ema_200, adx_val
    
    min_separation_price = _get_ema_min_separation(symbol, pip_size)
    # ✅ (2026-09-15) ATR-scaled: 5 fixed pips is 5 ATR on a 1-pip-ATR currency
    # pair (quiet FX trends always read NEUTRAL) and ~0.1 ATR on silver.
    if len(close) > 15:
        _tr = [max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
               for i in range(len(close) - 14, len(close))]
        _atr = sum(_tr) / 14
        if _atr > 0:
            min_separation_price = TREND_EMA_SEPARATION_ATR * _atr
    ema_separation = abs(ema_20 - ema_200)
    
    if ema_separation < min_separation_price:
        return "NEUTRAL", ema_20, ema_50, ema_200, adx_val
    
    if current > ema_200:
        return "BULLISH", ema_20, ema_50, ema_200, adx_val
    elif current < ema_200:
        return "BEARISH", ema_20, ema_50, ema_200, adx_val
    else:
        return "NEUTRAL", ema_20, ema_50, ema_200, adx_val


# ============================================================
# ZONE METADATA STORAGE
# ============================================================

class ZoneMetadataStore:
    def __init__(self):
        self._metadata = {}
        self._lock = threading.Lock()
    
    def get(self, zone_key: str) -> Optional[Dict]:
        with self._lock:
            data = self._metadata.get(zone_key)
            return copy.deepcopy(data) if data else None
    
    def set(self, zone_key: str, metadata: Dict):
        with self._lock:
            self._metadata[zone_key] = copy.deepcopy(metadata)
    
    def delete(self, zone_key: str):
        with self._lock:
            if zone_key in self._metadata:
                del self._metadata[zone_key]
    
    def contains(self, zone_key: str) -> bool:
        with self._lock:
            return zone_key in self._metadata
    
    def update(self, zone_key: str, updates: Dict):
        with self._lock:
            if zone_key in self._metadata:
                self._metadata[zone_key].update(copy.deepcopy(updates))
    
    def get_all(self) -> Dict:
        with self._lock:
            return copy.deepcopy(self._metadata)


_zone_metadata_store = ZoneMetadataStore()


# ============================================================
# ZONE RESET AND METADATA MANAGEMENT
# ============================================================

def _reset_zone_if_needed(zone_level: float, zone_type: str, current_time: int, symbol: str = "DEFAULT") -> bool:
    # ✅ FIXED: was f"{zone_level}_{zone_type}" with the raw, unrounded
    # float -- same fragility already found and fixed in
    # discount_engine.py's zone tracking. zone_level is re-derived from a
    # slightly shifting rates window on every call (a new bar arrives,
    # the swing-detection lookback shifts), so the same conceptual zone
    # could silently generate a different key across calls from sub-pip
    # float noise, resetting touch-count/decay tracking instead of
    # accumulating it. Rounded to the same 5-decimal precision zone
    # levels are already displayed at elsewhere in this codebase.
    zone_key = f"{round(zone_level, 5)}_{zone_type}"
    
    if not _zone_metadata_store.contains(zone_key):
        return False
    
    metadata = _zone_metadata_store.get(zone_key)
    if not metadata:
        return False
    
    last_touch = metadata.get("last_touch", 0)
    first_detected = metadata.get("first_detected", current_time)
    decay_config = _get_zone_time_decay_config(symbol)
    
    hours_since_last_touch = (current_time - last_touch) / 3600
    reset_hours = decay_config.get("decay_duration_hours", ZONE_RESET_AFTER_HOURS)
    
    if hours_since_last_touch > reset_hours:
        _zone_metadata_store.delete(zone_key)
        return True
    
    decay_start_hours = decay_config.get("decay_start_hours", 12)
    decay_duration = decay_config.get("decay_duration_hours", 48)
    min_decay_factor = decay_config.get("min_decay_factor", 0.3)
    hours_since_detection = (current_time - first_detected) / 3600
    
    if hours_since_detection > decay_start_hours:
        decay_factor = max(min_decay_factor, 1.0 - (hours_since_detection / decay_duration))
        original_touch_count = metadata.get("original_touch_count", metadata.get("touch_count", 0))
        new_touch_count = int(original_touch_count * decay_factor)
        if new_touch_count != metadata.get("touch_count", 0):
            _zone_metadata_store.update(zone_key, {"touch_count": new_touch_count})
    
    return False


def get_zone_freshness(zone_level: float, zone_type: str, current_time: int,
                       timeframe: str = "M1", decay_bars: int = 200) -> float:
    """
    ✅ How fresh a zone is, 0-1, from `first_detected` in the metadata
    store -- which was already being recorded and used for nothing.

    1.0 the bar it forms, decaying linearly to 0 over `decay_bars`. A
    zone the market has ignored for 200 bars is stale regardless of how
    decisively it formed.

    Returns 1.0 for an unknown zone: a level detected this instant is by
    definition brand new.
    """
    seconds = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
               "H1": 3600, "H4": 14400, "D1": 86400}.get((timeframe or "M1").upper(), 60)
    try:
        meta = _zone_metadata_store.get(f"{round(zone_level, 5)}_{zone_type}")
        if not meta or not meta.get("first_detected"):
            return 1.0
        age_bars = max(0.0, (current_time - float(meta["first_detected"])) / seconds)
        return max(0.0, min(1.0, 1.0 - (age_bars / float(decay_bars))))
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0


def get_zone_displacement_quality(rates, zone_level: float, zone_type: str,
                                  pip_size: float, atr_pips: float = None) -> float:
    """
    ✅ How decisively price LEFT the zone, 0-1.

    This is the property that makes a fresh zone tradable: an order block
    matters because price departed it with an impulse, not because it was
    revisited. Measured as the strongest body, in ATR terms, among the
    bars that moved away from the level -- capped at 1.0 for a full-ATR
    displacement candle.

    The system already computes displacement elsewhere
    (displacement_confirmation.py) but never fed it into zone grading.
    """
    if rates is None or len(rates) < 5 or not pip_size or pip_size <= 0:
        return 0.5
    scale = (atr_pips or 0.0) * pip_size
    if scale <= 0:
        return 0.5
    best = 0.0
    for r in rates[-20:]:
        try:
            o, c = float(r[1]), float(r[4])
        except (IndexError, TypeError, ValueError):
            continue
        body = c - o
        # only bars moving AWAY from the zone count as displacement
        if zone_type == "DEMAND" and body <= 0:
            continue
        if zone_type == "SUPPLY" and body >= 0:
            continue
        best = max(best, abs(body) / scale)
    return max(0.0, min(1.0, best))


def _update_zone_metadata(zone_level: float, zone_type: str, current_time: int, touch_detected: bool):
    # ✅ FIXED: same float-fragmentation fix as _reset_zone_if_needed
    # above -- these two functions must agree on the exact same key for
    # the same zone, so both need the identical rounding.
    zone_key = f"{round(zone_level, 5)}_{zone_type}"
    
    if not _zone_metadata_store.contains(zone_key):
        _zone_metadata_store.set(zone_key, {
            "first_detected": current_time,
            "last_touch": current_time if touch_detected else current_time,
            "touch_count": 1 if touch_detected else 0,
            "original_touch_count": 1 if touch_detected else 0
        })
    else:
        if touch_detected:
            metadata = _zone_metadata_store.get(zone_key)
            if metadata:
                new_touch_count = metadata.get("touch_count", 0) + 1
                if new_touch_count > ZONE_MAX_TOUCHES_FOR_GRADE:
                    new_touch_count = ZONE_MAX_TOUCHES_FOR_GRADE
                _zone_metadata_store.update(zone_key, {
                    "last_touch": current_time,
                    "touch_count": new_touch_count,
                    "original_touch_count": metadata.get("original_touch_count", new_touch_count)
                })


# ============================================================
# SUPPLY/DEMAND ZONE DETECTION (WITH PERSISTENCE AND FIXED GRADING)
# ============================================================

_ZONE_PERSISTENCE = {}
_ZONE_PERSISTENCE_LOCK = threading.Lock()

def _get_persistent_zone(symbol: str, current_time: int) -> Optional[Dict]:
    with _ZONE_PERSISTENCE_LOCK:
        if symbol in _ZONE_PERSISTENCE:
            zone_data = _ZONE_PERSISTENCE[symbol]
            age = current_time - zone_data.get("cached_at", 0)
            if age < ZONE_PERSISTENCE_SECONDS:
                return zone_data
            else:
                del _ZONE_PERSISTENCE[symbol]
    return None

def _update_persistent_zone(symbol: str, zone_data: Dict, current_time: int):
    with _ZONE_PERSISTENCE_LOCK:
        zone_data["cached_at"] = current_time
        _ZONE_PERSISTENCE[symbol] = zone_data

def _clear_persistent_zone(symbol: str = None):
    with _ZONE_PERSISTENCE_LOCK:
        if symbol:
            _ZONE_PERSISTENCE.pop(symbol, None)
        else:
            _ZONE_PERSISTENCE.clear()


ZONE_DEPARTURE_BARS = 10          # bars after the swing that may carry its departure impulse
ZONE_FRESHNESS_DECAY_BARS = 200   # a zone this many bars old is fully stale


def _bar(r, i):
    return float(r[i])


def _zone_candidates(rates, current_price: float, pip_size: float, timeframe: str,
                     touch_distance: float, use_high: bool, atr_pips: float = None):
    """Swing levels on one side of price that price has NOT closed through
    since they formed, as (level, bar_index), nearest first."""
    from core.swing_points import find_swing_points

    min_amp = get_min_swing_size(timeframe, pip_size, atr_pips)
    series = [_bar(r, 2) for r in rates] if use_high else [_bar(r, 3) for r in rates]
    wanted = "high" if use_high else "low"
    closes = [_bar(r, 4) for r in rates]
    out = []
    for p in find_swing_points(series, lookback=5, min_amplitude=min_amp):
        if p["type"] != wanted:
            continue
        level, idx = p["price"], p["index"]
        if use_high and level < current_price:
            continue
        if not use_high and level > current_price:
            continue
        after = closes[idx + 1:]
        broken = (any(c > level + touch_distance for c in after) if use_high
                  else any(c < level - touch_distance for c in after))
        if not broken:
            out.append((level, idx))
    out.sort(key=lambda z: abs(z[0] - current_price))
    return out


def _zone_facts(rates, level: float, idx: int, zone_type: str, touch_distance: float,
                atr_price: float) -> Dict[str, Any]:
    """Everything about a zone that grading needs, measured from the bars.

    Replaces the call-history store (2026-09-15). The old path counted a
    "touch" on every ANALYSIS CALL made while price was near the zone, dated
    freshness from when this PROCESS first saw the level, and decayed both on
    hours since then -- so the same bar graded differently in a monitor
    polling every few seconds, a replay stepping every 15 minutes, and a
    process restarted an hour ago.
    """
    n = len(rates)
    age_bars = max(0, n - 1 - idx)
    after = rates[idx + 1:]
    probe_col = 2 if zone_type == "SUPPLY" else 3
    touches, inside_prev = 0, True           # still at the level right after it forms
    for r in after:
        inside = abs(_bar(r, probe_col) - level) <= touch_distance
        if inside and not inside_prev:
            touches += 1
        inside_prev = inside
    best_body = 0.0
    for r in after[:ZONE_DEPARTURE_BARS]:
        body = _bar(r, 4) - _bar(r, 1)
        if (zone_type == "DEMAND" and body > 0) or (zone_type == "SUPPLY" and body < 0):
            best_body = max(best_body, abs(body))
    displacement = min(1.0, best_body / atr_price) if atr_price > 0 else 0.5
    return {
        "age_bars": age_bars,
        "touch_count": min(touches, ZONE_MAX_TOUCHES_FOR_GRADE),
        "freshness": round(max(0.0, 1.0 - age_bars / float(ZONE_FRESHNESS_DECAY_BARS)), 3),
        "displacement": round(displacement, 3),
    }


def _detect_supply_demand_zone(rates: np.ndarray, current_price: float, pip_size: float = 0.1,
                               symbol: str = "XAUUSD", timeframe: str = "M1",
                               volume_ratio: float = 1.0, adx: float = 0.0, spread_pips: float = 0,
                               atr_pips: float = None) -> Tuple[Optional[str], Optional[float], str, float, bool, int]:
    """Nearest unbroken supply (swing high above) or demand (swing low below)
    zone, graded from facts measured on the bars alone -- the same bars give
    the same zone and grade, whoever calls and however often."""
    zone_lookback = _get_zone_lookback_bars(timeframe)
    if rates is None or len(rates) < zone_lookback:
        return None, None, "E", 0.35, False, 35

    window = rates[-zone_lookback:]
    touch_distance = _get_zone_touch_distance(symbol, pip_size, timeframe, atr_pips)
    demand = _zone_candidates(window, current_price, pip_size, timeframe, touch_distance, use_high=False, atr_pips=atr_pips)
    supply = _zone_candidates(window, current_price, pip_size, timeframe, touch_distance, use_high=True, atr_pips=atr_pips)
    if not demand and not supply:
        return None, None, "E", 0.35, False, 35
    if demand and (not supply or abs(current_price - demand[0][0]) <= abs(supply[0][0] - current_price)):
        (best_zone, idx), zone_type = demand[0], "DEMAND"
    else:
        (best_zone, idx), zone_type = supply[0], "SUPPLY"

    atr_price = (atr_pips or 0.0) * pip_size
    facts = _zone_facts(window, best_zone, idx, zone_type, touch_distance, atr_price)

    range_high = max(_bar(r, 2) for r in rates[-50:])
    range_low = min(_bar(r, 3) for r in rates[-50:])
    try:
        _zone_vp = get_zone_volume_profile(
            [_bar(r, 4) for r in rates[-100:]], [_bar(r, 5) for r in rates[-100:]],
            best_zone, pip_size, atr_pips)
        _zone_volume_confirmed = bool(_zone_vp.get("volume_confirmed", False))
    except (IndexError, TypeError, ValueError) as e:
        logger.debug(f"[ZONE] volume profile unavailable: {e}")
        _zone_volume_confirmed = False

    grade, multiplier, zone_score, penalty_reason, details = get_zone_adjusted_score(
        touch_count=facts["touch_count"],
        volume_confirmed=_zone_volume_confirmed,
        freshness=facts["freshness"],
        displacement=facts["displacement"],
        volume_quality=1.0 if _zone_volume_confirmed else 0.5,
        volume_ratio=volume_ratio, adx=adx, spread_pips=spread_pips, pip_size=pip_size,
        zone_type=zone_type, range_high=range_high, range_low=range_low, zone_level=best_zone,
        use_strict=adx > 85,
    )
    breakdown = dict(details.get("quality_breakdown") or {})
    breakdown.update(facts)
    _record_zone_quality(best_zone, zone_type, breakdown, symbol=symbol)

    if zone_score <= 0:
        zone_score = ZONE_GRADE_SCORES.get(grade, 35)
    if grade == "E":
        is_at_zone = False
    else:
        is_at_zone = abs(current_price - best_zone) <= get_zone_proximity_pips(symbol, grade, atr_pips) * pip_size
    return zone_type, best_zone, grade, multiplier, is_at_zone, zone_score


# ============================================================
# HIGHER TIMEFRAME FUNCTIONS
# ============================================================

def get_h1_trend(symbol: str, h1_rates=None) -> Dict[str, Any]:
    """
    H1 trend context.

    h1_rates is an injection seam for replay. This function fetched its
    own 200 H1 bars from MT5, which meant that replaying a decision from
    months ago returned TODAY's H1 trend -- and the H1 alignment bonus
    is worth +10 probability points, so the backtest would have been
    reading the future at the single most valuable point in the chain.

    Omit h1_rates and it fetches live, exactly as before.
    """
    try:
        h1_tf = mt5.TIMEFRAME_H1
        if h1_rates is None:
            h1_rates = mt5.copy_rates_from_pos(symbol, h1_tf, 0, 200)
        
        if h1_rates is None or len(h1_rates) < 100:
            return {"trend": "NEUTRAL", "adx": 0, "ema_200": 0, "current_price": 0}
        
        price_arrays = _extract_price_arrays(h1_rates)
        h1_close = price_arrays["close"]
        h1_high = price_arrays["high"]
        h1_low = price_arrays["low"]
        
        h1_ema_20 = _calculate_ema(h1_close, 20)
        h1_ema_50 = _calculate_ema(h1_close, 50)
        h1_ema_200 = _calculate_ema(h1_close, 200)
        h1_adx = _calculate_adx(h1_high, h1_low, h1_close, 14)
        h1_current = h1_close[-1]
        
        above_ema20 = h1_current > h1_ema_20
        above_ema50 = h1_current > h1_ema_50
        above_ema200 = h1_current > h1_ema_200
        bullish_signals = sum([above_ema20, above_ema50, above_ema200])
        
        if len(h1_close) >= 10:
            recent_momentum = (h1_close[-1] - h1_close[-6]) / h1_close[-6] * 100
        else:
            recent_momentum = 0
        
        if h1_adx > 25:
            if bullish_signals >= 2:
                h1_trend = "BULLISH"
            elif bullish_signals <= 1:
                h1_trend = "BEARISH"
            else:
                h1_trend = "NEUTRAL"
        elif h1_adx > 20:
            if recent_momentum > 0.1:
                h1_trend = "BULLISH"
            elif recent_momentum < -0.1:
                h1_trend = "BEARISH"
            else:
                h1_trend = "NEUTRAL"
        else:
            h1_trend = "NEUTRAL"
        
        symbol_upper = symbol.upper()
        if "XAU" in symbol_upper or "XAG" in symbol_upper:
            if h1_adx > 20 and recent_momentum > 0.05:
                h1_trend = "BULLISH"
            elif h1_adx > 20 and recent_momentum < -0.05:
                h1_trend = "BEARISH"
        
        return {
            "trend": h1_trend, 
            "adx": round(h1_adx, 1), 
            "ema_200": round(h1_ema_200, 5), 
            "current_price": round(h1_current, 5), 
            "ema_20": round(h1_ema_20, 5), 
            "ema_50": round(h1_ema_50, 5), 
            "momentum": round(recent_momentum, 2)
        }
    except Exception as e:
        logger.warning(f"[H1_TREND] Failed for {symbol}: {e}")
        return {"trend": "NEUTRAL", "adx": 0, "ema_200": 0, "current_price": 0}


# RSI divergence is detected on M1 ONLY (operator, 2026-09-18: "forever").
# The M15 divergence functions that lived here were deleted; the one
# definition is core/rsi_divergence_setup.py.

# Bars of true range used as the volatility baseline that ATR(14) is
# compared against. Must exceed 14 for the comparison to mean anything.
_REGIME_BASELINE_BARS = 50


def detect_market_regime(rates: np.ndarray) -> str:
    # The baseline window must be strictly LONGER than the ATR window,
    # otherwise the comparison below is self-referential. Taking N bars
    # yields only N-1 true ranges (the loop needs a previous close), so
    # slicing 50 bars gave 49 TRs, the `len(tr) >= 50` guard never held,
    # avg_range silently fell back to atr, and every test reduced to
    # `atr > atr * 1.5` -- false for all inputs. The function returned
    # NORMAL on 1856/1856 replay decisions and on 1000 synthetic series
    # including a 500x volatility spike.
    if rates is None or len(rates) < _REGIME_BASELINE_BARS + 1:
        return "NORMAL"

    price_arrays = _extract_price_arrays(rates[-(_REGIME_BASELINE_BARS + 1):])
    high_prices = price_arrays["high"]
    low_prices = price_arrays["low"]
    close_prices = price_arrays["close"]
    
    tr = []
    for i in range(1, len(close_prices)):
        hl = high_prices[i] - low_prices[i]
        hc = abs(high_prices[i] - close_prices[i-1])
        lc = abs(low_prices[i] - close_prices[i-1])
        tr.append(max(hl, hc, lc))
    
    if len(tr) < _REGIME_BASELINE_BARS:
        return "NORMAL"

    atr = sum(tr[-14:]) / 14
    baseline = tr[-_REGIME_BASELINE_BARS:]
    avg_range = sum(baseline) / len(baseline)

    # A perfectly flat tape gives avg_range == 0; every ratio test below
    # would then be False and the answer would default to NORMAL, which
    # is the one thing a flat tape is not.
    if avg_range <= 0:
        return "NORMAL" if atr > 0 else "LOW_VOLATILITY"

    if atr > avg_range * 1.5:
        return "HIGH_VOLATILITY"
    elif atr < avg_range * 0.5:
        return "LOW_VOLATILITY"
    else:
        return "NORMAL"


# ============================================================
# MULTI-FACTOR TRADING REGIME CLASSIFICATION
# ============================================================
# ✅ ADDED: detect_market_regime() above is volatility-only (ATR ratio,
# 3 states) and is left completely untouched -- it still feeds
# apply_probability_multipliers_pair() and check_volatility_protection()
# in calculations.py exactly as before, so their `market_regime ==
# "HIGH_VOLATILITY"` string checks keep working unchanged.
#
# This is a SEPARATE, additive classifier combining ADX (trend
# strength), the same ATR-ratio volatility read, and Bollinger
# bandwidth percentile (compression/expansion) into 5 states instead
# of a binary trending/ranging split. It also requires a raw reading
# to repeat for REGIME_PERSISTENCE_BARS consecutive calls before the
# "confirmed" state switches, so weighting/probability corrections
# downstream don't flap on a single noisy bar right at a threshold.
#
# States:
#   TRENDING_CALM     - ADX confirms a trend, volatility normal
#   TRENDING_VOLATILE - ADX confirms a trend, but volatility is elevated
#                        (today's system treats this identically to
#                        TRENDING_CALM -- this is the actual gap being
#                        closed here)
#   RANGING_CALM      - no trend, volatility normal
#   CHOPPY            - no trend AND volatility elevated -- the worst
#                        regime for both trend-following and oscillator
#                        reads; today's binary split just falls back to
#                        "favor oscillators" here, which is wrong
#   SQUEEZE           - Bollinger bandwidth in the bottom of its own
#                        recent range -- pre-breakout compression,
#                        doesn't exist as a state today at all
# ============================================================

REGIME_PERSISTENCE_BARS = 3
_REGIME_STATES = ("TRENDING_CALM", "TRENDING_VOLATILE", "RANGING_CALM", "CHOPPY", "SQUEEZE")

_REGIME_HISTORY: Dict[str, List[str]] = {}
_REGIME_CONFIRMED: Dict[str, str] = {}
_REGIME_LOCK = threading.Lock()


def _bb_bandwidth_percentile(close_prices: List[float], current_bandwidth: float,
                              lookback_bars: int = 80, bb_period: int = 20,
                              bb_std: float = 2.0) -> float:
    """Percentile rank (0-1) of the current BB bandwidth within its own
    recent walk-forward history. Self-contained (no adaptive_thresholds
    import here, to avoid any cross-module import risk) -- cheap enough
    at these window sizes."""
    if len(close_prices) < bb_period + 10:
        return 0.5

    window_start = max(bb_period, len(close_prices) - lookback_bars)
    history = []
    for end in range(window_start, len(close_prices)):
        segment = close_prices[end - bb_period:end]
        if len(segment) < bb_period:
            continue
        # ✅ std_dev was hardcoded 2.0 while bb_period was already a
        # parameter -- so a caller passing the M1 period (50) still got
        # 2.0-sigma bands, mixing an M1 period with a non-M1 width.
        result = _calculate_bollinger_bands(segment, period=bb_period, std_dev=bb_std)
        if result and result[1]:
            history.append(result[5])  # width

    if len(history) < 10:
        return 0.5

    rank = sum(1 for v in history if v <= current_bandwidth) / len(history)
    return rank


def _raw_trading_regime(adx_value: float, atr_ratio: float, bandwidth_percentile: float,
                         trending_adx_threshold: float) -> str:
    """Single-bar regime read, before persistence smoothing."""
    is_trending = adx_value >= trending_adx_threshold
    is_volatile = atr_ratio > 1.5
    is_quiet_range = atr_ratio < 0.9  # loosely "not elevated", used for squeeze gating

    if bandwidth_percentile <= 0.15 and is_quiet_range:
        return "SQUEEZE"
    if is_trending and is_volatile:
        return "TRENDING_VOLATILE"
    if is_trending:
        return "TRENDING_CALM"
    if is_volatile:
        return "CHOPPY"
    return "RANGING_CALM"


REGIME_CONFIRM_LOOKBACK_BARS = 8   # how far back to look for the last confirmed run


def _regime_read(rates, symbol: str, pip_size: float, timeframe: str = None) -> Optional[Dict[str, Any]]:
    """The unsmoothed regime of the last closed bar of `rates` and its inputs."""
    if rates is None or len(rates) < 60:
        return None
    window = rates[-120:] if len(rates) >= 120 else rates
    price_arrays = _extract_price_arrays(window)
    high_prices = list(price_arrays["high"])
    low_prices = list(price_arrays["low"])
    close_prices = list(price_arrays["close"])

    tr = []
    for i in range(1, len(close_prices)):
        hl = high_prices[i] - low_prices[i]
        hc = abs(high_prices[i] - close_prices[i - 1])
        lc = abs(low_prices[i] - close_prices[i - 1])
        tr.append(max(hl, hc, lc))
    if len(tr) < 14:
        return None

    atr = sum(tr[-14:]) / 14
    avg_range = sum(tr[-50:]) / min(50, len(tr))
    atr_ratio = (atr / avg_range) if avg_range > 0 else 1.0
    atr_pips = (atr / pip_size) if pip_size else 0.0
    adx_value = _calculate_adx(high_prices, low_prices, close_prices, period=14) or 0.0

    # period/std per timeframe (M1 uses 50 / 2.5), so this bandwidth is the
    # same number as indicators.bollinger_bands.width
    _bb_period = get_bb_period(timeframe) if timeframe else 20
    _bb_std = get_bb_std(timeframe) if timeframe else 2.0
    bb_result = _calculate_bollinger_bands(close_prices, period=_bb_period, std_dev=_bb_std)
    bb_bandwidth = bb_result[5] if bb_result else 0.0
    bandwidth_percentile = _bb_bandwidth_percentile(close_prices, bb_bandwidth, bb_period=_bb_period, bb_std=_bb_std)

    trending_adx_threshold = _get_adx_thresholds(symbol).get("trend", 25)
    return {
        "raw_state": _raw_trading_regime(adx_value, atr_ratio, bandwidth_percentile, trending_adx_threshold),
        "adx": adx_value, "atr_pips": atr_pips, "atr_ratio": atr_ratio,
        "bb_bandwidth": bb_bandwidth, "bb_bandwidth_percentile": bandwidth_percentile,
    }


def classify_trading_regime(rates: np.ndarray, symbol: str = "DEFAULT",
                             pip_size: float = 0.0001,
                             timeframe: str = None) -> Dict[str, Any]:
    """
    Multi-factor trading regime classifier -- see module comment above.

    `state` is the regime of the most recent run of REGIME_PERSISTENCE_BARS
    consecutive closed BARS that all read the same (looking back up to
    REGIME_CONFIRM_LOOKBACK_BARS); `raw_state` is the last bar alone.

    ✅ FIXED (2026-09-15): the smoothing used to keep the last three CALLS
    per symbol in a module-level history. A monitor analysing every few
    seconds confirmed a regime within seconds of it appearing -- the same
    bar read three times -- while a replay stepping every 15 minutes needed
    45 minutes, and a restarted process started unconfirmed. The same bars
    now always give the same state.
    """
    default = {
        "state": "RANGING_CALM", "raw_state": "RANGING_CALM", "confirmed": False,
        "adx": 0.0, "atr_pips": 0.0, "atr_ratio": 1.0, "bb_bandwidth": 0.0,
        "bb_bandwidth_percentile": 0.5,
    }
    if rates is None or len(rates) < 60:
        return default
    try:
        current = _regime_read(rates, symbol, pip_size, timeframe)
        if current is None:
            return default
        reads = [current["raw_state"]]
        n = len(rates)
        for back in range(1, REGIME_CONFIRM_LOOKBACK_BARS + REGIME_PERSISTENCE_BARS - 1):
            if n - back < 60:
                break
            prior = _regime_read(rates[:n - back], symbol, pip_size, timeframe)
            if prior is None:
                break
            reads.append(prior["raw_state"])
        confirmed_state, confirmed = current["raw_state"], False
        for start in range(0, len(reads) - REGIME_PERSISTENCE_BARS + 1):
            run = reads[start:start + REGIME_PERSISTENCE_BARS]
            if len(set(run)) == 1:
                confirmed_state, confirmed = run[0], True
                break
        return {
            "state": confirmed_state,
            "raw_state": current["raw_state"],
            "confirmed": confirmed,
            "adx": round(current["adx"], 1),
            "atr_pips": round(current["atr_pips"], 1),
            "atr_ratio": round(current["atr_ratio"], 2),
            "bb_bandwidth": round(current["bb_bandwidth"], 5),
            "bb_bandwidth_percentile": round(current["bb_bandwidth_percentile"], 2),
        }
    except Exception as e:
        logger.warning(f"[REGIME] classify_trading_regime error for {symbol}: {e}")
        return default


def clear_regime_history(symbol: str = None):
    """Reset persistence smoothing state -- useful for tests/backtests
    where the same symbol is replayed from scratch."""
    with _REGIME_LOCK:
        if symbol:
            _REGIME_HISTORY.pop(symbol, None)
            _REGIME_CONFIRMED.pop(symbol, None)
        else:
            _REGIME_HISTORY.clear()
            _REGIME_CONFIRMED.clear()


def clear_zone_metadata():
    global _zone_metadata_store
    _zone_metadata_store = ZoneMetadataStore()
    logger.info("[ZONE] Zone metadata cleared")


def get_zone_metadata_status() -> Dict[str, Any]:
    metadata = _zone_metadata_store.get_all()
    return {
        "total_zones": len(metadata),
        "zones": list(metadata.keys())[:20],
        "zone_details": metadata
    }


def clear_zone_persistence(symbol: str = None):
    _clear_persistent_zone(symbol)


def get_zone_persistence_status() -> Dict[str, Any]:
    with _ZONE_PERSISTENCE_LOCK:
        status = {}
        for sym, data in _ZONE_PERSISTENCE.items():
            status[sym] = {
                "zone_grade": data.get("zone_grade"),
                "zone_level": data.get("zone_level"),
                "cached_at": data.get("cached_at"),
                "age_seconds": int(time.time() - data.get("cached_at", 0)) if data.get("cached_at") else 0
            }
        return {
            "persistence_enabled": True,
            "persistence_seconds": ZONE_PERSISTENCE_SECONDS,
            "cached_symbols": list(_ZONE_PERSISTENCE.keys()),
            "details": status
        }


# ============================================================
# FINAL DECISION FUNCTIONS
# ============================================================

def get_decision_action(probability: float, is_at_zone: bool) -> Dict[str, Any]:
    if probability >= DECISION_STRONG_ENTRY and is_at_zone:
        return {"action": "STRONG_BUY", "execution": "IMMEDIATE", "star_rating": 5, "stars": "★★★★★"}
    elif probability >= DECISION_ENTRY_WITH_ZONE and is_at_zone:
        return {"action": "BUY", "execution": "IMMEDIATE", "star_rating": 4, "stars": "★★★★☆"}
    elif probability >= DECISION_ENTRY_WITH_ZONE:
        return {"action": "BUY", "execution": "WAIT_FOR_ZONE", "star_rating": 3, "stars": "★★★☆☆"}
    elif probability >= DECISION_WAIT_THRESHOLD:
        return {"action": "WAIT", "execution": "MONITOR", "star_rating": 2, "stars": "★★☆☆☆"}
    elif probability >= DECISION_MONITOR_THRESHOLD:
        return {"action": "MONITOR", "execution": "NO_ACTION", "star_rating": 1, "stars": "★☆☆☆☆"}
    else:
        return {"action": "SKIP", "execution": "NO_ACTION", "star_rating": 0, "stars": "☆☆☆☆☆"}


def make_final_decision(probability: float, is_at_zone: bool, direction: str = "BUY") -> Dict[str, Any]:
    action_result = get_decision_action(probability, is_at_zone)
    return {
        "decision": f"{direction}_{action_result['action']}" if action_result['action'] not in ["SKIP", "MONITOR", "WAIT"] else action_result['action'],
        "action": action_result['action'],
        "execution": action_result['execution'],
        "star_rating": action_result['star_rating'],
        "stars": action_result['stars'],
        "probability": probability,
        "is_at_zone": is_at_zone
    }


# ============================================================
# EXPOSE MACD SCORING FOR INDICATOR SCORES
# ============================================================

def get_macd_indicator_score(
    macd_line: float, 
    signal_line: float, 
    histogram: float, 
    macd_signal: str,
    prev_histogram: float = None,
    trend_strength: float = 0
) -> Dict[str, Any]:
    return _score_macd_with_recovery(
        macd_line, signal_line, histogram, prev_histogram, macd_signal, trend_strength
    )


# ============================================================
# EXPOSE STOCHASTIC DIVERGENCE FOR USE IN ASSET ANALYSIS
# ============================================================

def get_stochastic_divergence(symbol: str, timeframe: str = "M15") -> Dict[str, Any]:
    try:
        tf_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1
        }
        
        mt5_tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M15)
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 200)
        
        if rates is None or len(rates) < 100:
            return {"divergence_type": "NONE", "divergence_score": 0, "stoch_k": 50, "stoch_d": 50}
        
        close_prices = [float(bar[4]) for bar in rates]
        high_prices = [float(bar[2]) for bar in rates]
        low_prices = [float(bar[3]) for bar in rates]
        
        stoch_k, stoch_d, _, _ = _calculate_stochastic(high_prices, low_prices, close_prices)
        
        k_values = []
        k_period = STOCH_K
        
        for i in range(k_period - 1, len(close_prices)):
            period_high = max(high_prices[i - k_period + 1:i + 1])
            period_low = min(low_prices[i - k_period + 1:i + 1])
            
            if period_high == period_low:
                k = 50.0
            else:
                k = 100 * (close_prices[i] - period_low) / (period_high - period_low)
            k_values.append(k)
        
        divergence = _detect_stochastic_divergence(close_prices, k_values, timeframe)
        
        current_k = k_values[-1] if k_values else 50
        current_d = stoch_d if stoch_d else 50
        
        return {
            "divergence_type": divergence["type"],
            "divergence_score": divergence["score"],
            "stoch_k": round(current_k, 1),
            "stoch_d": round(current_d, 1),
            "timeframe": timeframe
        }
        
    except Exception as e:
        logger.error(f"[STOCH_DIVERGENCE] Error for {symbol}: {e}")
        return {"divergence_type": "NONE", "divergence_score": 0, "stoch_k": 50, "stoch_d": 50}


# ============================================================
# END OF FILE 
# ============================================================