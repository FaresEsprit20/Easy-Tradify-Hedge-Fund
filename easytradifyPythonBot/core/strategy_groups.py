# ============================================================
# STRATEGY GROUPS -- each strategy scored alone, the best one decides
# ============================================================
# FILE: core/strategy_groups.py
#
# The analysis used to fold every component into one additive probability
# chain. This groups the components by the STRATEGY they belong to --
# trend following, momentum, mean reversion, structure, smart money,
# waves/patterns, order flow, cross-asset -- scores each group on its own,
# and takes the HIGHEST group score as the trade's probability.
#
#   group score = 50 + 45 x net agreement of the group's members with the
#                 traded side, weighted by each member's own confidence
#                 (all members agree at full confidence -> 95; all oppose
#                 -> 5; silent or split -> 50)
#   final       = highest group score
#                 - OPPOSITION: how far the most-opposed group sits below 50
#                 + context adjustments (ADR exhaustion, climax exhaustion,
#                   gap/slippage) that belong to no strategy
#
# WHY THE OPPOSITION TERM (added 2026-09-15). A group's SELL score is 100
# minus its BUY score, so "the other side's best group" is exactly "this
# side's most-opposed group". With the max alone, a bar where trend says BUY
# at 95 and mean reversion says SELL at 95 read 95% certain in BOTH
# directions -- 42 of 105 stored bars had both sides >= 75. On those trades:
#
#   max alone                 AUC 0.479 (halves 0.356 / 0.580) -- worse than chance
#   max - opposition          AUC 0.557 (halves 0.477 / 0.630); no bar is >= 75
#                             on both sides; final >= 50 right 63% vs < 50 right 31%
#
# The best group still decides; a contested bar just no longer reads certain.
#
# A group needs MIN_GROUP_MEMBERS members with a reading to be scored, so
# one lone component cannot claim a whole strategy.
#
# MEASURED BEFORE BUILDING (2026-09-15, 105 stored entries, 5-ATR barrier):
# "highest group decides" called the market right 53% (halves 49% / 58%)
# against 59% for the previous engine; the groups alone ranged from 48%
# (mean reversion) to 64% (cross-asset, 66 calls). Built as specified by
# the user regardless; every group's score is published on every analysis
# so the rule can be re-measured on live trades.
#
# The readers take the stored analysis-payload shape, so the SAME code
# scores a live analysis and a stored trade.
# ============================================================

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

STRATEGY_GROUPS_VERSION = "1.5"
MIN_GROUP_MEMBERS = 2
SCORE_SPAN = 45.0          # 50 +/- 45 keeps group scores inside the 5..95 clamp
# OPPOSITION: 0 as of 2026-09-16. Two reasons, one measured and one by design.
#
# MEASURED. On 61,950 decisions scored against tick-accurate outcomes, cross-
# group agreement is inversely related to success, monotonically:
#
#   groups agreeing   1      2      3      4      5      6
#   right            42.7%  41.3%  41.5%  41.4%  40.4%  37.7%
#   net R           -0.130 -0.195 -0.195 -0.201 -0.221 -0.278
#
# The opposition term amplified exactly the wrong end. When every group agrees
# there is nothing below 50, so opposition is 0 and the published probability
# is the winner's full score -- maximum confidence on the bars that measure
# WORST (-0.278R, 37.7% right, holdout 35.5%). When groups disagree the term
# subtracts points from bars that measure best. It was fitted on 105 stored
# trades and inverted on 61,950.
#
# BY DESIGN. The user's rule is that a score belongs to ONE group. With this at
# 0, final_probability is the winning group's own score plus the non-strategy
# context adjustments, and no other group's number touches it.
#
# Deliberately NOT done: inverting the term to reward disagreement. The 1-group
# and 6-group cells hold 510 and 469 samples, and fitting a rule to the two
# thinnest cells in the table is how this project produced four false edges
# already. Cross-group agreement is published as `groups_agreeing` so it can be
# measured on live trades instead of guessed at.
OPPOSITION_WEIGHT = 0.0
MIN_MEMBER_WEIGHT = 0.3    # a silent or low-confidence member still dilutes the group

# Groups measured to carry no directional information. They are still scored
# and published -- the readings stay visible, and a future measurement can
# revive them -- but they neither win the auction nor supply the opposition
# term, so they cannot move the probability.
#
# STRUCTURE (3/3 level-based members) and SMC (4/6) rest on the same primitive:
# where price sits relative to a zone. Measured 2026-09-16 on true bid/ask
# ticks and confirmed against two independent published studies:
#
#   zone first touch      42-46% at 1R, gross -0.10 to -0.15R, 11,736 trades
#   why it fails          86% of LOSERS saw price react first (median MFE
#                         +0.35R). The levels are real; the reaction is
#                         symmetric noise with no follow-through.
#   quality markers       change whether price REACTS (12.0% vs 15.7% no
#                         reaction) but not whether it CONTINUES
#   451 attribute cells   best z +0.73 (p 0.47); the cells that do clear FDR
#                         are significantly NEGATIVE, holdout gross -0.12/-0.19
#   published             StatOasis 648 backtests: order blocks t +1.22, FVG
#                         t -0.08, 0 of 648 beat buy-and-hold, "survivors: none"
#   HTF sweeps            3,579 events, mid price, zero cost: max |z| 1.36 of
#                         18 cells, control in the same range
#
# A group at the base rate is not neutral in this design: it wins auctions with
# noise, and as `most_opposed` it subtracts real points from a good group's
# score. Silencing beats down-weighting -- there is no weight at which noise
# helps.
#
# EMPTY SINCE 2026-09-17 (operator decision: each strategy group trades its own
# setup when it wins -- core/strategy_setups.py). Excluding these two was right
# only if the groups that DO compete measured better, and they do not: on the
# history replay of the live engine (17 markets, 107,622 decisions, true bid/ask,
# stop 1x ATR(M15), 1R) the later-half win rate of every group's decisions sits
# at the same base rate -- TREND 41.6%, MOMENTUM 41.6%, CROSS_ASSET 41.4%, WAVE
# 42.6%, ORDER_FLOW 40.5% -- the 42-46% the zone study found for STRUCTURE/SMC.
# A gate blocks only when it is shown to help (reports/entry_rules/). The
# mechanism stays: name a group here to silence it again.
#
# CROSS_ASSET since 2026-09-17 (operator decision): its readings are the GNN's
# alone, and they are advisory. It is still scored and published -- on the
# 10-market replay it was the deciding group on 8,965 of 52,031 decisions -- but
# it neither wins the auction nor supplies the opposition term, so no trade is
# taken on it.
#
# MOMENTUM since 2026-09-17 (operator decision, and the measurement agrees):
# every one of its members is wrapped in _trend_confirmed(), so it can only vote
# with the trend cascade -- it is the trend group counted twice. On the replay
# (63,325 decisions, 10 FX markets, each group's own plan) they are the same
# number: TREND 29.4% of decisions would win at -0.785R, MOMENTUM 29.0% at
# -0.803R. It is kept as a STRENGTH reading instead: its score rides on every
# decision (entry_analysis.rules.momentum, final_verdict.strategy.momentum) so
# "is this move strong" can be measured inside each category.
MEASURED_EMPTY_GROUPS: tuple = ("CROSS_ASSET", "MOMENTUM")

GROUP_TITLES = {
    "TREND": "Trend following",
    "MOMENTUM": "Momentum",
    "MEAN_REVERSION": "Mean reversion",
    "STRUCTURE": "Structure (zones, S/R, fibs)",
    "SMC": "Smart money / ICT",
    "ORDER_FLOW": "Volume and order flow",
    "WAVE": "Waves, patterns and candles",
    "CROSS_ASSET": "GNN and cross-asset",
}


# ============================================================
# READING HELPERS
# ============================================================

def _get(payload: Mapping[str, Any], path: str) -> Any:
    """Read a dotted path, in the grouped payload or the legacy flat one.

    Readings moved under analysis.<GROUP>.data.<key> on 2026-09-15
    (core/analysis_groups.py); member paths are written the legacy way and
    resolved here, so one map -- not thirty member definitions -- knows where
    a reading lives."""
    from core.analysis_groups import resolve

    for candidate in (path, resolve(path)):
        node: Any = payload
        for part in candidate.split("."):
            if not isinstance(node, Mapping) or part not in node:
                node = None
                break
            node = node[part]
        if node is not None:
            return node
    return None


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def market_direction(value: Any) -> Optional[int]:
    """+1 bullish, -1 bearish, 0 no direction, None when absent."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if not math.isfinite(value) else (value > 0) - (value < 0)
    text = str(value).strip().upper()
    # Liquidity vocabulary names the side whose stops were taken, not the
    # direction: a BUY_SIDE sweep (stops above highs run) is bearish, a
    # SELL_SIDE sweep bullish. Parsed literally, "BUY_SIDE_SWEEP" and
    # "STOP_HUNT_BUY_SIDE_TRAP" read BUY while the same event's
    # implied_direction read SELL.
    text = text.replace("BUY_SIDE", "BEARISH_LIQUIDITY").replace("SELL_SIDE", "BULLISH_LIQUIDITY")
    if not text or text in ("NONE", "NULL", "N/A", "UNKNOWN") or text.startswith("EXCLUDED"):
        return None
    bull = any(k in text for k in ("BUY", "BULL", "LONG", "DEMAND", "DISCOUNT")) or text in ("UP", "ABOVE")
    bear = any(k in text for k in ("SELL", "BEAR", "SHORT", "SUPPLY", "PREMIUM")) or text in ("DOWN", "BELOW")
    if bull and not bear:
        return 1
    if bear and not bull:
        return -1
    return 0


def _confidence(payload, path, default=1.0) -> float:
    value = _num(_get(payload, path))
    if value is None:
        return default
    return max(0.0, min(1.0, value / 100.0 if value > 1.0 else value))


def _direction_member(direction_path: str, confidence_path: Optional[str] = None):
    def read(payload):
        d = market_direction(_get(payload, direction_path))
        if d is None:
            return None
        return d, (_confidence(payload, confidence_path) if confidence_path else 1.0)
    return read


def _macd_momentum(payload):
    """MACD by momentum: the histogram sign encoded in calculate_macd's signal string."""
    signal = str(_get(payload, "indicators.macd.signal") or "").upper()
    hist = {"BULLISH": 1, "NEUTRAL_BEARISH": 1, "BEARISH": -1, "NEUTRAL_BULLISH": -1, "NEUTRAL": 0}.get(signal)
    if hist is None:
        return None
    return hist, _confidence(payload, "indicators.macd.confidence")


def _cascade(payload):
    d = market_direction(_get(payload, "trend_cascade.direction"))
    if d is None or _get(payload, "trend_cascade.available") is False:
        return None
    score = _num(_get(payload, "trend_cascade.score"))
    return d, (abs(score) if score is not None else 1.0)


def _price_vs_ema200(payload):
    side = _get(payload, "trend_confirmation.m1_price_vs_ema200")
    if side not in ("above", "below"):
        return None
    return (1 if side == "above" else -1), 0.5


def _vwap_side(payload):
    above = _get(payload, "vwap.above_vwap")
    if not isinstance(above, bool):
        return None
    return (1 if above else -1), 0.5


def _elliott_wave(payload):
    """Highest-confidence actionable Elliott wave (core/component_reads.elliott_read).

    Live analyses carry the waves themselves; stored trades carry the read
    that was computed from them at the time.
    """
    from core.component_reads import elliott_read

    waves = _get(payload, "pattern_analysis.elliott_waves") or _get(payload, "elliott_waves")
    if waves:
        read = elliott_read(payload, "BUY")
        direction, confidence = read.get("market_direction"), read.get("confidence")
    else:
        direction = _get(payload, "component_reads.elliott_wave.market_direction")
        confidence = _get(payload, "component_reads.elliott_wave.confidence")
    d = _num(direction)
    if d is None:
        return None
    c = _num(confidence)
    return (d > 0) - (d < 0), (max(0.0, min(1.0, c if c <= 1 else c / 100)) if c is not None else 1.0)


def _gnn_direction(payload):
    value = _num(_get(payload, "gnn.analysis.gnn_direction"))
    if value is None:
        return None
    return (0 if abs(value) < 0.01 else (1 if value > 0 else -1)), 1.0


# ============================================================
# MEMBER REPAIRS (2026-09-15)
# ============================================================
# Measured on 3,528 analysis snapshots (111 entries + every in-trade point),
# each trade weighted equally, direction = which 5-ATR barrier price hit
# first. Several members of the weak groups were reversal or zone calls that
# M1 price kept running through. Each repair below was one of a fixed set of
# variants (as-is / inverted / sweep-, momentum- or cascade-confirmed /
# ranging- or trending-only), and is kept only where it held in BOTH
# chronological halves. Accuracy before -> after, half 1 / half 2:
#
#   support / resistance   47 / 63  -> trend-confirmed 66 / 72
#   SMC market structure   48 / 56  -> trend-confirmed 67 / 66
#   Fibonacci confluence   52 / 42  -> trend-confirmed 71 / 57
#   supply / demand        58 / 34  -> trend-confirmed 73 / 53
#   RSI                    49 / 38  -> trend-confirmed 68 / 52
#   stochastic             56 / 39  -> trend-confirmed 61 / 54
#   Bollinger bands        29 / 36  -> read as continuation 71 / 64
#   GNN direction          61 / 55  -> ranging regimes only 72 / 66
#   premium / discount     49 / 31  -> read as continuation 51 / 69 (weakest)
#   trend indicator (M1)   48 / 61  -> trend-confirmed 63 / 65
#   price vs EMA200        46 / 61  -> trend-confirmed 57 / 69
#   chart patterns         56 / 53  -> trend-confirmed 70 / 67
#   wave lattice           55 / 57  -> trend-confirmed 71 / 71
#   candlestick            55 / 52  -> trend-confirmed 75 / 62
#   Wyckoff                42 / 63  -> trend-confirmed 64 / 56
#   Elliott wave (NEW)     58 / 57  -> trend-confirmed 79 / 89  (was in no group)
#   MACD momentum          54 / 52  -> trend-confirmed 70 / 66
#   TTM squeeze momentum   51 / 58  -> trend-confirmed 69 / 68
#   RVAM direction         54 / 53  -> trend-confirmed 71 / 63
#   VWAP side              45 / 54  -> trend-confirmed 58 / 61
#   stochastic cross (NEW) 52 / 50  -> trend-confirmed 77 / 66
#   liquidity sweeps bias  54 / 66  -> trend-confirmed 71 / 76
#   volume                 43 / 63  -> trend-confirmed 49 / 85  (unstable; better in both halves)
#   volume profile         54 / 27  -> trend-confirmed 77 / 46  (unstable; better in both halves)
#   SMC overall            54 / 63  -> trend-confirmed 73 / 80
#   SMC liquidity sweep    48 / 65  -> trend-confirmed 69 / 86
#   ICT FVG type           55 / 51  -> trend-confirmed 71 / 64  (agreed with 97 of 98 trades as-is:
#                                      the opposite case is a pre-flight veto, so it only inflated SMC,
#                                      which then won the max on 37 stored trades at -0.83R)
#   FVG / IFVG             54 / 58  -> trend-confirmed 72 / 69
#   order flow             39 / 47  -> trend-confirmed 53 / 59  (measured on data from before the
#                                      2026-09-15 exhausted-zone fix -- re-measure live)
#
# Consequence, stated plainly: nearly every group now votes only in the trend
# cascade's direction, so the engine is trend-following with each strategy
# family acting as a confirmation. That is what the measurements support.
#
# Kept as-is: trend cascade (67 / 62, it IS the confirmation), H1 trend (66 /
# 51, no variant better in both halves).
#
# "Trend-confirmed": the reading counts only when the M5-H4 trend cascade
# points the same way -- a zone or an oversold reading is traded in the
# direction of the higher timeframe, never against it. Outside that the
# member is silent (not a vote either way).

def _trend_confirmed(reader: Callable) -> Callable:
    def read(payload):
        reading = reader(payload)
        cascade = _cascade(payload)
        if reading is None or cascade is None or reading[0] == 0 or reading[0] != cascade[0]:
            return None
        return reading
    return read


def _as_continuation(reader: Callable) -> Callable:
    def read(payload):
        reading = reader(payload)
        return None if reading is None else (-reading[0], reading[1])
    return read


# Whether the mean-reversion group may actually fade.
#
# 2026-09-16: this is now ON, because the gate changed. The members no longer
# depend on hand-picked stretch/stall thresholds that nothing validated; they
# depend on core/ou_mean_reversion.py, which fits the process and refuses
# unless the forward PRICE slope clears t=3 on non-overlapping windows, the
# half-life is holdable, price rather than the baseline does the reverting, and
# the expected gain beats the round trip. That is a pre-registered statistical
# bar rather than a guess, so a signal that passes it has earned the trade.
#
# It currently fires on nothing: all 15 symbols measure a forward beta near
# 0.06 against the 0.50 OU theory implies, and none reaches t=3 (XAUUSD is
# significant with the WRONG sign, -4.90 -- gold extends, it does not revert).
# Silence here is the component working, not the component missing.
#
# The old note below is kept because it is why the switch exists at all.
#
# The group's structural defect is fixed below -- it is no longer a
# trend-follower wearing a reversion label, and self_check() proves it votes
# counter-trend on a stalled stretch. What is NOT fixed is that fading has no
# measured support. On 54,284 trades of true bid/ask ticks
# (ai/participation_ticks.py) every fade cell is negative and FOLLOW beats FADE
# in almost all of them:
#
#     REVERSION_READY  fade  net -0.098R to -0.238R   follow better in 3 of 4
#     MOMENTUM_RUNNING fade  net -0.161R to -0.242R   follow better in 3 of 4
#
# Four years of M15 bars said the opposite, with a clean monotone ladder. That
# was an artifact: bid-only bars dip and recover on every spread flicker, so a
# fade always looks like it worked -- a 0.14R gross bias, about three times
# MODEL_OPTIMISM_R, and directional towards reversion specifically.
#
# So this stays False until a fade configuration measures positive ON TICKS.
# It is not a runtime veto -- no condition is being checked against a live bar
# and no trade is blocked by it. It is one switch recording that a strategy has
# no evidence behind it yet. Flip it the moment there is some.
REVERSION_FADES_ENABLED = True


def _loud_smc(direction: str) -> Dict[str, Any]:
    """A bar where every SMC reading shouts `direction` at full confidence."""
    d = direction.upper()
    return {"smc": {"analysis": {"recommendation": d,
                                 "market_structure": {"structure": d},
                                 "premium_discount": {"zone": "PREMIUM" if d == "BUY" else "DISCOUNT"}}},
            "indicators": {"ict_concepts": {"type": "BULLISH" if d == "BUY" else "BEARISH"},
                           "fvg_ifvg": {"recommendation": d, "confidence": 100}},
            "trend_cascade": {"available": True, "direction": "BULLISH" if d == "BUY" else "BEARISH",
                              "score": 1.0}}


def _smc_can_win() -> bool:
    """SMC competes in the auction: a bar where only SMC speaks makes it the winner."""
    r = score_groups(_loud_smc("BUY"), "BUY")
    return r["winner"] == "SMC" and r["groups"]["SMC"].get("counts_in_decision", True) is not False


def _silenced_group_cannot_win() -> bool:
    """The silencing mechanism still works when a group is named in
    MEASURED_EMPTY_GROUPS: scored and published, never the winner."""
    global MEASURED_EMPTY_GROUPS
    saved = MEASURED_EMPTY_GROUPS
    MEASURED_EMPTY_GROUPS = tuple(set(saved) | {"SMC"})
    try:
        r = score_groups(_loud_smc("BUY"), "BUY")
        return (r["groups"]["SMC"]["scored"] is True and r["winner"] != "SMC"
                and r["groups"]["SMC"].get("counts_in_decision") is False)
    finally:
        MEASURED_EMPTY_GROUPS = saved


def _ou_payload(tradeable: bool) -> Dict[str, Any]:
    """A payload whose OU reading says a counter-trend fade is (or is not) earned."""
    return {"trend_cascade": {"available": True, "direction": "BULLISH", "score": 1.0},
            "ou_reversion": {"available": True, "tradeable": tradeable, "side": -1,
                             "size_multiple": 1.8, "z": -1.8, "half_life_bars": 90.0,
                             "forward_beta": 0.42, "forward_t": 4.1, "price_share": 0.71},
            "indicators": {"rsi": {"recommendation": "SELL", "confidence": 100},
                           "stochastic": {"recommendation": "SELL", "confidence": 100}}}


def _ou_side(payload):
    """The fade the fitted OU process implies, sized by the dislocation.

    Not an indicator's opinion of a stretch -- the process itself: half-life
    estimated from the data, the dislocation quoted in equilibrium sigma, and
    strength from `size_multiple` (proportional to z, capped at 3), which is
    how a reversion book actually sizes.
    """
    if not REVERSION_FADES_ENABLED:
        return None
    ou = _get(payload, "ou_reversion")
    if not isinstance(ou, Mapping) or not ou.get("tradeable"):
        return None
    side = _num(ou.get("side"))
    if not side:
        return None
    strength = _num(ou.get("size_multiple")) or 1.0
    return int(side), max(0.0, min(1.0, strength / 3.0))


def _ou_gated(reader: Callable) -> Callable:
    """An indicator reading, admitted only where the process says a fade pays.

    The gate is core/ou_mean_reversion.py, which refuses unless the fitted
    half-life is tradeable, the forward PRICE slope clears t=3 on
    non-overlapping windows, most of the reversion is price rather than the
    baseline moving, and the expected gain beats the round trip. That last
    clause is what the old implementation never had: it entered without ever
    asking whether the journey paid for itself.
    """
    def read(payload):
        if not REVERSION_FADES_ENABLED:
            return None
        ou = _get(payload, "ou_reversion")
        if not isinstance(ou, Mapping) or not ou.get("tradeable"):
            return None
        return reader(payload)
    return read


def _in_regime(reader: Callable, prefix: str) -> Callable:
    def read(payload):
        state = str(_get(payload, "volatility_protection.trading_regime.state") or "")
        return reader(payload) if state.startswith(prefix) else None
    return read


# (group, member name, reader)
#
# Removed 2026-09-15 as dead -- neutral on all 111 stored trades, so they only
# diluted their groups: VWAP context stance (mean reversion) and DXY
# confluence (disabled; it made cross-asset read a flat 65/35 on every bar).
# Rarely-voting members (Bollinger 9/111, volume 20, GNN recommendation 13)
# stay: when they do vote they carry information.
MEMBERS: List[Tuple[str, str, Callable]] = [
    ("TREND", "trend indicator (trend-confirmed)",
     _trend_confirmed(_direction_member("indicators.trend.recommendation", "indicators.trend.confidence"))),
    ("TREND", "trend cascade M5-H4", _cascade),
    ("TREND", "H1 trend", _direction_member("higher_timeframe.trend")),
    ("TREND", "price vs EMA200 (trend-confirmed)", _trend_confirmed(_price_vs_ema200)),

    ("MOMENTUM", "MACD momentum (trend-confirmed)", _trend_confirmed(_macd_momentum)),
    ("MOMENTUM", "TTM squeeze momentum (trend-confirmed)",
     _trend_confirmed(_direction_member("ttm_squeeze.release_direction"))),
    ("MOMENTUM", "RVAM direction (trend-confirmed)", _trend_confirmed(_direction_member("rvam.signal_direction"))),
    ("MOMENTUM", "VWAP side (trend-confirmed)", _trend_confirmed(_vwap_side)),
    ("MOMENTUM", "stochastic cross (trend-confirmed)", _trend_confirmed(_direction_member("indicators.stochastic.signal"))),
    # A band walk is a continuation thesis, so it belongs with the other
    # continuation readings. Inside MEAN_REVERSION it was inverted against
    # that group's own two members, and with OPPOSITION_WEIGHT at 1.0 the
    # three cancelled toward 50 -- the group argued with itself on every bar.
    ("MOMENTUM", "Bollinger band walk (continuation)",
     _as_continuation(_direction_member("indicators.bollinger_bands.recommendation", "indicators.bollinger_bands.confidence"))),

    ("MEAN_REVERSION", "OU dislocation (fitted half-life)", _ou_side),
    ("MEAN_REVERSION", "RSI extreme (OU-gated)",
     _ou_gated(_direction_member("indicators.rsi.recommendation", "indicators.rsi.confidence"))),
    ("MEAN_REVERSION", "stochastic extreme (OU-gated)",
     _ou_gated(_direction_member("indicators.stochastic.recommendation", "indicators.stochastic.confidence"))),

    ("STRUCTURE", "supply / demand (trend-confirmed)",
     _trend_confirmed(_direction_member("indicators.supply_demand.recommendation", "indicators.supply_demand.confidence"))),
    ("STRUCTURE", "support / resistance (trend-confirmed)",
     _trend_confirmed(_direction_member("indicators.support_resistance.recommendation"))),
    ("STRUCTURE", "Fibonacci confluence (trend-confirmed)",
     _trend_confirmed(_direction_member("indicators.fib_confluence.recommendation", "indicators.fib_confluence.confidence"))),

    ("SMC", "SMC overall (trend-confirmed)", _trend_confirmed(_direction_member("smc.analysis.recommendation"))),
    ("SMC", "SMC market structure (trend-confirmed)",
     _trend_confirmed(_direction_member("smc.analysis.market_structure.structure"))),
    ("SMC", "liquidity sweep (trend-confirmed)", _trend_confirmed(_direction_member("smc.analysis.liquidity_sweep.type"))),
    ("SMC", "premium / discount (continuation)",
     _as_continuation(_direction_member("smc.analysis.premium_discount.zone"))),
    ("SMC", "ICT FVG type (trend-confirmed)", _trend_confirmed(_direction_member("indicators.ict_concepts.type"))),
    ("SMC", "FVG / IFVG (trend-confirmed)",
     _trend_confirmed(_direction_member("indicators.fvg_ifvg.recommendation", "indicators.fvg_ifvg.confidence"))),

    ("ORDER_FLOW", "volume (trend-confirmed)", _trend_confirmed(_direction_member("indicators.volume.recommendation"))),
    ("ORDER_FLOW", "volume profile (trend-confirmed)",
     _trend_confirmed(_direction_member("indicators.volume_profile.recommendation", "indicators.volume_profile.confidence"))),
    ("ORDER_FLOW", "liquidity sweeps bias (trend-confirmed)", _trend_confirmed(_direction_member("liquidity_events.bias"))),
    ("ORDER_FLOW", "order flow (trend-confirmed)",
     _trend_confirmed(_direction_member("final_verdict.order_flow_final_score.order_flow_recommendation"))),

    ("WAVE", "chart patterns (trend-confirmed)",
     _trend_confirmed(_direction_member("final_verdict.pattern_final_score.pattern_recommendation"))),
    ("WAVE", "wave lattice (trend-confirmed)",
     _trend_confirmed(_direction_member("wave_lattice.lattice_summary.root_direction"))),
    ("WAVE", "Elliott wave (trend-confirmed)", _trend_confirmed(_elliott_wave)),
    ("WAVE", "Wyckoff (trend-confirmed)", _trend_confirmed(_direction_member("indicators.wyckoff.recommendation"))),
    ("WAVE", "candlestick (trend-confirmed)",
     _trend_confirmed(_direction_member("indicators.candlestick.recommendation", "indicators.candlestick.confidence"))),

    ("CROSS_ASSET", "GNN direction (ranging regimes)", _in_regime(_gnn_direction, "RANGING")),
    ("CROSS_ASSET", "GNN recommendation", _direction_member("gnn.analysis.recommendation")),
]

# ------------------------------------------------------------
# TRADING COST (2026-09-15)
# ------------------------------------------------------------
# A trade pays spread and commission whatever happens. With cost c and target
# T (both in R), its break-even win probability rises from 1/(1+T) to
# (1+c)/(1+T): it must be right 100*c/(1+T) points more often just to break
# even. That is the penalty -- arithmetic, not a fitted weight.
#
# Commission is IC Markets' measured round trip (from the broker's deals):
# $7.03 per FX lot, $0.04 per share.
#
# Stored entries, floor 75 (current bracket):
#   without cost   h1 n34 right 68% -0.01R   h2 n32 right 69% -0.35R
#   with cost      h1 n26 right 69% +0.01R   h2 n16 right 64% -0.03R
# Median cost 0.67R -> median penalty 10 points (p90 17). About a third fewer
# entries, and the ones removed were the expensive losers.
COMMISSION_PER_LOT_ROUND_TRIP = 7.03
COMMISSION_PER_SHARE_ROUND_TRIP = 0.04


def trading_cost(payload: Mapping[str, Any]) -> Optional[Dict[str, float]]:
    """Cost in R, target in R and the break-even penalty, or None if unknowable.

    Reads `cost` when the live analysis supplies it, otherwise derives it from
    the published entry details (so stored trades score identically).
    """
    supplied = _get(payload, "cost")
    if isinstance(supplied, Mapping) and _num(supplied.get("penalty_points")) is not None:
        return dict(supplied)
    ed = _get(payload, "entry_details") or {}
    spread = _num(_get(payload, "global_anticheat.spread_pips"))
    stop, target = _num(ed.get("stop_loss_pips")), _num(ed.get("take_profit_pips"))
    risk_usd, lots = _num(ed.get("risk_usd")), _num(ed.get("lot_size"))
    if spread is None or not stop or not target or not risk_usd or not lots:
        return None
    symbol = str(_get(payload, "config.symbol") or "").upper()
    per_unit = COMMISSION_PER_SHARE_ROUND_TRIP if symbol.endswith((".NAS", ".NYSE")) else COMMISSION_PER_LOT_ROUND_TRIP
    cost_r = spread / stop + (lots * per_unit) / risk_usd
    target_r = target / stop
    return {"cost_r": round(cost_r, 3), "target_r": round(target_r, 2),
            "penalty_points": round(100.0 * cost_r / (1.0 + target_r), 2)}


def _cost_penalty(payload):
    cost = trading_cost(payload)
    return None if cost is None else -cost["penalty_points"]


# Hours (BROKER clock, UTC+3) where these setups measurably die, and the
# win-rate deficit each carries against the rest of the day. Two independent
# constructs agree on the shape, which is why this is a measurement and not a
# hunch:
#
#   structure_lab zone entries, 11,736 tick trades
#     broker 0 (rollover)  15.3% won, -0.94R   <- spread spikes eating fills
#     broker 19-23 (NY pm) 28-41% won          vs Tokyo 47.7%, London 46.2%
#   the engine's own supply/demand reading, 4,442 tick-labelled calls
#     New York             37.7% right, -0.265R, z -8.46, holdout 36.9%
#
# The penalty is the measured deficit expressed in probability points, not a
# tuned number: the rollover hour runs ~28 points below the day's average and
# the NY afternoon ~10. It is a soft adjustment rather than a block -- the
# trade can still qualify on its own merit, which keeps trading easy.
DEAD_SESSION_PENALTY = {0: 28.0, 19: 8.0, 20: 12.0, 21: 10.0, 22: 13.0, 23: 13.0}

# Context readings that are PUBLISHED but do not move the probability.
#
# "dead session": the operator's rule since 2026-09-17 (strategic_plan_v4.md and
# v5) is no session or news rules -- session, hour and weekday are neither
# features nor filters. This reading is an hour-of-day filter (-8 to -28 points),
# so it is kept in `context` with counts=False, where it stays measurable, and
# left out of context_total. The rollover spread spike it was measured on is
# judged on the spread itself: the high_spread veto and the symbolic gate's
# spread-to-stop check.
RECORDED_ONLY_CONTEXT = frozenset({"dead session"})


def _session_penalty(payload):
    """Points off for the hours that measure catastrophic, or None if unknown."""
    hour = _num(_get(payload, "clock.broker_hour"))
    if hour is None:
        return None
    return -DEAD_SESSION_PENALTY.get(int(hour) % 24, 0.0) or None


# Adjustments that belong to no strategy (they describe the session, the fill
# or the cost, not a direction thesis) and are added after the max.
CONTEXT_ADJUSTMENTS = [
    ("ADR exhaustion", lambda p: _num(_get(p, "final_verdict.adr_exhaustion_final_score.adjustment"))),
    ("exhaustion climax", lambda p: _num(_get(p, "final_verdict.exhaustion_final_score.adjustment"))),
    ("gap / slippage", lambda p: (lambda v: -v if v else None)(_num(_get(p, "final_verdict.gap_slippage_final_score.gap_slippage_penalty")))),
    ("trading cost", _cost_penalty),
    ("dead session", _session_penalty),
]


# ============================================================
# SCORING
# ============================================================

def score_groups(payload: Mapping[str, Any], direction: str, only: Optional[str] = None) -> Dict[str, Any]:
    """Score every strategy group for `direction` and pick the highest.

    only: a group name to make that group the only one that can decide
    (asset_analysis_config.STRATEGY_SELECTION); None or "ALL" lets all compete.
    Every group is still scored and published either way."""
    side = 1 if str(direction).upper() == "BUY" else -1 if str(direction).upper() == "SELL" else 0
    groups: Dict[str, Dict[str, Any]] = {}
    for group in GROUP_TITLES:
        groups[group] = {"title": GROUP_TITLES[group], "members": [], "scored": False}

    for group, name, reader in MEMBERS:
        try:
            reading = reader(payload)
        except Exception:
            reading = None
        if reading is None:
            continue
        d, strength = reading
        groups[group]["members"].append({
            "name": name,
            "vote": ("WITH" if d * side > 0 else "AGAINST" if d * side < 0 else "NEUTRAL"),
            "strength": round(float(strength), 3),
        })

    for group, info in groups.items():
        members = info["members"]
        if side == 0 or len(members) < MIN_GROUP_MEMBERS:
            info["reason"] = (f"only {len(members)} member(s) with a reading" if side
                              else "no traded side")
            continue
        weight_sum = net = 0.0
        for m in members:
            w = max(MIN_MEMBER_WEIGHT, m["strength"])
            sign = {"WITH": 1, "AGAINST": -1, "NEUTRAL": 0}[m["vote"]]
            net += sign * w
            weight_sum += w
        agreement = net / weight_sum if weight_sum else 0.0
        info.update(scored=True, agreement=round(agreement, 3),
                    score=round(50.0 + SCORE_SPAN * agreement, 1),
                    with_count=sum(1 for m in members if m["vote"] == "WITH"),
                    against_count=sum(1 for m in members if m["vote"] == "AGAINST"))

    for group in MEASURED_EMPTY_GROUPS:
        if group in groups:
            groups[group]["counts_in_decision"] = False
            groups[group]["excluded_reason"] = (
                "measured at the 44.6% baseline on tick data -- published, not decided on")
    ranked = sorted((g for g in groups
                     if groups[g]["scored"] and g not in MEASURED_EMPTY_GROUPS),
                    key=lambda g: -groups[g]["score"])
    selected = str(only or "ALL").upper()
    if selected != "ALL":
        ranked = [g for g in ranked if g == selected]
    context = []
    for label, reader in CONTEXT_ADJUSTMENTS:
        try:
            value = reader(payload)
        except Exception:
            value = None
        if value:
            entry = {"name": label, "points": round(value, 2)}
            if label in RECORDED_ONLY_CONTEXT:
                entry["counts"] = False
            context.append(entry)
    context_total = sum(c["points"] for c in context if c.get("counts", True))

    if not ranked and selected != "ALL":
        # the selected strategy has nothing to say for this side: the floor, so
        # the probability rule refuses -- never a fall-back to another strategy
        return {"version": STRATEGY_GROUPS_VERSION, "direction": direction, "groups": groups,
                "ranked": [], "winner": selected if selected in groups else None, "selected": selected,
                "best_score": None, "most_opposed": None, "opposition": None, "context": context,
                "final_probability": 5.0,
                "reason": f"selected strategy {selected} has no reading for {direction}"}
    if not ranked:
        return {"version": STRATEGY_GROUPS_VERSION, "direction": direction, "groups": groups,
                "ranked": [], "winner": None, "best_score": None, "most_opposed": None, "opposition": None, "context": context,
                "final_probability": None, "reason": "no strategy group had enough readings"}

    winner = ranked[0]
    best = groups[winner]["score"]
    most_opposed = ranked[-1]
    opposition = OPPOSITION_WEIGHT * max(0.0, 50.0 - groups[most_opposed]["score"])
    final = max(5.0, min(95.0, best - opposition + context_total))
    return {
        "version": STRATEGY_GROUPS_VERSION,
        "direction": direction,
        "groups": groups,
        "selected": selected,
        "ranked": [{"group": g, "score": groups[g]["score"]} for g in ranked],
        "winner": winner,
        "best_score": best,
        # published, not acted on: cross-group agreement measured INVERSELY
        # related to success (6 groups agreeing -> 37.7% right, -0.278R), so it
        # is recorded for live re-measurement rather than fed back into the score
        "groups_agreeing": sum(1 for g in ranked if groups[g]["score"] > 50.0),
        "groups_scored": len(ranked),
        # A group's SELL score is 100 minus its BUY score, so the other side's
        # best group is exactly this side's most-opposed one. When both sides
        # read high the bar is genuinely ambiguous and the number is not a
        # probability -- that is what the opposition term existed to catch.
        # It is FLAGGED here rather than subtracted, because subtracting it
        # penalised the bars that measure best (1-2 groups agreeing, -0.130R)
        # and flattered the ones that measure worst (6 agreeing, -0.278R).
        "other_side_best": round(100.0 - min(groups[g]["score"] for g in ranked), 1),
        "contested": bool(min(groups[g]["score"] for g in ranked) < 50.0 < best),
        "most_opposed": most_opposed,
        "opposition": round(opposition, 1),
        "context": context,
        "context_total": round(context_total, 2),
        "cost": trading_cost(payload),
        "final_probability": round(final, 1),
        "reason": (f"{GROUP_TITLES[winner]} scored highest ({best:.1f}: "
                   f"{groups[winner]['with_count']} with / {groups[winner]['against_count']} against)"
                   + (f", opposed by {GROUP_TITLES[most_opposed]} (-{opposition:.1f})" if opposition else "")
                   + (f", context {context_total:+.1f}" if context_total else "")),
    }


def get_status() -> Dict[str, Any]:
    return {"component": "strategy_groups", "version": STRATEGY_GROUPS_VERSION,
            "groups": list(GROUP_TITLES), "members": len(MEMBERS)}


def self_check() -> Dict[str, Any]:
    # Trend says BUY (cascade + H1); cross-asset says SELL (GNN in a ranging market).
    payload = {"trend_cascade": {"available": True, "direction": "BULLISH", "score": 1.0},
               "higher_timeframe": {"trend": "BULLISH"},
               "volatility_protection": {"trading_regime": {"state": "RANGING_CALM"}},
               "gnn": {"analysis": {"gnn_direction": -0.2, "recommendation": "SELL"}}}
    buy = score_groups(payload, "BUY")
    sell = score_groups(payload, "SELL")
    # a genuinely two-sided bar: the trend group reads BUY, the fitted reversion
    # process says the fade is earned and reads SELL
    _contested = {**_ou_payload(True), "higher_timeframe": {"trend": "BULLISH"},
                  "trend_confirmation": {"m1_price_vs_ema200": "above"},
                  "indicators": {**_ou_payload(True)["indicators"],
                                 "trend": {"recommendation": "BUY", "confidence": 100}}}
    contested_buy = score_groups(_contested, "BUY")
    contested_sell = score_groups(_contested, "SELL")
    against_trend = dict(payload, indicators={"rsi": {"recommendation": "SELL", "confidence": 100},
                                               "stochastic": {"recommendation": "SELL", "confidence": 100}})
    counter_smc = dict(payload, indicators={"ict_concepts": {"type": "BEARISH"}},
                       smc={"analysis": {"recommendation": "BEARISH"}})
    checks = {
        "trend_group_wins_for_buy": buy["winner"] == "TREND" and buy["best_score"] == 95.0,
        # the counter-trend side is mean reversion with an earned OU fade: the
        # cross-asset group is advisory since 2026-09-17 and wins nothing
        "earned_fade_wins_the_other_side": contested_sell["winner"] == "MEAN_REVERSION",
        "single_member_group_not_scored": buy["groups"]["MOMENTUM"]["scored"] is False,
        # trend 95 BUY vs cross-asset 95 SELL. The opposition term used to drag
        # both sides to 50; it is gone because it penalised the bars that
        # measure BEST. The ambiguity is now flagged instead of priced in, and
        # both flags must fire -- a silent contested bar would be the old defect
        # back with no warning.
        "contested_bar_is_flagged_both_ways": contested_buy["contested"] and contested_sell["contested"],
        "contested_bar_publishes_the_other_side":
            contested_buy["other_side_best"] >= 50.0 and contested_sell["other_side_best"] >= 50.0,
        # Without an OU reading nothing knows whether a fade is earned, so the
        # group is silent -- it no longer votes on an indicator's opinion alone.
        "reversion_without_an_ou_fit_is_silent":
            score_groups(against_trend, "SELL")["groups"]["MEAN_REVERSION"]["scored"] is False,
        # The process says the fade is earned: the group votes AGAINST a bullish
        # cascade, which the old _trend_confirmed wrapper made impossible. This
        # is the defect that kept mean reversion off every auction.
        "earned_fade_votes_counter_trend":
            score_groups(_ou_payload(True), "SELL")["groups"]["MEAN_REVERSION"]["scored"] is True,
        # ...and when the fit does not clear its statistical bar, silent again,
        # which is the state all 15 symbols are actually in.
        "unearned_fade_is_refused":
            score_groups(_ou_payload(False), "SELL")["groups"]["MEAN_REVERSION"]["scored"] is False,
        # SMC and STRUCTURE compete (2026-09-17); a group named in
        # MEASURED_EMPTY_GROUPS is still published and cannot win.
        "smc_can_win": _smc_can_win(),
        "silenced_group_cannot_win": _silenced_group_cannot_win(),
        "counter_trend_smc_is_silent": score_groups(counter_smc, "SELL")["groups"]["SMC"]["scored"] is False,
    }
    return {"component": "strategy_groups", "ok": all(checks.values()), "checks": checks}
