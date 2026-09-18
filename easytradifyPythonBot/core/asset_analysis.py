# ============================================================
# PROFESSIONAL HEDGE FUND TRADING SYSTEM - V30 (ENTRY CONFIDENCE FIX)
# ============================================================

import numpy as np
import MetaTrader5 as mt5
from typing import Dict, Any, Mapping, Optional, Tuple, List
from datetime import datetime
import logging
import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ✅ FIXED: logger = logging.getLogger(__name__) was missing after the
# module split below -- `import logging` was still present, but the
# actual logger instance was never re-added to this file, meaning
# every logger.warning/info/error/debug call anywhere in this file
# (dozens of call sites throughout the main orchestrator, including
# most of this session's own fixes) would raise NameError the moment
# any of them executed.
logger = logging.getLogger(__name__)

# ============================================================
# ✅ NEW: split out of this file into core/asset_analysis_gnn.py --
# GNN (Graph Neural Network) integration wrappers. get_gnn_instance()
# and _calculate_combined_signal() stay purely internal to that module
# (only called by other GNN functions, never directly from here), so
# only the 10 names actually used by the orchestrator are re-imported.
# ============================================================
from core.asset_analysis_gnn import (
    analyze_gnn_correlations,
    build_ohlc_with_gnn,
    calculate_gnn_final_score,
    get_gnn_ab_test,
    get_gnn_conflict,
    get_gnn_context,
    get_gnn_correlations_detailed,
    get_gnn_divergence,
    get_gnn_suggestions,
    is_gnn_available,
)

# ============================================================
# ✅ NEW: split out of this file (asset_analysis.py had grown past
# 7,400 lines) into core/asset_analysis_smc.py -- FVG/ICT/Wyckoff/SD
# component analyzers, Smart Money Concepts, and reversal/setup
# evaluators. Every name below is used by the orchestrator further
# down in this file; see that module's own docstring for why it's one
# combined file rather than split further (genuine multi-directional
# dependencies between the SMC and setup-evaluator pieces).
# ============================================================
from core.asset_analysis_smc import (
    SMC_ELITE_MIN_CONFLUENCE,
    SMC_MIN_CONFLUENCE_SCORE,
    SMC_TOTAL_POSSIBLE_SIGNALS,
    _analyze_ict_component,
    _analyze_supply_demand_component,
    _analyze_wyckoff_component,
    analyze_smc_structure,
    calculate_fvg_ifvg_final_score,
    calculate_smc_final_score,
    evaluate_bb_mean_reversion_setup,
    evaluate_ema_crossover_setup,
    evaluate_fvg_ifvg_setup,
    evaluate_smc_trade_setup,
    evaluate_stochastic_reversal_setup,
    evaluate_wave_c_reversal_setup,
    score_fvg_ifvg_indicator,
    score_liquidity_pools_volume_profile_confluence,
    score_ob_volume_profile_confluence,
    score_sd_volume_profile_confluence,
    score_sr_volume_profile_confluence,
    score_sweep_volume_profile_confluence,
    score_volume_profile_indicator,
    score_wave_c_fibonacci_indicator,
    score_wyckoff_volume_profile_confluence,
)
# ============================================================
# ✅ NEW: split out of this file into core/asset_analysis_indicators.py
# -- divergence-aware indicator scorers (RSI/Stochastic/MACD/Bollinger/
# volume/trend/supply-demand/candlestick) and the component analyzers
# that call them. All used directly by the orchestrator further down
# in this file.
# ============================================================
from core.asset_analysis_indicators import (
    _analyze_candlestick_component,
    _analyze_indicators_component,
    _analyze_support_resistance_component,
    _analyze_trend_component,
    _analyze_trend_component_with_divergence,
    score_bollinger_indicator,
    score_candlestick_indicator,
    score_macd_indicator,
    score_rsi_indicator_with_divergence,
    score_stochastic_indicator_with_divergence,
    score_supply_demand_indicator,
    score_trend_indicator,
    score_volume_indicator,
)
# ============================================================
# IMPORT FROM UNIFIED CONFIG - ALL CONSTANTS
# ============================================================
from core.asset_analysis_config import (
    MIN_ENTRY_CONFIDENCE,
    # ✅ FIXED: removed MIN_PROBABILITY_FOR_ENTRY import -- it was only
    # ever used for display (never actually enforced anywhere), and its
    # one use has been replaced with TRADE_PROBABILITY_MINIMUM (the
    # constant that's actually enforced) so the two can't silently
    # diverge -- see the fix note at that output line.
    TRADE_PROBABILITY_MINIMUM,
    # ✅ NEW: SMC elite-setup dedicated lot size / risk config
    SMC_SETUP_TRADE_SIZE_USD,
    SMC_SETUP_RISK_PER_TRADE,
    # ✅ NEW: BB mean-reversion setup config (shares the $ budget / risk %
    # above, but with its own entry/exit geometry constants)
    BB_MEAN_REVERSION_MAX_PIERCE_PCT_B,
    BB_MEAN_REVERSION_EXIT_APPROACH_PCT,
    BB_MEAN_REVERSION_SL_BUFFER_SPREAD_MULT,
    BB_MEAN_REVERSION_SL_MIN_BUFFER_PIPS,
    BB_MEAN_REVERSION_MIN_RR,
    # ✅ NEW: RSI / Stochastic reversal setup config
    STOCH_EXTREME_OVERBOUGHT,
    STOCH_EXTREME_OVERSOLD,
    STOCH_REVERSAL_SETUP_MIN_CONFIDENCE,
    STOCH_REVERSAL_FIB_DEEP,
    STOCH_REVERSAL_FIB_NORMAL,
    STOCH_REVERSAL_SL_BUFFER_SPREAD_MULT,
    STOCH_REVERSAL_SL_MIN_BUFFER_PIPS,
    STOCH_REVERSAL_MIN_RR,
    # ✅ NEW: EMA crossover setup config
    EMA_CROSSOVER_SL_BUFFER_SPREAD_MULT,
    EMA_CROSSOVER_SL_MIN_BUFFER_PIPS,
    EMA_CROSSOVER_MAX_SL_ATR_MULT,
    get_ema_min_separation_pips,
    # ✅ NEW: Volume Profile / POC config
    VOLUME_PROFILE_NUM_BINS,
    VOLUME_PROFILE_LOOKBACK_BARS,
    VOLUME_PROFILE_VALUE_AREA_PCT,
    VOLUME_PROFILE_MAX_SCORE,
    VOLUME_PROFILE_MIN_SCORE_AT_EDGE,
    VOLUME_PROFILE_MAX_CONFIDENCE,
    VOLUME_PROFILE_MIN_CONFIDENCE_AT_EDGE,
    VOLUME_PROFILE_INSIDE_VA_SCORE,
    VOLUME_PROFILE_INSIDE_VA_CONFIDENCE,
    VOLUME_PROFILE_REQUIRE_CONFLUENCE,
    # ✅ NEW: Wave C / A-B-C correction config
    WAVE_C_MIN_RETRACEMENT_B,
    WAVE_C_MAX_RETRACEMENT_B,
    WAVE_C_IDEAL_RETRACEMENT_MIN,
    WAVE_C_IDEAL_RETRACEMENT_MAX,
    WAVE_C_FIB_EQUALITY,
    WAVE_C_FIB_EXTENSION,
    WAVE_C_ENTRY_ZONE_PCT,
    WAVE_C_OVEREXTENSION_TOLERANCE,
    WAVE_C_SETUP_SL_BUFFER_SPREAD_MULT,
    WAVE_C_SETUP_SL_MIN_BUFFER_PIPS,
    WAVE_C_SETUP_MIN_RR,
    # ✅ NEW: multi-gap FVG + IFVG config
    FVG_ALL_MAX_GAPS,
    FVG_ALL_LOOKBACK_BARS,
    FVG_MITIGATION_FULL_THRESHOLD,
    FVG_IFVG_MIN_TIER_SCORE,
    FVG_IFVG_WEIGHT,
    FVG_IFVG_SETUP_SL_BUFFER_SPREAD_MULT,
    FVG_IFVG_SETUP_SL_MIN_BUFFER_PIPS,
    FVG_IFVG_SETUP_MIN_RR,
    # ✅ NEW: S/R <-> volume profile confluence config
    SR_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    SD_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    OB_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    SWEEP_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    LIQUIDITY_POOL_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    WYCKOFF_VOLUME_CONFLUENCE_TOLERANCE_PIPS,
    PATTERN_ANALYSIS_CURRENT_TF_ONLY,
    # ✅ NEW: these existed in config but were imported nowhere and used
    # nowhere in the whole codebase — get_ict_recommendation() gave every
    # FVG a flat base_score of 80 regardless of width/freshness/volume.
    FVG_WIDTH_SCORE_WEIGHT,
    FVG_FRESHNESS_SCORE_WEIGHT,
    FVG_VOLUME_SCORE_WEIGHT,
    STRONG_ENTRY_THRESHOLD,
    DECISION_WAIT_THRESHOLD,
    DECISION_MONITOR_THRESHOLD,
    # ✅ FIXED: removed DECISION_STRONG_ENTRY/DECISION_ENTRY_WITH_ZONE
    # imports -- confirmed zero references anywhere in this file.
    # STRONG_ENTRY_THRESHOLD (above) is the one actually used; these look
    # like legacy name variants left behind after a rename.
    # ✅ FIXED: removed STAR_5_THRESHOLD/STAR_4_THRESHOLD/STAR_3_THRESHOLD/
    # STAR_2_THRESHOLD imports -- confirmed zero references anywhere in
    # this file, not even for display. The real star rating comes from
    # entry_result (entry_engine.py's own star_ratings dict, derived
    # from actual signal quality -- see the fix note there). These look
    # like vestigial config from an earlier, superseded star-rating
    # design that was never wired up or cleaned up.
    # ✅ FIXED: removed MINIMUM_PROBABILITY_FOR_TRADE import -- confirmed
    # zero references anywhere in this file (imported but never used at
    # all, not even for display). TRADE_PROBABILITY_MINIMUM (imported
    # above) is the one constant that's actually enforced.
    FIBONACCI_TP1,
    FIBONACCI_TP1_MIN_PIPS,
    FIBONACCI_TP1_MAX_PIPS,
    TP1_FOLLOWS_RR_FLOOR,
    TP2_MIN_PIPS,
    TP2_MAX_PIPS,
    TP2_ATR_MULTIPLIER,
    MINIMUM_RISK_REWARD,
    MINIMUM_RISK_REWARD_M1,
    CANDLE_SCORE_SHOOTING_STAR,
    CANDLE_SCORE_HAMMER,
    CANDLE_SCORE_MARUBOZU_BULLISH,
    CANDLE_SCORE_MARUBOZU_BEARISH,
    CANDLE_SCORE_PIN_BAR_BULLISH,
    CANDLE_SCORE_PIN_BAR_BEARISH,
    CANDLE_SCORE_NORMAL_BULLISH,
    CANDLE_SCORE_NORMAL_BEARISH,
    CANDLE_SCORE_SPINNING_TOP,
    CANDLE_SCORE_DOJI,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_EXTREME_OVERBOUGHT,
    RSI_EXTREME_OVERSOLD,
    RSI_OVERBOUGHT_M1,
    RSI_OVERSOLD_M1,
    RSI_DIVERGENCE_VETO_THRESHOLD_M1,
    RSI_DIVERGENCE_VETO_THRESHOLD,
    STOCH_OVERBOUGHT,
    STOCH_OVERSOLD,
    MACD_BULLISH_THRESHOLD,
    MACD_BEARISH_THRESHOLD,
    # ✅ FIXED: removed the flat BB_SQUEEZE_THRESHOLD import -- all three
    # former usages (score_bollinger_indicator, _analyze_indicators_
    # component, and the debug output field) now correctly use the
    # instrument-aware get_bb_squeeze_threshold(symbol), the same one
    # calculate_real_probability() actually uses for real decisions.
    BREAKOUT_PERIOD,
    BREAKOUT_VOLUME_THRESHOLD,
    DEFAULT_RSI_VALUE,
    FVG_INVALIDATION_MULTIPLIER,
    VOLUME_SPIKE_THRESHOLD_M1,
    VOLUME_LOW_THRESHOLD_M1,
    WICK_REVERSAL_RATIO,
    get_wick_reversal_ratio,
    get_volume_threshold,
    get_bb_period,
    get_bb_std,
    EXTREME_VOLATILITY_VETO_THRESHOLD,
    RANGING_MARKET_ADX_THRESHOLD,
    VALID_ZONE_GRADES,
    PATTERN_TIMEFRAMES,
    PATTERN_CONFIDENCE_THRESHOLDS,
    get_pattern_proximity_pips,
    PATTERN_TIMEFRAME_WEIGHTS,
    PATTERN_WEIGHT,
    GNN_WEIGHT,
    GNN_CONFIDENCE_THRESHOLD,
    MIN_ABSOLUTE_RISK_REWARD,
    CANDLESTICK_USE_CLOSED_BAR,
    TP3_MAX_PIPS,
    TP3_ATR_CAP_MULTIPLIER,
    RISK_REWARD_NET_OF_SPREAD,
    EXPECTED_VALUE_FEEDS_PROBABILITY,
    EXPECTED_VALUE_IS_A_GATE,
    EXPECTED_VALUE_MIN_PIPS,
    HARD_DISAGREEMENT_PROBABILITY_PENALTY,
    REGIME_PROBABILITY_ADJUSTMENTS,
    REGIME_UNCONFIRMED_DAMPING,
    ATR_PERIOD,
    RSI_PERIOD,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
    STOCH_K,
    STOCH_D,
    BB_PERIOD,
    BB_STD,
    ADX_PERIOD,
    EMA_FAST,
    EMA_MEDIUM,
    EMA_SLOW,
    EMA_VERY_SLOW,
    MAX_SPREAD_PIPS,
    MAX_SPREAD_PIPS_M1,
    TYPICAL_SPREADS,
    ZONE_AT_ZONE_PIPS,
    ZONE_GRADE_SCORES,
    ZONE_PROXIMITY_PIPS_DEFAULT,
    ZONE_TOUCH_COUNT_THRESHOLD,
    ATR_TP_MULTIPLIERS,
    ATR_TP_MULTIPLIERS_M1,
    FVG_ENTRY_TOLERANCE_PIPS_BASE,
    _FVG_TOLERANCE_MULTIPLIERS,
    EMA_MIN_SEPARATION_PIPS,
    _EMA_SEPARATION_MULTIPLIERS,
    RESISTANCE_PROXIMITY_WARNING_PIPS_BASE,
    _RESISTANCE_PROXIMITY_MULTIPLIERS,
    VOLUME_IMBALANCE_THRESHOLDS_BASE,
    VOLUME_THRESHOLD_STRONG_TREND,
    VOLUME_THRESHOLD_MODERATE_TREND,
    VOLUME_THRESHOLD_WEAK_TREND,
    VOLUME_MULTIPLIER_EXTREME_LOW,
    VOLUME_MULTIPLIER_VERY_LOW,
    VOLUME_MULTIPLIER_LOW,
    VOLUME_MULTIPLIER_BELOW_AVG,
    VOLUME_MULTIPLIER_NORMAL,
    VOLUME_MULTIPLIER_ABOVE_AVG,
    VOLUME_MULTIPLIER_HIGH,
    VOLUME_RATIO_EXTREME_LOW,
    VOLUME_RATIO_VERY_LOW,
    VOLUME_RATIO_LOW,
    VOLUME_RATIO_BELOW_AVG,
    VOLUME_RATIO_NORMAL_MAX,
    VOLUME_RATIO_ABOVE_AVG,
    _BASE_PROBABILITY,
    _MIN_PROBABILITY,
    _MAX_PROBABILITY,
    _RSI_DIVERGENCE_MULTIPLIER,
    _MAX_RSI_DIVERGENCE_IMPACT,
    WICK_REVERSAL_RATIO_NORMAL,
    WICK_REVERSAL_RATIO_SMALL,
    WICK_SMALL_CANDLE_BODY_THRESHOLD,
    INSTRUMENT_VOLUME_MULTIPLIER_GOLD,
    INSTRUMENT_VOLUME_MULTIPLIER_SILVER,
    INSTRUMENT_VOLUME_MULTIPLIER_DEFAULT,
    ADX_THRESHOLDS,
    ADX_STRONG_TREND_THRESHOLD,
    _ATR_RANGE_MULTIPLIERS,
    _NORMAL_ATR_RANGES,
    USE_MID_PRICE_FOR_INDICATORS,
    # Stop must clear the market's noise, not just the cost of entry
    SL_MIN_ATR_MULTIPLE,
    # Stage 10: regret-minimising position sizing (off by default)
    USE_ONLINE_SIZING,
    # Defensive core: stage 9 (symbolic gate). Stages 7/8 removed --
    # they were the pipeline's only trained model and its calibrator.
    USE_SYMBOLIC_GATE,
    SYMBOLIC_GATE_SHADOW_MODE,
    WYCKOFF_MARKUP_STRONG_MIN_VOL,
    WYCKOFF_MARKUP_MIN_VOL,
    WYCKOFF_MARKDOWN_STRONG_MIN_VOL,
    WYCKOFF_MARKDOWN_MIN_VOL,
    WYCKOFF_SPIKE_THRESHOLDS,
    WYCKOFF_CONSOLIDATION_VOLUME_THRESHOLD,
    WYCKOFF_LOOKBACK_BARS,
    WYCKOFF_UPGRADE_ADX_THRESHOLD,
    MOMENTUM_THRESHOLDS,
    ZONE_RESET_AFTER_HOURS,
    ZONE_MAX_TOUCHES_FOR_GRADE,
    ZONE_PERSISTENCE_SECONDS,
    ZONE_GRADE_THRESHOLDS,
    ZONE_QUALITY_GRADE_THRESHOLDS,
    ZONE_TIME_DECAY_CONFIG,
    ZONE_LOOKBACK_BARS,
    ZONE_TOUCH_DISTANCE_PIPS,
    ADX_EXTREME_THRESHOLDS,
    DIVERGENCE_LOOKBACK,
    DEFAULT_DIVERGENCE_LOOKBACK,
    M15_FALLBACK_ENABLED,
    MIN_BARS_FOR_TREND,
    PIN_BAR_THRESHOLD,
    BB_SQUEEZE_THRESHOLD_BASE,
    _BB_SQUEEZE_MULTIPLIERS,
    VOLUME_BASELINE_BARS,
    SPREAD_COLLAPSE_ABSOLUTE_THRESHOLD_PIPS,
    SPREAD_COLLAPSE_PERCENTAGE_THRESHOLD,
    SPREAD_COLLAPSE_METALS_THRESHOLD,
    MIN_ACTIVITY_SECONDS,
    MICRO_STRUCTURE_PROBABILITY_THRESHOLD,
    MICRO_STRUCTURE_MAX_SPREAD_PIPS,
    MICRO_STRUCTURE_MOMENTUM_THRESHOLD,
    MICRO_STRUCTURE_ICEBERG_MIN_VOLUME,
    MICRO_STRUCTURE_ICEBERG_MAX_PRANGE_PIPS,
    MICRO_STRUCTURE_ICEBERG_MIN_TICKS,
    ZONE_GRADE_MULTIPLIERS,
    MAX_WORKERS,
    get_typical_spread,
    get_max_spread,
    get_bb_squeeze_threshold,
    get_resistance_proximity_pips,
    get_zone_proximity_pips,
    get_atr_tp_multipliers,
    get_minimum_risk_reward,
    get_instrument_adx_thresholds,
    get_instrument_volume_multiplier,
    get_volume_multiplier,
)

# ============================================================
# IMPORT FROM INDICATORS
# ============================================================
from core.indicators import (
    _detect_wyckoff_phase,
    _detect_trend_bias,
    _detect_supply_demand_zone,
    _get_zone_touch_distance,
    _detect_fvg,
    calculate_volume_profile,
    detect_abc_correction,
    detect_all_fvgs,
    get_h1_trend,
    detect_market_regime,
    classify_trading_regime,
    get_stochastic_divergence,
    _detect_rsi_divergence,
    get_volume_ratio,
    get_candle_progress_fixed,
    get_sr_recommendation,
    get_ict_recommendation,
    make_json_safe,
)

# ============================================================
# IMPORT FROM CALCULATIONS
# ============================================================
from core.calculations import (
    _calculate_rsi,
    _calculate_bollinger_bands,
    _calculate_macd,
    _calculate_stochastic,
    _calculate_ema,
    _calculate_adx,
    calculate_correct_atr,
    calculate_atr_long,
    get_pip_info,
    _get_fvg_tolerance_pips,
    calculate_ema_gap_pips, 
    calculate_lot_proper,
    apply_probability_multipliers_pair,
    calculate_real_probability,
    # ✅ _NORMAL_ATR_RANGES intentionally NOT re-imported here -- it is
    # already imported from asset_analysis_config above, and calculations
    # now re-exports that same object rather than defining its own. Two
    # imports of the same name meant the second silently shadowed the
    # first.
    get_static_atr_ranges,
    validate_rsi_value,
    extract_rates_arrays,
    calculate_pivot_levels,
    calculate_fvg_distance_pips,
    calculate_distance_to_resistance_pips,
    calculate_distance_to_support_pips,
    check_volatility_protection
)

# ============================================================
# IMPORT FROM ENTRY ENGINE
# ============================================================
from core.entry_engine import analyze_entry

# ============================================================
# IMPORT FROM VETO ENGINE
# ============================================================
from core.veto_engine import check_all_vetos, get_effective_veto_thresholds, get_veto_engine
from core.swing_points import find_swing_points, get_min_swing_size

# ============================================================
# IMPORT FROM PATTERNS
# ============================================================
from core.patterns import (
    PatternRecognizer
)

# ============================================================
# IMPORT ELITE ENHANCEMENT MODULES (session additions)
# ============================================================
from core.wave_lattice import build_wave_lattice
from core.strategy_groups import score_groups
from core.skipped_setups import record as record_skipped_setup
from core.decision_log import record as record_decision
from core.strategy_setups import pick as pick_strategy_setup
from core.asset_analysis_config import USE_STRATEGY_GROUP_PROBABILITY, STRATEGY_GROUP_MIN_PROBABILITY
from core.asset_analysis_config import USE_CALIBRATED_PROBABILITY, USE_MARKET_STOP, MAX_RISK_PER_TRADE
from core.asset_analysis_config import INVERT_ENTRY_DIRECTION, M1_ONLY
from core.asset_analysis_config import atr_relative_pips
from core.calibrated_model import score as calibrated_score, load_model as load_calibrated_model
from core.edge_features import live_compute as live_edge_features
from core.order_flow_forensics import build_order_flow_forensics, calculate_order_flow_final_score
from core.gap_slippage_detector import build_gap_slippage_report, calculate_gap_slippage_final_score
from core.expected_value import score_expected_value
from core.risk_reward import rr_from_pips

# ============================================================
# NEW: MULTI-DEGREE TREND CASCADE + EXHAUSTION/CLIMAX FILTER
# ============================================================
from core.trend_cascade import (get_trend_cascade, calculate_trend_cascade_final_score,
                                cascade_direction_override)
from core.exhaustion_filter import (
    detect_exhaustion_climax,
    calculate_exhaustion_final_score,
    calculate_exhaustion_exit_signal,
)
from core.round_number_levels import analyze_round_number_levels
from core.adr_exhaustion import get_adr_exhaustion, calculate_adr_exhaustion_final_score
from core.fib_confluence import check_fib_confluence
from core.displacement_confirmation import check_displacement_confirmation
from core.retest_confirmation import check_retest_confirmation
# Defensive core (pipeline stages 9, 7, 8) + the shared flattener that
# keeps the meta-label model's training and serving inputs identical.
from core.decision_features import flatten_decision
from core.symbolic_gate import evaluate_symbolic_gate
from core.rvam import calculate_rvam, score_rvam_confirmation, calculate_rvam_final_score
from core.vwap import calculate_vwap, score_vwap_context
from core.ttm_squeeze import detect_ttm_squeeze, score_squeeze_setup
from core.liquidity_events import (detect_liquidity_events, summarize_liquidity,
                                   calculate_liquidity_final_score)


# ============================================================
# PATTERN ANALYSIS FUNCTIONS
# ============================================================

def analyze_patterns_multi_timeframe(
    symbol: str,
    rates_data: Dict[str, np.ndarray],
    current_price: float,
    pip_size: float,
    pattern_recognizer: PatternRecognizer = None,
    elliott_waves_by_tf: Dict[str, List[Dict]] = None,
    volume_ratio: float = 1.0,
    adx: float = 0.0,
    spread_pips: float = 0.0,
    trend: str = "NEUTRAL",
    range_high: float = None,
    range_low: float = None,
    rsi: float = None
) -> Dict[str, Any]:
    """Analyze patterns across multiple timeframes.

    rsi: current RSI(14) on the same timeframe being analyzed, used to
    score whether each detected pattern's direction is actually
    confirmed by momentum (e.g. a bullish reversal pattern forming
    while RSI is still overbought is weaker than one forming oversold).
    Without this, pattern confidence scoring previously had two dead
    weight categories (rsi_aligned/trend_aligned) that were never
    populated by any detector, silently capping how much scores could
    vary and making the same pattern look equally "confident" in good
    and bad setups.
    """
    if pattern_recognizer is None:
        pattern_recognizer = PatternRecognizer()
    
    result = {
        "timeframes": {},
        "summary": {
            "total_patterns": 0,
            "strongest_pattern": None,
            "strongest_timeframe": None,
            "highest_confidence": 0,
            "strongest_relevance": 0,
            "strongest_distance_pips": None,
            "overall_direction": "NEUTRAL"
        },
        "elliott_waves": []
    }
    
    timeframe_patterns = {}
    all_patterns = []
    
    # ✅ FIXED: was hardcoded `for tf in PATTERN_TIMEFRAMES`, which always
    # tried to process all 5 canonical timeframes regardless of what
    # rates_data actually contained. When the caller only fetched the
    # current timeframe (PATTERN_ANALYSIS_CURRENT_TF_ONLY), this now
    # correctly processes just that one.
    #
    # ✅ REMOVED: multi-timeframe pattern confirmation entirely (was
    # already effectively dead - see below). Patterns and Elliott Waves
    # are scoped to the current timeframe only by design, so there is
    # never a second timeframe's data available here to confirm a
    # pattern against.
    tfs_to_process = [t for t in PATTERN_TIMEFRAMES if t in rates_data]
    
    for tf in tfs_to_process:
        if rates_data[tf] is not None and len(rates_data[tf]) > 0:
            rates = rates_data[tf]
            
            price_evolution = []
            for i, bar in enumerate(rates):
                vol = float(bar[5]) if len(bar) > 5 else 1.0
                price_evolution.append({
                    'p': float(bar[4]),
                    'h': float(bar[2]),
                    'l': float(bar[3]),
                    'o': float(bar[1]),
                    't': datetime.fromtimestamp(bar[0]).isoformat(),
                    'vo': {'rt': vol},
                    'd': 0,
                    'c': 50,
                    'pf': 0
                })
            
            pattern_analysis = pattern_recognizer.analyze_patterns(
                price_evolution=price_evolution,
                timeframe=tf,
                pip_size=pip_size,
                external_trend=trend,
                external_adx=adx,
                external_rsi=rsi
            )
            
            confidence_threshold = PATTERN_CONFIDENCE_THRESHOLDS.get(tf, 0.5)
            # Proximity threshold for this timeframe, in pips, used below to
            # discount a pattern's relevance the farther its price_level
            # sits from where price actually is right now. Detection-time
            # proximity gates only block patterns that are wildly off; a
            # pattern sitting right at the edge of that gate is still a lot
            # less actionable than one sitting on top of current price, and
            # raw confidence alone doesn't capture that.
            proximity_pips_tf = get_pattern_proximity_pips(tf) / pip_size if pip_size else 0

            scored_patterns = {}
            for pattern_name, pattern_data in pattern_analysis.patterns.items():
                confidence = pattern_data.get('confidence', 0)
                direction = pattern_data.get('direction', 'NEUTRAL')
                
                if confidence >= confidence_threshold:
                    price_level = pattern_data.get('price_level')
                    if price_level is not None and current_price and pip_size:
                        distance_pips = abs(current_price - price_level) / pip_size
                    else:
                        distance_pips = None

                    # ✅ FIXED: strongest_pattern used to be selected by
                    # max(confidence) alone, with no penalty for how far a
                    # pattern's price_level actually was from current price.
                    # RECTANGLE detections in particular tend to cluster in a
                    # narrow confidence band, so ties (or near-ties) were
                    # broken arbitrarily by dict/list order rather than by
                    # which pattern is actually closer to being tradable
                    # right now. relevance decays confidence as distance
                    # grows relative to this timeframe's own proximity
                    # threshold -- a pattern right at the proximity boundary
                    # is worth about half its raw confidence, one at 2x the
                    # boundary about a third, etc.
                    if distance_pips is not None and proximity_pips_tf:
                        relevance = confidence / (1 + (distance_pips / proximity_pips_tf))
                    else:
                        relevance = confidence

                    scored_patterns[pattern_name] = {
                        'detected': True,
                        'confidence': confidence,
                        'direction': direction,
                        'description': pattern_data.get('description', ''),
                        'price_level': price_level,
                        'distance_pips': round(distance_pips, 1) if distance_pips is not None else None,
                        'relevance': round(relevance, 4),
                        'score': confidence * 100,
                        'recommendation': _get_pattern_recommendation(direction, confidence)
                    }
                    all_patterns.append({
                        'timeframe': tf,
                        'name': pattern_name,
                        'data': scored_patterns[pattern_name]
                    })
            
            elliott_waves = []
            for wave in pattern_analysis.elliott_waves:
                if wave.detected:
                    elliott_waves.append({
                        'type': wave.wave_type.value if hasattr(wave.wave_type, 'value') else str(wave.wave_type),
                        'confidence': wave.confidence,
                        'current_wave': wave.current_wave,
                        'next_wave': wave.next_wave,
                        'description': wave.description,
                        'recommendation': wave.recommendation if hasattr(wave, 'recommendation') else "NEUTRAL",
                        'action': wave.action if hasattr(wave, 'action') else "WAIT",
                        'direction': wave.direction if hasattr(wave, 'direction') else "NEUTRAL",
                        'confidence_score': wave.confidence_score if hasattr(wave, 'confidence_score') else 0,
                        'reason': wave.reason if hasattr(wave, 'reason') else "",
                        # ✅ FIXED: these existed on the ElliottWave object (as of
                        # the patterns.py fix that stopped discarding them) but
                        # were never copied into this dict — every consumer of
                        # this dict got a text-only recommendation with no
                        # numeric entry/target to actually act on.
                        'entry_price': wave.entry_price if hasattr(wave, 'entry_price') else None,
                        'target_price': wave.target_price if hasattr(wave, 'target_price') else None,
                        'fib_levels': wave.fib_levels if hasattr(wave, 'fib_levels') else {},
                        'entry_timing': wave.entry_timing if hasattr(wave, 'entry_timing') else 'WAIT',
                        'entry_condition': wave.entry_condition if hasattr(wave, 'entry_condition') else '',
                    })
            
            result['elliott_waves'].extend(elliott_waves)

            # ✅ FIXED: this text summary used to rank "Strongest" by raw
            # confidence while the overall strongest_pattern below ranks by
            # relevance (confidence discounted by distance from current
            # price) -- the two could name different patterns for the same
            # timeframe, which reads as an inconsistency in the output even
            # though both numbers were individually "correct".
            if scored_patterns:
                strongest_name, strongest_data = max(scored_patterns.items(), key=lambda x: x[1]['relevance'])
                tf_summary = (
                    f"Detected {len(scored_patterns)} patterns. "
                    f"Strongest: {strongest_name} ({strongest_data['confidence'] * 100:.0f}% confidence"
                )
                if strongest_data['distance_pips'] is not None:
                    tf_summary += f", {strongest_data['distance_pips']:.1f} pips away"
                tf_summary += ")"
            else:
                tf_summary = "No significant patterns detected"

            timeframe_patterns[tf] = {
                'patterns': scored_patterns,
                'pattern_count': len(scored_patterns),
                'elliott_waves': elliott_waves,
                'summary': tf_summary,
                'confidence_threshold': confidence_threshold
            }
    
    result['timeframes'] = timeframe_patterns

    # ✅ REMOVED: multi-timeframe pattern confirmation. With
    # tfs_to_process always containing exactly one timeframe now,
    # `other_tf != tf` in the confirmation loop that used to live here
    # always filtered out every candidate, so `confirming_tfs` was
    # always `[]` and `multi_timeframe_confirmed` was always `False` -
    # dead code computing a value that could never be anything else.

    # ✅ ADDED: `summary` describes chart patterns only, but Elliott waves
    # now feed calculate_pattern_final_score() alongside them. The two
    # therefore disagree in the payload -- live: summary.total_patterns 0
    # and strongest_pattern null, while final_score.patterns_detected was 1
    # and pattern_contribution -15.8, driven by an impulse wave the summary
    # never mentions. Counted separately rather than merged into
    # total_patterns, because an Elliott wave has no price_level, distance
    # or relevance and cannot be ranked by the strongest_pattern logic
    # below without inventing values for it.
    _elliott_actionable = [
        w
        for tf_data in result['timeframes'].values()
        for w in (tf_data.get('elliott_waves') or [])
        if isinstance(w, dict)
        and str(w.get('recommendation', '')).strip().upper() in ('BUY', 'SELL')
        and (w.get('confidence') or 0) > 0
    ]
    result['summary']['elliott_waves_scored'] = len(_elliott_actionable)
    result['summary']['scored_inputs_total'] = len(all_patterns) + len(_elliott_actionable)

    if all_patterns:
        strongest = max(all_patterns, key=lambda x: x['data']['relevance'])
        result['summary']['strongest_pattern'] = strongest['name']
        result['summary']['strongest_timeframe'] = strongest['timeframe']
        result['summary']['highest_confidence'] = strongest['data']['confidence']
        result['summary']['strongest_relevance'] = strongest['data']['relevance']
        result['summary']['strongest_distance_pips'] = strongest['data']['distance_pips']
        result['summary']['total_patterns'] = len(all_patterns)
        
        bullish_count = sum(1 for p in all_patterns if p['data']['direction'] == 'BULLISH' and p['data']['confidence'] > 0.5)
        bearish_count = sum(1 for p in all_patterns if p['data']['direction'] == 'BEARISH' and p['data']['confidence'] > 0.5)
        
        if bullish_count > bearish_count * 1.5:
            result['summary']['overall_direction'] = 'BULLISH'
        elif bearish_count > bullish_count * 1.5:
            result['summary']['overall_direction'] = 'BEARISH'
        else:
            result['summary']['overall_direction'] = 'NEUTRAL'
    
    return result


def _get_pattern_recommendation(direction: str, confidence: float) -> str:
    """Get recommendation based on pattern direction and confidence."""
    if confidence < 0.4:
        return "NEUTRAL"
    
    if direction == "BULLISH":
        if confidence >= 0.7:
            return "STRONG_BUY"
        elif confidence >= 0.5:
            return "BUY"
        else:
            return "NEUTRAL"
    elif direction == "BEARISH":
        if confidence >= 0.7:
            return "STRONG_SELL"
        elif confidence >= 0.5:
            return "SELL"
        else:
            return "NEUTRAL"
    else:
        return "NEUTRAL"


def calculate_pattern_final_score(pattern_result: Dict[str, Any], base_probability: float, best_direction: str = "BUY") -> Dict[str, Any]:
    """
    Calculate pattern contribution to final trade score.

    `best_direction` ("BUY" or "SELL") is required to sign the contribution
    correctly, for the same reason it is required in
    calculate_gnn_final_score() and calculate_smc_final_score():
    base_probability is the probability the CHOSEN direction is correct, not
    an absolute bullish/bearish market read. A BULLISH pattern read supports
    a BUY and opposes a SELL; without best_direction this function raised the
    probability of a SELL on bullish evidence. See the measurement in the
    contribution block below.

    Defaults to "BUY" to match the signatures of the sibling scorers, so an
    existing caller that does not pass it keeps the previous behaviour on
    long trades rather than failing.
    """
    if not pattern_result.get('timeframes'):
        return {
            "pattern_recommendation": "NEUTRAL",
            "pattern_score": 0,
            "pattern_contribution": 0,
            "final_score": base_probability,
            "pattern_weight_used": 0,
            "aligned": True
        }
    
    total_score = 0
    total_weight = 0
    patterns_detected = 0
    directions = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0}
    # ✅ FIXED (see below): tracks the same weight*confidence mass used for
    # normalized_score, per direction, so the direction/confidence decision
    # uses the identical weighting as the magnitude it's paired with,
    # instead of a separate unweighted headcount.
    weighted_directions = {"BULLISH": 0.0, "BEARISH": 0.0, "NEUTRAL": 0.0}
    
    for tf, tf_data in pattern_result['timeframes'].items():
        weight = PATTERN_TIMEFRAME_WEIGHTS.get(tf, 0.15)

        # ✅ FIXED: this loop only ever read tf_data['patterns']. Elliott
        # waves live in the SIBLING key tf_data['elliott_waves'] and were
        # therefore computed, published in the payload, surfaced in
        # wave_lattice, consulted by decision_snapshot's bull/bear case --
        # and contributed exactly nothing to probability. Live example: a
        # Wave C read at confidence 0.60 sat in the payload while
        # pattern_final_score reported patterns_detected 0 and
        # contribution 0, because tf_data['patterns'] happened to be empty.
        #
        # Folded in on the same footing as chart patterns, with the same
        # relevance-vs-confidence discipline: an Elliott wave has no
        # price_level/distance, so it has no distance discount to apply --
        # its `confidence` IS its effective weight. `direction` here is the
        # recommended TRADE direction (already flipped for Wave C
        # completion by _get_elliott_wave_recommendation), which is the
        # same thing chart patterns' `direction` means, so they compose.
        for wave in (tf_data.get('elliott_waves') or []):
            if not isinstance(wave, dict):
                continue
            wave_conf = wave.get('confidence', 0) or 0

            # ✅ FIXED (regression introduced when Elliott was first wired
            # in here): this gated on wave['direction'], which is NOT an
            # actionable call. _get_elliott_wave_recommendation() also
            # emits "WATCH" with entry_timing "WAIT" -- a diagonal that
            # is merely *anticipating* a reversal, explicitly not a trade
            # yet -- and those still carry a `direction`. Caught live on
            # the first payload after deploy: an ending diagonal at
            # confidence 0.55 with recommendation WATCH / action WATCH /
            # entry_timing WAIT was scored as a full BULLISH pattern worth
            # +13.7 probability, flipping pattern_recommendation to
            # BULLISH on a bar whose trend, cascade (-1.00 unanimous),
            # wyckoff, candlestick and stochastic were all bearish.
            #
            # Gate on `recommendation` instead -- the principle the rest of
            # the pipeline applies to every other scorer:
            # direction fields describe a read, recommendations are what
            # the component is willing to act on.
            wave_rec = str(wave.get('recommendation', '')).strip().upper()
            if wave_conf <= 0 or wave_rec not in ('BUY', 'SELL'):
                continue
            wave_dir = 'BULLISH' if wave_rec == 'BUY' else 'BEARISH'
            wave_score = wave_conf * 100 if wave_dir == 'BULLISH' else -wave_conf * 100
            total_score += wave_score * weight * wave_conf
            total_weight += weight * wave_conf
            patterns_detected += 1
            directions[wave_dir] += 1
            weighted_directions[wave_dir] += weight * wave_conf
        
        for pattern_name, pattern_data in tf_data.get('patterns', {}).items():
            # abc_correction is the same A-B-C structure the Elliott wave
            # above already scores; counting both voted it twice (2026-09-15).
            if pattern_name == 'abc_correction' and tf_data.get('elliott_waves'):
                continue
            if pattern_data.get('detected', False):
                confidence = pattern_data.get('confidence', 0)
                direction = pattern_data.get('direction', 'NEUTRAL')

                # ✅ FIXED: this used raw `confidence` and ignored
                # `relevance`, which analyze_patterns_multi_timeframe()
                # already computes right above as
                #     relevance = confidence / (1 + distance_pips / proximity_pips_tf)
                # specifically to discount a pattern the farther its
                # price_level sits from where price actually is. That
                # discount was computed, stored in the payload, reported in
                # summary.strongest_relevance -- and then thrown away here,
                # the one place it could affect a trade. Live example
                # (XAGUSD M1): wedge_falling, confidence 0.48, relevance
                # 0.08 at 20.0 pips away -- a pattern its own math says is
                # ~92% discounted contributed the FULL 0.48 and pushed
                # probability +12.72.
                #
                # relevance <= confidence always (distance >= 0), so this
                # can only ever shrink a far pattern's influence, never
                # inflate a near one: a pattern sitting exactly at price
                # has relevance == confidence and is unaffected.
                #
                # Falls back to confidence if relevance is missing, so any
                # other producer of this dict shape keeps working.
                relevance = pattern_data.get('relevance')
                if relevance is None:
                    relevance = confidence
                effective = min(confidence, max(0.0, float(relevance)))

                if direction == "BULLISH":
                    score = effective * 100
                elif direction == "BEARISH":
                    score = -effective * 100
                else:
                    score = 0

                # `effective` now drives the weighting mass as well as the
                # score, so a distant pattern is quiet in BOTH the
                # magnitude and the direction gate below, rather than being
                # discounted in one and full-strength in the other.
                weighted_score = score * weight * effective
                total_score += weighted_score
                total_weight += weight * effective
                patterns_detected += 1

                if direction in directions:
                    directions[direction] += 1
                if direction in weighted_directions:
                    weighted_directions[direction] += weight * effective
    
    if total_weight > 0:
        normalized_score = total_score / total_weight
    else:
        normalized_score = 0
    
    if patterns_detected == 0:
        recommendation = "NEUTRAL"
        confidence_score = 0
    else:
        # ✅ FIXED: was `directions["BULLISH"] / patterns_detected` and
        # `directions["BEARISH"] / patterns_detected` -- a raw pattern
        # headcount where a single M1 pattern and a single H1 pattern
        # counted as equal votes, disagreeing with normalized_score (which
        # correctly weights H1 ~4.6x M1 via PATTERN_TIMEFRAME_WEIGHTS). A
        # 55%-of-patterns-by-count bearish read could come entirely from
        # low-weight M1/M5 noise while the one H1 pattern present was
        # bullish -- the direction call ignored that distinction entirely.
        # Now both the direction gate and normalized_score are driven by
        # the same weighted mass, so they can't disagree with each other.
        if total_weight > 0:
            bullish_ratio = weighted_directions["BULLISH"] / total_weight
            bearish_ratio = weighted_directions["BEARISH"] / total_weight
        else:
            bullish_ratio = 0.0
            bearish_ratio = 0.0
        
        if bullish_ratio > 0.6:
            recommendation = "BULLISH"
            confidence_score = min(100, normalized_score * 0.7 + 30)
        elif bearish_ratio > 0.6:
            recommendation = "BEARISH"
            confidence_score = min(100, abs(normalized_score) * 0.7 + 30)
        else:
            recommendation = "NEUTRAL"
            confidence_score = 50
    
    # ✅ FIXED: the sign of the contribution was taken from the market read
    # alone -- `+X if BULLISH else -X if BEARISH` -- with no knowledge of
    # which direction was actually being traded. base_probability is the
    # probability the CHOSEN direction is correct, not an absolute bullish
    # market read, so on a SELL trade a BULLISH pattern is evidence AGAINST
    # the trade and was raising its probability. This is the identical bug
    # already found and fixed in calculate_gnn_final_score() and
    # calculate_smc_final_score(), whose docstrings state the same reasoning;
    # `pattern` was the only one of the eight chained scorers still not
    # receiving best_direction.
    #
    # Measured on 215 real MT5 trades, splitting by the ledger delta's sign:
    #
    #   BUY  trades  pattern agrees +0.1831R vs opposes -0.2232R  edge +0.4063R
    #   SELL trades  pattern agrees +0.0924R vs opposes -0.3373R  edge +0.4296R
    #   as shipped (BUY and SELL pooled, signs cancelling)         edge +0.0260R (p=0.89)
    #
    # The two directions carry nearly the same edge with opposite raw signs,
    # which is the signature of a sign error rather than a fitted rule -- and
    # pooling them cancelled the component to noise, which is why `pattern`
    # measured as uninformative despite firing on 80.5% of trades. 56 of 215
    # trades (26%) received a mean 12.29 probability points in the wrong
    # direction; those trades returned -0.2700R.
    #
    # Validated: chronological split train +0.4333R -> test +0.3281R (the
    # as-shipped signal reverses over the same split, +0.1294R -> -0.2575R),
    # present separately in BOTH directions, and a 1000-shuffle permutation of
    # the BUY/SELL labels puts the real edge past the 95th percentile of the
    # null (p=0.0120). The correction has no free parameter -- it is the
    # recommendation reinterpreted against best_direction -- so there is no
    # threshold here that could have been tuned to the sample.
    #
    # NOT copied from GNN/SMC: those additionally damp an OPPOSING read to
    # x0.2 weight. That asymmetry is untested here and is deliberately left
    # out rather than bundled in with a validated change.
    agree_label = "BULLISH" if str(best_direction).upper() == "BUY" else "BEARISH"
    oppose_label = "BEARISH" if str(best_direction).upper() == "BUY" else "BULLISH"

    aligned = True
    if recommendation == agree_label:
        pattern_contribution = (confidence_score / 100) * PATTERN_WEIGHT * 100
    elif recommendation == oppose_label:
        aligned = False
        pattern_contribution = -(confidence_score / 100) * PATTERN_WEIGHT * 100
    else:
        pattern_contribution = 0

    max_contribution = PATTERN_WEIGHT * 100
    pattern_contribution = max(-max_contribution, min(max_contribution, pattern_contribution))

    final_score = base_probability + pattern_contribution
    final_score = max(5.0, min(95.0, final_score))

    return {
        "pattern_recommendation": recommendation,
        "pattern_score": round(confidence_score, 1),
        "pattern_contribution": round(pattern_contribution, 2),
        "final_score": round(final_score, 2),
        "pattern_weight_used": round(PATTERN_WEIGHT * 100, 1),
        "patterns_detected": patterns_detected,
        "directions": directions,
        # Read by _final_score_note() -- the ledger now records "aligned" or
        # "OPPOSED to trade direction" on every pattern step, so a future
        # reader can tell which way the read pointed relative to the trade.
        "aligned": aligned,
    }


# ============================================================
# HYBRID TAKE PROFIT CALCULATION
# ============================================================

NO_LEVEL_PIPS = 999.0


def _broker_hour(rates: Any) -> Optional[int]:
    """Hour of the last bar on the BROKER's clock (UTC+3), or None.

    Taken from the bar stamps rather than the machine clock: MT5 timestamps are
    already broker time, so this needs no conversion and cannot drift with the
    local timezone or DST.
    """
    try:
        if rates is None or len(rates) == 0:
            return None
        return int((int(rates[-1]["time"]) % 86400) // 3600)
    except Exception:
        return None


def _picked_strategy(groups_result: Any, behaviour: Any = None) -> Dict[str, Any]:
    """The strategy the final decision actually came from, named.

    The auction in core/strategy_groups.py scores each strategy alone and the
    winner sets the probability everything downstream is built on, but its
    name lived only inside the groups block. A reader of the final decision
    saw the verdict and not the argument behind it.
    """
    if not isinstance(groups_result, Mapping) or not groups_result.get("enabled"):
        return {"available": False, "reason": "strategy groups disabled"}
    winner = groups_result.get("winner")
    if not winner:
        return {"available": False, "reason": groups_result.get("error") or "no group scored"}
    group = (groups_result.get("groups") or {}).get(winner) or {}
    members = group.get("members") or []
    picked = {
        "available": True,
        "name": winner,
        "title": group.get("title", winner),
        "score": groups_result.get("best_score"),
        "final_probability": groups_result.get("final_probability"),
        "why": groups_result.get("reason"),
        "agreeing": [m.get("name") for m in members if m.get("vote") == "WITH"],
        "opposing": [m.get("name") for m in members if m.get("vote") == "AGAINST"],
        # only one group scoring is the common case, not an anomaly -- indexing
        # [1] blindly raised and took the whole analysis down with it
        "runner_up": next(iter((groups_result.get("ranked") or [])[1:2]), None),
        "most_opposed": groups_result.get("most_opposed"),
    }
    # A reversion pick is earned by the fitted process, so the numbers that
    # admitted it travel with it -- a reader can check the trade against its
    # own thesis without re-deriving anything.
    if winner == "MEAN_REVERSION" and isinstance(behaviour, Mapping):
        picked["reversion_state"] = {
            "z": behaviour.get("z"),
            "half_life_bars": behaviour.get("half_life_bars"),
            "forward_beta": behaviour.get("forward_beta"),
            "forward_t": behaviour.get("forward_t"),
            "price_share": behaviour.get("price_share"),
            "expected_gain_sigma": behaviour.get("expected_gain_sigma"),
            "cost_sigma": behaviour.get("cost_sigma"),
            "net_edge_sigma": behaviour.get("net_edge_sigma"),
            "time_stop_bars": behaviour.get("time_stop_bars"),
            "size_multiple": behaviour.get("size_multiple"),
        }
    return picked


def _far_if_absent(value: Any) -> float:
    """A missing S/R level is scored as far away, but published as None
    (a sentinel in the payload reads as a real 999-pip measurement)."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else NO_LEVEL_PIPS


def side_probability(direction: str, probability_buy: Optional[float], probability_sell: Optional[float],
                     fallback: Optional[float] = None) -> Optional[float]:
    """The probability that belongs to `direction`.

    A trade must be judged on its own side's score: when the trend cascade
    flips the side, the rejected side's confidence describes a trade that is
    not being taken.
    """
    value = probability_buy if str(direction).upper() == "BUY" else probability_sell
    return fallback if value is None else value


def calculate_hybrid_take_profit(
    symbol: str,
    current_price: float,
    order_type: str,
    pip_size: float,
    atr_pips: float,
    spread_pips: float,
    sl_pips: float,
    zone_level: Optional[float] = None,
    zone_grade: str = "E",
    recent_swing_high: Optional[float] = None,
    recent_swing_low: Optional[float] = None,
    timeframe: str = "M1"
) -> Tuple[float, float, float]:
    """HYBRID TAKE PROFIT: Fibonacci 61.8% + Zone + ATR"""
    
    tp1_pips = FIBONACCI_TP1_MIN_PIPS
    
    if recent_swing_high and recent_swing_low and pip_size > 0:
        swing_range_pips = abs(recent_swing_high - recent_swing_low) / pip_size
        if swing_range_pips > 0:
            fib_tp = swing_range_pips * FIBONACCI_TP1
            tp1_pips = max(FIBONACCI_TP1_MIN_PIPS, min(FIBONACCI_TP1_MAX_PIPS, fib_tp))
    
    min_profitable = spread_pips * 2 + 1
    tp1_pips = max(tp1_pips, min_profitable)
    
    tp2_pips = TP2_MIN_PIPS
    
    zone_tp_pips = None
    if zone_level and pip_size > 0 and zone_grade in ["A", "B"]:
        if order_type == "BUY":
            zone_distance = abs(zone_level - current_price) / pip_size
        else:
            zone_distance = abs(current_price - zone_level) / pip_size
        if zone_distance > 0 and zone_distance <= 50:
            zone_tp_pips = zone_distance
    
    atr_tp_pips = atr_pips * TP2_ATR_MULTIPLIER
    
    candidates = []
    if zone_tp_pips:
        candidates.append(zone_tp_pips)
    candidates.append(atr_tp_pips)
    
    if candidates:
        tp2_pips = min(candidates)
    else:
        tp2_pips = atr_tp_pips
    
    tp2_pips = max(TP2_MIN_PIPS, min(TP2_MAX_PIPS, tp2_pips))
    tp2_pips = max(tp2_pips, tp1_pips + spread_pips + 1)
    
    tp3_pips = atr_pips * 2.0
    if zone_tp_pips and zone_tp_pips > tp2_pips:
        tp3_pips = zone_tp_pips
    else:
        tp3_pips = max(tp3_pips, tp2_pips + 5)
    # ✅ FIXED (Phase 2, defect D-11): was
    #     tp3_pips = min(tp3_pips, 50)
    # A hardcoded 50-pip ceiling applied AFTER the `tp2_pips + 5` floor,
    # inside a function that otherwise scales everything off ATR. On any
    # instrument whose targets exceed 50 pips it silently produced a TP3
    # NEARER than TP1 and TP2.
    #
    # Live proof, XAGUSD 2026-09-01 (ATR 64.8p, spread 40p):
    #     TP1 = 81p, TP2 = 122p, TP3 = min(max(129.6, 127), 50) = 50p
    # TP3 sat 31 pips closer than TP1. Anything sizing or scaling out on
    # a third target was working from a number that was not a third
    # target at all.
    #
    # The cap is now ATR-relative, and -- more importantly -- ordering is
    # enforced LAST, so no future cap can invert the ladder again. That
    # ordering guarantee is the actual fix; the cap value is secondary.
    tp3_cap = max(TP3_MAX_PIPS, atr_pips * TP3_ATR_CAP_MULTIPLIER)
    tp3_pips = min(tp3_pips, tp3_cap)

    # ✅ FIXED: `sl_pips` was a parameter this function ACCEPTED, that
    # every caller PASSED, and that the body never read once. The
    # function it superseded, calculations.calculate_atr_based_tp(),
    # enforces `min_tp1 = sl_pips * get_minimum_risk_reward(timeframe)`;
    # the hybrid rewrite dropped that line and nothing replaced it. So
    # the target was computed with no reference whatsoever to the stop
    # it is measured against, and the R:R the whole pipeline then gates
    # on (MIN_ABSOLUTE_RISK_REWARD = 2.0) was simply whatever fell out
    # of two independently-derived numbers.
    #
    # It went unnoticed because the two happened to land near 1.5 while
    # stops were ~33 pips. Correcting the stop distance to clear the
    # spread moved it to 72 pips, the target stayed put, and R:R
    # inverted to 0.68 -- risking 72 pips to make 49 -- on 1856 of 1856
    # replayed decisions, none of which could then clear the 2.0 floor.
    #
    # Applied HERE, after the caps, for the reason D-11 above documents:
    # a floor placed before a cap is a floor the cap can silently
    # revoke. On XAGUSD that is not hypothetical -- FIBONACCI_TP1_MAX_PIPS
    # (15) is a forex-scale ceiling well below this instrument's spread,
    # so TP1 was pinned to `2*spread + 1` and the Fibonacci branch never
    # bound at all.
    min_rr = get_minimum_risk_reward(timeframe)
    if TP1_FOLLOWS_RR_FLOOR and sl_pips and sl_pips > 0 and min_rr > 0:
        # TP1 IS the floor (operator, 2026-09-17): min_rr x stop net of the
        # spread, never inside the spread itself. The Fibonacci/8-pip target
        # above no longer lifts it.
        tp1_pips = max(sl_pips * min_rr + max(0.0, spread_pips or 0.0), min_profitable)
    elif sl_pips and sl_pips > 0 and min_rr > 0:
        # ✅ FIXED: this was `sl_pips * min_rr`, which sets the target to
        # exactly the GROSS floor -- and the gate that judges it tests
        # NET of spread (RISK_REWARD_NET_OF_SPREAD). Net is always below
        # gross, so a target placed exactly on the gross floor is
        # guaranteed to miss the net one, every single time.
        #
        # Measured: 14 of the 15 setups that survived the entry engine,
        # the veto engine and conviction died here, all with the same
        # rejection -- "Risk:Reward 1.90 net of 0.6p spread (gross 2.00)
        # is below the absolute floor 2.00". A 0.10 miss, by
        # construction, on every trade.
        #
        # Solving for the constraint the gate actually applies:
        #     (tp - spread) / sl >= min_rr   ->   tp >= min_rr*sl + spread
        # so the spread is added rather than hoped away. Costs a slightly
        # wider target and makes the floor reachable.
        rr_floor_tp1 = sl_pips * min_rr + max(0.0, spread_pips or 0.0)
        if rr_floor_tp1 > tp1_pips:
            logger.info(
                f"[HYBRID_TP] {symbol}: TP1 raised {tp1_pips:.1f}p -> "
                f"{rr_floor_tp1:.1f}p to hold the {min_rr:.1f}:1 minimum "
                f"NET of the {spread_pips:.1f}p spread against a "
                f"{sl_pips:.1f}p stop"
            )
            tp1_pips = rr_floor_tp1

    # Invariant: TP1 < TP2 < TP3. Enforced after every adjustment above.
    tp2_pips = max(tp2_pips, tp1_pips + spread_pips + 1)
    tp3_pips = max(tp3_pips, tp2_pips + 5)

    if tp3_pips <= tp2_pips or tp2_pips <= tp1_pips:
        logger.error(
            f"[HYBRID_TP] {symbol}: take-profit ladder is out of order after "
            f"clamping (TP1={tp1_pips:.1f} TP2={tp2_pips:.1f} TP3={tp3_pips:.1f}). "
            f"This should be unreachable -- investigate before trusting these levels."
        )
    
    logger.info(f"[HYBRID_TP] {symbol}: TP1={tp1_pips:.1f}p, TP2={tp2_pips:.1f}p, TP3={tp3_pips:.1f}p")
    
    return tp1_pips, tp2_pips, tp3_pips


# ============================================================
# GLOBAL WRAPPER FUNCTIONS
# ============================================================

def _get_news_veto(symbol: str, best_direction: str = "BUY", risk_tolerance: str = "NORMAL"):
    try:
        from core.news_veto import check_news_veto_for_new_entry
        return check_news_veto_for_new_entry(symbol, best_direction, risk_tolerance)
    except Exception as e:
        logger.warning(f"News veto unavailable: {e}")
        return (False, None)


def _get_news_risk(symbol: str, current_pnl_percent: float = 0, position_direction: str = "BUY"):
    try:
        from core.news_veto import check_news_risk_for_existing_position
        return check_news_risk_for_existing_position(symbol, current_pnl_percent, position_direction)
    except Exception as e:
        logger.warning(f"News risk unavailable: {e}")
        return (False, None)


def _get_news_summary(symbol: str):
    try:
        from core.news_veto import get_news_summary
        return get_news_summary(symbol)
    except Exception as e:
        logger.warning(f"News summary unavailable: {e}")
        return {"has_news": False, "high_impact_count": 0, "medium_impact_count": 0, "low_impact_count": 0, "next_event": None, "all_events": []}


def _get_session_analysis(symbol: str, expected_gain_percent: float = 0, sl_pips: float = 0, 
                          current_pnl_percent: float = 0, is_new_entry: bool = True):
    try:
        from core.session_manager import get_session_analysis
        return get_session_analysis(symbol, expected_gain_percent, sl_pips, current_pnl_percent, is_new_entry)
    except Exception as e:
        logger.warning(f"Session analysis unavailable: {e}")
        return {
            "symbol": symbol,
            "exchange": "FX",
            # ✅ FIXED: this fallback asserted the market is OPEN while
            # simultaneously reporting it closed 2 minutes ago -- two
            # mutually exclusive claims, and the -2 was a hardcoded
            # sentinel, not a measurement. Anything downstream reading
            # minutes_to_close as a real number (close-proximity vetoes,
            # position management) was being handed a fabricated one.
            # None means "unknown", which is the truth when session_manager
            # is unreachable, and is falsy-distinct from a real 0.
            "is_market_open": True,
            "is_trading_day": True,
            "minutes_to_close": None,
            "session_data_available": False,
            "is_boom_trade": False,
            "expected_gain_percent": expected_gain_percent,
            "sl_pips": sl_pips,
            "veto_triggered": False,
            "veto_reason": None,
            "modify_sl": False,
            "new_sl_pips": None,
            "new_sl_price": None,
            "modify_tp": False,
            "new_tp_pips": None,
            "new_tp_price": None,
            "modification_reason": None,
            "should_close": False,
            "close_reason": None,
        }


def _veto_check_safe(method_name: str, *args, symbol: str = None) -> bool:
    """
    Report the veto result the FINAL DECISION actually used.

    ✅ FIXED (Phase 2, defect D-05). This used to RE-INVOKE the veto
    engine at reporting time and discard the reason string. That made the
    published flags a second, independent evaluation rather than a record
    of the first, and the two can differ for a structural reason:
    check_all_vetos() short-circuits on the first veto that fires, so
    later checks never run during the decision. Re-invoking them
    afterwards evaluates checks the decision never made, against state
    that may have moved -- which is precisely how choppy_market,
    extreme_volatility, wick_reversal and low_volume ended up disagreeing
    with vetos.triggered on live bars.

    Now reads the canonical record written by check_all_vetos(). A check
    that did not run returns False AND is marked not-evaluated in the
    reported detail, because "this check ran and declined to veto" and
    "this check never ran" are different facts.

    Falls back to the old re-invocation ONLY when no record exists (the
    veto stage did not run at all for this symbol), so behaviour is
    preserved for early-return paths rather than silently reporting
    everything as not-vetoed.
    """
    if symbol:
        try:
            record = get_veto_engine().get_veto_record(symbol)
            name = method_name[len("check_"):] if method_name.startswith("check_") else method_name
            entry = record.get(name)
            if entry is not None:
                return bool(entry.get("vetoed", False))
            if record:
                # The decision ran but short-circuited before this check.
                return False
        except Exception as e:
            logger.debug(f"[VETO] record unavailable for {symbol}/{method_name}: {e}")

    try:
        vetoed, _reason = getattr(get_veto_engine(), method_name)(*args)
        return bool(vetoed)
    except Exception as e:
        logger.debug(f"[VETO] {method_name} unavailable: {e}")
        return False


def _get_effective_veto_thresholds_safe(symbol: str, atr_band=None) -> dict:
    """Never let a reporting lookup take down an analysis."""
    try:
        return get_effective_veto_thresholds(symbol, atr_band=atr_band)
    except Exception as e:
        logger.debug(f"[VETO] effective thresholds unavailable for {symbol}: {e}")
        return {}


def _spread_pct_of_band(spread: float, upper: float, lower: float):
    """Spread as a percentage of the Bollinger band width.

    This is the number that decides whether the ask-vs-bid basis matters
    on a given instrument. A 2% spread is rounding; a 12% spread displaces
    every level comparison by an eighth of the band.
    """
    width = (upper or 0) - (lower or 0)
    if width <= 0 or spread is None:
        return None
    return round(spread / width * 100, 1)


def _choppy_check_matches_veto(adx_value, threshold) -> bool:
    """
    The reported `checks.choppy_market`, computed the way the VETO computes it.

    Reads the same mode the veto engine reads, so the payload cannot publish a
    check that contradicts the enforcement decision beside it.
    """
    try:
        mode = str(getattr(_veto_engine_singleton(), "choppy_market_mode",
                           "invert")).lower()
    except Exception:
        mode = "invert"
    adx = adx_value or 0
    if mode == "off":
        return False
    if mode == "invert":
        return adx >= threshold
    return adx < threshold


def _veto_engine_singleton():
    from core.veto_engine import VetoEngine
    global _VETO_ENGINE_FOR_CHECKS
    try:
        return _VETO_ENGINE_FOR_CHECKS
    except NameError:
        pass
    _VETO_ENGINE_FOR_CHECKS = VetoEngine()
    return _VETO_ENGINE_FOR_CHECKS


def _final_score_note(block, prefix: str) -> str:
    """
    A ledger note for the *_final_score components.

    ✅ FIXED: all six of these callers asked `block.get("reason", "")` and not
    one of calculate_smc_final_score / _fvg_ifvg_ / _gnn_ / _pattern_ /
    _order_flow_ / _gap_slippage_final_score returns a `reason` key. So the six
    highest-influence steps in the chain -- order_flow fires on 90.7% of
    trades, pattern 80.5%, fvg_ifvg 76.7%, smc 67.9% -- recorded their
    probability adjustment with an EMPTY explanation on every trade.

    The ledger exists so the final number is reconstructible from the payload
    rather than inferred. For the biggest contributors it recorded a delta and
    said nothing about why, which is the failure it was built to prevent.

    Synthesised here from the fields these functions DO return rather than by
    changing six function contracts other callers may depend on.
    """
    if not isinstance(block, dict):
        return ""
    if block.get("reason"):
        return str(block["reason"])

    # ✅ `order_flow` publishes REASONS (plural, a list) -- entries like
    # "Aligned STOP_HUNT_BUY_SIDE_TRAP (12.3p swept, reclaimed in 1 bar(s))".
    # The caller asked for "reason", singular. A one-letter key mismatch was
    # discarding the most detailed explanation any component in the chain
    # produces, on the component that fires most often (90.7% of trades).
    reasons = block.get("reasons")
    if isinstance(reasons, (list, tuple)) and reasons:
        return "; ".join(str(r) for r in reasons)[:400]

    bits = []
    contribution = block.get(prefix + "_contribution")
    if isinstance(contribution, (int, float)):
        bits.append(f"{prefix} {contribution:+.2f}")
    weight = block.get(prefix + "_weight_used")
    if isinstance(weight, (int, float)):
        bits.append(f"weight {weight:.1f}%")
    aligned = block.get("aligned")
    if aligned is not None:
        bits.append("aligned" if aligned else "OPPOSED to trade direction")
    for key in ("recommendation", "state", "classification", "verdict"):
        if block.get(key):
            bits.append(f"{key}={block[key]}")
            break
    return ", ".join(bits) if bits else f"{prefix}: no detail published"


def _entry_is_live(result) -> bool:
    """Whether the analysis is currently saying ENTER, in the field the monitor reads."""
    return bool((result.get("entry_analysis") or {}).get("should_enter"))


def _decline_entry(result, reason: str) -> None:
    """Turn an ENTER into DO NOTHING everywhere the decision is read.

    ✅ FIXED 2026-09-15. The conviction filter and the symbolic gate used to
    write only `final_verdict["should_enter"] = False` -- a key the verdict
    never carried, guarded by a check on that same missing key, so the branch
    never ran. The monitor enters on `entry_analysis.should_enter`. Both gates
    were therefore report-only: stored trades that failed conviction (10, right
    30%, -0.92R) and the symbolic gate (11, -1.04R) were all taken.
    """
    ea = result.setdefault("entry_analysis", {})
    ea["should_enter"] = False
    ea["simple_action"] = "HOLD"
    ea["execution"] = "DO_NOTHING"
    ea["final_decision"] = reason
    ea["reason"] = reason
    fv = result.setdefault("final_verdict", {})
    fv["should_enter"] = False
    fv["simple_action"] = "HOLD"
    fv["verdict"] = f"⏸️ {reason}"
    result["FINAL_DECISION"] = "DO NOTHING"
    result["🎯 FINAL_DECISION"] = f"⏸️ {reason}"
    result["🚀 SIMPLE_ACTION"] = "HOLD"


def _ledger_step(ledger, name, before, after, note="", intended=None):
    """Record one movement of best_probability.

    ✅ The payload published a chain of *_final_score blocks, but they did
    not account for the whole movement: EV, the H1 bonus and the hard-
    disagreement penalty change best_probability WITHOUT emitting an
    "adjustment" the way the confluence steps do.

    Live proof, XAUUSD: sell_probability 45.0, one published adjustment of
    -18.0, and a final 5.0 -- a 22-point gap with nothing in the payload
    to explain it. XAGUSD showed the same in the other direction, +8.0.
    The chain looked complete and did not reconcile.

    This ledger records EVERY step, so the number is reconstructible from
    the payload rather than inferred. Steps that move nothing are still
    recorded: "this check ran and declined to act" is different from
    "this check did not run", and the old output could not distinguish
    them.
    """
    try:
        b, a = float(before), float(after)
    except (TypeError, ValueError):
        return
    ledger.append({
        "step": name,
        "before": round(b, 2),
        "after": round(a, 2),
        "delta": round(a - b, 2),
        # True when this step hit a bound, so a step that "did nothing"
        # because it was clamped is distinguishable from one that had
        # nothing to say.
        "clamped": a in (5.0, 95.0),
        # ✅ ADDED (defect D-19): what the step WANTED to do versus what
        # it was allowed to do.
        #
        # The clamp was silently eating contributions while the
        # *_final_score blocks kept publishing them. Live proof, XAGUSD
        # 2026-09-01 15:49: probability arrived at the 95.0 ceiling from
        # calculate_probability_* BEFORE any chain step ran, so
        # expected_value reported "+15.0" and h1_alignment reported
        # "+10.0" while both moved the number by exactly 0.0. Twenty-five
        # points of evidence discarded, with nothing in the payload
        # saying so. An earlier snapshot showed order_flow publishing a
        # +12.0 contribution and a 0.0 delta.
        #
        # "absorbed" is the honest version of that: how much of the
        # intended movement the bound ate. A chain that regularly shows
        # non-zero absorbed values is a chain whose later evidence is
        # decorative, and that is worth knowing rather than hiding.
        "intended_after": (round(float(intended), 2)
                           if intended is not None else None),
        "absorbed": (round(float(intended) - a, 2)
                     if intended is not None else 0.0),
        "note": note,
    })



def _summarize_absorbed(ledger):
    """
    Which chain steps had their contribution eaten by the 5/95 bounds.

    Returns only the steps that actually lost something, plus a total,
    so a clean chain reports an empty list rather than noise.
    """
    absorbed = []
    total = 0.0
    for step in ledger or []:
        amount = step.get("absorbed") or 0.0
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            continue
        if abs(amount) < 0.05:
            continue
        absorbed.append({
            "step": step.get("step"),
            "applied_delta": step.get("delta"),
            "intended_after": step.get("intended_after"),
            "absorbed": round(amount, 2),
        })
        total += amount
    return {
        "steps": absorbed,
        "total_absorbed": round(total, 2),
        "clamped_step_count": sum(1 for s in (ledger or []) if s.get("clamped")),
        "note": (
            "Non-empty means evidence was computed and discarded at a bound. "
            "The *_final_score blocks report the intended contribution, not "
            "the applied one -- compare against applied_delta here."
        ),
    }

def _decode_minutes_to_close(minutes) -> str:
    """
    Turn session_manager's minutes_to_close into a readable state.

    That field mixes two kinds of value in one number: real minutes
    (positive) and status sentinels (negative). Reading it arithmetically
    -- "negative means the session ended N minutes ago" -- is wrong and is
    a mistake this codebase has already made once. Sentinels per
    session_manager._get_minutes_until_close_sync():
        -1 = closed for the day
        -2 = open, continuous market, no scheduled close
    """
    if minutes is None:
        return "UNKNOWN"
    if minutes == -1:
        return "CLOSED"
    if minutes == -2:
        return "OPEN_CONTINUOUS"
    if minutes < 0:
        return f"UNRECOGNIZED_SENTINEL({minutes})"
    return "OPEN_SCHEDULED"


def _get_session_summary(symbol: str, expected_gain_percent: float = 0, sl_pips: float = 0):
    try:
        from core.session_manager import get_session_summary
        return get_session_summary(symbol, expected_gain_percent, sl_pips)
    except Exception as e:
        logger.warning(f"Session summary unavailable: {e}")
        return {
            "symbol": symbol,
            "exchange": "FX",
            # ✅ FIXED: same fabricated -2 sentinel as _get_session_analysis
            # above -- see the note there.
            "is_open": True,
            "is_trading_day": True,
            "minutes_to_close": None,
            "session_data_available": False,
            "veto_triggered": False,
            "veto_reason": None,
        }


def _check_session_close(symbol: str, expected_gain_percent: float = 0, sl_pips: float = 0):
    try:
        from core.session_manager import check_session_close_for_existing_position
        return check_session_close_for_existing_position(symbol, expected_gain_percent, sl_pips)
    except Exception as e:
        logger.warning(f"Session close check unavailable: {e}")
        return (False, None)


# ============================================================
# PATTERN DATA FETCHING - HELPER
# ============================================================

def get_multi_timeframe_rates(symbol: str, timeframes: List[str] = None) -> Dict[str, np.ndarray]:
    """Fetch rates data for multiple timeframes."""
    if timeframes is None:
        timeframes = PATTERN_TIMEFRAMES
    
    tf_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1
    }
    
    rates_data = {}
    bars_needed = 500
    
    for tf in timeframes:
        if tf in tf_map:
            try:
                rates = mt5.copy_rates_from_pos(symbol, tf_map[tf], 0, bars_needed)
                if rates is not None and len(rates) > 50:
                    rates_data[tf] = rates
                else:
                    logger.warning(f"Insufficient data for {symbol} on {tf}: {len(rates) if rates else 0} bars")
            except Exception as e:
                logger.error(f"Failed to fetch {tf} data for {symbol}: {e}")
    
    return rates_data


# ============================================================
# MAIN FUNCTION - ANALYZE INSTITUTIONAL SIGNAL
# ============================================================

def _closed_bars_when_live(fn):
    """Live analyses read closed bars only, exactly like a replay
    (core/closed_bars.py). A replay (market_data given) is already served
    closed bars by core/mt5_shim.py and is left alone."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if kwargs.get("market_data") is not None or len(args) >= 14:
            return fn(*args, **kwargs)
        from core.closed_bars import closed_bars_context
        with closed_bars_context():
            return fn(*args, **kwargs)
    return wrapper


@_closed_bars_when_live
def analyze_institutional_signal(
    symbol: str,
    order_type: str,
    fixed_trade_size_usd: float,
    risk_per_trade: float,
    leverage: int = 200,
    timeframe: str = "M1",
    stop_loss_pips: Optional[float] = None,
    take_profit_pips: Optional[float] = None,
    debug: bool = False,
    is_already_in_trade: bool = False,
    current_pnl_percent: float = 0,
    use_gnn: bool = True,
    trade_id: int = None,
    market_data=None,
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """Main entry point for institutional signal analysis.

    strategy: "ALL" (every strategy group competes) or one group name that alone
    decides; None uses asset_analysis_config.STRATEGY_SELECTION."""

    from core.asset_analysis_config import STRATEGY_SELECTION
    from core.strategy_groups import GROUP_TITLES as _GROUP_TITLES
    strategy_selection = str(strategy or STRATEGY_SELECTION or "ALL").strip().upper()
    if strategy_selection != "ALL" and strategy_selection not in _GROUP_TITLES:
        logger.warning(f"[STRATEGY] unknown strategy {strategy_selection!r} -- every strategy competes (ALL)")
        strategy_selection = "ALL"

    # stop_loss_pips / take_profit_pips are accepted and NOT implemented:
    # this function always derives its own stop (calculate_lot_proper) and
    # target (calculate_hybrid_take_profit). No caller passes them today,
    # so nothing is being ignored -- but the signature advertises an
    # override that does not exist, and that is precisely the shape of
    # four bugs already found here. `min_stop_pips_override` was accepted
    # and unread in TWO sizing functions; `sl_pips` was accepted and
    # unread in the take-profit calculator, which left R:R uncontrolled
    # and cost 14 of 15 qualifying trades.
    #
    # Each of those was silent. This one says so.
    if stop_loss_pips is not None or take_profit_pips is not None:
        logger.warning(
            f"[API] {symbol}: stop_loss_pips={stop_loss_pips} / "
            f"take_profit_pips={take_profit_pips} were passed but are NOT "
            f"implemented -- this function computes its own SL/TP and your "
            f"values are being discarded. Use min_stop_pips_override on "
            f"calculate_lot_proper() for a stop floor.")

    # The caller supplies risk_per_trade (api/execution_controller.py passes the
    # request body straight through). A live snapshot on 2026-09-16 showed a $20
    # stop because a caller asked for 10%; the operator trades $4. One ceiling,
    # here, so no caller can raise the budget.
    if isinstance(risk_per_trade, (int, float)) and risk_per_trade > MAX_RISK_PER_TRADE:
        logger.warning(f"[RISK] {symbol}: caller asked for {risk_per_trade:.1%} of "
                       f"${fixed_trade_size_usd:.0f} -- capped at {MAX_RISK_PER_TRADE:.1%} "
                       f"(${fixed_trade_size_usd * MAX_RISK_PER_TRADE:.2f})")
        risk_per_trade = MAX_RISK_PER_TRADE

    local_debug = debug
    
    try:
        # ============================================================
        # MT5 DATA FETCHING
        # ============================================================
        max_retries = 3
        
        account_info = None
        for attempt in range(max_retries):
            # ✅ ADDED: market_data injection seam.
            # Every acquisition point below falls through to MT5 when
            # market_data is None, so live behaviour is unchanged. When
            # a MarketData is supplied (replay), the analysis runs on
            # exactly the bars it is handed and never reaches the
            # terminal -- which is what makes historical replay possible
            # at all. See core/market_data.py.
            if market_data is not None and market_data.account is not None:
                account_info = market_data.account
                break
            account_info = mt5.account_info()
            if account_info is not None:
                break
            time.sleep(0.5)
        
        if account_info is None:
            return {"success": False, "error": "Cannot get account info - MT5 not connected"}
        
        free_margin = float(account_info.margin_free) if account_info.margin_free else 0.0
        actual_account_balance = float(account_info.balance) if account_info.balance else 0.0
        
        # ✅ FIXED: real account leverage was sitting unused in account_info
        # this whole time (account_info.leverage) — every margin/lot-size
        # calculation downstream was instead using the hardcoded
        # `leverage: int = 200` default parameter regardless of what the
        # actual account is set to. If the real account leverage is lower
        # than 200 (common — many brokers cap retail forex leverage at
        # 30:1-100:1), every lot-size/margin calculation in this pipeline
        # was silently sizing positions as if far more margin was
        # available than actually is, which is exactly what leads to a
        # stop-out (forced liquidation) before your intended SL is hit.
        real_leverage = int(account_info.leverage) if getattr(account_info, "leverage", None) else leverage
        if real_leverage != leverage:
            logger.info(f"[LEVERAGE] Using real account leverage {real_leverage}:1 (was using hardcoded default {leverage}:1)")
        leverage = real_leverage
        
        tf_map = {
            "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1
        }
        selected_tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M1)
        
        rates = None
        for attempt in range(max_retries):
            # Only take the injected series when it IS the timeframe that
            # was asked for. It used to be taken unconditionally, so a
            # replay always analysed the feed's base timeframe (M1) no
            # matter what `timeframe` said, while live honoured it via
            # copy_rates_from_pos below. A replay of an M15 strategy
            # therefore reported M15 in its header and M1 everywhere in
            # its numbers.
            #
            # Falling through is safe and is the point: core/mt5_shim.py
            # patches copy_rates_from_pos and serves the requested
            # timeframe from the same no-lookahead feed, so the replay
            # stays historical either way -- it just stops answering a
            # different question than the one asked.
            if market_data is not None and market_data.rates is not None:
                md_tf = getattr(market_data, "base_timeframe", None)
                if md_tf is None or md_tf == timeframe.upper():
                    rates = market_data.rates
                    break
            rates = mt5.copy_rates_from_pos(symbol, selected_tf, 0, 1000)
            if rates is not None:
                break
            time.sleep(0.5)
        
        if rates is None or len(rates) < 200:
            return {"success": False, "error": f"Insufficient data: {len(rates) if rates else 0} bars"}
        
        tick = None
        for attempt in range(max_retries):
            if market_data is not None and market_data.tick is not None:
                tick = market_data.tick
                break
            tick = mt5.symbol_info_tick(symbol)
            if tick is not None:
                break
            time.sleep(0.5)
        
        info = None
        for attempt in range(max_retries):
            if market_data is not None and market_data.info is not None:
                info = market_data.info
                break
            info = mt5.symbol_info(symbol)
            if info is not None:
                break
            time.sleep(0.5)
        
        if tick is None or info is None:
            return {"success": False, "error": "No market data from MT5"}
        
        if tick.ask <= 0 or tick.bid <= 0:
            return {"success": False, "error": "Invalid tick prices"}
        
        # ============================================================
        # HIGHER TIMEFRAME CONFIRMATION (H1)
        # ============================================================
        # ✅ Injection seam. get_h1_trend(symbol) fetches its own 200 H1
        # bars from MT5, so in replay it would return TODAY's H1 trend
        # for a decision being replayed from months ago -- the single
        # most damaging lookahead in this function, because the H1
        # alignment bonus is worth +10 points.
        #
        # When replaying, either h1_data is supplied directly or it is
        # computed from the H1 slice the feed has already cut at the
        # decision timestamp.
        h1_data = None
        if M1_ONLY:
            # the neutral shape get_h1_trend itself returns when H1 is unavailable
            h1_data = {"trend": "NEUTRAL", "adx": 0, "ema_200": 0, "current_price": 0,
                       "available": False, "reason": "M1_ONLY: not read (H1 trend)"}
        elif market_data is not None:
            h1_data = market_data.h1_data
            if h1_data is None and market_data.multi_tf_rates.get("H1") is not None:
                h1_data = get_h1_trend(symbol, h1_rates=market_data.multi_tf_rates["H1"])
        if h1_data is None:
            h1_data = get_h1_trend(symbol)
        h1_trend = h1_data["trend"]
        h1_adx = h1_data["adx"]
        h1_ema_200 = h1_data["ema_200"]
        h1_current = h1_data["current_price"]
        
        # ============================================================
        # RSI DIVERGENCE -- M1 (core/rsi_divergence_setup.py)
        # ============================================================
        # Operator, 2026-09-18: the M15 RSI divergence is REPLACED by the M1 one --
        # the measured setup: classic divergence at +-50-bar M1 swings, RSI < 20
        # (> 80) at the swing, confirmed by a break of structure. Everything that
        # read the M15 divergence reads this: the probability chain, the RSI
        # score, the opposing-divergence veto and the published record.
        from core import rsi_divergence_setup as _rds
        try:
            if market_data is not None:
                _rds_rates = market_data.rates              # replay: only what the replay holds
            else:
                _rds_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, _rds.HISTORY)
            _rds_info = mt5.symbol_info(symbol) if market_data is None else None
            _rds_point = float(_rds_info.point) if _rds_info else _rds.pip_size(symbol) / 10
            rsi_divergence_state = _rds.state_from_rates(_rds_rates, symbol, _rds_point)
        except Exception as e:
            logger.warning(f"[RSI DIVERGENCE] {symbol}: unavailable ({e})")
            rsi_divergence_state = {"status": "NONE", "reason": f"error: {e}"}
        _div_side = (rsi_divergence_state.get("side")
                     if rsi_divergence_state.get("status") in ("CONFIRMED", "AWAITING_BOS") else None)
        rsi_div_type = {1: "REGULAR_BULLISH", -1: "REGULAR_BEARISH"}.get(_div_side, "NONE")
        rsi_div_score = {1: 85, -1: -85}.get(_div_side, 0)     # the scale the probability chain and veto use
        rsi_div_rsi = float(rsi_divergence_state.get("rsi_now", 50.0))
        
        # ============================================================
        # M15 STOCHASTIC DIVERGENCE
        # ============================================================
        stoch_div_data = get_stochastic_divergence(symbol, "M1" if M1_ONLY else "M15")
        stoch_div_type = stoch_div_data.get("divergence_type", "NONE")
        stoch_div_score = stoch_div_data.get("divergence_score", 0)
        stoch_k_m15 = stoch_div_data.get("stoch_k", 50)
        stoch_d_m15 = stoch_div_data.get("stoch_d", 50)
        
        # ============================================================
        # PREPARE DATA
        # ============================================================
        close_prices, high_prices, low_prices, volumes = extract_rates_arrays(rates)
        
        if close_prices is None:
            return {"success": False, "error": "Failed to extract price data from rates"}
        
        pip_size, point, digits = get_pip_info(info)
        
        candle_progress, candle_ready = get_candle_progress_fixed(rates, selected_tf, symbol)
        # ✅ Two prices, named for what they are.
        #
        # tick.ask is the correct price to BUY at, and stays the basis for
        # entry price, lot sizing and margin. It is NOT the right price to
        # measure distance-to-level with: every indicator level in this
        # pipeline comes from bar CLOSE prices, which are bid-side.
        #
        # Live XAGUSD: 43-pip spread against a 355.6-pip Bollinger band,
        # so an ask-vs-bid comparison is displaced 12.1% up the band --
        # systematically bullish, and worst exactly when spreads widen.
        #
        # indicator_price follows USE_MID_PRICE_FOR_INDICATORS (default
        # False -> identical to before). The delta is reported either way.
        _ask = float(tick.ask)
        _bid = float(tick.bid) if getattr(tick, "bid", None) else _ask
        _mid = (_bid + _ask) / 2.0 if _bid > 0 else _ask

        current_price = _ask
        indicator_price = _mid if USE_MID_PRICE_FOR_INDICATORS else _ask
        
        if math.isnan(current_price) or math.isinf(current_price) or current_price <= 0:
            return {"success": False, "error": f"Invalid price: {current_price}"}
        if current_price > 10000000:
            return {"success": False, "error": f"Invalid price: {current_price}"}
        
        if point is None or point == 0:
            point = 0.00001
        
        # Validate spread
        #
        # ✅ FIXED: this divided by `point`, producing a spread in POINTS,
        # and then compared it against get_max_spread() and
        # get_typical_spread() -- both of which are documented and named
        # in PIPS (MAX_SPREAD_PIPS_M1; "Get typical spread for a symbol
        # (pips)"). On any 3- or 5-digit instrument 1 pip is 10 points, so
        # every forex spread was measured ten times too large and checked
        # against a pip-denominated ceiling. A real 1-pip EURUSD spread
        # read as 10 and tripped the high-spread veto.
        #
        # It survived because the instrument this engine was tuned on is
        # XAGUSD, where get_pip_info() returns pip_size == point (0.001)
        # and the two units coincide exactly -- so every number checked
        # out and the bug was invisible until a 5-digit pair was replayed.
        #
        # `spread` flows from here into the veto engine, the R:R
        # net-of-spread calculation, the TP floor and the reported
        # spread_pips, so this single division sets the units for all of
        # them. pip_size is the correct divisor and is already in scope
        # from get_pip_info() above.
        # The thresholds themselves are POINT-valued despite their names
        # (MAX_SPREAD_PIPS_M1, "typical spread ... (pips)"). Read as pips
        # they are absurd for a 5-digit pair -- EURUSD "typical 6.0" and
        # "max 25" would be a 6-pip normal spread and a 25-pip ceiling.
        # Read as points they are 0.6 and 2.5 pips, which is exactly right.
        # The naming survived because on XAGUSD, where these were tuned,
        # pip and point are the same number and nothing could distinguish
        # the two readings.
        #
        # So both sides are converted to pips here rather than either one
        # being reinterpreted. points_per_pip is 1 on XAGUSD, which leaves
        # its behaviour byte-identical, and 10 on 5-digit pairs, which is
        # the whole of the correction.
        points_per_pip = (pip_size / point) if (point and pip_size) else 1.0
        if points_per_pip <= 0:
            points_per_pip = 1.0
        max_allowed_spread = get_max_spread(symbol) / points_per_pip
        typical_spread = get_typical_spread(symbol) / points_per_pip
        spread_tick = float((tick.ask - tick.bid) / pip_size) if pip_size else 0.0
        spread = spread_tick if spread_tick != 0 else typical_spread
        
        if spread <= 0 or spread > 1000:
            spread = typical_spread
        spread_valid = spread <= max_allowed_spread
        
        market_regime = detect_market_regime(rates)

        # ✅ ADDED: multi-factor regime classifier (ADX + volatility +
        # BB bandwidth percentile, persistence-smoothed) -- separate
        # from market_regime above, which keeps feeding
        # apply_probability_multipliers_pair()/check_volatility_protection()
        # exactly as before. trading_regime drives a direct probability
        # correction (REGIME_PROBABILITY_ADJUSTMENTS).
        # ✅ timeframe passed so the regime's Bollinger bandwidth uses the
        # same period/std as the rest of the pipeline (M1: 50 / 2.5).
        # Without it, trading_regime.bb_bandwidth and
        # indicators.bollinger_bands.width described the same bar with
        # different bands -- and the regime state derived from it sets the
        # regime probability correction.
        trading_regime = classify_trading_regime(rates, symbol, pip_size, timeframe=timeframe)
        
        # ============================================================
        # VOLUME
        # ============================================================
        volume_ratio, volume_spike, volume_increasing = get_volume_ratio(volumes, timeframe)
        
        if timeframe.upper() == "M1":
            volume_spike = volume_ratio >= VOLUME_SPIKE_THRESHOLD_M1
        
        atr_val = calculate_correct_atr(high_prices, low_prices, 14)
        atr_pips = atr_val / pip_size if pip_size > 0 else 10.0
        
        # ✅ NEW: build the instrument's own ATR percentile band BEFORE the
        # volatility check, so the check can use it instead of the static
        # _NORMAL_ATR_RANGES table. This band was already being computed --
        # but ~1800 lines further down, purely for display, long after the
        # penalty it should have informed had already floored probability.
        # Same failure shape as pattern `relevance`: the better number was
        # computed, reported, and ignored by the one thing that mattered.
        #
        # Gated on USE_ADAPTIVE_VOLATILITY_BANDS (default False) because
        # switching it on releases trades the static table was suppressing.
        # The adaptive (percentile) volatility band was removed 2026-09-18 with
        # core/adaptive_thresholds.py (operator decision): the static
        # per-instrument table decides volatility protection and the veto.
        atr_percentile_band = None

        volatility_check = check_volatility_protection(
            symbol, atr_pips, market_regime, percentile_band=atr_percentile_band
        )
        
        fvg_tolerance = _get_fvg_tolerance_pips(symbol, atr_pips)
        
        # ============================================================
        # CALCULATE TREND WITH DIVERGENCE IMPACT
        # ============================================================
        
        # First get base trend without divergence for reference
        base_trend_data = _analyze_trend_component(rates, symbol, pip_size, timeframe)
        
        # Get trend WITH divergence impact
        trend_data = _analyze_trend_component_with_divergence(
            rates=rates,
            symbol=symbol,
            pip_size=pip_size,
            timeframe=timeframe,
            rsi_divergence_type=rsi_div_type,
            stoch_divergence_type=stoch_div_type
        )
        current_trend = trend_data.get("trend", "NEUTRAL")
        
        # ============================================================
        # PATTERN ANALYSIS - MULTI-TIMEFRAME
        # ============================================================
        
        # ✅ FIXED: this used to unconditionally call get_multi_timeframe_
        # rates(symbol), which fetches 500 bars via mt5.copy_rates_from_pos
        # for EVERY canonical timeframe (M1/M5/M15/M30/H1) - 5 separate
        # broker round-trips - on every single analysis call, regardless
        # of which one timeframe was actually being traded. Now scoped to
        # just the current timeframe by default (reuses the `rates`
        # already fetched for it - zero extra IO). Flip
        # PATTERN_ANALYSIS_CURRENT_TF_ONLY off in config to restore full
        # multi-timeframe fetching if genuinely needed later.
        #
        # ✅ ALSO REMOVED: the elliott_waves_by_tf pre-computation loop
        # that used to run here (a separate analyze_elliott_waves_
        # enhanced() call per timeframe, on top of the above). It built a
        # dict and passed it into analyze_patterns_multi_timeframe() as a
        # parameter that function NEVER READS — confirmed by checking the
        # function body, "elliott_waves_by_tf" only appeared in its
        # signature. 100% wasted computation, on every timeframe, every
        # call.
        if PATTERN_ANALYSIS_CURRENT_TF_ONLY:
            multi_tf_rates = {timeframe: rates}
        else:
            # ✅ Injection seam. Same lookahead risk as H1: the pattern
            # engine reads M1/M5/M15/M30/H1, and fetching them live
            # during replay hands it the present.
            if market_data is not None and market_data.multi_tf_rates:
                multi_tf_rates = market_data.multi_tf_rates
            else:
                multi_tf_rates = get_multi_timeframe_rates(symbol)
        pattern_recognizer = PatternRecognizer()

        # ✅ FIXED: pattern_recognizer.set_regime()/set_session()/
        # set_timeframe()/set_current_price() were NEVER called anywhere
        # in this codebase -- PatternRecognizer.__init__ defaults
        # _current_regime to "NORMAL" and _current_session to "LONDON"
        # and nothing ever updated them. "NORMAL" isn't even a key in
        # patterns.py's own REGIME_ADJUSTMENTS dict, so that lookup's
        # .get(..., 1.0) default fired on every single pattern, every
        # call -- both the existing flat regime reweight AND the new
        # classification-aware regime gate (REGIME_CLASSIFICATION_GATE)
        # were dead code with the multiplier permanently stuck at 1.0,
        # regardless of what the market was actually doing.
        #
        # patterns.py's Regime vocabulary (TRENDING/RANGING/
        # HIGH_VOLATILITY/LOW_VOLATILITY/NORMAL) is simpler than this
        # file's own 6-state trading_regime classifier (TRENDING_CALM/
        # TRENDING_VOLATILE/RANGING_CALM/RANGING_VOLATILE/CHOPPY/
        # SQUEEZE), so trading_regime["state"] (already computed above)
        # is mapped down onto it rather than introducing a third
        # regime concept: CHOPPY -> HIGH_VOLATILITY (erratic, no clear
        # direction) and SQUEEZE -> LOW_VOLATILITY (compressed range)
        # are the closest real matches for those two states.
        _PATTERNS_REGIME_MAP = {
            "TRENDING_CALM": "TRENDING",
            "TRENDING_VOLATILE": "TRENDING",
            "RANGING_CALM": "RANGING",
            "RANGING_VOLATILE": "RANGING",
            "CHOPPY": "HIGH_VOLATILITY",
            "SQUEEZE": "LOW_VOLATILITY",
        }
        pattern_recognizer.set_regime(_PATTERNS_REGIME_MAP.get(trading_regime.get("state"), "NORMAL"))
        pattern_recognizer.set_timeframe(timeframe)
        pattern_recognizer.set_current_price(current_price)
        pattern_recognizer.set_atr_pips(atr_pips)
        
        # Need sr_data for pattern analysis - compute it here
        sr_data_temp = _analyze_support_resistance_component(
            high_prices, low_prices, close_prices, current_price, pip_size, volume_ratio, current_trend
        )
        
        # RSI computed early (cheap, close_prices-only) so pattern
        # confidence scoring can check real momentum alignment instead of
        # the dead rsi_aligned flag that used to sit unset in every
        # detector. The full indicators component recomputes RSI again
        # later for its own section - fine, it's O(n) on an already-small
        # array, not worth threading a shared value through two unrelated
        # component functions for.
        _pattern_rsi_series = _calculate_rsi(close_prices, 14)
        pattern_rsi = validate_rsi_value(
            _pattern_rsi_series[-1] if _pattern_rsi_series else DEFAULT_RSI_VALUE,
            "RSI14_pattern", DEFAULT_RSI_VALUE
        )
        
        pattern_result = analyze_patterns_multi_timeframe(
            symbol=symbol,
            rates_data=multi_tf_rates,
            current_price=current_price,
            pip_size=pip_size,
            pattern_recognizer=pattern_recognizer,
            volume_ratio=volume_ratio,
            adx=trend_data.get("adx_value", 0),
            spread_pips=spread,
            trend=trend_data.get("trend", "NEUTRAL"),
            range_high=sr_data_temp.get("recent_swing_high"),
            range_low=sr_data_temp.get("recent_swing_low"),
            rsi=pattern_rsi
        )
        
        # ============================================================
        # PARALLEL COMPONENT ANALYSIS
        # ============================================================
        component_results = {}
        effective_workers = max(1, min(MAX_WORKERS, 8))
        
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            futures = {}
            
            # Use trend_data with divergence impact
            futures[executor.submit(lambda: trend_data)] = "trend"
            futures[executor.submit(_analyze_ict_component, rates, indicator_price, pip_size, fvg_tolerance, volume_ratio, atr_pips)] = "ict"
            futures[executor.submit(_analyze_supply_demand_component, rates, indicator_price, pip_size, symbol, timeframe, volume_ratio, trend_data.get("adx_value", 0), spread, atr_pips )] = "supply_demand"
            futures[executor.submit(_analyze_indicators_component, close_prices, high_prices, low_prices, volumes, timeframe, current_price, pip_size, volume_ratio, volume_increasing, current_trend, symbol)] = "indicators"
            futures[executor.submit(_analyze_support_resistance_component, high_prices, low_prices, close_prices, indicator_price, pip_size, volume_ratio, current_trend, atr_pips)] = "support_resistance"
            # ✅ FIXED (Phase 2/6, defect D-07): was `rates[-1]`, the bar
            # currently FORMING. Its high/low/close are still moving, so
            # the candlestick pattern read from it is provisional -- and
            # it feeds calculate_real_probability() (candlestick_score)
            # and the `pattern` family vote as if it were settled.
            #
            # The replay consequence is the serious one. In historical
            # replay rates[-1] is a CLOSED bar whose full range is known,
            # so identical code sees strictly more information replaying
            # than it had live. Every backtest built on it is optimistic
            # for a reason that has nothing to do with the strategy, and
            # the discrepancy is invisible because both runs "use
            # rates[-1]".
            #
            # CANDLESTICK_USE_CLOSED_BAR (default True) reads the last
            # CLOSED bar instead. When the forming bar is nearly complete
            # the two agree; early in a bar they do not, and the closed
            # one is the only one that is a fact. The forming bar's
            # progress is already tracked separately via candle_progress
            # / candle_ready and still gates entry timing -- that is the
            # right place for it, because timing is a question about the
            # bar in progress, and pattern evidence is not.
            # rates holds CLOSED bars only, live and in replay alike
            # (core/closed_bars.py), so the last one is the last completed
            # candle. Taking rates[-2] here read one bar too old in replay.
            _candle_bar = rates[-1]
            futures[executor.submit(_analyze_candlestick_component, _candle_bar, pip_size, atr_pips)] = "candlestick"
            
            for future in as_completed(futures):
                key = futures[future]
                try:
                    component_results[key] = future.result()
                except Exception as e:
                    logger.error(f"Component {key} failed: {e}")
                    component_results[key] = {}
        
        # Get trend data from component results (already has divergence applied)
        trend_data = component_results.get("trend") or {}
        ict_data = component_results.get("ict") or {}
        sd_data = component_results.get("supply_demand") or {}
        indicators_data = component_results.get("indicators") or {}
        sr_data = component_results.get("support_resistance") or {}
        candle_data = component_results.get("candlestick") or {}
        
        wyckoff_data = _analyze_wyckoff_component(
            rates, 
            trend_data.get("adx_value", 0), 
            trend_data.get("trend", "NEUTRAL"), 
            volume_ratio, 
            symbol, 
            pip_size,
            timeframe
        )
        
        # ============================================================
        # EMAS
        # ============================================================
        ema_9 = _calculate_ema(close_prices, 9)
        ema_21 = _calculate_ema(close_prices, 21)
        ema_100 = _calculate_ema(close_prices, 100)
        
        adx_7 = _calculate_adx(high_prices, low_prices, close_prices, 7)
        adx_21 = _calculate_adx(high_prices, low_prices, close_prices, 21)
        
        ema_gap_pips = calculate_ema_gap_pips(
            trend_data.get("ema_20", 0), 
            trend_data.get("ema_200", 0), 
            pip_size
        )
        
        # ============================================================
        # FVG INVALIDATION
        # ============================================================
        ict_signal_type = ict_data.get("signal_type", "NONE")
        price_above_fvg_pips = ict_data.get("price_above_fvg_pips", 0)
        price_below_fvg_pips = ict_data.get("price_below_fvg_pips", 0)
        
        if ict_signal_type == "BULLISH" and price_above_fvg_pips > fvg_tolerance * FVG_INVALIDATION_MULTIPLIER:
            ict_signal_type = "INVALID"
            if local_debug:
                logger.debug(f"[ICT] BULLISH FVG invalidated: price {price_above_fvg_pips:.1f}p above tolerance")
        elif ict_signal_type == "BEARISH" and price_below_fvg_pips > fvg_tolerance * FVG_INVALIDATION_MULTIPLIER:
            ict_signal_type = "INVALID"
            if local_debug:
                logger.debug(f"[ICT] BEARISH FVG invalidated: price {price_below_fvg_pips:.1f}p below tolerance")
        
        ict_rec, ict_score_val = get_ict_recommendation(ict_signal_type, trend_data.get("trend", "NEUTRAL"))
        
        # ✅ NEW: get_ict_recommendation() gives every valid BULLISH/BEARISH
        # FVG a flat base_score of 80, regardless of how wide, fresh, or
        # volume-backed it actually is. Scale it by the tier score computed
        # above instead — a TIER_3 (thin/stale/low-volume) FVG now
        # contributes much less than a TIER_1 one, rather than identically.
        if ict_score_val > 0:
            fvg_tier_score = ict_data.get("fvg_tier_score", 0.0)
            if not ict_data.get("fvg_valid", True):
                ict_score_val = 0
                ict_rec = "HOLD"
            else:
                ict_score_val = round(ict_score_val * (fvg_tier_score / 100.0), 1)

        # ============================================================
        # ✅ FIXED: ICT voted BUY on a setup ICT itself had vetoed
        # ============================================================
        # get_ict_recommendation(ict_type, trend) sees only the FVG's
        # polarity and the trend -- it has no idea WHERE price is relative
        # to the gap. calculate_probability_buy/sell does, and vetoes
        # outright when price hasn't reached the zone:
        #     BUY  + BULLISH FVG + price_below_fvg_pips > fvg_tolerance
        #           -> veto "ICT_BULLISH_PRICE_BELOW_FVG"
        #
        # The invalidation check above is NOT the same rule -- it fires on
        # the opposite side (price ran away PAST the gap) and at a looser
        # threshold (x FVG_INVALIDATION_MULTIPLIER). So the approach-side
        # case fell through: the FVG stayed "valid", ict_rec stayed a
        # full-strength directional call, and it cast a real vote in the
        # structure family for a direction the probability chain had
        # already ruled un-enterable.
        #
        # Confirmed live (XAGUSD M1): BULLISH FVG, price_below_fvg_pips
        # 75.0 against a 17.3 tolerance -- breakdown_buy came back
        # {"veto": "ICT_BULLISH_PRICE_BELOW_FVG"} while indicators.
        # ict_concepts published recommendation BUY at score 62.2.
        #
        # Downgraded to HOLD here rather than marked INVALID: the gap is
        # still a real level, it just isn't actionable yet. Deliberately
        # does NOT touch ict_signal_type, which is what feeds the veto --
        # this aligns the VOTE with the veto without altering the veto.
        if ict_rec in ("BUY", "SELL") and fvg_tolerance > 0:
            approach_distance = (
                price_below_fvg_pips if ict_signal_type == "BULLISH" else price_above_fvg_pips
            )
            if approach_distance > fvg_tolerance:
                logger.debug(
                    f"[ICT] {symbol}: {ict_signal_type} FVG not in play -- price "
                    f"{approach_distance:.1f}p from the gap vs {fvg_tolerance:.1f}p tolerance; "
                    f"vote downgraded {ict_rec}->HOLD to match the probability veto"
                )
                ict_rec = "HOLD"
                ict_score_val = 0
        
        # ============================================================
        # COT REPORT
        # ============================================================
        if timeframe.upper() in ["M1", "M5"]:
            cot_score = 0
            cot_rec = "EXCLUDED (M1/M5)"
        else:
            cot_rec = "REFER_TO_COMMITMENTS"
            cot_score = 0
        
        # ============================================================
        # BOLLINGER BANDWIDTH HISTORY
        # ============================================================
        # ✅ FIXED: same missing period/std args as the other BB call site,
        # plus the length guard was hardcoded to `idx + 20` regardless of
        # which period is actually being used -- on M1 (period 50) this
        # let through windows shorter than the period itself.
        bb_period_hist = get_bb_period(timeframe)
        bb_std_hist = get_bb_std(timeframe)
        bandwidth_history = []
        for idx in range(1, 6):
            if len(close_prices) > idx + bb_period_hist:
                temp_upper, temp_middle, temp_lower, _, _, temp_width = _calculate_bollinger_bands(
                    close_prices[:-idx] if idx > 0 else close_prices,
                    period=bb_period_hist, std_dev=bb_std_hist
                )
                bandwidth_history.append(round(temp_width, 4))
        
        # ============================================================
        # POI (Point of Interest)
        # ============================================================
        # ✅ FIXED: was pure proximity (is_at_zone OR is_price_in_fvg --
        # just "is price currently sitting inside the zone's bounds"),
        # with no check for HOW price got there. Now also requires
        # displacement confirmation (core/displacement_confirmation.py):
        # a strong-bodied candle actually broke INTO the zone in the
        # last few bars, not just price drifting into proximity. Cuts
        # the "price touched it but never respected it" loss pattern --
        # at_zone_proximity/at_fvg_proximity are preserved separately
        # below (and in the output) so it's still visible when price
        # was near a zone but displacement never confirmed it, rather
        # than that distinction disappearing into a flat False.
        at_zone_proximity = sd_data.get("is_at_zone", False)
        at_fvg_proximity = ict_data.get("is_price_in_fvg", False)

        displacement_confirmed = False
        displacement_detail = {"available": False, "confirmed": False, "reason": "not at any zone/FVG"}
        try:
            if at_zone_proximity and sd_data.get("zone_level") is not None:
                displacement_detail = check_displacement_confirmation(
                    rates, sd_data["zone_level"], sd_data["zone_level"],
                    sd_data.get("zone_type", "DEMAND"), pip_size, atr_pips
                )
                displacement_confirmed = displacement_confirmed or displacement_detail.get("confirmed", False)
            if at_fvg_proximity and ict_data.get("fvg_low") is not None and ict_data.get("fvg_high") is not None:
                fvg_displacement_detail = check_displacement_confirmation(
                    rates, ict_data["fvg_low"], ict_data["fvg_high"],
                    ict_data.get("signal_type", "BULLISH"), pip_size, atr_pips
                )
                displacement_confirmed = displacement_confirmed or fvg_displacement_detail.get("confirmed", False)
                if not at_zone_proximity:
                    displacement_detail = fvg_displacement_detail
        except Exception as e:
            logger.warning(f"[DISPLACEMENT] {symbol}: check failed: {e}")

        at_poi = (at_zone_proximity or at_fvg_proximity) and displacement_confirmed
        
        # ============================================================
        # PROBABILITY CALCULATION - WITH DIVERGENCE IMPACT
        # ============================================================
        
        probability_buy, fvg_tolerance_used_buy, breakdown_buy = calculate_real_probability(
            trend=trend_data.get("trend", "NEUTRAL"), order_type="BUY", 
            sd_grade=sd_data.get("zone_grade", "E"), is_at_zone=sd_data.get("is_at_zone", False),
            wyckoff_score=wyckoff_data.get("score", 0), wyckoff_phase=wyckoff_data.get("phase", "NEUTRAL"),
            volume_ratio=volume_ratio, rsi_val=indicators_data.get("rsi", {}).get("value", 50),
            ict_signal_type=ict_signal_type, adx_val=trend_data.get("adx_value", 0),
            bb_signal=indicators_data.get("bollinger", {}).get("signal", "NEUTRAL"),
            macd_signal=indicators_data.get("macd", {}).get("signal_str", "NEUTRAL"),
            stoch_signal=indicators_data.get("stochastic", {}).get("signal", "NEUTRAL"),
            rsi_divergence_type=rsi_div_type,
            rsi_divergence_score=rsi_div_score,
            candlestick_score=float(candle_data.get("score", 0)),
            price_above_fvg_pips=price_above_fvg_pips, price_below_fvg_pips=price_below_fvg_pips,
            bb_band_width=indicators_data.get("bollinger", {}).get("width", 1.0),
            distance_to_resistance_pips=_far_if_absent(sr_data.get("distance_to_resistance_pips")),
            distance_to_support_pips=_far_if_absent(sr_data.get("distance_to_support_pips")),
            ema20_ema200_gap_pips=ema_gap_pips,
            rsi_14=indicators_data.get("rsi", {}).get("value", 50),
            rsi_21=indicators_data.get("rsi", {}).get("rsi_21", 50),
            symbol=symbol, atr_pips=atr_pips, fvg_tolerance=fvg_tolerance, timeframe=timeframe
        )
        
        # Add Stochastic divergence bonus to probability
        if stoch_div_type == "HIDDEN_BULLISH" and probability_buy > 50:
            probability_buy += 3
            breakdown_buy["stoch_divergence"] = 3
        elif stoch_div_type == "REGULAR_BULLISH" and probability_buy > 50:
            probability_buy += 5
            breakdown_buy["stoch_divergence"] = 5
        elif stoch_div_type == "HIDDEN_BEARISH" and probability_buy > 50:
            probability_buy -= 3
            breakdown_buy["stoch_divergence"] = -3
        elif stoch_div_type == "REGULAR_BEARISH" and probability_buy > 50:
            probability_buy -= 5
            breakdown_buy["stoch_divergence"] = -5
        
        probability_sell, fvg_tolerance_used_sell, breakdown_sell = calculate_real_probability(
            trend=trend_data.get("trend", "NEUTRAL"), order_type="SELL",
            sd_grade=sd_data.get("zone_grade", "E"), is_at_zone=sd_data.get("is_at_zone", False),
            wyckoff_score=wyckoff_data.get("score", 0), wyckoff_phase=wyckoff_data.get("phase", "NEUTRAL"),
            volume_ratio=volume_ratio, rsi_val=indicators_data.get("rsi", {}).get("value", 50),
            ict_signal_type=ict_signal_type, adx_val=trend_data.get("adx_value", 0),
            bb_signal=indicators_data.get("bollinger", {}).get("signal", "NEUTRAL"),
            macd_signal=indicators_data.get("macd", {}).get("signal_str", "NEUTRAL"),
            stoch_signal=indicators_data.get("stochastic", {}).get("signal", "NEUTRAL"),
            rsi_divergence_type=rsi_div_type,
            rsi_divergence_score=rsi_div_score,
            candlestick_score=float(candle_data.get("score", 0)),
            price_above_fvg_pips=price_above_fvg_pips, price_below_fvg_pips=price_below_fvg_pips,
            bb_band_width=indicators_data.get("bollinger", {}).get("width", 1.0),
            distance_to_resistance_pips=_far_if_absent(sr_data.get("distance_to_resistance_pips")),
            distance_to_support_pips=_far_if_absent(sr_data.get("distance_to_support_pips")),
            ema20_ema200_gap_pips=ema_gap_pips,
            rsi_14=indicators_data.get("rsi", {}).get("value", 50),
            rsi_21=indicators_data.get("rsi", {}).get("rsi_21", 50),
            symbol=symbol, atr_pips=atr_pips, fvg_tolerance=fvg_tolerance, timeframe=timeframe
        )
        
        if local_debug:
            logger.debug(f"[PROBABILITY_BREAKDOWN] BUY: {breakdown_buy}")
            logger.debug(f"[PROBABILITY_BREAKDOWN] SELL: {breakdown_sell}")
        
        prob_buy_adj, prob_sell_adj = apply_probability_multipliers_pair(
            probability_buy, probability_sell, candle_ready, market_regime, spread_valid
        )
        probability_buy = prob_buy_adj
        probability_sell = prob_sell_adj
        
        confidence_penalty = volatility_check.get("confidence_penalty", 0)
        if confidence_penalty > 0:
            probability_buy = max(5.0, min(95.0, probability_buy - confidence_penalty))
            probability_sell = max(5.0, min(95.0, probability_sell - confidence_penalty))
        
        # ============================================================
        # TRADING REGIME PROBABILITY CORRECTION
        # ============================================================
        # ✅ ADDED: applied at the same point as the existing
        # confidence_penalty above, so it lands on probability_buy/sell
        # BEFORE best_direction/best_probability are chosen just below --
        # meaning it actually reaches analyze_entry()'s star_rating
        # decision. pattern_final_score/gnn_final/smc_final, further down,
        # are intentionally NOT applied until after the entry decision is
        # already locked in -- they affect the reported probability_percent
        # and downstream sizing, not entry/no-entry (see the chaining block
        # near gnn_final below for why, and confirmation all three are now
        # actually wired in rather than computed-and-discarded).
        regime_probability_adjustment = REGIME_PROBABILITY_ADJUSTMENTS.get(trading_regime["state"], 0.0)
        if not trading_regime.get("confirmed", False):
            regime_probability_adjustment *= REGIME_UNCONFIRMED_DAMPING
        if regime_probability_adjustment != 0:
            probability_buy = max(5.0, min(95.0, probability_buy + regime_probability_adjustment))
            probability_sell = max(5.0, min(95.0, probability_sell + regime_probability_adjustment))
        
        # ============================================================
        # BEST DIRECTION WITH TIE-BREAKER
        # ============================================================
        trend = trend_data.get("trend", "NEUTRAL")
        adx_val = trend_data.get("adx_value", 0)
        
        # ✅ FIXED: the tie-break below broke ties using `trend` alone and
        # never consulted whether one of the two directions had been
        # explicitly VETOED upstream. calculate_probability_*() signals a
        # veto by returning a breakdown of the form {"veto": "..."} (e.g.
        # ICT_BEARISH_FOR_BUY) along with a floored probability -- but the
        # veto reaches this decision only as a lowered NUMBER, and once the
        # 5.0 clamp on the penalty lines above pins both sides to the same
        # floor, the two directions are indistinguishable here and the tie
        # branch fires.
        #
        # That is exactly what happened live: BUY was vetoed
        # (ICT_BEARISH_FOR_BUY), the -71.9 volatility confidence_penalty
        # floored BOTH sides to 5.0, the tie branch consulted `trend`
        # (BULLISH) -- the very read ICT was contradicting -- and BUY won,
        # producing a full entry/SL/TP/lot plan for a vetoed direction.
        # Only the unrelated choppy-market veto stopped the trade.
        #
        # Scope is deliberately narrow: this ONLY governs the tie branch.
        # When the probabilities actually differ, the existing comparison
        # is untouched -- a veto still expresses itself as a lower number
        # there, exactly as before. All this does is stop a tie from being
        # resolved IN FAVOUR of a direction that was explicitly ruled out.
        buy_vetoed = isinstance(breakdown_buy, dict) and bool(breakdown_buy.get("veto"))
        sell_vetoed = isinstance(breakdown_sell, dict) and bool(breakdown_sell.get("veto"))

        if probability_buy > probability_sell:
            best_direction = "BUY"
            best_probability = probability_buy
        elif probability_sell > probability_buy:
            best_direction = "SELL"
            best_probability = probability_sell
        elif buy_vetoed and not sell_vetoed:
            best_direction = "SELL"
            best_probability = probability_sell
            logger.warning(
                f"[AUTO] {symbol}: tie at {probability_buy:.1f}% broken AWAY from BUY -- "
                f"BUY was vetoed ({breakdown_buy.get('veto')})"
            )
        elif sell_vetoed and not buy_vetoed:
            best_direction = "BUY"
            best_probability = probability_buy
            logger.warning(
                f"[AUTO] {symbol}: tie at {probability_sell:.1f}% broken AWAY from SELL -- "
                f"SELL was vetoed ({breakdown_sell.get('veto')})"
            )
        else:
            # Either both vetoed or neither -- no veto signal to separate
            # them, so fall back to the original trend tie-break.
            if buy_vetoed and sell_vetoed:
                logger.warning(
                    f"[AUTO] {symbol}: BOTH directions vetoed "
                    f"(BUY: {breakdown_buy.get('veto')}, SELL: {breakdown_sell.get('veto')}) "
                    f"-- falling back to trend tie-break"
                )
            if trend in ["STRONG_BEARISH", "BEARISH"]:
                best_direction = "SELL"
                best_probability = probability_sell
            elif trend in ["STRONG_BULLISH", "BULLISH"]:
                best_direction = "BUY"
                best_probability = probability_buy
            else:
                best_direction = "BUY" if probability_buy >= probability_sell else "SELL"
                best_probability = max(probability_buy, probability_sell)
        
        # ✅ NEW: when BOTH directions were vetoed, the pipeline still runs
        # to completion and emits a full entry/SL/TP/lot plan for whichever
        # side the trend tie-break picked -- a complete, actionable-looking
        # trade for a bar on which neither direction was permitted. Seen
        # live twice. Nothing downstream had any way to know: the vetoes
        # live in breakdown_buy/breakdown_sell, which no consumer reads.
        #
        # Surfaced as a first-class flag rather than suppressed, because
        # whether a both-vetoed bar should skip outright is a trading
        # policy decision, not a bug fix. The existing veto/probability
        # gates already stop these in practice; this makes the situation
        # visible so it can be gated deliberately if you want it to be.
        both_directions_vetoed = buy_vetoed and sell_vetoed
        directional_veto_info = {
            "buy_veto": breakdown_buy.get("veto") if isinstance(breakdown_buy, dict) else None,
            "sell_veto": breakdown_sell.get("veto") if isinstance(breakdown_sell, dict) else None,
            "both_directions_vetoed": both_directions_vetoed,
            "chosen_direction_was_vetoed": (
                (best_direction == "BUY" and buy_vetoed) or
                (best_direction == "SELL" and sell_vetoed)
            ),
        }
        if directional_veto_info["chosen_direction_was_vetoed"]:
            logger.warning(
                f"[AUTO] {symbol}: proceeding with {best_direction} despite its own veto "
                f"({directional_veto_info['buy_veto'] if best_direction == 'BUY' else directional_veto_info['sell_veto']}) "
                f"-- the opposing direction was vetoed too"
            )

        # ✅ every subsequent movement of best_probability is recorded here
        probability_ledger = []
        _ledger_step(probability_ledger, "directional_probability",
                     best_probability, best_probability,
                     f"{best_direction} raw from calculate_probability_*")

        logger.info(f"[AUTO] Direction: {best_direction} (BUY: {probability_buy:.1f}%, SELL: {probability_sell:.1f}%, Trend: {trend}, ADX: {adx_val:.1f})")

        # ============================================================
        # TREND CASCADE DECIDES THE SIDE (before sizing)
        # ============================================================
        # The M5/M15/H1/H4 cascade is the strongest directional evidence
        # measured on the stored trades, and as a probability nudge (applied
        # further down) it could not stop counter-trend entries. Here it
        # decides the side instead -- before the stop, target and lot are
        # built, so the bracket belongs to the side actually traded.
        #
        # ✅ FIXED 2026-09-16: the flipped side now carries ITS OWN probability.
        # The old behaviour kept the rejected side's confidence ("carried over"),
        # so a SELL could be gated on the BUY score -- a live snapshot showed a
        # SELL entered at 74.3% while the payload's own probability_sell was
        # 6.6%. Measured over 110,603 study snapshots the flip earns nothing
        # either way (flipped 41.5% right / -0.190R, unflipped 42.0% / -0.185R),
        # so there is no case for gating on a number that describes the side the
        # cascade just rejected. See core/trend_cascade.py.
        try:
            if M1_ONLY:
                # unavailable -> cascade_direction_override never flips the side
                trend_cascade_result = {"available": False, "score": 0.0, "direction": "NEUTRAL",
                                        "reason": "M1_ONLY: not read (M5-H4 trend cascade)"}
            else:
                trend_cascade_result = get_trend_cascade(symbol, pip_size)
        except Exception as e:
            logger.warning(f"[TREND CASCADE] {symbol}: failed: {e}")
            trend_cascade_result = {"available": False, "score": 0.0, "direction": "NEUTRAL", "reason": f"error: {e}"}

        analysis_direction = best_direction
        _cascade_side = cascade_direction_override(trend_cascade_result, best_direction)
        if _cascade_side is not None:
            best_direction = _cascade_side
            _prob_before_flip = best_probability
            best_probability = side_probability(best_direction, probability_buy, probability_sell,
                                                fallback=best_probability)
            _ledger_step(probability_ledger, "trend_cascade_direction", _prob_before_flip, best_probability,
                         f"side {analysis_direction} -> {best_direction}: decisive "
                         f"{trend_cascade_result.get('direction')} cascade (score "
                         f"{trend_cascade_result.get('score'):+.2f}); probability is now "
                         f"{best_direction}'s own")
            logger.warning(
                f"[TREND CASCADE] {symbol}: analysis chose {analysis_direction}, cascade is "
                f"{trend_cascade_result.get('direction')} ({trend_cascade_result.get('score'):+.2f}) "
                f"-- trading {best_direction}")
        # ---- measured direction inversion (2026-09-17) -----------------------
        # The engine's own side loses to its opposite by 2.7 points of win rate
        # on 60,853 decisions scored both ways on the same bars, in both halves
        # and both live categories (asset_analysis_config.INVERT_ENTRY_DIRECTION
        # carries the table). Flipped HERE -- after the auction and the cascade,
        # before the setups and the entry rules -- so the strategy setup, the
        # zone, the geometry and every rule are evaluated for the side actually
        # traded. It reduces the loss; it does not make the system profitable.
        if INVERT_ENTRY_DIRECTION:
            _pre_inversion_direction = best_direction
            best_direction = "SELL" if str(best_direction).upper() == "BUY" else "BUY"
            _prob_before_inversion = best_probability
            best_probability = side_probability(best_direction, probability_buy, probability_sell,
                                                fallback=best_probability)
            _ledger_step(probability_ledger, "measured_direction_inversion",
                         _prob_before_inversion, best_probability,
                         f"side {_pre_inversion_direction} -> {best_direction}: the engine's own "
                         f"side is measured 2.7 points worse than its opposite; probability is now "
                         f"{best_direction}'s own")
            directional_veto_info["chosen_direction_was_vetoed"] = (
                (best_direction == "BUY" and buy_vetoed) or (best_direction == "SELL" and sell_vetoed))
            logger.warning(
                f"[DIRECTION INVERTED] {symbol}: analysis chose {_pre_inversion_direction}, "
                f"trading {best_direction} (measured: the opposite side wins 32.0% vs 29.2%)")

        if _cascade_side is not None:
            # The veto record was written for the analysis's side. After the
            # flip it must describe the side actually traded, or coherence
            # reports "vetoed direction chosen" for a side that was not traded
            # (and, now that conviction enforces, blocks the trade for it).
            directional_veto_info["chosen_direction_was_vetoed"] = (
                (best_direction == "BUY" and buy_vetoed) or (best_direction == "SELL" and sell_vetoed))
            # An ICT pre-flight veto on the side the cascade chose is overruled,
            # not enforced. Measured on the price-history study (35,735 bars,
            # 13 symbols): cascade flips onto an ICT-vetoed side were right
            # 49.0% vs 50.7% when ICT agreed (5-ATR), and 51.1% vs 49.5% at
            # 2x H1 ATR -- the ICT opposition carries no information either
            # way, while enforcing it (via coherence -> conviction) blocked a
            # third of all bars.
            _traded_veto = directional_veto_info["buy_veto"] if best_direction == "BUY" else directional_veto_info["sell_veto"]
            if directional_veto_info["chosen_direction_was_vetoed"] and str(_traded_veto or "").startswith("ICT_"):
                directional_veto_info["chosen_direction_was_vetoed"] = False
                directional_veto_info["veto_overruled_by_trend_cascade"] = _traded_veto
        direction_decision = {
            "analysis_direction": analysis_direction,
            "traded_direction": best_direction,
            "flipped_by_trend_cascade": _cascade_side is not None,
            "cascade_direction": trend_cascade_result.get("direction"),
            "cascade_score": trend_cascade_result.get("score"),
            "chosen_direction_was_vetoed": directional_veto_info["chosen_direction_was_vetoed"],
            "veto_overruled_by_trend_cascade": directional_veto_info.get("veto_overruled_by_trend_cascade"),
        }

        # ✅ CONFIRMED (not a bug, but the wording downstream used to
        # suggest otherwise): effective_order_type is the SYSTEM's own
        # computed best_direction -- derived from probability_buy vs
        # probability_sell above -- not the user's raw requested
        # direction from config. Every "perfect setup" evaluation below
        # (SMC, BB, RSI/Stochastic reversal, EMA crossover, Wave C,
        # FVG/IFVG) gates on THIS, so none of them are influenced by what
        # direction the user asked for. Their reason strings used to say
        # "conflicts with requested order_type", which reads exactly like
        # a user-input dependency even though the logic never had one --
        # fixed to say "the system's own measured best direction" instead.
        effective_order_type = best_direction
        
        # ============================================================
        # POSITION SIZING
        # ============================================================
        # The stop must clear the market's own noise, not just the cost of
        # entry. calculate_lot_proper() applies a spread-based floor of its
        # own, but on a near-zero-spread instrument that collapses to the
        # 1-pip absolute minimum -- a stop ordinary EURUSD tick noise
        # removes before the setup can be right or wrong. ATR is the
        # instrument's own statement of what "ordinary" currently means, so
        # it is the honest second floor, and min_stop_pips_override is the
        # parameter that already exists to carry it.
        _atr_stop_floor = (atr_pips * SL_MIN_ATR_MULTIPLE
                           if atr_pips and atr_pips > 0 else None)

        # ---- why the stop is NOT derived from structure ----------
        # The stop here comes from calculate_lot_proper() as
        # `target_risk / pip_value_per_pip` -- account arithmetic, with
        # no reference to the chart. That is genuinely the wrong shape,
        # and a structural stop (swing low for a long, zone far side)
        # was built, wired and measured. It made things WORSE and was
        # reverted. The numbers, on 8296 EURUSD M1 decisions:
        #
        #     account stop  5.9p  ->  -0.0870R
        #     zone-derived        ->  -0.0915R
        #
        # The reason is scale, not principle. EURUSD M1 ATR is 0.90 pips
        # against a 0.60 pip spread, so structure on this timeframe is
        # FINER than the cost of entry:
        #
        #     stop at 1x ATR (0.9p)   spread = 67% of risk
        #     stop at 2x ATR (1.8p)   spread = 33% of risk
        #     the account stop 5.9p   spread = 10% of risk
        #
        # The account stop is accidentally better -- not because it is
        # correct, but because it is wide enough to dilute the spread.
        # A structural stop is the right idea on a timeframe where a
        # swing is many spreads away; on M1 majors it is not.
        #
        # Do not re-add this without re-measuring: the principle is
        # sound and the arithmetic still says no.
        lot_result = calculate_lot_proper(
            symbol, fixed_trade_size_usd, risk_per_trade, leverage,
            effective_order_type, min_stop_pips_override=_atr_stop_floor)
        
        if lot_result.get("success", False) and "data" in lot_result:
            lot_data = lot_result["data"]
            calculated_sl_pips = lot_data.get("stop_loss_pips", 5.0)
            calculated_sl_price = lot_data.get("stop_loss_price", 0)
            lot_size = lot_data.get("lot", 0.01)
            actual_risk = lot_data.get("actual_risk", 0)
            margin_required = lot_data.get("margin_required", 0)
            target_risk = lot_data.get("target_risk", 10.0)
            target_margin = lot_data.get("target_margin", 200.0)

            # Stage 10: regret-minimising exposure. Scales the lot that
            # was just sized from the stop distance -- it can only ever
            # make a position SMALLER, never larger, and it forecasts
            # nothing. It just stops betting the same amount on a
            # strategy that has stopped paying.
            #
            # Applied to this project's own 36 recorded trades it turned
            # -9.0R into -2.94R and cut max drawdown from 14.0R to 3.4R.
            # OFF by default: it changes live position sizing, which is
            # the operator's call, not a default.
            if USE_ONLINE_SIZING:
                try:
                    from core.online_sizing import OnlineSizer
                    _sizer = OnlineSizer.load()
                    _mult = _sizer.multiplier()
                    _before = lot_size
                    _scaled = math.floor((lot_size * _mult) / 0.01) * 0.01
                    lot_size = round(max(0.01, _scaled), 2)
                    if lot_size != _before:
                        logger.info(
                            f"[SIZING] {symbol}: lot {_before} -> {lot_size} "
                            f"(x{_mult:.2f} from {_sizer.n_updates} recorded "
                            f"outcomes, cumulative {_sizer.cumulative_r:+.2f}R)")
                    result_online_sizing = _sizer.as_dict()
                except Exception as e:
                    logger.warning(f"[SIZING] {symbol}: sizer unavailable ({e}) "
                                   f"-- using unscaled lot")
                    result_online_sizing = {"available": False, "error": str(e)}
            else:
                result_online_sizing = {"available": False, "reason": "disabled"}
        else:
            result_online_sizing = {"available": False, "reason": "lot sizing failed"}
            calculated_sl_pips = 5.0
            calculated_sl_price = 0
            lot_size = 0.01
            actual_risk = 10.0
            margin_required = 200.0
            target_risk = 10.0
            target_margin = 200.0
        
        # ============================================================
        # HYBRID TAKE PROFIT
        # ============================================================
        zone_level = sd_data.get("zone_level")
        zone_grade = sd_data.get("zone_grade", "E")
        recent_swing_high = sr_data.get("recent_swing_high")
        recent_swing_low = sr_data.get("recent_swing_low")
        
        tp1_pips, tp2_pips, tp3_pips = calculate_hybrid_take_profit(
            symbol=symbol,
            current_price=current_price,
            order_type=effective_order_type,
            pip_size=pip_size,
            atr_pips=atr_pips,
            spread_pips=spread,
            sl_pips=calculated_sl_pips,
            zone_level=zone_level,
            zone_grade=zone_grade,
            recent_swing_high=recent_swing_high,
            recent_swing_low=recent_swing_low,
            timeframe=timeframe
        )
        
        # MARKET STOP (core/market_stop.py): stop from H1 volatility, target
        # a fixed R multiple of it, lot sized to the dollar risk. Overrides the
        # account stop and the hybrid TP1 so cost, R:R and the published plan
        # all describe the trade that is sent.
        market_stop_plan = None
        if USE_MARKET_STOP:
            try:
                from core.market_stop import plan as _market_stop_plan
                market_stop_plan = _market_stop_plan(symbol, effective_order_type,
                                                     fixed_trade_size_usd * risk_per_trade)
            except Exception as e:
                logger.warning(f"[MARKET STOP] {symbol}: unavailable ({e}) -- account stop kept")
            if market_stop_plan:
                calculated_sl_pips = market_stop_plan["stop_pips"]
                calculated_sl_price = market_stop_plan["stop_price"]
                lot_size = market_stop_plan["lot"]
                actual_risk = market_stop_plan["risk_usd"]
                if market_stop_plan.get("margin_usd") is not None:
                    # the old figure belonged to the account-derived lot
                    margin_required = market_stop_plan["margin_usd"]
                tp1_pips = market_stop_plan["target_pips"]
                tp2_pips = max(tp2_pips, tp1_pips + spread + 1)
                tp3_pips = max(tp3_pips, tp2_pips + spread + 1)
                logger.info(f"[MARKET STOP] {symbol} {effective_order_type}: stop {calculated_sl_pips}p "
                            f"target {tp1_pips}p lot {lot_size} risk ${actual_risk} "
                            f"(affordable {market_stop_plan['affordable']})")

        net_profit_pips = tp1_pips - spread
        if net_profit_pips <= 0:
            return {"success": False, "error": f"Cannot profit: TP {tp1_pips:.1f}p - Spread {spread:.1f}p = negative"}
        
        # ============================================================
        # SESSION RESULT
        # ============================================================
        session_result = _get_session_analysis(
            symbol, best_probability, calculated_sl_pips, current_pnl_percent, is_new_entry=True
        )
        
        # ============================================================
        # INDIVIDUAL INDICATOR SCORES - WITH DIVERGENCE IMPACT
        # ============================================================
        
        # ✅ NEW: Volume Profile / POC - own merged result, advisory only
        # (see config comment: not wired into calculate_unified_indicator_
        # score's weighting).
        try:
            volume_profile_data = calculate_volume_profile(
                rates, VOLUME_PROFILE_NUM_BINS, VOLUME_PROFILE_LOOKBACK_BARS, VOLUME_PROFILE_VALUE_AREA_PCT
            )
        except Exception as e:
            logger.warning(f"[VOLUME PROFILE] Calculation failed: {e}")
            volume_profile_data = {"available": False, "reason": f"calculation error: {e}"}
        volume_profile_indicator = score_volume_profile_indicator(volume_profile_data, current_price, pip_size)
        
        # Cross-check the existing (formula-derived) pivot S/R levels
        # against the (volume-derived) POC/VAH/VAL. Feeds back into
        # sr_data's score below (see the adjustment block after
        # order_flow_forensics_data) -- no longer purely advisory.
        try:
            sr_volume_profile_confluence = score_sr_volume_profile_confluence(sr_data, volume_profile_data, pip_size)
        except Exception as e:
            logger.warning(f"[SR/VP CONFLUENCE] Cross-check failed: {e}")
            sr_volume_profile_confluence = {"available": False, "reason": f"error: {e}"}
        
        # ✅ NEW: same cross-check for the active supply/demand zone.
        try:
            sd_volume_profile_confluence = score_sd_volume_profile_confluence(sd_data, volume_profile_data, pip_size)
        except Exception as e:
            logger.warning(f"[SD/VP CONFLUENCE] Cross-check failed: {e}")
            sd_volume_profile_confluence = {"available": False, "reason": f"error: {e}"}
        
        # ✅ NEW: Wyckoff phase cross-check (basing-near-POC for
        # accumulation/distribution, breakout-beyond-value-area for
        # markup/markdown).
        try:
            wyckoff_volume_profile_confluence = score_wyckoff_volume_profile_confluence(
                wyckoff_data, volume_profile_data, current_price, pip_size
            )
        except Exception as e:
            logger.warning(f"[WYCKOFF/VP CONFLUENCE] Cross-check failed: {e}")
            wyckoff_volume_profile_confluence = {"available": False, "reason": f"error: {e}"}
        
        # ✅ NEW: build order-flow forensics here (was previously called
        # inline down in the final result dict, recomputing it there with
        # no way to also cross-check its liquidity pools against volume
        # profile). Computed once, reused both for the confluence check
        # below and for the report entry further down.
        try:
            order_flow_forensics_data = build_order_flow_forensics(
                rates=rates, pip_size=pip_size,
                zone_level=sd_data.get("zone_level"), zone_type=sd_data.get("zone_type"),
                # ✅ a sweep smaller than the spread isn't a liquidity event
                spread_pips=spread, timeframe=timeframe, atr_pips=atr_pips,
            )
        except Exception as e:
            logger.warning(f"[ORDER FLOW FORENSICS] Build failed: {e}")
            order_flow_forensics_data = {"stop_hunts": [], "liquidity_pools": {"available": False}, "order_block_mitigation": {"available": False}}

        # ✅ NEW: gap/slippage report moved up here (was previously built
        # inline, far below, inside the final result dict) -- computed
        # once, reused both for the probability-chain penalty below and
        # for the report entry in the output further down, same pattern
        # already applied to order_flow_forensics_data just above.
        try:
            gap_slippage_report = build_gap_slippage_report(
                rates=rates,
                pip_size=pip_size,
                spread_pips=spread,
                max_allowed_spread=max_allowed_spread,
                atr_pips=atr_pips,
                extreme_volatility_threshold_pips=EXTREME_VOLATILITY_VETO_THRESHOLD,
                volume_ratio=volume_ratio,
                is_market_open=session_result.get("is_market_open", True),
                minutes_to_close=session_result.get("minutes_to_close"),
            )
        except Exception as e:
            logger.warning(f"[GAP/SLIPPAGE] Build failed: {e}")
            gap_slippage_report = {"gap": {"available": False}, "slippage": {"risk_level": "NORMAL", "is_high_risk": False, "risk_factors": []}, "recommendation": {"avoid_trade_recommended": False, "should_exit_recommended": False, "reasons": []}}

        # ✅ NEW (per explicit request): volume-profile confluence and
        # order-block mitigation status used to be purely advisory --
        # computed, displayed, explicitly documented as never touching
        # sr_data/sd_data's own score. They now do, in a modest, capped
        # way, rather than being informative-but-inert:
        #
        # - support_resistance: each pivot level with real transacted-
        #   volume backing (POC/VAH/VAL nearby) adds a small amount of
        #   confidence, scaled by how many of the 7 levels are confirmed
        #   -- a pivot grid that's mostly empirical noise vs. one where
        #   most levels line up with where volume actually traded are not
        #   equally trustworthy, and previously scored identically.
        #
        # - supply_demand: the SAME zone gets checked two ways that
        #   were both already being computed for this exact zone_level
        #   and simply never fed back: (1) volume-profile confirmation
        #   (POC/VAH/VAL nearby the zone), and (2) order_block_mitigation
        #   status (VIRGIN/FIRST_TOUCH = fresh, orders likely still
        #   resting; LIKELY_EXHAUSTED = visited 4+ times, orders likely
        #   already consumed). A zone graded identically by touch-count
        #   alone but backed by real volume AND still fresh is a
        #   meaningfully better zone than one that's neither -- and a
        #   zone that's LIKELY_EXHAUSTED is a meaningfully worse one,
        #   which nothing previously captured at the score level at all.
        #
        # Deliberately bounded and NOT touching zone_grade (the A-E gate
        # that determines trade eligibility) -- that's a much
        # higher-stakes threshold than the continuous score, and
        # recalibrating it isn't something to do without real backtest
        # data. These point values are reasoned defaults, not calibrated
        # ones -- treat them as a starting point to tune, not a final
        # answer.
        if sr_volume_profile_confluence.get("available") and sr_data.get("score") is not None:
            total_checked = sr_volume_profile_confluence.get("total_levels_checked", 0)
            confirmed = sr_volume_profile_confluence.get("confirmed_count", 0)
            if total_checked > 0:
                sr_vp_boost = round(10.0 * (confirmed / total_checked), 1)
                sr_data["score"] = max(0, min(100, sr_data.get("score", 0) + sr_vp_boost))
                sr_data["volume_profile_score_adjustment"] = sr_vp_boost

        if sd_data.get("score") is not None:
            sd_score_adjustment = 0.0
            if sd_volume_profile_confluence.get("available") and sd_volume_profile_confluence.get("volume_confirmed"):
                sd_score_adjustment += 8.0
            ob_status = order_flow_forensics_data.get("order_block_mitigation", {}).get("status")
            if ob_status == "VIRGIN":
                sd_score_adjustment += 7.0
            elif ob_status == "FIRST_TOUCH":
                sd_score_adjustment += 3.0
            elif ob_status == "LIKELY_EXHAUSTED":
                sd_score_adjustment -= 10.0
            if sd_score_adjustment != 0.0:
                sd_data["score"] = max(0, min(100, sd_data.get("score", 0) + sd_score_adjustment))
                sd_data["order_flow_score_adjustment"] = sd_score_adjustment
        try:
            order_flow_forensics_data["liquidity_pool_volume_profile_confluence"] = score_liquidity_pools_volume_profile_confluence(
                order_flow_forensics_data.get("liquidity_pools", {}), volume_profile_data, pip_size
            )
        except Exception as e:
            logger.warning(f"[LIQUIDITY POOL/VP CONFLUENCE] Cross-check failed: {e}")
            order_flow_forensics_data["liquidity_pool_volume_profile_confluence"] = {"available": False, "reason": f"error: {e}"}
        
        # RSI with divergence impact: the M1 divergence (above) when there is one --
        # 95 confirmed by a break of structure, 75 awaiting it -- RSI on its own otherwise
        _rds_reading = _rds.score_indicator(rsi_divergence_state)
        rsi_indicator = _rds_reading or score_rsi_indicator_with_divergence(
            indicators_data.get("rsi", {}).get("value", 50),
            best_direction,
            divergence_type="NONE",
            # ✅ was using the generic 70/30 while the probability chain
            # uses get_rsi_thresholds(timeframe) -> 80/20 on M1/M5
            timeframe=timeframe
        )
        
        # Stochastic with divergence impact
        stoch_indicator = score_stochastic_indicator_with_divergence(
            indicators_data.get("stochastic", {}).get("k", 50),
            indicators_data.get("stochastic", {}).get("d", 50),
            divergence_type=stoch_div_type
        )

        # ============================================================
        # ✅ NEW: ADAPTIVE OSCILLATOR BANDS -- computed HERE, not 1600
        # lines downstream in the display block
        # Trend with divergence already applied
        trend_indicator = score_trend_indicator(trend, adx_val)

        avg_price = sum(close_prices[-100:]) / 100 if len(close_prices) >= 100 else close_prices[-1]
        
        # MACD with recovery detection and trend strength
        macd_histogram = indicators_data.get("macd", {}).get("histogram", 0)
        macd_prev_histogram = indicators_data.get("macd", {}).get("prev_histogram", macd_histogram)
        macd_line = indicators_data.get("macd", {}).get("line", 0)
        macd_signal_line = indicators_data.get("macd", {}).get("signal", 0)
        macd_signal_str = indicators_data.get("macd", {}).get("signal_str", "NEUTRAL")
        
        macd_indicator = score_macd_indicator(
            macd_line,
            macd_signal_line,
            macd_histogram,
            avg_price,
            macd_prev_histogram,
            adx_val
        )
        
        bb_indicator = score_bollinger_indicator(
            indicator_price,
            indicators_data.get("bollinger", {}).get("upper", 0),
            indicators_data.get("bollinger", {}).get("middle", 0),
            indicators_data.get("bollinger", {}).get("lower", 0),
            indicators_data.get("bollinger", {}).get("width", 0),
            symbol,
            bandwidth_percentile=(trading_regime or {}).get("bb_bandwidth_percentile"),
        )
        # the last closed bar's own direction: a body of at least half its range
        _vb = rates[-1]
        _vb_range = float(_vb[2]) - float(_vb[3])
        _vb_body = float(_vb[4]) - float(_vb[1])
        _vb_dir = (1 if _vb_body > 0 else -1) if _vb_range > 0 and abs(_vb_body) >= 0.5 * _vb_range else 0
        volume_indicator = score_volume_indicator(volume_ratio, trend, adx_val, bar_direction=_vb_dir)
        
        sd_indicator = score_supply_demand_indicator(
            sd_data.get("zone_grade", "E"),
            sd_data.get("is_at_zone", False),
            sd_data.get("zone_type", ""),
            sd_data.get("score", 0)  
        )
        
        candle_indicator = score_candlestick_indicator(
            candle_data.get("score", 0),
            candle_data.get("candle_type", "unknown")
        )
        
        # ✅ ADDED: expected-value score as a real weighted voice in the
        # consensus (not a separate advisory block). Uses best_probability
        # as computed up to this point -- the H1-alignment bonus is
        # applied slightly later in this function, so this is a small,
        # honest approximation (typically +10/0/-15) rather than the
        # final H1-adjusted probability. Reward basis is TP1 (the nearest,
        # most-likely-to-be-hit target) for a conservative EV estimate
        # rather than an optimistic TP3-based one.
        # ✅ FIXED (defect D-18): EV was CONSUMING best_probability and
        # then WRITING BACK to it. That is a closed loop -- a high
        # probability produces a high EV, which argues for a higher
        # probability, with nothing external validating it.
        #
        # Live proof, XAGUSD 2026-09-01 15:49: probability was 95.0, EV
        # reported "Strong positive EV: +27.2 pips (+0.83R) at 95% win
        # prob" and scored +15 straight back into probability. The 95 it
        # consumed was the CLAMPED ceiling, not a measured value, so the
        # loop was being fed by an artifact.
        #
        # There is a second path: reward_pips=tp1_pips, and tp1_pips is
        # floored at spread*2+1 inside calculate_hybrid_take_profit. So a
        # wider spread inflated EV, which inflated probability -- the
        # spread was making the setup look better.
        #
        # The deeper point is that EV = f(probability, reward, risk)
        # carries NO information the decision doesn't already have.
        # Probability is the thing being computed; risk/reward already
        # has its own hard floor. Adding EV back to probability is
        # double-counting probability against itself.
        #
        # So EV is now a GATE, not evidence: it is computed, reported,
        # and can REJECT a trade whose expectancy is negative -- but it
        # no longer moves the number it was derived from. That is the
        # right home for it, next to the R:R floor, because "is this
        # trade worth taking given the estimate" is a different question
        # from "what is the estimate".
        #
        # EXPECTED_VALUE_FEEDS_PROBABILITY=True restores the old
        # behaviour for A/B comparison.
        ev_result = score_expected_value(
            p_win_pct=best_probability,
            reward_pips=tp1_pips,
            risk_pips=calculated_sl_pips,
            spread_pips=spread,
            best_direction=best_direction
        )

        if ev_result.get("score"):
            if EXPECTED_VALUE_FEEDS_PROBABILITY:
                _prob_before = best_probability
                _prob_intended = best_probability + ev_result["score"]
                best_probability = max(5.0, min(95.0, _prob_intended))
                _ledger_step(probability_ledger, "expected_value", _prob_before, best_probability, f"EV score {ev_result['score']:+.1f}", intended=_prob_intended)
            else:
                # Recorded as a no-op step so the ledger still shows that
                # the check RAN and declined to act -- which is different
                # from the check not existing.
                _ledger_step(
                    probability_ledger, "expected_value",
                    best_probability, best_probability,
                    f"EV score {ev_result['score']:+.1f} recorded but NOT fed back "
                    f"(gate only -- see defect D-18)"
                )
            if ev_result["score"] < 0:
                logger.info(f"[EXPECTED VALUE] {symbol}: {ev_result['reason']}")

        # ✅ round-number / psychological level S/R -- genuinely
        # independent of swing points, SD zones, or SMC order blocks
        # (see core/round_number_levels.py). recent_closes drawn from
        # the same `rates` array already fetched for this analysis.
        # Surfaced directly in the output (see round_number_levels
        # below) -- no longer fed through calculate_unified_indicator_
        # score(), which has been removed (see note at that former
        # location: it never actually drove best_probability/the real
        # trade decision -- that comes from probability_buy/
        # probability_sell and the additive chain further below -- so
        # it was a parallel, display-only "13-indicators-blended-into-
        # one-number" computation that the decorrelated-family work
        # made more honest but didn't make load-bearing. Individual
        # indicators (trend_indicator, wyckoff_data, sr_data, etc.)
        # are untouched and still feed their own real consumers
        # elsewhere in this function).
        try:
            recent_closes_for_rn = [float(r[4]) for r in rates[-5:]] if rates is not None and len(rates) >= 2 else None
            round_number_result = analyze_round_number_levels(
                current_price, pip_size, recent_closes=recent_closes_for_rn,
                # 5 fixed pips was 5 ATR on a 1-pip-ATR currency pair (2026-09-15)
                proximity_pips=atr_relative_pips(5.0, atr_pips, 0.25))
        except Exception as e:
            logger.warning(f"[ROUND NUMBERS] {symbol}: failed: {e}")
            round_number_result = {"available": False, "recommendation": "NEUTRAL", "score": 0, "reason": f"error: {e}"}

        # ============================================================
        # ✅ NEW: RETEST-OVER-FIRST-TOUCH -- round_number_result's own
        # fresh_major_breakout read (see core/round_number_levels.py)
        # fires the moment price crosses a round level, which is
        # exactly the "buy the initial break" pattern this is meant to
        # avoid. Using the FULL rates history (not just the last 5
        # closes round_number_result itself sees), check whether that
        # break has actually been retested and held yet -- if not,
        # downgrade the fresh-breakout signal to NEUTRAL rather than
        # trading the untested break. See core/retest_confirmation.py.
        # ============================================================
        retest_result = {"available": False, "confirmed": False, "phase": "NOT_APPLICABLE", "reason": "no fresh breakout to retest"}
        if round_number_result.get("fresh_major_breakout"):
            try:
                breakout = round_number_result["fresh_major_breakout"]
                retest_result = check_retest_confirmation(
                    rates, breakout["level"], breakout["direction"], pip_size,
                    # ✅ break/retest bands scale with the instrument
                    atr_pips=atr_pips
                )
            except Exception as e:
                logger.warning(f"[RETEST] {symbol}: failed: {e}")
                retest_result = {"available": False, "confirmed": False, "phase": "ERROR", "reason": f"error: {e}"}

            if not retest_result.get("confirmed"):
                logger.info(
                    f"[RETEST] {symbol}: fresh round-number breakout downgraded to NEUTRAL "
                    f"({retest_result.get('phase')}) -- {retest_result.get('reason')}"
                )
                round_number_result = dict(round_number_result)
                round_number_result["recommendation"] = "NEUTRAL"
                round_number_result["score"] = 0
                # ✅ FIXED: `confidence` was left at its pre-downgrade value
                # (70 for a fresh breakout), so a signal zeroed out right
                # here still advertised 70% confidence downstream -- both in
                # the report and, now, to family voting, which reads
                # `confidence` as vote strength. Zeroed alongside score so
                # the three fields can't tell three different stories.
                round_number_result["confidence"] = 0
                round_number_result["reason"] = (
                    f"Fresh major breakout not yet retest-confirmed ({retest_result.get('phase')}) -- "
                    f"{retest_result.get('reason')}"
                )

        # ✅ NEW: standalone Fibonacci confluence -- checks the current
        # price against retracement/extension levels of the most recent
        # swing leg, independent of whether Elliott Wave found a
        # confirmed wave count. See core/fib_confluence.py.
        try:
            fib_confluence_result = check_fib_confluence(indicator_price, rates, pip_size, timeframe=timeframe, atr_pips=atr_pips)
        except Exception as e:
            logger.warning(f"[FIB CONFLUENCE] {symbol}: failed: {e}")
            fib_confluence_result = {"available": False, "confluent": False, "recommendation": "NEUTRAL", "score": 0, "reason": f"error: {e}"}
        
        # ============================================================
        # H1 ALIGNMENT - DEFINE BEFORE USING
        # ============================================================
        h1_aligned = False
        h1_confidence_bonus = 0
        
        if best_direction == "BUY" and h1_trend == "BULLISH":
            h1_aligned = True
            h1_confidence_bonus = 10
        elif best_direction == "SELL" and h1_trend == "BEARISH":
            h1_aligned = True
            h1_confidence_bonus = 10
        elif h1_trend == "NEUTRAL":
            h1_aligned = True
            h1_confidence_bonus = 0
        else:
            h1_aligned = False
            h1_confidence_bonus = -15
        
        # Apply H1 bonus to probability

        # ✅ FIXED: this step was only recorded when it ACTED, which breaks
        # the ledger's own contract -- "steps that move nothing are still
        # recorded: 'this check ran and declined to act' is different from
        # 'this check did not run'". Measured on 215 real trades: h1_alignment appeared on only 100 of them.
        # A reader (and every diagnostic built on the ledger, including the
        # component audit) could not tell a silent check from an absent one,
        # and a component that appears on 8 of 215 trades looks like it fired
        # 100% of the time when it actually declined 207 times.
        _prob_before = best_probability
        if h1_confidence_bonus != 0:
            _prob_intended = best_probability + h1_confidence_bonus
            best_probability = max(5.0, min(95.0, _prob_intended))
            _ledger_step(probability_ledger, "h1_alignment", _prob_before, best_probability, f"H1 bonus {h1_confidence_bonus:+.1f}", intended=_prob_intended)
        else:
            _ledger_step(probability_ledger, "h1_alignment", _prob_before,
                         best_probability, "H1 bonus 0.0 (no alignment effect)")

        # ============================================================
        # ✅ NEW: MULTI-DEGREE TREND CASCADE (M5/M15/H1/H4 EMA-slope
        # alignment) -- applied at the same point as the H1-alignment
        # bonus just above, so a decisive cascade can actually help a
        # borderline setup clear analyze_entry()'s probability threshold
        # (or keep a cascade-opposed setup from clearing it), not just
        # change the reported number after the entry decision is locked
        # in. See core/trend_cascade.py for the full design notes.
        # ============================================================
        # trend_cascade_result was read once, before sizing, where it decided
        # the side (see "TREND CASCADE DECIDES THE SIDE"). Re-fetching here
        # could read a newer bar and disagree with the side already traded.
        trend_cascade_final = calculate_trend_cascade_final_score(
            trend_cascade_result, best_probability, best_direction=best_direction
        )
        _prob_before = best_probability
        best_probability = trend_cascade_final["final_score"]
        _ledger_step(probability_ledger, "trend_cascade", _prob_before, best_probability, trend_cascade_final.get("reason",""))

        # The exhaustion/climax ENTRY filter was deleted on 2026-09-15: over
        # 110,603 study snapshots it moved the probability on 0.1% of them,
        # and the direction it favoured won 36% (against 51% for the side it
        # pushed away from). The same detector still runs on OPEN positions
        # in the is_already_in_trade branch below.

        # ============================================================
        # ✅ NEW: AVERAGE DAILY RANGE (ADR) EXHAUSTION CHECK -- once most
        # of today's typical range is already used, a trade extending
        # today's already-established move has statistically worse odds
        # (continuation/breakout), while a trade fading it has better
        # odds (mean-reversion). See core/adr_exhaustion.py.
        # ============================================================
        try:
            if M1_ONLY:
                adr_result = {"available": False, "exhausted": False, "reason": "M1_ONLY: not read (D1 range)"}
            else:
                adr_result = get_adr_exhaustion(symbol, pip_size, current_price)
        except Exception as e:
            logger.warning(f"[ADR EXHAUSTION] {symbol}: failed: {e}")
            adr_result = {"available": False, "exhausted": False, "reason": f"error: {e}"}

        adr_exhaustion_final = calculate_adr_exhaustion_final_score(
            adr_result, best_probability, best_direction=best_direction
        )
        _prob_before = best_probability
        best_probability = adr_exhaustion_final["final_score"]
        _ledger_step(probability_ledger, "adr_exhaustion", _prob_before, best_probability, adr_exhaustion_final.get("reason",""))
        if adr_exhaustion_final.get("signal") in ("CONTINUATION_PENALIZED", "FADE_PENALIZED"):
            logger.warning(f"[ADR EXHAUSTION] {symbol}: {adr_exhaustion_final['reason']}")

        # The DXY cross-check and the nested-zone requirement were deleted on
        # 2026-09-15. DXY never once changed the probability (0 non-zero
        # adjustments in 110,603 snapshots -- it is disabled unless
        # DXY_CONFLUENCE_ENABLED is set); the nested-zone check fired on 3.9%
        # and the side it favoured won 42.9% against a 41.8% baseline.

        # Family voting was removed on 2026-09-15: it averaged the same
        # indicators the probability already scores, and on the stored trades
        # its momentum/volume/structure/pattern votes showed no lift.

        # ============================================================
        # VWAP -- value weighted by where business actually got done
        # ============================================================
        # Bollinger, EMAs and pivots are all price-only. Volume profile
        # is the closest existing analogue but it is a static histogram
        # with no session anchor and no dispersion bands.
        #
        # Anchored to the most recent liquidity sweep when one exists:
        # that gives the average price paid by everyone who has traded
        # since the trap, which is the level they will defend or abandon.
        # NOTE: smc_result is not built until ~440 lines below this
        # point, so reading the sweep from it here would resolve to
        # None on every bar and the anchored VWAP would silently never
        # exist. Calling the canonical engine directly is both correct
        # and cheap -- and it is the SAME engine SMC and order flow
        # now read, so all three anchor to one definition of a sweep.
        # Initialised first: the output reads it, and an exception inside the
        # try below used to leave it undefined (NameError at output time).
        _liq_events = None
        try:
            _anchor = None
            _liq_events = detect_liquidity_events(
                rates, pip_size, timeframe, atr_pips=atr_pips, spread_pips=spread
            )
            if _liq_events:
                _anchor = max(_liq_events, key=lambda e: e["strength"])["bar_index"]
            vwap_result = calculate_vwap(rates, indicator_price, pip_size, anchor_index=_anchor)
            vwap_context = score_vwap_context(
                vwap_result, best_direction,
                regime=(trading_regime or {}).get("state"),
            )
        except Exception as e:
            logger.warning(f"[VWAP] {symbol}: failed: {e}")
            vwap_result = {"available": False, "reason": f"error: {e}"}
            vwap_context = {"score": 0, "stance": None, "reason": f"error: {e}"}


        # ✅ FIXED: this step was only recorded when it ACTED, which breaks
        # the ledger's own contract -- "steps that move nothing are still
        # recorded: 'this check ran and declined to act' is different from
        # 'this check did not run'". Measured on 215 real trades: vwap_context appeared on only 112 of them.
        # A reader (and every diagnostic built on the ledger, including the
        # component audit) could not tell a silent check from an absent one,
        # and a component that appears on 8 of 215 trades looks like it fired
        # 100% of the time when it actually declined 207 times.
        _prob_before = best_probability
        if vwap_context.get("score"):
            _prob_intended = best_probability + vwap_context["score"]
            best_probability = max(5.0, min(95.0, _prob_intended))
            _ledger_step(probability_ledger, "vwap_context", _prob_before,
                         best_probability, vwap_context.get("reason", ""), intended=_prob_intended)
        else:
            _ledger_step(probability_ledger, "vwap_context", _prob_before,
                         best_probability,
                         vwap_context.get("reason") or "no VWAP stance")
        if vwap_context.get("score"):
            if vwap_context["score"] < 0:
                logger.warning(f"[VWAP] {symbol}: {vwap_context['reason']}")

        # ============================================================
        # LIQUIDITY SWEEPS -- which side's stops were just taken
        # ============================================================
        # The sweep bias was computed and shown but never moved probability.
        # It is one of the few readings that measurably separates good
        # entries from bad ones (see core/liquidity_events.py), so it is now
        # a step in the chain. Recorded even when it declines to act.
        liquidity_summary = (summarize_liquidity(_liq_events, best_direction)
                             if isinstance(_liq_events, list) else {"available": False})
        liquidity_final = calculate_liquidity_final_score(liquidity_summary, best_probability, best_direction)
        _prob_before = best_probability
        best_probability = liquidity_final["final_score"]
        _ledger_step(probability_ledger, "liquidity_sweeps", _prob_before, best_probability,
                     liquidity_final.get("reason", ""), intended=liquidity_final.get("intended"))

        # ============================================================
        # RVAM -- did participation match the movement?
        # ============================================================
        # Every other check in this chain reads price OR volume. None
        # compares them, so a 40-pip break on a dead tape and the same
        # break on triple volume score identically -- and the first is
        # where fake breakouts come from.
        #
        # Placed here, last in the pre-entry chain, because it is a
        # CONFIRMATION rather than a directional read: it judges the move
        # the rest of the chain has already decided to act on.
        try:
            rvam_result = calculate_rvam(rates, volume_ratio)
            # A break of structure or a round-number break is exactly the
            # case where thin participation matters most, so the harsher
            # penalty applies there.
            _is_breakout = bool(
                (sr_data or {}).get("breakout")
                or (round_number_result or {}).get("fresh_major_breakout")
            )
            rvam_confirmation = score_rvam_confirmation(
                rvam_result, best_direction, is_breakout=_is_breakout
            )
        except Exception as e:
            logger.warning(f"[RVAM] {symbol}: failed: {e}")
            rvam_result = {"available": False, "reason": f"error: {e}", "classification": "UNKNOWN"}
            rvam_confirmation = {"confirms": None, "score": 0, "reason": f"error: {e}"}

        rvam_final = calculate_rvam_final_score(rvam_confirmation, best_probability)
        _prob_before = best_probability
        best_probability = rvam_final["final_score"]
        _ledger_step(probability_ledger, "rvam", _prob_before, best_probability, rvam_final.get("reason",""))
        if rvam_result.get("classification") in ("UNPARTICIPATED", "ABSORPTION"):
            logger.warning(f"[RVAM] {symbol}: {rvam_result['classification']} -- {rvam_final['reason']}")

        # ============================================================
        # TTM SQUEEZE -- compression as a SETUP, not a volatility label
        # ============================================================
        # get_bb_squeeze_threshold() compares Bollinger bandwidth to a
        # fixed number. That answers "is volatility low" and nothing more
        # -- no duration, no release event, no direction -- so a squeeze
        # could only ever tilt indicator weights. It could not be traded.
        #
        # Placed after RVAM deliberately: the release is only tradeable
        # if participation showed up, and RVAM already answers that. A
        # squeeze releasing on thin volume is the textbook failed
        # breakout.
        try:
            squeeze_result = detect_ttm_squeeze(rates)
            squeeze_setup = score_squeeze_setup(squeeze_result, best_direction, rvam_result)
        except Exception as e:
            logger.warning(f"[SQUEEZE] {symbol}: failed: {e}")
            squeeze_result = {"available": False, "state": "UNKNOWN", "reason": f"error: {e}"}
            squeeze_setup = {"score": 0, "setup": None, "reason": f"error: {e}"}


        # ✅ FIXED: this step was only recorded when it ACTED, which breaks
        # the ledger's own contract -- "steps that move nothing are still
        # recorded: 'this check ran and declined to act' is different from
        # 'this check did not run'". Measured on 215 real trades: ttm_squeeze appeared on only 8 of them.
        # A reader (and every diagnostic built on the ledger, including the
        # component audit) could not tell a silent check from an absent one,
        # and a component that appears on 8 of 215 trades looks like it fired
        # 100% of the time when it actually declined 207 times.
        _prob_before = best_probability
        if squeeze_setup.get("score"):
            _prob_intended = best_probability + squeeze_setup["score"]
            best_probability = max(5.0, min(95.0, _prob_intended))
            _ledger_step(probability_ledger, "ttm_squeeze", _prob_before,
                         best_probability, squeeze_setup.get("reason", ""), intended=_prob_intended)
            logger.info(f"[SQUEEZE] {symbol}: {squeeze_setup['reason']}")
        else:
            _ledger_step(probability_ledger, "ttm_squeeze", _prob_before,
                         best_probability,
                         squeeze_setup.get("reason") or "no squeeze setup")

        # ============================================================
        # ENTRY DECISION ENGINE - ✅ FIXED: ALWAYS USE entry_result
        # ============================================================
        
        # ============================================================
        # MOVED (Phase 2, defects D-01 + D-02)
        # ============================================================
        # This whole chain -- GNN, pattern, SMC, FVG/IFVG, order flow,
        # gap/slippage -- used to run AFTER analyze_entry(). Two
        # consequences, both recorded in the Phase 1 audit:
        #
        #   D-01: the entry gate read best_probability BEFORE these six
        #   stages moved it, so the probability the gate decided on was
        #   not the probability the system published. The note left at
        #   the old location documents a live case: the gate checked 9.5
        #   against a threshold of 75 while the headline read 27.1%.
        #
        #   D-02: because the only post-entry enforcement was a
        #   monotone-downgrade floor, these six could REJECT a trade but
        #   never QUALIFY one. SMC -- the roadmap's 'core structural
        #   intelligence' -- was in practice a late filter. A setup the
        #   entry gate declined at 70% stayed declined even if SMC and
        #   pattern would have carried it past the floor.
        #
        # Verified safe by static analysis: the block has 45 free
        # variables, every one assigned before the entry gate, and
        # nothing in it reads any output of analyze_entry(). The reverse
        # is not true -- check_all_vetos() takes entry_triggered -- which
        # is why the chain moved up rather than the gate moving down.
        # ============================================================

        # ============================================================
        # GNN ANALYSIS
        # ============================================================
        
        gnn_result = None
        if M1_ONLY:
            logger.info(f"[GNN] Skipped: M1_ONLY: not read (GNN reads H1)")
        elif use_gnn and is_gnn_available():
            try:
                logger.info(f"[GNN] Running GNN analysis for {symbol}")
                gnn_result = analyze_gnn_correlations(symbol, best_direction, trade_id)
                
                if gnn_result and gnn_result.get("available", False):
                    logger.info(f"[GNN] Analysis complete: {len(gnn_result.get('correlations', []))} correlations, {len(gnn_result.get('suggestions', []))} suggestions")
                else:
                    logger.warning(f"[GNN] Analysis returned no data for {symbol}")
            except Exception as e:
                logger.warning(f"[GNN] Analysis failed: {e}")
                gnn_result = {"available": False, "error": str(e)}
        else:
            logger.info(f"[GNN] Skipped: use_gnn={use_gnn}, available={is_gnn_available()}")
        
        # ============================================================
        # PATTERN FINAL SCORE
        # ============================================================
        # ✅ CRITICAL FIX: pattern_final_score used to be computed earlier
        # in the pipeline (right after best_direction/best_probability were
        # chosen) and then never fed back -- best_probability was never
        # reassigned from it, so it only ever reached the output as a
        # "pattern_final_score" display field, exactly the bug already
        # found and fixed for GNN above and mirrored in SMC below. Moved
        # here and chained the same way, so the order is now: base
        # indicators -> pattern adjustment -> GNN adjustment -> SMC
        # adjustment. Computed at this point in the pipeline (after the
        # entry decision, same as GNN/SMC) so -- also like GNN/SMC -- it
        # affects the reported probability_percent and downstream sizing,
        # not entry/no-entry, which was already decided earlier.
        pattern_final_score = calculate_pattern_final_score(pattern_result, base_probability=best_probability, best_direction=best_direction)
        _prob_before = best_probability
        best_probability = pattern_final_score["final_score"]
        _ledger_step(probability_ledger, "pattern", _prob_before, best_probability, _final_score_note(pattern_final_score, "pattern"), intended=_prob_before + (pattern_final_score.get("pattern_contribution") or 0.0))

        gnn_final = calculate_gnn_final_score(gnn_result or {"available": False}, best_probability, best_direction=best_direction)
        
        # ✅ CRITICAL FIX: gnn_final['final_score'] was computed here and
        # then discarded — best_probability was never reassigned from it,
        # so calculate_gnn_final_score()'s entire output (including
        # data-quality dampening, conflict handling, alignment checks)
        # only ever reached Firebase as a "gnn_final_score" display field.
        # It had ZERO effect on probability_percent, entry decisions, or
        # position sizing. Applying it now so the GNN subsystem actually
        # influences trades, not just logs. (Note: this doesn't retroactively
        # let GNN veto a trade — final_decision was already set earlier in
        # this pipeline via the entry engine; this affects the reported/
        # used probability and downstream sizing, not entry/no-entry.)
        _prob_before = best_probability
        best_probability = gnn_final["final_score"]
        _ledger_step(probability_ledger, "gnn", _prob_before, best_probability, _final_score_note(gnn_final, "gnn"), intended=_prob_before + (gnn_final.get("gnn_contribution") or 0.0))
        
        # ============================================================
        # FVG/IFVG (multi-gap, tier-scored, inversion-aware) — computed
        # here, BEFORE SMC, so the same fvg_ifvg_indicator can be passed
        # into analyze_smc_structure() as a genuine confluence signal
        # (see the fix note on analyze_smc_structure itself). The
        # probability-chain adjustment below (fvg_ifvg_final) stays in
        # its documented position in the base -> pattern -> GNN -> SMC ->
        # FVG/IFVG chain — only the raw indicator computation moved up;
        # nothing about that chain order changes. Also still used as-is
        # for display and the setup evaluation further down via the same
        # `all_fvgs`/`fvg_ifvg_indicator` variables, not recomputed.
        # ============================================================
        try:
            all_fvgs = detect_all_fvgs(rates, FVG_ALL_MAX_GAPS, FVG_ALL_LOOKBACK_BARS, FVG_MITIGATION_FULL_THRESHOLD)
        except Exception as e:
            logger.warning(f"[FVG/IFVG] Multi-gap detection failed: {e}")
            all_fvgs = []
        fvg_ifvg_indicator = score_fvg_ifvg_indicator(all_fvgs, indicator_price, pip_size, volume_ratio, atr_pips=atr_pips)

        # ============================================================
        # ✅ NEW: SMC (SMART MONEY CONCEPTS) — applied the same way GNN
        # now correctly is, chained on top so probability_percent reflects
        # base indicators -> GNN adjustment -> SMC adjustment, in order.
        # ============================================================
        try:
            smc_result = analyze_smc_structure(rates, indicator_price, pip_size, symbol, timeframe,
                                           fvg_ifvg=fvg_ifvg_indicator,
                                           atr_pips=atr_pips, spread_pips=spread)
        except Exception as e:
            logger.warning(f"[SMC] Analysis failed: {e}")
            smc_result = {"available": False, "error": str(e)}

        # ============================================================
        # ✅ NEW: HARD DISAGREEMENT FLAG (SMC vs Wyckoff)
        # ============================================================
        # SMC and Wyckoff are independent methods reading the same
        # chart two different ways (order flow/liquidity structure vs
        # accumulation/distribution phase). When they AGREE, that's
        # real corroborating evidence and the normal weighted chain
        # already reflects it. When two genuinely high-conviction reads
        # flatly CONTRADICT each other (SMC elite-confluence BUY,
        # Wyckoff MARKUP_STRONG/MARKDOWN_STRONG-equivalent SELL, or the
        # mirror image) that disagreement is itself information -- and
        # folding it into the same weighted average as everything else
        # would let it get quietly smoothed into a middling score that
        # looks like ordinary uncertainty rather than what it actually
        # is. Surfaced explicitly below (hard_disagreement in the
        # output) regardless of what else fires, plus a real but
        # moderate probability penalty so it can't get averaged away by
        # an otherwise-agreeing chain.
        hard_disagreement = None
        try:
            wyckoff_rec = wyckoff_data.get("recommendation") if wyckoff_data else None
            wyckoff_phase = wyckoff_data.get("phase") if wyckoff_data else None
            # "High conviction" Wyckoff = the phase itself is one of the
            # highest-conviction schematic reads (score=95, see
            # _analyze_wyckoff_component()'s MARKUP_STRONG/
            # MARKDOWN_STRONG/ACCUMULATION_COMPLETE set), not just any
            # non-neutral phase.
            wyckoff_high_conviction = bool(
                wyckoff_data and wyckoff_data.get("score", 0) >= 95 and wyckoff_rec in ("BUY", "SELL")
            )

            smc_rec = smc_result.get("recommendation") if smc_result else None
            smc_confluence_count = smc_result.get("confluence_count", 0) if smc_result else 0
            # "High conviction" SMC = genuinely elite confluence (see
            # SMC_ELITE_MIN_CONFLUENCE), not just a bare-minimum signal
            # that happened to clear SMC_MIN_CONFLUENCE_SCORE.
            smc_high_conviction = bool(
                smc_result and smc_result.get("available", False)
                and smc_confluence_count >= SMC_ELITE_MIN_CONFLUENCE
                and smc_rec in ("BULLISH", "BEARISH")
            )

            if wyckoff_high_conviction and smc_high_conviction:
                smc_direction = "BUY" if smc_rec == "BULLISH" else "SELL"
                if smc_direction != wyckoff_rec:
                    hard_disagreement = {
                        "detected": True,
                        "smc_recommendation": smc_rec,
                        "smc_confluence": f"{smc_confluence_count}/{SMC_TOTAL_POSSIBLE_SIGNALS}",
                        "wyckoff_recommendation": wyckoff_rec,
                        "wyckoff_phase": wyckoff_phase,
                        "probability_penalty": HARD_DISAGREEMENT_PROBABILITY_PENALTY,
                        "message": (
                            f"SMC says {smc_direction} ({smc_confluence_count}/{SMC_TOTAL_POSSIBLE_SIGNALS} elite "
                            f"confluence) but Wyckoff phase reads {wyckoff_phase} ({wyckoff_rec}) -- two "
                            f"independent, high-conviction methods flatly disagree. Treat this as a genuine "
                            f"warning sign, not noise averaged away by the rest of the confluence score."
                        ),
                    }
                    logger.warning(f"[HARD DISAGREEMENT] {symbol}: {hard_disagreement['message']}")
                    _prob_before = best_probability
                    best_probability = max(5.0, best_probability + HARD_DISAGREEMENT_PROBABILITY_PENALTY)
                    _ledger_step(probability_ledger, "hard_disagreement", _prob_before, best_probability, "GNN/SMC hard disagreement")
        except Exception as e:
            logger.warning(f"[HARD DISAGREEMENT] {symbol}: check failed: {e}")
        
        # ✅ NEW: cross-check SMC order blocks against POC/VAH/VAL -
        # advisory only, does not touch evaluate_smc_trade_setup()'s own
        # use of these order blocks for entry/SL.
        try:
            ob_volume_profile_confluence = score_ob_volume_profile_confluence(
                smc_result.get("order_blocks", {}) if smc_result else {}, volume_profile_data, pip_size
            )
        except Exception as e:
            logger.warning(f"[OB/VP CONFLUENCE] Cross-check failed: {e}")
            ob_volume_profile_confluence = {"available": False, "reason": f"error: {e}"}
        
        # ✅ NEW: same cross-check for the detected liquidity sweep.
        try:
            sweep_volume_profile_confluence = score_sweep_volume_profile_confluence(
                smc_result.get("liquidity_sweep", {}) if smc_result else {}, volume_profile_data, pip_size
            )
        except Exception as e:
            logger.warning(f"[SWEEP/VP CONFLUENCE] Cross-check failed: {e}")
            sweep_volume_profile_confluence = {"available": False, "reason": f"error: {e}"}
        
        smc_final = calculate_smc_final_score(smc_result, best_probability, best_direction=best_direction)
        _prob_before = best_probability
        best_probability = smc_final["final_score"]
        _ledger_step(probability_ledger, "smc", _prob_before, best_probability, _final_score_note(smc_final, "smc"), intended=_prob_before + (smc_final.get("smc_contribution") or 0.0))

        # ============================================================
        # ✅ CRITICAL FIX: FVG/IFVG probability-chain adjustment
        # ============================================================
        # score_fvg_ifvg_indicator() has produced a real recommendation +
        # signed score every run (computed above, before SMC, so SMC's
        # own confluence vote could see it too), but it only ever reached
        # the output as a display field (indicators.fvg_ifvg) -- same
        # class of bug already found and fixed for GNN/SMC/pattern above.
        # Applied here, in its documented chain position: base -> pattern
        # -> GNN -> SMC -> FVG/IFVG. Like its siblings, this only affects
        # the reported probability_percent and downstream sizing, not
        # entry/no-entry, which was already decided earlier. Does NOT
        # touch the existing, separately-wired single-nearest-FVG read
        # already feeding calculate_real_probability() via
        # ict_signal_type/price_above_fvg_pips/price_below_fvg_pips --
        # that logic is untouched.
        fvg_ifvg_final = calculate_fvg_ifvg_final_score(fvg_ifvg_indicator, best_probability, best_direction=best_direction)
        _prob_before = best_probability
        best_probability = fvg_ifvg_final["final_score"]
        _ledger_step(probability_ledger, "fvg_ifvg", _prob_before, best_probability, _final_score_note(fvg_ifvg_final, "fvg_ifvg"), intended=_prob_before + (fvg_ifvg_final.get("fvg_ifvg_contribution") or 0.0))

        # ============================================================
        # ✅ NEW: ORDER FLOW (stop hunts / traps, order-block freshness,
        # liquidity-pool draw targets, Wyckoff spring/UTAD confluence) --
        # chained on top the same way pattern/GNN/SMC/FVG-IFVG already
        # are. Previously this entire module's output (order_flow_
        # forensics_data) was computed and displayed but read by nothing
        # -- see the fix note on calculate_order_flow_final_score() in
        # core/order_flow_forensics.py for the full before/after.
        # ============================================================
        order_flow_final = calculate_order_flow_final_score(
            order_flow_forensics_data,
            best_probability,
            best_direction=best_direction,
            current_price=current_price,
            pip_size=pip_size,
            wyckoff_phase=wyckoff_data.get("phase"),
            atr_pips=atr_pips,
        )
        _prob_before = best_probability
        best_probability = order_flow_final["final_score"]
        _ledger_step(probability_ledger, "order_flow", _prob_before, best_probability, _final_score_note(order_flow_final, "order_flow"), intended=_prob_before + (order_flow_final.get("order_flow_contribution") or 0.0))

        # ============================================================
        # ✅ NEW: GAP/SLIPPAGE execution-quality penalty. Deliberately
        # NOT a directional signal like the six chain steps above it --
        # see the fix note on calculate_gap_slippage_final_score() in
        # core/gap_slippage_detector.py for why this only ever subtracts
        # instead of taking an "aligned/opposed" shape. build_gap_
        # slippage_report()'s own avoid_trade_recommended/should_exit_
        # recommended fields remain advisory-only, unchanged, exactly as
        # documented in that module -- this is a separate, additive
        # probability derate, not a second veto path.
        # ============================================================
        gap_slippage_final = calculate_gap_slippage_final_score(gap_slippage_report, best_probability)
        _prob_before = best_probability
        best_probability = gap_slippage_final["final_score"]
        _ledger_step(probability_ledger, "gap_slippage", _prob_before, best_probability, _final_score_note(gap_slippage_final, "gap_slippage"))

        # ✅ The probability the ENTRY DECISION was actually made on.
        #
        # Everything after analyze_entry() -- pattern, GNN, SMC, FVG/IFVG,
        # order flow, gap/slippage -- still moves best_probability, but by
        # design it affects reported probability and position sizing, NOT
        # entry/no-entry (see the note above calculate_pattern_final_score).
        #
        # The output then published the POST-chain number as
        # probability_percent and as the headline CONFIDENCE, while the
        # gate had been decided on this one. Live 14:44: the gate checked
        # 9.5 against a threshold of 75 and blocked; the headline read
        # 27.1%. A reader comparing 27.1 to 75 sees a near-miss that never
        # happened -- the real margin was 65.5 points, not 47.9.
        #
        # ============================================================
        # STRATEGY GROUPS -- each strategy scored alone, best one decides
        # ============================================================
        # The payload below uses the SAME shape the analysis publishes, so
        # core/strategy_groups.py scores a live bar and a stored trade with
        # identical code. See USE_STRATEGY_GROUP_PROBABILITY.
        strategy_groups_result = {"enabled": False}
        # BEHAVIOUR (core/behaviour_readings.py): is the move still moving.
        # Every other reading in this payload is a position reading -- where
        # price sits relative to a level, a band, a mean. Measured on the
        # holdout they were interchangeable (44.2-45.4% right, 100% coverage
        # on some), because thirteen views of "where price is" are one view.
        # This is the other axis, and MEAN_REVERSION now depends on it: a fade
        # only counts once the stretch it fades has stopped extending.
        try:
            from core.behaviour_readings import from_rates as _behaviour_from_rates
            from core.behaviour_readings import minutes_per_bar as _minutes_per_bar
            from core.market_stop import MARKET_STOP_H1_ATR_MULTIPLE as _STOP_ATR_MULT
            # the ATR the stop was actually sized from, so "0.3 ATR" here and
            # the risk geometry are quoted in the same unit
            _behaviour_atr = ((calculated_sl_pips / _STOP_ATR_MULT) * pip_size
                              if market_stop_plan else (atr_pips or 0) * pip_size)
            behaviour_result = _behaviour_from_rates(rates, _behaviour_atr,
                                                     minutes_per_bar=_minutes_per_bar(timeframe))
        except Exception as e:
            logger.warning(f"[BEHAVIOUR] {symbol}: unavailable ({e})")
            behaviour_result = {"available": False, "reason": f"error: {e}"}
        # OU MEAN REVERSION (core/ou_mean_reversion.py): fits the process on H1
        # closes and decides whether a fade is earned -- half-life holdable, the
        # forward PRICE slope significant on non-overlapping windows, price
        # rather than the baseline doing the reverting, and the expected gain
        # beating the round trip. MEAN_REVERSION votes only when this says yes.
        try:
            if M1_ONLY:
                # the process is fitted on H1 closes; nothing trades on it under M1 only
                ou_reversion_result = {"available": False, "reason": "M1_ONLY: not read (OU fitted on H1)"}
            else:
                from core.ou_mean_reversion import live as _ou_live
                ou_reversion_result = _ou_live(symbol, spread_price=(spread or 0) * pip_size)
        except Exception as e:
            logger.warning(f"[OU] {symbol}: unavailable ({e})")
            ou_reversion_result = {"available": False, "reason": f"error: {e}"}
        if ou_reversion_result.get("available") and not ou_reversion_result.get("tradeable"):
            logger.debug(f"[OU] {symbol}: no fade -- {'; '.join(ou_reversion_result.get('why_not') or [])}")
        _sg_payload = None
        if USE_STRATEGY_GROUP_PROBABILITY:
            try:
                _sg_payload = {
                    "behaviour": behaviour_result,
                    "ou_reversion": ou_reversion_result,
                    # broker clock (UTC+3): the rollover hour and the NY
                    # afternoon measure catastrophic on tick data, so the
                    # scorer needs to know what time it is on the broker
                    "clock": {"broker_hour": _broker_hour(rates)},
                    "indicators": {
                        "trend": {"recommendation": trend_data.get("recommendation"),
                                  "confidence": trend_indicator.get("confidence")},
                        "rsi": rsi_indicator,
                        "stochastic": {**stoch_indicator,
                                       "signal": indicators_data.get("stochastic", {}).get("signal")},
                        "macd": {"recommendation": macd_indicator.get("recommendation"),
                                 "confidence": macd_indicator.get("confidence"),
                                 "signal": indicators_data.get("macd", {}).get("signal_str")},
                        "bollinger_bands": bb_indicator,
                        "volume": volume_indicator,
                        "supply_demand": {"recommendation": sd_data.get("recommendation"),
                                          "confidence": sd_indicator.get("confidence")},
                        "support_resistance": {"recommendation": sr_data.get("recommendation")},
                        "fib_confluence": fib_confluence_result,
                        "ict_concepts": {"type": ict_signal_type},
                        "fvg_ifvg": fvg_ifvg_indicator,
                        "volume_profile": volume_profile_indicator,
                        "wyckoff": {"recommendation": wyckoff_data.get("recommendation")},
                        "candlestick": {"recommendation": candle_data.get("recommendation"),
                                        "confidence": candle_indicator.get("confidence")},
                    },
                    "trend_cascade": trend_cascade_result,
                    "volatility_protection": {"trading_regime": trading_regime},
                    # what this trade pays whatever happens: spread + commission
                    "config": {"symbol": symbol},
                    "global_anticheat": {"spread_pips": spread},
                    "entry_details": {"stop_loss_pips": calculated_sl_pips, "take_profit_pips": tp1_pips,
                                      "risk_usd": actual_risk, "lot_size": lot_size},
                    "higher_timeframe": {"trend": h1_trend},
                    "trend_confirmation": {"m1_price_vs_ema200":
                                           "above" if current_price > trend_data.get("ema_200", 0) else "below"},
                    "ttm_squeeze": squeeze_result,
                    "rvam": rvam_result,
                    "vwap": vwap_result,
                    "vwap_context": vwap_context,
                    "smc": {"analysis": smc_result or {}},
                    "liquidity_events": liquidity_summary,
                    "wave_lattice": build_wave_lattice(pattern_result),
                    "pattern_analysis": {"elliott_waves": pattern_result.get("elliott_waves", [])},
                    "gnn": {"analysis": gnn_result or {}},
                    "final_verdict": {
                        "order_flow_final_score": order_flow_final,
                        "pattern_final_score": pattern_final_score,
                        "adr_exhaustion_final_score": adr_exhaustion_final,
                        "gap_slippage_final_score": gap_slippage_final,
                    },
                }
                strategy_groups_result = {"enabled": True,
                                          **score_groups(_sg_payload, best_direction, only=strategy_selection)}
                # Published, not acted on: the other side's group probability.
                # Letting the groups pick the side did not hold across both
                # halves of the stored entries (flips 46% then 70% right), so
                # it is recorded for re-measurement on live trades instead.
                _other_side = "SELL" if best_direction == "BUY" else "BUY"
                strategy_groups_result["other_side"] = {
                    "direction": _other_side,
                    "final_probability": score_groups(_sg_payload, _other_side,
                                                      only=strategy_selection).get("final_probability"),
                }
            except Exception as e:
                logger.warning(f"[STRATEGY GROUPS] {symbol}: scoring failed, additive chain kept: {e}")
                strategy_groups_result = {"enabled": True, "error": str(e), "final_probability": None}
            if strategy_groups_result.get("final_probability") is not None:
                _prob_before = best_probability
                best_probability = strategy_groups_result["final_probability"]
                _ledger_step(probability_ledger, "strategy_groups", _prob_before, best_probability,
                             strategy_groups_result.get("reason", ""))

            # Calibrated probability: the same payload, scored with weights
            # measured on price history instead of hand-set points. Inert
            # until core/calibrated_model.json is installed.
            if USE_CALIBRATED_PROBABILITY and strategy_groups_result.get("final_probability") is not None                     and load_calibrated_model():
                try:
                    _edges = live_edge_features(symbol, replay=market_data is not None,
                                                extended_m1=getattr(market_data, "edge_m1", None))
                    strategy_groups_result["edges"] = _edges
                    # version 2 scores the assembled result at decision time
                    _calibrated = (None if (load_calibrated_model() or {}).get("version") == 2
                                   else calibrated_score(_sg_payload, best_direction, _edges))
                except Exception as e:
                    logger.warning(f"[CALIBRATED] {symbol}: scoring failed, group score kept: {e}")
                    _calibrated = None
                if _calibrated and _calibrated.get("probability") is not None:
                    _prob_before = best_probability
                    best_probability = _calibrated["probability"]
                    _calibrated["edges"] = _edges
                    strategy_groups_result["calibrated"] = _calibrated
                    _ledger_step(probability_ledger, "calibrated_model", _prob_before, best_probability,
                                 f"calibrated P({best_direction}) {best_probability:.1f}% "
                                 f"(model prefers {_calibrated['preferred_direction']} "
                                 f"{_calibrated['preferred_probability']:.1f}%)")

        # ============================================================
        # STRATEGY SETUPS -- evaluated BEFORE the entry decision
        # ============================================================
        # Each strategy group's own trade setup (entry, structural stop, target,
        # the $200 lot shrunk to the $4 budget). The winning group trades its
        # setup: the entry rule table's "setup" rule decides for groups that have
        # one (core/strategy_setups.py). Until 2026-09-17 these ran after the
        # decision and were advisory only.
        # ✅ NEW: precise market-order SL/TP suggestion from SMC structure
        # only, reconciled against the real margin-safe lot ceiling
        # (lot_size, already computed above via calculate_lot_proper()
        # with real account leverage). Traded when SMC wins the strategy
        # auction (core/strategy_setups.py).
        try:
            smc_trade_setup = evaluate_smc_trade_setup(
                smc_analysis=smc_result,
                symbol=symbol,
                order_type=effective_order_type,
                current_price=current_price,
                pip_size=pip_size,
                spread_pips=spread,
                margin_safe_lot=lot_size,
                target_risk_usd=SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE,
            )
        except Exception as e:
            logger.warning(f"[SMC SETUP] Trade setup evaluation failed: {e}")
            smc_trade_setup = {"is_perfect_setup": False, "reason": f"evaluation error: {e}"}
        
        # ✅ NEW: precise market-order SL/TP suggestion for a Bollinger
        # Band mean-reversion extreme, same contract as the SMC setup
        # above (real structural SL/TP, lot reconciled against the same
        # margin-safe ceiling and $ risk budget). Traded when MEAN_REVERSION
        # wins the strategy auction (core/strategy_setups.py).
        try:
            bb_mean_reversion_setup = evaluate_bb_mean_reversion_setup(
                bollinger_data=indicators_data.get("bollinger", {}),
                symbol=symbol,
                order_type=effective_order_type,
                current_price=current_price,
                pip_size=pip_size,
                spread_pips=spread,
                margin_safe_lot=lot_size,
                target_risk_usd=SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE,
                volume_profile_data=volume_profile_data,
            )
        except Exception as e:
            logger.warning(f"[BB SETUP] Mean-reversion setup evaluation failed: {e}")
            bb_mean_reversion_setup = {"is_perfect_setup": False, "reason": f"evaluation error: {e}"}
        
        # RSI setup: the measured M1 divergence confirmed by a break of structure,
        # stop at the swing, exit at RSI 80/20. No Fibonacci (removed 2026-09-18).
        try:
            rsi_reversal_setup = _rds.setup_from_state(rsi_divergence_state, effective_order_type,
                                                       current_price, symbol)
        except Exception as e:
            logger.warning(f"[RSI SETUP] Reversal setup evaluation failed: {e}")
            rsi_reversal_setup = {"is_perfect_setup": False, "reason": f"evaluation error: {e}"}
        rsi_reversal_setup["divergence_state"] = {k: v for k, v in rsi_divergence_state.items()
                                                  if k in ("status", "side", "rsi_at_swing", "bars_waited",
                                                           "stop_price", "reason")}
        
        # ✅ NEW: Stochastic reversal setup - mirror of the RSI one above,
        # using the stoch_indicator merge already computed above.
        try:
            stoch_reversal_setup = evaluate_stochastic_reversal_setup(
                stoch_indicator=stoch_indicator,
                k_value=indicators_data.get("stochastic", {}).get("k", 50),
                symbol=symbol,
                order_type=effective_order_type,
                current_price=current_price,
                pip_size=pip_size,
                spread_pips=spread,
                margin_safe_lot=lot_size,
                recent_swing_high=recent_swing_high,
                recent_swing_low=recent_swing_low,
                target_risk_usd=SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE,
                volume_profile_data=volume_profile_data,
            )
        except Exception as e:
            logger.warning(f"[STOCH SETUP] Reversal setup evaluation failed: {e}")
            stoch_reversal_setup = {"is_perfect_setup": False, "reason": f"evaluation error: {e}"}
        
        # ✅ NEW: EMA crossover setup - fires only on a fresh fast/slow
        # EMA cross. Unlike the setups above, exit is a signal (opposite
        # re-cross), not a fixed price - see the function docstring.
        try:
            ema_crossover_setup = evaluate_ema_crossover_setup(
                close_prices=close_prices,
                symbol=symbol,
                order_type=effective_order_type,
                current_price=current_price,
                pip_size=pip_size,
                spread_pips=spread,
                atr_pips=atr_pips,
                margin_safe_lot=lot_size,
                target_risk_usd=SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE,
                volume_profile_data=volume_profile_data,
            )
        except Exception as e:
            logger.warning(f"[EMA SETUP] Crossover setup evaluation failed: {e}")
            ema_crossover_setup = {"is_perfect_setup": False, "reason": f"evaluation error: {e}"}
        
        # ✅ NEW: Wave C / A-B-C correction + Fibonacci projection -
        # standalone detector (see function docstrings), scored as its
        # own advisory result, plus a market-order setup gated on the
        # cleanest read (ideal wave B retracement + inside the Fib zone)
        # and the same volume-profile confluence check as the other
        # mean-reversion-style setups.
        try:
            wave_c_data = detect_abc_correction(
                rates,
                WAVE_C_MIN_RETRACEMENT_B,
                WAVE_C_MAX_RETRACEMENT_B,
                WAVE_C_IDEAL_RETRACEMENT_MIN,
                WAVE_C_IDEAL_RETRACEMENT_MAX,
                WAVE_C_FIB_EQUALITY,
                WAVE_C_FIB_EXTENSION,
                timeframe=timeframe,
                pip_size=pip_size,
            )
        except Exception as e:
            logger.warning(f"[WAVE C] A-B-C detection failed: {e}")
            wave_c_data = {"available": False, "reason": f"detection error: {e}"}
        wave_c_indicator = score_wave_c_fibonacci_indicator(wave_c_data, current_price, pip_size)
        try:
            wave_c_reversal_setup = evaluate_wave_c_reversal_setup(
                wave_c_data=wave_c_data,
                wave_c_indicator=wave_c_indicator,
                symbol=symbol,
                order_type=effective_order_type,
                current_price=current_price,
                pip_size=pip_size,
                spread_pips=spread,
                margin_safe_lot=lot_size,
                target_risk_usd=SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE,
                volume_profile_data=volume_profile_data,
            )
        except Exception as e:
            logger.warning(f"[WAVE C SETUP] Reversal setup evaluation failed: {e}")
            wave_c_reversal_setup = {"is_perfect_setup": False, "reason": f"evaluation error: {e}"}
        
        # all_fvgs / fvg_ifvg_indicator already computed above (chained
        # into best_probability alongside pattern/GNN/SMC) -- reused here
        # rather than recomputed, so the setup evaluation below is
        # guaranteed to agree with what actually drove the probability.
        try:
            fvg_ifvg_setup = evaluate_fvg_ifvg_setup(
                fvg_list=all_fvgs,
                fvg_indicator=fvg_ifvg_indicator,
                symbol=symbol,
                order_type=effective_order_type,
                current_price=current_price,
                pip_size=pip_size,
                spread_pips=spread,
                margin_safe_lot=lot_size,
                recent_swing_high=recent_swing_high,
                recent_swing_low=recent_swing_low,
                target_risk_usd=SMC_SETUP_TRADE_SIZE_USD * SMC_SETUP_RISK_PER_TRADE,
                volume_profile_data=volume_profile_data,
            )
        except Exception as e:
            logger.warning(f"[FVG/IFVG SETUP] Setup evaluation failed: {e}")
            fvg_ifvg_setup = {"is_perfect_setup": False, "reason": f"evaluation error: {e}"}
        
        strategy_setup = pick_strategy_setup(
            (strategy_groups_result or {}).get("winner"),
            {"smc_trade": smc_trade_setup, "fvg_ifvg": fvg_ifvg_setup,
             "bb_mean_reversion": bb_mean_reversion_setup, "rsi_reversal": rsi_reversal_setup,
             "stochastic_reversal": stoch_reversal_setup, "ema_crossover": ema_crossover_setup,
             "wave_c": wave_c_reversal_setup},
            best_direction, spread_pips=spread)

        # A valid setup IS the trade, so the probability pays ITS cost. The
        # strategy-group score subtracts a trading-cost term, 100 x cost_r /
        # (1 + target_r) points, read from the trade's stop, target, lot and risk.
        # It was priced on the account trade (a ~1-pip FX stop: cost 0.6-1.3R,
        # 26-41 points at a 1.2R target) even when a setup with a wider
        # structural stop and a smaller lot is what goes out. Re-scored for the
        # same winning group with the setup's geometry; the group ranking is
        # unchanged because the context term applies to every group alike.
        if (strategy_setup.get("valid") and _sg_payload is not None
                and strategy_groups_result.get("final_probability") is not None
                and strategy_groups_result.get("winner")):
            try:
                _setup_risk = float(strategy_setup.get("risk_pips") or 0.0)
                _setup_reward = strategy_setup.get("reward_pips")
                if _setup_reward is None and _setup_risk > 0:
                    # a signal-exit setup takes the analysis's own target: the floor
                    _setup_reward = max(_setup_risk * get_minimum_risk_reward(timeframe) + (spread or 0.0),
                                        (spread or 0.0) * 2 + 1)
                if _setup_risk > 0 and _setup_reward:
                    _setup_payload = dict(_sg_payload, entry_details={
                        "stop_loss_pips": _setup_risk, "take_profit_pips": float(_setup_reward),
                        "risk_usd": strategy_setup.get("projected_risk_usd") or actual_risk,
                        "lot_size": strategy_setup.get("lot_size") or lot_size})
                    _rescored = score_groups(_setup_payload, best_direction,
                                             only=strategy_groups_result["winner"])
                    if _rescored.get("final_probability") is not None:
                        _prob_before = best_probability
                        best_probability = _rescored["final_probability"]
                        strategy_groups_result.update({
                            "final_probability": _rescored["final_probability"],
                            "cost": _rescored.get("cost"),
                            "context": _rescored.get("context"),
                            "context_total": _rescored.get("context_total"),
                            "cost_priced_on": f"strategy_setup:{strategy_setup.get('name')}",
                        })
                        _ledger_step(probability_ledger, "strategy_setup_cost", _prob_before, best_probability,
                                     f"trading cost priced on the {strategy_setup.get('name')} setup "
                                     f"({_setup_risk:.1f}p stop, {float(_setup_reward):.1f}p target)")
            except Exception as e:
                logger.warning(f"[SETUP] {symbol}: could not price the setup's cost ({e}); account cost kept")

        # Captured here so both numbers can be reported for what each is.
        probability_at_decision = best_probability
        # Mark where the entry decision was taken, so the ledger is
        # self-describing: everything up to here gated the trade,
        # everything after only affects reporting and sizing. Without
        # the marker a reader (or an invariant) cannot tell which
        # published probability the ledger should reconcile against.
        _ledger_step(probability_ledger, "ENTRY_DECISION",
                     best_probability, best_probability,
                     "entry gate evaluated at this value")

        # The entry floor for the scale this probability is on: strategy-group
        # scores have their own bar, and an installed calibrated model sets its
        # own. Decided here once and applied once, by the entry rule table
        # (core/entry_engine.py, rule "probability"); nothing after this line
        # re-checks the probability.
        probability_floor = (STRATEGY_GROUP_MIN_PROBABILITY
                             if strategy_groups_result.get("final_probability") is not None
                             else TRADE_PROBABILITY_MINIMUM)
        if strategy_groups_result.get("calibrated"):
            probability_floor = float((load_calibrated_model() or {}).get("entry_floor", probability_floor))

        # The entry rule table evaluates every rule and decides (no manual override).
        entry_result = analyze_entry(
            symbol=symbol,
            best_direction=best_direction,
            current_price=current_price,
            zone_level=sd_data.get("zone_level"),
            zone_type=sd_data.get("zone_type"),
            zone_grade=sd_data.get("zone_grade", "E"),
            candle_data=candle_data,
            volume_spike=volume_spike,
            at_poi=at_poi,
            best_probability=best_probability,
            probability_floor=probability_floor,
            strategy_setup=strategy_setup,
            # momentum rides along as a strength reading of the traded side
            momentum_score=((strategy_groups_result.get("groups") or {}).get("MOMENTUM") or {}).get("score"),
            pip_size=pip_size,
            h1_trend=h1_trend,
            h1_aligned=h1_aligned,
            h1_bonus=h1_confidence_bonus,
            # ✅ discount buffer + thresholds scale with the instrument
            atr_pips=atr_pips,
            # Bar replay has no real tick stream: analyze_micro_structure()
            # always reports unavailable, which pinned timing_ready at
            # False for literally every decision and made it the terminal
            # gate of every replay (see get_entry_decision()'s is_replay
            # docstring in core/entry_engine.py). market_data is only
            # ever injected by replay -- live calls never pass it -- so
            # it's the correct signal for "no real ticks exist here",
            # not a new assumption.
            is_replay=market_data is not None
        )
        
        # Extract ALL values from entry_result (NO manual override!)
        entry_triggered = entry_result.get("should_enter", False)
        entry_reason = entry_result.get("reason", "")
        final_decision = entry_result.get("final_decision", "HOLD")
        simple_action = entry_result.get("simple_action", "HOLD")
        execution = entry_result.get("execution", "DO_NOTHING")
        star_rating = entry_result.get("star_rating", 1)
        stars = entry_result.get("stars", "☆")
        micro_structure = entry_result.get("micro_structure", {})
        # ✅ FIXED: was `entry_result.get("timing_confidence", 50)`. entry_engine.py's
        # early-exit branches (NO_POTENTIAL, INSUFFICIENT_PROBABILITY, WAITING_DISCOUNT,
        # POOR_DISCOUNT, and especially INVALID_ZONE — the branch nearly every symbol
        # was hitting) never included this key, so this default fired constantly and
        # every symbol showed a fake "Entry: 50%" regardless of real timing data.
        # Those branches now populate the key for real (or explicit None for
        # INVALID_ZONE, where timing genuinely isn't computed). timing_confidence can
        # end up None here; downstream display code should show "N/A" in that case
        # rather than coercing it to a number.
        timing_confidence = entry_result.get("timing_confidence")
        # ✅ FIXED: this recomputed timing readiness from timing_confidence
        # against MIN_ENTRY_CONFIDENCE, silently DISCARDING the
        # timing_ready the entry engine had already decided. Two sources
        # of truth for one fact -- and the two thresholds
        # (MIN_ENTRY_CONFIDENCE here, EntryEngine.min_timing_confidence
        # there) are separately maintained, so they agree only by
        # coincidence, both being 75 today.
        #
        # It also silently reverted the engine's replay bypass: in a bar
        # replay the engine correctly rules timing not-applicable (no
        # tick stream exists -- see get_entry_decision()'s is_replay
        # docstring) and returns timing_ready True, but timing_confidence
        # stays at its honest neutral 50, so recomputing here flipped it
        # straight back to False. The reported funnel then showed 0 of 65
        # candidates passing "timing ready" while the engine itself had
        # actually qualified them.
        #
        # The engine's verdict wins where it gave one. The recomputation
        # survives only as the fallback for early-exit branches that
        # never set the key.
        _engine_timing_ready = entry_result.get("timing_ready")
        if _engine_timing_ready is None:
            timing_good = (timing_confidence is not None
                           and timing_confidence >= MIN_ENTRY_CONFIDENCE)
        else:
            timing_good = bool(_engine_timing_ready)

        signals = entry_result.get("signals", {})
        absorption = signals.get("absorption", False)
        momentum_burst = signals.get("momentum_burst", False)
        signal_count = signals.get("signal_count", 0)
        
        discount_info = entry_result.get("discount_info", {})
        confirmation = entry_result.get("confirmation", {"is_confirmed": False, "type": None, "score": 0})
        required_confirmation = entry_result.get("required_confirmation")
        
        # ✅ FIXED: Get entry_quality from entry_result
        entry_quality = entry_result.get("entry_quality", "NO")
        entry_status = entry_result.get("entry_status", "UNKNOWN")
        
        # Build entry_analysis from entry_result (NO manual override)
        entry_analysis = {
            "pre_entry_passed": True,
            "pre_entry_skip_reason": None,
            "should_enter": entry_triggered,
            # The ENTRY ENGINE's own verdict, before any later gate can
            # overturn it. `should_enter` is the live answer and is
            # correctly cleared by the veto and the R:R floor -- which
            # means it can no longer say WHERE a decision died. Keeping
            # the engine's original answer separately is what lets the
            # replay funnel still distinguish "the engine never
            # qualified this" from "the engine qualified it and a later
            # gate refused it". Those call for opposite fixes.
            "engine_qualified": entry_triggered,
            "entry_status": entry_status,
            # The whole entry rule table (core/entry_engine.py): every rule's
            # verdict on this decision, blocking or not, and which ones blocked.
            "rules": entry_result.get("rules"),
            "blocked_by": entry_result.get("blocked_by"),
            "final_decision": final_decision,
            # WHICH STRATEGY THIS DECISION CAME FROM. The group auction already
            # elects a winner and sets the probability the decision is built
            # on, but only the groups block carried its name -- so the final
            # decision said BUY without ever saying what argued for it.
            "strategy": _picked_strategy(strategy_groups_result, ou_reversion_result),
            "simple_action": simple_action,
            "execution": execution,
            "reason": entry_reason,
            "star_rating": star_rating,
            "stars_display": stars,
            "entry_quality": entry_quality,
            "timing_confidence": timing_confidence,
            "timing_ready": timing_good,
            # No default: the engine now stamps this on every exit path.
            # Defaulting to False here is what turned "bypassed on every
            # decision" into "bypassed on 11" in the XAGUSD audit -- the
            # early returns omitted the key and this silently invented a
            # reassuring answer. None means "the engine did not say",
            # which is a question, not a clean bill of health.
            "timing_bypassed_replay": entry_result.get("timing_bypassed_replay"),
            "micro_structure_available": entry_result.get("micro_structure_available"),
            "discount": discount_info,
            "confirmation": confirmation,
            "required_confirmation": required_confirmation,
            "micro_structure": micro_structure,
            "golden_signals": {
                "momentum_burst": momentum_burst,
                "absorption": absorption,
                "volume_spike": volume_spike,
                "at_poi": at_poi,
                # ✅ NEW: breakdown of the fix above -- lets a trader see
                # "price WAS near a zone/FVG, but no displacement candle
                # confirmed it yet" instead of that distinction
                # disappearing into a flat False.
                "at_poi_zone_proximity": at_zone_proximity,
                "at_poi_fvg_proximity": at_fvg_proximity,
                "at_poi_displacement": displacement_detail,
                "signal_count": signal_count,
                "signal_type": signals.get("signal_type", "NO_SIGNAL")
            },
            "h1_alignment": {
                "aligned": h1_aligned,
                "h1_trend": h1_trend,
                "confidence_bonus": h1_confidence_bonus,
                # ✅ FIXED: was hardcoded to `best_probability` directly,
                # discarding entry_result's own field entirely (which, before
                # the entry_engine fix above, would itself have been a
                # double-adjusted number -- now that entry_engine reuses this
                # same h1_bonus instead of re-deriving one, entry_result's
                # adjusted_probability and best_probability are guaranteed
                # equal, so pulling from entry_result is safe and single-
                # sourced). Also now rounded to 1 decimal to match how
                # directional_analysis.buy_probability is displayed --
                # previously the same underlying number showed as both
                # "83.0" and "82.97857142857096" in the same JSON payload.
                "adjusted_probability": round(entry_result.get("adjusted_probability", best_probability), 1)
            }
            # ✅ REMOVED: "indicator_scores" (= unified_score) and
            # "divergence_info" (rsi_m15/stoch_m15) - both were exact
            # duplicates of data that now lives in a single place, the
            # top-level "indicators" section, alongside every other
            # indicator instead of scattered across entry_analysis,
            # indicator_scores, divergence_analysis, m15_divergence,
            # adaptive_oscillators, and components.8_indicators.
        }
        
        # Log entry decision
        if entry_triggered:
            logger.info(f"[ENTRY] ✅ {symbol} - ENTRY SIGNAL: {final_decision} (Entry Quality: {entry_quality})")
        else:
            logger.info(f"[ENTRY] ⏳ {symbol} - {entry_reason} (Status: {entry_status})")
        
        # ============================================================
        # VETO CONDITIONS
        # ============================================================
        
        veto, veto_reason, modified_sl = check_all_vetos(
            symbol=symbol,
            best_direction=best_direction,
            adx_val=trend_data.get("adx_value", 0),
            atr_pips=atr_pips,
            trend=trend,
            current_price=current_price,
            ema_200=trend_data.get("ema_200", 0),
            h1_trend=h1_trend,
            m15_div_score=rsi_div_score,
            m15_rsi=rsi_div_rsi,
            upper_wick_pips=candle_data.get("upper_wick_pips", 0),
            lower_wick_pips=candle_data.get("lower_wick_pips", 0),
            body_pips=candle_data.get("body_pips", 0),
            volume_ratio=volume_ratio,
            spread_valid=spread_valid,
            spread_pips=spread,
            max_allowed_spread=max_allowed_spread,
            entry_triggered=entry_triggered,
            candle_progress_pct=candle_progress * 100,
            is_already_in_trade=is_already_in_trade,
            session_result=session_result,
            news_veto_func=_get_news_veto,
            session_manager=None,
            signal_count=signal_count,
            probability=best_probability,
            volume_spike=volume_spike,
            absorption=absorption,
            # the instrument's own ATR band, so "extreme" is judged per instrument
            atr_band=atr_percentile_band,
        )
        
        if modified_sl and not market_stop_plan:
            calculated_sl_pips = modified_sl
            tp1_pips, tp2_pips, tp3_pips = calculate_hybrid_take_profit(
                symbol=symbol,
                current_price=current_price,
                order_type=effective_order_type,
                pip_size=pip_size,
                atr_pips=atr_pips,
                spread_pips=spread,
                sl_pips=calculated_sl_pips,
                zone_level=zone_level,
                zone_grade=zone_grade,
                recent_swing_high=recent_swing_high,
                recent_swing_low=recent_swing_low,
                timeframe=timeframe
            )
        
        if veto:
            final_decision = f"VETO - {veto_reason}"
            simple_action = "HOLD"
            execution = "DO_NOTHING"
            star_rating = 1
            stars = "☆"
            entry_triggered = False
            # ✅ FIXED: the block above set LOCAL variables only and left
            # `entry_analysis` untouched, so a vetoed trade still carried
            # should_enter=True, simple_action="ENTER NOW" and
            # execution="EXECUTE_MARKET_ORDER" in the dict every
            # downstream consumer actually reads -- decision_snapshot,
            # coherence, the replay recorder, and anything else that asks
            # entry_analysis whether this was an entry.
            #
            # The R:R floor further down has always propagated its
            # rejection this way; the veto, which is the more important
            # gate, did not. The inconsistency was invisible while
            # engine_replay._extract_plan() was separately broken and
            # returned None for everything. Fixing that surfaced it
            # immediately: 37 of 38 recorded "entries" were setups the
            # veto engine had refused, and their outcomes were being
            # counted as the strategy's performance.
            entry_analysis["should_enter"] = False
            entry_analysis["simple_action"] = "HOLD"
            entry_analysis["execution"] = "DO_NOTHING"
            entry_analysis["final_decision"] = final_decision
            entry_analysis["reason"] = final_decision
            entry_analysis["veto_reason"] = veto_reason
            print(f"🛑 [VETO] {veto_reason}")
        
        # ============================================================
        # EXISTING POSITION CHECK
        # ============================================================
        should_close_position = False
        close_position_reason = None
        
        if is_already_in_trade:
            should_close, close_reason = _check_session_close(symbol, best_probability, calculated_sl_pips)
            if should_close:
                should_close_position = True
                close_position_reason = close_reason
                logger.warning(f"[CLOSE POSITION] {symbol}: {close_reason}")
            
            news_exit, news_exit_reason = _get_news_risk(symbol, current_pnl_percent, best_direction)
            if news_exit:
                should_close_position = True
                close_position_reason = news_exit_reason
                logger.warning(f"[CLOSE POSITION] {symbol}: {news_exit_reason}")

            # ✅ NEW: EXHAUSTION/CLIMAX EXIT FILTER (task 3) -- exits a
            # running trend trade when a climax bar (range expansion +
            # volume spike + rejection wick + no follow-through, all
            # four) fires AGAINST the trade's own direction. Uses
            # best_direction as the trade's direction, same precedent
            # the existing news-exit check just above already relies on
            # (this function always recomputes best_direction fresh from
            # current data rather than threading the position's original
            # order_type through, and _get_news_risk() already treats
            # that freshly-computed value as the position's direction).
            try:
                exit_exhaustion_result = detect_exhaustion_climax(rates, pip_size, atr_pips, timeframe=timeframe)
            except Exception as e:
                logger.warning(f"[EXHAUSTION EXIT] {symbol}: detection failed: {e}")
                exit_exhaustion_result = {"is_exhaustion": False}

            exhaustion_exit = calculate_exhaustion_exit_signal(exit_exhaustion_result, best_direction)
            if exhaustion_exit.get("should_exit") and not should_close_position:
                should_close_position = True
                close_position_reason = exhaustion_exit["reason"]
                logger.warning(f"[CLOSE POSITION] {symbol}: {exhaustion_exit['reason']}")
        
        if local_debug:
            logger.info(f"[DECISION] {symbol} {effective_order_type}: {final_decision} (prob={best_probability:.1f}%, timing={timing_confidence}, zone={sd_data.get('is_at_zone', False)})")
        
        # ============================================================
        # STRATEGY SETUP GEOMETRY
        # ============================================================
        # When the winning group's own setup is valid, it IS the trade: its
        # structural stop, its target, and the $200 margin-first lot shrunk so
        # the loss at that stop stays within the $4 budget (never larger than the
        # margin-first lot). Published whether or not a later gate refuses the
        # entry, so every record prices the trade this decision proposed.
        # A setup that exits on a signal (EMA crossover) keeps its stop and takes
        # the analysis's own target against that stop.
        stop_source = "account"
        if strategy_setup.get("valid"):
            _setup_stop = strategy_setup["stop_loss"]
            calculated_sl_price = _setup_stop
            calculated_sl_pips = (strategy_setup.get("risk_pips")
                                  or abs(current_price - _setup_stop) / pip_size)
            if strategy_setup.get("take_profit") is not None:
                tp1_pips = (strategy_setup.get("reward_pips")
                            or abs(strategy_setup["take_profit"] - current_price) / pip_size)
                tp2_pips = max(tp2_pips, tp1_pips + spread + 1)
                tp3_pips = max(tp3_pips, tp2_pips + 5)
            else:
                tp1_pips, tp2_pips, tp3_pips = calculate_hybrid_take_profit(
                    symbol=symbol, current_price=current_price, order_type=effective_order_type,
                    pip_size=pip_size, atr_pips=atr_pips, spread_pips=spread, sl_pips=calculated_sl_pips,
                    zone_level=zone_level, zone_grade=zone_grade, recent_swing_high=recent_swing_high,
                    recent_swing_low=recent_swing_low, timeframe=timeframe)
            if strategy_setup.get("lot_size"):
                lot_size = min(lot_size, strategy_setup["lot_size"])
            if strategy_setup.get("projected_risk_usd"):
                actual_risk = strategy_setup["projected_risk_usd"]
            stop_source = f"strategy_setup:{strategy_setup['name']}"
            # expected value on the geometry actually traded
            ev_result = score_expected_value(
                p_win_pct=best_probability, reward_pips=tp1_pips, risk_pips=calculated_sl_pips,
                spread_pips=spread, best_direction=best_direction)
            logger.info(f"[SETUP] {symbol}: {strategy_setup['group']} trades {strategy_setup['name']} -- "
                        f"stop {calculated_sl_pips:.1f}p, target {tp1_pips:.1f}p, lot {lot_size}")

        # ============================================================
        # FINALIZE LOT SIZE
        # ============================================================
        final_lot_size = lot_size
        
        volume_step = float(info.volume_step) if info.volume_step else 0.01
        volume_min = float(info.volume_min) if info.volume_min else 0.01
        
        if volume_min <= 0:
            volume_min = 0.01
        if volume_step <= 0:
            volume_step = 0.01
        
        if final_lot_size < volume_min:
            final_lot_size = volume_min
        else:
            final_lot_size = round(final_lot_size / volume_step) * volume_step
            final_lot_size = max(volume_min, final_lot_size)
        
        max_lot_by_margin = (free_margin * leverage) / (current_price * 100000) if current_price > 0 else volume_min
        final_lot_size = min(final_lot_size, max_lot_by_margin)
        
        # ✅ FIXED: TP prices for a SELL order were anchored to
        # current_price, which is set once near the top of this function
        # as tick.ask (before BUY vs SELL is even decided) and never
        # adjusted afterward. calculated_sl_price, by contrast, already
        # comes from calculate_lot_proper()'s own internal computation,
        # which correctly uses tick.bid as its reference price for SELL
        # orders (verified directly in calculations.py). That meant a
        # SELL trade's stop-loss and take-profit were being measured
        # from two DIFFERENT reference prices -- off by exactly the
        # spread -- silently skewing the realized R:R for every SELL
        # trade. sell_execution_price mirrors calculate_lot_proper's own
        # BUY-ask/SELL-bid convention using the same tick object already
        # fetched once at the top of this function.
        sell_execution_price = float(tick.bid) if tick is not None and tick.bid else current_price

        # ✅ FIXED (Phase 2, defect D-13): the price PUBLISHED as the entry.
        #
        # SL and TP are both derived from sell_execution_price (the bid) on
        # a SELL, but every entry_price output field published
        # current_price (the ask). The three numbers therefore did not
        # describe one trade.
        #
        # Live proof, XAGUSD 2026-09-01: published entry 64.886 (ask), SL
        # 64.879, TP1 64.765. Computing R:R from those three published
        # numbers gives 7p risk against 121p reward -- 1:17 -- while the
        # engine correctly reported 1:2.47 from the bid (64.846). Anything
        # downstream that recomputed R:R from the output -- a dashboard, a
        # journal, a reviewer sanity-checking a signal -- got a number off
        # by a factor of seven, and it looked BETTER, not worse.
        #
        # Worse for a SELL, the ask sits ABOVE the bid, so the published
        # entry was on the wrong side of its own stop loss.
        execution_entry_price = (
            sell_execution_price if effective_order_type == "SELL" else current_price
        )

        if effective_order_type == "BUY":
            sl_price = calculated_sl_price
            tp1_price = current_price + (tp1_pips * pip_size)
            tp2_price = current_price + (tp2_pips * pip_size)
            tp3_price = current_price + (tp3_pips * pip_size)
        else:
            sl_price = calculated_sl_price
            tp1_price = sell_execution_price - (tp1_pips * pip_size)
            tp2_price = sell_execution_price - (tp2_pips * pip_size)
            tp3_price = sell_execution_price - (tp3_pips * pip_size)
        
        # ✅ FIXED (Phase 2, defect D-03 -- CRITICAL): was
        #     risk_reward_ratio = tp1_pips / calculated_sl_pips if calculated_sl_pips > 0 else 2.0
        #
        # MIN_ABSOLUTE_RISK_REWARD is 2.0 and the floor below tests
        # `risk_reward_ratio < MIN_ABSOLUTE_RISK_REWARD`. 2.0 is not less
        # than 2.0, so a zero, missing or invalid calculated_sl_pips
        # produced exactly the floor value and PASSED the R:R gate. The
        # one number in this pipeline that is a MEASURED fact rather than
        # a model estimate -- the number the comment on that floor
        # explicitly calls "the margin of safety against that estimate
        # being wrong" -- had a failure mode of assuming the requirement
        # was satisfied.
        #
        # rr_result fails closed: when the inputs don't support an R:R,
        # .valid is False and .passes_floor() returns False for ANY
        # floor. risk_reward_ratio is kept as a float for the ~6 existing
        # consumers that expect one (reward_amount_1, the REASON string,
        # two report blocks), but it is now 0.0 rather than 2.0 on
        # failure -- so even a consumer that forgets to check .valid and
        # compares it against a floor gets a rejection instead of a pass.
        #
        # Regression test: tests/test_risk_reward.py::TestD03_FallbackCannotPassFloor
        # ✅ D-12: reward net of spread.
        #
        # tp1_pips is floored at `spread_pips * 2 + 1` inside
        # calculate_hybrid_take_profit(), so on a wide-spread symbol the
        # target is set BY THE SPREAD rather than by structure -- and the
        # reported R:R therefore IMPROVES as conditions get worse.
        # XAGUSD 2026-09-01: spread 40p forced TP1 to 81p against a 32.8p
        # stop, reporting 1:2.47 and clearing the 1:2.0 floor on an
        # instrument whose spread alone exceeded the stop distance.
        #
        # Gross R:R is still computed and published, because that is what
        # the levels literally are. The FLOOR is tested against net,
        # because net is what the trade can actually realise.
        _net_tp1_pips = tp1_pips - spread if RISK_REWARD_NET_OF_SPREAD else tp1_pips
        rr_result_net = rr_from_pips(
            reward_pips=_net_tp1_pips,
            risk_pips=calculated_sl_pips,
            direction=effective_order_type,
        )
        rr_result = rr_from_pips(
            reward_pips=tp1_pips,
            risk_pips=calculated_sl_pips,
            direction=effective_order_type,
        )
        risk_reward_ratio = rr_result.ratio
        if not rr_result.valid:
            logger.warning(
                f"[R:R] {symbol}: risk/reward could not be computed -- {rr_result.reason} "
                f"(tp1_pips={tp1_pips}, calculated_sl_pips={calculated_sl_pips}). "
                f"Trade will be rejected by the absolute R:R floor."
            )
        elif RISK_REWARD_NET_OF_SPREAD and rr_result_net.valid and rr_result_net.ratio < rr_result.ratio:
            logger.info(
                f"[R:R] {symbol}: gross {rr_result.ratio:.2f} -> net {rr_result_net.ratio:.2f} "
                f"after {spread:.1f}p spread. Floor is tested against net."
            )
        reward_amount_1 = actual_risk * risk_reward_ratio
        

        # The probability floor is checked once, by the entry rule table above
        # (rule "probability", floor computed before analyze_entry). A second
        # copy used to run here with the same number; the tier table inside the
        # engine was a third (45) and the engine's band floor a fourth (25).

        # ============================================================
        # ============================================================
        # NEGATIVE EXPECTED VALUE GATE  (defect D-18)
        # ============================================================
        # EV no longer feeds probability (see the chain step above), so
        # it needs somewhere real to act. This is that place: a trade
        # whose expectancy is negative GIVEN the system's own estimate
        # is not a trade, however confident the estimate is.
        #
        # Like the two floors below it, this only ever moves toward
        # HOLD and never overwrites a rejection that already fired.
        #
        # ✅ FIXED 2026-09-17, two defects found on a live SPY.NYSE entry:
        #   * the gate set local variables only and never entry_analysis, which
        #     is what the monitor executes from -- it logged "SKIP" and the
        #     trade went out anyway, so it had never blocked anything;
        #   * ev_result was computed early, on the additive-chain probability
        #     (19% on that bar) and the account geometry, while the entry was
        #     decided on the strategy-group probability (75.4) and trades the
        #     final stop and target. EV is now judged on the probability the
        #     decision used and the geometry the order carries.
        if (EXPECTED_VALUE_IS_A_GATE and not EXPECTED_VALUE_FEEDS_PROBABILITY
                and simple_action != "HOLD" and execution != "DO_NOTHING"):
            ev_result = score_expected_value(
                p_win_pct=probability_at_decision, reward_pips=tp1_pips, risk_pips=calculated_sl_pips,
                spread_pips=spread, best_direction=best_direction)
            _ev_pips = ev_result.get("ev_pips")
            if _ev_pips is not None and _ev_pips < EXPECTED_VALUE_MIN_PIPS:
                ev_reason = (
                    f"SKIP - Expected value {_ev_pips:+.1f} pips is below the minimum "
                    f"{EXPECTED_VALUE_MIN_PIPS:+.1f} ({ev_result.get('reason', '')})"
                )
                logger.info(f"[EV GATE] {symbol}: {ev_reason}")
                final_decision = ev_reason
                simple_action = "HOLD"
                execution = "DO_NOTHING"
                entry_triggered = False
                entry_analysis["should_enter"] = False
                entry_analysis["simple_action"] = "HOLD"
                entry_analysis["execution"] = "DO_NOTHING"
                entry_analysis["final_decision"] = ev_reason
                entry_analysis["reason"] = ev_reason
        # ✅ NEW: ABSOLUTE R:R FLOOR (independent of probability)
        # ============================================================
        # best_probability is a MODEL estimate -- the single least
        # reliable number anywhere in this pipeline, however carefully
        # the chain above just adjusted it. risk_reward_ratio (already
        # computed above from calculated_sl_pips/tp1_pips, both real
        # priced levels) is a MEASURED fact once SL/TP are set. A high
        # probability estimate is not a substitute for an adequate
        # margin of safety if that estimate turns out to be wrong --
        # so this floor applies regardless of how high best_probability
        # reads, and (like the probability floor just above) only ever
        # moves the decision toward HOLD, never away from it, and never
        # overwrites an existing HOLD/veto that already fired for its
        # own reason.
        # ✅ FIXED (Phase 2, defect D-03): the test is now
        # `not rr_result.passes_floor(...)` rather than
        # `risk_reward_ratio < MIN_ABSOLUTE_RISK_REWARD`. passes_floor()
        # folds in the validity check, so an R:R that could not be
        # computed is rejected here by name instead of slipping through
        # on a fabricated default. Two distinct rejection reasons are
        # emitted so the replay in Phase 6 can tell "R:R too low" apart
        # from "R:R unmeasurable" -- they are different failure modes and
        # collapsing them would hide a data-integrity problem inside what
        # looks like ordinary trade selection.
        # ✅ D-12: the floor is tested against rr_result_net (reward net of
        # spread), not the gross ratio. tp1_pips is floored at spread*2+1,
        # so a wider spread INFLATES the gross ratio while making the trade
        # strictly worse -- the floor was rewarding the conditions it exists
        # to protect against. Gross is still what gets published, because
        # that is what the levels literally are.
        _rr_gate = rr_result_net if RISK_REWARD_NET_OF_SPREAD else rr_result
        # Under the market stop the R multiple is fixed by the plan (chosen on
        # tick-accurate brackets), so only measurability is tested here.
        _rr_floor = 0.0 if market_stop_plan else MIN_ABSOLUTE_RISK_REWARD
        if simple_action != "HOLD" and execution != "DO_NOTHING" and not _rr_gate.passes_floor(_rr_floor):
            if not _rr_gate.valid:
                rr_reason = (
                    f"SKIP - Risk:Reward could not be measured: {_rr_gate.reason}. "
                    f"An unmeasurable R:R is never treated as an acceptable one, regardless of "
                    f"probability ({best_probability:.1f}%)"
                )
            else:
                rr_reason = (
                    f"SKIP - Risk:Reward {_rr_gate.ratio:.2f} net of {spread:.1f}p spread "
                    f"(gross {risk_reward_ratio:.2f}) is below the absolute floor "
                    f"{MIN_ABSOLUTE_RISK_REWARD:.2f} (probability was {best_probability:.1f}%, but R:R is "
                    f"the margin of safety against that estimate being wrong, not a number probability "
                    f"can compensate for)"
                )
            simple_action = "HOLD"
            execution = "DO_NOTHING"
            entry_triggered = False
            final_decision = rr_reason
            entry_analysis["should_enter"] = False
            entry_analysis["simple_action"] = "HOLD"
            entry_analysis["execution"] = "DO_NOTHING"
            entry_analysis["final_decision"] = rr_reason
            entry_analysis["reason"] = rr_reason

        # ============================================================
        # OHLC + GNN OUTPUT
        # ============================================================
        
        ohlc_gnn_output = build_ohlc_with_gnn(
            symbol=symbol,
            rates=rates,
            current_price=current_price,
            pip_size=pip_size,
            gnn_analysis=gnn_result or {"available": False},
            # ✅ was defaulting to a hardcoded "H1" label inside
            timeframe=timeframe
        )
        
        # ============================================================
        # BUILD VOLATILITY DEBUG
        # ============================================================
        
        fvg_index = ict_data.get("fvg_index")
        adjacent_candles_data = {}
        if fvg_index is not None and fvg_index >= 2 and fvg_index < len(rates):
            try:
                adjacent_candles_data = {
                    "left_candle_high": round(float(rates[fvg_index-2][2]), 5),
                    "left_candle_low": round(float(rates[fvg_index-2][3]), 5),
                    "right_candle_high": round(float(rates[fvg_index][2]), 5),
                    "right_candle_low": round(float(rates[fvg_index][3]), 5)
                }
            except (IndexError, TypeError):
                logger.warning(f"Invalid fvg_index {fvg_index}")
        
        symbol_upper = symbol.upper()
        ranges = _NORMAL_ATR_RANGES.get(symbol_upper, _NORMAL_ATR_RANGES["DEFAULT"])

        # ✅ ADDED: calculate_atr_long() was dead code (never called
        # anywhere) despite its own docstring saying it exists specifically
        # for volatility protection, and it discarded its true-range
        # history the same way _calculate_stochastic() used to. Now wired
        # in: the 50-period ATR history becomes a REAL percentile-derived
        # band instead of the static per-symbol table above being the only
        # read on "normal" volatility. Additive field -- normal_range_min_
        # pips/normal_range_max_pips above are untouched for any existing
        # consumer; atr_percentile_band is the new, data-driven version.
        # ✅ FIXED: this recomputed the band a SECOND time, independently of
        # the one the volatility check now uses further up, with different
        # fallbacks and no fallback_extreme -- two bands from the same data
        # that could disagree, with the displayed one not being the one
        # that decided anything. Reuses the earlier band when it exists.

        # ✅ Resolved here, BEFORE volatility_debug is built, so this block
        # and vetos.checks below both quote the thresholds VetoEngine
        # actually applies. It used to be bound ~140 lines further down,
        # which is why volatility_protection kept reporting the DEFAULT
        # (70.0) while the gate quoted the instrument override (80.0).
        _veto_effective_thresholds = _get_effective_veto_thresholds_safe(symbol, atr_band=atr_percentile_band)
        _eff_atr_veto = _veto_effective_thresholds.get(
            "volatility_threshold_pips", EXTREME_VOLATILITY_VETO_THRESHOLD
        )

        volatility_debug = {
            "atr_pips": round(atr_pips, 1),
            "market_regime": market_regime,
            "normal_range_min_pips": ranges["min"],
            "normal_range_max_pips": ranges["max"],
            # ✅ FIXED: this key was `ranges["extreme"]` (the per-symbol
            # _NORMAL_ATR_RANGES table, 45.0 for XAGUSD) while `is_extreme`
            # below is computed against EXTREME_VOLATILITY_VETO_THRESHOLD
            # (70.0). Two different thresholds published side by side under
            # names that read like one. An ATR landing between them -- 49.2
            # live -- rendered as "threshold 45.0, ATR 49.2, is_extreme:
            # false", and core/decision_snapshot.py's gate paired the
            # DISPLAY threshold with the VETO's pass/fail, emitting
            # "[PASS] extreme_volatility: value=49.2 threshold=45.0
            # (margin -4.20)" -- a passing gate with a negative margin.
            #
            # Both thresholds are now named for what they actually govern,
            # and the veto threshold (the one with teeth) is the one the
            # gate should quote.
            "classification_threshold_pips": ranges["extreme"],
            # ✅ FIXED: pointed at EXTREME_VOLATILITY_VETO_THRESHOLD (70.0),
            # the DEFAULT, while VetoEngine overrides it per instrument
            # (XAGUSD: 80.0). Correct name, wrong constant -- my own
            # regression from the round that introduced this key. Live
            # 14:44: this said 70.0 while the gate said 80.0 on the same bar.
            "veto_threshold_pips": _eff_atr_veto,
            "extreme_threshold_pips": EXTREME_VOLATILITY_VETO_THRESHOLD,
            # True when ATR is past the classification threshold but not yet
            # past the veto threshold -- i.e. flagged as elevated by one
            # scale while the gate that can actually stop a trade still
            # reads it as fine. This is the band the live snapshot sat in.
            "above_classification_below_veto": (
                ranges["extreme"] < atr_pips <= EXTREME_VOLATILITY_VETO_THRESHOLD
            ),
            # Which table the penalty above was actually computed from.
            "range_source": volatility_check.get("range_source", "static_table"),
            "ranges_used": volatility_check.get("ranges_used"),
            "volatility_level": volatility_check["volatility_level"],
            "safe_to_trade": volatility_check["safe_to_trade"],
            "confidence_penalty": confidence_penalty,
            "reason": volatility_check["reason"],
            # ✅ FIXED: same flat constant. Live 14:44 ATR 76.2 -> is_extreme
            # true against 70.0, while the veto (80.0) passed with 3.8 pips
            # to spare. "EXTREME" and "allowed to trade" in one block.
            "is_extreme": atr_pips > _eff_atr_veto,
            # ✅ ADDED: three different "how volatile is it" verdicts ship in
            # every payload and routinely disagree, because each is measured
            # against a different yardstick:
            #   volatility_level  -- check_volatility_protection(), static
            #                        per-symbol _NORMAL_ATR_RANGES table
            #   market_regime     -- upstream regime classifier
            #   regime_3d.volatility -- decision_snapshot, real ATR percentile
            # Live XAGUSD carried volatility_level EXTREME, market_regime
            # NORMAL and regime_3d NORMAL simultaneously, on the same ATR.
            # None of them is wrong on its own terms; the payload just never
            # said they were answering different questions. Spelled out here
            # rather than silently reconciled, since which one SHOULD govern
            # is the open calibration decision.
            "volatility_verdicts": {
                "static_table": volatility_check["volatility_level"],
                "market_regime": market_regime,
                "percentile_band": (
                    "UNKNOWN" if not atr_percentile_band
                    else "BELOW_NORMAL" if atr_pips < atr_percentile_band["low"]
                    else "ABOVE_NORMAL" if atr_pips > atr_percentile_band["high"]
                    else "NORMAL"
                ),
                "agree": None,  # filled just below
            },
            "is_high_regime": market_regime == "HIGH_VOLATILITY",
            "is_above_normal": atr_pips > ranges["max"],
            "is_below_normal": atr_pips < ranges["min"],
            # ✅ ADDED: the new 5-state classifier, plus the probability
            # correction it actually applied (not just what the state
            # implies) -- so any given trade record shows exactly how
            # much this moved best_probability, for later review.
            "trading_regime": trading_regime,
            "trading_regime_probability_adjustment": regime_probability_adjustment,
            # ✅ NEW: what USE_MID_PRICE_FOR_INDICATORS would change.
            # Reported whether the switch is on or off, so the decision can
            # be made from observed impact rather than argument -- same
            # approach as adaptive_disagreement.
            "price_basis": {
                "indicator_price_source": "mid" if USE_MID_PRICE_FOR_INDICATORS else "ask",
                "entry_price_source": "ask",
                "bid": round(_bid, digits),
                "ask": round(_ask, digits),
                "mid": round(_mid, digits),
                "spread_pips": round((_ask - _bid) / pip_size, 1) if pip_size else None,
                # How far apart the two bases place price, as a fraction of
                # the Bollinger band. This is the number that matters: a
                # spread that is a large share of the band displaces every
                # level comparison by that much.
                "spread_as_pct_of_bb_band": _spread_pct_of_band(
                    _ask - _bid,
                    indicators_data.get("bollinger", {}).get("upper", 0),
                    indicators_data.get("bollinger", {}).get("lower", 0),
                ),
            }
        }

        # ✅ Flag whether the three volatility verdicts actually agree, so a
        # disagreement is visible as a boolean rather than something you have
        # to notice by reading three fields in three different sections.
        _verdicts = volatility_debug["volatility_verdicts"]
        _normalish = {"NORMAL"}
        volatility_debug["volatility_verdicts"]["agree"] = (
            (_verdicts["static_table"] in _normalish)
            == (_verdicts["market_regime"] in _normalish)
            == (_verdicts["percentile_band"] in _normalish)
        )
        if not volatility_debug["volatility_verdicts"]["agree"]:
            logger.info(
                f"[VOLATILITY] {symbol}: verdicts disagree on ATR {atr_pips:.1f}p -- "
                f"static_table={_verdicts['static_table']}, "
                f"market_regime={_verdicts['market_regime']}, "
                f"percentile_band={_verdicts['percentile_band']}"
            )
        
        # ✅ Resolved once, then used BOTH for vetos.checks below and
        # published as vetos.effective_thresholds -- so the booleans and
        # the thresholds they were computed from can never disagree.

        news_summary = _get_news_summary(symbol)
        session_summary = _get_session_summary(symbol, best_probability, calculated_sl_pips)
        
        # ============================================================
        # FINAL RESULT - COMPLETE
        # ============================================================
        
        result = {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "🎯 FINAL_DECISION": final_decision,
            "💰 ENTRY": round(execution_entry_price, digits),
            "🛑 STOP_LOSS": round(sl_price, digits),
            "🎯 TAKE_PROFIT_1": round(tp1_price, digits),
            "🎯 TAKE_PROFIT_2": round(tp2_price, digits),
            "🎯 TAKE_PROFIT_3": round(tp3_price, digits),
            "📊 LOT_SIZE": round(final_lot_size, 4),
            "💵 RISK_USD": round(actual_risk, 2),
            "📈 REWARD_USD": round(reward_amount_1, 2),
            "💰 MARGIN_REQUIRED_USD": round(margin_required, 2),
            # ✅ FIXED: this showed the POST-decision probability, which no
            # gate ever tested. The headline now reports the number the
            # entry decision was actually made on, so it can be compared
            # against min_probability_for_entry without misleading anyone.
            # The post-chain figure is still published in full below as
            # final_verdict.probability_percent_post_chain.
            "⭐ CONFIDENCE": f"{probability_at_decision:.1f}%",
            "⭐ CONFIDENCE_POST_CHAIN": f"{best_probability:.1f}%",
            "🚀 SIMPLE_ACTION": simple_action,
            "🚀 REASON": f"{best_probability:.1f}% - {trend_data.get('trend', 'NEUTRAL')} trend - Zone {sd_data.get('zone_grade', 'E')} - RR {rr_result.display()}",
            
            # ============================================================
            # INDICATORS — single unified section
            # ============================================================
            # ✅ MERGED: every indicator used to be split across up to 6
            # separate top-level sections (indicator_scores,
            # divergence_analysis, adaptive_oscillators, m15_divergence,
            # components.8_indicators, and standalone *_reversal /
            # bb_mean_reversion / ema_crossover / volume_profile / wave_c
            # / fvg_ifvg sections), each showing a different subset of
            # the same underlying data - e.g. RSI's score lived in
            # indicator_scores, its divergence in divergence_analysis AND
            # m15_divergence, its percentile-based alt score in
            # adaptive_oscillators, and its raw values + reversal setup +
            # debug in components.8_indicators. Same pattern for
            # Stochastic, MACD, Bollinger, Volume, Supply/Demand,
            # Candlestick, Support/Resistance, Breakout, Wyckoff, ICT,
            # Volume Profile, Wave C, FVG/IFVG, EMA crossover, and COT.
            # All of that now lives here exactly once, per indicator.
            "indicators": {
                # ✅ FIXED: was "unified_score": unified_score --
                # unified_score (a single blended number+recommendation
                # collapsing all indicators into one flat vote) has been
                # removed entirely: it never actually drove
                # best_probability/the real trade decision (that comes
                # from probability_buy/probability_sell and the additive
                # chain below), so it was a parallel, display-only
                # computation, and pointless to maintain once each
                # indicator already gets its own honest section here.
                # round_numbers (see core/round_number_levels.py) takes
                # its place as a real, standalone structural indicator.
                "round_numbers": round_number_result,
                "expected_value": ev_result,
                "fib_confluence": fib_confluence_result,
                "retest_confirmation": retest_result,

                "trend": {
                    "trend": trend_data.get("trend", "NEUTRAL"),
                    "base_trend": trend_data.get("base_trend", "NEUTRAL"),
                    "recommendation": trend_data.get("recommendation", "NEUTRAL"),
                    "score": trend_data.get("score", 0),
                    "confidence": trend_indicator.get("confidence", 0),
                    "reason": trend_indicator.get("reason", ""),
                    # Already published here, and now also captured by
                    # core/decision_features.py so the invariance splits
                    # can test it. It is computed for real and passed to
                    # calculate_real_probability() as
                    # `ema20_ema200_gap_pips`, which accepts it and never
                    # reads it -- a genuine trend-strength measure handed
                    # to the probability engine and dropped. Capturing is
                    # not wiring: whether it earns a place in the chain
                    # is for the splits to answer, the same route the
                    # three disabled vetoes took.
                    "ema_gap_pips": round(ema_gap_pips, 1),
                    "adx": {"adx_7": round(adx_7, 1), "adx_14": round(trend_data.get("adx_value", 0), 1), "adx_21": round(adx_21, 1)},
                    "ema": {"ema_9": round(ema_9, 5), "ema_20": round(trend_data.get("ema_20", 0), 5), "ema_21": round(ema_21, 5), "ema_50": round(trend_data.get("ema_50", 0), 5), "ema_100": round(ema_100, 5), "ema_200": round(trend_data.get("ema_200", 0), 5)},
                    "crossover_setup": ema_crossover_setup,
                    "divergence_impact": trend_data.get("divergence_impact", {}),
                },

                "rsi": {
                    "rsi_14": round(indicators_data.get("rsi", {}).get("value", 50), 1),
                    "rsi_21": round(indicators_data.get("rsi", {}).get("rsi_21", 50), 1),
                    "score": rsi_indicator.get("score", 0),
                    "confidence": rsi_indicator.get("confidence", 0),
                    "recommendation": rsi_indicator.get("recommendation", "NEUTRAL"),
                    "reason": rsi_indicator.get("reason", ""),
                    # the M1 divergence (core/rsi_divergence_setup.py)
                    "divergence": {
                        "type": rsi_div_type,
                        "score": rsi_div_score,
                        "timeframe": "M1",
                        "veto_triggered": (best_direction == "BUY" and rsi_div_score < 0 and (rsi_div_rsi < 30 or rsi_div_score < -80)) or (best_direction == "SELL" and rsi_div_score > 0 and (rsi_div_rsi > 70 or rsi_div_score > 80))
                    },
                    # ✅ reuses the read computed at decision time above --
                    # was recomputed here independently, so the published
                    # band and the one available to the chain could drift.
                    "reversal_setup": rsi_reversal_setup,
                    "debug": {"rsi_trend": indicators_data.get("rsi_trend", "unknown"), "price_trend": indicators_data.get("price_trend", "unknown")}
                },

                "stochastic": {
                    "k": round(indicators_data.get("stochastic", {}).get("k", 50), 1),
                    "d": round(indicators_data.get("stochastic", {}).get("d", 50), 1),
                    "signal": indicators_data.get("stochastic", {}).get("signal", "NEUTRAL"),
                    "score": stoch_indicator.get("score", 0),
                    "confidence": stoch_indicator.get("confidence", 0),
                    "recommendation": stoch_indicator.get("recommendation", "NEUTRAL"),
                    "reason": stoch_indicator.get("reason", ""),
                    "divergence": {
                        "type": stoch_div_type,
                        "score": stoch_div_score,
                        "k": round(stoch_k_m15, 1),
                        "d": round(stoch_d_m15, 1),
                        "timeframe": "M15",
                    },
                    "reversal_setup": stoch_reversal_setup,
                },

                "macd": {
                    "macd_line": round(indicators_data.get("macd", {}).get("line", 0), 5),
                    "signal_line": round(indicators_data.get("macd", {}).get("signal", 0), 5),
                    "histogram": round(indicators_data.get("macd", {}).get("histogram", 0), 5),
                    "prev_histogram": round(indicators_data.get("macd", {}).get("prev_histogram", 0), 5),
                    "cross_direction": indicators_data.get("macd", {}).get("cross_direction"),
                    "signal": indicators_data.get("macd", {}).get("signal_str", "NEUTRAL"),
                    "score": macd_indicator.get("score", 0),
                    "confidence": macd_indicator.get("confidence", 0),
                    "recommendation": macd_indicator.get("recommendation", "NEUTRAL"),
                    "reason": macd_indicator.get("reason", ""),
                    "debug": {"histogram_direction": indicators_data.get("macd", {}).get("histogram_direction", "unknown")}
                },

                "bollinger_bands": {
                    "upper": round(indicators_data.get("bollinger", {}).get("upper", 0), 5),
                    "middle": round(indicators_data.get("bollinger", {}).get("middle", 0), 5),
                    "lower": round(indicators_data.get("bollinger", {}).get("lower", 0), 5),
                    # ✅ FIXED: this took `position` from _calculate_bollinger_bands(),
                    # which derives it from prices[-1] (the bar CLOSE, bid side),
                    # while `reason`/`score`/`percent_b` in the same block come
                    # from score_bollinger_indicator() using current_price
                    # (tick.ask). Two prices, one dict.
                    #
                    # Live 00:08: middle 68.79336, bid close 68.767, ask 68.810 --
                    # the two straddle the middle band, and the block published
                    # position "BELOW_MIDDLE" next to reason "Above middle band"
                    # with percent_b 0.547. Both were internally correct and the
                    # pair was nonsense.
                    #
                    # Now taken from the scorer, so the whole block describes one
                    # price. See that function's docstring for the underlying
                    # ask-vs-bid basis issue, which is NOT fixed here.
                    "position": bb_indicator.get("position",
                        indicators_data.get("bollinger", {}).get("position", "UNKNOWN")),
                    "price_basis": bb_indicator.get("price_basis", "ask"),
                    "signal": indicators_data.get("bollinger", {}).get("signal", "NEUTRAL"),
                    "width": round(indicators_data.get("bollinger", {}).get("width", 0), 4),
                    "score": bb_indicator.get("score", 0),
                    "confidence": bb_indicator.get("confidence", 0),
                    "recommendation": bb_indicator.get("recommendation", "NEUTRAL"),
                    "reason": bb_indicator.get("reason", ""),
                    "mean_reversion_setup": bb_mean_reversion_setup,
                    "debug": {
                        "is_squeeze": indicators_data.get("bollinger", {}).get("is_squeeze", False),
                        # ✅ FIXED: was the flat BB_SQUEEZE_THRESHOLD (0.05
                        # for every instrument) -- displayed a threshold
                        # that was never actually the one used to compute
                        # is_squeeze/score/recommendation above once the
                        # other two BB_SQUEEZE_THRESHOLD sites were fixed
                        # to use get_bb_squeeze_threshold(symbol). Now
                        # shows the real, instrument-aware value.
                        "squeeze_threshold": get_bb_squeeze_threshold(symbol),
                        "percent_b": round(indicators_data.get("bollinger", {}).get("percent_b", 0.5), 2),
                        "bandwidth_history": bandwidth_history
                    }
                },

                "volume": {
                    "ratio": round(volume_ratio, 2),
                    "confirmed": indicators_data.get("volume", {}).get("confirmed", False),
                    "score": volume_indicator.get("score", 0),
                    # ✅ FIXED: read a "rec" key that score_volume_indicator()
                    # has never emitted -- it returns "recommendation". The
                    # .get() default therefore fired on EVERY call, so this
                    # field reported "LOW_VOLUME" permanently regardless of
                    # what the scorer actually decided. Confirmed live: a
                    # payload whose volume scorer returned NEUTRAL still
                    # displayed LOW_VOLUME here.
                    "recommendation": volume_indicator.get("recommendation", "NEUTRAL"),
                    "debug": {
                        "current_volume": volumes[-1] if volumes else 0,
                        "avg_volume_20": round(sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0, 0),
                        "avg_volume_50": round(sum(volumes[-50:]) / 50 if len(volumes) >= 50 else 0, 0),
                        "is_spike": volume_spike,
                        "score_breakdown": indicators_data.get("volume", {}).get("breakdown", {})
                    }
                },

                "supply_demand": {
                    "zone_grade": sd_data.get("zone_grade", "E"),
                    "zone_level": round(sd_data.get("zone_level"), 5) if sd_data.get("zone_level") else None,
                    "is_at_zone": sd_data.get("is_at_zone", False),
                    "score": sd_data.get("score", 0),
                    "recommendation": sd_data.get("recommendation", "NEUTRAL"),
                    "confidence": sd_indicator.get("confidence", 0),
                    "reason": sd_indicator.get("reason", ""),
                    "volume_profile_confluence": sd_volume_profile_confluence,
                    "debug": {
                        "touch_count": sd_data.get("touch_count", 0),
                        # ✅ the composite inputs behind the grade; the
                        # coherence validator reads this to check the grade
                        # against the model that actually produced it
                        "quality_breakdown": sd_data.get("quality_breakdown"),
                        "distance_to_zone_pips": round(abs(current_price - (sd_data.get("zone_level") or current_price)) / pip_size, 1) if sd_data.get("zone_level") else 0,
                        "max_allowed_pips_for_grade": ZONE_AT_ZONE_PIPS.get(sd_data.get("zone_grade", "E"), 0),
                        "zone_strength_multiplier": sd_data.get("zone_multiplier", 1.0),
                        "is_demand_zone": sd_data.get("zone_type") == "DEMAND"
                    }
                },

                "candlestick": {
                    "score": candle_data.get("score", 0),
                    "recommendation": candle_data.get("recommendation", "NEUTRAL"),
                    "confidence": candle_indicator.get("confidence", 0),
                    "reason": candle_indicator.get("reason", ""),
                    "debug": {
                        "body_pips": round(candle_data.get("body_pips", 0), 1),
                        "upper_wick_pips": round(candle_data.get("upper_wick_pips", 0), 1),
                        "lower_wick_pips": round(candle_data.get("lower_wick_pips", 0), 1),
                        "candle_type": candle_data.get("candle_type", "normal"),
                        "is_pin_bar": False,
                        "closing_position": "unknown"
                    }
                },

                "support_resistance": {
                    "pivot": round(sr_data.get("pivot", 0), 5),
                    "r1": round(sr_data.get("r1", 0), 5), "r2": round(sr_data.get("r2", 0), 5), "r3": round(sr_data.get("r3", 0), 5),
                    "s1": round(sr_data.get("s1", 0), 5), "s2": round(sr_data.get("s2", 0), 5), "s3": round(sr_data.get("s3", 0), 5),
                    "breakout": sr_data.get("breakout", False),
                    "distance_to_resistance_pips": (lambda v: round(v, 1) if isinstance(v, (int, float)) else None)(sr_data.get("distance_to_resistance_pips")),
                    "score": sr_data.get("score", 0),
                    "recommendation": sr_data.get("recommendation", "NEUTRAL"),
                    "volume_profile_confluence": sr_volume_profile_confluence,
                    "debug": {
                        "price_vs_pivot": "above" if current_price > sr_data.get("pivot", 0) else "below",
                        "pivot_distance_pips": round(abs(current_price - sr_data.get("pivot", current_price)) / pip_size, 1),
                        "breakout_period": BREAKOUT_PERIOD
                    }
                },

                "breakout": {
                    "is_breakout": sr_data.get("breakout", False),
                    "debug": {
                        "breakout_threshold": round(sr_data.get("high_period", 0), 5),
                        "distance_to_breakout_pips": round((sr_data.get("high_period", current_price) - current_price) / pip_size if sr_data.get("high_period", current_price) > current_price else 0, 1),
                        "required_volume_for_breakout": BREAKOUT_VOLUME_THRESHOLD,
                        "breakout_candle_confirmed": volume_ratio >= BREAKOUT_VOLUME_THRESHOLD and sr_data.get("breakout", False)
                    }
                },

                "wyckoff": {
                    "phase": wyckoff_data.get("phase", "NEUTRAL"),
                    "score": wyckoff_data.get("score", 0),
                    "recommendation": wyckoff_data.get("recommendation", "NEUTRAL"),
                    "volume_profile_confluence": wyckoff_volume_profile_confluence,
                    "debug": {
                        "adx_used": round(trend_data.get("adx_value", 0), 1),
                        "trend_used": trend_data.get("trend", "NEUTRAL"),
                        "volume_ratio": round(volume_ratio, 2),
                        "momentum": round((close_prices[-1] - close_prices[-20]) / close_prices[-20] if len(close_prices) >= 20 else 0, 4),
                        "range_high": round(max(high_prices[-50:]), 5) if len(high_prices) >= 50 else 0,
                        "range_low": round(min(low_prices[-50:]), 5) if len(low_prices) >= 50 else 0
                    }
                },

                "ict_concepts": {
                    "signal": ict_data.get("signals", {}),
                    "type": ict_signal_type,
                    "price_above_fvg_pips": round(price_above_fvg_pips, 1),
                    "price_below_fvg_pips": round(price_below_fvg_pips, 1),
                    "score": ict_score_val,
                    "recommendation": ict_rec,
                    "fvg_tolerance_applied": round(fvg_tolerance, 1),
                    "is_blocked": ict_signal_type == "INVALID",
                    "debug": {
                        "fvg_high": round(ict_data.get("fvg_high"), 5) if ict_data.get("fvg_high") else None,
                        "fvg_low": round(ict_data.get("fvg_low"), 5) if ict_data.get("fvg_low") else None,
                        "fvg_width_pips": round((ict_data.get("fvg_high", 0) - ict_data.get("fvg_low", 0)) / pip_size, 1) if ict_data.get("fvg_high") and ict_data.get("fvg_low") else 0,
                        "distance_to_fvg_pips": round(ict_data.get("distance_to_fvg_pips", 0), 1),
                        "is_price_in_fvg": ict_data.get("is_price_in_fvg", False),
                        "adjacent_candles": adjacent_candles_data
                    }
                },

                "volume_profile": {
                    "poc": volume_profile_data.get("poc"),
                    "vah": volume_profile_data.get("vah"),
                    "val": volume_profile_data.get("val"),
                    "score": volume_profile_indicator.get("score", 0),
                    "confidence": volume_profile_indicator.get("confidence", 0),
                    "recommendation": volume_profile_indicator.get("recommendation", "NEUTRAL"),
                    "reason": volume_profile_indicator.get("reason", ""),
                },

                "wave_c": {
                    "data": wave_c_data,
                    "score": wave_c_indicator.get("score", 0),
                    "confidence": wave_c_indicator.get("confidence", 0),
                    "recommendation": wave_c_indicator.get("recommendation", "NEUTRAL"),
                    "reason": wave_c_indicator.get("reason", ""),
                    "reversal_setup": wave_c_reversal_setup,
                },

                "fvg_ifvg": {
                    "active_gaps": all_fvgs,
                    "score": fvg_ifvg_indicator.get("score", 0),
                    "confidence": fvg_ifvg_indicator.get("confidence", 0),
                    "recommendation": fvg_ifvg_indicator.get("recommendation", "NEUTRAL"),
                    "reason": fvg_ifvg_indicator.get("reason", ""),
                    "setup": fvg_ifvg_setup,
                },

                "cot_report": {"score": cot_score, "recommendation": cot_rec},

            },
            
            "pattern_analysis": {
                "timeframes": pattern_result.get('timeframes', {}),
                "summary": pattern_result.get('summary', {}),
                "elliott_waves": pattern_result.get('elliott_waves', []),
            },

            # ============================================================
            # ELITE ENHANCEMENTS (session additions) — items #5, #6
            # ============================================================
            # ✅ WIRED IN: previously delivered as standalone modules only,
            # never actually called from the main analysis flow. Now live.

            # #5 — multi-degree wave nesting instead of 5 flat per-TF opinions
            "wave_lattice": build_wave_lattice(pattern_result),

            # #6 — stop-hunt / order-block mitigation / liquidity pools,
            # always-on rather than conditionally computed. Computed
            # earlier (alongside its volume-profile confluence check) and
            # reused here rather than calling build_order_flow_forensics()
            # a second time.
            "order_flow_forensics": order_flow_forensics_data,

            # Gap & slippage risk. The detection/report itself is still
            # advisory-only exactly as before -- avoid_trade_recommended /
            # should_exit_recommended do NOT modify final_decision, veto,
            # or should_close_position anywhere. What changed: this is now
            # the SAME gap_slippage_report object (computed once, earlier)
            # that calculate_gap_slippage_final_score() already turned into
            # a bounded probability penalty as part of the chain above --
            # see gap_slippage_final_score in final_verdict below for that.
            "gap_slippage_analysis": gap_slippage_report,

            # ✅ NEW: multi-degree trend cascade (M5/M15/H1/H4 EMA-slope
            # alignment) -- raw detector output; see
            # final_verdict.trend_cascade_final_score for how it was applied
            # to probability_percent.
            "trend_cascade": trend_cascade_result,
            "adr_exhaustion": adr_result,

            # RVAM: did participation match the movement? The 2x2 that
            # separates a funded breakout from an unfunded one, and
            # heavy-volume absorption from a quiet tape.
            "rvam": rvam_result,

            # Value weighted by where business actually got done --
            # the first non-price-only measure of value in the system.
            # Anchored to the strongest recent liquidity sweep, so
            # `anchored.vwap` is the average entry of everyone trapped
            # by it: the level they defend or abandon.
            "vwap": vwap_result,

            # Real BB-inside-Keltner squeeze: duration, release event
            # and direction. Replaces a bandwidth threshold that could
            # only say "volatility is low".
            "ttm_squeeze": squeeze_result,
            "ttm_squeeze_setup": squeeze_setup,
            "vwap_context": vwap_context,

            # One canonical set of sweeps, now shared by SMC, order
            # flow and the VWAP anchor.
            "liquidity_events": liquidity_summary,
            "liquidity_final_score": liquidity_final,

            # Which side the analysis chose, which side was traded, and
            # whether the trend cascade switched it.
            "direction_decision": direction_decision,

            # Every strategy group's score for the traded side, the winner,
            # and the context adjustments. See core/strategy_groups.py.
            "strategy_groups": strategy_groups_result,


            # ✅ NEW: explicit SMC-vs-Wyckoff hard disagreement flag --
            # None when they agree or aren't both high-conviction; a
            # populated dict (see message) when two independent,
            # high-conviction methods flatly contradict each other.

            "entry_analysis": entry_analysis,

            # ✅ NEW: each analysis component's own verdict, published so
            # it can be scored against outcomes.
            #
            # These were computed on every decision and then existed only
            # as local variables -- trend_data, sd_data, sr_data and the
            # rest never reached the result, so no report could ask the
            # obvious question: does supply/demand actually predict
            # anything? Section 5 could only score the eleven
            # probability-chain contributions, which is a different and
            # much smaller set than the components a trader reasons about.
            #
            # Recommendation and score only. The full component payloads
            # are large and mostly debug detail; what attribution needs is
            # the verdict each one reached and how strongly.
            "volatility_protection": volatility_debug,
            "news_analysis": {
                "has_news": news_summary.get("has_news", False),
                "high_impact_count": news_summary.get("high_impact_count", 0),
                "medium_impact_count": news_summary.get("medium_impact_count", 0),
                "low_impact_count": news_summary.get("low_impact_count", 0),
                "next_event": news_summary.get("next_event"),
                # ✅ FIXED: was `veto and "news" in str(veto_reason).lower()`
                # -- string-matching the single combined veto_reason message
                # instead of reading the actual news-veto result already
                # sitting in news_summary (same source session_analysis uses
                # for its own veto_triggered below). Substring matching can
                # only ever report one cause at a time and only when it
                # happens to be the primary reason text -- it would report
                # False here even when the news veto is independently true
                # alongside some other, differently-worded primary veto.
                "veto_triggered": news_summary.get("veto_triggered", False),
            },
            "session_analysis": {
                "exchange": session_summary.get("exchange", "FX"),
                "is_market_open": session_summary.get("is_open", True),
                "is_trading_day": session_summary.get("is_trading_day", True),
                "minutes_to_close": session_summary.get("minutes_to_close"),
                # ✅ CORRECTED: an earlier version of this flag treated ANY
                # negative minutes_to_close as a contradiction with
                # is_market_open=True. That was wrong and produced a false
                # positive on every continuous-market symbol. The negative
                # values are documented SENTINELS in
                # session_manager._get_minutes_until_close_sync(), not
                # durations:
                #     -1 = market closed for the day
                #     -2 = market open, continuous, no close time
                # So -2 alongside is_market_open=True is exactly correct,
                # not a contradiction. Decoded into a readable state
                # instead of being compared as a number.
                "session_close_state": _decode_minutes_to_close(
                    session_summary.get("minutes_to_close")
                ),
                # A calendar that failed to LOAD is reported separately by
                # session_manager -- a non-FX symbol running on continuous
                # (FX) session rules means its exchange calendar is missing,
                # and its pre-close veto can never fire. See
                # SessionManager.calendar_load_failures.
                "calendar_degraded": session_summary.get("calendar_degraded", False),
                "veto_triggered": session_summary.get("veto_triggered", False),
                "veto_reason": session_summary.get("veto_reason"),
            },
            "position_management": {
                "should_close": should_close_position,
                "close_reason": close_position_reason,
                "is_already_in_trade": is_already_in_trade,
                "current_pnl_percent": round(current_pnl_percent, 1)
            },
            "vetos": {
                "triggered": veto,
                "reason": veto_reason if veto else None,
                "checks": {
                    # ✅ FIXED: these two used to be derived by string-
                    # matching "session"/"news" inside the single combined
                    # veto_reason message, unlike every other entry in this
                    # dict (all independently re-evaluated against live
                    # data). That meant they could only ever be True when
                    # session/news happened to be the ONE primary cause
                    # named in veto_reason -- e.g. this exact snapshot has
                    # low_volume and candle_too_young both independently
                    # true at once, proving multiple simultaneous vetoes
                    # are a real case this dict needs to represent, which
                    # substring matching structurally can't for session/
                    # news. Now reads the same independently-computed
                    # veto_triggered flags session_analysis/news_analysis
                    # already surface elsewhere in this payload.
                    "session_veto": session_summary.get("veto_triggered", False),
                    "news_veto": news_summary.get("veto_triggered", False),
                    # ✅ FIXED: these two were recomputed here against the
                    # FLAT system-wide constants (25 / 70.0) while the veto
                    # that sets vetos.triggered / vetos.reason uses the veto
                    # engine's PER-INSTRUMENT overrides (XAGUSD: 22 / 80.0).
                    # Two independent computations of the same question,
                    # published side by side in the same block.
                    #
                    # Observed live at ADX 24.0 -- inside the [22, 25) band:
                    # checks.choppy_market said true while triggered was
                    # false and reason was null, because 24.0 >= 22 (no veto)
                    # but 24.0 < 25 (check fires). Now both read the same
                    # effective thresholds, falling back to the flat
                    # constants only if the engine lookup failed.
                    # Must mirror VetoEngine.check_choppy_market, including
                    # its mode. The veto now defaults to "invert" (it blocks
                    # TRENDING setups, measured at 37.1% -> 50.7% win rate),
                    # and this reporting check still read the original
                    # low-ADX condition -- so the coherence checker
                    # immediately fired `cause_without_veto`: the check said
                    # true while vetos.triggered said false, on the same
                    # question. Two computations of one condition disagreeing
                    # in the same payload is exactly what that checker exists
                    # to catch, and it caught this.
                    "choppy_market": _choppy_check_matches_veto(
                        trend_data.get("adx_value", 0),
                        _veto_effective_thresholds.get(
                            "adx_threshold", RANGING_MARKET_ADX_THRESHOLD)),
                    "extreme_volatility": atr_pips > _veto_effective_thresholds.get(
                        "volatility_threshold_pips", EXTREME_VOLATILITY_VETO_THRESHOLD
                    ),
                    # ⚠️ ADVISORY ONLY -- see "advisory_only" below. These three
                    # have no live counterpart: VetoEngine.check_against_trend,
                    # check_against_ema and check_h1_conflict are all commented
                    # out (veto_engine.py lines 276/290/303) and their call
                    # sites at V3/V4/V5 are commented out too. They are computed
                    # and reported here, and rendered as PASS/FAIL gates by
                    # decision_snapshot, but they cannot stop a trade.
                    #
                    # Live 12:44: checks.against_ema true and the gate showed
                    # FAIL, while vetos.reason was "Choppy market" -- because
                    # against_ema is incapable of being the reason. Reading that
                    # payload it looks like five checks failed and any could
                    # have blocked the trade; three of them were inert.
                    #
                    # Left computed rather than removed -- they are real reads
                    # and re-enabling them is a trading decision, not a bug fix.
                    # Flagged instead so the output stops implying they gate.
                    "against_trend": (best_direction == "BUY" and trend not in ["STRONG_BULLISH", "BULLISH"]) or (best_direction == "SELL" and trend not in ["STRONG_BEARISH", "BEARISH"]),
                    "against_ema": (best_direction == "BUY" and current_price < trend_data.get("ema_200", 0)) or (best_direction == "SELL" and current_price > trend_data.get("ema_200", 0)),
                    "h1_conflict": not h1_aligned and h1_trend != "NEUTRAL",
                    # ✅ Delegated. The inline version happened to be
                    # equivalent to the engine's under default config (30 /
                    # 70 / 80), but those are VetoEngine constructor options
                    # -- a config that overrode any of them would have split
                    # the two silently. Same implementation now either way.
                    "rsi_divergence_opposing": _veto_check_safe(
                        "check_rsi_divergence_opposing", best_direction, rsi_div_score, rsi_div_rsi,
                        symbol=symbol),
                    # ✅ FIXED: was flat WICK_REVERSAL_RATIO (3.0) for every
                    # candle regardless of body size. get_wick_reversal_ratio()
                    # was built (config section 32-adjacent) specifically to
                    # widen this to 5.0x for tiny bodies (<1 pip) so noise-level
                    # wicks on candles like M1 dojis don't false-trigger the
                    # veto -- but it was never actually called anywhere. A
                    # 0.3-pip-body doji now needs a 1.5-pip wick to trigger
                    # instead of 0.9 pips.
                    # ✅ FIXED (again, same class): both of these were
                    # reimplemented here rather than asked of the veto engine,
                    # and both drifted from it.
                    #
                    # wick_reversal: VetoEngine.check_wick_reversal() opens
                    #   with `if body_pips <= 0: return False` -- a zero-body
                    #   doji cannot trigger it, because body * ratio == 0 and
                    #   ANY wick would exceed 0. This copy had no such guard,
                    #   so `4.0 > 0.0 * 5.0` evaluated True on every doji.
                    #   Live 12:59: body 0.0p, upper wick 4.0p, BUY ->
                    #   checks.wick_reversal true while triggered was false.
                    #
                    # low_volume: the engine uses get_volume_threshold(trend,
                    #   adx) -- 0.3 in a strong trend, 0.4 moderate, 0.5
                    #   neutral. This copy used the flat
                    #   VOLUME_LOW_THRESHOLD_M1 (0.5). Live veto messages show
                    #   both in use: "< 0.5" on a NEUTRAL bar and "< 0.4" on a
                    #   BEARISH one. Contradiction band: ratio in [0.3, 0.5)
                    #   depending on regime.
                    #
                    # Delegated to the engine so there is one implementation
                    # rather than two that agree until one is touched.
                    "wick_reversal": _veto_check_safe(
                        "check_wick_reversal", best_direction,
                        candle_data.get("upper_wick_pips", 0),
                        candle_data.get("lower_wick_pips", 0),
                        candle_data.get("body_pips", 0),
                        symbol=symbol),
                    "low_volume": _veto_check_safe(
                        "check_low_volume", volume_ratio, trend, adx_val,
                        symbol=symbol),
                    # ✅ Delegated. Byte-identical to the engine's version
                    # (`if not spread_valid: return True`) -- routed through
                    # anyway so it stays identical rather than being one more
                    # copy waiting to drift.
                    "high_spread": _veto_check_safe(
                        "check_high_spread", spread_valid, spread, max_allowed_spread,
                        symbol=symbol),
                    # ✅ FIXED: this was a flat `progress < 75%`. The engine
                    # runs a signal-aware ladder instead: no veto at all above
                    # 50%, and when signals are strong (>=2 signals, a volume
                    # spike, absorption, or probability >=75) entry is allowed
                    # from 10%. Two contradiction bands:
                    #   progress in [50, 75)  -> check said too young, veto
                    #                            did not fire. The live 12:44
                    #                            bar sat at 58.3%.
                    #   progress in [10, 50) with strong signals -> check said
                    #                            too young, veto allowed entry.
                    # The flat version had no path to the strong-signal case
                    # at all, so it could never agree there.
                    # ✅ FIXED: passed best_probability, which by this point has
                    # been through the POST-ENTRY chain. The veto itself ran far
                    # earlier with the DECISION-time probability. Same function,
                    # different input, so they disagreed whenever the post-chain
                    # moved probability across the 75 strong-signal boundary.
                    #
                    # Caught by the coherence validator on a live bar: decision
                    # probability 95.0, post-chain 74.9 -- under by 0.1 -- so the
                    # check saw "weak signals, 33% candle" and vetoed while the
                    # engine had seen "strong signals" and allowed it.
                    #
                    # Delegating to one implementation was necessary but not
                    # sufficient; it also has to be called with the same inputs.
                    "candle_too_young": _veto_check_safe(
                        "check_candle_too_young", entry_triggered, candle_progress * 100,
                        signal_count, probability_at_decision, volume_spike, absorption
                    , symbol=symbol)
                },
                # ✅ NEW: the thresholds the veto engine ACTUALLY applied to
                # this symbol. VetoEngine overrides ADX and volatility
                # per-instrument (XAGUSD: ADX 22 not 25, ATR 80.0 not 70.0),
                # but nothing outside the class could see that, so
                # decision_snapshot's gates quoted the flat system-wide
                # constants and disagreed with the veto that actually ran.
                # Contradiction bands: ADX in [22, 25) and ATR in (70, 80].
                "effective_thresholds": _veto_effective_thresholds,
                # ✅ NEW: which entries in `checks` above can actually stop a
                # trade. Everything not listed here is enforced by the veto
                # engine; these three are computed and displayed but their
                # engine implementations are commented out, so a True value
                # here never contributes to vetos.triggered.
                "advisory_only": ["against_trend", "against_ema", "h1_conflict"]
            },
            "higher_timeframe": {
                "timeframe": "H1",
                "trend": h1_trend,
                "adx": h1_adx,
                "ema_200": round(h1_ema_200, 5) if h1_ema_200 else None,
                "aligned_with_m1": h1_aligned,
                "confidence_bonus": h1_confidence_bonus
            },
            "trend_confirmation": {
                "m1_trend": trend_data.get("trend", "NEUTRAL"),
                "m1_adx": round(trend_data.get("adx_value", 0), 1),
                "m1_price_vs_ema200": "above" if current_price > trend_data.get("ema_200", 0) else "below",
                "h1_trend": h1_trend,
                "h1_aligned": h1_aligned,
                "overall_aligned": h1_aligned and ((best_direction == "BUY" and trend_data.get("trend", "NEUTRAL") in ["STRONG_BULLISH", "BULLISH"]) or (best_direction == "SELL" and trend_data.get("trend", "NEUTRAL") in ["STRONG_BEARISH", "BEARISH"]))
            },
            "final_verdict": {
                "verdict": final_decision if final_decision in ["BUY NOW", "SELL NOW"] else f"⏸️ {final_decision}",
                # ✅ SPLIT. probability_percent kept as the DECISION value --
                # the one min_probability_for_entry was compared against --
                # because that is what every consumer of this field is
                # implicitly asking for. The post-chain number is published
                # beside it rather than in place of it.
                "probability_percent": round(probability_at_decision, 1),
                # kept from the deleted `directional_analysis` section: the two
                # side probabilities and what was ruled out, which the stored
                # trade record and the decision features read
                "probability_buy": round(probability_buy, 1),
                "probability_sell": round(probability_sell, 1),
                "best_direction": best_direction,
                "directional_vetoes": directional_veto_info,
                "probability_percent_post_chain": round(best_probability, 1),
                # ✅ Every movement of best_probability, in order, with the
                # reason for each. The *_final_score blocks below do not
                # account for the whole chain -- EV, the H1 bonus and the
                # hard-disagreement penalty move it without emitting an
                # "adjustment" -- so the published chain did not reconcile
                # with the published result. This does.
                "probability_ledger": probability_ledger,
                # ✅ ADDED (defect D-19): reported contribution vs actual
                # movement, per step.
                #
                # The *_final_score blocks publish a "contribution"
                # figure that is what the module WANTED to add. When the
                # probability is already at the 95.0 ceiling, the chain
                # applies none of it -- and nothing in the payload said
                # so. XAGUSD 2026-09-01 15:49: expected_value published
                # +15.0 and h1_alignment +10.0 against deltas of 0.0 and
                # 0.0. An earlier bar had order_flow publishing +12.0
                # against a 0.0 delta and pattern +14.4 against +4.0.
                #
                # Anything with a non-zero "absorbed" here is evidence
                # the system computed and then threw away. A chain that
                # absorbs regularly is one whose later checks are
                # decorative, which is a measurable fact rather than a
                # suspicion.
                "probability_absorbed_by_bounds": _summarize_absorbed(probability_ledger),
                "probability_ledger_reconciles": (
                    bool(probability_ledger)
                    and abs(probability_ledger[-1]["after"] - round(probability_at_decision, 2)) < 0.15
                ),
                "probability_note": (
                    "probability_percent is the value the entry gate tested. "
                    "As of the D-01/D-02 fix the FULL chain -- including "
                    "pattern/GNN/SMC/FVG/order-flow/gap -- runs BEFORE the entry "
                    "gate, so probability_percent and probability_percent_post_chain "
                    "are now the same number. See probability_absorbed_by_bounds for "
                    "contributions the 5/95 clamp discarded."
                ),
                "action": effective_order_type if final_decision in ["BUY NOW", "SELL NOW"] else "HOLD",
                "simple_action": simple_action,
                "entry_price": round(execution_entry_price, digits),
                "stop_loss": round(sl_price, digits),
                "stop_loss_pips": round(calculated_sl_pips, 1),
                "take_profit_1": round(tp1_price, digits),
                "take_profit_2": round(tp2_price, digits),
                "take_profit_3": round(tp3_price, digits),
                "take_profit_pips": round(tp1_pips, 1),
                "lot_size": round(final_lot_size, 4),
                "margin_required_usd": round(margin_required, 2),
                # "account" or "strategy_setup:<name>": the executor keeps a
                # setup's stop and sizes the lot to the budget (core/execution.py)
                "stop_source": stop_source,
                # THE STRATEGY THIS DECISION CAME FROM and the setup it trades:
                # the group that won the auction (core/strategy_groups.py) and
                # its own trade setup (core/strategy_setups.py) -- entry, stop,
                # target, lot -- or why it has none.
                "strategy": {**{k: (entry_analysis.get("strategy") or {}).get(k)
                                for k in ("name", "title", "score", "final_probability", "why")},
                             # momentum is strength, not a strategy: published beside
                             # whichever strategy decided
                             "momentum": ((strategy_groups_result.get("groups") or {}).get("MOMENTUM") or {}).get("score")},
                "strategy_setup": strategy_setup,
                "risk_reward_ratio": rr_result.display(),
                "star_rating": star_rating,
                "stars_display": stars,
                "execution": execution,
                "market_regime": market_regime,
                "timing_confidence": timing_confidence,
                "timing_ready": timing_good,
                "gnn_final_score": gnn_final,
                "smc_final_score": smc_final,
                "pattern_final_score": pattern_final_score,
                "fvg_ifvg_final_score": fvg_ifvg_final,
                "order_flow_final_score": order_flow_final,
                "gap_slippage_final_score": gap_slippage_final,
                "trend_cascade_final_score": trend_cascade_final,
                "adr_exhaustion_final_score": adr_exhaustion_final,
                "rvam_final_score": rvam_final
            },
            "entry_details": {
                "entry_price": round(execution_entry_price, digits),
                "stop_loss": round(sl_price, digits),
                "stop_loss_pips": round(calculated_sl_pips, 1),
                "take_profit_1": round(tp1_price, digits),
                "take_profit_2": round(tp2_price, digits),
                "take_profit_3": round(tp3_price, digits),
                "take_profit_pips": round(tp1_pips, 1),
                # ✅ FIXED (Phase 2, defect D-10): was an unguarded
                # `tp1_pips / calculated_sl_pips`, which raises
                # ZeroDivisionError on the same invalid stop-loss that
                # D-03 covered -- and it was a SECOND, independently
                # computed R:R sitting three lines from the one the gate
                # used. Now renders the canonical result, which prints
                # "1:N/A" rather than a fabricated number when the R:R
                # could not be measured.
                "risk_reward": rr_result.display(),
                "risk_reward_detail": rr_result.as_dict(),
                "lot_size": round(final_lot_size, 4),
                "market_stop": market_stop_plan,
                # the one reading in this payload that is about what price is
                # DOING rather than where it is -- see core/behaviour_readings.py
                "behaviour": behaviour_result,
                # the fitted reversion process and its verdict on fading now
                "ou_reversion": ou_reversion_result,
                "spread_pips": round(spread, 1),
                "risk_usd": round(actual_risk, 2),
                "reward_usd": round(reward_amount_1, 2),
                "margin_required_usd": round(margin_required, 2)
            },
            "global_anticheat": {
                "candle_progress_percent": round(candle_progress * 100, 1),
                "candle_ready": candle_ready,
                "spread_pips": round(spread, 1),
                "spread_valid": spread_valid,
                "max_allowed_spread": max_allowed_spread,
                "volume_ratio": round(volume_ratio, 2),
                "atr_pips": round(atr_pips, 1)
            },
            "account_info": {
                "balance": round(actual_account_balance, 2),
                "leverage": leverage,
                "free_margin_before": round(free_margin, 2),
                "margin_required_usd": round(margin_required, 2),
                "free_margin_after": round(free_margin - margin_required, 2)
            },
            "gnn": {
                "available": gnn_result.get("available", False) if gnn_result else False,
                "analysis": gnn_result if gnn_result else {"available": False},
                "divergence": ({"available": False, "reason": "M1_ONLY: not read (GNN reads H1)"} if M1_ONLY
                               else get_gnn_divergence(symbol) if is_gnn_available() else {"available": False}),
            },
            "smc": {
                "available": smc_result.get("available", False) if smc_result else False,
                "analysis": smc_result if smc_result else {"available": False},
                "trade_setup": smc_trade_setup,
                "order_block_volume_profile_confluence": ob_volume_profile_confluence,
                "sweep_volume_profile_confluence": sweep_volume_profile_confluence,
            },
            # ✅ REMOVED: bb_mean_reversion, rsi_reversal, stochastic_reversal,
            # ema_crossover, volume_profile, wave_c, fvg_ifvg as standalone
            # top-level sections - each was just a trade_setup/data pair
            # that already lives inside its matching indicators.* entry
            # (indicators.bollinger_bands.mean_reversion_setup,
            # indicators.rsi.reversal_setup,
            # indicators.stochastic.reversal_setup,
            # indicators.trend.crossover_setup, indicators.volume_profile,
            # indicators.wave_c, indicators.fvg_ifvg).
            "config": {
                "symbol": symbol,
                # "ALL" or the one strategy group allowed to decide
                "strategy_selection": strategy_selection,
                "user_requested_direction": order_type,
                "executed_direction": effective_order_type,
                "timeframe": timeframe,
                "leverage": leverage,
                "fixed_trade_size_usd": fixed_trade_size_usd,
                "risk_per_trade_percent": int(risk_per_trade * 100),
                "max_risk_usd": round(fixed_trade_size_usd * risk_per_trade, 2),
                "breakout_period": BREAKOUT_PERIOD,
                "breakout_volume_threshold": BREAKOUT_VOLUME_THRESHOLD,
                # ✅ FIXED: MIN_ENTRY_CONFIDENCE is actually a TIMING-
                # confidence threshold (see timing_good = timing_confidence
                # >= MIN_ENTRY_CONFIDENCE), not a trade-probability
                # threshold despite its name -- labeled "min_timing_
                # confidence" here (not "min_entry_confidence") so the
                # output itself doesn't perpetuate that confusion.
                "min_timing_confidence": MIN_ENTRY_CONFIDENCE,
                # ✅ FIXED: was MIN_PROBABILITY_FOR_ENTRY, a constant that's
                # imported and displayed here but never actually enforced
                # anywhere in the pipeline -- the REAL gate is
                # TRADE_PROBABILITY_MINIMUM (see the post-chain probability
                # floor check). Both happened to be 75, masking the
                # disconnect; editing MIN_PROBABILITY_FOR_ENTRY would have
                # silently changed nothing while this field kept reporting
                # a now-false number. Both output keys now derive from the
                # one constant that's actually enforced, so they can never
                # silently diverge again.
                "min_probability_for_entry": probability_floor,
                "strong_entry_threshold": STRONG_ENTRY_THRESHOLD,
                "decision_wait_threshold": DECISION_WAIT_THRESHOLD,
                "decision_monitor_threshold": DECISION_MONITOR_THRESHOLD,
                "min_wick_ratio": WICK_REVERSAL_RATIO,
                "extreme_volatility_veto_threshold": EXTREME_VOLATILITY_VETO_THRESHOLD,
                "ranging_market_adx_threshold": RANGING_MARKET_ADX_THRESHOLD,
                "trade_probability_minimum": TRADE_PROBABILITY_MINIMUM,
                "valid_zone_grades": VALID_ZONE_GRADES,
                # under M1 only the GNN is never touched: even asking whether it is
                # available builds its graph from H1 bars
                "gnn_enabled": False if M1_ONLY else (use_gnn and is_gnn_available()),
                "gnn_available": False if M1_ONLY else is_gnn_available(),
                "gnn_ab_test_enabled": False if M1_ONLY else (is_gnn_available() and get_gnn_ab_test().get("enabled", False) if is_gnn_available() else False),
                "gnn_weight": GNN_WEIGHT,
                "gnn_confidence_threshold": GNN_CONFIDENCE_THRESHOLD,
                "pattern_weight": PATTERN_WEIGHT,
                "pattern_timeframes": PATTERN_TIMEFRAMES
            }
        }
        
        # decision_snapshot was deleted on 2026-09-15: it restated gates,
        # cases, scenarios and sensitivity that are computed from the rest
        # of the payload, so it could never teach a model anything new.
        try:

            # The coherence validator was deleted on 2026-09-15: its only
            # consumer was the conviction filter, also deleted below.

            # ============================================================
            # CALIBRATED DECISION (core/calibrated_model.entry_decision)
            # ============================================================
            # When the installed model runs in decision_mode "calibrated" the
            # validated model decides the entry; the legacy funnel above only
            # informs it. Runs before the defensive core, which can still
            # turn a YES into a NO.
            # Under M1_ONLY the installed model (fitted 2026-09-15 on the M5-H4
            # cascade, H1 and GNN features) is not scored: it runs in shadow
            # mode and decides nothing, and fed neutral values for the inputs
            # it weights, its recorded score would look valid and mean nothing.
            _cal_model = load_calibrated_model() if USE_CALIBRATED_PROBABILITY and not M1_ONLY else None
            _sg = result.get("strategy_groups") or {}
            if _cal_model and _cal_model.get("version") == 2 and _sg.get("edges") is not None:
                try:
                    from core.calibrated_model import score_row as _score_row
                    from core.result_leaves import model_row as _model_row
                    _row = _model_row(result, _sg["edges"], close=float(rates[-1][4]), pip=pip_size)
                    _sg["calibrated"] = _score_row(_row, effective_order_type, _cal_model)
                    result["strategy_groups"] = _sg
                except Exception as e:
                    logger.warning(f"[CALIBRATED] {symbol}: v2 scoring failed: {e}")
            _cal = _sg.get("calibrated")
            if _cal and _cal_model and _cal_model.get("decision_mode") == "calibrated":
                try:
                    from core.calibrated_model import entry_decision as _cal_entry, apply_entry as _cal_apply
                    _decision = _cal_entry(result, _cal, _cal_model)
                    result["calibrated_decision"] = _decision
                    if _decision["enter"]:
                        _cal_apply(result, _decision)
                    elif _entry_is_live(result):
                        _decline_entry(result, f"CALIBRATED - {_decision['reason']}")
                except Exception as e:
                    logger.warning(f"[CALIBRATED] {symbol}: decision failed, legacy decision kept: {e}")

            # ============================================================
            # DEFENSIVE CORE -- stages 9, 7, 8
            # ============================================================
            # Placed here, after coherence and before conviction,
            # because `result` is finally complete: the trade exists as
            # a concrete proposition (direction, stop, target, lot,
            # spread) AND every cross-check it depends on has run.
            #
            # Features come from flatten_decision() -- the same function
            # engine_replay records with -- so the Stage 7 model is
            # served exactly the shape it was trained on. See
            # core/decision_features.py on why that is a module and not
            # two copies.
            #
            # All three are evaluated unconditionally so their verdicts
            # are recorded even when an earlier gate already said no: a
            # filter you cannot measure on the trades it did not decide
            # is a filter you cannot tune. Only ENFORCEMENT is
            # conditional, and like conviction each can only ever turn a
            # YES into a NO.
            _facts = flatten_decision(result)

            # --- Stage 9: symbolic gate -------------------------
            try:
                symbolic = evaluate_symbolic_gate(_facts)
            except Exception as e:
                # A crash is not permission to trade. This gate exists
                # to PROVE the trade is arithmetically sound; if it
                # could not run, nothing has been proven.
                logger.warning(f"[SYMBOLIC] {symbol}: gate raised {e} -- failing closed")
                symbolic = {"passed": False, "violations": [],
                            "blocked_by": "gate_error",
                            "reason": f"symbolic gate could not run: {e}"}

            if USE_SYMBOLIC_GATE and not symbolic.get("passed"):
                if SYMBOLIC_GATE_SHADOW_MODE:
                    logger.info(f"[SYMBOLIC] {symbol}: WOULD block -- "
                                f"{symbolic['reason']} (shadow mode, trade allowed)")
                elif _entry_is_live(result):
                    logger.warning(f"[SYMBOLIC] {symbol}: blocked -- {symbolic['reason']}")
                    _decline_entry(result, f"SYMBOLIC GATE - {symbolic['reason']}")
                    result["final_verdict"]["symbolic_blocked"] = True
                    result["final_verdict"]["symbolic_reason"] = symbolic["reason"]

            # REMOVED: stages 7 (meta-labeling) and 8 (conformal).
            #
            # Stage 7 was the only trained model in the pipeline -- a
            # logistic regression fitted on replay outcomes -- and stage
            # 8 existed solely to calibrate its scores. This system is
            # rule-based by decision, so both are gone from the decision
            # path rather than left switched off.
            #
            # Nothing measurable is lost. Stage 7 never passed its own
            # validation gate: purged cross-validation scored it at
            # AUC 0.5034 against a shuffled-label control of 0.5092 --
            # worse than random labels -- so core/train_meta_label.py
            # correctly refused to write an artifact and the stage never
            # ran on a single decision.
            #
            # core/meta_labeling.py, core/conformal.py and
            # core/train_meta_label.py remain on disk as research
            # instruments, unreferenced by the live pipeline.

            # ============================================================
            # CONVICTION FILTER -- selectivity at constant R:R
            # ============================================================
            # The conviction filter was deleted on 2026-09-15. It consumed
            # coherence and gate margins to decline the least certain
            # entries; on the study it declined nothing that was measurably
            # worse, and the calibrated model now decides entries.

        except Exception as e:
            logger.warning(f"[ANALYSIS] post-assembly step failed: {e}")

        # What every group SEES, even when its label says nothing
        # (core/state_readings.py). Published, never scored: measured on the
        # live trade the best of these wins 45.9% against a 44.6% baseline.
        try:
            from core.state_readings import readings as _state_readings, summary as _state_summary
            _state = _state_readings(result)
            result["state_readings"] = {"groups": _state, **_state_summary(_state)}
        except Exception as e:
            logger.debug(f"[STATE] {symbol}: readings unavailable: {e}")

        # File every reading under the strategy group that trades it
        # (core/analysis_groups.py): one home per reading, the dead sections
        # dropped, and each group stating its own score beside its data.
        try:
            from core.analysis_groups import reshape as _reshape
            _reshape(result, (strategy_groups_result or {}).get("groups"))
        except Exception as e:
            logger.warning(f"[GROUPS] {symbol}: could not group the payload ({e}) -- leaving it flat")

        safe_result = make_json_safe(result)
        # Record setups the engine declined, so the gates after probability
        # can be measured on what they stopped (core/skipped_setups.py).
        # Live only; never raises.
        record_skipped_setup(safe_result, symbol=symbol, is_replay=market_data is not None,
                             is_already_in_trade=is_already_in_trade)
        # Every live decision on a target market, entered or not, with live
        # order flow and the engine stamp (core/decision_log.py,
        # strategic_plan_v5_live_data.md phase 1). Never raises.
        record_decision(safe_result, symbol=symbol, is_replay=market_data is not None,
                        is_already_in_trade=is_already_in_trade)
        return safe_result
        
    except Exception as e:
        import traceback
        logger.error(f"Error: {str(e)}")
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}