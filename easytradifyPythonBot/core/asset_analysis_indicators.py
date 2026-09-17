# ============================================================
# ASSET ANALYSIS - CORE INDICATOR SCORERS + COMPONENT ANALYZERS
# ============================================================
# FILE: core/asset_analysis_indicators.py
#
# Split out of asset_analysis.py (which had grown past 7,400 lines) to
# reduce its length -- this is a pure code-motion, not a rewrite: every
# function below is byte-for-byte identical to what was in asset_
# analysis.py, just relocated. Contains:
#   - Divergence-aware indicator scorers: RSI, Stochastic, MACD,
#     Bollinger Bands, volume, trend, supply/demand, candlestick
#   - Component analyzers: _analyze_trend_component (+ its divergence
#     variant), _analyze_indicators_component (RSI/MACD/BB/Stochastic/
#     pivot S/R all in one pass), _analyze_support_resistance_component,
#     _analyze_candlestick_component
#
# This file has NO dependency on asset_analysis.py, asset_analysis_smc.py,
# or any other split-out module -- only on core.asset_analysis_config
# and core.calculations/core.indicators (pre-existing, independent
# modules). asset_analysis.py imports FROM this file, never the other
# way around, so there is no circular import.
# ============================================================

from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import logging

from core.calculations import (
    _calculate_rsi,
    _calculate_macd,
    _calculate_bollinger_bands,
    _calculate_stochastic,
    calculate_pivot_levels,
    calculate_distance_to_resistance_pips,
    calculate_distance_to_support_pips,
    validate_rsi_value,
)
from core.indicators import _detect_trend_bias, get_sr_recommendation

from core.asset_analysis_config import (
    CANDLE_SCORE_DOJI,
    CANDLE_SCORE_HAMMER,
    CANDLE_WICK_CONFIRMED_MULT,
    CANDLE_SCORE_MARUBOZU_BEARISH,
    CANDLE_SCORE_MARUBOZU_BULLISH,
    CANDLE_SCORE_NORMAL_BEARISH,
    CANDLE_SCORE_NORMAL_BULLISH,
    CANDLE_SCORE_SHOOTING_STAR,
    CANDLE_SCORE_SPINNING_TOP,
    DEFAULT_RSI_VALUE,
    MACD_BULLISH_THRESHOLD,
    RSI_EXTREME_OVERBOUGHT,
    RSI_EXTREME_OVERSOLD,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    STOCH_OVERBOUGHT,
    STOCH_OVERSOLD,
    get_bb_period,
    get_bb_squeeze_threshold,
    get_bb_std,
    get_volume_threshold,
    get_rsi_thresholds,
)

logger = logging.getLogger(__name__)


def score_rsi_indicator_with_divergence(rsi_value: float, order_type: str, divergence_type: str = "NONE", timeframe: str = None) -> Dict[str, Any]:
    """
    Score RSI indicator with divergence impact.
    Divergence REVERSES or CONFIRMS the indicator direction.

    ✅ timeframe: this scorer used the generic RSI_OVERBOUGHT /
    RSI_OVERSOLD (70 / 30) unconditionally, while the probability chain
    calls get_rsi_thresholds(timeframe) and gets 80 / 20 on M1 and M5.
    The same RSI value therefore had two verdicts in the same bar:

        RSI 72  ->  scorer "overbought"  |  probability chain "neutral"
        RSI 25  ->  scorer "oversold"    |  probability chain "neutral"

    Contradiction bands: RSI in (70, 80] and RSI in [20, 30). M1 RSI
    oscillates far more than the textbook 70/30 assumes, which is exactly
    why the M1 constants exist -- this scorer just never asked for them.

    Passing None keeps the old generic thresholds, so any caller that
    doesn't specify a timeframe is unaffected.
    """
    if rsi_value is None or rsi_value < 0 or rsi_value > 100:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": "Invalid RSI value"}

    if timeframe:
        rsi_overbought, rsi_oversold, _ = get_rsi_thresholds(timeframe)
    else:
        rsi_overbought, rsi_oversold = RSI_OVERBOUGHT, RSI_OVERSOLD
    
    if divergence_type == "REGULAR_BULLISH":
        if rsi_value < rsi_oversold:
            return {"recommendation": "BUY", "score": 25, "confidence": 95, "reason": f"RSI: Regular Bullish Divergence - OVERSOLD ({rsi_value:.1f})"}
        elif rsi_value < 50:
            return {"recommendation": "BUY", "score": 20, "confidence": 85, "reason": f"RSI: Regular Bullish Divergence ({rsi_value:.1f})"}
        else:
            return {"recommendation": "BUY", "score": 15, "confidence": 75, "reason": f"RSI: Regular Bullish Divergence ({rsi_value:.1f})"}
    
    elif divergence_type == "REGULAR_BEARISH":
        if rsi_value > rsi_overbought:
            return {"recommendation": "SELL", "score": -25, "confidence": 95, "reason": f"RSI: Regular Bearish Divergence - OVERBOUGHT ({rsi_value:.1f})"}
        elif rsi_value > 50:
            return {"recommendation": "SELL", "score": -20, "confidence": 85, "reason": f"RSI: Regular Bearish Divergence ({rsi_value:.1f})"}
        else:
            return {"recommendation": "SELL", "score": -15, "confidence": 75, "reason": f"RSI: Regular Bearish Divergence ({rsi_value:.1f})"}
    
    elif divergence_type == "HIDDEN_BULLISH":
        if rsi_value < rsi_oversold:
            return {"recommendation": "BUY", "score": 15, "confidence": 80, "reason": f"RSI: Hidden Bullish Divergence - OVERSOLD ({rsi_value:.1f})"}
        elif rsi_value > rsi_overbought:
            return {"recommendation": "NEUTRAL", "score": -3, "confidence": 60, "reason": f"RSI: Hidden Bullish Divergence - OVERBOUGHT ({rsi_value:.1f})"}
        else:
            return {"recommendation": "BUY", "score": 10, "confidence": 70, "reason": f"RSI: Hidden Bullish Divergence ({rsi_value:.1f})"}
    
    elif divergence_type == "HIDDEN_BEARISH":
        if rsi_value > rsi_overbought:
            return {"recommendation": "SELL", "score": -15, "confidence": 80, "reason": f"RSI: Hidden Bearish Divergence - OVERBOUGHT ({rsi_value:.1f})"}
        elif rsi_value < rsi_oversold:
            return {"recommendation": "NEUTRAL", "score": 3, "confidence": 60, "reason": f"RSI: Hidden Bearish Divergence - OVERSOLD ({rsi_value:.1f})"}
        else:
            return {"recommendation": "SELL", "score": -10, "confidence": 70, "reason": f"RSI: Hidden Bearish Divergence ({rsi_value:.1f})"}
    
    # NO DIVERGENCE - Normal RSI scoring
    # (2026-09-15) 'Approaching' tiers (RSI < 40 / > 60) keep their score but
    # are NEUTRAL: on M1, where the extremes are 20/80, they put a BUY/SELL on
    # 62% of bars. Oversold/overbought is the signal; approaching it is not.
    # SYMMETRY (defect: confirmation bias in the tier magnitudes)
    #
    # The tiers below score evidence FOR the direction being evaluated
    # and AGAINST it. They used to be:
    #
    #     supports:  +20   +15   +8
    #     opposes:   -20   -10   -3
    #
    # so identical evidence counted roughly twice as heavily when it
    # agreed with the direction under test as when it disagreed. On M1
    # (thresholds 20/80) RSI 25 scored +8 while its mirror RSI 75 scored
    # -3, and RSI 75 was labelled NEUTRAL where RSI 25 was labelled BUY.
    # The chain evaluates BUY and SELL and takes the better, so a bias
    # that flatters whichever side is being scored inflates both and
    # lets mildly-opposing evidence pass almost unnoticed.
    #
    # Direction on this data measures at entropy 1.0000, so a scorer
    # that leans is describing itself, not the market.
    if order_type.upper() == "BUY":
        # <=, not <: the overbought side's terminal `else` catches
        # rsi == RSI_EXTREME_OVERBOUGHT, so the oversold side must catch
        # rsi == RSI_EXTREME_OVERSOLD or the two boundaries disagree. On
        # M1, where oversold and extreme_oversold are both 20, RSI 20
        # fell through to the weak tier (+8) while its mirror RSI 80 hit
        # the extreme tier (-20).
        if rsi_value <= RSI_EXTREME_OVERSOLD:
            return {"recommendation": "BUY", "score": 20, "confidence": 90, "reason": f"Extreme oversold ({rsi_value:.1f})"}
        # <=, mirroring the overbought side: rsi == rsi_overbought falls
        # through `< rsi_overbought` into the STRONGER tier below, so
        # rsi == rsi_oversold must also land on its strong tier rather
        # than dropping to the weak one. On H1 (30/70) RSI 30 scored +8
        # while RSI 70 scored -15.
        elif rsi_value <= rsi_oversold:
            return {"recommendation": "BUY", "score": 15, "confidence": 80, "reason": f"Oversold ({rsi_value:.1f})"}
        elif rsi_value < 40:
            return {"recommendation": "NEUTRAL", "score": 8, "confidence": 60, "reason": f"Approaching oversold ({rsi_value:.1f})"}
        elif rsi_value <= 60:
            return {"recommendation": "NEUTRAL", "score": 0, "confidence": 50, "reason": f"Neutral ({rsi_value:.1f})"}
        elif rsi_value < rsi_overbought:
            return {"recommendation": "NEUTRAL", "score": -8, "confidence": 60, "reason": f"Approaching overbought ({rsi_value:.1f})"}
        elif rsi_value < RSI_EXTREME_OVERBOUGHT:
            return {"recommendation": "SELL", "score": -15, "confidence": 80, "reason": f"Overbought ({rsi_value:.1f})"}
        else:
            return {"recommendation": "SELL", "score": -20, "confidence": 85, "reason": f"Extreme overbought ({rsi_value:.1f})"}
    else:
        # >=, mirroring the BUY branch's <= on the oversold extreme.
        if rsi_value >= RSI_EXTREME_OVERBOUGHT:
            return {"recommendation": "SELL", "score": 20, "confidence": 90, "reason": f"Extreme overbought ({rsi_value:.1f})"}
        # >=, mirroring the BUY branch's <= on the oversold threshold.
        elif rsi_value >= rsi_overbought:
            return {"recommendation": "SELL", "score": 15, "confidence": 80, "reason": f"Overbought ({rsi_value:.1f})"}
        elif rsi_value > 60:
            return {"recommendation": "NEUTRAL", "score": 8, "confidence": 60, "reason": f"Approaching overbought ({rsi_value:.1f})"}
        elif rsi_value >= 40:
            return {"recommendation": "NEUTRAL", "score": 0, "confidence": 50, "reason": f"Neutral ({rsi_value:.1f})"}
        elif rsi_value > rsi_oversold:
            return {"recommendation": "NEUTRAL", "score": -8, "confidence": 60, "reason": f"Approaching oversold ({rsi_value:.1f})"}
        elif rsi_value > RSI_EXTREME_OVERSOLD:
            return {"recommendation": "BUY", "score": -15, "confidence": 80, "reason": f"Oversold ({rsi_value:.1f})"}
        else:
            return {"recommendation": "BUY", "score": -20, "confidence": 85, "reason": f"Extreme oversold ({rsi_value:.1f})"}


def score_stochastic_indicator_with_divergence(k_value: float, d_value: float, divergence_type: str = "NONE") -> Dict[str, Any]:
    """Score Stochastic indicator with divergence impact."""
    if k_value is None or d_value is None:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": "Invalid Stochastic data"}
    
    # ✅ FIXED (asymmetry): the code used a single strict `k > d` and then
    # tested it as `k_above_d` on the oversold side and `not k_above_d` on
    # the overbought side. A TIE (k == d) makes that flag False, which
    # FAILS the bullish condition and PASSES the bearish one -- so every
    # tie resolved bearish:
    #
    #     k=d=10 (deeply oversold)   -> NEUTRAL  +8
    #     k=d=90 (deeply overbought) -> SELL    -18
    #
    # and in the neutral zone k=d=40 scored -5 while k=d=60 scored 0.
    # Measured over 4240 decisions the component agreed with the trade
    # 309 times and opposed it 775 -- a 1:2.5 bearish lean on data whose
    # up and down moves are symmetric by measurement (direction entropy
    # 1.0000, return autocorrelation -0.024).
    #
    # A tie is the absence of a crossover, not a crossover in the
    # bearish direction. Both sides now require an explicit cross.
    k_above_d = k_value > d_value
    k_below_d = k_value < d_value

    if divergence_type == "REGULAR_BULLISH":
        if k_value < STOCH_OVERSOLD:
            return {"recommendation": "BUY", "score": 25, "confidence": 95, "reason": f"Stoch: Regular Bullish Divergence - OVERSOLD (K={k_value:.1f})"}
        else:
            return {"recommendation": "BUY", "score": 18, "confidence": 85, "reason": f"Stoch: Regular Bullish Divergence (K={k_value:.1f})"}
    
    elif divergence_type == "REGULAR_BEARISH":
        if k_value > STOCH_OVERBOUGHT:
            return {"recommendation": "SELL", "score": -25, "confidence": 95, "reason": f"Stoch: Regular Bearish Divergence - OVERBOUGHT (K={k_value:.1f})"}
        else:
            return {"recommendation": "SELL", "score": -18, "confidence": 85, "reason": f"Stoch: Regular Bearish Divergence (K={k_value:.1f})"}
    
    elif divergence_type == "HIDDEN_BULLISH":
        if k_value < STOCH_OVERSOLD:
            return {"recommendation": "BUY", "score": 15, "confidence": 80, "reason": f"Stoch: Hidden Bullish Divergence - OVERSOLD (K={k_value:.1f})"}
        elif k_value > STOCH_OVERBOUGHT:
            return {"recommendation": "NEUTRAL", "score": -3, "confidence": 60, "reason": f"Stoch: Hidden Bullish Divergence - OVERBOUGHT (K={k_value:.1f})"}
        else:
            return {"recommendation": "BUY", "score": 10, "confidence": 70, "reason": f"Stoch: Hidden Bullish Divergence (K={k_value:.1f})"}
    
    elif divergence_type == "HIDDEN_BEARISH":
        if k_value > STOCH_OVERBOUGHT:
            return {"recommendation": "SELL", "score": -15, "confidence": 80, "reason": f"Stoch: Hidden Bearish Divergence - OVERBOUGHT (K={k_value:.1f})"}
        elif k_value < STOCH_OVERSOLD:
            return {"recommendation": "NEUTRAL", "score": 3, "confidence": 60, "reason": f"Stoch: Hidden Bearish Divergence - OVERSOLD (K={k_value:.1f})"}
        else:
            return {"recommendation": "SELL", "score": -10, "confidence": 70, "reason": f"Stoch: Hidden Bearish Divergence (K={k_value:.1f})"}
    
    # NO DIVERGENCE - Normal Stochastic scoring
    if k_value < STOCH_OVERSOLD:
        if d_value < STOCH_OVERSOLD and k_above_d:
            return {"recommendation": "BUY", "score": 18, "confidence": 85, "reason": f"Oversold, K crosses above D ({k_value:.1f})"}
        elif d_value < STOCH_OVERSOLD:
            return {"recommendation": "NEUTRAL", "score": 8, "confidence": 60, "reason": f"Oversold ({k_value:.1f})"}
        else:
            return {"recommendation": "BUY", "score": 12, "confidence": 70, "reason": f"Oversold region ({k_value:.1f})"}
    elif k_value > STOCH_OVERBOUGHT:
        if d_value > STOCH_OVERBOUGHT and k_below_d:
            return {"recommendation": "SELL", "score": -18, "confidence": 85, "reason": f"Overbought, K crosses below D ({k_value:.1f})"}
        elif d_value > STOCH_OVERBOUGHT:
            return {"recommendation": "NEUTRAL", "score": -8, "confidence": 60, "reason": f"Overbought ({k_value:.1f})"}
        else:
            return {"recommendation": "SELL", "score": -12, "confidence": 70, "reason": f"Overbought region ({k_value:.1f})"}
    else:
        if k_above_d and k_value > 50:
            return {"recommendation": "NEUTRAL", "score": 5, "confidence": 40, "reason": f"Bullish crossover in neutral zone ({k_value:.1f})"}
        elif k_below_d and k_value < 50:
            return {"recommendation": "NEUTRAL", "score": -5, "confidence": 40, "reason": f"Bearish crossover in neutral zone ({k_value:.1f})"}
        else:
            return {"recommendation": "NEUTRAL", "score": 0, "confidence": 30, "reason": f"Neutral ({k_value:.1f})"}


def score_macd_indicator(
    macd_line: float, 
    macd_signal: float, 
    histogram: float, 
    avg_price: float = 1.0,
    prev_histogram: float = None,
    trend_strength: float = 0
) -> Dict[str, Any]:
    """
    Score MACD indicator with dynamic threshold and recovery detection.
    ✅ FIXED: Now uses recovery detection and reduced weight in strong trends.
    """
    if macd_line is None or macd_signal is None:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": "Invalid MACD data"}
    
    diff = macd_line - macd_signal
    dynamic_threshold = max(1e-7, avg_price * 1e-6)
    threshold = min(MACD_BULLISH_THRESHOLD, dynamic_threshold)
    # ✅ FIXED: this was named `histogram_increasing` but tested
    # `histogram > 0` -- the SIGN of the histogram, not whether it is
    # increasing. Nothing downstream noticed because the name read
    # correctly, so branches gated on it emitted "hist rising" / "hist
    # falling" reasons that were actually reporting "hist positive" /
    # "hist negative". Confirmed live (XAGUSD M1): histogram 0.00496 vs
    # prev_histogram 0.01110 -- collapsing by 55% -- was scored BUY at
    # the MAXIMUM confidence branch (15/80) with reason "hist rising",
    # while the same payload's own debug field correctly read "falling".
    #
    # Renamed to what it actually measures. The real direction test is
    # hist_improving below, which already existed and was only being
    # consulted in the recovery branch.
    histogram_positive = histogram > 0 if histogram else False
    
    # Check if histogram is improving (recovery detection)
    # None (not False) when there is no previous bar to compare against,
    # so "we can't tell" stays distinct from "it fell". The branches
    # below only claim a direction on an explicit True/False.
    hist_improving = None
    if prev_histogram is not None:
        hist_improving = histogram > prev_histogram
    
    # ✅ FIXED (asymmetry): "recovering" existed ONLY for the bearish
    # side. A bearish MACD whose histogram was improving got downgraded
    # to NEUTRAL, while a bullish MACD whose histogram was DETERIORATING
    # kept its BUY. The same weakening evidence therefore suppressed a
    # SELL and preserved a BUY.
    #
    # Measured on a 4240-decision EURUSD replay: 1997 BUY calls against
    # 1162 SELL -- a 63/37 split on data whose up and down moves are
    # symmetric by measurement (direction entropy 1.0000, return
    # autocorrelation -0.024). An indicator cannot honestly be that
    # one-sided on a symmetric series; the split was the missing mirror
    # branch, not the market.
    #
    # Both sides now use the same rule: momentum moving AGAINST the
    # crossover's direction means the impulse is fading, and a fading
    # impulse is not a signal in either direction.
    fading_bull = diff > 0 and hist_improving is False
    recovering_bear = diff < 0 and hist_improving is True

    if recovering_bear or fading_bull:
        near = abs(diff) < threshold * 2
        if recovering_bear:
            score = -3 if near else -5
            detail = "bearish but improving"
        else:
            # Mirrored sign: a fading BULL is evidence against the long,
            # so it scores positive-but-small the way a recovering bear
            # scores negative-but-small against the short.
            score = 3 if near else 5
            detail = "bullish but fading"
        return {
            "recommendation": "NEUTRAL",
            "score": score,
            "confidence": 60 if near else 55,
            "reason": f"MACD {detail} (diff={diff:.6f})",
            "is_recovering": True,
        }
    
    # Normal MACD scoring (when not recovering)
    # The top-confidence branches (80) now require BOTH that the histogram
    # is on the right side of zero AND that it is actually moving that way.
    # A positive-but-collapsing histogram is a fading bullish impulse, not
    # a maximum-conviction one, and drops to the 70-confidence branch.
    if diff > threshold:
        if histogram_positive and histogram > threshold and hist_improving is True:
            score = 15
            confidence = 80
            rec = "BUY"
            reason = f"Bullish crossover, hist rising ({diff:.6f})"
        else:
            score = 12
            confidence = 70
            rec = "BUY"
            fading = " (hist fading)" if hist_improving is False else ""
            reason = f"Bullish crossover{fading} ({diff:.6f})"
    elif diff < -threshold:
        if (not histogram_positive) and histogram < -threshold and hist_improving is False:
            score = -15
            confidence = 80
            rec = "SELL"
            reason = f"Bearish crossover, hist falling ({diff:.6f})"
        else:
            score = -12
            confidence = 70
            rec = "SELL"
            fading = " (hist fading)" if hist_improving is True else ""
            reason = f"Bearish crossover{fading} ({diff:.6f})"
    else:
        # Near the crossover, direction of travel is the whole signal, so
        # these branches key on hist_improving alone. Unknown direction
        # (no previous bar) falls through to flat rather than guessing.
        if hist_improving is True:
            score = 5
            confidence = 50
            rec = "NEUTRAL"
            reason = f"Near crossover, histogram rising ({diff:.6f})"
        elif hist_improving is False and histogram < 0:
            score = -5
            confidence = 50
            rec = "NEUTRAL"
            reason = f"Near crossover, histogram falling ({diff:.6f})"
        else:
            score = 0
            confidence = 40
            rec = "NEUTRAL"
            reason = f"Flat MACD ({diff:.6f})"
    
    # Reduce MACD weight in strong trends (ADX > 50)
    if trend_strength > 50:
        score = score * 0.6
        confidence = confidence * 0.7
        reason += " (reduced weight in strong trend)"
    
    return {
        "recommendation": rec,
        "score": score,
        "confidence": confidence,
        "reason": reason,
        # Reaching here means neither the recovering-bear nor the
        # fading-bull branch fired -- both return early above.
        "is_recovering": False,
    }


BB_SQUEEZE_PERCENTILE = 0.15   # same cut as the regime classifier's SQUEEZE


def score_bollinger_indicator(current_price: float, upper: float, middle: float, lower: float, bandwidth: float, symbol: str = "DEFAULT",
                              bandwidth_percentile: float = None) -> Dict[str, Any]:
    """
    ⚠️ PRICE BASIS. current_price here is tick.ask (asset_analysis.py:1334),
    while upper/middle/lower are derived from bar CLOSE prices, which are
    bid-side. The comparison is therefore ask-vs-bid-derived-levels.

    On a wide-spread instrument that is not a rounding difference. Live
    XAGUSD: band width 355.6 pips, spread 43 pips -- so every read is
    shifted 12.1% up the band by the spread alone, a systematic bullish
    bias that is LARGEST exactly when spreads widen and the read is least
    trustworthy. Live 00:08: bid close 68.767 gives percent_b 0.426
    (below middle); the ask 68.810 gives 0.547 (above middle). Same bar.

    Not changed here -- switching the whole pipeline to mid prices affects
    zone distance, FVG proximity, S/R distance and more, and is a
    deliberate decision rather than a local fix. What IS fixed is the
    self-contradiction it caused: this function now returns the position
    label it actually used, so the published block can stop mixing this
    price with the one _calculate_bollinger_bands() used.
    """
    """Score Bollinger Bands indicator."""
    if upper is None or middle is None or lower is None or upper <= lower:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": "Invalid BB data", "position": derived_position, "price_basis": "ask"}
    
    # ✅ FIXED: was bandwidth < BB_SQUEEZE_THRESHOLD (a flat 0.05 for
    # every instrument). calculate_real_probability() (calculations.py,
    # the function that actually determines best_probability) uses the
    # instrument-aware get_bb_squeeze_threshold(symbol) for this exact
    # same "is this a squeeze" question -- this was a genuine, visible
    # contradiction: the squeeze status DISPLAYED in this indicator's
    # own recommendation/score/confidence could disagree with what the
    # real decision engine used internally for the same bar. Now uses
    # the same instrument-aware threshold both places agree on.
    is_squeeze = bandwidth < get_bb_squeeze_threshold(symbol)
    # ✅ (2026-09-15) with the bandwidth's own percentile available, a squeeze
    # is "narrow for this instrument lately" -- the regime classifier's
    # SQUEEZE definition. The fixed 0.5%-of-price threshold is ~8x the M1
    # bandwidth of a currency pair, so every M1 bar read as a squeeze.
    if bandwidth_percentile is not None:
        is_squeeze = bandwidth_percentile <= BB_SQUEEZE_PERCENTILE

    # Position derived from the SAME price used for the branches below,
    # so `position` and `reason` can no longer disagree.
    if current_price > upper:
        derived_position = "ABOVE_UPPER"
    elif current_price < lower:
        derived_position = "BELOW_LOWER"
    elif current_price > middle:
        derived_position = "ABOVE_MIDDLE"
    elif current_price < middle:
        derived_position = "BELOW_MIDDLE"
    else:
        derived_position = "AT_MIDDLE"

    if current_price <= lower:
        if is_squeeze:
            return {"recommendation": "BUY", "score": 10, "confidence": 50, "reason": "Price below lower band (squeeze)", "position": derived_position, "price_basis": "ask"}
        else:
            return {"recommendation": "BUY", "score": 20, "confidence": 75, "reason": "Price below lower band", "position": derived_position, "price_basis": "ask"}
    elif current_price >= upper:
        if is_squeeze:
            return {"recommendation": "SELL", "score": -10, "confidence": 50, "reason": "Price above upper band (squeeze)", "position": derived_position, "price_basis": "ask"}
        else:
            return {"recommendation": "SELL", "score": -20, "confidence": 75, "reason": "Price above upper band", "position": derived_position, "price_basis": "ask"}
    elif current_price < middle:
        if is_squeeze:
            return {"recommendation": "NEUTRAL", "score": 3, "confidence": 30, "reason": "Below middle band (squeeze)", "position": derived_position, "price_basis": "ask"}
        else:
            return {"recommendation": "NEUTRAL", "score": 5, "confidence": 50, "reason": "Below middle band", "position": derived_position, "price_basis": "ask"}
    elif current_price > middle:
        if is_squeeze:
            return {"recommendation": "NEUTRAL", "score": -3, "confidence": 30, "reason": "Above middle band (squeeze)", "position": derived_position, "price_basis": "ask"}
        else:
            return {"recommendation": "NEUTRAL", "score": -5, "confidence": 50, "reason": "Above middle band", "position": derived_position, "price_basis": "ask"}
    else:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 40, "reason": "At middle band", "position": derived_position, "price_basis": "ask"}


def score_volume_indicator(volume_ratio: float, trend: str, adx_value: float = None,
                           bar_direction: int = None) -> Dict[str, Any]:
    """Score Volume indicator.

    ✅ FIXED: the "very low volume" cutoff was a flat 0.5 regardless of
    market regime. get_volume_threshold(trend, adx) was built specifically
    to make this regime-aware (0.3x in a strong trend, where volume is
    naturally lower relative to a ranging market; 0.5x when there's no
    trend at all to explain reduced participation) but was never called
    anywhere. adx_value is optional and defaults to the old flat 0.5
    behavior if not supplied, so any other caller is unaffected.
    """
    if volume_ratio is None or volume_ratio <= 0:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": "Invalid volume data"}
    
    is_trending = trend in ["STRONG_BULLISH", "BULLISH", "STRONG_BEARISH", "BEARISH"]
    low_volume_threshold = get_volume_threshold(trend, adx_value) if adx_value is not None else 0.5
    
    # ✅ FIXED (2026-09-15): the direction on high volume was the TREND
    # label -- the trend component's reading counted again. Volume's own
    # evidence is effort behind the bar that carried it: heavy volume on a
    # decisive up-bar is buying pressure, on a down-bar selling pressure.
    # With no bar direction supplied the reading is non-directional.
    if volume_ratio >= 1.5:
        if bar_direction and bar_direction > 0:
            return {"recommendation": "BUY", "score": 15, "confidence": 80, "reason": f"High volume on an up-bar ({volume_ratio:.2f}x)"}
        if bar_direction and bar_direction < 0:
            return {"recommendation": "SELL", "score": -15, "confidence": 80, "reason": f"High volume on a down-bar ({volume_ratio:.2f}x)"}
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 50, "reason": f"High volume, no decisive bar ({volume_ratio:.2f}x)"}
    elif volume_ratio >= 1.15:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 45, "reason": f"Above avg volume ({volume_ratio:.2f}x)"}
    elif volume_ratio >= 0.85:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 40, "reason": f"Normal volume ({volume_ratio:.2f}x)"}
    # Thin volume DOUBTS whatever trend is in force, so its sign has to
    # follow that trend -- the same way the high-volume branches above
    # confirm it with +15/-15 and +10/-10.
    #
    # These branches returned a flat negative regardless of direction.
    # Under this module's convention (positive = bullish, cf.
    # score_trend_indicator) that meant low volume cast doubt on an
    # uptrend and CONFIRMED a downtrend -- the identical reading
    # weakening one side and strengthening the other. And with no trend
    # at all it still leaned bearish, which is a directional claim from
    # a non-directional observation.
    _bull = trend in ["STRONG_BULLISH", "BULLISH"]
    _bear = trend in ["STRONG_BEARISH", "BEARISH"]

    if volume_ratio >= low_volume_threshold:
        if _bull:
            return {"recommendation": "NEUTRAL", "score": -5, "confidence": 35, "reason": f"Below avg volume, uptrend unconfirmed ({volume_ratio:.2f}x, threshold {low_volume_threshold:.2f}x)"}
        if _bear:
            return {"recommendation": "NEUTRAL", "score": 5, "confidence": 35, "reason": f"Below avg volume, downtrend unconfirmed ({volume_ratio:.2f}x, threshold {low_volume_threshold:.2f}x)"}
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 35, "reason": f"Below avg volume, no trend to doubt ({volume_ratio:.2f}x)"}
    else:
        if _bull:
            return {"recommendation": "NEUTRAL", "score": -10, "confidence": 50, "reason": f"Very low volume, uptrend suspect ({volume_ratio:.2f}x)"}
        if _bear:
            return {"recommendation": "NEUTRAL", "score": 10, "confidence": 50, "reason": f"Very low volume, downtrend suspect ({volume_ratio:.2f}x)"}
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 40, "reason": f"Very low volume, no trend to doubt ({volume_ratio:.2f}x)"}


def score_trend_indicator(trend: str, adx_value: float) -> Dict[str, Any]:
    """Score Trend indicator."""
    if adx_value is None:
        adx_value = 0
    
    if trend == "STRONG_BULLISH":
        if adx_value > 50:
            return {"recommendation": "BUY", "score": 25, "confidence": 90, "reason": f"Strong bullish trend, ADX {adx_value:.1f}"}
        else:
            return {"recommendation": "BUY", "score": 20, "confidence": 75, "reason": f"Bullish trend, ADX {adx_value:.1f}"}
    elif trend == "BULLISH":
        return {"recommendation": "BUY", "score": 15, "confidence": 65, "reason": f"Bullish trend, ADX {adx_value:.1f}"}
    elif trend == "STRONG_BEARISH":
        if adx_value > 50:
            return {"recommendation": "SELL", "score": -25, "confidence": 90, "reason": f"Strong bearish trend, ADX {adx_value:.1f}"}
        else:
            return {"recommendation": "SELL", "score": -20, "confidence": 75, "reason": f"Bearish trend, ADX {adx_value:.1f}"}
    elif trend == "BEARISH":
        return {"recommendation": "SELL", "score": -15, "confidence": 65, "reason": f"Bearish trend, ADX {adx_value:.1f}"}
    else:
        if adx_value > 40:
            return {"recommendation": "NEUTRAL", "score": 5, "confidence": 40, "reason": f"Strong ADX but neutral trend ({adx_value:.1f})"}
        else:
            return {"recommendation": "NEUTRAL", "score": 0, "confidence": 30, "reason": f"Neutral trend, ADX {adx_value:.1f}"}


def score_supply_demand_indicator(
    zone_grade: str, 
    is_at_zone: bool, 
    zone_type: str,
    zone_score: int = 0
) -> Dict[str, Any]:
    """Score Supply/Demand zone indicator using adjusted score."""
    
    if zone_grade == "A" and is_at_zone:
        if zone_type == "DEMAND":
            return {"recommendation": "BUY", "score": min(25, zone_score // 4), "confidence": min(95, zone_score), "reason": f"Grade A Demand Zone - At Zone (adjusted score: {zone_score})"}
        elif zone_type == "SUPPLY":
            return {"recommendation": "SELL", "score": -min(25, zone_score // 4), "confidence": min(95, zone_score), "reason": f"Grade A Supply Zone - At Zone (adjusted score: {zone_score})"}
    elif zone_grade == "B" and is_at_zone:
        if zone_type == "DEMAND":
            return {"recommendation": "BUY", "score": min(20, zone_score // 4), "confidence": min(85, zone_score), "reason": f"Grade B Demand Zone - At Zone (adjusted score: {zone_score})"}
        elif zone_type == "SUPPLY":
            return {"recommendation": "SELL", "score": -min(20, zone_score // 4), "confidence": min(85, zone_score), "reason": f"Grade B Supply Zone - At Zone (adjusted score: {zone_score})"}
    elif zone_grade in ["A", "B"] and not is_at_zone:
        if zone_type == "DEMAND":
            return {"recommendation": "NEUTRAL", "score": 5, "confidence": 50, "reason": f"Grade {zone_grade} Demand Zone - Nearby (adjusted score: {zone_score})"}
        elif zone_type == "SUPPLY":
            return {"recommendation": "NEUTRAL", "score": -5, "confidence": 50, "reason": f"Grade {zone_grade} Supply Zone - Nearby (adjusted score: {zone_score})"}
    elif zone_grade == "C" and is_at_zone:
        if zone_type == "DEMAND":
            return {"recommendation": "NEUTRAL", "score": 3, "confidence": 40, "reason": f"Grade C Demand Zone - At Zone (adjusted score: {zone_score})"}
        elif zone_type == "SUPPLY":
            return {"recommendation": "NEUTRAL", "score": -3, "confidence": 40, "reason": f"Grade C Supply Zone - At Zone (adjusted score: {zone_score})"}
    else:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 20, "reason": f"No significant zone or zone invalid (grade: {zone_grade}, score: {zone_score})"}


def score_candlestick_indicator(candle_score: float, candle_type: str) -> Dict[str, Any]:
    """Score Candlestick indicator."""
    if candle_score is None:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 0, "reason": "Invalid candle data"}
    
    if candle_score >= 20:
        return {"recommendation": "BUY", "score": candle_score, "confidence": 80, "reason": f"Bullish candle: {candle_type}"}
    elif candle_score >= 10:
        return {"recommendation": "BUY", "score": candle_score, "confidence": 60, "reason": f"Moderately bullish: {candle_type}"}
    elif candle_score <= -20:
        return {"recommendation": "SELL", "score": candle_score, "confidence": 80, "reason": f"Bearish candle: {candle_type}"}
    elif candle_score <= -10:
        return {"recommendation": "SELL", "score": candle_score, "confidence": 60, "reason": f"Moderately bearish: {candle_type}"}
    else:
        return {"recommendation": "NEUTRAL", "score": 0, "confidence": 30, "reason": f"Neutral candle: {candle_type}"}
def _analyze_trend_component(rates: np.ndarray, symbol: str, pip_size: float, timeframe: str = "M1") -> Dict[str, Any]:
    """Analyze trend component with timeframe support."""
    trend, ema_20, ema_50, ema_200, adx_value = _detect_trend_bias(rates, symbol, pip_size, timeframe)
    if trend == "FLAT_NEUTRAL":
        trend = "NEUTRAL"
    
    if trend in ["STRONG_BULLISH", "BULLISH"]:
        trend_rec = "STRONG_BUY" if trend == "STRONG_BULLISH" else "BUY"
        trend_score = 95 if trend == "STRONG_BULLISH" else 75
    elif trend in ["STRONG_BEARISH", "BEARISH"]:
        trend_rec = "STRONG_SELL" if trend == "STRONG_BEARISH" else "SELL"
        trend_score = 95 if trend == "STRONG_BEARISH" else 75
    else:
        trend_rec = "NEUTRAL"
        trend_score = 0
    
    return {
        "trend": trend,
        "ema_20": ema_20,
        "ema_50": ema_50,
        "ema_200": ema_200,
        "adx_value": adx_value,
        "recommendation": trend_rec,
        "score": trend_score
    }


def _analyze_trend_component_with_divergence(
    rates: np.ndarray, 
    symbol: str, 
    pip_size: float, 
    timeframe: str = "M1",
    rsi_divergence_type: str = "NONE",
    stoch_divergence_type: str = "NONE"
) -> Dict[str, Any]:
    """Analyze trend component WITH divergence impact."""
    # Get base trend
    trend, ema_20, ema_50, ema_200, adx_value = _detect_trend_bias(rates, symbol, pip_size, timeframe)
    
    if trend == "FLAT_NEUTRAL":
        trend = "NEUTRAL"
    
    # Determine divergence direction
    divergence_direction = None
    divergence_type_label = None
    
    if rsi_divergence_type == "REGULAR_BULLISH":
        divergence_direction = "BULLISH"
        divergence_type_label = "REVERSAL"
    elif rsi_divergence_type == "REGULAR_BEARISH":
        divergence_direction = "BEARISH"
        divergence_type_label = "REVERSAL"
    elif rsi_divergence_type == "HIDDEN_BULLISH":
        divergence_direction = "BULLISH"
        divergence_type_label = "CONTINUATION"
    elif rsi_divergence_type == "HIDDEN_BEARISH":
        divergence_direction = "BEARISH"
        divergence_type_label = "CONTINUATION"
    
    if divergence_direction is None:
        if stoch_divergence_type == "REGULAR_BULLISH":
            divergence_direction = "BULLISH"
            divergence_type_label = "REVERSAL"
        elif stoch_divergence_type == "REGULAR_BEARISH":
            divergence_direction = "BEARISH"
            divergence_type_label = "REVERSAL"
        elif stoch_divergence_type == "HIDDEN_BULLISH":
            divergence_direction = "BULLISH"
            divergence_type_label = "CONTINUATION"
        elif stoch_divergence_type == "HIDDEN_BEARISH":
            divergence_direction = "BEARISH"
            divergence_type_label = "CONTINUATION"
    
    if divergence_direction is None:
        final_trend = trend
    else:
        if divergence_type_label == "REVERSAL":
            final_trend = f"STRONG_{divergence_direction}"
            logger.info(f"[TREND] {divergence_type_label} divergence: REVERSAL from {trend} to {divergence_direction}")
        else:
            if trend in [f"STRONG_{divergence_direction}", divergence_direction]:
                final_trend = f"STRONG_{divergence_direction}"
                logger.info(f"[TREND] {divergence_type_label} divergence: CONTINUATION confirms {divergence_direction}")
            else:
                # ✅ FIXED: this branch used to be IDENTICAL to the
                # "confirms" branch above -- final_trend was forced to
                # STRONG_{divergence_direction} even when the base trend
                # didn't already point that way at all, including when
                # base trend was NEUTRAL or flatly the OPPOSITE direction.
                # A continuation-type divergence is only meaningful as
                # confirmation of an EXISTING trend; forcing "STRONG" onto
                # a trend that wasn't there fabricates a stronger reading
                # than the real ADX/EMA structure supports, and every
                # downstream consumer of trend_data["trend"] -- Wyckoff,
                # H1 alignment, regime classification, entry gating --
                # inherits that fabricated label with no way to know it
                # didn't come from actual trend structure. Base trend is
                # preserved instead; the divergence is still fully
                # reported via divergence_impact below, so no information
                # is lost, it just no longer silently overwrites a trend
                # field it doesn't support.
                final_trend = trend
                logger.info(f"[TREND] {divergence_type_label} divergence: {divergence_direction} noted, but base trend ({trend}) doesn't already point that way -- not escalating to STRONG")
    
    if adx_value < 25 and final_trend != "NEUTRAL":
        final_trend = final_trend.replace("STRONG_", "")
    
    if final_trend in ["STRONG_BULLISH", "BULLISH"]:
        trend_rec = "STRONG_BUY" if final_trend == "STRONG_BULLISH" else "BUY"
        trend_score = 95 if final_trend == "STRONG_BULLISH" else 75
    elif final_trend in ["STRONG_BEARISH", "BEARISH"]:
        trend_rec = "STRONG_SELL" if final_trend == "STRONG_BEARISH" else "SELL"
        trend_score = 95 if final_trend == "STRONG_BEARISH" else 75
    else:
        trend_rec = "NEUTRAL"
        trend_score = 0
    
    return {
        "trend": final_trend,
        "base_trend": trend,
        "ema_20": ema_20,
        "ema_50": ema_50,
        "ema_200": ema_200,
        "adx_value": adx_value,
        "recommendation": trend_rec,
        "score": trend_score,
        "divergence_impact": {
            "rsi_divergence": rsi_divergence_type,
            "stoch_divergence": stoch_divergence_type,
            "divergence_direction": divergence_direction,
            "divergence_type": divergence_type_label
        }
    }


MACD_CROSS_BARS = 3   # a histogram zero-cross this recent is the MACD signal


def _analyze_indicators_component(
    close_prices: List[float],
    high_prices: List[float],
    low_prices: List[float],
    volumes: List[float],
    timeframe: str,
    current_price: float,
    pip_size: float,
    volume_ratio: float,
    volume_increasing: bool,
    trend: str,
    symbol: str = "DEFAULT"
) -> Dict[str, Any]:
    """Analyze technical indicators component."""
    rsi = _calculate_rsi(close_prices, 14)
    rsi_val = validate_rsi_value(rsi[-1] if rsi else DEFAULT_RSI_VALUE, "RSI14", DEFAULT_RSI_VALUE)
    rsi_14 = rsi_val
    
    rsi_21_raw = _calculate_rsi(close_prices, 21)
    rsi_21 = validate_rsi_value(rsi_21_raw[-1] if rsi_21_raw else DEFAULT_RSI_VALUE, "RSI21", DEFAULT_RSI_VALUE)
    
    if len(rsi) >= 5:
        rsi_trend = "rising" if rsi[-1] > rsi[-3] else "falling" if rsi[-1] < rsi[-3] else "flat"
    else:
        rsi_trend = "unknown"
    
    if len(close_prices) >= 5:
        price_trend = "rising" if close_prices[-1] > close_prices[-3] else "falling" if close_prices[-1] < close_prices[-3] else "flat"
    else:
        price_trend = "unknown"
    
    # ✅ REMOVED (was dead + misleading): this function used to also run
    # _detect_rsi_divergence() on the SAME timeframe here and stash it as
    # "rsi_divergence" purely for the report. It was never the divergence
    # actually used to score RSI — the real scoring divergence is the
    # cross-timeframe M15 one (m15_div_type, from get_m15_divergence()),
    # fed into score_rsi_indicator_with_divergence() at the call site.
    # Keeping both meant the report could show e.g. "divergence: NONE"
    # for the same-timeframe check while the RSI score actually used
    # elsewhere reflected an M15 REGULAR_BULLISH divergence — two
    # different "RSI divergence" answers with no visible link between
    # them. RSI now has exactly one divergence result, computed once,
    # scored once, and reported from that same single result (see the
    # "8_indicators.rsi" report block, which now reads straight from
    # rsi_indicator instead of recomputing its own answer).
    
    # ✅ FIXED: was calling _calculate_bollinger_bands(close_prices) with
    # no period/std args, so it always used the flat defaults (20, 2.0)
    # regardless of timeframe -- get_bb_period()/get_bb_std() were built
    # specifically to widen M1 to (50, 2.5) "to filter noise" per their
    # own config comments, but were never actually called anywhere.
    bb_period = get_bb_period(timeframe)
    bb_std = get_bb_std(timeframe)
    bb_upper, bb_middle, bb_lower, bb_position, bb_signal, bb_width = _calculate_bollinger_bands(
        close_prices, period=bb_period, std_dev=bb_std
    )
    
    # ✅ FIXED: was bb_width < BB_SQUEEZE_THRESHOLD (flat 0.05 for every
    # instrument) -- same contradiction as score_bollinger_indicator's
    # fix above: calculate_real_probability() actually uses the
    # instrument-aware get_bb_squeeze_threshold(symbol) for this exact
    # question, so the displayed "is_squeeze" here could disagree with
    # what the real decision engine used internally for the same bar.
    is_squeeze = bb_width < get_bb_squeeze_threshold(symbol)
    
    percent_b = (current_price - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
    
    macd_line, macd_signal_line, macd_histogram, macd_signal = _calculate_macd(close_prices)
    
    # Track previous histogram for recovery detection
    if len(close_prices) >= 50:
        prev_histogram = _calculate_macd(close_prices[:-1])[2]
        histogram_direction = "rising" if macd_histogram > prev_histogram else "falling" if macd_histogram < prev_histogram else "flat"
        # The MACD event (2026-09-15): the histogram changing sign within the
        # last MACD_CROSS_BARS bars. Its sign alone is a state that holds on
        # every bar and voted on 100% of study bars.
        _hist_back = _calculate_macd(close_prices[:-MACD_CROSS_BARS])[2]
        if macd_histogram > 0 and _hist_back is not None and _hist_back <= 0:
            macd_cross_direction = "UP"
        elif macd_histogram < 0 and _hist_back is not None and _hist_back >= 0:
            macd_cross_direction = "DOWN"
        else:
            macd_cross_direction = None
    else:
        prev_histogram = macd_histogram
        histogram_direction = "unknown"
        macd_cross_direction = None
    
    stoch_k, stoch_d, stoch_signal, stoch_k_history = _calculate_stochastic(high_prices, low_prices, close_prices)
    
    volume_confirmed = volume_ratio >= 1.15
    volume_score = 75 if volume_confirmed else 50 if volume_ratio > 1.0 else 0
    if volume_ratio < 0.7:
        volume_score = -50
    
    if volume_confirmed:
        if trend in ["STRONG_BEARISH", "BEARISH"]:
            volume_rec = "CONFIRMS_BEARISH"
        elif trend in ["STRONG_BULLISH", "BULLISH"]:
            volume_rec = "CONFIRMS_BULLISH"
        else:
            volume_rec = "HIGH_VOLUME"
    else:
        volume_rec = "LOW_VOLUME"
    
    volume_score_breakdown = {
        "ratio_penalty": -30 if volume_ratio < 0.3 else -20 if volume_ratio < 0.5 else -10 if volume_ratio < 0.7 else 0,
        "trend_penalty": -20 if not volume_increasing and volume_ratio < 0.8 else 0,
        "total": volume_score
    }
    
    return {
        "rsi": {"value": rsi_val, "rsi_21": rsi_21},
        "rsi_trend": rsi_trend,
        "price_trend": price_trend,
        "bollinger": {
            "upper": bb_upper, 
            "middle": bb_middle, 
            "lower": bb_lower, 
            "position": bb_position, 
            "signal": bb_signal,
            "width": bb_width, 
            "percent_b": percent_b, 
            "is_squeeze": is_squeeze
        },
        "macd": {
            "line": macd_line, 
            "signal": macd_signal_line, 
            "histogram": macd_histogram,
            "prev_histogram": prev_histogram,
            "signal_str": macd_signal, 
            "histogram_direction": histogram_direction,
            "cross_direction": macd_cross_direction,
        },
        "stochastic": {"k": stoch_k, "d": stoch_d, "signal": stoch_signal},
        "volume": {"confirmed": volume_confirmed, "score": volume_score, "rec": volume_rec, "breakdown": volume_score_breakdown},
        # ✅ ADDED: full oscillator history, for core/adaptive_thresholds.py's
        # percentile-based bands. Both were already being computed inside
        # this function and discarded after taking the last value -- this
        # is purely additive, no existing key changed.
        "history": {"rsi": rsi, "stochastic_k": stoch_k_history}
    }


# Support / resistance as LEVELS (2026-09-15). The component used to call
# price above/below a 20-bar pivot "support/resistance" -- a direction on
# 99.6% of bars -- and detected breakouts only upward, labelling an upward
# break in a bearish trend "BREAKOUT_SELL". It also took the trend component's
# reading into its own vote, counting trend twice.
SR_LOOKBACK_BARS = 100          # swing levels considered
SR_BREAKOUT_BARS = 20           # range whose break is a breakout (excluding the last bar)
SR_BREAKOUT_ATR = 0.10          # a close this far beyond the range is a break, not a poke
SR_AT_LEVEL_ATR = 0.25          # within this of a level is "at" it


def _bar_atr(high_prices, low_prices, close_prices, bars: int = 14) -> float:
    n = len(close_prices)
    if n < bars + 1:
        return 0.0
    tr = [max(high_prices[i] - low_prices[i], abs(high_prices[i] - close_prices[i - 1]),
              abs(low_prices[i] - close_prices[i - 1])) for i in range(n - bars, n)]
    return sum(tr) / bars


def _sr_levels(high_prices, low_prices, price: float, atr_price: float):
    """Nearest swing-low support below and swing-high resistance above."""
    from core.swing_points import find_swing_points

    highs = list(high_prices[-SR_LOOKBACK_BARS:])
    lows = list(low_prices[-SR_LOOKBACK_BARS:])
    amp = 0.5 * atr_price
    resist = [p["price"] for p in find_swing_points(highs, lookback=5, min_amplitude=amp)
              if p["type"] == "high" and p["price"] >= price]
    support = [p["price"] for p in find_swing_points(lows, lookback=5, min_amplitude=amp)
               if p["type"] == "low" and p["price"] <= price]
    return (max(support) if support else None), (min(resist) if resist else None)


def _analyze_support_resistance_component(
    high_prices: List[float],
    low_prices: List[float],
    close_prices: List[float],
    current_price: float,
    pip_size: float,
    volume_ratio: float,
    trend: str,
    atr_pips: float = None,
) -> Dict[str, Any]:
    """Support/resistance levels and what price is doing at them.

    BREAKOUT_BUY / BREAKOUT_SELL  last close beyond the prior 20-bar range
    SUPPORT_BUY / RESISTANCE_SELL price at a swing level (within 0.25 ATR)
    NEUTRAL                       otherwise -- no level in play, no vote
    `trend` is accepted for the old signature and deliberately unused.
    """
    pivot_data = calculate_pivot_levels(high_prices, low_prices, close_prices)
    atr_price = (atr_pips * pip_size) if atr_pips and pip_size else _bar_atr(high_prices, low_prices, close_prices)
    price = float(current_price)
    last_close = float(close_prices[-1]) if close_prices else price

    prior_high = max(high_prices[-SR_BREAKOUT_BARS - 1:-1]) if len(high_prices) > SR_BREAKOUT_BARS else pivot_data["high_20"]
    prior_low = min(low_prices[-SR_BREAKOUT_BARS - 1:-1]) if len(low_prices) > SR_BREAKOUT_BARS else pivot_data["low_20"]
    margin = SR_BREAKOUT_ATR * atr_price
    breakout_up = last_close > prior_high + margin
    breakout_down = last_close < prior_low - margin

    support, resistance = _sr_levels(high_prices, low_prices, price, atr_price) if atr_price > 0 else (None, None)
    near = SR_AT_LEVEL_ATR * atr_price
    at_support = support is not None and price - support <= near
    at_resistance = resistance is not None and resistance - price <= near

    confirmed = volume_ratio >= 1.2
    if breakout_up and not breakout_down:
        sr_rec, sr_score = "BREAKOUT_BUY", 85 if confirmed else 60
    elif breakout_down and not breakout_up:
        sr_rec, sr_score = "BREAKOUT_SELL", 85 if confirmed else 60
    elif at_support and not at_resistance:
        sr_rec, sr_score = "SUPPORT_BUY", 70
    elif at_resistance and not at_support:
        sr_rec, sr_score = "RESISTANCE_SELL", 70
    else:
        sr_rec, sr_score = "NEUTRAL", 0

    to_pips = (lambda d: round(d / pip_size, 1)) if pip_size else (lambda d: None)
    return {
        "high_period": pivot_data["high_20"],
        "low_period": pivot_data["low_20"],
        "pivot": pivot_data["pivot"],
        "r1": pivot_data["r1"], "r2": pivot_data["r2"], "r3": pivot_data["r3"],
        "s1": pivot_data["s1"], "s2": pivot_data["s2"], "s3": pivot_data["s3"],
        "breakout": bool(breakout_up or breakout_down),
        "breakout_direction": "UP" if breakout_up else "DOWN" if breakout_down else None,
        "support_level": support,
        "resistance_level": resistance,
        # ✅ FIXED 2026-09-16: was 999.0 when no level was found -- "unknown"
        # published as a measurement, which any model reads as a real 999-pip
        # distance. Absent is None.
        "distance_to_resistance_pips": to_pips(resistance - price) if resistance is not None else None,
        "distance_to_support_pips": to_pips(price - support) if support is not None else None,
        "distance_to_resistance_atr": round((resistance - price) / atr_price, 2) if resistance is not None and atr_price else None,
        "distance_to_support_atr": round((price - support) / atr_price, 2) if support is not None and atr_price else None,
        "recommendation": sr_rec,
        "score": sr_score,
        "recent_swing_high": pivot_data["high_20"],
        "recent_swing_low": pivot_data["low_20"],
    }


# Candle definitions as shares of the bar's own range and of ATR (2026-09-15).
# "Marubozu" used to mean only body > each wick, so a bar that was 40% body
# qualified -- 70% of all study bars read STRONG -- and a 0.3-pip bar counted
# like a 3-ATR one. Plain up/down bars also voted BUY/SELL (score +/-10),
# which put a direction on 84% of bars.
CANDLE_MARUBOZU_BODY_SHARE = 0.75     # body at least 75% of the range
CANDLE_REJECTION_WICK_SHARE = 0.60    # rejection wick at least 60% of the range
CANDLE_MIN_RANGE_ATR = 0.8            # a signal candle spans at least 0.8 ATR


def _analyze_candlestick_component(candle, pip_size: float, atr_pips: float = None) -> Dict[str, Any]:
    """Analyze candlestick component with proper scoring.

    ✅ FIXED: open_price and low_price were reading from the wrong
    columns (open_price <- candle[3], low_price <- candle[1]). MT5's
    real rates column order is time=0, open=1, high=2, low=3, close=4
    (verified directly against the structured-array dtype) -- the same
    convention already used consistently everywhere else in this
    codebase (indicators.py's r[2]=high/r[3]=low, swing_points.py's
    find_swing_points_ohlc(), etc.). With open/low swapped, `body =
    abs(close - open)` was actually computing abs(close - low), and
    `total_range = high - low` was actually computing high - open --
    silently wrong body/wick/range values feeding every downstream
    consumer of candle_data: candle_type classification (doji/marubozu/
    hammer/shooting_star), entry confirmation (entry_engine.py's
    hammer/shooting-star check), the wick-reversal veto, discount-engine
    confirmation, and the new exhaustion/climax filter below.
    """
    try:
        open_price = float(candle[1])
        close_price = float(candle[4])
        high_price = float(candle[2])
        low_price = float(candle[3])
    except (IndexError, TypeError) as e:
        logger.error(f"Failed to parse candle: {e}")
        return {
            "open": 0, "close": 0, "high": 0, "low": 0,
            "body_pips": 0, "upper_wick_pips": 0, "lower_wick_pips": 0,
            "candle_type": "unknown", "recommendation": "NEUTRAL", "score": 0
        }
    
    body = abs(close_price - open_price)
    total_range = high_price - low_price
    
    if close_price >= open_price:
        lower_wick = open_price - low_price
        upper_wick = high_price - close_price
    else:
        lower_wick = close_price - low_price
        upper_wick = high_price - open_price
    
    lower_wick = max(0, lower_wick)
    upper_wick = max(0, upper_wick)
    
    body_pips = body / pip_size if pip_size > 0 else 0
    upper_wick_pips = upper_wick / pip_size if pip_size > 0 else 0
    lower_wick_pips = lower_wick / pip_size if pip_size > 0 else 0
    
    # A tiny body with one dominant wick is a gravestone/dragonfly rejection,
    # not an indecision doji -- those fall through to the wick checks below.
    _dominant_wick = total_range > 0 and max(upper_wick, lower_wick) >= CANDLE_REJECTION_WICK_SHARE * total_range
    if total_range == 0 or (body / total_range < 0.1 and not _dominant_wick):
        return {
            "open": open_price,
            "close": close_price,
            "high": high_price,
            "low": low_price,
            "body_pips": body_pips,
            "upper_wick_pips": upper_wick_pips,
            "lower_wick_pips": lower_wick_pips,
            "candle_type": "doji",
            "recommendation": "NEUTRAL",
            "score": CANDLE_SCORE_DOJI
        }
    
    range_pips = total_range / pip_size if pip_size > 0 else 0
    big_enough = (not atr_pips or atr_pips <= 0) or range_pips >= CANDLE_MIN_RANGE_ATR * atr_pips

    if body >= CANDLE_MARUBOZU_BODY_SHARE * total_range and big_enough:
        candle_type = "marubozu"
        if close_price > open_price:
            candle_rec = "STRONG_BULLISH"
            candle_score = CANDLE_SCORE_MARUBOZU_BULLISH
        else:
            candle_rec = "STRONG_BEARISH"
            candle_score = CANDLE_SCORE_MARUBOZU_BEARISH

    # The wick SIDE decides the pattern (defect D-15): a long upper wick is
    # rejection from above whatever the body colour; the colour only
    # strengthens it.
    elif upper_wick >= body * 2 and upper_wick >= CANDLE_REJECTION_WICK_SHARE * total_range and big_enough:
        candle_type = "shooting_star"
        candle_rec = "BEARISH"
        candle_score = CANDLE_SCORE_SHOOTING_STAR
        if close_price < open_price:
            candle_score = int(CANDLE_SCORE_SHOOTING_STAR * CANDLE_WICK_CONFIRMED_MULT)

    elif lower_wick >= body * 2 and lower_wick >= CANDLE_REJECTION_WICK_SHARE * total_range and big_enough:
        candle_type = "hammer"
        candle_rec = "BULLISH"
        candle_score = CANDLE_SCORE_HAMMER
        if close_price > open_price:
            candle_score = int(CANDLE_SCORE_HAMMER * CANDLE_WICK_CONFIRMED_MULT)

    elif abs(upper_wick - lower_wick) < body * 0.5:
        candle_type = "spinning_top"
        candle_rec = "NEUTRAL"
        candle_score = CANDLE_SCORE_SPINNING_TOP

    else:
        # an ordinary bar is not a pattern: no direction
        candle_type = "normal"
        candle_rec = "NEUTRAL"
        candle_score = 0

    return {
        "open": open_price,
        "close": close_price,
        "high": high_price,
        "low": low_price,
        "body_pips": body_pips,
        "upper_wick_pips": upper_wick_pips,
        "lower_wick_pips": lower_wick_pips,
        "candle_type": candle_type,
        "recommendation": candle_rec,
        "score": candle_score
    }