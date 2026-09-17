# ============================================================
# CORE PATTERN RECOGNITION SYSTEM - V11 (COMPLETE FIX)
# ============================================================
# FILE: core/patterns.py
#
# ✅ ALL FIXES APPLIED:
# 1. Volume threshold: 0.6 → 0.3
# 2. Proximity: SIGNIFICANTLY increased for ALL timeframes
# 3. Freshness: Increased for ALL timeframes
# 4. Min size: Drastically reduced for ALL patterns
# 5. Min bars M1: Drastically reduced
# 6. Swing lookback: 3 → 2
# 7. Trend requirements: FULLY RELAXED (allow ALL trends)
# 8. ABC tolerance: 30% → 50%
# 9. Triangle compression: 60% → 70%
# 10. Volume spike threshold: 1.5 → 1.2
# 11. Min swing size M1: 0.0002 → 0.0001
# 12. Max patterns: 3 → 8
# 13. Shoulder symmetry M1: 20% → 30%
# 14. Neckline tolerance: 0 → 0.0005
# 15. Double bottom breakout: 1x → 2x proximity
# 16. ✅ PRECISE ELLIOTT ENTRY TIMING
# 17. ✅ ALL PATTERNS INCLUDED: Ascending & Descending Triangles
# 18. ✅ FORCE DETECTION for debugging patterns
# ============================================================

import numpy as np
from typing import Dict, Any, List, Optional, Tuple, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import Counter
import logging
import math
from enum import Enum

# ============================================================
# ✅ IMPORT FROM UNIFIED CONFIG
# ============================================================
from core.asset_analysis_config import (
    PATTERN_CONFIDENCE_THRESHOLDS,
    PATTERN_MAX_AGE_BARS,
    PATTERN_PROXIMITY_PIPS,
    PATTERN_MIN_SIZE_PIPS,
    PATTERN_MIN_BARS_M1,
    PATTERN_VOLUME_CONFIRMATION_THRESHOLD,
    MAX_PATTERNS_PER_TIMEFRAME,
    PATTERN_WEIGHT,
    ELLIOTT_WAVE_RECOMMENDATIONS,
    get_pattern_min_bars_m1,
    get_pattern_min_size_pips,
    get_pattern_confidence_threshold,
    get_pattern_proximity_pips,
    get_pattern_freshness_bars,
    get_elliott_wave_recommendation,
    RANGING_MARKET_ADX_THRESHOLD,
)

# ✅ Single source of truth for swing-high/low detection — shared with
# indicators.py's supply/demand zone detection instead of each file
# keeping its own (previously divergent, both buggy) copy.
from core.swing_points import find_swing_points, get_min_swing_size

logger = logging.getLogger(__name__)

# ============================================================
# ENUMS
# ============================================================

class PatternType(Enum):
    """Classical chart pattern types."""
    DOUBLE_BOTTOM = "double_bottom"
    DOUBLE_TOP = "double_top"
    HEAD_SHOULDERS = "head_shoulders"
    INVERSE_HEAD_SHOULDERS = "inverse_head_shoulders"
    TRIANGLE_ASCENDING = "triangle_ascending"
    TRIANGLE_DESCENDING = "triangle_descending"
    TRIANGLE_SYMMETRICAL = "triangle_symmetrical"
    FLAG_BULLISH = "flag_bullish"
    FLAG_BEARISH = "flag_bearish"
    PENNANT_BULLISH = "pennant_bullish"
    PENNANT_BEARISH = "pennant_bearish"
    WEDGE_RISING = "wedge_rising"
    WEDGE_FALLING = "wedge_falling"
    RECTANGLE = "rectangle"
    ABC_CORRECTION = "abc_correction"
    ELLIOTT_WAVE = "elliott_wave"
    MEAN_REVERSION = "mean_reversion"


class ElliottWaveType(Enum):
    """Elliott Wave types."""
    WAVE_1 = "wave_1"
    WAVE_2 = "wave_2"
    WAVE_3 = "wave_3"
    WAVE_4 = "wave_4"
    WAVE_5 = "wave_5"
    WAVE_A = "wave_a"
    WAVE_B = "wave_b"
    WAVE_C = "wave_c"
    WAVE_X = "wave_x"
    IMPULSE = "impulse"
    CORRECTIVE = "corrective"
    DIAGONAL = "diagonal"
    TRIANGLE = "triangle"


class Regime(Enum):
    """Market regime types."""
    NORMAL = "NORMAL"
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    BREAKOUT = "BREAKOUT"
    BREAKDOWN = "BREAKDOWN"
    ACCUMULATION = "ACCUMULATION"
    DISTRIBUTION = "DISTRIBUTION"


class PatternStatus(Enum):
    """Pattern completion status."""
    COMPLETE = "COMPLETE"
    FORMING = "FORMING"
    BROKEN = "BROKEN"
    HISTORICAL = "HISTORICAL"


class PatternClassification(Enum):
    """Pattern type classification."""
    REVERSAL = "REVERSAL"
    CONTINUATION = "CONTINUATION"
    NEUTRAL = "NEUTRAL"


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Pattern:
    """Pattern detection result."""
    type: PatternType
    detected: bool
    confidence: float
    description: str
    timeframe: str = "M1"
    direction: str = "NEUTRAL"
    price_level: Optional[float] = None
    status: str = "UNKNOWN"
    status_description: str = ""
    pattern_classification: str = "NEUTRAL"
    reversal_from: Optional[str] = None
    reversal_to: Optional[str] = None
    continues_trend: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ElliottWave:
    """Elliott Wave analysis result - CLEAN VERSION with entry timing."""
    wave_type: ElliottWaveType
    detected: bool
    confidence: float
    wave_count: int = 0
    current_wave: str = ""
    next_wave: str = ""
    description: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""
    action: str = ""
    direction: str = ""
    confidence_score: int = 0
    reason: str = ""
    entry_timing: str = "WAIT"
    entry_condition: str = ""
    confirmation_status: Dict[str, bool] = field(default_factory=dict)
    entry_window_pips: float = 0.0
    time_to_entry_estimate: str = ""
    # ✅ FIXED: entry_price/target/fib_levels were computed in
    # analyze_elliott_waves_enhanced()'s wave_data dict and used to derive
    # entry_timing/entry_condition text (via distance_to_entry_pips), but
    # the raw numeric values themselves were never stored anywhere on the
    # final ElliottWave object — not even in `details`, which is never
    # populated anywhere in this file. Every consumer downstream got a
    # text description ("Wait for pullback to Wave 1 low") with no way to
    # act on it programmatically. Now preserved directly.
    entry_price: Optional[float] = None
    target_price: Optional[float] = None
    fib_levels: Dict[str, float] = field(default_factory=dict)


@dataclass
class VolumeTracking:
    """Volume tracking results."""
    volume_ratio: List[Dict] = field(default_factory=list)
    volume_spikes: List[Dict] = field(default_factory=list)
    volume_trend: str = "stable"
    average_volume: float = 0.0
    max_volume: float = 0.0
    min_volume: float = 0.0
    diagnosis: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RegimeTracking:
    """Market regime tracking."""
    regime_at_entry: str = Regime.NORMAL.value
    regime_at_exit: str = Regime.NORMAL.value
    regime_changes: List[Dict] = field(default_factory=list)
    regime_duration: Dict[str, int] = field(default_factory=dict)
    diagnosis: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SignalTracking:
    """Signal evolution tracking."""
    signals: List[Dict] = field(default_factory=list)
    signal_changes: List[Dict] = field(default_factory=list)
    signal_consistency: float = 0.0
    diagnosis: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class InstitutionalBehavior:
    """Institutional behavior analysis."""
    stop_hunting: Dict = field(default_factory=dict)
    liquidity_grabbing: Dict = field(default_factory=dict)
    institutional_distribution: Dict = field(default_factory=dict)
    institutional_accumulation: Dict = field(default_factory=dict)
    overall_institutional_activity: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PatternAnalysis:
    """Complete pattern analysis."""
    patterns: Dict[str, Dict] = field(default_factory=dict)
    pattern_confidence: Dict[str, float] = field(default_factory=dict)
    pattern_count: int = 0
    pattern_summary: str = ""
    elliott_waves: List[ElliottWave] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class HiddenGem:
    """Hidden gem pattern detection."""
    type: str
    description: str
    confidence: float
    implication: str
    action: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictiveSignals:
    """Predictive signals for early warning."""
    early_warnings: List[Dict] = field(default_factory=list)
    reversal_signals: List[Dict] = field(default_factory=list)
    signal_quality: float = 0.0
    prediction_accuracy: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ============================================================
# CONSTANTS - ALL FIXED
# ============================================================

HIDDEN_GEM_PATTERNS = {
    'institutional_accumulation': {
        'description': 'Institutional accumulation detected',
        'confidence': 0.75,
        'implication': 'Smart money is accumulating',
        'action': 'Buy the dip near support'
    },
    'liquidity_sweep': {
        'description': 'Liquidity sweep detected',
        'confidence': 0.75,
        'implication': 'Liquidity was swept, price will likely reverse',
        'action': 'Trade the reversal from the sweep level'
    },
    'algorithmic_trap': {
        'description': 'Algorithmic trap detected',
        'confidence': 0.70,
        'implication': 'Price is being manipulated by algorithms',
        'action': 'Avoid trading here, wait for confirmation'
    },
    'smart_money_divergence': {
        'description': 'Smart money divergence detected',
        'confidence': 0.70,
        'implication': 'Smart money is selling into strength',
        'action': 'Consider selling the rally'
    },
    'fvg_trap': {
        'description': 'FVG trap detected',
        'confidence': 0.70,
        'implication': 'Price may fill the FVG then reverse',
        'action': 'Wait for FVG fill then trade the reversal'
    },
    'absorption': {
        'description': 'Institutional absorption detected',
        'confidence': 0.80,
        'implication': 'Large players absorbing orders',
        'action': 'Enter with the institutions'
    },
    'iceberg': {
        'description': 'Iceberg order detection',
        'confidence': 0.65,
        'implication': 'Large hidden orders in the market',
        'action': 'Trade with the iceberg direction'
    },
    'dark_pool': {
        'description': 'Dark pool activity detected',
        'confidence': 0.60,
        'implication': 'Off-exchange institutional trading',
        'action': 'Follow dark pool buying/selling'
    }
}

FIBONACCI_LEVELS = {
    0.0: "0",
    0.236: "23.6%",
    0.382: "38.2%",
    0.5: "50%",
    0.618: "61.8%",
    0.786: "78.6%",
    1.0: "100%",
    1.272: "127.2%",
    1.618: "161.8%",
    2.0: "200%",
    2.618: "261.8%",
    3.618: "361.8%"
}

# MIN_BARS - base values (timeframe-specific applied later) - DRASTICALLY REDUCED
MIN_BARS = {
    PatternType.DOUBLE_BOTTOM: 15,  # was 30
    PatternType.DOUBLE_TOP: 15,     # was 30
    PatternType.HEAD_SHOULDERS: 25, # was 50
    PatternType.INVERSE_HEAD_SHOULDERS: 25, # was 50
    PatternType.TRIANGLE_ASCENDING: 20, # was 40
    PatternType.TRIANGLE_DESCENDING: 20, # was 40
    PatternType.TRIANGLE_SYMMETRICAL: 20, # was 40
    PatternType.FLAG_BULLISH: 12,   # was 20
    PatternType.FLAG_BEARISH: 12,   # was 20
    PatternType.PENNANT_BULLISH: 15, # was 25
    PatternType.PENNANT_BEARISH: 15, # was 25
    PatternType.WEDGE_RISING: 15,   # was 30
    PatternType.WEDGE_FALLING: 15,  # was 30
    PatternType.RECTANGLE: 20,      # was 40
    PatternType.ABC_CORRECTION: 12, # was 25
    PatternType.ELLIOTT_WAVE: 40,   # was 60
    PatternType.MEAN_REVERSION: 8   # was 15
}

# ✅ FIXED: Volume spike thresholds lowered
VOLUME_SPIKE_THRESHOLD = 1.2
VOLUME_EXTREME_SPIKE_THRESHOLD = 2.0

# ✅ FIXED: Volume confirmation threshold lowered to 0.3
VOLUME_CONFIRMATION_THRESHOLD = PATTERN_VOLUME_CONFIRMATION_THRESHOLD

# PATTERN_PROXIMITY_PIPS, PATTERN_MAX_AGE_BARS, and PATTERN_MIN_SIZE_PIPS
# used to be redefined here, which silently shadowed the "unified
# config" versions imported above -- asset_analysis_config.py's copies
# were then never updated when these were tightened, so callers reading
# straight from the config module (e.g. asset_analysis.py's confidence
# gate) kept using stale, much looser values while this module used the
# tightened ones internally. That divergence is a large part of why
# RECTANGLE patterns were surfacing so often, from so far off current
# price: this module's own detectors were filtering correctly, but the
# threshold deciding what actually got published to the caller was not.
# These three constants now live only in asset_analysis_config.py --
# do not redefine them here.

# Minimum swing size now lives in core/swing_points.py (single source of
# truth, shared with indicators.py's zone detection). See MIN_SWING_SIZE_PIPS
# / get_min_swing_size() there.

# ✅ FIXED: (strong_pips, weak_pips) EMA20/EMA50 gap thresholds used by
# _get_trend_context() ONLY when no external_trend was supplied. Replaces
# a flat 0.3% threshold (~34 pips on EURUSD) that almost never fired on
# M1, where the main trend-bias engine already calls a 1-3 pip EMA gap
# "STRONG_BEARISH/BULLISH".
TREND_CONTEXT_PIP_THRESHOLDS = {
    "M1": (3.0, 0.8),
    "M5": (5.0, 1.5),
    "M15": (8.0, 2.5),
    "M30": (12.0, 4.0),
    "H1": (18.0, 6.0),
    "DEFAULT": (10.0, 3.0),
}

# ✅ FIXED: max acceptable 10-bar range for a rectangle to count as
# "consolidation", in pips. Was a flat 2% of price (~227 pips on
# EURUSD around 1.137), which never filters anything on FX pairs — a
# rectangle could be "detected" inside a clearly trending 10-bar move
# as long as it stayed under ~227 pips, which on M1 it basically
# always does.
RECTANGLE_MAX_RANGE_PIPS = {
    "M1": 15.0,
    "M5": 25.0,
    "M15": 40.0,
    "M30": 60.0,
    "H1": 100.0,
    "DEFAULT": 30.0,
}

# ✅ FIXED: mean-reversion "mean" was the average of the ENTIRE fetched
# price history (often 500 bars — many hours on M1), not a local/recent
# mean. A signal is only actionable if it's reverting toward something
# nearby, not a stale long-run average. MEAN_REVERSION_WINDOW bounds how
# far back that average looks; MEAN_REVERSION_MIN_DEVIATION_PIPS replaces
# the old flat 0.3% threshold (~34 pips on EURUSD, unreachable on a quiet
# M1 local window) with a pip-based, timeframe-aware one.
MEAN_REVERSION_WINDOW = {
    "M1": 20,
    "M5": 30,
    "M15": 40,
    "M30": 50,
    "H1": 60,
    "DEFAULT": 30,
}
MEAN_REVERSION_MIN_DEVIATION_PIPS = {
    "M1": 3.0,
    "M5": 5.0,
    "M15": 8.0,
    "M30": 12.0,
    "H1": 18.0,
    "DEFAULT": 8.0,
}

# ✅ MODERATE TIGHTENING (was "loosened for M1" to 10% - two lows/highs
# 10% apart barely register as a matching "double" anymore).
# diff_pct: how far apart the two lows/highs may be (%)
# between_factor: how far price must move between the two lows/highs
DOUBLE_PATTERN_TOLERANCE = {
    # ✅ FIXED: between_factor was 1.05/1.03/1.02 -- interpreted as a
    # direct multiplier on raw price, that requires the peak between the
    # two lows to sit 2-5% ABOVE the low just to count as a real
    # separating resistance. For a EURUSD-scale price (~1.10), that's a
    # ~550-pip requirement on M1 and 220+ pips even on H1 -- essentially
    # unmeetable by normal price action, so both _detect_double_bottom
    # and _detect_double_top were silently near-dead regardless of what
    # the market did (same category of units-confusion bug as the
    # diff_pct/min_size mismatch already fixed a few lines below in this
    # same function). Values below are divided by ~25x, which preserves
    # the exact 5:3:2:2:2 relative scaling across timeframes the
    # original clearly intended (more separation required to filter
    # noise on lower timeframes) while landing in a pip range real price
    # action can actually reach (e.g. M1: ~22 pips on a 1.10 price,
    # rather than ~550).
    "M1": {"diff_pct": 6.0, "between_factor": 1.0020},
    "M5": {"diff_pct": 5.0, "between_factor": 1.0012},
    "M15": {"diff_pct": 4.0, "between_factor": 1.0008},
    "M30": {"diff_pct": 3.5, "between_factor": 1.0008},
    "H1": {"diff_pct": 3.0, "between_factor": 1.0008},
}

# ✅ FIXED (Issue 6): Flag/Pennant pole-move requirement - loosened for M1
FLAG_POLE_MOVE_MIN = {
    "M1": 0.005,
    "M5": 0.008,
    "M15": 0.010,
    "M30": 0.012,
    "H1": 0.015,
}

SESSION_ADJUSTMENTS = {
    'LONDON_NY_OVERLAP': 1.10,
    'LONDON': 1.00,
    'NY': 1.00,
    'ASIA': 0.90,
    'WEEKEND': 0.80,
}

REGIME_ADJUSTMENTS = {
    'TRENDING': 1.05,
    'RANGING': 0.90,
    'HIGH_VOLATILITY': 0.85,
    'LOW_VOLATILITY': 1.10,
}

# ✅ NEW: pattern-classification-aware regime GATING -- separate from,
# and much stronger than, REGIME_ADJUSTMENTS above. REGIME_ADJUSTMENTS
# applies the SAME flat multiplier to every pattern regardless of
# whether that specific pattern is actually a good fit for the current
# regime (a breakout-style CONTINUATION pattern gets the identical
# 0.90x RANGING haircut as a mean-reversion-style REVERSAL pattern,
# even though the reversal pattern should be FAVORED in ranging
# conditions and the continuation pattern should be suppressed, not
# just mildly discounted). Weighting softens a bad-fit setup; gating
# stops it from firing at all. Applied in _apply_alignment_scoring()
# below, on top of REGIME_ADJUSTMENTS, keyed by
# (self._current_regime, pattern's own 'pattern_classification').
# NEUTRAL-classified patterns (symmetrical triangle, ABC correction,
# mean_reversion type) have no inherent regime-fit bias and aren't
# gated either way (fall through to the 1.0 default).
REGIME_CLASSIFICATION_GATE = {
    ('RANGING', 'CONTINUATION'): 0.25,    # breakout-style pattern fighting a ranging market
    ('RANGING', 'REVERSAL'): 1.20,        # mean-reversion-style pattern favored in ranging
    ('TRENDING', 'REVERSAL'): 0.25,       # reversal pattern fighting a trending market
    ('TRENDING', 'CONTINUATION'): 1.15,   # continuation pattern favored in a trend
}

# PATTERN_CONFIDENCE_THRESHOLDS and MAX_PATTERNS_PER_TIMEFRAME used to
# be redefined here too -- same shadowing bug described above where
# this import block loaded, at the top of this file. Both now live only
# in asset_analysis_config.py.

PATTERN_CLASSIFICATION = {
    'head_shoulders': {
        'type': 'REVERSAL',
        'direction': 'BEARISH',
        'requires_trend': 'BULLISH',
        'description': 'Reverses BULLISH trend to BEARISH'
    },
    'inverse_head_shoulders': {
        'type': 'REVERSAL',
        'direction': 'BULLISH',
        'requires_trend': 'BEARISH',
        'description': 'Reverses BEARISH trend to BULLISH'
    },
    'double_bottom': {
        'type': 'REVERSAL',
        'direction': 'BULLISH',
        'requires_trend': 'BEARISH',
        'description': 'Reverses BEARISH trend to BULLISH'
    },
    'double_top': {
        'type': 'REVERSAL',
        'direction': 'BEARISH',
        'requires_trend': 'BULLISH',
        'description': 'Reverses BULLISH trend to BEARISH'
    },
    'wedge_rising': {
        'type': 'REVERSAL',
        'direction': 'BEARISH',
        'requires_trend': 'BULLISH',
        'description': 'Reverses BULLISH trend to BEARISH'
    },
    'wedge_falling': {
        'type': 'REVERSAL',
        'direction': 'BULLISH',
        'requires_trend': 'BEARISH',
        'description': 'Reverses BEARISH trend to BULLISH'
    },
    'rectangle': {
        'type': 'CONTINUATION',
        'direction': 'FOLLOWS_TREND',
        'requires_trend': None,
        'description': 'Continues the current trend'
    },
    'triangle_ascending': {
        'type': 'CONTINUATION',
        'direction': 'FOLLOWS_TREND',
        'requires_trend': None,
        'description': 'Continues the current trend'
    },
    'triangle_descending': {
        'type': 'CONTINUATION',
        'direction': 'FOLLOWS_TREND',
        'requires_trend': None,
        'description': 'Continues the current trend'
    },
    'flag_bullish': {
        'type': 'CONTINUATION',
        'direction': 'FOLLOWS_TREND',
        'requires_trend': None,
        'description': 'Continues the current trend'
    },
    'flag_bearish': {
        'type': 'CONTINUATION',
        'direction': 'FOLLOWS_TREND',
        'requires_trend': None,
        'description': 'Continues the current trend'
    },
    'pennant_bullish': {
        'type': 'CONTINUATION',
        'direction': 'FOLLOWS_TREND',
        'requires_trend': None,
        'description': 'Continues the current trend'
    },
    'pennant_bearish': {
        'type': 'CONTINUATION',
        'direction': 'FOLLOWS_TREND',
        'requires_trend': None,
        'description': 'Continues the current trend'
    },
    'triangle_symmetrical': {
        'type': 'NEUTRAL',
        'direction': 'NEUTRAL',
        'requires_trend': None,
        'description': 'Neutral pattern, waiting for breakout'
    },
    'abc_correction': {
        'type': 'NEUTRAL',
        'direction': 'NEUTRAL',
        'requires_trend': None,
        'description': 'Corrective pattern'
    },
    'mean_reversion': {
        'type': 'NEUTRAL',
        'direction': 'NEUTRAL',
        'requires_trend': None,
        'description': 'Mean reversion pattern'
    },
}


# ============================================================
# MAIN PATTERN RECOGNITION CLASS
# ============================================================

class PatternRecognizer:
    """Complete pattern recognition system."""

    def __init__(self):
        self._patterns_cache = {}
        self._elliot_cache = {}
        self._last_analysis_time = 0
        self._analysis_interval = 60
        self._current_timeframe = "M1"
        self._current_price = 0.0
        self._current_session = "LONDON"
        self._current_regime = "NORMAL"
        self._price_history = []
        self._volume_history = []
        self._external_rsi = None

    def _get_trend_context(self, prices: List[float], use_external: bool = True) -> Dict[str, Any]:
        """Get current trend context for pattern direction.

        use_external: True for "what is the trend right now" queries (safe
        to prefer the externally-injected authoritative trend). Several
        call sites instead ask "what was the trend BEFORE this pattern
        formed" by deliberately passing an earlier, truncated price slice
        (pre_pattern_prices / prices[:-20] etc.) to validate reversal
        patterns like head-and-shoulders — those must always compute
        locally from the given slice, since the current external trend
        describes now, not the market state at that earlier point. Passing
        use_external=True there would silently answer a different
        question than the one being asked.
        """
        if use_external and getattr(self, '_external_trend', None):
            return {'trend': self._external_trend, 'strength': getattr(self, '_external_trend_strength', 0)}

        if len(prices) < 50:
            return {'trend': 'NEUTRAL', 'strength': 0}

        ema_20 = sum(prices[-20:]) / 20
        ema_50 = sum(prices[-50:]) / 50

        # Pip-based, timeframe-aware thresholds (see TREND_CONTEXT_PIP_THRESHOLDS)
        # instead of a flat 0.3% EMA-gap threshold (~34 pips on EURUSD),
        # which almost never fired on M1.
        pip_size = getattr(self, '_current_pip_size', 0.0001) or 0.0001
        gap_pips = abs(ema_20 - ema_50) / pip_size

        strong_pips, weak_pips = TREND_CONTEXT_PIP_THRESHOLDS.get(
            getattr(self, '_current_timeframe', 'M1'), TREND_CONTEXT_PIP_THRESHOLDS['DEFAULT']
        )

        if ema_20 > ema_50:
            trend = 'STRONG_BULLISH' if gap_pips >= strong_pips else ('BULLISH' if gap_pips >= weak_pips else 'NEUTRAL')
        elif ema_20 < ema_50:
            trend = 'STRONG_BEARISH' if gap_pips >= strong_pips else ('BEARISH' if gap_pips >= weak_pips else 'NEUTRAL')
        else:
            trend = 'NEUTRAL'

        return {'trend': trend, 'strength': gap_pips}

    def _get_pattern_classification(self, pattern_name: str) -> Dict[str, Any]:
        """Get pattern classification."""
        return PATTERN_CLASSIFICATION.get(pattern_name, {
            'type': 'UNKNOWN',
            'direction': 'NEUTRAL',
            'requires_trend': None,
            'description': 'Unknown pattern type'
        })

    def _get_min_bars_for_timeframe(self, pattern_type: PatternType, timeframe: str) -> int:
        """Get timeframe-appropriate minimum bars.

        ✅ FIXED: this used to hand-duplicate all 14 M1 minimum-bar values
        in a local dict (m1_reductions) that happened to match
        PATTERN_MIN_BARS_M1 in config -- same shape as the H1-alignment
        duplication bug fixed earlier this session: two independently-
        maintained copies of the same numbers that currently agree by
        coincidence, not by construction. Now delegates to
        get_pattern_min_bars_m1() (imported, previously unused) so tuning
        a value in config actually takes effect here instead of needing
        the same edit made twice.
        """
        base_min = MIN_BARS.get(pattern_type, 30)

        if timeframe == "M1":
            return get_pattern_min_bars_m1(pattern_type.name) if pattern_type.name in PATTERN_MIN_BARS_M1 \
                else max(4, base_min // 2)

        return base_min

    # ============================================================
    # ELLIOTT WAVE RECOMMENDATIONS - WITH PRECISE ENTRY TIMING
    # ============================================================

    # Used by _get_elliott_wave_recommendation to make BUY/SELL wording
    # match the real detected wave direction. The branches below are
    # written assuming a bullish impulse / bearish correction (the most
    # common textbook framing); when the actual detected wave runs the
    # other way, this flips every direction-bearing word in the result.
    _ELLIOTT_DIRECTION_FLIP = {
        'BUY': 'SELL', 'SELL': 'BUY',
        'STRONG_BUY': 'STRONG_SELL', 'STRONG_SELL': 'STRONG_BUY',
        'BUY NOW': 'SELL NOW', 'SELL NOW': 'BUY NOW',
        'BULLISH': 'BEARISH', 'BEARISH': 'BULLISH',
    }

    # The direction each branch below is WRITTEN assuming (impulse
    # branches assume a bullish impulse, corrective branches assume a
    # bearish correction — the common textbook framing). Used by the
    # flip logic at the end of _get_elliott_wave_recommendation: if the
    # actually-detected wave_direction differs from this, every
    # direction-bearing word gets flipped. Comparing against this fixed
    # per-type assumption (rather than against the branch's own
    # result["direction"]) is what makes the flip work correctly for
    # BOTH continuation calls (waves 1/3/5/A, where the recommendation
    # direction matches the wave's own direction) AND reversal calls
    # (wave C, where the recommendation is deliberately the OPPOSITE of
    # the correction's own direction) — see the Wave C branch below.
    _ELLIOTT_TEXTBOOK_DIRECTION = {
        "impulse": "BULLISH",
        "corrective": "BEARISH",
    }

    def _get_elliott_wave_recommendation(
        self, 
        wave_type: str, 
        current_wave: str, 
        confidence: float,
        current_price: float = None,
        wave_data: Dict = None,
        prices: List[float] = None,
        pip_size: float = 0.001,
        wave_direction: str = None,
        adx: float = 0.0
    ) -> Dict[str, Any]:
        """Get trading recommendation with PRECISE ENTRY TIMING.

        wave_direction: the ACTUAL detected direction ('BULLISH'/'BEARISH')
        from _detect_impulse_waves / _detect_corrective_waves / etc. Every
        branch below is written assuming a bullish impulse wave and a
        bearish correction (the common textbook case); if the real
        detected wave runs the other way, the result is flipped before
        returning. Without this, every impulse wave was reported as a BUY
        and every A-B-C correction as a SELL regardless of which way price
        actually moved — a critical precision bug for entries.
        """
        result = {
            "recommendation": "",
            "action": "",
            "direction": "",
            "confidence_score": 0,
            "reason": "",
            "entry_timing": "WAIT",
            "entry_condition": "",
            "confirmation_status": {
                "price_aligned": False,
                "volume_confirmed": False,
                "trend_confirmed": False,
                "momentum_confirmed": False,
                "fvg_confirmed": False
            },
            "entry_window_pips": 0.0,
            "time_to_entry_estimate": ""
        }

        if current_price is None:
            current_price = 1.0

        if prices is None or len(prices) < 10:
            prices = [current_price] * 10

        momentum = 0
        if len(prices) >= 5:
            momentum = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0

        entry_price = None
        if wave_data:
            entry_price = wave_data.get('entry_price')
        
        distance_to_entry_pips = 0
        if entry_price and pip_size > 0:
            distance_to_entry_pips = abs(entry_price - current_price) / pip_size

        # IMPULSE WAVES
        if wave_type == "impulse":
            if current_wave == "1":
                # ✅ FIXED (2026-09-15): was BUY NOW. Wave 1 is only a wave 1 once wave 2 holds and wave 3 breaks out; calling it live is a guess.
                result["recommendation"] = "WAIT"
                result["action"] = "WAIT"
                result["direction"] = "NEUTRAL"
                result["confidence_score"] = 0
                result["reason"] = "Wave 1: unconfirmed until wave 2 holds -- not an entry"

            elif current_wave == "2":
                result["recommendation"] = "WAIT"
                result["action"] = "WAIT"
                result["direction"] = "NEUTRAL"
                result["confidence_score"] = 0
                result["reason"] = "Wave 2: Correction - wait for completion"
                result["entry_timing"] = "WAIT"
                result["entry_condition"] = "Wait for 0.618 retracement of Wave 1"
                result["time_to_entry_estimate"] = "30-60 minutes"

            elif current_wave == "3":
                result["recommendation"] = "STRONG_BUY"
                result["action"] = "BUY NOW"
                result["direction"] = "BULLISH"
                result["confidence_score"] = min(95, confidence * 100 + 20)
                result["reason"] = "Wave 3: Most powerful impulse wave"
                
                if distance_to_entry_pips < 8:
                    result["entry_timing"] = "IMMEDIATE"
                    result["entry_condition"] = "Wave 3 breakout confirmed, enter now"
                    result["entry_window_pips"] = distance_to_entry_pips
                    result["time_to_entry_estimate"] = "Now"
                elif distance_to_entry_pips < 20:
                    result["entry_timing"] = "WITHIN_15_MIN"
                    result["entry_condition"] = "Wait for small pullback to enter Wave 3"
                    result["entry_window_pips"] = distance_to_entry_pips
                    result["time_to_entry_estimate"] = "5-15 minutes"
                else:
                    result["entry_timing"] = "WITHIN_30_MIN"
                    result["entry_condition"] = "Monitor for Wave 3 momentum confirmation"
                    result["entry_window_pips"] = distance_to_entry_pips
                    result["time_to_entry_estimate"] = "15-30 minutes"

            elif current_wave == "4":
                result["recommendation"] = "WAIT"
                result["action"] = "WAIT"
                result["direction"] = "NEUTRAL"
                result["confidence_score"] = 0
                result["reason"] = "Wave 4: Correction - wait for completion"
                result["entry_timing"] = "WAIT"
                result["entry_condition"] = "Wait for 0.382 retracement of Wave 3"
                result["time_to_entry_estimate"] = "30-60 minutes"

            elif current_wave == "5":
                # ✅ FIXED (2026-09-15): was BUY NOW. Wave 5 is the exhaustion leg of the impulse: entering continuation there buys the top.
                result["recommendation"] = "WAIT"
                result["action"] = "WAIT"
                result["direction"] = "NEUTRAL"
                result["confidence_score"] = 0
                result["reason"] = "Wave 5: final leg, exhaustion risk -- not a continuation entry"

        # CORRECTIVE WAVES
        elif wave_type == "corrective":
            if current_wave == "A":
                # ✅ FIXED (2026-09-15): was SELL NOW. Wave A is identified only after it completes; live it is indistinguishable from a pullback.
                result["recommendation"] = "WAIT"
                result["action"] = "WAIT"
                result["direction"] = "NEUTRAL"
                result["confidence_score"] = 0
                result["reason"] = "Wave A: identifiable only after completion -- not an entry"

            elif current_wave == "B":
                result["recommendation"] = "WAIT"
                result["action"] = "WAIT"
                result["direction"] = "NEUTRAL"
                result["confidence_score"] = 0
                result["reason"] = "Wave B: Counter-trend move - avoid"
                result["entry_timing"] = "WAIT"
                result["entry_condition"] = "Avoid Wave B counter-trend"
                result["time_to_entry_estimate"] = "30-60 minutes"

            elif current_wave == "C":
                # ✅ FIXED: this used to recommend STRONG_SELL ("Correction
                # completion") -- i.e. treat the END of the corrective
                # move as a signal to keep going in the correction's OWN
                # direction, with a confidence BOOST on top. That's
                # backwards: Wave C completing is, by definition, where
                # the correction is exhausted and the larger trend it
                # interrupted is due to resume. The textbook-correct call
                # at Wave C completion is a REVERSAL trade, opposite the
                # correction's own direction -- exactly the moment
                # reversal-sensitive indicators elsewhere in this system
                # (RSI, stochastic) are also likely calling a turn. Making
                # the highest-confidence Elliott call in the wrong
                # direction at exactly that moment is very likely the
                # single largest source of Elliott Wave output
                # contradicting the rest of the analysis.
                result["recommendation"] = "BUY"
                result["action"] = "BUY NOW"
                result["direction"] = "BULLISH"
                result["confidence_score"] = min(85, confidence * 100 + 10)
                result["reason"] = "Wave C: Correction likely complete -- expect reversal back toward the larger trend, not continuation"

                # Reversal entry is measured against where wave C is
                # projected to COMPLETE (the target the detector already
                # computed) rather than the level where wave C started --
                # that start level is stale by the time the correction
                # has run its course.
                reversal_ref_price = wave_data.get('target') if wave_data else None
                if reversal_ref_price and pip_size > 0:
                    distance_to_entry_pips = abs(reversal_ref_price - current_price) / pip_size

                if distance_to_entry_pips < 5:
                    result["entry_timing"] = "IMMEDIATE"
                    result["entry_condition"] = "Price at Wave C completion zone, reversal entry"
                    result["entry_window_pips"] = distance_to_entry_pips
                    result["time_to_entry_estimate"] = "Now"
                elif distance_to_entry_pips < 15:
                    result["entry_timing"] = "WITHIN_15_MIN"
                    result["entry_condition"] = "Wait for price to reach Wave C completion zone"
                    result["entry_window_pips"] = distance_to_entry_pips
                    result["time_to_entry_estimate"] = "5-15 minutes"
                elif distance_to_entry_pips < 30:
                    result["entry_timing"] = "WITHIN_30_MIN"
                    result["entry_condition"] = "Monitor for reversal confirmation near Wave C target"
                    result["entry_window_pips"] = distance_to_entry_pips
                    result["time_to_entry_estimate"] = "15-30 minutes"
                else:
                    result["entry_timing"] = "WITHIN_1_HOUR"
                    result["entry_condition"] = "Wait for Wave C completion and reversal confirmation"
                    result["entry_window_pips"] = distance_to_entry_pips
                    result["time_to_entry_estimate"] = "30-60 minutes"

        # OTHER WAVES
        elif wave_type == "diagonal":
            # ✅ FIXED: previously always NEUTRAL/WATCH regardless of the
            # diagonal's own detected direction. An ending diagonal signals
            # the CURRENT move (wave_direction) is exhausting — the
            # actionable implication is a reversal in the opposite
            # direction once it completes, not "no direction at all".
            result["recommendation"] = "WATCH"
            result["action"] = "WATCH"
            if wave_direction == "BEARISH":
                result["direction"] = "BULLISH"
                result["reason"] = "Ending diagonal (bearish move exhausting) - watch for bullish reversal"
            elif wave_direction == "BULLISH":
                result["direction"] = "BEARISH"
                result["reason"] = "Ending diagonal (bullish move exhausting) - watch for bearish reversal"
            else:
                result["direction"] = "NEUTRAL"
                result["reason"] = "Diagonal pattern - watch for reversal"
            result["confidence_score"] = min(50, confidence * 100)
            result["entry_timing"] = "WAIT"
            result["entry_condition"] = "Wait for diagonal breakout/breakdown"
            result["time_to_entry_estimate"] = "30-60 minutes"

        elif wave_type == "triangle":
            # ✅ FIXED: was hardcoded WAIT/NEUTRAL/0% unconditionally, with
            # no connection to wave_direction (which _detect_triangle_waves
            # now actually computes, based on where price sits inside the
            # narrowing range). Still fundamentally a "wait for the
            # breakout" pattern -- confidence stays capped low below --
            # but a triangle leaning toward its upper or lower boundary
            # says something about which way that breakout is more likely
            # to go, instead of saying nothing at all every single time.
            result["action"] = "WATCH"
            if wave_direction == "BULLISH":
                result["recommendation"] = "WATCH_BULLISH"
                result["direction"] = "BULLISH"
                result["reason"] = "Triangle apex forming -- price leaning toward the upper boundary, watch for bullish breakout"
            elif wave_direction == "BEARISH":
                result["recommendation"] = "WATCH_BEARISH"
                result["direction"] = "BEARISH"
                result["reason"] = "Triangle apex forming -- price leaning toward the lower boundary, watch for bearish breakdown"
            else:
                result["recommendation"] = "WAIT"
                result["direction"] = "NEUTRAL"
                result["reason"] = "Triangle mid-range -- no directional lean yet, wait for breakout"
            # Capped well below impulse/corrective: a pre-breakout
            # triangle is genuinely lower-conviction than a confirmed
            # 5-wave or 3-wave structure, by design -- this isn't a
            # placeholder value, it's an intentional ceiling.
            result["confidence_score"] = round(min(50, confidence * 100))
            result["entry_timing"] = "WAIT"
            result["entry_condition"] = "Wait for confirmed triangle breakout in the leaning direction"
            result["time_to_entry_estimate"] = "30-60 minutes"

        # ✅ FIXED: flip BUY/SELL/BULLISH/BEARISH wording to match the
        # ACTUAL detected wave direction. Only applies to impulse/
        # corrective, whose branches above are written assuming a fixed
        # textbook direction (bullish impulse / bearish correction);
        # diagonal already computes its own correct (reversal-implied)
        # direction and must not be re-flipped here.
        #
        # ✅ FIXED: this used to compare wave_direction against this
        # branch's own result["direction"], which only works for
        # CONTINUATION calls (waves 1/3/5/A, where the recommendation
        # direction equals the wave's own direction by construction). It
        # silently breaks for Wave C, whose recommendation is deliberately
        # the OPPOSITE of the correction's own direction (a reversal
        # call) -- comparing against result["direction"] there would flip
        # exactly when it shouldn't. Comparing against the wave TYPE's
        # fixed textbook assumption instead works correctly for both.
        textbook_dir = self._ELLIOTT_TEXTBOOK_DIRECTION.get(wave_type)
        if wave_type in ("impulse", "corrective") and wave_direction and textbook_dir \
                and wave_direction != textbook_dir:
            result["recommendation"] = self._ELLIOTT_DIRECTION_FLIP.get(result["recommendation"], result["recommendation"])
            result["action"] = self._ELLIOTT_DIRECTION_FLIP.get(result["action"], result["action"])
            result["direction"] = self._ELLIOTT_DIRECTION_FLIP.get(result["direction"], result["direction"])

        # CONFIRMATION STATUS
        # ✅ FIXED: moved to run AFTER the flip above (was before it) so
        # these checks are against the actual final recommended
        # direction, not the pre-flip textbook-template one -- otherwise
        # a flipped call could show "price_aligned: True" based on
        # momentum agreeing with the direction it was ABOUT to be
        # flipped away from.
        if result["direction"] == "BULLISH" and momentum > 0:
            result["confirmation_status"]["price_aligned"] = True
        elif result["direction"] == "BEARISH" and momentum < 0:
            result["confirmation_status"]["price_aligned"] = True

        # ✅ FIXED: was hardcoded True unconditionally, on every single
        # call, with no volume data ever passed into this function to
        # justify it. An unconditional fake "confirmed" is worse than an
        # honest "not assessed" -- it made every wave call look more
        # validated than it actually was. No volume series reaches this
        # function, so left False (honestly unconfirmed) rather than
        # fabricated; wiring in a real volume check would need a volume
        # parameter threaded in the same way `adx` now is.
        result["confirmation_status"]["volume_confirmed"] = False

        if result["direction"] != "NEUTRAL":
            result["confirmation_status"]["trend_confirmed"] = True
        
        if abs(momentum) > 0.0005:
            result["confirmation_status"]["momentum_confirmed"] = True

        # ✅ FIXED: Elliott Wave's own textbook precondition is that a
        # reliable wave count requires a trending market. This does NOT
        # touch direction/recommendation (BUY stays BUY, SELL stays
        # SELL) — it only scales how much confidence the count deserves,
        # using the same RANGING_MARKET_ADX_THRESHOLD the rest of the
        # system already uses for the choppy-market veto. Previously ADX
        # never reached this function and every wave type used a flat
        # confidence constant regardless of regime.
        if adx and result["confidence_score"]:
            reliability = min(1.0, adx / RANGING_MARKET_ADX_THRESHOLD)
            result["confidence_score"] = round(result["confidence_score"] * reliability)
            if reliability < 1.0:
                result["reason"] += f" [ADX {adx:.1f} < {RANGING_MARKET_ADX_THRESHOLD} — wave count reliability reduced]"

        return result

    # ============================================================
    # PUBLIC METHODS
    # ============================================================

    def analyze_patterns(
        self,
        price_evolution: List[Dict],
        timeframe: str = "M1",
        pip_size: float = 0.001,
        external_trend: str = None,
        external_adx: float = 0.0,
        external_rsi: float = None
    ) -> PatternAnalysis:
        """Complete pattern analysis.

        external_trend: pass the authoritative trend (e.g. the same
        STRONG_BEARISH/BULLISH/etc value used for `1_trend_bias`) so that
        pattern direction (rectangle, flag, wedge, etc.) agrees with the
        rest of the system instead of being derived a second time from a
        crude EMA20/EMA50 percentage check that disagrees on M1.

        external_adx: pass the same ADX(14) value used for the choppy-
        market veto elsewhere in the system, so Elliott Wave confidence
        reflects its own textbook precondition (reliable wave counts
        require a trending market, ADX >= RANGING_MARKET_ADX_THRESHOLD)
        instead of being a flat constant regardless of regime. Previously
        this value was computed upstream but never reached this class.

        external_rsi: current RSI(14) on this timeframe. Used to check
        whether each detected pattern's direction is actually confirmed
        by momentum, and whether it agrees with external_trend. Both
        checks used to exist as 'rsi_aligned'/'trend_aligned' keys inside
        _calculate_rule_based_confidence(), but no detector ever set
        them - they silently defaulted to False on every single pattern,
        every call, which is a large part of why confidence scores
        looked static and undifferentiated regardless of setup quality.
        That's fixed now via _apply_alignment_scoring() below, which
        adjusts each pattern's confidence directly from its own
        'direction' field (which detectors DO set) instead of relying on
        detectors to populate flags nobody wired up.

        ✅ REMOVED: the `higher_timeframes` param and the multi-timeframe
        confirmation block that used it. Pattern analysis is scoped to
        the current timeframe only (PATTERN_ANALYSIS_CURRENT_TF_ONLY),
        so there is never a second timeframe's data available here to
        confirm against - that block always received an empty list and
        never did anything.
        """
        result = PatternAnalysis()

        if not price_evolution or len(price_evolution) < 5:
            return result

        self._current_timeframe = timeframe
        self._current_pip_size = pip_size
        self._external_trend = external_trend
        self._external_adx = external_adx
        self._external_rsi = external_rsi

        prices = self._extract_prices(price_evolution)
        if prices:
            self._current_price = prices[-1]
            self._price_history = prices

        pattern_results = self._detect_all_patterns(prices, price_evolution, timeframe)
        pattern_results = self._resolve_pattern_conflicts(pattern_results, timeframe)
        pattern_results = self._resolve_pattern_overlaps(pattern_results)
        pattern_results = self._filter_patterns(pattern_results, timeframe, prices)

        for pattern_name, pattern_data in pattern_results.items():
            if pattern_data.get('detected', False):
                if 'confidence' in pattern_data:
                    pattern_data['confidence'] = round(pattern_data['confidence'], 2)
                if 'price_level' in pattern_data and pattern_data['price_level']:
                    pattern_data['price_level'] = round(pattern_data['price_level'], 5)

                classification = self._get_pattern_classification(pattern_name)
                pattern_data['pattern_type'] = classification.get('type', 'UNKNOWN')
                pattern_data['pattern_description'] = classification.get('description', '')

                pattern_data['confidence'] = self._apply_alignment_scoring(pattern_data)

                result.patterns[pattern_name] = pattern_data
                result.pattern_confidence[pattern_name] = pattern_data.get('confidence', 0)
                result.pattern_count += 1

        elliott_result = self.analyze_elliott_waves_enhanced(
            prices, price_evolution, pip_size=pip_size, adx=self._external_adx
        )
        result.elliott_waves = elliott_result

        if result.pattern_count > 0:
            top_pattern = max(
                result.patterns.items(),
                key=lambda x: x[1].get('confidence', 0)
            )
            result.pattern_summary = (
                f"Detected {result.pattern_count} patterns. "
                f"Strongest: {top_pattern[0]} "
                f"({top_pattern[1].get('confidence', 0) * 100:.0f}% confidence)"
            )
        else:
            result.pattern_summary = "No significant patterns detected"

        return result

    # ============================================================
    # ELLIOTT WAVE ANALYSIS - WITH ENTRY TIMING
    # ============================================================

    # Maps each Elliott Wave detector to its ElliottWaveType enum, default
    # wave_count, and default current/next wave labels — used by
    # analyze_elliott_waves_enhanced() to build whichever ONE wave type
    # wins the best-fit selection, without duplicating the same
    # construction logic four times.
    _ELLIOTT_WAVE_DEFAULTS = {
        "impulse": {"enum": ElliottWaveType.IMPULSE, "wave_count": 5, "default_wave": "1"},
        "corrective": {"enum": ElliottWaveType.CORRECTIVE, "wave_count": 3, "default_wave": "A"},
        "diagonal": {"enum": ElliottWaveType.DIAGONAL, "wave_count": 5, "default_wave": "5"},
        "triangle": {"enum": ElliottWaveType.TRIANGLE, "wave_count": 5, "default_wave": "E"},
    }

    def analyze_elliott_waves_enhanced(
        self,
        prices: List[float],
        price_evolution: List[Dict],
        current_price: float = None,
        pip_size: float = 0.001,
        adx: float = 0.0
    ) -> List[ElliottWave]:
        """Enhanced Elliott Wave analysis with PRECISE ENTRY TIMING.

        ✅ FIXED (best-fit selection): the four wave detectors
        (impulse/corrective/diagonal/triangle) run against the SAME price
        series. A single price series can only be in one wave structure
        at a time, so previously appending every detector that fired
        could report mutually exclusive interpretations (e.g. both
        "corrective wave C" and "triangle wave E") as co-equal signals
        from the same bars — manufacturing disagreement that wasn't real
        information, just double-counting. Now only the single
        highest-raw-confidence interpretation is returned per call
        (i.e. per timeframe), matching how only one wave count can
        actually be "current" at a given wave degree.

        ✅ FIXED (ADX awareness): Elliott Wave theory's own precondition
        is that reliable wave counts require a trending market. `adx`
        (now threaded in from the caller, previously dropped) scales
        confidence toward RANGING_MARKET_ADX_THRESHOLD instead of using a
        flat constant regardless of regime — see _get_elliott_wave_recommendation.

        ✅ REMOVED: the `higher_timeframes` param - it was never actually
        read anywhere in this method's body (checked: only appeared in
        the signature). Elliott Wave analysis, like pattern detection, is
        scoped to the current timeframe only.
        """
        waves = []
        
        if len(prices) < MIN_BARS[PatternType.ELLIOTT_WAVE]:
            return waves
        
        if current_price is None:
            current_price = prices[-1] if prices else 0

        candidates = []

        impulse = self._detect_impulse_waves(prices)
        if impulse.get('detected', False):
            candidates.append(("impulse", impulse))

        corrective = self._detect_corrective_waves(prices)
        if corrective.get('detected', False):
            candidates.append(("corrective", corrective))

        diagonal = self._detect_diagonal_waves(prices)
        if diagonal.get('detected', False):
            candidates.append(("diagonal", diagonal))

        triangle = self._detect_triangle_waves(prices)
        if triangle.get('detected', False):
            candidates.append(("triangle", triangle))

        if not candidates:
            return waves

        # Best-fit interpretation: the detector with the highest raw
        # (pre-ADX-adjustment) confidence wins. Ties keep detector order
        # (impulse > corrective > diagonal > triangle), the same priority
        # the original code implicitly used by appending in that order.
        wave_type, wave_data_raw = max(candidates, key=lambda c: c[1].get('confidence', 0))
        defaults = self._ELLIOTT_WAVE_DEFAULTS[wave_type]
        confidence = wave_data_raw.get('confidence', 0.50)

        wave_data = {
            'entry_price': wave_data_raw.get('fib_levels', {}).get('0.618', current_price * 0.998),
            'target': wave_data_raw.get('targets', {}).get('wave_5' if wave_type == "impulse" else 'wave_c_completion', current_price * 0.99),
            'fib_levels': wave_data_raw.get('fib_levels', {})
        }

        current_wave = wave_data_raw.get('current_wave', defaults['default_wave'])

        rec = self._get_elliott_wave_recommendation(
            wave_type,
            current_wave if wave_type in ("impulse", "corrective") else "",
            confidence,
            current_price,
            wave_data if wave_type in ("impulse", "corrective") else None,
            prices,
            pip_size,
            wave_direction=wave_data_raw.get('direction'),
            adx=adx
        )

        wave_obj = ElliottWave(
            wave_type=defaults['enum'],
            detected=True,
            confidence=confidence,
            wave_count=defaults['wave_count'],
            current_wave=current_wave,
            next_wave=wave_data_raw.get('next_wave', '1'),
            description=wave_data_raw.get('description', f'{wave_type.capitalize()} wave detected'),
            recommendation=rec['recommendation'],
            action=rec['action'],
            direction=rec['direction'],
            confidence_score=rec['confidence_score'],
            reason=rec['reason'],
            entry_timing=rec.get('entry_timing', 'WAIT'),
            entry_condition=rec.get('entry_condition', ''),
            confirmation_status=rec.get('confirmation_status', {}),
            entry_window_pips=rec.get('entry_window_pips', 0.0),
            time_to_entry_estimate=rec.get('time_to_entry_estimate', ''),
            # ✅ FIXED: these were computed above (wave_data) but never
            # reached the final object before now — see dataclass comment.
            entry_price=wave_data.get('entry_price') if wave_type in ("impulse", "corrective") else None,
            target_price=wave_data.get('target') if wave_type in ("impulse", "corrective") else None,
            fib_levels=wave_data.get('fib_levels', {}) if wave_type in ("impulse", "corrective") else {},
        )
        waves.append(wave_obj)

        return waves

    def analyze_elliott_waves(
        self,
        prices: List[float],
        price_evolution: List[Dict]
    ) -> List[ElliottWave]:
        """Legacy Elliott Wave analysis."""
        return self.analyze_elliott_waves_enhanced(prices, price_evolution)

    # ============================================================
    # PATTERN DETECTION METHODS
    # ============================================================

    def _detect_all_patterns(
        self,
        prices: List[float],
        price_evolution: List[Dict],
        timeframe: str = "M1"
    ) -> Dict[str, Dict]:
        results = {}

        results['double_bottom'] = self._detect_double_bottom(prices, price_evolution, timeframe)
        results['double_top'] = self._detect_double_top(prices, price_evolution, timeframe)
        results['head_shoulders'] = self._detect_head_shoulders(prices, price_evolution, timeframe)
        results['inverse_head_shoulders'] = self._detect_inverse_head_shoulders(prices, price_evolution, timeframe)
        results['triangle_ascending'] = self._detect_triangle_ascending(prices, price_evolution, timeframe)
        results['triangle_descending'] = self._detect_triangle_descending(prices, price_evolution, timeframe)
        results['triangle_symmetrical'] = self._detect_triangle_symmetrical(prices, price_evolution, timeframe)
        results['flag_bullish'] = self._detect_flag_bullish(prices, price_evolution, timeframe)
        results['flag_bearish'] = self._detect_flag_bearish(prices, price_evolution, timeframe)
        results['pennant_bullish'] = self._detect_pennant_bullish(prices, price_evolution, timeframe)
        results['pennant_bearish'] = self._detect_pennant_bearish(prices, price_evolution, timeframe)
        results['wedge_rising'] = self._detect_wedge_rising(prices, price_evolution, timeframe)
        results['wedge_falling'] = self._detect_wedge_falling(prices, price_evolution, timeframe)
        results['rectangle'] = self._detect_rectangle(prices, price_evolution, timeframe)
        results['abc_correction'] = self._detect_abc_correction(prices, price_evolution, timeframe)
        results['mean_reversion'] = self._detect_mean_reversion(prices, price_evolution, timeframe)

        return results

    # ============================================================
    # REVERSAL PATTERNS - WITH RELAXED TREND REQUIREMENTS
    # ============================================================

    def _detect_head_shoulders(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.HEAD_SHOULDERS, timeframe)
        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        peaks = []
        # ✅ MODERATE TIGHTENING: 3-bar swing confirmation each side (was
        # 2). A 2-bar window flags a peak off a single noisy tick on
        # either side, which is the single biggest source of false
        # shoulders on M1. 3 bars still catches real swings quickly
        # without over-filtering into 4-5+ bar windows.
        for i in range(3, len(prices) - 3):
            if (prices[i] > prices[i - 1] and prices[i] > prices[i - 2] and prices[i] > prices[i - 3] and
                prices[i] > prices[i + 1] and prices[i] > prices[i + 2] and prices[i] > prices[i + 3]):
                peaks.append((i, prices[i]))

        if len(peaks) >= 3:
            for mid_idx in range(1, len(peaks) - 1):
                left = peaks[mid_idx - 1]
                head = peaks[mid_idx]
                right = peaks[mid_idx + 1]

                if not (head[1] > left[1] and head[1] > right[1]):
                    continue

                freshness_bars = PATTERN_MAX_AGE_BARS.get(timeframe, 30)
                if right[0] < len(prices) - freshness_bars:
                    continue

                # ✅ MODERATE TIGHTENING: was 40/30 - a shoulder 40%
                # bigger than the other barely reads as symmetric anymore.
                # 25/20 still allows for real-world imperfect shoulders
                # without accepting near-arbitrary size mismatches.
                shoulder_diff_max = 25 if timeframe == "M1" else 20
                shoulder_diff = abs(left[1] - right[1]) / left[1] * 100 if left[1] > 0 else 100
                if shoulder_diff > shoulder_diff_max:
                    continue

                min_size = PATTERN_MIN_SIZE_PIPS.get("HEAD_SHOULDERS", 0.00005)
                head_to_shoulder = abs(head[1] - (left[1] + right[1]) / 2)
                if head_to_shoulder < min_size:
                    continue

                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(right[1] - current_price) > proximity * 3:
                    continue

                pre_pattern_prices = prices[:right[0]]
                if len(pre_pattern_prices) > 30:
                    pre_trend_context = self._get_trend_context(pre_pattern_prices[-30:], use_external=False)
                    pre_trend = pre_trend_context.get('trend', 'NEUTRAL')
                else:
                    pre_trend = self._get_trend_context(prices[:-20], use_external=False).get('trend', 'NEUTRAL')

                # ✅ FIXED: Allow ALL trends for head and shoulders
                # Now detects even in strong bearish trends

                neckline = (left[1] + right[1]) / 2

                # ✅ MODERATE TIGHTENING: was a flat 0.0010 raw price
                # delta regardless of instrument - arbitrarily too tight
                # or too loose depending on what's traded (a forex pair
                # vs gold vs an index have wildly different pip_size).
                # Pip-normalized to a moderate 6 pips.
                neckline_tolerance = self._current_pip_size * 6
                if current_price < neckline + neckline_tolerance:
                    status = 'COMPLETE'
                    status_desc = f'Head and shoulders complete: {pre_trend} → BEARISH reversal'
                    confidence = self._calculate_rule_based_confidence('HEAD_SHOULDERS', {
                        'complete': True,
                        'recent': right[0] > len(prices) - 5,
                        'near_key_level': True,
                        'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                    })
                else:
                    status = 'FORMING'
                    status_desc = 'Head and shoulders forming, waiting for neckline break'
                    confidence = self._calculate_rule_based_confidence('HEAD_SHOULDERS', {
                        'complete': False,
                        'recent': right[0] > len(prices) - 5,
                        'near_key_level': True,
                        'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                    }) * 0.7

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': f'Head and shoulders: Reversing {pre_trend} to BEARISH',
                    'price_level': round(neckline, 5),
                    'direction': 'BEARISH',
                    'status': status,
                    'status_description': status_desc,
                    'pattern_classification': 'REVERSAL',
                    'reversal_from': pre_trend,
                    'reversal_to': 'BEARISH',
                    'details': {
                        'left_shoulder': round(left[1], 5),
                        'head': round(head[1], 5),
                        'right_shoulder': round(right[1], 5),
                        'neckline': round(neckline, 5),
                        'pre_trend': pre_trend
                    }
                }

        return {'detected': False, 'confidence': 0.00}

    def _detect_inverse_head_shoulders(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.INVERSE_HEAD_SHOULDERS, timeframe)
        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        troughs = []
        # ✅ MODERATE TIGHTENING: 3-bar swing confirmation each side (was
        # 2) - see matching note in _detect_head_shoulders above.
        for i in range(3, len(prices) - 3):
            if (prices[i] < prices[i - 1] and prices[i] < prices[i - 2] and prices[i] < prices[i - 3] and
                prices[i] < prices[i + 1] and prices[i] < prices[i + 2] and prices[i] < prices[i + 3]):
                troughs.append((i, prices[i]))

        if len(troughs) >= 3:
            for mid_idx in range(1, len(troughs) - 1):
                left = troughs[mid_idx - 1]
                head = troughs[mid_idx]
                right = troughs[mid_idx + 1]

                if not (head[1] < left[1] and head[1] < right[1]):
                    continue

                freshness_bars = PATTERN_MAX_AGE_BARS.get(timeframe, 30)
                if right[0] < len(prices) - freshness_bars:
                    continue

                # ✅ MODERATE TIGHTENING: matches _detect_head_shoulders above
                shoulder_diff_max = 25 if timeframe == "M1" else 20
                shoulder_diff = abs(left[1] - right[1]) / left[1] * 100 if left[1] > 0 else 100
                if shoulder_diff > shoulder_diff_max:
                    continue

                min_size = PATTERN_MIN_SIZE_PIPS.get("INVERSE_HEAD_SHOULDERS", 0.00005)
                head_to_shoulder = abs(head[1] - (left[1] + right[1]) / 2)
                if head_to_shoulder < min_size:
                    continue

                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(right[1] - current_price) > proximity * 3:
                    continue

                pre_pattern_prices = prices[:right[0]]
                if len(pre_pattern_prices) > 30:
                    pre_trend_context = self._get_trend_context(pre_pattern_prices[-30:], use_external=False)
                    pre_trend = pre_trend_context.get('trend', 'NEUTRAL')
                else:
                    pre_trend = self._get_trend_context(prices[:-20], use_external=False).get('trend', 'NEUTRAL')

                # ✅ FIXED: Allow ALL trends
                # No trend restriction

                neckline = (left[1] + right[1]) / 2

                # ✅ MODERATE TIGHTENING: pip-normalized, matches
                # _detect_head_shoulders above (was flat 0.0010).
                neckline_tolerance = self._current_pip_size * 6
                if current_price > neckline - neckline_tolerance:
                    status = 'COMPLETE'
                    status_desc = f'Inverse H&S complete: {pre_trend} → BULLISH reversal'
                    confidence = self._calculate_rule_based_confidence('INVERSE_HEAD_SHOULDERS', {
                        'complete': True,
                        'recent': right[0] > len(prices) - 5,
                        'near_key_level': True,
                        'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                    })
                else:
                    status = 'FORMING'
                    status_desc = 'Inverse H&S forming, waiting for neckline break'
                    confidence = self._calculate_rule_based_confidence('INVERSE_HEAD_SHOULDERS', {
                        'complete': False,
                        'recent': right[0] > len(prices) - 5,
                        'near_key_level': True,
                        'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                    }) * 0.7

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': f'Inverse H&S: Reversing {pre_trend} to BULLISH',
                    'price_level': round(neckline, 5),
                    'direction': 'BULLISH',
                    'status': status,
                    'status_description': status_desc,
                    'pattern_classification': 'REVERSAL',
                    'reversal_from': pre_trend,
                    'reversal_to': 'BULLISH',
                    'details': {
                        'left_shoulder': round(left[1], 5),
                        'head': round(head[1], 5),
                        'right_shoulder': round(right[1], 5),
                        'neckline': round(neckline, 5),
                        'pre_trend': pre_trend
                    }
                }

        return {'detected': False, 'confidence': 0.00}

    def _detect_double_bottom(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.DOUBLE_BOTTOM, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        # Swing lows from the bars' actual LOWS, not their closes.
        # price_evolution was accepted and ignored here; a double bottom
        # is two matching lows, and closes are not lows.
        low_series = self._series_or_close(price_evolution, 'l', prices)

        lows = []
        # ✅ MODERATE TIGHTENING: 3-bar swing confirmation each side (was
        # 2) - see matching note in _detect_head_shoulders above.
        for i in range(3, len(low_series) - 3):
            if (low_series[i] < low_series[i - 1] and low_series[i] < low_series[i - 2] and low_series[i] < low_series[i - 3] and
                low_series[i] < low_series[i + 1] and low_series[i] < low_series[i + 2] and low_series[i] < low_series[i + 3]):
                lows.append((i, low_series[i]))

        if len(lows) >= 2:
            tolerance = DOUBLE_PATTERN_TOLERANCE.get(timeframe, DOUBLE_PATTERN_TOLERANCE["H1"])

            # ✅ FIXED: was `sorted(lows, key=lambda x: x[1])[:2]` -- the
            # two globally SMALLEST-value lows in the whole window, which
            # could be two swing lows from completely unrelated points in
            # time (one from 150 bars back, one from 5 bars back) that
            # simply happen to have numerically close prices. A double
            # bottom is a RECENCY-and-adjacency relationship, not just a
            # value-similarity one. Now scans from the most recent low
            # backward for the nearest-in-time pair within tolerance,
            # preferring the most recent valid pair over the closest-by-
            # value one anywhere in the window.
            low1, low2 = None, None
            for j in range(len(lows) - 1, 0, -1):
                candidate2 = lows[j]
                for i in range(j - 1, -1, -1):
                    candidate1 = lows[i]
                    diff_pct_check = abs(candidate1[1] - candidate2[1]) / candidate1[1] * 100 if candidate1[1] > 0 else 100
                    if diff_pct_check <= tolerance["diff_pct"]:
                        low1, low2 = candidate1, candidate2
                        break
                if low1 is not None:
                    break

            if low1 is not None:
                freshness_bars = PATTERN_MAX_AGE_BARS.get(timeframe, 30)
                if low2[0] < len(prices) - freshness_bars:
                    return {'detected': False, 'confidence': 0.00}

                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(low1[1] - current_price) > proximity * 3:
                    return {'detected': False, 'confidence': 0.00}

                between_lows = prices[low1[0]:low2[0]] if low1[0] < low2[0] else prices[low2[0]:low1[0]]
                if between_lows and max(between_lows) > low1[1] * tolerance["between_factor"]:
                    resistance = max(between_lows)

                    # ✅ FIXED: was `diff_pct < min_size` — diff_pct is a
                    # PERCENTAGE (0-100 scale) but min_size is a raw
                    # price-unit constant (e.g. 0.00005), so this never
                    # actually filtered anything (diff_pct is virtually
                    # always numerically larger). Checking the pattern's
                    # actual height (resistance to the lows, in price
                    # units) is what "minimum pattern size" should mean —
                    # filters out negligible noise-sized double bottoms.
                    min_size = PATTERN_MIN_SIZE_PIPS.get("DOUBLE_BOTTOM", 0.00005)
                    pattern_height = resistance - min(low1[1], low2[1])
                    if pattern_height < min_size:
                        return {'detected': False, 'confidence': 0.00}

                    pre_pattern_prices = prices[:low2[0]]
                    if len(pre_pattern_prices) > 30:
                        pre_trend_context = self._get_trend_context(pre_pattern_prices[-30:], use_external=False)
                        pre_trend = pre_trend_context.get('trend', 'NEUTRAL')
                    else:
                        pre_trend = self._get_trend_context(prices[:-20], use_external=False).get('trend', 'NEUTRAL')

                    # ✅ FIXED: Allow ALL trends
                    # No trend restriction

                    if abs(resistance - current_price) < proximity * 3:
                        status = 'COMPLETE'
                        status_desc = f'Double Bottom: Reversing {pre_trend} to BULLISH'
                        confidence = self._calculate_rule_based_confidence('DOUBLE_BOTTOM', {
                            'complete': True,
                            'recent': low2[0] > len(prices) - 5,
                            'near_key_level': True
                        })
                    else:
                        status = 'FORMING'
                        status_desc = 'Double bottom forming, waiting for breakout'
                        confidence = self._calculate_rule_based_confidence('DOUBLE_BOTTOM', {
                            'complete': False,
                            'recent': low2[0] > len(prices) - 5,
                            'near_key_level': True
                        }) * 0.7

                    return {
                        'detected': True,
                        'confidence': round(confidence, 2),
                        'description': f'Double Bottom: Reversing {pre_trend} to BULLISH',
                        'price_level': round(resistance, 5),
                        'direction': 'BULLISH',
                        'status': status,
                        'status_description': status_desc,
                        'pattern_classification': 'REVERSAL',
                        'reversal_from': pre_trend,
                        'reversal_to': 'BULLISH',
                        'details': {
                            'low1': round(low1[1], 5),
                            'low2': round(low2[1], 5),
                            'resistance': round(resistance, 5),
                            'pre_trend': pre_trend
                        }
                    }

        return {'detected': False, 'confidence': 0.00}

    def _detect_double_top(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.DOUBLE_TOP, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        # Swing highs from the bars' actual HIGHS, mirroring
        # _detect_double_bottom above. Closes are not highs.
        high_series = self._series_or_close(price_evolution, 'h', prices)

        highs = []
        # ✅ MODERATE TIGHTENING: 3-bar swing confirmation each side (was
        # 2) - see matching note in _detect_head_shoulders above.
        for i in range(3, len(high_series) - 3):
            if (high_series[i] > high_series[i - 1] and high_series[i] > high_series[i - 2] and high_series[i] > high_series[i - 3] and
                high_series[i] > high_series[i + 1] and high_series[i] > high_series[i + 2] and high_series[i] > high_series[i + 3]):
                highs.append((i, high_series[i]))

        if len(highs) >= 2:
            tolerance = DOUBLE_PATTERN_TOLERANCE.get(timeframe, DOUBLE_PATTERN_TOLERANCE["H1"])

            # ✅ FIXED: same anti-pattern as double_bottom -- was
            # `sorted(highs, key=lambda x: x[1], reverse=True)[:2]`, the
            # two globally HIGHEST-value peaks in the whole window,
            # which could pair two highs from unrelated points in time.
            # Now scans from the most recent high backward for the
            # nearest-in-time pair within tolerance.
            high1, high2 = None, None
            for j in range(len(highs) - 1, 0, -1):
                candidate2 = highs[j]
                for i in range(j - 1, -1, -1):
                    candidate1 = highs[i]
                    diff_pct_check = abs(candidate1[1] - candidate2[1]) / candidate1[1] * 100 if candidate1[1] > 0 else 100
                    if diff_pct_check <= tolerance["diff_pct"]:
                        high1, high2 = candidate1, candidate2
                        break
                if high1 is not None:
                    break

            if high1 is not None:
                freshness_bars = PATTERN_MAX_AGE_BARS.get(timeframe, 30)
                if high2[0] < len(prices) - freshness_bars:
                    return {'detected': False, 'confidence': 0.00}

                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(high1[1] - current_price) > proximity * 3:
                    return {'detected': False, 'confidence': 0.00}

                between_highs_factor = 2.0 - tolerance["between_factor"]  # mirror of between_factor below 1.0
                between_highs = prices[high1[0]:high2[0]] if high1[0] < high2[0] else prices[high2[0]:high1[0]]
                if between_highs and min(between_highs) < high1[1] * between_highs_factor:
                    support = min(between_highs)

                    # ✅ FIXED: same unit-mismatch bug as double bottom —
                    # diff_pct (a percentage) was compared against min_size
                    # (a raw price-unit constant), which never filtered
                    # anything. Check the pattern's actual height instead.
                    min_size = PATTERN_MIN_SIZE_PIPS.get("DOUBLE_TOP", 0.00005)
                    pattern_height = max(high1[1], high2[1]) - support
                    if pattern_height < min_size:
                        return {'detected': False, 'confidence': 0.00}

                    pre_pattern_prices = prices[:high2[0]]
                    if len(pre_pattern_prices) > 30:
                        pre_trend_context = self._get_trend_context(pre_pattern_prices[-30:], use_external=False)
                        pre_trend = pre_trend_context.get('trend', 'NEUTRAL')
                    else:
                        pre_trend = self._get_trend_context(prices[:-20], use_external=False).get('trend', 'NEUTRAL')

                    # ✅ FIXED: Allow ALL trends

                    if abs(support - current_price) < proximity * 3:
                        status = 'COMPLETE'
                        status_desc = f'Double Top: Reversing {pre_trend} to BEARISH'
                        confidence = self._calculate_rule_based_confidence('DOUBLE_TOP', {
                            'complete': True,
                            'recent': high2[0] > len(prices) - 5,
                            'near_key_level': True
                        })
                    else:
                        status = 'FORMING'
                        status_desc = 'Double top forming, waiting for breakdown'
                        confidence = self._calculate_rule_based_confidence('DOUBLE_TOP', {
                            'complete': False,
                            'recent': high2[0] > len(prices) - 5,
                            'near_key_level': True
                        }) * 0.7

                    return {
                        'detected': True,
                        'confidence': round(confidence, 2),
                        'description': f'Double Top: Reversing {pre_trend} to BEARISH',
                        'price_level': round(support, 5),
                        'direction': 'BEARISH',
                        'status': status,
                        'status_description': status_desc,
                        'pattern_classification': 'REVERSAL',
                        'reversal_from': pre_trend,
                        'reversal_to': 'BEARISH',
                        'details': {
                            'high1': round(high1[1], 5),
                            'high2': round(high2[1], 5),
                            'support': round(support, 5),
                            'pre_trend': pre_trend
                        }
                    }

        return {'detected': False, 'confidence': 0.00}

    # ============================================================
    # WEDGE PATTERNS - WITH RELAXED TREND REQUIREMENTS
    # ============================================================

    def _detect_wedge_rising(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.WEDGE_RISING, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0
        pip_size = getattr(self, '_current_pip_size', 0.0001) or 0.0001

        if len(prices) >= 8:
            # ✅ FIXED: high_trend and low_trend used to be computed with
            # the EXACT SAME formula from the same series, so they were
            # always numerically equal — the required `high_trend <
            # low_trend` condition below could never be true, making this
            # entire function permanently dead code (it could never
            # detect anything, ever). Derive real, independent swing-high
            # and swing-low trends instead, same approach as the triangle
            # fix. Also fixed: `current_price` was referenced further
            # below but never defined in this function — would have
            # raised a NameError the moment this branch was ever reached.
            #
            # ✅ FIXED (freshness): window used to be a flat `prices[-30:]`
            # regardless of timeframe, so a wedge built from swings 30
            # bars old on M1 (30 minutes) was scored as "recent" via a
            # hardcoded flag with no real check behind it. Bounding the
            # swing-search window itself to get_pattern_freshness_bars()
            # guarantees any swing found here is genuinely within the
            # freshness window - no dependency on an unverified bar-index
            # field on the swing-point dict.
            freshness_bars = get_pattern_freshness_bars(timeframe)
            window = prices[-freshness_bars:] if len(prices) >= freshness_bars else prices
            swings = self._find_swing_points(window, lookback=2)
            swing_highs = [p['price'] for p in swings if p['type'] == 'high'][-4:]
            swing_lows = [p['price'] for p in swings if p['type'] == 'low'][-4:]

            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                high_trend = (swing_highs[-1] - swing_highs[0]) / swing_highs[0] if swing_highs[0] > 0 else 0
                low_trend = (swing_lows[-1] - swing_lows[0]) / swing_lows[0] if swing_lows[0] > 0 else 0
            else:
                high_trend = low_trend = 0

            # ✅ FIXED (geometry): a rising wedge needs BOTH boundaries
            # rising by a real, non-noise amount, not just "greater than
            # zero" - at zero-pip resolution, `high_trend > 0` passes on
            # a fractional-pip drift that isn't a genuine rising boundary.
            # Require each swing leg to have moved at least
            # PATTERN_MIN_SIZE_PIPS worth of price, pip-normalized.
            min_leg_pips = PATTERN_MIN_SIZE_PIPS.get("WEDGE", 0.0003)
            high_leg_pips = abs(swing_highs[-1] - swing_highs[0]) if len(swing_highs) >= 2 else 0
            low_leg_pips = abs(swing_lows[-1] - swing_lows[0]) if len(swing_lows) >= 2 else 0
            geometry_valid = high_leg_pips >= min_leg_pips and low_leg_pips >= min_leg_pips

            if high_trend > 0 and low_trend > 0 and high_trend < low_trend and geometry_valid:
                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(prices[-1] - self._current_price) > proximity * 2:
                    return {'detected': False, 'confidence': 0.00}

                pre_pattern_prices = prices[:-10]
                if len(pre_pattern_prices) > 30:
                    pre_trend_context = self._get_trend_context(pre_pattern_prices[-30:], use_external=False)
                    pre_trend = pre_trend_context.get('trend', 'NEUTRAL')
                else:
                    pre_trend = self._get_trend_context(prices[:-10], use_external=False).get('trend', 'NEUTRAL')

                # ✅ FIXED: Allow ALL trends

                # ✅ FIXED (geometry): completion used to check
                # `current_price < min(prices[-5:]) * 0.998` - an
                # arbitrary 0.2% dip in an unrelated 5-bar window, with no
                # connection to the wedge's own lower boundary computed
                # above. Now checks an actual break of the wedge's most
                # recent confirmed swing low, with a pip-normalized buffer
                # instead of a flat percentage (which is wildly different
                # in pip terms across instruments at different price
                # levels).
                wedge_lower_boundary = swing_lows[-1]
                breakout_buffer = max(min_leg_pips * 0.5, pip_size * 2)
                if current_price < wedge_lower_boundary - breakout_buffer:
                    status = 'COMPLETE'
                    status_desc = f'Rising Wedge: Reversing {pre_trend} to BEARISH'
                else:
                    status = 'FORMING'
                    status_desc = 'Rising wedge forming, waiting for breakdown'

                confidence = self._calculate_rule_based_confidence('WEDGE', {
                    'complete': status == 'COMPLETE',
                    'recent': True,  # justified: window above is freshness-bounded
                    'near_key_level': True  # justified: proximity-gated above
                })

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': f'Rising Wedge: Reversing {pre_trend} to BEARISH',
                    'price_level': round(prices[-1], 5),
                    'direction': 'BEARISH',
                    'status': status,
                    'status_description': status_desc,
                    'pattern_classification': 'REVERSAL',
                    'reversal_from': pre_trend,
                    'reversal_to': 'BEARISH',
                    'details': {'pre_trend': pre_trend, 'wedge_lower_boundary': round(wedge_lower_boundary, 5)}
                }

        return {'detected': False, 'confidence': 0.00}

    def _detect_wedge_falling(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.WEDGE_FALLING, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0
        pip_size = getattr(self, '_current_pip_size', 0.0001) or 0.0001

        if len(prices) >= 8:
            # ✅ FIXED: same permanently-dead-code bug as rising wedge —
            # high_trend/low_trend were identical formulas, so
            # `high_trend > low_trend` could never be true. Also fixed
            # the undefined `current_price` reference below.
            #
            # ✅ FIXED (freshness): see matching note in _detect_wedge_rising.
            freshness_bars = get_pattern_freshness_bars(timeframe)
            window = prices[-freshness_bars:] if len(prices) >= freshness_bars else prices
            swings = self._find_swing_points(window, lookback=2)
            swing_highs = [p['price'] for p in swings if p['type'] == 'high'][-4:]
            swing_lows = [p['price'] for p in swings if p['type'] == 'low'][-4:]

            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                high_trend = (swing_highs[-1] - swing_highs[0]) / swing_highs[0] if swing_highs[0] > 0 else 0
                low_trend = (swing_lows[-1] - swing_lows[0]) / swing_lows[0] if swing_lows[0] > 0 else 0
            else:
                high_trend = low_trend = 0

            # ✅ FIXED (geometry): see matching note in _detect_wedge_rising
            # - require a real, non-noise pip move on each boundary.
            min_leg_pips = PATTERN_MIN_SIZE_PIPS.get("WEDGE", 0.0003)
            high_leg_pips = abs(swing_highs[-1] - swing_highs[0]) if len(swing_highs) >= 2 else 0
            low_leg_pips = abs(swing_lows[-1] - swing_lows[0]) if len(swing_lows) >= 2 else 0
            geometry_valid = high_leg_pips >= min_leg_pips and low_leg_pips >= min_leg_pips

            if high_trend < 0 and low_trend < 0 and high_trend > low_trend and geometry_valid:
                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(prices[-1] - self._current_price) > proximity * 2:
                    return {'detected': False, 'confidence': 0.00}

                pre_pattern_prices = prices[:-10]
                if len(pre_pattern_prices) > 30:
                    pre_trend_context = self._get_trend_context(pre_pattern_prices[-30:], use_external=False)
                    pre_trend = pre_trend_context.get('trend', 'NEUTRAL')
                else:
                    pre_trend = self._get_trend_context(prices[:-10], use_external=False).get('trend', 'NEUTRAL')

                # ✅ FIXED: Allow ALL trends

                # ✅ FIXED (geometry): see matching note in
                # _detect_wedge_rising - tied to the wedge's actual upper
                # boundary instead of an arbitrary unrelated 5-bar %.
                wedge_upper_boundary = swing_highs[-1]
                breakout_buffer = max(min_leg_pips * 0.5, pip_size * 2)
                if current_price > wedge_upper_boundary + breakout_buffer:
                    status = 'COMPLETE'
                    status_desc = f'Falling Wedge: Reversing {pre_trend} to BULLISH'
                else:
                    status = 'FORMING'
                    status_desc = 'Falling wedge forming, waiting for breakout'

                confidence = self._calculate_rule_based_confidence('WEDGE', {
                    'complete': status == 'COMPLETE',
                    'recent': True,  # justified: window above is freshness-bounded
                    'near_key_level': True  # justified: proximity-gated above
                })

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': f'Falling Wedge: Reversing {pre_trend} to BULLISH',
                    'price_level': round(prices[-1], 5),
                    'direction': 'BULLISH',
                    'status': status,
                    'status_description': status_desc,
                    'pattern_classification': 'REVERSAL',
                    'reversal_from': pre_trend,
                    'reversal_to': 'BULLISH',
                    'details': {'pre_trend': pre_trend, 'wedge_upper_boundary': round(wedge_upper_boundary, 5)}
                }

        return {'detected': False, 'confidence': 0.00}

    # ============================================================
    # TRIANGLE PATTERNS - WITH FIXED PARAMETERS
    # ============================================================

    def _detect_triangle_ascending(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.TRIANGLE_ASCENDING, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0
        pip_size = getattr(self, '_current_pip_size', 0.0001) or 0.0001

        # ✅ FIXED: recent_highs and recent_lows were the exact same
        # close-price array duplicated — an ascending triangle needs a
        # flat resistance from actual swing HIGHS and a rising support
        # from actual swing LOWS (two different point sets), not the same
        # series compared against itself. price_evolution only carries a
        # single price per point (no OHLC), so true swing highs/lows are
        # derived via the shared swing detector rather than raw bar
        # highs/lows — still a real improvement over duplicating one
        # series as both sides of the pattern.
        #
        # ✅ FIXED (freshness): window used to be a flat `prices[-30:]`
        # regardless of timeframe - see matching note in
        # _detect_wedge_rising for why that's wrong on M1.
        freshness_bars = get_pattern_freshness_bars(timeframe)
        window = prices[-freshness_bars:] if len(prices) >= freshness_bars else prices
        swings = self._find_swing_points(window, lookback=2)
        recent_highs = [p['price'] for p in swings if p['type'] == 'high'][-4:]
        recent_lows = [p['price'] for p in swings if p['type'] == 'low'][-4:]

        if len(recent_highs) >= 2 and len(recent_lows) >= 2:
            # ✅ FIXED (geometry): was `high_range / max(recent_highs) < 0.015`
            # - a 1.5% relative tolerance, which is ~170 pips on EURUSD
            # (~1.15) and means "flat resistance" would still pass with
            # highs scattered over a huge range. Pip-normalized instead,
            # scaled to the pattern's own minimum size so it's consistent
            # with how tightly every other M1 pattern is now held.
            min_leg_pips = PATTERN_MIN_SIZE_PIPS.get("TRIANGLE", 0.0003)
            high_range = max(recent_highs) - min(recent_highs)
            if high_range <= min_leg_pips * 2:
                low_trend_pips = (recent_lows[-1] - recent_lows[0]) if len(recent_lows) >= 2 else 0
                # was `low_trend > 0.003` (0.3% ~ 35 pips on EURUSD)
                if low_trend_pips > min_leg_pips:
                    resistance = max(recent_highs)
                    proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                    if abs(resistance - current_price) > proximity * 2:
                        return {'detected': False, 'confidence': 0.00}

                    trend_context = self._get_trend_context(prices)
                    trend = trend_context.get('trend', 'NEUTRAL')

                    if trend in ['STRONG_BULLISH', 'BULLISH']:
                        direction = 'BULLISH'
                        status_desc = f'Ascending Triangle: CONTINUING {trend} trend'
                    elif trend in ['STRONG_BEARISH', 'BEARISH']:
                        direction = 'BEARISH'
                        status_desc = f'Ascending Triangle in {trend} trend (fakeout possible)'
                    else:
                        direction = 'BULLISH'
                        status_desc = 'Ascending triangle in neutral trend'

                    # ✅ FIXED (geometry): completion check was
                    # `current_price > resistance * 0.995` (0.5% ~ 57
                    # pips on EURUSD - the entire triangle could be
                    # smaller than this "breakout" buffer). Pip-normalized
                    # to the same buffer used for the wedge breakouts.
                    breakout_buffer = max(min_leg_pips * 0.5, pip_size * 2)
                    is_complete = current_price > resistance - breakout_buffer

                    confidence = self._calculate_rule_based_confidence('TRIANGLE', {
                        'complete': is_complete,
                        'recent': True,  # justified: window above is freshness-bounded
                        'near_key_level': True,  # justified: proximity-gated above
                        'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                    })

                    return {
                        'detected': True,
                        'confidence': round(confidence, 2),
                        'description': 'Ascending triangle detected',
                        'direction': direction,
                        'price_level': round(resistance, 5),
                        'status': 'COMPLETE' if is_complete else 'FORMING',
                        'status_description': status_desc,
                        'pattern_classification': 'CONTINUATION',
                        'continues_trend': trend if direction in ['BULLISH', 'BEARISH'] else None,
                        'details': {'trend': trend}
                    }

        return {'detected': False, 'confidence': 0.00}

    def _detect_triangle_descending(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.TRIANGLE_DESCENDING, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0
        pip_size = getattr(self, '_current_pip_size', 0.0001) or 0.0001

        # ✅ FIXED: same issue as ascending triangle — recent_highs and
        # recent_lows were the identical close-price array.
        # ✅ FIXED (freshness): window now bounded to the freshness
        # window instead of a flat 30 bars — see matching note in
        # _detect_wedge_rising.
        freshness_bars = get_pattern_freshness_bars(timeframe)
        window = prices[-freshness_bars:] if len(prices) >= freshness_bars else prices
        swings = self._find_swing_points(window, lookback=2)
        recent_highs = [p['price'] for p in swings if p['type'] == 'high'][-4:]
        recent_lows = [p['price'] for p in swings if p['type'] == 'low'][-4:]

        if len(recent_lows) >= 2 and len(recent_highs) >= 2:
            # ✅ FIXED (geometry): pip-normalized, see matching note in
            # _detect_triangle_ascending.
            min_leg_pips = PATTERN_MIN_SIZE_PIPS.get("TRIANGLE", 0.0003)
            low_range = max(recent_lows) - min(recent_lows)
            if low_range <= min_leg_pips * 2:
                high_trend_pips = (recent_highs[-1] - recent_highs[0]) if len(recent_highs) >= 2 else 0
                if high_trend_pips < -min_leg_pips:
                    support = min(recent_lows)
                    proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                    if abs(support - current_price) > proximity * 2:
                        return {'detected': False, 'confidence': 0.00}

                    trend_context = self._get_trend_context(prices)
                    trend = trend_context.get('trend', 'NEUTRAL')

                    if trend in ['STRONG_BEARISH', 'BEARISH']:
                        direction = 'BEARISH'
                        status_desc = f'Descending Triangle: CONTINUING {trend} trend'
                    elif trend in ['STRONG_BULLISH', 'BULLISH']:
                        direction = 'BULLISH'
                        status_desc = f'Descending Triangle in {trend} trend (fakeout possible)'
                    else:
                        direction = 'BEARISH'
                        status_desc = 'Descending triangle in neutral trend'

                    # ✅ FIXED (geometry): pip-normalized breakout buffer,
                    # see matching note in _detect_triangle_ascending.
                    breakout_buffer = max(min_leg_pips * 0.5, pip_size * 2)
                    is_complete = current_price < support + breakout_buffer

                    confidence = self._calculate_rule_based_confidence('TRIANGLE', {
                        'complete': is_complete,
                        'recent': True,  # justified: window above is freshness-bounded
                        'near_key_level': True,  # justified: proximity-gated above
                        'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                    })

                    return {
                        'detected': True,
                        'confidence': round(confidence, 2),
                        'description': 'Descending triangle detected',
                        'direction': direction,
                        'price_level': round(support, 5),
                        'status': 'COMPLETE' if is_complete else 'FORMING',
                        'status_description': status_desc,
                        'pattern_classification': 'CONTINUATION',
                        'continues_trend': trend if direction in ['BULLISH', 'BEARISH'] else None,
                        'details': {'trend': trend}
                    }

        return {'detected': False, 'confidence': 0.00}

    def _detect_triangle_symmetrical(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.TRIANGLE_SYMMETRICAL, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0
        pip_size = getattr(self, '_current_pip_size', 0.0001) or 0.0001

        recent_range = max(prices[-5:]) - min(prices[-5:])
        older_range = max(prices[-10:-5]) - min(prices[-10:-5]) if len(prices) >= 10 else recent_range

        # ✅ FIXED (geometry): a contracting range of pure sub-pip noise
        # still satisfies `recent_range < older_range * 0.7` - the ratio
        # check alone doesn't establish the contraction is a real,
        # tradeable triangle rather than two flat, quiet windows. Require
        # the older (wider) range to be at least a real minimum size.
        min_leg_pips = PATTERN_MIN_SIZE_PIPS.get("TRIANGLE", 0.0003)
        if recent_range < older_range * 0.7 and older_range > min_leg_pips:
            recent_high_trend = (max(prices[-5:]) - max(prices[-10:-5])) / max(prices[-10:-5]) if max(prices[-10:-5]) > 0 else 0
            recent_low_trend = (min(prices[-5:]) - min(prices[-10:-5])) / min(prices[-10:-5]) if min(prices[-10:-5]) > 0 else 0

            if recent_high_trend < 0 and recent_low_trend > 0:
                apex = (max(prices[-5:]) + min(prices[-5:])) / 2
                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(apex - current_price) > proximity * 2:
                    return {'detected': False, 'confidence': 0.00}

                # ✅ FIXED (reliability): 'complete' was hardcoded True
                # unconditionally while 'status' below was hardcoded
                # 'FORMING' - directly contradicting each other. Every
                # single symmetrical-triangle detection got the full
                # 0.25 'complete' confidence bonus regardless of whether
                # price had actually broken out of the contracting range.
                # Now a real breakout check, pip-normalized like the
                # other triangle detectors.
                breakout_buffer = max(min_leg_pips * 0.5, pip_size * 2)
                upper_bound = max(prices[-5:])
                lower_bound = min(prices[-5:])
                if current_price > upper_bound + breakout_buffer:
                    is_complete = True
                    direction = 'BULLISH'
                    status_desc = 'Symmetrical triangle: bullish breakout confirmed'
                elif current_price < lower_bound - breakout_buffer:
                    is_complete = True
                    direction = 'BEARISH'
                    status_desc = 'Symmetrical triangle: bearish breakdown confirmed'
                else:
                    is_complete = False
                    direction = 'NEUTRAL'
                    status_desc = 'Symmetrical triangle forming, waiting for breakout'

                confidence = self._calculate_rule_based_confidence('TRIANGLE', {
                    'complete': is_complete,
                    'recent': True,  # justified: only ever looks at the last 10 bars
                    'near_key_level': True  # justified: proximity-gated above
                })

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': 'Symmetrical triangle detected',
                    'direction': direction,
                    'price_level': round(apex, 5),
                    'status': 'COMPLETE' if is_complete else 'FORMING',
                    'status_description': status_desc,
                    'pattern_classification': 'NEUTRAL',
                    'details': {}
                }

        return {'detected': False, 'confidence': 0.00}

    # ============================================================
    # CONTINUATION PATTERNS
    # ============================================================

    def _detect_rectangle(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        # ✅ FIXED: this branch previously hardcoded min_bars/min_size_pips/
        # max_age_bars/confidence_threshold as separate inline literals
        # instead of calling the config getters built for exactly this
        # (get_pattern_min_bars_m1, get_pattern_min_size_pips,
        # get_pattern_freshness_bars, get_pattern_confidence_threshold --
        # imported at the top of this file but never actually called
        # anywhere). Two concrete problems that caused, not just style:
        #   1. max_age_bars was hardcoded to 30 here, while
        #      PATTERN_MAX_AGE_BARS["M1"] = 50 is what every OTHER M1
        #      pattern type uses (see the head&shoulders/double-top/double-
        #      bottom detectors below) -- M1 rectangles were silently using
        #      a tighter, inconsistent freshness window than the rest of
        #      the M1 pattern suite for no stated reason.
        #   2. min_size_pips=0.00005 bypassed the RECTANGLE_M1-specific
        #      config key entirely -- get_pattern_min_size_pips() exists
        #      specifically to special-case M1 rectangles onto
        #      PATTERN_MIN_SIZE_PIPS["RECTANGLE_M1"] instead of the generic
        #      "RECTANGLE" key, and that special-casing was dead code.
        # Now both branches go through the same getter functions, so
        # tuning any of these in config actually takes effect, and M1
        # rectangles are no longer out of step with M1 everything-else.
        min_bars = get_pattern_min_bars_m1("RECTANGLE") if timeframe == "M1" else MIN_BARS.get(PatternType.RECTANGLE, 20)
        min_size_pips = get_pattern_min_size_pips(timeframe, "RECTANGLE")
        max_age_bars = get_pattern_freshness_bars(timeframe)
        confidence_threshold = get_pattern_confidence_threshold(timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        recent_high = max(prices[-10:])
        recent_low = min(prices[-10:])

        # ✅ FIXED: was `range_pct = (high-low)/high * 100 < 2.0` — 2% of
        # ~1.137 on EURUSD is ~227 pips, so this consolidation check never
        # actually failed on M1 (typical 10-bar ranges are a handful of
        # pips). A genuinely trending 10-bar move could pass as a
        # "rectangle" purely because it stayed under 227 pips.
        pip_size = getattr(self, '_current_pip_size', 0.0001) or 0.0001
        range_pips = (recent_high - recent_low) / pip_size
        max_range_pips = RECTANGLE_MAX_RANGE_PIPS.get(timeframe, RECTANGLE_MAX_RANGE_PIPS['DEFAULT'])

        if range_pips < max_range_pips:
            # ✅ FIXED: tolerance band was recent_low*0.98 / recent_high*1.02
            # (2%, same ~227-pip-on-EURUSD problem as the range check above)
            # — every window trivially satisfied it, so this consistency
            # counter was effectively always incrementing regardless of
            # whether price actually stayed inside the range. Use a pip
            # tolerance scaled off the rectangle's own height instead.
            tolerance = max((recent_high - recent_low) * 0.15, pip_size * 2)
            range_consistency = 0
            # ✅ FIXED: max_age_bars was fetched above but never used
            # anywhere in this function - the scan below used to run over
            # the ENTIRE available price history with no freshness bound,
            # so a range that was consistent 200+ bars ago (M1: over 3
            # hours) could still count toward range_consistency today even
            # if price wandered away and only recently drifted back near
            # the midpoint. Now bounded to the same freshness window every
            # other pattern type respects.
            scan_start = max(8, len(prices) - max_age_bars)
            for i in range(scan_start, len(prices)):
                if min(prices[i - 8:i]) > recent_low - tolerance and max(prices[i - 8:i]) < recent_high + tolerance:
                    range_consistency += 1

            if range_consistency > 3:
                if (recent_high - recent_low) < min_size_pips:
                    return {'detected': False, 'confidence': 0.00}

                midpoint = (recent_high + recent_low) / 2
                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)

                volumes = self._extract_volumes(price_evolution)
                volume_confirmed = self._check_volume_confirmation(volumes, 0.5)

                if current_price > recent_high:
                    status = 'BROKEN'
                    status_desc = 'Rectangle broken UP - confirmed breakout'
                    direction = 'BULLISH'
                    confidence = self._calculate_rule_based_confidence('RECTANGLE_BREAKOUT', {
                        'complete': True,
                        'recent': True,
                        'near_key_level': True,
                        'volume_ratio': volume_confirmed
                    })
                    if volume_confirmed:
                        confidence = min(1.0, confidence * 1.2)
                    return {
                        'detected': True,
                        'confidence': round(confidence, 2),
                        'description': f'Rectangle BROKEN UP: {recent_low:.5f} - {recent_high:.5f}',
                        'price_level': round(recent_high, 5),
                        'direction': 'BULLISH',
                        'status': 'BROKEN',
                        'status_description': status_desc,
                        'pattern_classification': 'CONTINUATION',
                        'continues_trend': 'BULLISH',
                        'details': {
                            'breakout': True,
                            'breakout_direction': 'UP',
                            'breakout_volume_confirmed': volume_confirmed
                        }
                    }

                if current_price < recent_low:
                    status = 'BROKEN'
                    status_desc = 'Rectangle broken DOWN - confirmed breakdown'
                    direction = 'BEARISH'
                    confidence = self._calculate_rule_based_confidence('RECTANGLE_BREAKOUT', {
                        'complete': True,
                        'recent': True,
                        'near_key_level': True,
                        'volume_ratio': volume_confirmed
                    })
                    if volume_confirmed:
                        confidence = min(1.0, confidence * 1.2)
                    return {
                        'detected': True,
                        'confidence': round(confidence, 2),
                        'description': f'Rectangle BROKEN DOWN: {recent_low:.5f} - {recent_high:.5f}',
                        'price_level': round(recent_low, 5),
                        'direction': 'BEARISH',
                        'status': 'BROKEN',
                        'status_description': status_desc,
                        'pattern_classification': 'CONTINUATION',
                        'continues_trend': 'BEARISH',
                        'details': {
                            'breakout': True,
                            'breakout_direction': 'DOWN',
                            'breakout_volume_confirmed': volume_confirmed
                        }
                    }

                if abs(midpoint - current_price) > proximity * 2:
                    return {'detected': False, 'confidence': 0.00}

                trend_context = self._get_trend_context(prices)
                trend = trend_context.get('trend', 'NEUTRAL')

                if trend in ['STRONG_BEARISH', 'BEARISH']:
                    direction = 'BEARISH'
                    status_desc = f'Rectangle: CONTINUING {trend} trend'
                    confidence = self._calculate_rule_based_confidence('RECTANGLE', {
                        'complete': True,
                        'recent': True,
                        'near_key_level': True,
                        'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                    })
                elif trend in ['STRONG_BULLISH', 'BULLISH']:
                    direction = 'BULLISH'
                    status_desc = f'Rectangle: CONTINUING {trend} trend'
                    confidence = self._calculate_rule_based_confidence('RECTANGLE', {
                        'complete': True,
                        'recent': True,
                        'near_key_level': True,
                        'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                    })
                else:
                    # ✅ FIXED: was `current_price > recent_high * 0.995` /
                    # `< recent_low * 1.005` (0.5% ~ 57 pips on EURUSD) -
                    # the same unnormalized-percentage problem the rest of
                    # this function was already fixed to avoid, just missed
                    # in this one branch. Pip-normalized to the same
                    # breakout buffer style used elsewhere.
                    edge_buffer = max((recent_high - recent_low) * 0.1, pip_size * 2)
                    if current_price > recent_high - edge_buffer:
                        direction = 'BULLISH'
                        status_desc = 'Rectangle at resistance, breakout up'
                    elif current_price < recent_low + edge_buffer:
                        direction = 'BEARISH'
                        status_desc = 'Rectangle at support, breakdown down'
                    else:
                        direction = 'NEUTRAL'
                        status_desc = 'Rectangle forming, waiting for direction'
                    confidence = self._calculate_rule_based_confidence('RECTANGLE', {
                        'complete': direction != 'NEUTRAL',
                        'recent': True,
                        'near_key_level': True,
                        'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                    })

                # ✅ FIXED: confidence_threshold was fetched at the top of
                # this function and never used -- this is the branch (no
                # confirmed breakout, just "price stayed in a range") that
                # is structurally the easiest continuation pattern to
                # satisfy on any low-ATR window, so it needs its own gate
                # rather than relying solely on the caller's timeframe-level
                # filter downstream.
                if confidence < confidence_threshold:
                    return {'detected': False, 'confidence': round(confidence, 2)}

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': f'Rectangle pattern: {recent_low:.5f} - {recent_high:.5f}',
                    'price_level': round(midpoint, 5),
                    'direction': direction,
                    'status': 'COMPLETE' if direction != 'NEUTRAL' else 'FORMING',
                    'status_description': status_desc,
                    'pattern_classification': 'CONTINUATION',
                    'continues_trend': trend if direction in ['BULLISH', 'BEARISH'] else None,
                    'details': {
                        'high': round(recent_high, 5),
                        'low': round(recent_low, 5),
                        'midpoint': round(midpoint, 5),
                        'trend': trend
                    }
                }

        return {'detected': False, 'confidence': 0.00}

    # ============================================================
    # FLAG AND PENNANT PATTERNS
    # ============================================================

    def _detect_flag_bullish(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.FLAG_BULLISH, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        # ✅ FIXED (freshness - severe): pole_start used to be `prices[0]`,
        # the very first bar of whatever the ENTIRE price_evolution array
        # happened to contain (often hundreds of bars), with pole_end/
        # flag_highs/flag_lows all derived by splitting that same
        # unbounded array in half. On M1 that could mean a "pole" spanning
        # hours-old price action and a "flag" consolidation stretching
        # over 100+ minutes - nothing here was ever freshness-checked,
        # unlike every other pattern type in this file. Bounded to the
        # same freshness window as everything else before doing any of
        # the pole/flag math.
        freshness_bars = get_pattern_freshness_bars(timeframe)
        window = prices[-freshness_bars:] if len(prices) >= freshness_bars else prices
        if len(window) < 10:
            return {'detected': False, 'confidence': 0.00}

        pole_start = window[0]
        pole_end = max(window[:len(window) // 2])
        pole_move = (pole_end - pole_start) / pole_start if pole_start > 0 else 0

        pole_move_min = FLAG_POLE_MOVE_MIN.get(timeframe, 0.015)
        if pole_move > pole_move_min:
            flag_highs = window[len(window) // 2:]
            flag_lows = window[len(window) // 2:]

            flag_range = max(flag_highs) - min(flag_lows)
            pole_range = pole_end - pole_start

            if flag_range < pole_range * 0.6:
                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(pole_end - current_price) > proximity * 2:
                    return {'detected': False, 'confidence': 0.00}

                trend_context = self._get_trend_context(prices)
                trend = trend_context.get('trend', 'NEUTRAL')

                if trend in ['STRONG_BULLISH', 'BULLISH']:
                    direction = 'BULLISH'
                    status_desc = f'Bullish Flag: CONTINUING {trend} trend'
                elif trend in ['STRONG_BEARISH', 'BEARISH']:
                    direction = 'BEARISH'
                    status_desc = f'Bullish Flag in {trend} trend (reversal unlikely)'
                else:
                    direction = 'BULLISH'
                    status_desc = 'Bullish flag in neutral trend'

                confidence = self._calculate_rule_based_confidence('FLAG', {
                    'complete': True,
                    'recent': True,  # justified: window above is freshness-bounded
                    'near_key_level': True,  # justified: proximity-gated above
                    'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                })

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': 'Bullish flag detected',
                    'direction': direction,
                    'price_level': round(pole_end, 5),
                    'status': 'COMPLETE',
                    'status_description': status_desc,
                    'pattern_classification': 'CONTINUATION',
                    'continues_trend': trend if direction in ['BULLISH', 'BEARISH'] else None,
                    'details': {'pole_move': round(pole_move * 100, 1), 'trend': trend}
                }

        return {'detected': False, 'confidence': 0.00}

    def _detect_flag_bearish(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.FLAG_BEARISH, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        # ✅ FIXED (freshness - severe): see matching note in
        # _detect_flag_bullish.
        freshness_bars = get_pattern_freshness_bars(timeframe)
        window = prices[-freshness_bars:] if len(prices) >= freshness_bars else prices
        if len(window) < 10:
            return {'detected': False, 'confidence': 0.00}

        pole_start = window[0]
        pole_end = min(window[:len(window) // 2])
        pole_move = (pole_start - pole_end) / pole_start if pole_start > 0 else 0

        pole_move_min = FLAG_POLE_MOVE_MIN.get(timeframe, 0.015)
        if pole_move > pole_move_min:
            flag_highs = window[len(window) // 2:]
            flag_lows = window[len(window) // 2:]

            flag_range = max(flag_highs) - min(flag_lows)
            pole_range = pole_start - pole_end

            if flag_range < pole_range * 0.6:
                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(pole_end - current_price) > proximity * 2:
                    return {'detected': False, 'confidence': 0.00}

                trend_context = self._get_trend_context(prices)
                trend = trend_context.get('trend', 'NEUTRAL')

                if trend in ['STRONG_BEARISH', 'BEARISH']:
                    direction = 'BEARISH'
                    status_desc = f'Bearish Flag: CONTINUING {trend} trend'
                elif trend in ['STRONG_BULLISH', 'BULLISH']:
                    direction = 'BULLISH'
                    status_desc = f'Bearish Flag in {trend} trend (reversal unlikely)'
                else:
                    direction = 'BEARISH'
                    status_desc = 'Bearish flag in neutral trend'

                confidence = self._calculate_rule_based_confidence('FLAG', {
                    'complete': True,
                    'recent': True,  # justified: window above is freshness-bounded
                    'near_key_level': True,  # justified: proximity-gated above
                    'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                })

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': 'Bearish flag detected',
                    'direction': direction,
                    'price_level': round(pole_end, 5),
                    'status': 'COMPLETE',
                    'status_description': status_desc,
                    'pattern_classification': 'CONTINUATION',
                    'continues_trend': trend if direction in ['BULLISH', 'BEARISH'] else None,
                    'details': {'pole_move': round(pole_move * 100, 1), 'trend': trend}
                }

        return {'detected': False, 'confidence': 0.00}

    def _detect_pennant_bullish(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.PENNANT_BULLISH, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        # ✅ FIXED (freshness - severe): see matching note in
        # _detect_flag_bullish - same unbounded prices[0]/prices[:n//3]
        # issue, just with a 1/3 split instead of 1/2.
        freshness_bars = get_pattern_freshness_bars(timeframe)
        window = prices[-freshness_bars:] if len(prices) >= freshness_bars else prices
        if len(window) < 12:
            return {'detected': False, 'confidence': 0.00}

        pole_start = window[0]
        pole_end = max(window[:len(window) // 3])
        pole_move = (pole_end - pole_start) / pole_start if pole_start > 0 else 0

        pole_move_min = FLAG_POLE_MOVE_MIN.get(timeframe, 0.015)
        if pole_move > pole_move_min:
            # ✅ FIXED: flag_highs/flag_lows were the identical price
            # slice reused for both. max()/min() of the same array still
            # produced numerically different high_trend/low_trend (unlike
            # the wedge bug, this wasn't a guaranteed-impossible
            # condition), but it's still measuring "highest close" and
            # "lowest close" of one series rather than genuine swing
            # highs/lows. Use real swing points for the same precision
            # improvement applied to triangles and wedges.
            consolidation = window[len(window) // 3:]
            swings = self._find_swing_points(consolidation, lookback=2)
            swing_highs = [p['price'] for p in swings if p['type'] == 'high']
            swing_lows = [p['price'] for p in swings if p['type'] == 'low']

            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                mid_h = len(swing_highs) // 2 or 1
                mid_l = len(swing_lows) // 2 or 1
                first_half_high = max(swing_highs[:mid_h])
                first_half_low = min(swing_lows[:mid_l])
                high_trend = (max(swing_highs) - first_half_high) / first_half_high if first_half_high > 0 else 0
                low_trend = (min(swing_lows) - first_half_low) / first_half_low if first_half_low > 0 else 0
            else:
                high_trend = low_trend = 0

            if high_trend < 0 and low_trend > 0:
                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(pole_end - current_price) > proximity * 2:
                    return {'detected': False, 'confidence': 0.00}

                trend_context = self._get_trend_context(prices)
                trend = trend_context.get('trend', 'NEUTRAL')

                if trend in ['STRONG_BULLISH', 'BULLISH']:
                    direction = 'BULLISH'
                elif trend in ['STRONG_BEARISH', 'BEARISH']:
                    direction = 'BEARISH'
                else:
                    direction = 'BULLISH'

                confidence = self._calculate_rule_based_confidence('PENNANT', {
                    'complete': True,
                    'recent': True,  # justified: window above is freshness-bounded
                    'near_key_level': True,  # justified: proximity-gated above
                    'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                })

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': 'Bullish pennant detected',
                    'direction': direction,
                    'price_level': round(pole_end, 5),
                    'status': 'COMPLETE',
                    'status_description': f'Bullish pennant in {trend} trend',
                    'pattern_classification': 'CONTINUATION',
                    'continues_trend': trend if direction in ['BULLISH', 'BEARISH'] else None,
                    'details': {'trend': trend}
                }

        return {'detected': False, 'confidence': 0.00}

    def _detect_pennant_bearish(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.PENNANT_BEARISH, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        # ✅ FIXED (freshness - severe): see matching note in
        # _detect_flag_bullish / _detect_pennant_bullish.
        freshness_bars = get_pattern_freshness_bars(timeframe)
        window = prices[-freshness_bars:] if len(prices) >= freshness_bars else prices
        if len(window) < 12:
            return {'detected': False, 'confidence': 0.00}

        pole_start = window[0]
        pole_end = min(window[:len(window) // 3])
        pole_move = (pole_start - pole_end) / pole_start if pole_start > 0 else 0

        pole_move_min = FLAG_POLE_MOVE_MIN.get(timeframe, 0.015)
        if pole_move > pole_move_min:
            # ✅ FIXED: same fix as bullish pennant — real swing highs/lows
            # instead of the same price slice reused for both.
            consolidation = window[len(window) // 3:]
            swings = self._find_swing_points(consolidation, lookback=2)
            swing_highs = [p['price'] for p in swings if p['type'] == 'high']
            swing_lows = [p['price'] for p in swings if p['type'] == 'low']

            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                mid_h = len(swing_highs) // 2 or 1
                mid_l = len(swing_lows) // 2 or 1
                first_half_high = max(swing_highs[:mid_h])
                first_half_low = min(swing_lows[:mid_l])
                high_trend = (max(swing_highs) - first_half_high) / first_half_high if first_half_high > 0 else 0
                low_trend = (min(swing_lows) - first_half_low) / first_half_low if first_half_low > 0 else 0
            else:
                high_trend = low_trend = 0

            if high_trend < 0 and low_trend > 0:
                proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
                if abs(pole_end - current_price) > proximity * 2:
                    return {'detected': False, 'confidence': 0.00}

                trend_context = self._get_trend_context(prices)
                trend = trend_context.get('trend', 'NEUTRAL')

                if trend in ['STRONG_BEARISH', 'BEARISH']:
                    direction = 'BEARISH'
                elif trend in ['STRONG_BULLISH', 'BULLISH']:
                    direction = 'BULLISH'
                else:
                    direction = 'BEARISH'

                confidence = self._calculate_rule_based_confidence('PENNANT', {
                    'complete': True,
                    'recent': True,  # justified: window above is freshness-bounded
                    'near_key_level': True,  # justified: proximity-gated above
                    'volume_ratio': self._check_volume_confirmation(self._extract_volumes(price_evolution), 0.5)
                })

                return {
                    'detected': True,
                    'confidence': round(confidence, 2),
                    'description': 'Bearish pennant detected',
                    'direction': direction,
                    'price_level': round(pole_end, 5),
                    'status': 'COMPLETE',
                    'status_description': f'Bearish pennant in {trend} trend',
                    'pattern_classification': 'CONTINUATION',
                    'continues_trend': trend if direction in ['BULLISH', 'BEARISH'] else None,
                    'details': {'trend': trend}
                }

        return {'detected': False, 'confidence': 0.00}

    # ============================================================
    # ABC CORRECTION - WITH FIXED TOLERANCE
    # ============================================================

    def _detect_abc_correction(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        # ✅ REBUILT: this function used to slice the price window into
        # three mechanically EQUAL thirds (len(prices)//3, 2*len(prices)//3)
        # and call those "wave A/B/C" regardless of where the real turning
        # points actually were -- every other corrective-style detector in
        # this file (_detect_corrective_waves, _detect_impulse_waves) uses
        # real swing-point detection; this one didn't. Now it does, via the
        # same shared _group_swings_into_waves() helper (which also carries
        # the direction-labeling and dropped-first-leg fixes made earlier).
        min_bars = self._get_min_bars_for_timeframe(PatternType.ABC_CORRECTION, timeframe)

        if len(prices) < min_bars or len(prices) < 20:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        swing_points = self._find_swing_points(prices)
        if len(swing_points) < 4:
            return {'detected': False, 'confidence': 0.00}

        waves = self._group_swings_into_waves(swing_points)
        if len(waves) < 3:
            return {'detected': False, 'confidence': 0.00}

        # ✅ FIXED: was always `waves[-3], waves[-2], waves[-1]` -- locked
        # to exactly the trailing 3 legs. The moment even one small new
        # leg starts and confirms after a real, complete, obvious
        # correction -- normal market behavior, not an edge case -- that
        # window slides past it and the correction becomes permanently
        # invisible, even though it's still sitting right there a leg or
        # two back. Verified directly: a clean C/A-ratio-1.00 correction
        # stopped being detected the instant one small new leg confirmed
        # after it. Now searches backward through a bounded recent window
        # for the most recent combination that actually validates.
        found = self._find_recent_abc(waves, ratio_ok=lambda r: abs(r - 1.0) < 0.7)
        if found is None:
            return {'detected': False, 'confidence': 0.00}
        wave_a, wave_b, wave_c = found
        ratio = wave_c['size'] / wave_a['size']

        # Freshness: now that the match isn't implicitly pinned to the
        # trailing edge, explicitly confirm wave_c's end is still recent
        # -- a correction found several legs back that also happens to
        # validate shouldn't be reported as "current" just because
        # nothing more recent qualified.
        max_age_bars = get_pattern_freshness_bars(timeframe)
        bars_since_c = (len(prices) - 1) - wave_c['end']['index']
        if bars_since_c > max_age_bars:
            return {'detected': False, 'confidence': 0.00}

        proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
        if abs(wave_c['end']['price'] - current_price) > proximity * 2:
            return {'detected': False, 'confidence': 0.00}

        confidence = self._calculate_rule_based_confidence('ABC_CORRECTION', {
            'complete': True,
            'recent': True,
            'near_key_level': True
        })

        # ✅ FIXED: this used to report wave_c's own raw movement direction
        # here (BULLISH if wave C moved up, BEARISH if down). That's fine
        # as a description of what wave C did, but this 'direction' field
        # is what asset_analysis.py's pattern-scoring loop reads and feeds
        # straight into _get_pattern_recommendation() as "the direction to
        # trade" -- which is correct for continuation-style patterns
        # (rectangle breakout, flag, wedge) but backwards for a completing
        # correction. An ABC correction finishing is, by definition, where
        # the correction is exhausted and the larger trend it interrupted
        # is due to resume -- the actionable call is the OPPOSITE of wave
        # C's own direction, exactly the same fix already made to Wave C
        # in _get_elliott_wave_recommendation(). Without this, a
        # bullish-correction-within-a-downtrend could clear the pattern
        # confidence gate and get reported as a BUY (continuing the
        # correction) at the same moment the Elliott Wave engine correctly
        # calls SELL (reversing out of it) for the same underlying swing
        # structure -- which is exactly the kind of self-contradiction
        # this pattern is supposed to help avoid, not cause.
        raw_wave_c_direction = 'BULLISH' if wave_c['direction'] == 1 else 'BEARISH'
        direction = 'BEARISH' if raw_wave_c_direction == 'BULLISH' else 'BULLISH'

        return {
            'detected': True,
            'confidence': round(confidence, 2),
            'description': (
                f'ABC correction complete (swing-based), C/A ratio: {ratio:.2f} -- '
                f'wave C moved {raw_wave_c_direction.lower()}, reversal back toward '
                f'the larger trend expected'
            ),
            'price_level': round(wave_c['end']['price'], 5),
            'direction': direction,
            'status': 'COMPLETE',
            'status_description': 'ABC correction complete, reversal zone',
            'pattern_classification': 'REVERSAL',
            'details': {
                'wave_a_size_pips': round(wave_a['size'] / (getattr(self, '_current_pip_size', 0.0001) or 0.0001), 1),
                'wave_b_size_pips': round(wave_b['size'] / (getattr(self, '_current_pip_size', 0.0001) or 0.0001), 1),
                'wave_c_size_pips': round(wave_c['size'] / (getattr(self, '_current_pip_size', 0.0001) or 0.0001), 1),
                'wave_c_own_direction': raw_wave_c_direction,
            }
        }

    # ============================================================
    # MEAN REVERSION
    # ============================================================

    def _detect_mean_reversion(self, prices: List[float], price_evolution: List[Dict], timeframe: str) -> Dict:
        min_bars = self._get_min_bars_for_timeframe(PatternType.MEAN_REVERSION, timeframe)

        if len(prices) < min_bars:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1] if prices else 0

        # ✅ FIXED: was `avg_price = sum(prices) / len(prices)` — averaging
        # over the entire fetched history (often ~500 bars) rather than a
        # recent, actionable window. Also replaced the flat 0.3% deviation
        # threshold (~34 pips on EURUSD, essentially unreachable versus a
        # quiet local M1 window) with a pip-based, timeframe-aware one.
        window_size = MEAN_REVERSION_WINDOW.get(timeframe, MEAN_REVERSION_WINDOW['DEFAULT'])
        window = prices[-window_size:] if len(prices) >= window_size else prices
        avg_price = sum(window) / len(window)
        deviation = abs(current_price - avg_price) / avg_price * 100 if avg_price > 0 else 0

        pip_size = getattr(self, '_current_pip_size', 0.0001) or 0.0001
        deviation_pips = abs(current_price - avg_price) / pip_size
        min_deviation_pips = MEAN_REVERSION_MIN_DEVIATION_PIPS.get(timeframe, MEAN_REVERSION_MIN_DEVIATION_PIPS['DEFAULT'])

        if deviation_pips > min_deviation_pips:
            proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)
            if abs(avg_price - current_price) > proximity * 2:
                return {'detected': False, 'confidence': 0.00}

            confidence = self._calculate_rule_based_confidence('MEAN_REVERSION', {
                'complete': deviation > 0.5,
                'recent': True,
                'near_key_level': True
            })

            return {
                'detected': True,
                'confidence': round(confidence, 2),
                'description': f'Mean reversion: {deviation:.2f}% from average',
                'direction': 'BEARISH' if current_price > avg_price else 'BULLISH',
                'price_level': round(avg_price, 5),
                'status': 'COMPLETE' if deviation > 0.5 else 'FORMING',
                'status_description': 'Mean reversion signal active',
                'pattern_classification': 'NEUTRAL',
                'details': {'deviation': round(deviation, 2)}
            }

        return {'detected': False, 'confidence': 0.00}

    # ============================================================
    # ELLIOTT WAVE DETECTION
    # ============================================================

    def _detect_impulse_waves(self, prices: List[float]) -> Dict:
        if len(prices) < 40:
            return {'detected': False, 'confidence': 0.00}

        swing_points = self._find_swing_points(prices)

        if len(swing_points) < 8:
            return {'detected': False, 'confidence': 0.00}

        waves = self._group_swings_into_waves(swing_points)

        if len(waves) >= 5:
            # ✅ FIXED: was `waves[0], waves[1], waves[2], waves[3], waves[4]`
            # -- always the FIRST five legs of the ENTIRE swing history
            # handed to this function, never the five most recent. On any
            # window with more than 5 total legs (the normal case once you
            # have more than a couple hours of M1 data — this function
            # requires len(prices) >= 40 to even run), this was analyzing,
            # and reporting as "the current wave", a structure that could
            # be hundreds of bars in the past — while every other
            # indicator in the system is computed from the latest bars.
            # This is a direct, structural reason Elliott Wave calls could
            # look wrong or contradict everything else: they weren't
            # describing the same moment in time as the rest of the
            # analysis. waves[-1] is always the most recently completed
            # (or still-forming — see _group_swings_into_waves) leg, so
            # slicing from the end anchors "wave 5" at the actual present.
            last5 = waves[-5:]
            wave_sizes = [w['size'] for w in last5]
            wave1, wave2, wave3, wave4, wave5 = last5
            overall_up = wave1['direction'] == 1

            # ✅ FIXED: this function previously approximated all three
            # canonical Elliott impulse validity rules with unrelated
            # size-ratio heuristics (wave2_size < wave1_size*0.7, etc.)
            # instead of the actual rules, which are PRICE-LEVEL checks:
            #
            #   Rule 1 (wave 3 not shortest): was `w3 > w1 AND w3 > w5`,
            #   which wrongly requires wave 3 to be the LARGEST -- the
            #   real rule only forbids w3 being the SMALLEST of the
            #   three, so a legitimate extended-fifth impulse (w5 > w3)
            #   was being rejected outright.
            #
            #   Rule 2 (wave 2 never retraces 100% of wave 1): was never
            #   actually checked -- a size ratio on wave 2 alone can't
            #   tell you whether wave 2's END PRICE crossed back past
            #   wave 1's START PRICE, which is what the real rule means.
            #
            #   Rule 3 (wave 4 doesn't overlap wave 1): same problem --
            #   was a size ratio on wave 4 vs wave 3, never actually
            #   checking whether wave 4's end price crossed into wave 1's
            #   price territory. (Exception: diagonals allow this overlap
            #   -- _detect_diagonal_waves() handles that separately, this
            #   function is the classic non-diagonal impulse only.)

            wave3_not_shortest = wave_sizes[2] >= wave_sizes[0] or wave_sizes[2] >= wave_sizes[4]

            if overall_up:
                wave2_valid = wave2['end']['price'] > wave1['start']['price']
                wave4_valid = wave4['end']['price'] > wave1['end']['price']
            else:
                wave2_valid = wave2['end']['price'] < wave1['start']['price']
                wave4_valid = wave4['end']['price'] < wave1['end']['price']

            if wave3_not_shortest and wave2_valid and wave4_valid:
                # Magnitude sanity checks kept as a confidence signal (not
                # a hard rule) -- waves 1 and 3 should be substantial
                # relative to the average, or this is more likely noise
                # than a real impulse.
                wave1_impulse = wave_sizes[0] > np.mean(wave_sizes) * 0.5
                wave3_impulse = wave_sizes[2] > np.mean(wave_sizes) * 0.7

                if wave1_impulse and wave3_impulse:
                    # ✅ FIXED: direction and entry/target used to be
                    # ignored entirely here — every impulse wave was
                    # later reported as BULLISH by
                    # _get_elliott_wave_recommendation() regardless of
                    # whether prices actually rose or fell, and
                    # entry/target were fabricated as current_price *
                    # 0.998 (a flat -0.2% offset unrelated to the real
                    # wave). Both are now derived from the actual
                    # detected swing geometry.
                    overall_direction = 'BULLISH' if overall_up else 'BEARISH'
                    sign = 1 if overall_direction == 'BULLISH' else -1

                    # Entry: the real, already-confirmed end of wave 4
                    # (the pullback low/high), not a guessed percentage.
                    entry_price = wave4['end']['price']

                    # Target: classic wave-5 ≈ wave-1 length, projected
                    # from the wave-4 turning point. Conservative choice
                    # vs. a wave-3 extension, which is noisier on M1.
                    target = entry_price + sign * wave1['size']

                    return {
                        'detected': True,
                        'confidence': 0.70,
                        'current_wave': '5' if len(waves) >= 5 else f'{len(waves)}',
                        'next_wave': 'A' if len(waves) >= 5 else f'{len(waves) + 1}',
                        'direction': overall_direction,
                        # Same `direction` overwrite applies here -- see the
                        # note in _detect_corrective_waves.
                        'wave_own_direction': overall_direction,
                        'description': f'Impulse wave detected (1-2-3-4-5), wave runs {overall_direction}',
                        'fib_levels': {'0.618': entry_price},
                        'targets': {'wave_5': target},
                        'entry_price': entry_price
                    }

        return {'detected': False, 'confidence': 0.00}

    def _detect_corrective_waves(self, prices: List[float]) -> Dict:
        if len(prices) < 20:
            return {'detected': False, 'confidence': 0.00}

        swing_points = self._find_swing_points(prices)

        if len(swing_points) < 5:
            return {'detected': False, 'confidence': 0.00}

        waves = self._group_swings_into_waves(swing_points)

        if len(waves) >= 3:
            # ✅ FIXED: was `waves[-3], waves[-2], waves[-1]` -- rigidly
            # locked to exactly the trailing 3 legs. The instant even one
            # small new leg starts and confirms after a real, complete,
            # obvious correction -- normal market behavior, not an edge
            # case -- that window slides past the correction and it
            # becomes permanently invisible, even though it's still
            # sitting right there a leg or two back. Verified directly on
            # synthetic data: a clean C/A-ratio-1.00 correction stopped
            # being detected the instant one small new leg confirmed
            # after it. Now searches backward through a bounded recent
            # window for the most recent combination that actually
            # validates, via the same helper _detect_abc_correction uses.
            # ✅ FIXED (2026-09-15): any three legs with C/A between 0.5 and 1.8
            # used to count as a COMPLETED correction -- nearly every stretch
            # of M1 bars zigzags like that, so wave C was reported on 83% of
            # bars at a fixed 0.60 and each one called a reversal. A
            # correction needs something to correct and has to be finished:
            #   * C has travelled at least ~A's length (C/A >= 0.9)
            #   * the leg before A is the impulse: opposite to A, larger than A
            #   * A->C retraces no more than 0.786 of that impulse
            found = self._find_recent_abc(waves, ratio_ok=lambda r: 0.9 <= r <= 1.8)
            if found is not None:
                wave_a, wave_b, wave_c = found
                ratio = wave_c['size'] / wave_a['size']
                ia = next((i for i, w in enumerate(waves) if w is wave_a), None)
                impulse = waves[ia - 1] if ia else None
                correction_depth = abs(wave_c['end']['price'] - wave_a['start']['price'])
                if (impulse is None or impulse['direction'] == wave_a['direction']
                        or impulse['size'] < wave_a['size']
                        or correction_depth > 0.786 * impulse['size']):
                    return {'detected': False, 'confidence': 0.00}
                # fit to the textbook C = A or C = 1.618 A
                fit = max(0.0, 1.0 - min(abs(ratio - 1.0), abs(ratio - 1.618)) / 0.4)
                abc_confidence = round(0.50 + 0.25 * fit, 3)

                # Freshness: now that the match isn't implicitly pinned to
                # the trailing edge, explicitly confirm wave_c's end is
                # still recent enough to call "current".
                max_age_bars = get_pattern_freshness_bars(self._current_timeframe)
                bars_since_c = (len(prices) - 1) - wave_c['end']['index']
                if bars_since_c <= max_age_bars:
                    # ✅ ADDED: zigzag vs. flat classification. Previously
                    # every 3-leg A-B-C correction was reported
                    # identically as generic "Corrective wave (A-B-C)"
                    # regardless of internal structure, even though the
                    # data needed to tell a sharp zigzag (5-3-5, B
                    # retraces relatively little of A) from a sideways
                    # flat (3-3-5, B retraces most/all of A) was already
                    # sitting right here as wave_b['size'] / wave_a['size'].
                    b_to_a_ratio = wave_b['size'] / wave_a['size'] if wave_a['size'] > 0 else 0
                    if b_to_a_ratio >= 0.9:
                        corrective_subtype = 'FLAT'
                        structure_note = '3-3-5, sideways -- wave B retraced most of wave A'
                    else:
                        corrective_subtype = 'ZIGZAG'
                        structure_note = '5-3-5, sharp correction'

                    # ✅ FIXED: same issue as impulse waves — direction
                    # and entry/target are now derived from the actual
                    # wave C geometry instead of always being reported
                    # BEARISH with a fabricated entry price.
                    overall_direction = 'BULLISH' if wave_c['direction'] == 1 else 'BEARISH'
                    sign = 1 if overall_direction == 'BULLISH' else -1

                    # Entry: the real end of wave B (the actual start
                    # of wave C), not a guessed percentage.
                    entry_price = wave_b['end']['price']

                    # Target: wave C ≈ wave A length (1.0 extension),
                    # projected from the wave-B turning point.
                    target = entry_price + sign * wave_a['size']

                    return {
                        'detected': True,
                        'confidence': abc_confidence,
                        'current_wave': 'C',
                        'next_wave': '1',
                        'direction': overall_direction,
                        # ✅ ADDED: kept under its own unambiguous name because
                        # `direction` does NOT survive intact --
                        # _get_elliott_wave_recommendation() overwrites it with
                        # the recommended TRADE direction, which at Wave C
                        # completion is deliberately the OPPOSITE of the
                        # correction's own direction (a completed correction
                        # reverses). The published object therefore ends up with
                        # direction: BEARISH sitting next to a description
                        # reading "direction: BULLISH" -- both correct, one word
                        # meaning two different things. Seen live on XAGUSD twice.
                        'wave_own_direction': overall_direction,
                        'wave_subtype': corrective_subtype,
                        'description': f'{corrective_subtype} corrective wave detected (A-B-C), '
                                       f'C/A ratio: {ratio:.2f}, B/A retracement: {b_to_a_ratio:.2f} '
                                       f'({structure_note}), wave C runs {overall_direction}',
                        'fib_levels': {'0.618': entry_price},
                        'targets': {'wave_c_completion': target},
                        'entry_price': entry_price
                    }

        return {'detected': False, 'confidence': 0.00}

    def _detect_diagonal_waves(self, prices: List[float]) -> Dict:
        if len(prices) < 30:
            return {'detected': False, 'confidence': 0.00}

        swing_points = self._find_swing_points(prices)

        if len(swing_points) < 8:
            return {'detected': False, 'confidence': 0.00}

        # ✅ FIXED: was filtering by `p['price'] > swing_points[0]['price'] *
        # 1.005` / `< swing_points[0]['price'] * 0.995` -- comparing every
        # swing point's price against a threshold relative to the FIRST
        # swing point in the window, rather than using each point's own
        # already-correct 'type' field from find_swing_points(). In a
        # realistic converging diagonal, the first swing point is often
        # itself the most extreme high or low, which makes "1.5% above
        # the first point" structurally unsatisfiable for every other
        # high in the sequence. Verified directly: a synthetic 5-high/
        # 5-low ending-diagonal shape produced ZERO threshold-classified
        # highs (all 5 real highs excluded) even though find_swing_points
        # had already correctly typed every one of them. Now uses that
        # existing, correct classification directly.
        highs = [p for p in swing_points if p['type'] == 'high']
        lows = [p for p in swing_points if p['type'] == 'low']

        if len(highs) >= 3 and len(lows) >= 3:
            high_trend = (highs[-1]['price'] - highs[0]['price']) / highs[0]['price'] if highs[0]['price'] > 0 else 0
            low_trend = (lows[-1]['price'] - lows[0]['price']) / lows[0]['price'] if lows[0]['price'] > 0 else 0

            # Bearish ending diagonal: both highs and lows declining,
            # trendlines converging.
            # ✅ FIXED: comparison was backwards. Convergence means the
            # range (high - low) shrinks over time, which requires highs
            # to be falling MORE steeply than lows (high_trend < low_trend,
            # both negative) so the top boundary closes in on the bottom
            # one -- not high_trend > low_trend as this checked, which
            # actually selects for a WIDENING channel instead. Verified
            # directly: a genuine converging bearish diagonal (range
            # shrinking from 0.0060 to 0.0030 in a synthetic test) failed
            # this check before the fix and passes it after. The bullish
            # branch just below was already using the equivalent correct
            # comparison (low_trend > high_trend, i.e. the same relation).
            if high_trend < 0 and low_trend < 0 and high_trend < low_trend:
                return {
                    'detected': True,
                    'confidence': 0.55,
                    'current_wave': '5',
                    'next_wave': 'A',
                    'direction': 'BEARISH',
                    'description': 'Ending diagonal detected (converging trendlines, bearish)'
                }

            # ✅ FIXED: the symmetric bullish case (both highs and lows
            # rising, trendlines converging) was never checked before —
            # diagonal detection only ever fired for bearish setups.
            if high_trend > 0 and low_trend > 0 and low_trend > high_trend:
                return {
                    'detected': True,
                    'confidence': 0.55,
                    'current_wave': '5',
                    'next_wave': 'A',
                    'direction': 'BULLISH',
                    'description': 'Ending diagonal detected (converging trendlines, bullish)'
                }

        return {'detected': False, 'confidence': 0.00}

    def _detect_triangle_waves(self, prices: List[float]) -> Dict:
        # ✅ FIXED: this detector's only criterion used to be "are the
        # last 5 bars' range narrower than the previous 5 bars' range" --
        # that's not validating a triangle wave structure at all, just
        # asking whether volatility recently dipped, which happens
        # constantly in any market and has nothing to do with a genuine
        # 5-point converging ABCDE formation. swing_points was already
        # being fetched (the len(swing_points) < 8 gate below used it)
        # but never actually used for the detection itself -- the real
        # geometry check below is what that data was for.
        #
        # This matters more than it might look: of the four Elliott Wave
        # candidates (impulse/corrective/diagonal/triangle), this one has
        # by far the loosest bar to clear, so on most bars it was the
        # ONLY candidate that fired at all -- meaning the "Elliott Wave"
        # signal shown to the trader was this flat, contentless
        # WAIT/NEUTRAL/0%-confidence placeholder most of the time,
        # regardless of what price was actually doing.
        if len(prices) < 25:
            return {'detected': False, 'confidence': 0.00}

        swing_points = self._find_swing_points(prices)

        if len(swing_points) < 8:
            return {'detected': False, 'confidence': 0.00}

        # ✅ FIXED (freshness): a converging structure found anywhere in
        # the whole price history isn't "currently forming" just because
        # it exists somewhere in `prices` -- same staleness class of bug
        # already fixed for impulse/corrective waves above. Only the last
        # 5 swing points (the most recent potential A-B-C-D-E vertices)
        # are considered, and the last one must be recent.
        last5 = swing_points[-5:]
        max_age = get_pattern_freshness_bars(self._current_timeframe)
        bars_since_last_point = (len(prices) - 1) - last5[-1]['index']
        if bars_since_last_point > max_age:
            return {'detected': False, 'confidence': 0.00}

        # A triangle's five vertices must strictly alternate high/low/
        # high/low/high (or the mirror) -- this is the actual structural
        # definition a range-comparison can't check.
        types = [p['type'] for p in last5]
        alternates = all(types[i] != types[i + 1] for i in range(len(types) - 1))
        if not alternates:
            return {'detected': False, 'confidence': 0.00}

        # Converging: each leg smaller than the leg two positions back
        # (leg C-D narrower than leg A-B, leg D-E narrower than leg B-C)
        # -- the actual definition of a contracting triangle, not just
        # "the last 5 bars happened to be quieter than the previous 5".
        legs = [abs(last5[i + 1]['price'] - last5[i]['price']) for i in range(4)]
        if legs[0] <= 0 or legs[1] <= 0:
            return {'detected': False, 'confidence': 0.00}
        converging = legs[2] < legs[0] and legs[3] < legs[1]
        if not converging:
            return {'detected': False, 'confidence': 0.00}

        # ✅ FIXED (direction): this always returned no 'direction' key at
        # all, which _get_elliott_wave_recommendation's triangle branch
        # then always rendered as a hardcoded WAIT/NEUTRAL/0% regardless
        # of price structure -- a permanent non-signal. A triangle is
        # genuinely lower-conviction pre-breakout (correctly still capped
        # low below), but "no information at all" isn't the same as "low
        # confidence" -- where price currently sits inside the narrowing
        # range does lean one way, the same edge-proximity idea the
        # rectangle detector already uses for its forming/continuation
        # case.
        highs_in_window = [p['price'] for p in last5 if p['type'] == 'high']
        lows_in_window = [p['price'] for p in last5 if p['type'] == 'low']
        upper = max(highs_in_window)
        lower = min(lows_in_window)
        triangle_height = upper - lower
        if triangle_height <= 0:
            return {'detected': False, 'confidence': 0.00}

        current_price = prices[-1]
        position_in_range = (current_price - lower) / triangle_height  # 0 = at lower edge, 1 = at upper edge

        if position_in_range >= 0.65:
            direction = 'BULLISH'
        elif position_in_range <= 0.35:
            direction = 'BEARISH'
        else:
            direction = 'NEUTRAL'

        # Contraction ratio (how tight the newest leg is vs. the oldest
        # of the five) is used as the confidence signal -- a triangle
        # that has narrowed a lot is closer to its apex/breakout than one
        # that's barely converged yet, which is real information the old
        # flat 0.50 constant wasn't capturing. Capped below impulse
        # (0.70) and corrective (0.60): a pre-breakout triangle is
        # legitimately lower-conviction than a confirmed 5-wave or 3-wave
        # structure, by design.
        contraction_ratio = legs[3] / legs[0]
        confidence = max(0.30, min(0.65, 0.65 - contraction_ratio * 0.30))

        return {
            'detected': True,
            'confidence': round(confidence, 2),
            'current_wave': 'E',
            'next_wave': '1',
            'direction': direction,
            'description': (
                f'Triangle wave detected (converging range, apex lean '
                f'{direction.lower()}, price {position_in_range:.0%} through the range)'
            ),
        }

    def _find_swing_points(self, prices: List[float], lookback: int = 2) -> List[Dict]:
        """Find swing highs and lows.

        ✅ Delegates to core/swing_points.py — the single shared swing
        detector also used by indicators.py's zone-level detection. The
        old local version here filtered by distance-to-previous-bar
        instead of real swing amplitude; see swing_points.py docstring.
        """
        # ✅ pip_size threaded through. self._current_pip_size is already
        # set by analyze_patterns() and used elsewhere in this class (see
        # _get_trend_context); the min-swing table is expressed in pips
        # and is meaningless without it on non-FX-major instruments.
        # ✅ ATR threaded through (2026-09-15): the pip table is 0.01 ATR on
        # metals, so waves were counted on single-tick wiggles and a wave
        # label existed on ~95% of study bars.
        min_swing = get_min_swing_size(
            self._current_timeframe,
            getattr(self, '_current_pip_size', None),
            getattr(self, '_current_atr_pips', None),
        )
        return find_swing_points(prices, lookback=lookback, min_amplitude=min_swing)

    def _group_swings_into_waves(self, swing_points: List[Dict]) -> List[Dict]:
        """
        Groups a swing-point sequence into direction-consistent legs
        ("waves"): {'direction', 'start', 'end', 'size'}.

        ✅ FIXED: this used to be two separately-maintained, buggy copies
        of the same loop (one in _detect_impulse_waves, one in
        _detect_corrective_waves). Both had two distinct bugs, confirmed
        by direct trace on synthetic data:
          1. Direction label was STALE — each appended wave was labeled
             with the direction of the PREVIOUS leg, not its own actual
             start->end movement. For a cleanly alternating swing series
             this inverted every single wave's direction (a verified
             +40 pip up move was being recorded as direction=-1).
          2. The very first leg (swing_points[0] -> swing_points[1]) was
             silently dropped -- the loop's first comparison can never
             register as a "change" against the direction it just seeded
             itself from, so "wave 1" as reported was actually already
             the second real leg of price action.
        Both are fixed here by tracking where the CURRENT leg started
        (leg_start_idx) and only finalizing it -- with its own correct
        direction -- when a genuine reversal is confirmed, plus flushing
        the final in-progress leg after the loop instead of dropping it.
        """
        if len(swing_points) < 2:
            return []

        waves = []
        leg_start_idx = 0
        direction = 1 if swing_points[1]['price'] > swing_points[0]['price'] else -1

        for i in range(1, len(swing_points)):
            current_direction = 1 if swing_points[i]['price'] > swing_points[i - 1]['price'] else -1
            if current_direction != direction:
                waves.append({
                    'direction': direction,  # the direction that was actually active for this leg
                    'start': swing_points[leg_start_idx],
                    'end': swing_points[i - 1],
                    'size': abs(swing_points[i - 1]['price'] - swing_points[leg_start_idx]['price'])
                })
                leg_start_idx = i - 1
                direction = current_direction

        # Flush the final in-progress leg (previously dropped entirely).
        waves.append({
            'direction': direction,
            'start': swing_points[leg_start_idx],
            'end': swing_points[-1],
            'size': abs(swing_points[-1]['price'] - swing_points[leg_start_idx]['price'])
        })

        return waves

    def _find_recent_abc(
        self,
        waves: List[Dict],
        ratio_ok: Callable[[float], bool],
        max_candidates: int = 6,
    ) -> Optional[Tuple[Dict, Dict, Dict]]:
        """
        Scans backward through the most recent legs for the most recent
        valid 3-consecutive-leg A-B-C combination -- wave_a and wave_c in
        the same direction, wave_b opposite, and ratio_ok(wave_c size /
        wave_a size) passing. Returns (wave_a, wave_b, wave_c) for the
        first (most recent) match found, or None if nothing in the
        window qualifies.

        ✅ FIXED: _detect_abc_correction and _detect_corrective_waves both
        used to ALWAYS take exactly the trailing 3 legs (waves[-3:]) as
        "the" correction, full stop. That's too rigid: the instant even
        one small new leg starts and gets confirmed after a real, obvious,
        textbook correction completes -- completely normal, unremarkable
        market behavior, not an edge case -- the trailing-3 window slides
        past the correction entirely, and it becomes permanently invisible
        even though it's still sitting right there a leg or two back and
        is still genuinely useful, current information. Verified directly:
        a clean C/A-ratio-1.00 correction stopped being detected the
        moment a single small new leg confirmed after it, even though nothing
        about the original correction had changed.
        Scanning backward through a bounded recent window instead means a
        correction that just completed is still found even once a small
        new leg has begun, without reaching arbitrarily far into stale
        history -- max_candidates bounds how far back this looks, and it's
        deliberately small (this is "did I just miss it by one leg", not a
        general historical pattern search).
        """
        if len(waves) < 3:
            return None
        limit = min(max_candidates, len(waves) - 2)
        for offset in range(limit):
            # offset=0 -> waves[-3:] (the old, only, behavior), offset=1
            # -> waves[-4:-1], etc. -- most recent combination first.
            end = len(waves) - offset
            start = end - 3
            wave_a, wave_b, wave_c = waves[start], waves[start + 1], waves[start + 2]
            if wave_a['direction'] != wave_c['direction'] or wave_b['direction'] == wave_a['direction']:
                continue
            if wave_a['size'] <= 0:
                continue
            if not ratio_ok(wave_c['size'] / wave_a['size']):
                continue
            return wave_a, wave_b, wave_c
        return None

    # ============================================================
    # HIDDEN GEM DETECTION
    # ============================================================

    def _detect_institutional_accumulation_gem(self, price_evolution: List[Dict]) -> Optional[HiddenGem]:
        pass

    def _detect_liquidity_sweep_gem(self, price_evolution: List[Dict]) -> Optional[HiddenGem]:
        pass

    # ============================================================
    # HELPER METHODS
    # ============================================================

    def _calculate_rule_based_confidence(self, pattern_type: str, details: Dict) -> float:
        """Base geometric/volume confidence for a single detected pattern.

        ✅ FIXED: this used to also check 'rsi_aligned', 'trend_aligned'
        (worth 0.10 each) and 'tf_confirmed' (worth 0.15) - 35% of the
        achievable score. None of the ~20 pattern detectors ever set
        those three keys in the `details` dict they pass in here, so
        `.get(..., False)` always fell back to False and those branches
        never fired, on any pattern, ever. That's why confidence looked
        static: every pattern's score was really only ever built from
        'complete' + volume_ratio + the near-constant 'near_key_level'/
        'recent' flags (which most detectors hardcode to True), giving a
        handful of possible values clustered in a narrow band.

        trend/RSI alignment is now scored for real in
        _apply_alignment_scoring() below, run once on each pattern's
        final confidence using its actual 'direction' field (which
        detectors DO set) against external_trend/external_rsi - instead
        of requiring every detector to redundantly populate flags. The
        old tf_confirmed branch is removed outright rather than patched:
        with pattern analysis now scoped to the current timeframe only
        (PATTERN_ANALYSIS_CURRENT_TF_ONLY), there is no second timeframe
        to confirm against, so a "confirmed" flag here would just be
        dead weight again.
        """
        confidence = 0.0

        if details.get('complete', False):
            confidence += 0.25

        volume_ratio = details.get('volume_ratio', 0)
        if isinstance(volume_ratio, bool):
            if volume_ratio:
                confidence += 0.20
        elif volume_ratio > 1.5:
            confidence += 0.20
        elif volume_ratio > 1.2:
            confidence += 0.15
        elif volume_ratio > 0.8:
            confidence += 0.08

        if details.get('near_key_level', False):
            confidence += 0.10

        if details.get('recent', False):
            confidence += 0.10

        session_mult = SESSION_ADJUSTMENTS.get(self._current_session, 1.0)
        if session_mult != 1.0:
            confidence = confidence * session_mult

        regime_mult = REGIME_ADJUSTMENTS.get(self._current_regime, 1.0)
        if regime_mult != 1.0:
            confidence = confidence * regime_mult

        return round(min(1.0, confidence), 2)

    def _apply_alignment_scoring(self, pattern_data: Dict) -> float:
        """Adjust a detected pattern's confidence for real momentum/trend
        alignment - the checks 'rsi_aligned'/'trend_aligned' were meant to
        do but never actually ran (see _calculate_rule_based_confidence).

        Runs once per pattern using fields every detector already sets
        ('direction', 'confidence', 'pattern_classification'), so it
        needed no changes to the ~20 individual detector functions.

        Trend alignment: continuation patterns (flags, pennants,
        triangles-as-continuation, rectangles) should score higher when
        their direction agrees with the prevailing trend, and lower when
        they're fighting it. Reversal patterns (head & shoulders, double
        top/bottom) are the opposite - counter-trend IS the setup, so
        agreement with the *prior* trend isn't meaningful here and isn't
        scored; instead they lean on RSI extremes below.

        RSI alignment: a bullish setup forming while RSI is still
        overbought (or a bearish one while still oversold) is fighting
        exhausted momentum and should score lower; forming from the
        opposite extreme (oversold for bullish, overbought for bearish)
        is the textbook confirming case and scores higher.
        """
        confidence = pattern_data.get('confidence', 0.0)
        direction = pattern_data.get('direction', 'NEUTRAL')
        classification = pattern_data.get('pattern_classification', '')

        if direction not in ('BULLISH', 'BEARISH'):
            return round(min(1.0, max(0.0, confidence)), 2)

        adjustment = 0.0

        if classification == 'CONTINUATION' and self._external_trend:
            et = self._external_trend.upper()
            if direction == 'BULLISH':
                if 'BULLISH' in et:
                    adjustment += 0.10
                elif 'BEARISH' in et:
                    adjustment -= 0.10
            elif direction == 'BEARISH':
                if 'BEARISH' in et:
                    adjustment += 0.10
                elif 'BULLISH' in et:
                    adjustment -= 0.10

        if self._external_rsi is not None:
            if direction == 'BULLISH':
                if self._external_rsi <= 35:
                    adjustment += 0.10
                elif self._external_rsi >= 70:
                    adjustment -= 0.10
            elif direction == 'BEARISH':
                if self._external_rsi >= 65:
                    adjustment += 0.10
                elif self._external_rsi <= 30:
                    adjustment -= 0.10

        # ✅ NEW: classification-aware regime gate (see REGIME_
        # CLASSIFICATION_GATE above) -- a breakout-style CONTINUATION
        # pattern forming in a RANGING market, or a mean-reversion-style
        # REVERSAL pattern forming in a TRENDING market, is fighting the
        # regime it's in. This is intentionally a much stronger effect
        # than REGIME_ADJUSTMENTS' flat per-regime reweight (which still
        # applies too, in _calculate_rule_based_confidence above) --
        # gating a bad-fit setup down to near-zero rather than a mild
        # uniform haircut.
        gate_mult = REGIME_CLASSIFICATION_GATE.get((self._current_regime, classification), 1.0)

        return round(min(1.0, max(0.0, (confidence + adjustment) * gate_mult)), 2)

    def _check_volume_confirmation(self, volumes: List[float], required_ratio: float = 0.5) -> bool:
        # ✅ MODERATE TIGHTENING: required_ratio raised from 0.2 to 0.5
        # everywhere it's called. At 0.2, current volume only had to
        # exceed 20% of the recent average to "confirm" a pattern - an
        # almost meaningless bar that passed on nearly every bar,
        # including quiet/noise ones. 0.5 still doesn't require
        # above-average volume (that would be stricter still), just
        # meaningfully above negligible.
        if len(volumes) < 5:
            return True

        avg_volume = sum(volumes) / len(volumes)
        current_volume = volumes[-1] if volumes else 0
        return current_volume > avg_volume * required_ratio

    def _series_or_close(self, price_evolution: List[Dict],
                         key: str, prices: List[float]) -> List[float]:
        """
        A per-bar extreme ('h' high / 'l' low) from price_evolution,
        falling back to closes when the field is absent.

        WHY THIS EXISTS

        price_evolution carries 'o','h','l','p' (p = close) per bar, and
        several detectors accepted it and then worked purely off
        `prices`, which is closes only. For patterns DEFINED by extremes
        that is the wrong series: a double bottom is two matching LOWS,
        and finding them among closing prices misses the wicks where the
        pattern actually forms -- and can miss the pattern entirely when
        a bar closes well off its low.

        Fallback rather than failure: a caller that supplies no
        price_evolution keeps the old behaviour exactly, so this cannot
        turn a working call into a broken one.
        """
        if not price_evolution:
            return prices
        out = []
        for point in price_evolution:
            v = point.get(key)
            if v is None:
                return prices
            try:
                v = float(v)
            except (TypeError, ValueError):
                return prices
            if v <= 0:
                return prices
            out.append(v)
        return out if len(out) == len(prices) else prices

    def _extract_prices(self, price_evolution: List[Dict]) -> List[float]:
        prices = []
        for point in price_evolution:
            price = point.get('p', 0)
            if price > 0:
                prices.append(price)
        return prices

    def _extract_volumes(self, price_evolution: List[Dict]) -> List[float]:
        volumes = []
        for point in price_evolution:
            vo = point.get('vo', {})
            if isinstance(vo, dict):
                vol = vo.get('rt', 1.0)
            else:
                vol = 1.0
            volumes.append(vol)
        return volumes

    def _calculate_signal_quality(self, signals: PredictiveSignals) -> float:
        total = len(signals.early_warnings) + len(signals.reversal_signals)
        if total == 0:
            return 0

        quality = len(signals.early_warnings) * 0.8 + len(signals.reversal_signals) * 0.6
        return min(1.0, quality / (total * 0.8))

    def _calculate_prediction_accuracy(self, signals: PredictiveSignals, price_evolution: List[Dict]) -> float:
        if not signals.early_warnings and not signals.reversal_signals:
            return 0

        profits = [p.get('pf', 0) for p in price_evolution]
        reversal_index = None
        for i in range(1, len(profits)):
            if profits[i] < 0 and profits[i - 1] >= 0:
                reversal_index = i
                break

        if reversal_index is None:
            return 0

        all_signals = signals.early_warnings + signals.reversal_signals
        early_signals = sum(1 for s in all_signals if s.get('index', 0) < reversal_index)

        return early_signals / len(all_signals) if all_signals else 0

    # ============================================================
    # CONFLICT RESOLUTION
    # ============================================================

    def _resolve_pattern_conflicts(self, pattern_results: Dict, timeframe: str) -> Dict:
        bullish_patterns = []
        bearish_patterns = []
        neutral_patterns = []

        for name, data in pattern_results.items():
            if not data.get('detected', False):
                continue
            direction = data.get('direction', 'NEUTRAL')
            confidence = data.get('confidence', 0)

            if direction == 'BULLISH':
                bullish_patterns.append((name, confidence))
            elif direction == 'BEARISH':
                bearish_patterns.append((name, confidence))
            else:
                neutral_patterns.append((name, confidence))

        if bullish_patterns and bearish_patterns:
            bullish_avg = sum(c for _, c in bullish_patterns) / len(bullish_patterns) if bullish_patterns else 0
            bearish_avg = sum(c for _, c in bearish_patterns) / len(bearish_patterns) if bearish_patterns else 0

            if bullish_avg > bearish_avg * 1.3:
                filtered = {name: pattern_results[name] for name, _ in bullish_patterns}
            elif bearish_avg > bullish_avg * 1.3:
                filtered = {name: pattern_results[name] for name, _ in bearish_patterns}
            else:
                # Confidence is too close to call a clear winner - rather than
                # discarding every directional pattern, keep the single
                # strongest one from either side so genuinely detected
                # patterns aren't thrown away.
                best_name, _ = max(bullish_patterns + bearish_patterns, key=lambda x: x[1])
                filtered = {best_name: pattern_results[best_name]}

            for name, _ in neutral_patterns:
                filtered[name] = pattern_results[name]

            return filtered

        return pattern_results

    # ============================================================
    # OVERLAP RESOLUTION
    # ============================================================

    def _resolve_pattern_overlaps(self, pattern_results: Dict) -> Dict:
        groups = {}
        for name, data in pattern_results.items():
            if not data.get('detected', False):
                continue
            price_level = data.get('price_level', 0)
            if price_level == 0:
                continue
            pattern_type = name
            timeframe = data.get('timeframe', 'M1')

            key = f"{pattern_type}_{round(price_level, 5)}"
            if key not in groups:
                groups[key] = []
            groups[key].append((timeframe, name, data))

        filtered = {}
        tf_order = {'H1': 5, 'M30': 4, 'M15': 3, 'M5': 2, 'M1': 1}

        for key, patterns in groups.items():
            if len(patterns) == 1:
                filtered[patterns[0][1]] = patterns[0][2]
            else:
                best = max(patterns, key=lambda x: tf_order.get(x[0], 0))
                filtered[best[1]] = best[2]
                for p in patterns:
                    if p[0] != best[0]:
                        logger.debug(f"[PATTERN] Filtered out {p[0]} {p[1]} - same as {best[0]} {best[1]}")

        return filtered

    # ============================================================
    # PATTERN FILTERING
    # ============================================================

    def _filter_patterns(self, pattern_results: Dict, timeframe: str, prices: List[float]) -> Dict:
        filtered = {}

        current_price = prices[-1] if prices else 0
        proximity = PATTERN_PROXIMITY_PIPS.get(timeframe, 0.0080)

        for name, data in pattern_results.items():
            if not data.get('detected', False):
                continue

            price_level = data.get('price_level', 0)
            if price_level > 0:
                if abs(price_level - current_price) > proximity * 3:
                    continue

            status = data.get('status', 'HISTORICAL')
            if status == 'HISTORICAL':
                continue

            filtered[name] = data

        if len(filtered) > MAX_PATTERNS_PER_TIMEFRAME:
            sorted_patterns = sorted(
                filtered.items(),
                key=lambda x: x[1].get('confidence', 0),
                reverse=True
            )
            filtered = dict(sorted_patterns[:MAX_PATTERNS_PER_TIMEFRAME])

        return filtered

    # ============================================================
    # SETTER METHODS
    # ============================================================

    def set_session(self, session: str):
        self._current_session = session

    def set_regime(self, regime: str):
        self._current_regime = regime

    def set_timeframe(self, timeframe: str):
        self._current_timeframe = timeframe

    def set_current_price(self, price: float):
        self._current_price = price

    def set_atr_pips(self, atr_pips: float):
        """Bar ATR in pips: swings smaller than half of it are noise, not waves."""
        self._current_atr_pips = atr_pips


# ============================================================
# END OF FILE
# ============================================================