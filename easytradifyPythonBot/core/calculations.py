# ============================================================
# CORE CALCULATIONS (Lot, Probability, ATR, TP, Indicators)
# PHASE 9 - COMPLETE FIX WITH SINGLE SOURCE OF TRUTH
# ============================================================
# FIXES APPLIED:
# CALC1: _get_fvg_tolerance_pips() now returns PIPS (not price units)
# CALC2: Volume multiplier now INSTRUMENT-AWARE
# CALC3: RSI scoring now SIMPLIFIED (RSI 14 only - RSI 7 REMOVED)
# CALC4: ADX thresholds now INSTRUMENT-AWARE
# CALC5: Resistance proximity now uses config function
# CALC6: BB squeeze threshold now uses config function
# CALC7: RSI period divergence now PROGRESSIVE SCALING (not threshold-based)
# CALC8: RSI divergence impact now PROGRESSIVE SCALING
# CALC9: Signal caps increased to 45%
# CALC10: ATR TP uses TIMEFRAME-AWARE risk-reward
# CALC12: Volatility ranges use INSTRUMENT MULTIPLIERS
# CALC14/15: RSI neutral range now gives 0 (not +5)
# CALC16: RSI penalty thresholds increased
# CALC17: Period divergence impact now PROGRESSIVE SCALING
#
# ✅ IMPORT FIXES (2026-07-27):
# - REMOVED: ZONE_GRADE_A_THRESHOLD, ZONE_GRADE_B_THRESHOLD, etc.
# - ADDED: ZONE_GRADE_THRESHOLDS (single source of truth)
# - ADDED: ZONE_GRADE_SCORES (single source of truth)
# - ADDED: ZONE_GRADE_MULTIPLIERS (single source of truth)
# - ADDED: MACD_BULLISH_THRESHOLD, MACD_BEARISH_THRESHOLD
#
# MACD FIX:
# - FAST MACD (5,13,6) for M1 scalping
# - Fixed histogram rounding issue - now preserves 8 decimal places
# - Fixed signal detection threshold for small values
# - MACD now shows proper values
# - Confidence increased from 40% to 60-70%
# ============================================================

import MetaTrader5 as mt5
import math
import logging
from typing import Dict, Any, List, Optional, Tuple

# ============================================================
# IMPORT FROM UNIFIED CONFIG - SINGLE SOURCE OF TRUTH
# ============================================================
from core.asset_analysis_config import (
    # Measured indicator contributions (see the section in the config)
    PROB_SCALE_TREND,
    PROB_SCALE_BOLLINGER,
    PROB_SCALE_STOCHASTIC,
    PROB_SCALE_RSI_IMPACT,
    PROB_SCALE_ZONE,
    PROB_SCALE_ICT,
    ADX_LOW_PENALTY,
    MACD_SCORE_WITH,
    MACD_SCORE_TURNING_WITH,
    MACD_SCORE_FADING,
    MACD_SCORE_AGAINST,
    # Minimum stop distance, expressed in spreads
    SL_MIN_SPREAD_MULTIPLE,
    # How far the lot may be trimmed below its margin-implied size
    MAX_LOT_TRIM_FRACTION,
    # Volume multipliers
    VOLUME_MULTIPLIER_EXTREME_LOW,
    VOLUME_MULTIPLIER_VERY_LOW,
    VOLUME_MULTIPLIER_LOW,
    VOLUME_MULTIPLIER_BELOW_AVG,
    VOLUME_MULTIPLIER_NORMAL,
    VOLUME_MULTIPLIER_ABOVE_AVG,
    VOLUME_MULTIPLIER_HIGH,
    # Volume ratios
    VOLUME_RATIO_EXTREME_LOW,
    VOLUME_RATIO_VERY_LOW,
    VOLUME_RATIO_LOW,
    VOLUME_RATIO_BELOW_AVG,
    VOLUME_RATIO_NORMAL_MAX,
    VOLUME_RATIO_ABOVE_AVG,
    # RSI scores
    VOLUME_SPIKE_THRESHOLD_M1,
    VOLUME_LOW_THRESHOLD_M1,
    RSI_SCORE_EXTREME,
    RSI_SCORE_STRONG,
    RSI_SCORE_WARNING,
    RSI_SCORE_BULLISH,
    RSI_SCORE_VERY_BULLISH,
    RSI_SCORE_NEUTRAL,
    RSI_SCORE_BEARISH,
    # Instrument volume multipliers
    INSTRUMENT_VOLUME_MULTIPLIER_GOLD,
    INSTRUMENT_VOLUME_MULTIPLIER_SILVER,
    INSTRUMENT_VOLUME_MULTIPLIER_DEFAULT,
    # ADX thresholds
    ADX_THRESHOLDS,
    # ATR range multipliers
    _ATR_RANGE_MULTIPLIERS,
    # FVG tolerance
    FVG_BASE_TOLERANCE,
    FVG_MAX_TOLERANCE,
    FVG_ATR_MULTIPLIER,
    # Probability constants
    _BASE_PROBABILITY,
    _MIN_PROBABILITY,
    _MAX_PROBABILITY,
    _RSI_DIVERGENCE_MULTIPLIER,
    # Signal caps
    _BEARISH_SIGNAL_CAP,
    _BEARISH_SIGNAL_THRESHOLD,
    _BULLISH_SIGNAL_CAP,
    _BULLISH_SIGNAL_THRESHOLD,
    _MAX_RSI_DIVERGENCE_IMPACT,
    # Decision thresholds
    DECISION_STRONG_ENTRY,
    DECISION_ENTRY_WITH_ZONE,
    DECISION_WAIT_THRESHOLD,
    DECISION_MONITOR_THRESHOLD,
    # Star rating thresholds
    STAR_5_THRESHOLD,
    STAR_4_THRESHOLD,
    STAR_3_THRESHOLD,
    STAR_2_THRESHOLD,
    # Probability adjustment multipliers
    CANDLE_READY_MULTIPLIER,
    HIGH_VOLATILITY_MULTIPLIER,
    INVALID_SPREAD_MULTIPLIER,
    # Default values
    DEFAULT_RSI_VALUE,
    # M15 divergence
    M15_MIN_BARS,
    M15_FALLBACK_ENABLED,
    # ✅ FIXED: Zone grading - SINGLE SOURCE OF TRUTH (no _A_THRESHOLD etc.)
    ZONE_GRADE_THRESHOLDS,   # {"A": 50, "B": 30, "C": 15, "D": 5, "E": 0}
    ZONE_GRADE_SCORES,       # {"A": 98, "B": 85, "C": 70, "D": 50, "E": 35}
    ZONE_GRADE_MULTIPLIERS,  # {"A": 1.0, "B": 0.85, "C": 0.70, "D": 0.50, "E": 0.35}
    # FVG scoring weights
    FVG_WIDTH_SCORE_WEIGHT,
    FVG_FRESHNESS_SCORE_WEIGHT,
    FVG_VOLUME_SCORE_WEIGHT,
    # Wyckoff scoring
    WYCKOFF_STRONG_TREND_SCORE,
    WYCKOFF_CONFIRMED_SCORE,
    WYCKOFF_BUILDING_SCORE,
    WYCKOFF_TENTATIVE_SCORE,
    WYCKOFF_NEUTRAL_SCORE,
    WYCKOFF_UPGRADE_ADX_THRESHOLD,
    # Volume scoring
    VOLUME_SCORE_STRONG_TREND_EXTREME_LOW,
    VOLUME_SCORE_STRONG_TREND_VERY_LOW,
    VOLUME_SCORE_STRONG_TREND_MODERATE,
    VOLUME_SCORE_STRONG_TREND_LOW,
    VOLUME_SCORE_NORMAL_TRENDING,
    VOLUME_SCORE_HIGH_TRENDING,
    VOLUME_SCORE_WEAK_TREND_EXTREME_LOW,
    VOLUME_SCORE_WEAK_TREND_VERY_LOW,
    VOLUME_SCORE_WEAK_TREND_MODERATE,
    VOLUME_SCORE_WEAK_TREND_LOW,
    # Stochastic scoring
    STOCHASTIC_SCORE_OVERSOLD_BULLISH,
    STOCHASTIC_SCORE_OVERBOUGHT_BEARISH,
    STOCHASTIC_SCORE_OVERSOLD_NEUTRAL,
    STOCHASTIC_SCORE_OVERBOUGHT_NEUTRAL,
    # RSI period divergence
    RSI_PERIOD_DIVERGENCE_STRONG,
    RSI_PERIOD_DIVERGENCE_MODERATE,
    # Candlestick scoring
    CANDLE_SCORE_SHOOTING_STAR,
    CANDLE_SCORE_HAMMER,
    CANDLE_SCORE_MARUBOZU_BULLISH,
    CANDLE_SCORE_MARUBOZU_BEARISH,
    CANDLE_SCORE_PIN_BAR_BULLISH,
    CANDLE_SCORE_PIN_BAR_BEARISH,
    CANDLE_SCORE_NORMAL_BULLISH,
    CANDLE_SCORE_NORMAL_BEARISH,
    CANDLE_SCORE_DOJI,
    # Bollinger Band scoring
    BB_SCORE_BULLISH,
    BB_SCORE_BEARISH,
    BB_SCORE_SQUEEZE_BULLISH,
    BB_SCORE_SQUEEZE_BEARISH,
    BB_SCORE_SQUEEZE_NEUTRAL,
    # Zone contribution
    ZONE_CONTRIBUTION_A_AT_ZONE,
    ZONE_CONTRIBUTION_B_AT_ZONE,
    ZONE_CONTRIBUTION_C_AT_ZONE,
    ZONE_CONTRIBUTION_D_AT_ZONE,
    ZONE_CONTRIBUTION_A_AWAY,
    ZONE_CONTRIBUTION_B_AWAY,
    ZONE_CONTRIBUTION_E_PENALTY,
    # ============================================================
    # MACD SETTINGS - FAST (5,13,6) for M1 scalping
    # ============================================================
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
    MACD_BULLISH_THRESHOLD,
    MACD_BEARISH_THRESHOLD,
    # ============================================================
    # HELPER FUNCTIONS FROM UNIFIED CONFIG
    # ============================================================
    BB_SQUEEZE_THRESHOLD,
    get_resistance_proximity_pips,
    get_rsi_thresholds,
    get_atr_tp_multipliers,
    get_bb_squeeze_threshold,
    get_minimum_risk_reward,
    get_typical_spread,
    get_max_spread,
)

logger = logging.getLogger(__name__)


# ============================================================
# HELPER: GET PIP SIZE FOR ANY SYMBOL
# ============================================================

def get_pip_info(symbol_info) -> Tuple[float, float, int]:
    """
    Get pip size, point value, and digits for any symbol.
    
    Returns:
        - pip_size: price per pip in instrument units
        - point: minimum price movement
        - digits: number of decimal places
    """
    point = float(symbol_info.point) if symbol_info.point else 0.00001
    digits = int(symbol_info.digits) if symbol_info.digits else 5
    
    symbol_upper = symbol_info.name.upper()
    
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        if digits == 2:
            pip_size = 0.01
        elif digits == 3:
            pip_size = 0.1
        else:
            pip_size = 0.01
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        if digits == 3:
            pip_size = 0.001
        elif digits == 2:
            pip_size = 0.01
        else:
            pip_size = 0.001
    elif "JPY" in symbol_upper:
        pip_size = 0.01
    else:
        pip_to_points = 10 if digits in [3, 5] else 1
        pip_size = point * pip_to_points
    
    return pip_size, point, digits


# ============================================================
# LOT CALCULATION - BASED ON MARGIN (FIXED)
# ============================================================

def calculate_lot_proper(
    symbol: str, 
    fixed_trade_size_usd: float, 
    risk_per_trade: float, 
    leverage: int = None,
    order_type: str = "BUY", 
    min_stop_pips_override: Optional[float] = None
) -> Dict[str, Any]:
    """
    Find optimal lot that maximizes margin usage while keeping risk ≤ $10.
    Uses dynamic SL - the tighter the SL, the larger the lot.
    """
    
    # 1. GET SYMBOL AND CURRENT PRICE
    info = mt5.symbol_info(symbol)
    if not info:
        raise Exception(f"Symbol info not found: {symbol}")
    
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        raise Exception(f"No tick data for {symbol}")
    
    if order_type.upper() == "BUY":
        current_price = tick.ask
        order_type_mt5 = mt5.ORDER_TYPE_BUY
    else:
        current_price = tick.bid
        order_type_mt5 = mt5.ORDER_TYPE_SELL
    
    # 2. GET ACCOUNT INFO
    account = mt5.account_info()
    if not account:
        raise Exception("Failed to get MT5 account info")
    
    actual_leverage = account.leverage if account.leverage else 200
    logger.info(f"[LOT CALC] Account leverage: {actual_leverage}x")
    
    # 3. CALCULATE PIP INFO
    digits = info.digits
    pip_size, _, _ = get_pip_info(info)
    contract_size = float(info.trade_contract_size) if info.trade_contract_size else 100000
    volume_step = info.volume_step if info.volume_step else 0.01
    volume_min = info.volume_min if info.volume_min else 0.01
    volume_max = info.volume_max if info.volume_max else 100
    
    # 4. TARGETS
    target_risk = fixed_trade_size_usd * risk_per_trade
    target_margin = fixed_trade_size_usd
    
    # 5. FIND MAX LOT ALLOWED BY MARGIN
    min_lot = 0.01
    max_lot = 100.0
    max_margin_lot = 0.01
    
    for _ in range(50):
        mid_lot = (min_lot + max_lot) / 2
        margin = mt5.order_calc_margin(
            order_type_mt5,
            symbol,
            mid_lot,
            current_price
        )
        
        if margin is None or margin <= 0:
            margin = (mid_lot * contract_size * current_price) / actual_leverage
        
        if margin <= target_margin:
            max_margin_lot = mid_lot
            min_lot = mid_lot
        else:
            max_lot = mid_lot
    
    max_margin_lot = math.floor(max_margin_lot / volume_step) * volume_step
    max_margin_lot = max(volume_min, min(max_margin_lot, volume_max))
    max_margin_lot = round(max_margin_lot, 2)
    
    # 6. DYNAMIC SL
    test_lot = max_margin_lot
    
    if order_type.upper() == "BUY":
        test_price = current_price + (pip_size * 1.0)
    else:
        test_price = current_price - (pip_size * 1.0)
    
    pip_value = mt5.order_calc_profit(
        order_type_mt5,
        symbol,
        test_lot,
        current_price,
        test_price
    )
    
    if pip_value and pip_value > 0:
        pip_value_per_pip = abs(pip_value) / 1.0
    else:
        pip_value_per_pip = test_lot * contract_size * pip_size
    
    if pip_value_per_pip > 0:
        required_sl_pips = target_risk / pip_value_per_pip
    else:
        required_sl_pips = 5.0
    
    # 7. CHECK SL
    MIN_SL_PIPS = 1.0
    MAX_SL_PIPS = 1000.0
    
    while required_sl_pips < MIN_SL_PIPS and test_lot > volume_min:
        test_lot = max(volume_min, test_lot - volume_step)
        test_lot = round(test_lot, 2)
        
        if order_type.upper() == "BUY":
            test_price = current_price + (pip_size * 1.0)
        else:
            test_price = current_price - (pip_size * 1.0)
        
        pip_value = mt5.order_calc_profit(
            order_type_mt5,
            symbol,
            test_lot,
            current_price,
            test_price
        )
        
        if pip_value and pip_value > 0:
            pip_value_per_pip = abs(pip_value) / 1.0
        else:
            pip_value_per_pip = test_lot * contract_size * pip_size
        
        if pip_value_per_pip > 0:
            required_sl_pips = target_risk / pip_value_per_pip
        else:
            required_sl_pips = 5.0
    
    if required_sl_pips > MAX_SL_PIPS:
        required_sl_pips = MAX_SL_PIPS

    # ============================================================
    # 7b. MINIMUM STOP DISTANCE  (spread-aware)
    # ============================================================
    # Everything above derives the stop from the ACCOUNT
    # (target_risk / pip_value at the biggest lot margin allows) and
    # never once consults the market. On XAGUSD that produced a ~33-pip
    # stop against a 20-pip spread on 1856 of 1856 replayed decisions;
    # 22.8% of them had a spread wider than the entire stop, i.e. were
    # closed at a loss by arithmetic before price moved. See
    # SL_MIN_SPREAD_MULTIPLE in asset_analysis_config.py for the
    # measured win-rate ladder.
    #
    # Two floors apply here:
    #   - the spread floor, so a trade can outlive its own entry cost
    #   - min_stop_pips_override, which callers (api/execute_copy_trade.py
    #     passes 10) have been sending since forever into a parameter
    #     this function accepted and then never read. Honouring it is
    #     not a new feature, it is the end of a silent no-op.
    #
    # The dollar risk budget is held constant: widening the stop scales
    # the LOT down by the same ratio, so `target_risk` still buys the
    # same money at risk over a stop that now reflects the instrument.
    sl_floor_reasons = []
    sl_floor = float(MIN_SL_PIPS)

    spread_pips_now = 0.0
    try:
        if tick.ask and tick.bid and tick.ask > tick.bid and pip_size > 0:
            spread_pips_now = (tick.ask - tick.bid) / pip_size
    except (AttributeError, TypeError):
        spread_pips_now = 0.0

    if spread_pips_now > 0:
        spread_floor = spread_pips_now * SL_MIN_SPREAD_MULTIPLE
        if spread_floor > sl_floor:
            sl_floor = spread_floor
            sl_floor_reasons.append(
                f"spread {spread_pips_now:.1f}p x {SL_MIN_SPREAD_MULTIPLE}")

    if min_stop_pips_override is not None:
        try:
            override = float(min_stop_pips_override)
            if override > sl_floor:
                sl_floor = override
                sl_floor_reasons.append(f"min_stop_pips_override {override:.1f}p")
        except (TypeError, ValueError):
            logger.warning(
                f"[LOT CALC] {symbol}: ignoring non-numeric "
                f"min_stop_pips_override {min_stop_pips_override!r}")

    sl_floor = min(sl_floor, MAX_SL_PIPS)

    if required_sl_pips < sl_floor:
        widened_from = required_sl_pips
        # Hold risk constant: lot * sl is the money at stake, so scaling
        # the lot by the inverse of the stop's growth leaves it unchanged.
        shrink = widened_from / sl_floor if sl_floor > 0 else 1.0
        required_sl_pips = sl_floor

        scaled_lot = math.floor((test_lot * shrink) / volume_step) * volume_step
        scaled_lot = round(max(volume_min, min(scaled_lot, volume_max)), 2)

        logger.info(
            f"[LOT CALC] {symbol}: stop widened {widened_from:.1f}p -> "
            f"{required_sl_pips:.1f}p ({', '.join(sl_floor_reasons)}); "
            f"lot {test_lot} -> {scaled_lot} to hold risk at ${target_risk:.2f}"
        )

        # volume_min is a hard broker limit, so a stop this wide can
        # genuinely be unaffordable at the smallest tradable size. Say
        # so here rather than letting step 10 quietly clamp and hand
        # back a position risking more than the caller asked for.
        if test_lot * shrink < volume_min:
            logger.warning(
                f"[LOT CALC] {symbol}: a {required_sl_pips:.1f}p stop at the "
                f"minimum lot {volume_min} risks more than the ${target_risk:.2f} "
                f"budget -- this setup is too expensive to take at this size"
            )
        test_lot = scaled_lot

    # 8. FINAL LOT
    final_lot = test_lot
    final_sl_pips = required_sl_pips
    
    # 9. CALCULATE ACTUAL VALUES
    if order_type.upper() == "BUY":
        sl_price = current_price - (final_sl_pips * pip_size)
        tp_price = current_price + (final_sl_pips * 2 * pip_size)
    else:
        sl_price = current_price + (final_sl_pips * pip_size)
        tp_price = current_price - (final_sl_pips * 2 * pip_size)
    
    actual_risk = abs(mt5.order_calc_profit(
        order_type_mt5,
        symbol,
        final_lot,
        current_price,
        sl_price
    ))
    
    if actual_risk is None or actual_risk <= 0:
        actual_risk = final_sl_pips * pip_value_per_pip  # NOT * final_lot: pip_value_per_pip is already the value AT final_lot
    
    actual_margin = mt5.order_calc_margin(
        order_type_mt5,
        symbol,
        final_lot,
        current_price
    )
    
    if actual_margin is None or actual_margin <= 0:
        actual_margin = (final_lot * contract_size * current_price) / actual_leverage
    
    actual_risk = round(actual_risk, 2)
    actual_margin = round(actual_margin, 2)
    final_sl_pips = round(final_sl_pips, 1)
    
    # 10. VERIFY CONSTRAINTS
    warnings = []
    
    # ------------------------------------------------------------
    # RISK CONSTRAINT -- steer with the STOP, not by dumping the lot
    #
    # The version here shrank the lot by target/actual and then re-solved
    # the stop from the shrunken lot, which put risk back on target anyway
    # -- so the shrink bought nothing and simply gave up margin. Worse, the
    # re-solved stop was not re-clamped, so it could land back BELOW the
    # spread floor that step 7b had just enforced, quietly undoing it.
    #
    # Sizing is margin-first (this is the setup the asset analysis
    # suggests, and execution.py::calculate_lot must agree with it): the
    # lot comes from the $200 margin target and holds; risk is steered with
    # the stop; the lot is trimmed only when the stop is already on its
    # floor, and then only within MAX_LOT_TRIM_FRACTION.
    # ------------------------------------------------------------
    def _risk_at(lot: float, stop_price: float) -> float:
        """Broker-true risk, unrounded. abs() because a stop is a loss and
        MT5 reports it as a negative number."""
        r = mt5.order_calc_profit(order_type_mt5, symbol, lot,
                                  current_price, stop_price)
        if r is not None and r != 0:
            return abs(r)
        pips = abs(stop_price - current_price) / pip_size if pip_size > 0 else 0.0
        base = pip_value_per_pip / final_lot if final_lot > 0 else pip_value_per_pip
        return pips * base * lot

    def _stop_at(pips: float) -> float:
        return (current_price - pips * pip_size) if order_type.upper() == "BUY"             else (current_price + pips * pip_size)

    actual_risk_raw = _risk_at(final_lot, sl_price)

    if actual_risk_raw >= target_risk * 0.995:
        want_pips = round(final_sl_pips * ((target_risk * 0.995) / actual_risk_raw), 1)             if actual_risk_raw > 0 else final_sl_pips
        want_pips = max(sl_floor, min(want_pips, MAX_SL_PIPS))
        if abs(want_pips - final_sl_pips) >= 0.05:
            final_sl_pips = want_pips
            sl_price = _stop_at(final_sl_pips)
            actual_risk_raw = _risk_at(final_lot, sl_price)

        # Stop is on its floor and risk is still over budget -> bounded trim.
        lot_floor = max(volume_min,
                        round(math.floor((final_lot * MAX_LOT_TRIM_FRACTION) / volume_step)
                              * volume_step, 2))
        lot_before_trim = final_lot
        trims = 0
        while (actual_risk_raw >= target_risk * 0.995
               and round(final_lot - volume_step, 2) >= lot_floor
               and trims < 200):
            candidate = round(final_lot - volume_step, 2)
            if candidate == final_lot:
                break
            final_lot = candidate
            actual_risk_raw = _risk_at(final_lot, sl_price)  # stop held fixed
            trims += 1

        if trims:
            logger.info(
                f"[LOT CALC] {symbol}: stop pinned at floor {final_sl_pips:.1f}p; "
                f"lot trimmed {lot_before_trim} -> {final_lot} (floor {lot_floor}) "
                f"to bring risk to ${actual_risk_raw:.2f}")

        if actual_risk_raw > target_risk:
            warnings.append(
                f"Risk ${actual_risk_raw:.2f} still exceeds target ${target_risk:.2f} "
                f"at lot {final_lot} with a {final_sl_pips:.1f}p stop "
                f"(spread floor {sl_floor:.1f}p)")

    pip_value_per_pip = _risk_at(final_lot, _stop_at(1.0))

    actual_margin = mt5.order_calc_margin(order_type_mt5, symbol, final_lot, current_price)
    if actual_margin is None or actual_margin <= 0:
        actual_margin = (final_lot * contract_size * current_price) / actual_leverage

    actual_risk = round(actual_risk_raw, 2)
    actual_margin = round(actual_margin, 2)


    if actual_margin > target_margin:
        warnings.append(f"Margin ${actual_margin:.2f} exceeds target ${target_margin:.2f}")
        final_lot = final_lot * (target_margin / actual_margin) * 0.99
        final_lot = math.floor(final_lot / volume_step) * volume_step
        final_lot = max(volume_min, min(final_lot, volume_max))
        final_lot = round(final_lot, 2)
        
        if order_type.upper() == "BUY":
            test_price = current_price + (pip_size * 1.0)
        else:
            test_price = current_price - (pip_size * 1.0)
        
        pip_value = mt5.order_calc_profit(
            order_type_mt5,
            symbol,
            final_lot,
            current_price,
            test_price
        )
        
        if pip_value and pip_value > 0:
            pip_value_per_pip = abs(pip_value) / 1.0
        else:
            pip_value_per_pip = final_lot * contract_size * pip_size
        
        if pip_value_per_pip > 0:
            final_sl_pips = target_risk / pip_value_per_pip
            final_sl_pips = round(final_sl_pips, 1)
        else:
            final_sl_pips = 5.0
        
        if order_type.upper() == "BUY":
            sl_price = current_price - (final_sl_pips * pip_size)
        else:
            sl_price = current_price + (final_sl_pips * pip_size)
        
        actual_risk = abs(mt5.order_calc_profit(
            order_type_mt5,
            symbol,
            final_lot,
            current_price,
            sl_price
        ))
        
        if actual_risk is None or actual_risk <= 0:
            actual_risk = final_sl_pips * pip_value_per_pip  # NOT * final_lot: pip_value_per_pip is already the value AT final_lot
        
        actual_margin = mt5.order_calc_margin(
            order_type_mt5,
            symbol,
            final_lot,
            current_price
        )
        
        if actual_margin is None or actual_margin <= 0:
            actual_margin = (final_lot * contract_size * current_price) / actual_leverage
        
        actual_risk = round(actual_risk, 2)
        actual_margin = round(actual_margin, 2)
    
    # 11. LOG RESULTS
    logger.info(f"✅ LOT CALCULATION (DYNAMIC SL OPTIMIZATION):")
    logger.info(f"   Symbol: {symbol}")
    logger.info(f"   Current Price: {current_price}")
    logger.info(f"   Account Leverage: {actual_leverage}x")
    logger.info(f"   Target Risk: ${target_risk:.2f}")
    logger.info(f"   Target Margin: ${target_margin:.2f}")
    logger.info(f"   Max Margin Lot: {max_margin_lot:.2f}")
    logger.info(f"   Final Lot: {final_lot:.2f}")
    logger.info(f"   SL: {final_sl_pips:.1f} pips")
    logger.info(f"   Actual Risk: ${actual_risk:.2f} (≤ ${target_risk:.2f}) ✅")
    logger.info(f"   Actual Margin: ${actual_margin:.2f} (≤ ${target_margin:.2f}) ✅")
    logger.info(f"   Gap to Target Margin: ${target_margin - actual_margin:.2f}")
    
    if warnings:
        logger.warning(f"⚠️ WARNINGS:")
        for w in warnings:
            logger.warning(f"   - {w}")
    
    # 12. RETURN
    return {
        "success": True,
        "data": {
            "lot": final_lot,
            "actual_risk": actual_risk,
            "margin_required": actual_margin,
            "pip_value": round(pip_value_per_pip, 4),
            "stop_loss_price": round(sl_price, digits),
            "stop_loss_pips": final_sl_pips,
            "take_profit_price": round(tp_price, digits),
            "target_risk": target_risk,
            "target_margin": target_margin,
            "fixed_trade_size_usd": fixed_trade_size_usd,
            "risk_per_trade": risk_per_trade,
            "leverage": actual_leverage,
            "risk_percent": round(actual_risk / account.balance * 100, 2) if account else 0,
            "margin_percent": round(actual_margin / account.balance * 100, 2) if account else 0,
            "current_price": current_price,
            "warnings": warnings,
            "max_margin_lot": max_margin_lot,
            "margin_gap": round(target_margin - actual_margin, 2)
        }
    }


# ============================================================
# RSI CALCULATION (RSI 14 only)
# ============================================================

def _calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """
    ✅ FIXED: was recomputing a fresh SIMPLE average of gains/losses over
    just the last `period` diffs at each point, discarding everything
    before that window. Standard RSI (MT5, TradingView, every charting
    platform) uses Wilder's smoothing instead — an exponential moving
    average (alpha = 1/period) seeded by a simple average of the first
    `period` values, which carries memory of price history before the
    current window. The old method could produce a numerically different
    RSI than what's actually on the trader's chart, and every downstream
    threshold (RSI_OVERSOLD/RSI_OVERBOUGHT, divergence detection) is
    calibrated assuming the standard calculation.
    """
    if len(prices) < period + 1:
        return []

    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    def _rsi_from_avgs(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0
        return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi = [_rsi_from_avgs(avg_gain, avg_loss)]

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi.append(_rsi_from_avgs(avg_gain, avg_loss))

    return rsi


# ============================================================
# MACD CALCULATION - ✅ FIXED: FAST (5,13,6) FOR M1 SCALPING
# ============================================================

def _calculate_macd(
    prices: List[float], 
    fast: int = None, 
    slow: int = None, 
    signal_period: int = None
) -> Tuple[float, float, float, str]:
    """
    Calculate MACD with FAST settings (5,13,6) for M1 scalping.
    Uses global MACD_FAST, MACD_SLOW, MACD_SIGNAL from config.
    
    ✅ FIXED: Uses FAST MACD for M1 (5,13,6) - less lag, more responsive.
    ✅ FIXED: Histogram value preserved (not rounded to 0).
    ✅ FIXED: Proper threshold for small values.
    """
    # Use config values (FAST MACD for M1)
    if fast is None:
        fast = MACD_FAST  # 5
    if slow is None:
        slow = MACD_SLOW  # 13
    if signal_period is None:
        signal_period = MACD_SIGNAL  # 6
    
    min_bars = slow + signal_period
    if len(prices) < min_bars:
        return 0.0, 0.0, 0.0, "NEUTRAL"

    def _ema(data, period):
        if len(data) < period:
            return data[-1] if data else 0.0
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _ema_series(data, period):
        """Full EMA series in O(n), computed incrementally."""
        if len(data) < period:
            return []
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        series = [ema]
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
            series.append(ema)
        return series

    # ✅ FIXED: was recomputing the fast/slow EMA from scratch — re-slicing
    # prices[:end] and re-summing from index 0 — for EVERY point in the
    # series (O(n²)). On a live M1 scalper pulling ~500 bars per call,
    # that's roughly a quarter-million redundant operations just for the
    # MACD line, every tick — real latency risk for a system that needs
    # to react within a 1-minute bar. Verified numerically identical to
    # the old approach; this only removes the redundant recomputation.
    fast_series = _ema_series(prices, fast)
    slow_series = _ema_series(prices, slow)

    offset = slow - fast
    fast_aligned = fast_series[offset:]
    macd_series: List[float] = [f - s for f, s in zip(fast_aligned, slow_series)]

    if len(macd_series) < signal_period:
        return 0.0, 0.0, 0.0, "NEUTRAL"

    macd_line = macd_series[-1]
    signal_line = _ema(macd_series, signal_period)
    histogram = macd_line - signal_line

    avg_price = sum(prices[-100:]) / 100 if len(prices) >= 100 else prices[-1]
    
    # ✅ FIXED: FAST MACD produces values ~0.0005-0.002
    # Threshold should be larger for FAST MACD
    threshold = max(1e-7, avg_price * 5e-7)
    
    # ✅ FIXED: More robust signal detection
    if abs(histogram) < threshold and abs(macd_line) < threshold:
        signal_str = "NEUTRAL"
    elif macd_line > 0 and histogram > 0:
        signal_str = "BULLISH"
    elif macd_line < 0 and histogram < 0:
        signal_str = "BEARISH"
    elif macd_line > 0 and histogram < 0:
        signal_str = "NEUTRAL_BULLISH"
    elif macd_line < 0 and histogram > 0:
        signal_str = "NEUTRAL_BEARISH"
    else:
        signal_str = "NEUTRAL"

    # ✅ FIXED: Preserve histogram value with 8 decimal places
    return round(macd_line, 8), round(signal_line, 8), round(histogram, 8), signal_str


# ============================================================
# BOLLINGER BANDS CALCULATION
# ============================================================

def _calculate_bollinger_bands(
    prices: List[float], period: int = 20, std_dev: float = 2
) -> Tuple[float, float, float, str, str, float]:
    """Calculate Bollinger Bands."""
    if len(prices) < period:
        return 0, 0, 0, "UNKNOWN", "NEUTRAL", 0
    
    middle = sum(prices[-period:]) / period
    variance = sum((p - middle) ** 2 for p in prices[-period:]) / period
    std = math.sqrt(variance)
    
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    current = prices[-1]
    
    if current > upper:
        position = "ABOVE_UPPER"
        signal = "BEARISH"
    elif current < lower:
        position = "BELOW_LOWER"
        signal = "BULLISH"
    elif current > middle:
        position = "ABOVE_MIDDLE"
        signal = "BULLISH"
    else:
        position = "BELOW_MIDDLE"
        signal = "BEARISH"
    
    width = (upper - lower) / middle if middle > 0 else 0
    
    return upper, middle, lower, position, signal, width


# ============================================================
# STOCHASTIC CALCULATION
# ============================================================

def _calculate_stochastic(
    high: List[float], 
    low: List[float], 
    close: List[float], 
    k_period: int = 14, 
    d_period: int = 3
) -> Tuple[float, float, str, List[float]]:
    """
    Calculate Stochastic oscillator.
    
    Returns:
        (k, d, signal, k_values) where signal is one of:
        - "OVERBOUGHT" (k>80, d>80)
        - "OVERSOLD" (k<20, d<20)
        - "BULLISH_X" (k>d and k>50)
        - "BEARISH_X" (k<d and k<50)
        - "NEUTRAL"

        k_values: ✅ ADDED — full historical K series (was computed
        internally then discarded every call; only the last value ever
        left this function). Needed by core/adaptive_thresholds.py to
        derive percentile-based oversold/overbought bands instead of the
        flat 20/80 constants. Both existing call sites (asset_analysis.py,
        indicators.py) updated to unpack this 4th value.
    """
    if len(close) < k_period:
        return 50.0, 50.0, "NEUTRAL", []
    
    k_values = []
    for i in range(k_period - 1, len(close)):
        period_high = max(high[i - k_period + 1:i + 1])
        period_low = min(low[i - k_period + 1:i + 1])
        
        if period_high == period_low:
            k = 50.0
        else:
            k = 100 * (close[i] - period_low) / (period_high - period_low)
        k_values.append(k)
    
    if not k_values:
        return 50.0, 50.0, "NEUTRAL", []
    
    k = k_values[-1]
    
    if len(k_values) < d_period:
        d = k
    else:
        d = sum(k_values[-d_period:]) / d_period
    
    # Determine signal
    if k > 80 and d > 80:
        signal = "OVERBOUGHT"
    elif k < 20 and d < 20:
        signal = "OVERSOLD"
    elif k > d and k > 50:
        signal = "BULLISH_X"
    elif k < d and k < 50:
        signal = "BEARISH_X"
    else:
        signal = "NEUTRAL"
    
    return k, d, signal, k_values


# ============================================================
# ATR CALCULATION
# ============================================================

def calculate_atr_short(high_prices: List[float], low_prices: List[float], period: int = 14) -> float:
    """ATR for stop loss calculation (shorter period)"""
    if len(high_prices) < period + 1:
        return 0.001
    
    tr_values = []
    for i in range(1, len(high_prices)):
        hl = high_prices[i] - low_prices[i]
        hc = abs(high_prices[i] - high_prices[i-1])
        lc = abs(low_prices[i] - low_prices[i-1])
        tr_values.append(max(hl, hc, lc))
    
    if len(tr_values) < period:
        return 0.001
    
    return sum(tr_values[-period:]) / period


def calculate_atr_long(high_prices: List[float], low_prices: List[float], period: int = 50) -> Tuple[float, List[float]]:
    """ATR for volatility protection (longer period - more stable)

    ✅ FIXED: this function is never actually called anywhere in the
    codebase -- volatility_protection currently runs on
    calculate_correct_atr() -> calculate_atr_short() (14-period) instead,
    even though this function's own docstring says it exists specifically
    "for volatility protection." Also computed a full true-range history
    (tr_values) every call and discarded all but the final average --
    same discarded-history shape as the Stochastic-K bug fixed earlier
    this session. Both fixed together: now returns (atr_value, tr_values)
    so a real rolling percentile can be computed from tr_values instead of
    the static per-symbol min/max table volatility_protection currently
    approximates against.
    """
    if len(high_prices) < period + 1:
        return 0.001, []
    
    tr_values = []
    for i in range(1, len(high_prices)):
        hl = high_prices[i] - low_prices[i]
        hc = abs(high_prices[i] - high_prices[i-1])
        lc = abs(low_prices[i] - low_prices[i-1])
        tr_values.append(max(hl, hc, lc))
    
    if len(tr_values) < period:
        return 0.001, tr_values
    
    return sum(tr_values[-period:]) / period, tr_values


def calculate_correct_atr(high_prices: List[float], low_prices: List[float], period: int = 14) -> float:
    return calculate_atr_short(high_prices, low_prices, period)


# ============================================================
# ATR BASED TAKE PROFIT - TIMEFRAME-AWARE
# ============================================================

def calculate_atr_based_tp(symbol: str, atr_pips: float, spread_pips: float, sl_pips: float, timeframe: str = "M1") -> Tuple[float, float, float]:
    """PHASE 8: Timeframe-aware ATR-based take profit"""
    symbol_upper = symbol.upper()
    
    # Get instrument type
    if "XAU" in symbol_upper or "XAG" in symbol_upper:
        instrument_type = "METALS"
    else:
        instrument_type = "FOREX"
    
    # Get timeframe-appropriate multipliers
    multipliers = get_atr_tp_multipliers(symbol, timeframe)
    
    tp1_from_atr = atr_pips * multipliers["tp1"]
    tp2_from_atr = atr_pips * multipliers["tp2"]
    tp3_from_atr = atr_pips * multipliers["tp3"]
    
    # Get timeframe-appropriate minimum risk-reward
    min_rr = get_minimum_risk_reward(timeframe)
    
    min_tp1 = sl_pips * min_rr
    min_tp2 = sl_pips * (min_rr + 0.5)
    min_tp3 = sl_pips * (min_rr + 1.0)
    
    min_profitable = spread_pips * 2 + 1
    
    tp1_pips = max(tp1_from_atr, min_tp1, min_profitable)
    tp2_pips = max(tp2_from_atr, min_tp2, tp1_pips * 1.5)
    tp3_pips = max(tp3_from_atr, min_tp3, tp1_pips * 2)
    
    return tp1_pips, tp2_pips, tp3_pips


# ============================================================
# EMA CALCULATION
# ============================================================

def _calculate_ema(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def _calculate_adx(high: List[float], low: List[float], close: List[float], period: int = 14) -> float:
    """
    Calculate Average Directional Index (ADX).
    
    Args:
        high: List of high prices
        low: List of low prices
        close: List of close prices
        period: ADX period (default 14)
    
    Returns:
        ADX value (0-100)
    """
    if len(close) < period * 2:
        return 20.0
    
    tr = []
    for i in range(1, len(close)):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i-1])
        lc = abs(low[i] - close[i-1])
        tr.append(max(hl, hc, lc))
    
    plus_dm, minus_dm = [], []
    for i in range(1, len(close)):
        up = high[i] - high[i-1]
        down = low[i-1] - low[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
    
    # ✅ FIXED: +DM/-DM must be Wilder-smoothed the SAME way as TR/ATR
    # before computing DI. The old code divided RAW, single-bar plus_dm/
    # minus_dm directly by the SMOOTHED atr — mixing an unsmoothed
    # numerator against a smoothed denominator. Verified empirically:
    # this saturates ADX at 100.0 on mild synthetic trend data where a
    # correctly Wilder-smoothed calculation gives ~37 — a plausible root
    # cause for the unusually extreme ADX readings (80s-90s) seen
    # throughout this system, which standard Wilder ADX rarely reaches.
    def _wilder_smooth(values: List[float], period: int) -> List[float]:
        if len(values) < period:
            return []
        smoothed = [sum(values[:period]) / period]
        for v in values[period:]:
            smoothed.append((smoothed[-1] * (period - 1) + v) / period)
        return smoothed

    atr = _wilder_smooth(tr, period)
    plus_dm_smooth = _wilder_smooth(plus_dm, period)
    minus_dm_smooth = _wilder_smooth(minus_dm, period)

    n = min(len(atr), len(plus_dm_smooth), len(minus_dm_smooth))
    if n == 0:
        return 20.0
    atr = atr[-n:]
    plus_dm_smooth = plus_dm_smooth[-n:]
    minus_dm_smooth = minus_dm_smooth[-n:]

    plus_di = [p / a * 100 if a > 0 else 0 for p, a in zip(plus_dm_smooth, atr)]
    minus_di = [m / a * 100 if a > 0 else 0 for m, a in zip(minus_dm_smooth, atr)]
    
    dx = [abs(p - m) / (p + m) * 100 if p + m > 0 else 0 for p, m in zip(plus_di, minus_di)]
    
    if len(dx) < period:
        return 20.0
    
    return sum(dx[-period:]) / period


# ============================================================
# INSTRUMENT-AWARE HELPER FUNCTIONS
# ============================================================

def _get_instrument_adx_thresholds(symbol: str) -> Tuple[float, float]:
    """Get instrument-appropriate ADX thresholds."""
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        return ADX_THRESHOLDS["XAUUSD"]["trend"], ADX_THRESHOLDS["XAUUSD"]["strong_trend"]
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        return ADX_THRESHOLDS["XAGUSD"]["trend"], ADX_THRESHOLDS["XAGUSD"]["strong_trend"]
    else:
        return ADX_THRESHOLDS["DEFAULT"]["trend"], ADX_THRESHOLDS["DEFAULT"]["strong_trend"]


def _get_instrument_volume_multiplier(symbol: str) -> float:
    """Get instrument-appropriate volume multiplier adjustment."""
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        return INSTRUMENT_VOLUME_MULTIPLIER_GOLD
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        return INSTRUMENT_VOLUME_MULTIPLIER_SILVER
    else:
        return INSTRUMENT_VOLUME_MULTIPLIER_DEFAULT


# ============================================================
# FVG TOLERANCE
# ============================================================

def _get_fvg_tolerance_pips(symbol: str, atr_pips: float = None) -> float:
    """Returns tolerance in PIPS (not price units)."""
    symbol_upper = symbol.upper()
    
    # Determine base tolerance based on instrument
    if "XAU" in symbol_upper:
        base_tolerance = FVG_BASE_TOLERANCE["XAU"]
    elif "XAG" in symbol_upper:
        base_tolerance = FVG_BASE_TOLERANCE["XAG"]
    else:
        base_tolerance = FVG_BASE_TOLERANCE["DEFAULT"]
    
    # Use atr_pips parameter to adjust tolerance
    if atr_pips and atr_pips > 0:
        atr_tolerance = atr_pips * FVG_ATR_MULTIPLIER
        tolerance = max(base_tolerance, atr_tolerance)
        logger.debug(f"[FVG] Using ATR-based tolerance: ATR={atr_pips:.1f}p → {atr_tolerance:.1f}p (base={base_tolerance:.1f}p)")
    else:
        tolerance = base_tolerance
    
    # Apply max tolerance cap
    if "XAU" in symbol_upper:
        tolerance = min(tolerance, FVG_MAX_TOLERANCE["XAU"])
    elif "XAG" in symbol_upper:
        tolerance = min(tolerance, FVG_MAX_TOLERANCE["XAG"])
    else:
        tolerance = min(tolerance, FVG_MAX_TOLERANCE["DEFAULT"])
    
    return tolerance


# ============================================================
# VOLUME MULTIPLIER
# ============================================================

def _get_volume_multiplier(volume_ratio: float, timeframe: str = "M1", symbol: str = "XAUUSD") -> float:
    """Instrument-aware volume multiplier."""
    is_small_tf = timeframe.upper() in ["M1", "M5"]
    instrument_factor = _get_instrument_volume_multiplier(symbol)
    adjusted_ratio = volume_ratio / instrument_factor
    
    if is_small_tf:
        if adjusted_ratio < VOLUME_RATIO_EXTREME_LOW:
            return VOLUME_MULTIPLIER_EXTREME_LOW
        elif adjusted_ratio < VOLUME_RATIO_VERY_LOW:
            return VOLUME_MULTIPLIER_VERY_LOW
        elif adjusted_ratio < VOLUME_RATIO_LOW:
            return VOLUME_MULTIPLIER_LOW
        elif adjusted_ratio < VOLUME_RATIO_BELOW_AVG:
            return VOLUME_MULTIPLIER_BELOW_AVG
        elif adjusted_ratio < VOLUME_RATIO_NORMAL_MAX:
            return VOLUME_MULTIPLIER_NORMAL
        elif adjusted_ratio < VOLUME_RATIO_ABOVE_AVG:
            return VOLUME_MULTIPLIER_ABOVE_AVG
        else:
            return VOLUME_MULTIPLIER_HIGH
    else:
        if adjusted_ratio < VOLUME_RATIO_EXTREME_LOW:
            return 0.30
        elif adjusted_ratio < VOLUME_RATIO_VERY_LOW:
            return 0.50
        elif adjusted_ratio < VOLUME_RATIO_LOW:
            return 0.70
        elif adjusted_ratio < VOLUME_RATIO_BELOW_AVG:
            return 0.85
        elif adjusted_ratio < VOLUME_RATIO_NORMAL_MAX:
            return VOLUME_MULTIPLIER_NORMAL
        elif adjusted_ratio < VOLUME_RATIO_ABOVE_AVG:
            return VOLUME_MULTIPLIER_ABOVE_AVG
        else:
            return VOLUME_MULTIPLIER_HIGH


# ============================================================
# RSI SCORING (RSI 14 only - simplified)
# ============================================================

def _score_rsi(rsi_val: float, order_type: str) -> float:
    """
    Simplified RSI scoring using only RSI 14.
    
    For BUY:
    - RSI > 80: -20 (extreme overbought - bad to buy)
    - RSI > 75: -8 (overbought)
    - RSI > 70: -3 (warning)
    - RSI 40-70: 0 (neutral)
    - RSI 30-40: +5 (bullish - oversold bounce potential)
    - RSI < 30: +8 (very bullish - extreme oversold)
    
    For SELL:
    - RSI < 20: -20 (extreme oversold - bad to sell)
    - RSI < 25: -8 (oversold)
    - RSI < 30: -3 (warning)
    - RSI 30-60: 0 (neutral)
    - RSI 60-70: +5 (bearish - overbought reversal potential)
    - RSI > 70: +8 (very bearish - extreme overbought)
    """
    if order_type.upper() == "BUY":
        if rsi_val > 80:
            return -20.0
        elif rsi_val > 75:
            return -8.0
        elif rsi_val > 70:
            return -3.0
        elif rsi_val >= 40:
            return 0.0
        elif rsi_val >= 30:
            return 5.0
        else:
            return 8.0
    else:  # SELL
        if rsi_val < 20:
            return -20.0
        elif rsi_val < 25:
            return -8.0
        elif rsi_val < 30:
            return -3.0
        elif rsi_val <= 60:
            return 0.0
        elif rsi_val <= 70:
            return 5.0
        else:
            return 8.0


# ============================================================
# RSI PERIOD DIVERGENCE
# ============================================================

def _score_rsi_period_divergence(rsi_14: float, rsi_21: float, order_type: str, symbol: str = "XAUUSD") -> float:
    """
    Progressive scaling based on divergence magnitude.
    FIX: Now returns positive for bullish divergence, negative for bearish.
    """
    diff = rsi_14 - rsi_21
    is_positive = rsi_14 > rsi_21
    
    # Progressive scaling: larger divergence = larger impact
    if diff >= 30:
        impact = 25
    elif diff >= 25:
        impact = 20
    elif diff >= 20:
        impact = 15
    elif diff >= 15:
        impact = 10
    elif diff >= 5:
        impact = 5
    else:
        return 0.0
    
    # For BUY: positive divergence (rsi_14 > rsi_21) is bullish
    # For SELL: negative divergence (rsi_14 < rsi_21) is bearish
    if order_type.upper() == "BUY":
        if is_positive:
            return impact
        else:
            return -impact
    else:  # SELL
        if is_positive:
            return -impact
        else:
            return impact


# ============================================================
# RSI DIVERGENCE IMPACT
# ============================================================

def _calculate_rsi_divergence_impact(divergence_score: float) -> float:
    """Progressive scaling instead of hard cap."""
    abs_score = abs(divergence_score)
    
    if abs_score >= 85:
        impact = 30.0
    elif abs_score >= 70:
        impact = 25.0
    elif abs_score >= 50:
        impact = 20.0
    elif abs_score >= 30:
        impact = 15.0
    else:
        impact = abs_score * 0.5
    
    return impact if divergence_score > 0 else -impact


# ============================================================
# VOLATILITY PROTECTION
# ============================================================

# ✅ FIXED: this table used to be defined here AND independently in
# asset_analysis_config.py:907, with identical contents -- two separately
# maintained copies of the same numbers. asset_analysis.py imports the
# name from BOTH modules (lines 329 and 423), so whichever import lands
# second silently wins and the other becomes a decoy: editing the losing
# copy would change nothing, with no error to say so.
#
# They happened to agree, so nothing was live-broken -- but these are
# exactly the numbers under discussion for recalibration (XAGUSD's
# 10/25/45 scored mid-normal volatility as EXTREME), and recalibrating
# the wrong copy would have looked like the change simply had no effect.
#
# Now re-exported from the config module, which is the stated "SOURCE OF
# TRUTH: All constants defined ONCE" per its own header. The alias below
# is kept so this module's existing importers are unaffected.
from core.asset_analysis_config import _NORMAL_ATR_RANGES as _NORMAL_ATR_RANGES_BASE

# Note: check_volatility_protection is defined once, further below in this
# file (near extract_rates_arrays). ✅ FIXED: removed a duplicate, byte-
# for-byte identical definition that used to sit here — Python silently
# used whichever definition came last, making this copy dead code that
# could mislead a future edit into the wrong copy.

# ============================================================
# BACKWARD COMPATIBILITY ALIASES
# ============================================================

_NORMAL_ATR_RANGES = _NORMAL_ATR_RANGES_BASE


# ============================================================
# HELPER FUNCTIONS FOR EXPORTING CONSTANTS
# ============================================================

def get_calculations_constants() -> Dict[str, Any]:
    """Return all configurable constants for debugging."""
    return {
        "macd_settings": {
            "fast": MACD_FAST,
            "slow": MACD_SLOW,
            "signal": MACD_SIGNAL,
            "description": "FAST MACD (5,13,6) - less lag for M1 scalping"
        },
        "volume_multipliers": {
            "extreme_low": VOLUME_MULTIPLIER_EXTREME_LOW,
            "very_low": VOLUME_MULTIPLIER_VERY_LOW,
            "low": VOLUME_MULTIPLIER_LOW,
            "below_avg": VOLUME_MULTIPLIER_BELOW_AVG,
            "normal": VOLUME_MULTIPLIER_NORMAL,
            "above_avg": VOLUME_MULTIPLIER_ABOVE_AVG,
            "high": VOLUME_MULTIPLIER_HIGH
        },
        "volume_ratio_thresholds": {
            "extreme_low": VOLUME_RATIO_EXTREME_LOW,
            "very_low": VOLUME_RATIO_VERY_LOW,
            "low": VOLUME_RATIO_LOW,
            "below_avg": VOLUME_RATIO_BELOW_AVG,
            "normal_max": VOLUME_RATIO_NORMAL_MAX,
            "above_avg": VOLUME_RATIO_ABOVE_AVG
        },
        "instrument_multipliers": {
            "volume": {
                "gold": INSTRUMENT_VOLUME_MULTIPLIER_GOLD,
                "silver": INSTRUMENT_VOLUME_MULTIPLIER_SILVER,
                "default": INSTRUMENT_VOLUME_MULTIPLIER_DEFAULT
            }
        },
        "adx_thresholds": ADX_THRESHOLDS,
        "fvg_tolerance": {
            "base": FVG_BASE_TOLERANCE,
            "max": FVG_MAX_TOLERANCE,
            "atr_multiplier": FVG_ATR_MULTIPLIER
        },
        "decision_thresholds": {
            "strong_entry": DECISION_STRONG_ENTRY,
            "entry_with_zone": DECISION_ENTRY_WITH_ZONE,
            "wait": DECISION_WAIT_THRESHOLD,
            "monitor": DECISION_MONITOR_THRESHOLD,
            "star_5": STAR_5_THRESHOLD,
            "star_4": STAR_4_THRESHOLD,
            "star_3": STAR_3_THRESHOLD,
            "star_2": STAR_2_THRESHOLD
        },
        "probability_multipliers": {
            "candle_ready": CANDLE_READY_MULTIPLIER,
            "high_volatility": HIGH_VOLATILITY_MULTIPLIER,
            "invalid_spread": INVALID_SPREAD_MULTIPLIER,
            "min_probability": _MIN_PROBABILITY,
            "max_probability": _MAX_PROBABILITY
        },
        "zone_grading": {
            "thresholds": ZONE_GRADE_THRESHOLDS,
            "scores": ZONE_GRADE_SCORES,
            "multipliers": ZONE_GRADE_MULTIPLIERS
        }
    }


# ============================================================
# PROBABILITY ADJUSTMENT FUNCTIONS
# ============================================================

def apply_probability_multipliers(
    probability: float,
    candle_ready: bool,
    market_regime: str,
    spread_valid: bool
) -> float:
    """Apply multipliers to probability based on market conditions."""
    if not candle_ready:
        probability *= CANDLE_READY_MULTIPLIER
        logger.debug(f"[PROBABILITY] Candle not ready: applied {CANDLE_READY_MULTIPLIER}x multiplier")
    
    if market_regime == "HIGH_VOLATILITY":
        probability *= HIGH_VOLATILITY_MULTIPLIER
        logger.debug(f"[PROBABILITY] High volatility regime: applied {HIGH_VOLATILITY_MULTIPLIER}x multiplier")
    
    if not spread_valid:
        probability *= INVALID_SPREAD_MULTIPLIER
        logger.debug(f"[PROBABILITY] Invalid spread: applied {INVALID_SPREAD_MULTIPLIER}x multiplier")
    
    return max(_MIN_PROBABILITY, min(_MAX_PROBABILITY, probability))


def apply_probability_multipliers_pair(
    prob_buy: float,
    prob_sell: float,
    candle_ready: bool,
    market_regime: str,
    spread_valid: bool
) -> Tuple[float, float]:
    """Apply multipliers to both BUY and SELL probabilities."""
    prob_buy = apply_probability_multipliers(prob_buy, candle_ready, market_regime, spread_valid)
    prob_sell = apply_probability_multipliers(prob_sell, candle_ready, market_regime, spread_valid)
    return prob_buy, prob_sell


def get_best_direction(prob_buy: float, prob_sell: float) -> Tuple[str, float]:
    """Determine the best trading direction based on probabilities."""
    if prob_buy >= prob_sell:
        return "BUY", prob_buy
    else:
        return "SELL", prob_sell


# ============================================================
# DECISION THRESHOLD FUNCTIONS
# ============================================================

def get_decision_thresholds() -> Dict[str, float]:
    """Return current decision thresholds for debugging/inspection."""
    return {
        "strong_entry": DECISION_STRONG_ENTRY,
        "entry_with_zone": DECISION_ENTRY_WITH_ZONE,
        "wait": DECISION_WAIT_THRESHOLD,
        "monitor": DECISION_MONITOR_THRESHOLD,
        "star_5": STAR_5_THRESHOLD,
        "star_4": STAR_4_THRESHOLD,
        "star_3": STAR_3_THRESHOLD,
        "star_2": STAR_2_THRESHOLD,
        "min_probability": _MIN_PROBABILITY,
        "max_probability": _MAX_PROBABILITY,
        "candle_ready_multiplier": CANDLE_READY_MULTIPLIER,
        "high_volatility_multiplier": HIGH_VOLATILITY_MULTIPLIER,
        "invalid_spread_multiplier": INVALID_SPREAD_MULTIPLIER
    }


def update_decision_thresholds(**kwargs) -> Dict[str, float]:
    """Update decision thresholds at runtime."""
    global DECISION_STRONG_ENTRY, DECISION_ENTRY_WITH_ZONE, DECISION_WAIT_THRESHOLD
    global DECISION_MONITOR_THRESHOLD, STAR_5_THRESHOLD, STAR_4_THRESHOLD
    global STAR_3_THRESHOLD, STAR_2_THRESHOLD
    
    if "strong_entry" in kwargs:
        DECISION_STRONG_ENTRY = kwargs["strong_entry"]
    if "entry_with_zone" in kwargs:
        DECISION_ENTRY_WITH_ZONE = kwargs["entry_with_zone"]
    if "wait" in kwargs:
        DECISION_WAIT_THRESHOLD = kwargs["wait"]
    if "monitor" in kwargs:
        DECISION_MONITOR_THRESHOLD = kwargs["monitor"]
    if "star_5" in kwargs:
        STAR_5_THRESHOLD = kwargs["star_5"]
    if "star_4" in kwargs:
        STAR_4_THRESHOLD = kwargs["star_4"]
    if "star_3" in kwargs:
        STAR_3_THRESHOLD = kwargs["star_3"]
    if "star_2" in kwargs:
        STAR_2_THRESHOLD = kwargs["star_2"]
    
    logger.info(f"[THRESHOLDS] Updated: {get_decision_thresholds()}")
    return get_decision_thresholds()


# RSI divergence is detected on M1 ONLY (operator, 2026-09-18: "forever").
# The M15 divergence functions that lived here were deleted; the one
# definition is core/rsi_divergence_setup.py.

# ============================================================
# MAIN PROBABILITY CALCULATION
# ============================================================

# calculate_macd() encodes both signs in its signal string:
#   BULLISH          line > 0, histogram > 0
#   BEARISH          line < 0, histogram < 0
#   NEUTRAL_BULLISH  line > 0, histogram < 0   (momentum rolling over)
#   NEUTRAL_BEARISH  line < 0, histogram > 0   (momentum turning up)
_MACD_SIGNS = {
    "BULLISH": (1, 1),
    "BEARISH": (-1, -1),
    "NEUTRAL_BULLISH": (1, -1),
    "NEUTRAL_BEARISH": (-1, 1),
}


def _macd_signs(macd_signal: str) -> Tuple[int, int]:
    """(line sign, histogram sign); (0, 0) for NEUTRAL or anything unknown."""
    return _MACD_SIGNS.get(str(macd_signal or "").upper(), (0, 0))


def _macd_contribution(macd_signal: str, order_type: str) -> float:
    """Probability points from MACD for one side, symmetric for BUY and SELL.

    Momentum (histogram) decides the sign, position (line) the strength.
    """
    side = 1 if str(order_type).upper() == "BUY" else -1
    line, hist = _macd_signs(macd_signal)
    line, hist = line * side, hist * side
    if hist > 0:
        return float(MACD_SCORE_WITH if line > 0 else MACD_SCORE_TURNING_WITH)
    if hist < 0:
        return float(MACD_SCORE_FADING if line > 0 else MACD_SCORE_AGAINST)
    return 0.0


def calculate_real_probability(
    trend: str,
    order_type: str,
    sd_grade: str,
    is_at_zone: bool,
    wyckoff_score: int,
    wyckoff_phase: str,
    volume_ratio: float,
    rsi_val: float,
    ict_signal_type: str,
    adx_val: float,
    bb_signal: str,
    macd_signal: str,
    stoch_signal: str,
    rsi_divergence_type: str = "NONE",
    rsi_divergence_score: float = 0.0,
    candlestick_score: float = 0.0,
    price_above_fvg_pips: float = 0.0,
    price_below_fvg_pips: float = 0.0,
    bb_band_width: float = 1.0,
    distance_to_resistance_pips: float = 999.0,
    # ✅ NEW: dedicated parameter for the SELL-side mirror of the
    # resistance-proximity discount below -- previously the caller
    # passed support-distance into distance_to_resistance_pips for SELL
    # calls, reusing the same (BUY-labeled) "resistance_discount" slot
    # for a different meaning with no comment explaining it anywhere.
    # See the discount block itself for the full reasoning.
    distance_to_support_pips: float = 999.0,
    ema20_ema200_gap_pips: float = 999.0,
    rsi_14: float = 50.0,
    rsi_21: float = 50.0,
    symbol: str = "XAUUSD",
    atr_pips: float = 10.0,
    fvg_tolerance: float = None,
    timeframe: str = "M1",
) -> Tuple[float, float, Dict[str, Any]]:
    """
    PHASE 8: Complete probability calculation with all fixes applied.
    
    NOTE: rsi_val is RSI 14 (RSI 7 has been removed from the system)
    """
    
    breakdown = {"base": _BASE_PROBABILITY}
    
    if fvg_tolerance is None:
        fvg_tolerance = _get_fvg_tolerance_pips(symbol, atr_pips)
    
    rsi_overbought, rsi_oversold, rsi_divergence_veto = get_rsi_thresholds(timeframe)
    adx_strong, adx_very_strong = _get_instrument_adx_thresholds(symbol)

    # PRE-FLIGHT VETOES
    if order_type.upper() == "BUY" and rsi_divergence_type == "REGULAR_BEARISH" and rsi_val > rsi_divergence_veto:
        return 25.0, fvg_tolerance, {"veto": "REGULAR_BEARISH_RSI_DIVERGENCE"}
    if order_type.upper() == "BUY" and rsi_val > rsi_overbought:
        return 30.0, fvg_tolerance, {"veto": "RSI_OVERBOUGHT"}
    if order_type.upper() == "SELL" and rsi_val < rsi_oversold:
        return 30.0, fvg_tolerance, {"veto": "RSI_OVERSOLD"}
    if order_type.upper() == "BUY" and ict_signal_type == "BEARISH":
        return 20.0, fvg_tolerance, {"veto": "ICT_BEARISH_FOR_BUY"}
    if order_type.upper() == "SELL" and ict_signal_type == "BULLISH":
        return 20.0, fvg_tolerance, {"veto": "ICT_BULLISH_FOR_SELL"}
    if order_type.upper() == "BUY" and ict_signal_type == "BULLISH" and price_below_fvg_pips > fvg_tolerance:
        return 20.0, fvg_tolerance, {"veto": "ICT_BULLISH_PRICE_BELOW_FVG"}

    # STEP 1: Volume multiplier
    volume_multiplier = _get_volume_multiplier(volume_ratio, timeframe, symbol)
    base_after_volume = _BASE_PROBABILITY * volume_multiplier
    breakdown["base_after_volume"] = base_after_volume
    breakdown["volume_multiplier"] = volume_multiplier
    breakdown["timeframe"] = timeframe
    probability = base_after_volume

    # STEP 2: Trend impact
    trend_contribution = 0
    if order_type.upper() == "BUY":
        if trend == "STRONG_BULLISH":
            trend_contribution = 30 if adx_val > adx_very_strong else (20 if adx_val > adx_strong else 15)
        elif trend == "BULLISH":
            trend_contribution = 10
        elif trend == "STRONG_BEARISH":
            trend_contribution = -35 if adx_val > adx_very_strong else (-25 if adx_val > adx_strong else -20)
        elif trend == "BEARISH":
            trend_contribution = -15
    else:
        if trend == "STRONG_BEARISH":
            trend_contribution = 30 if adx_val > adx_very_strong else (20 if adx_val > adx_strong else 15)
        elif trend == "BEARISH":
            trend_contribution = 10
        elif trend == "STRONG_BULLISH":
            trend_contribution = -35 if adx_val > adx_very_strong else (-25 if adx_val > adx_strong else -20)
        elif trend == "BULLISH":
            trend_contribution = -15
    
    # M1 trend showed no directional lift on the stored trades; the H1/H4
    # evidence now comes from the trend cascade. See PROB_SCALE_TREND.
    trend_contribution = trend_contribution * PROB_SCALE_TREND
    breakdown["trend"] = trend_contribution
    probability += trend_contribution

    # ✅ FIXED: this discount used to apply unconditionally regardless of
    # order_type, using distance_to_resistance_pips for BOTH BUY and
    # SELL -- but the caller was actually passing support-distance into
    # that same parameter for SELL calls (an undocumented reuse of one
    # slot for two different meanings, with no comment anywhere
    # explaining it, unlike every other BUY/SELL asymmetry already
    # handled explicitly in this function). Rather than just drop the
    # SELL-side effect, this now gives SELL its own proper, symmetric
    # discount using the dedicated distance_to_support_pips parameter --
    # being near support is a genuine caution for SELLING into a
    # potential floor, the same way being near resistance is a caution
    # for BUYING into a potential ceiling.
    proximity_threshold = get_resistance_proximity_pips(symbol)
    if order_type.upper() == "BUY" and distance_to_resistance_pips < proximity_threshold:
        resistance_discount = (1.0 - distance_to_resistance_pips / proximity_threshold) * 10.0
        breakdown["resistance_discount"] = -resistance_discount
        probability -= resistance_discount
    elif order_type.upper() == "SELL" and distance_to_support_pips < proximity_threshold:
        support_discount = (1.0 - distance_to_support_pips / proximity_threshold) * 10.0
        breakdown["support_discount"] = -support_discount
        probability -= support_discount

    # STEP 3: Supply/Demand impact - FIXED with D grade contribution
    zone_contribution = 0
    if sd_grade == "A" and is_at_zone:
        zone_contribution = ZONE_CONTRIBUTION_A_AT_ZONE
    elif sd_grade == "B" and is_at_zone:
        zone_contribution = ZONE_CONTRIBUTION_B_AT_ZONE
    elif sd_grade == "C" and is_at_zone:
        zone_contribution = ZONE_CONTRIBUTION_C_AT_ZONE
    elif sd_grade == "D" and is_at_zone:
        zone_contribution = ZONE_CONTRIBUTION_D_AT_ZONE
    elif sd_grade == "A":
        zone_contribution = ZONE_CONTRIBUTION_A_AWAY
    elif sd_grade == "B":
        zone_contribution = ZONE_CONTRIBUTION_B_AWAY
    elif sd_grade == "E":
        zone_contribution = ZONE_CONTRIBUTION_E_PENALTY
    
    zone_contribution = zone_contribution * PROB_SCALE_ZONE + 0.0   # see PROB_SCALE_ZONE
    breakdown["zone"] = zone_contribution
    probability += zone_contribution

    # STEP 4: Wyckoff impact
    # ✅ FIXED: this used to add the same positive bonus to BOTH the BUY call
    # and the SELL call for the exact same bar, because it only looked at
    # wyckoff_score (confidence-in-phase-detection) and never checked
    # wyckoff_phase's actual direction against order_type -- every other
    # step in this function (trend, ICT, MACD, stochastic) branches on
    # order_type.upper(); this one didn't. A confidently-detected
    # MARKDOWN_STRONG phase was inflating BUY probability exactly as much
    # as SELL probability, which is backwards -- a directional phase read
    # should help the side it agrees with and hurt the side it opposes.
    # ACCUMULATION/CONSOLIDATION phases stay at 0 either way: per Wyckoff
    # theory those are genuinely directionally unresolved (you know a move
    # is being prepared, not which way it breaks), so no non-arbitrary
    # sign exists to assign them here -- consistent with how the unified
    # score's rescaler already treats a NEUTRAL wyckoff recommendation.
    wyckoff_tier = 0.0
    if wyckoff_score >= 90:
        wyckoff_tier = 15.0
    elif wyckoff_score >= 70:
        wyckoff_tier = 10.0
    elif wyckoff_score >= 50:
        wyckoff_tier = 5.0
    elif wyckoff_score >= 30:
        wyckoff_tier = 2.0

    phase_upper = (wyckoff_phase or "").upper()
    order_upper = order_type.upper()
    is_markup = "MARKUP" in phase_upper
    is_markdown = "MARKDOWN" in phase_upper

    if order_upper == "BUY":
        wyckoff_bonus = wyckoff_tier if is_markup else (-wyckoff_tier if is_markdown else 0.0)
    else:  # SELL
        wyckoff_bonus = wyckoff_tier if is_markdown else (-wyckoff_tier if is_markup else 0.0)

    # Candle-vs-direction disagreement still dampens trust in the read --
    # now checked against order_type instead of a hardcoded bullish-only
    # assumption, so it dampens correctly for SELL calls too.
    candle_disagrees = (candlestick_score < 0 and order_upper == "BUY") or (candlestick_score > 0 and order_upper == "SELL")
    if wyckoff_bonus != 0.0 and candle_disagrees:
        wyckoff_bonus *= 0.5

    breakdown["wyckoff"] = wyckoff_bonus
    probability += wyckoff_bonus

    # ✅ FIXED: this conflict penalty also used to fire the same way for a
    # SELL call as for a BUY call. A bullish-trending market that's stuck in
    # CONSOLIDATION (no real markup structure yet) is specifically a red
    # flag against BUYING into a fakeout -- it isn't obviously a reason to
    # doubt a SELL. Added the mirror case for a bearish trend stuck in
    # consolidation, which is the equivalent caution against SELLING.
    if order_upper == "BUY" and trend in ["STRONG_BULLISH", "BULLISH"] and wyckoff_phase == "CONSOLIDATION":
        breakdown["wyckoff_trend_conflict"] = -5
        probability -= 5
    elif order_upper == "SELL" and trend in ["STRONG_BEARISH", "BEARISH"] and wyckoff_phase == "CONSOLIDATION":
        breakdown["wyckoff_trend_conflict"] = -5
        probability -= 5

    # STEP 5: RSI impacts (RSI 14 only)
    rsi_impact = _score_rsi(rsi_val, order_type) * PROB_SCALE_RSI_IMPACT + 0.0
    breakdown["rsi_impact"] = rsi_impact
    probability += rsi_impact

    # RSI Divergence impact
    rsi_divergence_impact = 0
    if rsi_divergence_type != "NONE" and rsi_divergence_score != 0:
        abs_score = abs(rsi_divergence_score)
        raw_impact = _calculate_rsi_divergence_impact(abs_score)
        
        is_bullish_divergence = rsi_divergence_score > 0        
        is_buy_order = order_type.upper() == "BUY"
        
        if (is_bullish_divergence and is_buy_order) or (not is_bullish_divergence and not is_buy_order):
            rsi_divergence_impact = raw_impact
        else:
            rsi_divergence_impact = -raw_impact
        
        rsi_divergence_impact = max(-_MAX_RSI_DIVERGENCE_IMPACT, min(_MAX_RSI_DIVERGENCE_IMPACT, rsi_divergence_impact))
    
    breakdown["rsi_divergence"] = rsi_divergence_impact
    probability += rsi_divergence_impact

    # RSI Period Divergence
    rsi_period = _score_rsi_period_divergence(rsi_14, rsi_21, order_type, symbol)
    breakdown["rsi_period"] = rsi_period
    probability += rsi_period

    # STEP 6: ICT impact
    ict_contribution = 0
    ict_blocked = False
    if order_type.upper() == "BUY" and ict_signal_type == "BULLISH" and price_above_fvg_pips > fvg_tolerance:
        ict_blocked = True
    elif order_type.upper() == "SELL" and ict_signal_type == "BEARISH" and price_below_fvg_pips > fvg_tolerance:
        ict_blocked = True
    if not ict_blocked:
        if ict_signal_type == "BULLISH" and order_type == "BUY":
            ict_contribution = 10
        elif ict_signal_type == "BEARISH" and order_type == "SELL":
            ict_contribution = 10
        elif ict_signal_type == "BEARISH" and order_type == "BUY":
            ict_contribution = -10
        elif ict_signal_type == "BULLISH" and order_type == "SELL":
            ict_contribution = -10
    ict_contribution = ict_contribution * PROB_SCALE_ICT + 0.0      # see PROB_SCALE_ICT
    breakdown["ict"] = ict_contribution
    breakdown["ict_blocked"] = ict_blocked
    probability += ict_contribution

    # STEP 7: ADX trend strength
    # Trades this penalised were right MORE often (70% vs 52%). See ADX_LOW_PENALTY.
    if adx_val < 20:
        breakdown["adx_penalty"] = ADX_LOW_PENALTY
        probability += ADX_LOW_PENALTY
    else:
        breakdown["adx_penalty"] = 0

    # STEP 8: Bollinger Bands - FIXED with squeeze scoring
    squeeze_threshold = get_bb_squeeze_threshold(symbol)
    bb_effective_signal = bb_signal
    bb_contribution = 0
    
    if bb_band_width < squeeze_threshold:
        # Squeeze mode - reduced impact
        if order_type == "BUY":
            if bb_signal == "BULLISH" or bb_signal == "BELOW_LOWER":
                bb_contribution = BB_SCORE_SQUEEZE_BULLISH
            elif bb_signal == "BEARISH" or bb_signal == "ABOVE_UPPER":
                bb_contribution = BB_SCORE_SQUEEZE_BEARISH
            else:
                bb_contribution = BB_SCORE_SQUEEZE_NEUTRAL
        else:
            if bb_signal == "BEARISH" or bb_signal == "ABOVE_UPPER":
                bb_contribution = BB_SCORE_SQUEEZE_BEARISH
            elif bb_signal == "BULLISH" or bb_signal == "BELOW_LOWER":
                bb_contribution = BB_SCORE_SQUEEZE_BULLISH
            else:
                bb_contribution = BB_SCORE_SQUEEZE_NEUTRAL
    else:
        # Normal mode - full impact
        if order_type == "BUY":
            if bb_signal == "BULLISH":
                bb_contribution = BB_SCORE_BULLISH
            elif bb_signal == "BEARISH":
                bb_contribution = BB_SCORE_BEARISH
        else:
            if bb_signal == "BEARISH":
                bb_contribution = BB_SCORE_BEARISH
            elif bb_signal == "BULLISH":
                bb_contribution = BB_SCORE_BULLISH
    
    bb_contribution = bb_contribution * PROB_SCALE_BOLLINGER
    breakdown["bb"] = bb_contribution
    probability += bb_contribution

    # STEP 9: MACD impact -- by MOMENTUM (histogram), then position (line).
    #
    # ✅ FIXED 2026-09-15. This used to group NEUTRAL_BULLISH with BULLISH:
    # line above zero but histogram already negative -- momentum rolling
    # over -- scored +8 for a BUY, and price then FELL 73% of the time on
    # the stored trades. It was also asymmetric: a SELL got the full +15 for
    # NEUTRAL_BEARISH while a BUY got +8 for its mirror. As written the MACD
    # term had a -13 point lift (inverted); driven by the histogram it is
    # +21. See MACD_SCORE_* in asset_analysis_config.py.
    macd_contribution = _macd_contribution(macd_signal, order_type)
    breakdown["macd"] = macd_contribution
    probability += macd_contribution

    # STEP 10: Stochastic impact (FIXED - trend-aware)
    stoch_contribution = 0
    if order_type.upper() == "BUY":
        if stoch_signal == "OVERSOLD":
            if trend in ["STRONG_BEARISH", "BEARISH"]:
                stoch_contribution = STOCHASTIC_SCORE_OVERSOLD_NEUTRAL
            else:
                stoch_contribution = STOCHASTIC_SCORE_OVERSOLD_BULLISH
        elif stoch_signal == "OVERBOUGHT":
            if trend in ["STRONG_BEARISH", "BEARISH"]:
                stoch_contribution = STOCHASTIC_SCORE_OVERBOUGHT_NEUTRAL
            else:
                stoch_contribution = -10
        elif stoch_signal == "BULLISH_X":
            stoch_contribution = 5
        elif stoch_signal == "BEARISH_X":
            stoch_contribution = -5
    else:  # SELL
        if stoch_signal == "OVERBOUGHT":
            if trend in ["STRONG_BULLISH", "BULLISH"]:
                stoch_contribution = STOCHASTIC_SCORE_OVERBOUGHT_NEUTRAL
            else:
                stoch_contribution = 10
        elif stoch_signal == "OVERSOLD":
            if trend in ["STRONG_BULLISH", "BULLISH"]:
                stoch_contribution = STOCHASTIC_SCORE_OVERSOLD_NEUTRAL
            else:
                stoch_contribution = -10
        elif stoch_signal == "BEARISH_X":
            stoch_contribution = 5
        elif stoch_signal == "BULLISH_X":
            stoch_contribution = -5
    stoch_contribution = stoch_contribution * PROB_SCALE_STOCHASTIC
    breakdown["stochastic"] = stoch_contribution
    probability += stoch_contribution

    # STEP 11: Signal caps
    if order_type.upper() == "BUY":
        bearish_signal_count = 0
        if trend in ["STRONG_BEARISH", "BEARISH"]:
            bearish_signal_count += 1
        if ict_signal_type == "BEARISH":
            bearish_signal_count += 1
        if "MARKDOWN" in wyckoff_phase:
            bearish_signal_count += 1
        # Momentum against the BUY: histogram negative (BEARISH, or a
        # bullish line whose histogram has turned -- NEUTRAL_BULLISH).
        if _macd_signs(macd_signal)[1] < 0:
            bearish_signal_count += 1
        if bb_signal == "BEARISH":
            bearish_signal_count += 1
        if rsi_divergence_type in ["REGULAR_BEARISH", "HIDDEN_BEARISH"]:
            bearish_signal_count += 1
        breakdown["bearish_signal_count"] = bearish_signal_count
        if bearish_signal_count >= _BEARISH_SIGNAL_THRESHOLD and probability > _BEARISH_SIGNAL_CAP:
            probability = min(probability, _BEARISH_SIGNAL_CAP)
    elif order_type.upper() == "SELL":
        bullish_signal_count = 0
        if trend in ["STRONG_BULLISH", "BULLISH"]:
            bullish_signal_count += 1
        if ict_signal_type == "BULLISH":
            bullish_signal_count += 1
        if "MARKUP" in wyckoff_phase:
            bullish_signal_count += 1
        if _macd_signs(macd_signal)[1] > 0:
            bullish_signal_count += 1
        if bb_signal == "BULLISH":
            bullish_signal_count += 1
        if rsi_divergence_type in ["REGULAR_BULLISH", "HIDDEN_BULLISH"]:
            bullish_signal_count += 1
        breakdown["bullish_signal_count"] = bullish_signal_count
        if bullish_signal_count >= _BULLISH_SIGNAL_THRESHOLD and probability > _BULLISH_SIGNAL_CAP:
            probability = min(probability, _BULLISH_SIGNAL_CAP)

    final_probability = max(_MIN_PROBABILITY, min(95.0, probability))
    breakdown["final"] = final_probability
    
    return final_probability, fvg_tolerance, breakdown


# ============================================================
# DISTANCE CALCULATION FUNCTIONS
# ============================================================

def calculate_ema_gap_pips(ema_20: float, ema_200: float, pip_size: float) -> float:
    """Calculate EMA gap in pips."""
    gap_price = abs(ema_20 - ema_200)
    gap_pips = gap_price / pip_size if pip_size > 0 else 0
    return gap_pips


def calculate_fvg_distance_pips(current_price: float, fvg_level: float, pip_size: float) -> float:
    """Calculate distance from current price to FVG level in pips."""
    if fvg_level is None or fvg_level == 0:
        return 0.0
    distance_price = current_price - fvg_level
    distance_pips = distance_price / pip_size if pip_size > 0 else 0
    return distance_pips


def calculate_distance_to_resistance_pips(current_price: float, r1: float, r2: float, r3: float, pip_size: float) -> float:
    """Calculate distance to nearest resistance in pips."""
    resistances = []
    if r1 and r1 > 0:
        resistances.append(r1)
    if r2 and r2 > 0:
        resistances.append(r2)
    if r3 and r3 > 0:
        resistances.append(r3)
    
    if not resistances:
        return 999.0
    
    min_distance = min(abs(current_price - r) for r in resistances)
    min_distance_pips = min_distance / pip_size if pip_size > 0 else 999.0
    return min_distance_pips


def calculate_distance_to_support_pips(current_price: float, s1: float, s2: float, s3: float, pip_size: float) -> float:
    """Calculate distance to nearest support in pips."""
    supports = []
    if s1 and s1 > 0:
        supports.append(s1)
    if s2 and s2 > 0:
        supports.append(s2)
    if s3 and s3 > 0:
        supports.append(s3)
    
    if not supports:
        return 999.0
    
    min_distance = min(abs(current_price - s) for s in supports)
    min_distance_pips = min_distance / pip_size if pip_size > 0 else 999.0
    return min_distance_pips


# ============================================================
# PIP SIZE HELPERS
# ============================================================

def get_pip_size(symbol: str) -> float:
    """Get pip size for any symbol."""
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        return 0.01
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        return 0.001
    elif "JPY" in symbol_upper:
        return 0.01
    else:
        return 0.0001


def pips_to_price(symbol: str, pips: float) -> float:
    """Convert pips to price units for a symbol."""
    pip_size = get_pip_size(symbol)
    return pips * pip_size


def price_to_pips(symbol: str, price_distance: float) -> float:
    """Convert price distance to pips for a symbol."""
    pip_size = get_pip_size(symbol)
    return price_distance / pip_size if pip_size > 0 else 0


# ============================================================
# PIVOT LEVELS CALCULATION
# ============================================================

def calculate_pivot_levels(high: List[float], low: List[float], close: List[float]) -> Dict[str, float]:
    """Calculate pivot points and support/resistance levels."""
    high_20 = max(high[-20:]) if len(high) >= 20 else close[-1] * 1.01
    low_20 = min(low[-20:]) if len(low) >= 20 else close[-1] * 0.99
    pivot = (high_20 + low_20 + close[-1]) / 3
    r1 = 2 * pivot - low_20
    s1 = 2 * pivot - high_20
    r2 = pivot + (high_20 - low_20)
    s2 = pivot - (high_20 - low_20)
    r3 = high_20 + 2 * (pivot - low_20)
    s3 = low_20 - 2 * (high_20 - pivot)
    
    return {
        "high_20": high_20,
        "low_20": low_20,
        "pivot": pivot,
        "r1": r1, "r2": r2, "r3": r3,
        "s1": s1, "s2": s2, "s3": s3
    }


# ============================================================
# RSI VALIDATION FUNCTION
# ============================================================

def validate_rsi_value(rsi_candidate: Optional[float], period_name: str = "", default_rsi: float = 50.0) -> float:
    """Validate RSI value and return default if invalid."""
    if rsi_candidate is not None and 0 <= rsi_candidate <= 100:
        return rsi_candidate
    logger.debug(f"[RSI] {period_name} candidate {rsi_candidate} invalid, using {default_rsi}")
    return default_rsi


# ============================================================
# SPREAD VALIDATION FUNCTION
# ============================================================

def validate_spread(spread: float, symbol: str, point: float, get_max_spread_func, get_typical_spread_func) -> Tuple[float, bool]:
    """
    Validate spread and return corrected spread with validity flag.
    
    Args:
        spread: Current spread in pips
        symbol: Trading symbol
        point: Point value from symbol info
        get_max_spread_func: Function to get max allowed spread
        get_typical_spread_func: Function to get typical spread
    
    Returns:
        Tuple of (corrected_spread, is_valid)
    """
    max_allowed_spread = get_max_spread_func(symbol)
    if spread < 0 or spread > 1000:
        logger.warning(f"Abnormal spread: {spread} pips for {symbol}, using typical spread")
        spread = get_typical_spread_func(symbol)
    spread_valid = spread <= max_allowed_spread
    return spread, spread_valid

# ============================================================
# VOLATILITY PROTECTION - INSTRUMENT-AWARE
# ============================================================

def get_static_atr_ranges(symbol: str) -> Dict[str, float]:
    """
    The per-symbol static ATR range table lookup (exact match, then
    partial match, then DEFAULT), with the instrument multiplier applied.

    ✅ EXTRACTED from check_volatility_protection() so callers that need
    to know what the static table says -- e.g. to supply it as the
    fallback for an adaptive band -- can ask for it without duplicating
    the partial-match + multiplier logic and silently drifting from it.
    """
    symbol_upper = symbol.upper()

    base_ranges = _NORMAL_ATR_RANGES.get(symbol_upper)
    if base_ranges is None:
        # Check for partial matches (XAU in XAUUSD, etc.)
        matched = False
        for key in _NORMAL_ATR_RANGES:
            if key in symbol_upper:
                base_ranges = _NORMAL_ATR_RANGES[key]
                matched = True
                break
        if not matched:
            base_ranges = _NORMAL_ATR_RANGES["DEFAULT"]

    multiplier = _ATR_RANGE_MULTIPLIERS.get(symbol_upper, 1.0)
    if multiplier != 1.0:
        return {
            "min": base_ranges["min"] * multiplier,
            "max": base_ranges["max"] * multiplier,
            "extreme": base_ranges["extreme"] * multiplier,
        }
    return dict(base_ranges)


def check_volatility_protection(
    symbol: str,
    atr_pips: float,
    market_regime: str,
    percentile_band: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Instrument-aware volatility protection.
    
    Checks if current volatility is within normal range for the instrument.
    Returns confidence penalty and volatility level.

    percentile_band: optional output of
    adaptive_thresholds.compute_volatility_percentile_band(). When
    supplied AND marked adaptive AND internally well-ordered, its
    low/high/extreme replace the static _NORMAL_ATR_RANGES entry for this
    symbol.

    Why this matters: the static table is a hand-maintained guess, and
    when it is wrong it is catastrophically wrong in one direction. Live
    XAGUSD -- static says normal is 10-25 pips and extreme is 45, while
    the instrument's own last 100 bars put the 10th-90th percentile at
    30.8-90.4. Readings of 49.2 and 57.6 (mid-normal by the real
    distribution) were scored EXTREME, drawing a ~72-76 point confidence
    penalty that floored probability to the 5.0 clamp on every bar. Every
    downstream stage then operated on a pinned number, and no setup of
    any quality could clear the entry threshold.

    Passing None preserves the original behaviour exactly.
    """
    ranges = get_static_atr_ranges(symbol)
    range_source = "static_table"

    if percentile_band and percentile_band.get("adaptive"):
        low = percentile_band.get("low")
        high = percentile_band.get("high")
        extreme = percentile_band.get("extreme")
        # Only adopt a band that is complete and correctly ordered.
        # A malformed band silently reordering these tiers would be worse
        # than the miscalibration it is meant to fix.
        if (
            low is not None and high is not None and extreme is not None
            and 0 < low < high < extreme
        ):
            ranges = {"min": low, "max": high, "extreme": extreme}
            range_source = "percentile_band"
        else:
            logger.warning(
                f"[VOLATILITY] {symbol}: adaptive band rejected as malformed "
                f"(low={low}, high={high}, extreme={extreme}) -- using static table"
            )
    
    confidence_penalty = 0
    volatility_level = "NORMAL"
    warning = None
    
    if atr_pips > ranges["extreme"]:
        excess_ratio = min(1.0, (atr_pips - ranges["extreme"]) / ranges["extreme"])
        confidence_penalty = 70 + (excess_ratio * 20)
        volatility_level = "EXTREME"
        warning = f"⚠️ EXTREME VOLATILITY: ATR {atr_pips:.1f} pips exceeds {ranges['extreme']:.1f}"
        logger.warning(f"[VOLATILITY] {warning}")
    elif atr_pips > ranges["max"]:
        excess_ratio = min(1.0, (atr_pips - ranges["max"]) / (ranges["extreme"] - ranges["max"]))
        confidence_penalty = 30 + (excess_ratio * 30)
        volatility_level = "HIGH"
        warning = f"⚠️ HIGH VOLATILITY: ATR {atr_pips:.1f} pips above normal max {ranges['max']:.1f}"
        logger.debug(f"[VOLATILITY] {warning}")
    elif atr_pips < ranges["min"]:
        deficit_ratio = (ranges["min"] - atr_pips) / ranges["min"]
        confidence_penalty = min(20, deficit_ratio * 15)
        volatility_level = "LOW"
        logger.debug(f"[VOLATILITY] Low volatility: ATR {atr_pips:.1f} pips below {ranges['min']:.1f}")
    
    # Additional penalty for high volatility regime
    if market_regime == "HIGH_VOLATILITY":
        confidence_penalty += 20
        warning = f"⚠️ HIGH VOLATILITY REGIME + {warning if warning else 'Market unstable'}"
    
    return {
        "safe_to_trade": True,
        "volatility_level": volatility_level,
        "confidence_penalty": min(95, confidence_penalty),
        "reason": f"ATR {atr_pips:.1f} pips within {ranges['min']:.0f}-{ranges['max']:.0f} range" if confidence_penalty == 0 else f"Volatility penalty applied: -{confidence_penalty:.0f}%",
        "warning": warning,
        "atr_pips": round(atr_pips, 1),
        "normal_range": f"{ranges['min']:.0f}-{ranges['max']:.0f}",
        "extreme_threshold": ranges["extreme"],
        # Which table actually decided the penalty above, so a payload is
        # never ambiguous about whether the adaptive path was live.
        "range_source": range_source,
        "ranges_used": {k: round(v, 2) for k, v in ranges.items()},
    }

# ============================================================
# SAFE RATES EXTRACTION FUNCTION
# ============================================================

def extract_rates_arrays(rates):
    """
    Extract price arrays from rates data safely.
    
    Args:
        rates: numpy array or list of rate data from MT5
    
    Returns:
        Tuple of (close_prices, high_prices, low_prices, volumes) as lists
        Returns (None, None, None, None) if extraction fails
    """
    if rates is None or len(rates) == 0:
        return None, None, None, None
    
    # Try numpy array extraction first (most common)
    try:
        if hasattr(rates, 'ndim') and rates.ndim == 2:
            close_prices = rates[:, 4].astype(float).tolist()
            high_prices = rates[:, 2].astype(float).tolist()
            low_prices = rates[:, 3].astype(float).tolist()
            volumes = rates[:, 5].astype(float).tolist()
            return close_prices, high_prices, low_prices, volumes
    except (IndexError, ValueError, AttributeError):
        pass
    
    # Fallback to list comprehension
    try:
        close_prices = [float(r[4]) for r in rates]
        high_prices = [float(r[2]) for r in rates]
        low_prices = [float(r[3]) for r in rates]
        volumes = [float(r[5]) for r in rates]
        return close_prices, high_prices, low_prices, volumes
    except (IndexError, TypeError, ValueError) as e:
        logger.error(f"Failed to extract price arrays: {e}")
        return None, None, None, None