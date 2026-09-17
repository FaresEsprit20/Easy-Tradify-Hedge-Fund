# ai/component_scorecard.py
"""
Component-by-component scorecard of the stored trades.

trade_evaluation answers "how did the system do, and does ANY field predict
the outcome". This answers the question a trader asks next: for EACH piece of
the analysis -- RSI, MACD, stochastic, volume profile, supply/demand, SMC
structure, VWAP, the wave count -- what happened when it agreed with the trade,
when it disagreed, and when it had no opinion? And the same per strategy
CATEGORY (trend, momentum, mean reversion, structure, SMC, wave...).

READING A COMPONENT
-------------------
Every directional component is reduced to a vote in the TRADE'S frame:
  ALIGNED   it pointed the way the trade was placed
  OPPOSED   it pointed the other way
  NEUTRAL   it was available but had no direction
A component that was absent on a trade is not counted (coverage is reported).

For each state: n, win rate (Wilson 95% CI), expectancy in price R and in net
R (after commission), and $ result. "Edge" is expectancy when ALIGNED minus
expectancy when OPPOSED: a useful component has a clearly positive edge; a
negative edge means the component is INVERTED on this sample.

Non-directional readings (star rating, zone grade, volatility regime...) and
key raw values put in the trade's frame (RSI, stochastic %K, Bollinger %B,
VWAP deviation, premium/discount position) are bucketed the same way.

SIGNIFICANCE
------------
p is a permutation test on the component's best state versus the rest, with
the search over states included in the null; q is Benjamini-Hochberg across
every component in the report. With ~116 trades, q < 0.10 is the bar. A
component above it may still be real -- it has simply not been shown yet.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ai import trade_evaluation as te

SCORECARD_VERSION = "1.0"

CATEGORIES = [
    ("TREND", "Trend following"),
    ("MOMENTUM", "Momentum oscillators"),
    ("MEAN_REVERSION", "Mean reversion"),
    ("VOLUME", "Volume and order flow"),
    ("STRUCTURE", "Structure: zones, S/R, fibs"),
    ("SMC", "Smart money / ICT"),
    ("WAVE", "Waves, patterns and candles"),
    ("AI_MACRO", "GNN and cross-asset"),
    ("DECISION", "Decision and entry quality"),
    ("REGIME", "Market regime and conditions"),
    ("STRATEGY_GROUPS", "Strategy groups (decision engine)"),
]


# ============================================================
# ACCESS AND PARSING
# ============================================================

def g(analysis: Mapping[str, Any], path: str) -> Any:
    """Value at a dotted path; falls back to the m1_analysis_raw copy."""
    for root in (analysis, analysis.get("m1_analysis_raw") or {}):
        node: Any = root
        for part in path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                node = None
                break
            node = node[part]
        if node is not None:
            return node
    return None


def market_direction(value: Any) -> Optional[int]:
    """+1 bullish, -1 bearish, 0 no direction, None absent/unparseable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None
        return 1 if value > 0 else -1 if value < 0 else 0
    text = str(value).strip().upper()
    # Liquidity vocabulary names the side whose stops were taken, not the
    # direction: a BUY_SIDE sweep (stops above highs run) is bearish, a
    # SELL_SIDE sweep bullish. Parsed literally, "BUY_SIDE_SWEEP" and
    # "STOP_HUNT_BUY_SIDE_TRAP" read BUY while the same event's
    # implied_direction read SELL.
    text = text.replace("BUY_SIDE", "BEARISH_LIQUIDITY").replace("SELL_SIDE", "BULLISH_LIQUIDITY")
    if not text or text in ("NONE", "NULL", "N/A") or text.startswith("EXCLUDED"):
        return None
    bull = any(k in text for k in ("BUY", "BULL", "LONG", "DEMAND", "DISCOUNT"))
    bear = any(k in text for k in ("SELL", "BEAR", "SHORT", "SUPPLY", "PREMIUM"))
    if text in ("UP", "ABOVE", "RISING"):
        bull = True
    if text in ("DOWN", "BELOW", "FALLING"):
        bear = True
    if bull and not bear:
        return 1
    if bear and not bull:
        return -1
    return 0


def vote_state(direction: Optional[int], sign: int) -> Optional[str]:
    if direction is None:
        return None
    product = direction * sign
    return "ALIGNED" if product > 0 else "OPPOSED" if product < 0 else "NEUTRAL"


# ---- component builders ---------------------------------------------------

def vote(path: str, *fallbacks: str) -> Callable:
    """A component whose field states a market direction."""
    def read(a, sign):
        for p in (path, *fallbacks):
            state = vote_state(market_direction(g(a, p)), sign)
            if state is not None:
                return state
        return None
    return read


def trade_frame(path: str) -> Callable:
    """A signed number already expressed relative to the trade (+ = supports)."""
    def read(a, sign):
        value = te._num(g(a, path))
        if value is None:
            return None
        return "ALIGNED" if value > 0 else "OPPOSED" if value < 0 else "NEUTRAL"
    return read


def flag_against(path: str) -> Callable:
    """A boolean meaning 'this trade is AGAINST x'."""
    def read(a, sign):
        value = g(a, path)
        if not isinstance(value, bool):
            return None
        return "OPPOSED" if value else "ALIGNED"
    return read


def flag_for(path: str) -> Callable:
    """A boolean meaning 'x supports this trade'."""
    def read(a, sign):
        value = g(a, path)
        if not isinstance(value, bool):
            return None
        return "ALIGNED" if value else "NEUTRAL"
    return read


def category(path: str, max_len: int = 30) -> Callable:
    def read(a, sign):
        value = g(a, path)
        if value is None or isinstance(value, (dict, list)):
            return None
        text = str(value).strip()
        return text[:max_len] if text else None
    return read


def bands(path: str, edges: Sequence[float], labels: Sequence[str],
          frame: Optional[Callable[[float, int], float]] = None) -> Callable:
    """Bucket a number by fixed edges; `frame` re-expresses it for the trade side."""
    def read(a, sign):
        value = te._num(g(a, path))
        if value is None:
            return None
        if frame is not None:
            value = frame(value, sign)
        for edge, label in zip(edges, labels):
            if value < edge:
                return label
        return labels[-1]
    return read


def ema_stack(a, sign):
    ema = g(a, "indicators.trend.ema") or {}
    e9, e50, e200 = (te._num(ema.get(k)) for k in ("ema_9", "ema_50", "ema_200"))
    if None in (e9, e50, e200):
        return None
    direction = 1 if e9 > e50 > e200 else -1 if e9 < e50 < e200 else 0
    return vote_state(direction, sign)


def order_block(a, sign):
    bull, bear = g(a, "smc.analysis.order_blocks.price_in_bullish_ob"), \
        g(a, "smc.analysis.order_blocks.price_in_bearish_ob")
    if not isinstance(bull, bool) or not isinstance(bear, bool):
        bull, bear = g(a, "final_verdict.smc_analysis.order_blocks.price_in_bullish_ob"), \
            g(a, "final_verdict.smc_analysis.order_blocks.price_in_bearish_ob")
    if not isinstance(bull, bool) or not isinstance(bear, bool):
        return None
    return vote_state(1 if bull and not bear else -1 if bear and not bull else 0, sign)


def microflow(a, sign):
    supports, opposes = g(a, "microstructure_bias.flow_supports_trade"), \
        g(a, "microstructure_bias.flow_opposes_trade")
    if not isinstance(supports, bool):
        return None
    return "ALIGNED" if supports else "OPPOSED" if opposes else "NEUTRAL"


def case_balance(a, sign):
    bull, bear = te._num(g(a, "decision_snapshot.bull_case.confidence")), \
        te._num(g(a, "decision_snapshot.bear_case.confidence"))
    if bull is None or bear is None:
        return None
    own, other = (bull, bear) if sign > 0 else (bear, bull)
    return vote_state(1 if own > other else -1 if own < other else 0, 1)


def gnn_direction(a, sign):
    value = te._num(g(a, "gnn.analysis.gnn_direction"))
    if value is None:
        return None
    return vote_state(0 if abs(value) < 0.01 else (1 if value > 0 else -1), sign)


def against_side(value, sign):   # 0-100 oscillator put in the trade's frame
    return value if sign > 0 else 100 - value


def signed(value, sign):
    return value * sign


def percent_b(a, sign):
    value = te._num(g(a, "indicators.bollinger_bands.debug.percent_b"))
    if value is None:
        return None
    value = value if sign > 0 else 1 - value
    return ("< 0 (beyond band, with trade side cheap)" if value < 0 else
            "0-0.2 (near cheap band)" if value < 0.2 else
            "0.2-0.5" if value < 0.5 else
            "0.5-0.8" if value < 0.8 else
            "0.8-1 (near expensive band)" if value <= 1 else
            "> 1 (chasing beyond band)")


# ---- strategy groups: the decision engine since 2026-09-15 ------------------
# Scored with core/strategy_groups.py on the stored payload, so a stored trade
# is judged by exactly the code that now decides live trades.
_GROUP_CACHE: Dict[tuple, Dict[str, Any]] = {}


def _groups_for(a, sign):
    from core.strategy_groups import score_groups
    key = (id(a), sign)
    if key not in _GROUP_CACHE:
        if len(_GROUP_CACHE) > 20000:
            _GROUP_CACHE.clear()
        _GROUP_CACHE[key] = score_groups(a, "BUY" if sign > 0 else "SELL")
    return _GROUP_CACHE[key]


def group_vote(group: str) -> Callable:
    def read(a, sign):
        info = (_groups_for(a, sign).get("groups") or {}).get(group) or {}
        if not info.get("scored"):
            return None
        score = info.get("score", 50)
        return "ALIGNED" if score > 50 else "OPPOSED" if score < 50 else "NEUTRAL"
    return read


def group_state(field: str, edges=None, labels=None) -> Callable:
    def read(a, sign):
        value = _groups_for(a, sign).get(field)
        if value is None:
            return None
        if edges is None:
            return str(value)
        for edge, label in zip(edges, labels):
            if value < edge:
                return label
        return labels[-1]
    return read


def group_other_side(a, sign):
    mine = _groups_for(a, sign).get("final_probability")
    other = _groups_for(a, -sign).get("final_probability")
    if mine is None or other is None:
        return None
    return "OPPOSED" if other > mine else "ALIGNED" if mine > other else "NEUTRAL"


def group_cost(a, sign):
    cost = _groups_for(a, sign).get("cost") or {}
    points = cost.get("penalty_points")
    if points is None:
        return None
    return "< 5 pts" if points < 5 else "5-10 pts" if points < 10 else "10-15 pts" if points < 15 else ">= 15 pts"


# ============================================================
# THE CATALOGUE
# ============================================================
# (name, category, kind, reader, description)
#   kind "vote"  -> ALIGNED / OPPOSED / NEUTRAL, counts toward category agreement
#   kind "state" -> descriptive buckets

RSI_BANDS = ([30, 45, 55, 70], ["< 30 (trade side oversold)", "30-45", "45-55",
                                "55-70", ">= 70 (trade side overbought)"])

CATALOGUE: List[tuple] = [
    # ---------------- TREND
    ("Trend indicator (EMA/ADX)", "TREND", "vote", vote("indicators.trend.recommendation", "indicators.trend.trend"),
     "indicators.trend recommendation"),
    ("Trend cascade M5-H4", "TREND", "vote", vote("trend_cascade.direction"), "slope agreement across M5/M15/H1/H4"),
    ("H1 trend", "TREND", "vote", vote("higher_timeframe.trend"), "higher_timeframe.trend"),
    ("M1 trend (confirmation)", "TREND", "vote", vote("trend_confirmation.m1_trend"), "trend_confirmation.m1_trend"),
    ("Price vs EMA200", "TREND", "vote", vote("trend_confirmation.m1_price_vs_ema200"), "above = bullish"),
    ("EMA stack 9/50/200", "TREND", "vote", ema_stack, "9>50>200 bullish, reverse bearish"),
    ("M5 slope", "TREND", "vote", vote("trend_cascade.timeframes.M5.slope_sign"), ""),
    ("M15 slope", "TREND", "vote", vote("trend_cascade.timeframes.M15.slope_sign"), ""),
    ("H1 slope", "TREND", "vote", vote("trend_cascade.timeframes.H1.slope_sign"), ""),
    ("H4 slope", "TREND", "vote", vote("trend_cascade.timeframes.H4.slope_sign"), ""),
    ("Veto check: against trend", "TREND", "vote", flag_against("vetos.checks.against_trend"), "True = trade against trend"),
    ("Veto check: against EMA", "TREND", "vote", flag_against("vetos.checks.against_ema"), "True = trade against EMA"),
    ("Family score TREND", "TREND", "vote", trade_frame("strategy_family_scores.TREND"), "signed contribution to the trade"),
    ("ADX 14 (strength)", "TREND", "state", bands("indicators.trend.adx.adx_14", [15, 20, 25, 35],
                                                 ["< 15", "15-20", "20-25", "25-35", ">= 35"]), ""),

    # ---------------- MOMENTUM
    ("RSI", "MOMENTUM", "vote", vote("indicators.rsi.recommendation"), "indicators.rsi recommendation"),
    ("RSI adaptive", "MOMENTUM", "vote", vote("indicators.rsi.adaptive.recommendation"), ""),
    ("RSI divergence", "MOMENTUM", "vote", vote("indicators.rsi.divergence.type"), "M15 divergence"),
    ("RSI 14 level (trade frame)", "MOMENTUM", "state", bands("indicators.rsi.rsi_14", *RSI_BANDS, frame=against_side),
     "for a SELL, 100-RSI"),
    ("Stochastic", "MOMENTUM", "vote", vote("indicators.stochastic.recommendation"), ""),
    ("Stochastic cross signal", "MOMENTUM", "vote", vote("indicators.stochastic.signal"), "BULLISH_X / BEARISH_X"),
    ("Stochastic divergence", "MOMENTUM", "vote", vote("indicators.stochastic.divergence.type"), ""),
    ("Stochastic %K (trade frame)", "MOMENTUM", "state", bands("indicators.stochastic.k", [20, 45, 55, 80],
                                                              ["< 20 (oversold)", "20-45", "45-55", "55-80", ">= 80 (overbought)"],
                                                              frame=against_side), ""),
    ("MACD", "MOMENTUM", "vote", vote("indicators.macd.recommendation"), ""),
    ("MACD signal", "MOMENTUM", "vote", vote("indicators.macd.signal"), ""),
    ("MACD histogram", "MOMENTUM", "vote", vote("indicators.macd.histogram"), "sign of histogram"),
    ("TTM squeeze momentum", "MOMENTUM", "vote", vote("ttm_squeeze.momentum_direction"), ""),
    ("TTM squeeze state", "MOMENTUM", "state", category("ttm_squeeze.state"), ""),
    ("Expected value", "MOMENTUM", "vote", vote("indicators.expected_value.recommendation"), ""),

    # ---------------- MEAN REVERSION
    ("Bollinger bands", "MEAN_REVERSION", "vote", vote("indicators.bollinger_bands.recommendation"), ""),
    ("Bollinger signal", "MEAN_REVERSION", "vote", vote("indicators.bollinger_bands.signal"), ""),
    ("Bollinger %B (trade frame)", "MEAN_REVERSION", "state", percent_b, ""),
    ("Bollinger squeeze", "MEAN_REVERSION", "state", category("indicators.bollinger_bands.debug.is_squeeze"), ""),
    ("VWAP context stance", "MEAN_REVERSION", "vote", vote("vwap_context.stance"), ""),
    ("VWAP side (above = bullish)", "MEAN_REVERSION", "vote",
     lambda a, s: None if not isinstance(g(a, "vwap.above_vwap"), bool)
     else vote_state(1 if g(a, "vwap.above_vwap") else -1, s), ""),
    ("VWAP deviation sigma (trade frame)", "MEAN_REVERSION", "state",
     bands("vwap.deviation_sigma", [-2, -1, 0, 1, 2], ["< -2 (deep discount)", "-2..-1", "-1..0", "0..1", "1..2",
                                                       ">= 2 (stretched)"], frame=signed), "negative = entered cheap"),
    ("VWAP zone", "MEAN_REVERSION", "state", category("vwap.zone"), ""),
    ("Anchored VWAP: who is in profit", "MEAN_REVERSION", "vote", vote("vwap.anchored.participants_in_profit"),
     "LONGS = bullish"),
    ("Round numbers", "MEAN_REVERSION", "vote", vote("indicators.round_numbers.recommendation"), ""),
    ("Exhaustion climax direction", "MEAN_REVERSION", "vote", vote("exhaustion_climax.direction"), ""),
    ("ADR exhausted", "MEAN_REVERSION", "state", category("adr_exhaustion.exhausted"), ""),
    ("ADR % used", "MEAN_REVERSION", "state", bands("adr_exhaustion.pct_of_adr_used", [0.3, 0.6, 0.9, 1.2],
                                                   ["< 30%", "30-60%", "60-90%", "90-120%", ">= 120%"]), ""),
    ("Trade with today's direction", "MEAN_REVERSION", "vote", vote("adr_exhaustion.today_net_direction"), ""),

    # ---------------- VOLUME / ORDER FLOW
    ("Volume", "VOLUME", "vote", vote("indicators.volume.recommendation"), ""),
    ("Volume confirmed", "VOLUME", "state", category("indicators.volume.confirmed"), ""),
    ("Volume ratio", "VOLUME", "state", bands("indicators.volume.ratio", [0.8, 1.2, 1.8, 3],
                                             ["< 0.8", "0.8-1.2", "1.2-1.8", "1.8-3", ">= 3"]), ""),
    ("Volume profile", "VOLUME", "vote", vote("indicators.volume_profile.recommendation"), ""),
    ("Position in value area", "VOLUME", "state",
     bands("component_reads.volume_profile.position_in_value_area", [0, 0.33, 0.66, 1.0001],
           ["below VAL", "lower third", "middle", "upper third", "above VAH"]), ""),
    ("RVAM direction", "VOLUME", "vote", vote("rvam.direction"), ""),
    ("RVAM classification", "VOLUME", "state", category("rvam.classification"), ""),
    ("RVAM confirms trade", "VOLUME", "vote", flag_for("final_verdict.rvam_final_score.aligned"), ""),
    ("Order flow", "VOLUME", "vote", vote("final_verdict.order_flow_final_score.order_flow_recommendation"), ""),
    ("Tick flow (microstructure)", "VOLUME", "vote", microflow, "tick imbalance with/against trade"),
    ("Tick volume imbalance at entry", "VOLUME", "vote", vote("entry_analysis.micro_structure.volume_imbalance_direction"), ""),
    ("Liquidity sweeps bias", "VOLUME", "vote", vote("liquidity_events.bias"), ""),
    ("Order block mitigation", "VOLUME", "state", category("order_flow_forensics.order_block_mitigation.status"), ""),
    ("Family score PARTICIPATION", "VOLUME", "vote", trade_frame("strategy_family_scores.PARTICIPATION"), ""),
    ("Family score ORDER_FLOW", "VOLUME", "vote", trade_frame("strategy_family_scores.ORDER_FLOW"), ""),

    # ---------------- STRUCTURE
    ("Supply / demand", "STRUCTURE", "vote", vote("indicators.supply_demand.recommendation"), ""),
    ("Supply / demand zone grade", "STRUCTURE", "state", category("indicators.supply_demand.zone_grade"), ""),
    ("Support / resistance", "STRUCTURE", "vote", vote("indicators.support_resistance.recommendation"), ""),
    ("Price vs pivot", "STRUCTURE", "vote", vote("indicators.support_resistance.debug.price_vs_pivot"), "above = bullish"),
    ("Fibonacci confluence", "STRUCTURE", "vote", vote("indicators.fib_confluence.recommendation"), ""),
    ("Breakout", "STRUCTURE", "state", category("indicators.breakout.is_breakout"), ""),
    ("Retest confirmation", "STRUCTURE", "state", category("indicators.retest_confirmation.phase"), ""),
    ("Nested zone", "STRUCTURE", "state", category("nested_zone.nested"), ""),

    # ---------------- SMC / ICT
    ("SMC overall", "SMC", "vote", vote("smc.analysis.recommendation", "final_verdict.smc_analysis.recommendation"), ""),
    ("SMC market structure", "SMC", "vote", vote("smc.analysis.market_structure.structure",
                                                "final_verdict.smc_analysis.market_structure.structure"), ""),
    ("SMC last event (BOS/CHoCH)", "SMC", "vote", vote("smc.analysis.market_structure.last_event",
                                                      "final_verdict.smc_analysis.market_structure.last_event"), ""),
    ("SMC liquidity sweep", "SMC", "vote", vote("smc.analysis.liquidity_sweep.type",
                                               "final_verdict.smc_analysis.liquidity_sweep.type"), ""),
    ("SMC premium / discount", "SMC", "vote", vote("smc.analysis.premium_discount.zone",
                                                  "final_verdict.smc_analysis.premium_discount.zone"),
     "DISCOUNT = buy side"),
    ("SMC range position (trade frame)", "SMC", "state",
     bands("smc.analysis.premium_discount.position_pct", [25, 50, 75],
           ["< 25% (cheap for trade)", "25-50%", "50-75%", ">= 75% (expensive for trade)"],
           frame=lambda v, s: v if s > 0 else 100 - v), ""),
    ("SMC order block", "SMC", "vote", order_block, "price inside bullish/bearish OB"),
    ("SMC confluence count", "SMC", "state", category("smc.trade_setup.confluence_count"), "of 6"),
    ("ICT concepts (FVG type)", "SMC", "vote", vote("indicators.ict_concepts.type"), ""),
    ("FVG / IFVG", "SMC", "vote", vote("indicators.fvg_ifvg.recommendation"), ""),
    ("Family score SMC_STRUCTURE", "SMC", "vote", trade_frame("strategy_family_scores.SMC_STRUCTURE"), ""),
    ("Family score FVG", "SMC", "vote", trade_frame("strategy_family_scores.FVG"), ""),

    # ---------------- WAVE / PATTERN
    ("Chart patterns", "WAVE", "vote", vote("final_verdict.pattern_final_score.pattern_recommendation"), ""),
    ("Pattern overall direction", "WAVE", "vote", vote("pattern_analysis.summary.overall_direction"), ""),
    ("Strongest pattern", "WAVE", "state", category("pattern_analysis.summary.strongest_pattern"), ""),
    ("Wave lattice direction", "WAVE", "vote", vote("wave_lattice.lattice_summary.root_direction"), ""),
    ("Wave label (M1)", "WAVE", "state", category("wave_lattice.nodes.M1.current_wave_label"), ""),
    ("Elliott wave", "WAVE", "vote", trade_frame("component_reads.elliott_wave.supports_trade"), ""),
    ("Wave C reversal", "WAVE", "vote", vote("indicators.wave_c.recommendation"), ""),
    ("Wyckoff", "WAVE", "vote", vote("indicators.wyckoff.recommendation"), ""),
    ("Wyckoff phase", "WAVE", "state", category("indicators.wyckoff.phase"), ""),
    ("Candlestick", "WAVE", "vote", vote("indicators.candlestick.recommendation"), ""),
    ("Candle type", "WAVE", "state", category("indicators.candlestick.debug.candle_type"), ""),
    ("Entry confirmation candle", "WAVE", "state", category("entry_analysis.confirmation.type"), ""),
    ("Family score PATTERN", "WAVE", "vote", trade_frame("strategy_family_scores.PATTERN"), ""),

    # ---------------- AI / MACRO
    ("GNN recommendation", "AI_MACRO", "vote", vote("gnn.analysis.recommendation"), ""),
    ("GNN direction", "AI_MACRO", "vote", gnn_direction, "|value| < 0.01 = neutral"),
    ("OHLC+GNN combined", "AI_MACRO", "vote", vote("ohlc_gnn.combined_signal.recommendation"), ""),
    ("DXY confluence", "AI_MACRO", "vote", vote("dxy_confluence.direction"), ""),

    # ---------------- DECISION / ENTRY
    ("Final probability %", "DECISION", "state", bands("final_verdict.probability_percent", [75, 80, 85, 90],
                                                      ["< 75", "75-80", "80-85", "85-90", ">= 90"]), ""),
    ("Bull vs bear case", "DECISION", "vote", case_balance, "own case more confident"),
    ("Conviction passed", "DECISION", "state", category("conviction.passed"), ""),
    ("Coherence", "DECISION", "state", category("coherence.coherent"), ""),
    ("Symbolic gate", "DECISION", "state", category("symbolic_gate.passed"), ""),
    ("Star rating", "DECISION", "state", category("entry_analysis.star_rating"), ""),
    ("Entry quality", "DECISION", "state", category("entry_analysis.entry_quality"), ""),
    ("Entry status", "DECISION", "state", category("entry_analysis.entry_status"), ""),
    ("Discount quality", "DECISION", "state", category("entry_analysis.discount.discount_quality"), ""),
    ("Zone type", "DECISION", "state", category("entry_analysis.discount.zone_type"), ""),
    ("Golden signal count", "DECISION", "state", category("entry_analysis.golden_signals.signal_count"), ""),
    ("Golden: absorption", "DECISION", "state", category("entry_analysis.golden_signals.absorption"), ""),
    ("Golden: volume spike", "DECISION", "state", category("entry_analysis.golden_signals.volume_spike"), ""),
    ("Golden: momentum burst", "DECISION", "state", category("entry_analysis.golden_signals.momentum_burst"), ""),
    ("H1 alignment", "DECISION", "state", category("entry_analysis.h1_alignment.aligned"), ""),
    ("Timing confidence", "DECISION", "state", bands("entry_analysis.timing_confidence", [70, 80, 90],
                                                    ["< 70", "70-80", "80-90", ">= 90"]), ""),
    ("Stop distance (pips)", "DECISION", "state", bands("entry_details.stop_loss_pips", [1.5, 3, 6, 12],
                                                       ["< 1.5", "1.5-3", "3-6", "6-12", ">= 12"]), ""),
    ("Planned R:R", "DECISION", "state", bands("entry_details.risk_reward_detail.ratio", [2, 4, 6, 8],
                                              ["< 2", "2-4", "4-6", "6-8", ">= 8"]), ""),

    # ---------------- REGIME
    ("Volatility level", "REGIME", "state", category("volatility_protection.volatility_level"), ""),
    ("Trading regime", "REGIME", "state", category("volatility_protection.trading_regime.state"), ""),
    ("Regime 3D", "REGIME", "state", category("decision_snapshot.regime_3d.combined_label", 40), ""),
    ("Trend strength (regime)", "REGIME", "state", category("decision_snapshot.regime_3d.trend_strength"), ""),
    ("ATR (pips)", "REGIME", "state", bands("volatility_protection.atr_pips", [1, 2, 4, 8],
                                           ["< 1", "1-2", "2-4", "4-8", ">= 8"]), ""),
    ("Spread (pips)", "REGIME", "state", bands("global_anticheat.spread_pips", [0.3, 0.6, 1.0, 2.0],
                                              ["< 0.3", "0.3-0.6", "0.6-1", "1-2", ">= 2"]), ""),
    ("Session (UTC)", "REGIME", "state", lambda a, s: None, "filled from the trade time"),

    # ---------------- STRATEGY GROUPS (decision engine)
    ("Group: Trend following", "STRATEGY_GROUPS", "vote", group_vote("TREND"), "group score > 50 = with the trade"),
    ("Group: Momentum", "STRATEGY_GROUPS", "vote", group_vote("MOMENTUM"), ""),
    ("Group: Mean reversion", "STRATEGY_GROUPS", "vote", group_vote("MEAN_REVERSION"), ""),
    ("Group: Structure", "STRATEGY_GROUPS", "vote", group_vote("STRUCTURE"), ""),
    ("Group: Smart money / ICT", "STRATEGY_GROUPS", "vote", group_vote("SMC"), ""),
    ("Group: Volume and order flow", "STRATEGY_GROUPS", "vote", group_vote("ORDER_FLOW"), ""),
    ("Group: Waves, patterns, candles", "STRATEGY_GROUPS", "vote", group_vote("WAVE"), ""),
    ("Group: GNN and cross-asset", "STRATEGY_GROUPS", "vote", group_vote("CROSS_ASSET"), ""),
    ("Winning group", "STRATEGY_GROUPS", "state", group_state("winner"), "the highest-scoring group"),
    ("Most opposed group", "STRATEGY_GROUPS", "state", group_state("most_opposed"), ""),
    ("Group probability (final)", "STRATEGY_GROUPS", "state",
     group_state("final_probability", [50, 65, 75, 85], ["< 50", "50-65", "65-75 (below floor)", "75-85", ">= 85"]),
     "entry floor 75"),
    ("Opposition penalty", "STRATEGY_GROUPS", "state",
     group_state("opposition", [1, 15, 30], ["none", "< 15", "15-30", ">= 30"]), ""),
    ("Trading cost penalty", "STRATEGY_GROUPS", "state", group_cost, "break-even shift from spread + commission"),
    ("Other side scores higher", "STRATEGY_GROUPS", "vote", group_other_side, "OPPOSED = groups prefer the other side"),
]


# ============================================================
# EVALUATION
# ============================================================

def _stats(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    info = te.summarise(rows)
    return {k: info.get(k) for k in ("n", "wins", "win_rate", "win_rate_ci95", "expectancy_r",
                                     "expectancy_net_r", "net_usd", "profit_factor", "small_sample")}


def score_component(rows, labels, permutations, seed) -> Dict[str, Any]:
    groups: Dict[str, List] = defaultdict(list)
    for row, label in zip(rows, labels):
        if label is not None:
            groups[str(label)].append(row)
    covered = sum(len(v) for v in groups.values())
    states = []
    for label, members in groups.items():
        s = _stats(members)
        s["state"] = label
        # SELLs did far better than BUYs over this sample, so a state that is
        # mostly one direction can look predictive by restating the direction.
        s["sell_share"] = round(sum(1 for m in members if m["direction"] == "SELL") / len(members), 2)
        states.append(s)
    order = {"ALIGNED": 0, "NEUTRAL": 1, "OPPOSED": 2}
    states.sort(key=lambda s: (order.get(s["state"], 3), -s["n"]))
    result = {"coverage": covered, "states": states}

    by = {s["state"]: s for s in states}
    al, op = by.get("ALIGNED"), by.get("OPPOSED")
    if al and op:
        result["edge_r"] = round(al["expectancy_r"] - op["expectancy_r"], 3)
        result["edge_win_rate"] = round(al["win_rate"] - op["win_rate"], 1)
        result["edge_small_sample"] = min(al["n"], op["n"]) < te.MIN_BUCKET

    kept = [(str(l), r["r"]) for r, l in zip(rows, labels) if l is not None]
    if len(groups) >= 2 and kept:
        test = te.permutation_best_bucket([k[0] for k in kept], [k[1] for k in kept],
                                          permutations, seed)
        if test:
            result.update(test)
    return result


def evaluate(trades=None, *, permutations: int = 2000, seed: int = te.DEFAULT_SEED) -> Dict[str, Any]:
    if trades is None:
        from ai.trade_repository import load_trades
        trades = load_trades()
    trades = list(trades)
    rows, excluded = te.build_rows(trades)

    # build_rows drops the analysis; re-attach it by trade id.
    from ai import trade_repository as repo
    analyses = {}
    for t in trades:
        if isinstance(t, Mapping):
            tt = repo.canonicalise(t) if "m1_analysis_raw" in (t.get("analysis_at_open") or {}) else t
            analyses[tt.get("trade_id")] = tt.get("analysis_at_open") or {}

    report: Dict[str, Any] = {"component": "component_scorecard", "version": SCORECARD_VERSION,
                              "scored": len(rows), "excluded": excluded,
                              "permutations": permutations, "overall": _stats(rows)}
    components: List[Dict[str, Any]] = []
    votes_by_row: List[Dict[str, List[str]]] = [defaultdict(list) for _ in rows]

    for name, cat, kind, reader, description in CATALOGUE:
        if name == "Session (UTC)":
            labels = [te._session(r["opened_at"]) for r in rows]
        else:
            labels = []
            for i, row in enumerate(rows):
                try:
                    label = reader(analyses.get(row["trade_id"]) or {}, row["sign"])
                except Exception:
                    label = None
                labels.append(label)
                if kind == "vote" and label in ("ALIGNED", "OPPOSED", "NEUTRAL"):
                    votes_by_row[i][cat].append(label)
        result = score_component(rows, labels, permutations, seed)
        result.update(name=name, category=cat, kind=kind, description=description)
        if result["coverage"] == 0:
            result["dead"] = "field absent on every trade"
        elif len(result["states"]) == 1:
            result["dead"] = f"always {result['states'][0]['state']}"
        components.append(result)

    # ---- category agreement: (aligned - opposed) / voting members, per trade
    categories = []
    for cat, title in CATEGORIES:
        members = [c for c in components if c["category"] == cat]
        vote_members = [c for c in members if c["kind"] == "vote"]
        labels = []
        for i in range(len(rows)):
            vs = votes_by_row[i].get(cat, [])
            if not vs:
                labels.append(None)
                continue
            net = (vs.count("ALIGNED") - vs.count("OPPOSED")) / len(vs)
            labels.append("AGREES (net > +0.2)" if net > 0.2 else
                          "DISAGREES (net < -0.2)" if net < -0.2 else "MIXED")
        agreement = score_component(rows, labels, permutations, seed) if vote_members else None
        categories.append({"category": cat, "title": title, "members": len(members),
                           "voting_members": len(vote_members), "agreement": agreement})

    # ---- total confluence across every directional component
    totals = []
    for i in range(len(rows)):
        all_votes = [v for vs in votes_by_row[i].values() for v in vs]
        if not all_votes:
            totals.append(None)
            continue
        share = (all_votes.count("ALIGNED") - all_votes.count("OPPOSED")) / len(all_votes)
        totals.append(share)
    present = sorted(t for t in totals if t is not None)
    if present:
        lo, hi = present[len(present) // 3], present[2 * len(present) // 3]
        conf_labels = [None if t is None else
                       (f"LOW net agreement <= {lo:+.2f}" if t <= lo else
                        f"HIGH net agreement > {hi:+.2f}" if t > hi else "MID") for t in totals]
        report["total_confluence"] = score_component(rows, conf_labels, permutations, seed)

    tested = [c for c in components if c.get("p") is not None] + \
             [c["agreement"] for c in categories if c["agreement"] and c["agreement"].get("p") is not None]
    if report.get("total_confluence", {}).get("p") is not None:
        tested.append(report["total_confluence"])
    te.benjamini_hochberg(tested)
    report["tests_in_family"] = len(tested)
    report["components"] = components
    report["categories"] = categories
    return report


def get_status() -> Dict[str, Any]:
    return {"component": "component_scorecard", "version": SCORECARD_VERSION,
            "components_catalogued": len(CATALOGUE)}


def self_check(trades=None) -> Dict[str, Any]:
    """ok=None without trades; False when nothing scores; True when votes reconcile."""
    report: Dict[str, Any] = {"component": "component_scorecard", "ok": None, "checks": {}}
    if not trades:
        report["reason"] = "no trades supplied"
        return report
    try:
        rows, _ = te.build_rows(trades)
        if not rows:
            report["ok"] = False
            report["reason"] = "no scorable trades"
            return report
        checks = {
            "buy_vote_aligned_for_buy": vote_state(market_direction("STRONG_BUY"), 1) == "ALIGNED",
            "sell_vote_opposed_for_buy": vote_state(market_direction("IMMEDIATE_SELL"), 1) == "OPPOSED",
            "neutral_is_neutral": vote_state(market_direction("NEUTRAL"), -1) == "NEUTRAL",
            "absent_is_absent": market_direction(None) is None,
        }
        report["checks"] = checks
        report["ok"] = all(checks.values())
        return report
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        return report


if __name__ == "__main__":
    import json
    import os
    import sys
    import logging

    logging.disable(logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = evaluate()
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "component_scorecard.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, default=str)
    print(f"saved {path}")

    if "--html" in sys.argv:
        # The interactive page: every component's states with win-rate CI bars.
        template = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates",
                                "component_scorecard.html")
        with open(template, encoding="utf-8") as handle:
            page = handle.read()
        data = json.dumps(result, separators=(",", ":"), default=str).replace("</", "<" + chr(92) + "/")
        html_path = os.path.join(folder, "component_scorecard.html")
        with open(html_path, "w", encoding="utf-8") as handle:
            handle.write(page.replace("__DATA__", data))
        print(f"saved {html_path}")
