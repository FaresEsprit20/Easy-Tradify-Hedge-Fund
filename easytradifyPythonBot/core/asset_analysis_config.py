from typing import Dict

# ============================================================
# UNIFIED ASSET ANALYSIS CONFIGURATION - V6 (COMPLETE FIX)
# ============================================================
# SOURCE OF TRUTH: All constants defined ONCE
# NO DUPLICATES: Removed conflicting definitions
# CONSISTENT: All scores and thresholds match
#
# ✅ FIXES APPLIED IN V6:
# 1. REMOVED ALL DUPLICATES (ZONE_GRADE_SCORES_HELPERS, etc.)
# 2. MACD: FAST (5,13,6) for M1 scalping - less lag
# 3. MACD THRESHOLDS: ADJUSTED for fast MACD values (0.0005)
# 4. BOLLINGER BANDS M1: 50 period, 2.5 std dev
# 5. ZONE SCORES: SINGLE definition (E = 35, not 0)
# 6. ZONE MULTIPLIERS: SINGLE definition
# 7. ZONE THRESHOLDS: SINGLE definition
# 8. Volume confirmation: 0.3 (volume is BONUS)
# ============================================================


# ============================================================
# SECTION 1: THRESHOLDS
# ============================================================

# ============================================================
# MINIMUM STOP DISTANCE  (spread-aware)
# ============================================================
# calculate_lot_proper() sizes the position from MARGIN capacity first
# and then derives the stop as `target_risk / pip_value`, so the stop
# distance is a function of leverage and account size with no input
# from the market. Its own docstring states the intent plainly: "the
# tighter the SL, the larger the lot."
#
# On a real XAGUSD replay that produced a stop of ~33 pips against a
# 20-pip spread on every single decision -- 1856 of 1856 -- because
# $200 of margin at 200:1 carries ~0.12 lots of silver and $20 of risk
# on 0.12 lots is ~33 pips, whatever price is doing. Measured result:
#
#   spread/stop 0.50-0.60   585 decisions   35.2% win   -0.228R
#   spread/stop 0.60-0.80   517 decisions   31.1% win   -0.267R
#   spread/stop 0.80+       754 decisions   18.6% win   -0.426R
#
# and 423 decisions (22.8%) had a spread LARGER than the whole stop --
# stopped out at entry as a matter of arithmetic, before price moved.
# The median trade began 70% of the way to its own stop. That single
# fact explains the -0.319R expectancy far better than any indicator.
#
# So the stop gets a floor expressed in spreads. A trade must be able
# to survive its own cost of entry: at a multiple of 3.0 the spread is
# a third of the risk, which is still expensive but no longer decides
# the outcome by itself.
#
# This does NOT loosen risk. The dollar risk budget is unchanged --
# the position is scaled DOWN to pay for the wider stop. Fewer units,
# same money at risk, a stop that reflects the market instead of the
# leverage.
SL_MIN_SPREAD_MULTIPLE = 3.0

# How far the position may be trimmed below the size the $200 margin
# target implies, when the stop is already pinned on its spread floor and
# risk is STILL over budget.
#
# Sizing is margin-first: the lot comes from the margin target and risk is
# steered with the stop, which is free to move. Trimming the lot is the
# last resort, for the case where the stop cannot go any tighter without
# landing inside the spread. Bounding it matters -- calculate_lot() used
# to walk the lot down by 100 * volume_step unconditionally (a flat -10.00
# lots on the .NYSE/.NAS stocks), returning MCD at 3.00 lots / $38 margin
# against a $200 target. A floor of 0.70 keeps a trimmed position
# recognisably the size that was intended; if risk is still over target at
# that floor the sizer says so in `warnings` instead of shrinking silently.
MAX_LOT_TRIM_FRACTION = 0.70

# The spread floor above is necessary but not sufficient: it says the stop
# must clear the COST of trading, and says nothing about the NOISE. On a
# zero-spread instrument it collapses to the 1-pip absolute minimum, which
# on EURUSD is a stop that ordinary tick noise removes before the setup
# has a chance to be right or wrong.
#
# So the stop must also clear the instrument's own recent volatility. At
# 1.0 the stop sits one full ATR away -- a move of ordinary size does not
# reach it, and only a move larger than the market has recently been
# making does. Both floors apply; whichever is wider wins.
SL_MIN_ATR_MULTIPLE = 1.0

# Buffer PAST a zone level when the stop is derived from it, as a
# multiple of ATR. A stop sitting exactly on the zone is removed by the
# same wick that tests it, which converts a correct read of structure
# into a loss.
SL_ZONE_BUFFER_ATR = 0.5

# Ceiling on a structural stop, as a multiple of ATR. A zone far from
# price would otherwise produce a stop whose 2R target needs a move the
# instrument does not make -- a trade that cannot win rather than one
# that is unlikely to.
SL_MAX_ATR_MULTIPLE = 8.0

# ============================================================
# CONFIRMATION QUALITY  (entry_engine.check_discount_confirmation)
# ============================================================
# The confirmation ladder scores four tiers 95/85/80/60. The bottom one
# was `close > open and body > 0` for a BUY -- the candle closed green,
# by any margin at all. On M1 that is close to a coin flip, and it was
# not a rare fallback: on a 4240-decision EURUSD replay it produced 49
# of 52 confirmations, the three structural tiers firing 3 times
# between them.
#
# So "CONFIRMED_DISCOUNT" almost always meant "this candle happened to
# close in our direction". The consequence is measurable: setups the
# engine confirmed went on to win 23.1%, while setups it REJECTED for
# lacking confirmation won 35.3%. The step meant to select good entries
# was selecting on noise.
#
# Deleting the tier is not the answer -- it would cut entries from 38 to
# 3 in a month, and the structural tiers fire too rarely to trade on.
# The fix is to make the tier mean what it claims: a close is evidence
# about who won the bar only if the bar ACTUALLY closed near the
# favourable extreme, on a body big enough to not be a doji.
#
# CLOSE_LOCATION: where in the bar's own range the close sat, as the
# standard [-1,+1] close-location value. +0.30 means the close was in
# the upper 65% of the range for a BUY -- buyers held the level into
# the close rather than merely finishing a tick above the open.
#
# MIN_BODY_FRACTION: the body as a share of the range, which rejects
# the doji case where a "green" close is one tick and both wicks are
# enormous. Those bars are indecision, not confirmation.
#
# Both are deliberately mild. This is meant to remove bars that carry
# no information, not to hunt for a threshold that flatters a backtest.
CONFIRMATION_MIN_CLOSE_LOCATION = 0.30
CONFIRMATION_MIN_BODY_FRACTION = 0.25

# Entry thresholds
# DATA-COLLECTION MODE (2026-09-10): 75 -> 65 at Fares's request.
# At 75 the monitor produced 2492 NO_POTENTIAL rejections and 1 trade in
# an hour; the bottleneck for the edge research is trade COUNT, not signal
# purity. Raise it back before drawing conclusions about the tight rules --
# data gathered at 65 measures the 65 rule, not the 75 one.
MIN_ENTRY_CONFIDENCE = 65   # a TIMING confidence, not a probability -- not re-centred

# ------------------------------------------------------------
# PROBABILITY RE-CENTRING (2026-09-15)
# ------------------------------------------------------------
# The zone (+15/+20 by grade at a zone) and ICT (+10) contributions in
# calculate_real_probability were removed (PROB_SCALE_ZONE / PROB_SCALE_ICT).
# On the 111 stored trades they added points to 103 and 96 trades
# respectively -- a mean of 20.3 -- without separating winners from losers
# (zone grade did not rank outcomes). Their only real effect was to lift
# every setup ~20 points, pinning many at the 95 clamp where later penalties
# (liquidity, ADR, order flow) were absorbed instead of applied.
#
# Every threshold on the probability scale moves down by the same amount, so
# a setup keeps its place relative to the bars; only the absorbed penalties
# now land. Set PROBABILITY_RECENTER_POINTS = 0 together with the two scales
# above = 1.0 to restore the old scale exactly.
PROBABILITY_RECENTER_POINTS = 20

# ------------------------------------------------------------
# STRATEGY GROUPS DECIDE THE PROBABILITY (2026-09-15, user's rule)
# ------------------------------------------------------------
# True: the components are grouped by strategy (trend, momentum, mean
# reversion, structure, SMC, order flow, waves, cross-asset), each group is
# scored alone, and the trade's probability is the HIGHEST group score plus
# context adjustments. See core/strategy_groups.py. The additive chain still
# runs and is recorded, but no longer sets the probability.
#
# The plain max put the median probability at 86.8, every setup above the 55
# floor, and scored BOTH sides >= 75 on 42 of 105 bars (AUC 0.479). The best
# group minus the most-opposed group's shortfall (core/strategy_groups.py,
# OPPOSITION_WEIGHT) gives median 64.9, no bar certain both ways, AUC 0.557;
# final >= 50 was right 63% vs 31% below. False restores the additive chain.
USE_STRATEGY_GROUP_PROBABILITY = True

# Entry floor on the strategy-group scale. The re-centred 55 above was set for
# the additive chain; group scores sit higher (median ~82 after the member
# repairs). Chosen on the first half of the stored entries and confirmed on the
# second (current trade direction, current bracket):
#     floor 50  h1 64% right -0.30R (n42)   h2 62% right -0.53R (n44)
#     floor 70  h1 68% right -0.13R (n37)   h2 62% right -0.47R (n36)
#     floor 75  h1 68% right -0.01R (n34)   h2 69% right -0.35R (n32)   <- better than 70 in both halves
#     floor 80  h1 67% right -0.14R (n33)   h2 74% right -0.49R (n26)
# Used only while USE_STRATEGY_GROUP_PROBABILITY is on and the groups produced a
# probability; otherwise TRADE_PROBABILITY_MINIMUM applies.
STRATEGY_GROUP_MIN_PROBABILITY = 75.0

# Calibrated strategy-group probability (2026-09-15). The hand-built group
# score above was measured on the price-history study (every 15 minutes, 17
# symbols, real engine): final probability AUC 0.50, not monotone -- a 40 won
# as often as a 90. core/calibrated_model.py evaluates weights fitted on the
# study and validated out of sample (ai/component_calibration.py). When the
# model file core/calibrated_model.json is installed it sets the probability
# and its own entry floor (the file's "entry_floor", chosen on net R after
# cost); without the file nothing changes.
USE_CALIBRATED_PROBABILITY = True

# Market stop (core/market_stop.py): stop = 1.5 x H1 ATR, target = 1R, lot
# sized so the loss at the stop is the dollar risk. Replaces the account stop
# (~1 M1 ATR, commission 0.4-0.7R) in the analysis AND in execute_trade, which
# then keeps the caller's stop and sizes the lot instead of pulling the stop
# back to the margin-first distance. Chosen on tick-accurate brackets.
#
# OFF since 2026-09-17, operator decision: lot size and risk revert to the
# original margin-first sizing (calculate_lot_proper). Measured live that day:
# the market stop sent $2.09-$3.17 of the $4 budget on EURUSD/GBPJPY/US500 (lots
# round down to the broker step) and $47.04 on XAUUSD, where even the minimum
# lot is 11x over budget; the original sends $3.64-$3.90 on all four. Its
# stops are tight (EURUSD 1.0 pip, GBPJPY 2.4 pips on that bar) and the larger
# lots pay more commission. The module is kept: set True to restore.
USE_MARKET_STOP = False

# The most a single trade may risk, as a fraction of the trade-size budget.
# 0.02 x $200 = $4, which is what the operator trades. Callers supply
# risk_per_trade themselves (api/execution_controller.py passes the request
# body straight through), and a live snapshot on 2026-09-16 showed a $20 stop
# from a caller asking for 10%. The analysis and the executor clamp to this,
# so the budget cannot be raised by whoever happens to call.
MAX_RISK_PER_TRADE = 0.02

MIN_PROBABILITY_FOR_ENTRY = 75 - PROBABILITY_RECENTER_POINTS

# The probability CEILING. Entry needs a band, not just a floor, because the
# system's confidence is inverted at the top -- measured on 61,950 decisions
# against tick-accurate outcomes, holdout accuracy climbs through the deciles
# (35.1 -> 48.6%) and then the top decile falls back to 42.9%. Trading the
# D6-D9 band instead of everything returns -0.099R against -0.192R on holdout,
# and -0.166R against -0.193R on train: better on both halves independently.
#
# 83.0 is the measured D9/D10 boundary on the training period. Raise it to 100
# to restore "a floor only" behaviour.
MAX_PROBABILITY_FOR_ENTRY = 83.0
TRADE_PROBABILITY_MINIMUM = 75 - PROBABILITY_RECENTER_POINTS

# ------------------------------------------------------------
# ENTRY RULE TABLE (2026-09-17, entry foundation v2)
# ------------------------------------------------------------
# core/entry_engine.py evaluates EVERY entry rule on EVERY decision and
# publishes the whole table in entry_analysis.rules (passed, mode, value,
# threshold, why) with the failing blockers in entry_analysis.blocked_by.
# Until now the engine returned at the first rule that failed, so a decision
# stopped at WAITING_DISCOUNT never said whether its confirmation or timing
# would have held, and no rule could be measured on the decisions another rule
# had already stopped.
#
# "block": a failed rule stops the entry. "observe": the rule is evaluated and
# recorded but never blocks. A rule changes mode on measured results
# (strategic_plan_v5_live_data.md: one result per decision, later data than it
# was chosen on, same pass line), not by hand. A missing or unknown mode blocks.
#
# Each rule is checked in ONE place. Before this the probability was checked
# four times with four different bars (tier table 45, engine band 25-83, the
# post-chain floor 75, the monitor 65), the spread five times and the candle's
# age four times.
#
# Modes set 2026-09-17 by the pre-registered verdict (ai/entry_rule_evidence.py)
# on the history replay of this engine: 17 markets, 107,622 decisions every 15
# minutes, June 12 - September 15, results on true bid/ask M1 bars with
# commission, primary geometry stop 1x ATR(M15) / target 1R, earlier vs later
# half (reports/entry_rules/ENTRY_RULES_HISTORY.md). A rule blocks only when its
# passed decisions beat its failed ones in BOTH halves (lift in R):
#   probability       +0.110 / +0.078   block
#   discount_quality  +0.050 / +0.049   block
#   discount          -0.104 / -0.147   observe (hurt in both halves)
#   signals           -0.011 / -0.024   observe
#   confirmation      +0.013 / -0.031   observe
#   zone              4 and 7 failures in 107,622 decisions: unproven -> observe
#   timing            needs live ticks, not measurable on bars -> observe
# With every rule blocking, the table let through 2 of 45,474 winning decisions;
# with these modes 1,691. The strategy setups add a rule of their own ("setup").
ENTRY_RULE_MODES = {
    "zone": "observe",            # a supply/demand zone with a tradable grade   -> INVALID_ZONE
    "signals": "observe",         # golden signals >= ENTRY_MIN_SIGNALS          -> NO_POTENTIAL
    "probability": "block",       # floor <= probability <= MAX_PROBABILITY_FOR_ENTRY -> INSUFFICIENT_PROBABILITY
    "setup": "block",             # the winning group's own trade setup is valid -> NO_STRATEGY_SETUP
    "discount": "observe",        # measured inconclusive once geometry is controlled
    "discount_quality": "block",  # zone on the trade's side, quality and score  -> POOR_DISCOUNT
    "confirmation": "block",      # INVERTED (see ENTRY_RULE_POLARITY)           -> ALREADY_CONFIRMED
    "timing": "observe",          # tick micro-structure timing confidence       -> POOR_TIMING
    "momentum": "observe",        # the momentum group's strength for this side  -> WEAK_MOMENTUM
}

# ---------------------------------------------------------------------------
# Rule polarity -- two rules are backwards, measured (2026-09-17)
# ---------------------------------------------------------------------------
# On the 60,853-decision replay of the final engine, orientation chosen on the
# EARLIER half and confirmed on the LATER half
# (tradify_study/entry_edges_v1/invert_entry.py):
#
#   confirmation  the bar confirmed the side -> 28.0% won, -0.272R gross
#                 the bar did NOT confirm    -> 30.3% won, -0.220R gross
#                 backwards in EVERY category and BOTH halves (10/10).
#                 Mechanism: waiting for a confirmation candle means entering
#                 after the move has already happened.
#
#   discount      REJECTED. On raw win rate it looked identical to confirmation
#                 (26.4% at the zone vs 29.3% away). Once each band is judged
#                 against its OWN free barrier rate the pattern falls apart: it
#                 holds only in aggregate (1.5 points, and the "at a discount"
#                 group is 3% of decisions), FLIPS in SMC (early best True,
#                 later best False) and is FLAT in TREND. It is not inverted and
#                 it does not block. Raw win rate moves when the target moves;
#                 that is what made it look real.
#
# polarity -1 => the rule passes when its condition is FALSE. The condition is
# still measured and recorded exactly as before; only what counts as passing is
# flipped. Worth about +0.05R gross. Gates only block where they are measured to
# help -- that standard is what found these, and it is what they now satisfy.
ENTRY_RULE_POLARITY = {"confirmation": -1}

# ---------------------------------------------------------------------------
# Direction inversion -- the engine's chosen side loses to its own opposite
# ---------------------------------------------------------------------------
# Every decision scored BOTH ways on the same bars, same entry, same stop and
# target distances (60,853 decisions, 15 FX markets):
#
#                       won %   free %   edge    gross R   net R
#   engine's side       29.2%   38.1%    -8.8    -0.237    -0.798
#   OPPOSITE side       32.0%   38.1%    -6.1    -0.168    -0.729
#
# +2.4 points in the earlier half, +2.7 in the later, positive in both live
# categories. The tick tape says the same from a different angle: fading the
# signed flow is right ~54% of the time. The engine is trend-following at a
# scale where price reverts.
#
# HONEST LIMIT: this reduces the loss, it does not create a profit. BOTH sides
# lose -- the opposite side is still -0.168R gross and -0.729R net, because a
# ~6-point deficit is present on both and is structural (enter at the ask, exit
# at the bid, and a bar touching both levels counts as the stop). Demo only.
INVERT_ENTRY_DIRECTION = True

# ---------------------------------------------------------------------------
# M1 ONLY (operator rule, 2026-09-18: "timeframe only M1")
# ---------------------------------------------------------------------------
# Every signal, filter and trend reading is computed on M1 bars. A spy on one
# live analysis (EURUSD) found 18 M1 bar requests and 38 on other timeframes,
# from seven consumers -- all of them switched off here:
#
#   M5/M15/H1/H4  trend cascade      gated 25 members (_trend_confirmed), was a
#                                    TREND member, and could flip the direction
#   H1            "H1 trend"         TREND member, H1 alignment in probability
#   D1            ADR exhaustion     probability adjustment
#   H1            OU mean reversion  the mean-reversion gate
#   M15           RSI divergence     probability input
#   M15           stochastic div.    -> now read on M1 (the function takes a timeframe)
#   H1 (x29)      GNN                cross-asset, advisory
#   and the M5/H1 re-analyses the monitor ran when a trade closed.
#
# A switched-off reading reports itself as not read ("M1_ONLY") -- it is never
# replaced with a guess. The trend confirmation that 25 members depend on now
# uses the M1 trend (price vs EMA200 on M1) instead of the M5-H4 cascade.
M1_ONLY = True

# ---------------------------------------------------------------------------
# What places live (demo) orders -- operator decision, 2026-09-18
# ---------------------------------------------------------------------------
# The generic engine's entries are OFF: no edge was found in them, and the
# replay of the live M1-only engine measured about -0.6R per trade. The demo bot
# trades ONLY the frozen RSI-extreme divergence setup
# (engine_v2/run/shadow_rsi_div_m1.py + rsi_div_live.py), which refuses to send
# anything on a non-demo account. The monitor keeps analysing and recording.
GENERIC_ENTRIES_ENABLED = False
RSI_DIV_M1_LIVE = True
# Operator priority, 2026-09-18: "the most important is to win money, I want to
# stop losing." So the setup is ARMED but places no order until its own
# pre-registered shadow verdict reads CONFIRMED (>= 300 resolved trades, net R
# per trade > 0, and beating the same levels on the opposite side). Checked on
# every setup: if later evidence pulls the verdict below CONFIRMED, trading stops
# again by itself. Until then the bot does not trade, so it does not lose.
RSI_DIV_M1_REQUIRE_CONFIRMED = True

# RSI divergence on H4, DEMO orders (engine_v2/run/rsi_div_h4.py). Operator,
# 2026-09-18: the one H1/H4 cell that passed development halves AND the
# untouched holdout (+0.17R holdout, +0.21R on real bid/ask); traded on demo
# now. The runner stops new orders itself on its pre-registered STOP verdict
# (40 trades) or at -10R cumulative. False = no order is ever sent.
RSI_DIV_H4_LIVE = True

# Golden signals an entry needs (momentum burst, absorption, volume spike, at a
# point of interest, volume imbalance). Entries with none were right 17% of the
# time on the stored trades (core/entry_engine.ALLOW_UNCONFIRMED_ENTRIES).
ENTRY_MIN_SIGNALS = 1

# Momentum as a strength reading, not a strategy (operator, 2026-09-17). The
# MOMENTUM group score (0-100 for the traded side) rides on every decision as
# the "momentum" rule. It is recorded, never blocking, until the evidence says
# strong-momentum decisions beat weak ones inside a category
# (ai/entry_rule_evidence.py). MOMENTUM_STRENGTH_MIN is the line the recorded
# verdict uses.
MOMENTUM_STRENGTH_MIN = 60.0

# Vetoes that still run and record their verdict but no longer block
# (core/veto_engine.py, disabled_vetos).
#
# candle_too_young: since 2026-09-15 every reading comes from CLOSED bars
# (core/closed_bars.py). How far the forming minute has run changes no reading
# the decision is made from; only the live quote moves. The candle-age checks
# (this veto, the tier table's 20-40% progress, the x0.7 timing penalty below
# 75% and the safety check at 75%) therefore judged nothing but the clock. The
# monitor analyses early in the minute (median 8% into the bar at NO_POTENTIAL)
# and those checks refused its setups on timing alone, pushing any entry away
# from the close of the bar that confirmed it. Candle progress is still
# recorded in the veto ledger.
#
# news_veto: the operator's rule (strategic_plan_v4.md / v5) is no session or
# news rules -- news is neither a feature nor a filter. The check still runs and
# records what it would have done (vetos.checks.news_veto), and a recorded-only
# news veto no longer starts the 60-second veto cooldown. The session veto is
# not a session rule in that sense (market closed / not a trading day / close
# imminent) and stays active.
DISABLED_VETOS = ("candle_too_young", "news_veto")
STRONG_ENTRY_THRESHOLD = 85 - PROBABILITY_RECENTER_POINTS
DECISION_WAIT_THRESHOLD = 65 - PROBABILITY_RECENTER_POINTS
DECISION_MONITOR_THRESHOLD = 50 - PROBABILITY_RECENTER_POINTS

# Decision thresholds
DECISION_STRONG_ENTRY = 85.0 - PROBABILITY_RECENTER_POINTS
DECISION_ENTRY_WITH_ZONE = 75.0 - PROBABILITY_RECENTER_POINTS

# Star rating thresholds
STAR_5_THRESHOLD = 85.0 - PROBABILITY_RECENTER_POINTS
STAR_4_THRESHOLD = 75.0 - PROBABILITY_RECENTER_POINTS
STAR_3_THRESHOLD = 65.0 - PROBABILITY_RECENTER_POINTS
STAR_2_THRESHOLD = 50.0 - PROBABILITY_RECENTER_POINTS

# Probability minimum
MINIMUM_PROBABILITY_FOR_TRADE = 75.0 - PROBABILITY_RECENTER_POINTS


# ============================================================
# SECTION 2: TAKE PROFIT
# ============================================================

FIBONACCI_TP1 = 0.618
FIBONACCI_TP1_MIN_PIPS = 8
FIBONACCI_TP1_MAX_PIPS = 15

# TP1 FOLLOWS THE R:R FLOOR (operator, 2026-09-17). True: TP1 is the minimum
# risk:reward NET of spread -- MINIMUM_RISK_REWARD x stop + spread -- and no
# longer the Fibonacci swing target clamped to 8-15 pips. Against the 1-2 pip
# account stops on FX, the 8-pip minimum put targets at 4-8R (history with those
# levels: 18.6% won, -0.52R per trade). Targets now sit at about 1.2R net, so more
# trades reach them and each win pays 1.2R; commission (~0.6R at a 1-pip stop) is
# unchanged. A strategy setup keeps its own structural target. False restores the
# Fibonacci target.
TP1_FOLLOWS_RR_FLOOR = True

# WHICH STRATEGY DECIDES (operator, 2026-09-17). "ALL": every strategy group
# competes and the highest-scoring one decides and trades its own setup
# (core/strategy_groups.py, core/strategy_setups.py). A group name -- "TREND",
# "MOMENTUM", "MEAN_REVERSION", "STRUCTURE", "SMC", "ORDER_FLOW", "WAVE" or
# "CROSS_ASSET" -- makes that strategy the only one: its own score is the
# probability and its own setup is the trade, whether or not it would have won
# the auction; when it has no reading the probability is the 5.0 floor and
# nothing enters. analyze_institutional_signal(strategy=...) overrides this per
# call (the /trade/analyse API accepts "strategy" in the body).
STRATEGY_SELECTION = "ALL"
TP2_MIN_PIPS = 10
TP2_MAX_PIPS = 25
TP2_ATR_MULTIPLIER = 1.2


# ============================================================
# SECTION 3: RISK REWARD
# ============================================================

# 1:1.2 since 2026-09-17, operator decision (was 1:2 by an earlier directive).
# The 1:2 floor never rejected a trade: calculate_hybrid_take_profit() raises TP1
# to `min_rr x stop + spread`, so it only pushed every target out to at least 2R
# net. On FX the 8-pip TP1 minimum (FIBONACCI_TP1_MIN_PIPS) against stops of 1-3
# pips still sets most targets. The strategy setups use their own 1:1.2 minimums
# (BB_MEAN_REVERSION_MIN_RR, RSI_REVERSAL_MIN_RR, ...), so all three stages agree.
MINIMUM_RISK_REWARD = 1.2
# ✅ FIXED: was 1.5 (M1 got a looser minimum than every other
# timeframe) -- explicit directive is a 1:2 minimum with no timeframe
# exceptions. This also resolves a real contradiction: this value feeds
# calculate_atr_based_tp() (calculations.py) when TP levels are first
# set, while a SEPARATE post-hoc floor gate in asset_analysis.py
# (MIN_ABSOLUTE_RISK_REWARD, below) checks the REALIZED R:R afterward --
# the two were previously set to different numbers (1.5 vs 1.2) for the
# same concept at different pipeline stages. Both are now equal (1.2 since
# 2026-09-17, see MINIMUM_RISK_REWARD).
MINIMUM_RISK_REWARD_M1 = 1.2


# ============================================================
# SECTION 4: CANDLESTICK SCORING
# ============================================================

CANDLE_SCORE_SHOOTING_STAR = -20
CANDLE_SCORE_HAMMER = 20
CANDLE_SCORE_MARUBOZU_BULLISH = 25
CANDLE_SCORE_MARUBOZU_BEARISH = -25
CANDLE_SCORE_PIN_BAR_BULLISH = 20
CANDLE_SCORE_PIN_BAR_BEARISH = -20
CANDLE_SCORE_NORMAL_BULLISH = 10
CANDLE_SCORE_NORMAL_BEARISH = -10
CANDLE_SCORE_SPINNING_TOP = 0
CANDLE_SCORE_DOJI = 0


# ============================================================
# SECTION 5: INDICATOR SCORING
# ============================================================

# RSI thresholds
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
RSI_EXTREME_OVERBOUGHT = 80
RSI_EXTREME_OVERSOLD = 20

# M1 RSI thresholds
RSI_OVERBOUGHT_M1 = 80.0
RSI_OVERSOLD_M1 = 20.0
RSI_DIVERGENCE_VETO_THRESHOLD_M1 = 60.0
RSI_DIVERGENCE_VETO_THRESHOLD = 65.0

# RSI score values
RSI_SCORE_EXTREME = -20.0
RSI_SCORE_STRONG = -8.0
RSI_SCORE_WARNING = -3.0
RSI_SCORE_BULLISH = 5.0
RSI_SCORE_VERY_BULLISH = 8.0
RSI_SCORE_NEUTRAL = 0.0
RSI_SCORE_BEARISH = -5.0

# Stochastic thresholds
STOCH_OVERBOUGHT = 80
STOCH_OVERSOLD = 20


# ============================================================
# SECTION 6: BOLLINGER BANDS - ✅ FIXED FOR M1
# ============================================================
# M1 needs WIDER bands and LONGER period to filter noise
# ============================================================

# Bollinger Band settings by timeframe
BB_PERIOD = {
    "M1": 50,      # WAS 20 - much wider for M1 to filter noise
    "M5": 20,
    "M15": 20,
    "M30": 20,
    "H1": 20,
    "DEFAULT": 20
}

BB_STD = {
    "M1": 2.5,     # WAS 2.0 - wider bands for M1
    "M5": 2.0,
    "M15": 2.0,
    "M30": 2.0,
    "H1": 2.0,
    "DEFAULT": 2.0
}

# Bollinger Band squeeze threshold
BB_SQUEEZE_THRESHOLD = 0.05
BB_SQUEEZE_THRESHOLD_BASE = 0.005

# Bollinger Band squeeze multipliers (instrument-aware)
_BB_SQUEEZE_MULTIPLIERS = {
    "XAU": 0.5,
    "XAG": 0.7,
    "DEFAULT": 1.0
}

# Bollinger Band scoring
BB_SCORE_BULLISH = 20
BB_SCORE_BEARISH = -20
BB_SCORE_SQUEEZE_BULLISH = 10
BB_SCORE_SQUEEZE_BEARISH = -10
BB_SCORE_SQUEEZE_NEUTRAL = 0


# ============================================================
# SECTION 7: MACD - ✅ FAST FOR M1 SCALPING
# ============================================================
# Fast MACD (5,13,6) reacts faster with less lag
# Thresholds adjusted for fast MACD values
# ============================================================

MACD_FAST = 5      # WAS 12 - more responsive for M1
MACD_SLOW = 13     # WAS 26 - less lag
MACD_SIGNAL = 6    # WAS 9 - faster signal line

# ✅ FIXED: Thresholds for FAST MACD (larger values)
MACD_BULLISH_THRESHOLD = 0.0005   # WAS 0.00001
MACD_BEARISH_THRESHOLD = -0.0005  # WAS -0.00001

# MACD recovery detection threshold
MACD_RECOVERY_THRESHOLD = 0.0001

# MACD weight reduction in strong trends
MACD_WEIGHT_STRONG_TREND = 0.05
MACD_WEIGHT_NORMAL = 0.10


# ============================================================
# SECTION 8: CONFIGURABLE CONSTANTS
# ============================================================

BREAKOUT_PERIOD = 20
BREAKOUT_VOLUME_THRESHOLD = 1.5
DEFAULT_RSI_VALUE = 50.0
FVG_INVALIDATION_MULTIPLIER = 1.5

# Volume thresholds
VOLUME_SPIKE_THRESHOLD_M1 = 1.2
VOLUME_LOW_THRESHOLD_M1 = 0.5

# Candlestick
WICK_REVERSAL_RATIO = 3

# Veto thresholds
EXTREME_VOLATILITY_VETO_THRESHOLD = 70.0
RANGING_MARKET_ADX_THRESHOLD = 25

# Zone execution
# ✅ FIXED: was ["A", "B"] - out of sync with entry_engine.py's actual
# gating logic (EntryEngine.tradable_grades), which has treated A/B/C as
# tradable since an earlier explicit fix there. This constant only feeds
# the informational config.valid_zone_grades display field in
# asset_analysis.py's output - it was never the real gate - but showing
# ["A","B"] here while the real logic (and its own rejection message)
# both said "A, B, and C" made the output actively misleading about its
# own behavior.
VALID_ZONE_GRADES = ["A", "B", "C", "D"]

# Parallel execution settings 
MAX_WORKERS = 4
DEFAULT_DEBUG = False


# ============================================================
# SECTION 9: PATTERN RECOGNITION
# ============================================================

PATTERN_TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1"]

# Moderate tightening (was 0.30 on M1 -- combined with looser scoring,
# that let very weakly-supported patterns through and made low-bar
# patterns like RECTANGLE dominate "strongest_pattern" selection almost
# by default). This is the single source of truth: patterns.py used to
# keep its own shadow copy of this dict with these same tightened
# values, which silently overrode this one and masked the fact that
# this file was still stale. Do not redefine this dict anywhere else.
PATTERN_CONFIDENCE_THRESHOLDS = {
    "M1": 0.40,
    "M5": 0.45,
    "M15": 0.50,
    "M30": 0.55,
    "H1": 0.60
}

PATTERN_TIMEFRAME_WEIGHTS = {
    "M1": 0.08,
    "M5": 0.12,
    "M15": 0.18,
    "M30": 0.25,
    "H1": 0.37
}

PATTERN_WEIGHT = 0.20

# Moderate tightening (was 50 minutes on M1 -- too long for an M1
# pattern to still count as "fresh"). Single source of truth -- see
# note on PATTERN_CONFIDENCE_THRESHOLDS above.
PATTERN_MAX_AGE_BARS = {
    "M1": 25,
    "M5": 15,
    "M15": 12,
    "M30": 10,
    "H1": 8,
}

# Moderate tightening (was 80 pips on M1 -- let current price be
# almost anywhere and still count as "near" a pattern's key level,
# which defeats the point of proximity filtering). Single source of
# truth -- see note on PATTERN_CONFIDENCE_THRESHOLDS above.
PATTERN_PROXIMITY_PIPS = {
    "M1": 0.0040,
    "M5": 0.0040,
    "M15": 0.0060,
    "M30": 0.0080,
    "H1": 0.0120,
}

# Moderate tightening (was 0.5 pips -- noise-floor tiny on virtually
# any instrument, not distinguishable from tick jitter). Single source
# of truth -- see note on PATTERN_CONFIDENCE_THRESHOLDS above.
PATTERN_MIN_SIZE_PIPS = {
    "HEAD_SHOULDERS": 0.0003,
    "INVERSE_HEAD_SHOULDERS": 0.0003,
    "DOUBLE_BOTTOM": 0.0003,
    "DOUBLE_TOP": 0.0003,
    "RECTANGLE": 0.0003,
    "RECTANGLE_M1": 0.0003,
    "TRIANGLE": 0.0003,
    "WEDGE": 0.0003,
    "FLAG": 0.0003,
    "PENNANT": 0.0003,
}

PATTERN_MIN_BARS_M1 = {
    "RECTANGLE": 8,
    "TRIANGLE_ASCENDING": 8,
    "TRIANGLE_DESCENDING": 8,
    "TRIANGLE_SYMMETRICAL": 8,
    "FLAG_BULLISH": 6,
    "FLAG_BEARISH": 6,
    "PENNANT_BULLISH": 8,
    "PENNANT_BEARISH": 8,
    "WEDGE_RISING": 8,
    "WEDGE_FALLING": 8,
    "DOUBLE_BOTTOM": 8,
    "DOUBLE_TOP": 8,
    "HEAD_SHOULDERS": 10,
    "INVERSE_HEAD_SHOULDERS": 10,
    "ABC_CORRECTION": 6,
    "MEAN_REVERSION": 4,
}

PATTERN_VOLUME_CONFIRMATION_THRESHOLD = 0.3
# Moderate tightening (was 8 -- itself raised from an original 5).
# Single source of truth -- see note on PATTERN_CONFIDENCE_THRESHOLDS
# above.
MAX_PATTERNS_PER_TIMEFRAME = 6


# ============================================================
# SECTION 10: GNN WEIGHTING
# ============================================================

GNN_WEIGHT = 0.15
GNN_CONFIDENCE_THRESHOLD = 40


# ============================================================
# SECTION 11: REGIME PROBABILITY CORRECTION
# ============================================================
# The per-indicator weight table, its regime tilts and the indicator
# families lived here. They fed only family voting, removed on
# 2026-09-15; indicator influence is set in calculate_real_probability
# (see MEASURED INDICATOR CONTRIBUTIONS).

# ✅ ADDED: direct probability correction applied by the new regime
# classifier, on top of (not instead of) the existing HIGH_VOLATILITY
# multiplier in apply_probability_multipliers_pair() and the ATR-band
# confidence_penalty in check_volatility_protection() -- both of those
# stay wired to the OLD 3-state detect_market_regime() output, exactly
# as before. This is an additional, separate correction from the newer
# 5-state read, applied right alongside the existing confidence_penalty
# step so it reaches best_probability (and therefore the actual entry
# decision) rather than being a display-only side value.
REGIME_PROBABILITY_ADJUSTMENTS = {
    "TRENDING_CALM": 0.0,
    "TRENDING_VOLATILE": -8.0,
    "RANGING_CALM": 0.0,
    "CHOPPY": -15.0,
    "SQUEEZE": -5.0,   # not wrong-footed, just genuinely unresolved -- small caution discount, not a veto
}

# If the regime hasn't been confirmed yet for this symbol (still
# flapping between raw reads, see REGIME_PERSISTENCE_BARS in
# core/indicators.py), only apply half the adjustment -- enough to
# matter, not enough to swing a decision on an unstable read.
REGIME_UNCONFIRMED_DAMPING = 0.5


# ============================================================
# SECTION 12: COMPONENT WEIGHTS
# ============================================================

COMPONENT_WEIGHTS = {
    "trend": 0.18,
    "supply_demand": 0.15,
    "wyckoff": 0.05,
    "h1_alignment": 0.12,
    "adx": 0.08,
    "volatility": 0.05,
    "support_resistance": 0.08,
    "ict_fvg": 0.06,
    "rsi_divergence_m1": 0.04,
    "veto_system": 0.10,
    "breakout": 0.04,
    "candlestick": 0.04
}


# ============================================================
# SECTION 13: MICROSTRUCTURE/GOLDEN SIGNALS
# ============================================================

MICRO_STRUCTURE_WEIGHT = 0.22
GOLDEN_SIGNALS_WEIGHT = 0.25


# ============================================================
# SECTION 14: INDICATOR PERIODS
# ============================================================

ATR_PERIOD = 14
RSI_PERIOD = 14
STOCH_K = 14
STOCH_D = 3
ADX_PERIOD = 14
EMA_FAST = 9
EMA_MEDIUM = 21
EMA_SLOW = 50
EMA_VERY_SLOW = 200


# ============================================================
# SECTION 15: SPREAD LIMITS
# ============================================================

MAX_SPREAD_PIPS = {
    "EURUSD": 40, "GBPUSD": 40, "USDCHF": 40, "USDJPY": 40,
    "AUDUSD": 40, "NZDUSD": 40, "USDCAD": 40,
    "XAUUSD": 50, "XAGUSD": 50,
    "SPX500": 60, "NAS100": 60, "DAX30": 60, "DJ30": 60
}

MAX_SPREAD_PIPS_M1 = {
    "EURUSD": 25, "GBPUSD": 25, "USDCHF": 25, "USDJPY": 25,
    "AUDUSD": 25, "NZDUSD": 25, "USDCAD": 25,
    "XAUUSD": 40, "XAGUSD": 40,
    "SPX500": 50, "NAS100": 50, "DAX30": 50, "DJ30": 50
}

TYPICAL_SPREADS = {
    "EURUSD": 6.0, "GBPUSD": 8.0, "USDJPY": 7.0,
    "AUDUSD": 8.0, "USDCAD": 8.0, "NZDUSD": 9.0,
    "USDCHF": 7.0, "XAUUSD": 25.0, "XAGUSD": 20.0
}


# ============================================================
# SECTION 16: ZONE SETTINGS - SINGLE SOURCE OF TRUTH
# ============================================================

# ✅ SINGLE DEFINITION - NO DUPLICATES!

# Zone grade scores
ZONE_GRADE_SCORES = {
    "A": 98,
    "B": 85,
    "C": 70,
    "D": 50,
    "E": 35          # WAS 0 - NOW 35 (matches helpers)
}

# Zone grade multipliers
ZONE_GRADE_MULTIPLIERS = {
    "A": 1.0,
    "B": 0.85,
    "C": 0.70,
    "D": 0.50,
    "E": 0.35
}

# Zone grade thresholds
# ✅ RECALIBRATED for event-counting.
#
# These numbers were calibrated against the OLD touch counter, which
# incremented once per BAR spent inside the touch band -- a single visit
# that lingered 15 bars scored 15. _calculate_initial_touch_count() now
# counts distinct VISITS (a run of consecutive bars inside the band is
# one touch), which is what "touch count" has always claimed to mean.
#
# Against distinct visits in a 100-bar window, the old thresholds are
# unreachable: a level revisited 15 separate times would mean price
# crosses it roughly every 7 bars. Measured on frequently-revisited
# levels, distinct-visit counts land around 3-8 where bar counts landed
# around 5-10.
#
# Scaled to preserve the SHAPE of the original tiers rather than picking
# round numbers -- each grade stays roughly 1.5-1.7x the one below, and
# D stays at 2 because "tested at least twice" is the minimum for a level
# to be a level at all rather than a single untested reaction.
#
#     A: 15 -> 8    a genuinely well-defined level, revisited repeatedly
#     B:  8 -> 5
#     C:  4 -> 3    the realistic floor for a tradable zone
#     D:  2 -> 2    unchanged: tested twice
#     E:  <2        fresh or untested
#
# NOTE: this widens what can pass VALID_ZONE_GRADES = [A, B, C]. It
# cannot on its own cause trades to fire -- probability is independently
# floored at 5.0 by the static volatility table until
# USE_ADAPTIVE_VOLATILITY_BANDS is enabled -- but the two together will.
ZONE_GRADE_THRESHOLDS = {"A": 8, "B": 5, "C": 3, "D": 2, "E": 0}

# ============================================================
# ✅ NEW: COMPOSITE ZONE QUALITY
# ============================================================
# Grade used to be a pure function of touch_count, and that is backwards
# for the strategy this system runs.
#
# Every other component here -- ICT, FVG, order blocks, displacement
# confirmation, the sweep detector -- is built around FRESH, untested
# levels. In SMC terms each touch CONSUMES the liquidity resting at a
# level, so a zone touched eight times has been drained. Grading purely
# on touches rewarded the drained zone with an A and rejected the fresh
# one as an E.
#
# Live proof: XAUUSD sat 43 pips (0.14 ATR) from a SUPPLY zone with
# displacement confirmed and timing ready, and was rejected -- because
# nobody had traded against that level yet. That is precisely the setup
# the rest of the pipeline exists to find.
#
# Quality is now a weighted blend of four signals. Touch count remains,
# but as ONE input with a deliberate hump rather than a ladder: 1-3
# touches confirm a level is respected, while many touches mean it is
# spent. The others reward the properties that actually make a fresh
# zone tradable.
#
# Weights sum to 1.0. They are a starting position, reasoned from how the
# strategy is built -- not measured, because no outcomes exist yet. When
# attach_outcome() has data behind it, these are the first numbers to fit.
ZONE_QUALITY_WEIGHTS = {
    "freshness": 0.30,      # how recently the zone formed
    "displacement": 0.30,   # how decisively price left it (impulse quality)
    "touch": 0.25,          # respected, but decaying past the hump
    "volume": 0.15,         # participation at formation
}

# touch_count -> touch sub-score (0-1). A hump, not a ladder.
# 0 touches is not a flaw in a fresh zone, but an untested level is
# unproven, so it scores below one that has held once or twice.
ZONE_TOUCH_QUALITY_CURVE = {0: 0.55, 1: 0.85, 2: 1.00, 3: 0.90, 4: 0.75, 5: 0.60}
ZONE_TOUCH_QUALITY_FLOOR = 0.35   # 6+ touches: level is spent

# Composite score (0-100) -> grade. Replaces the touch-count ladder.
ZONE_QUALITY_GRADE_THRESHOLDS = {"A": 80, "B": 65, "C": 50, "D": 35, "E": 0}

# Zone at-zone proximity in pips
# How close price must be to count as "at" a zone of each grade.
#
# ✅ E was 0.0 -- a zero-width band, so is_at_zone was structurally False
# for every E zone no matter where price stood. That closed a loop:
#
#     fresh zone -> grade E (0 touches) -> can never be "at zone"
#     -> never registers a touch -> stays E forever
#
# Live proof: XAUUSD sat 43 pips from its supply zone (0.14 ATR) with
# confirmed displacement and ready timing, reporting is_at_zone false
# against max_allowed_pips_for_grade 0.0. Price was on the level and the
# system could not say so.
#
# E now gets a real band. It is the WIDEST, not the narrowest, because a
# grade reflects how well-tested a zone is, not how precisely price must
# arrive at it -- and an untested zone is exactly the one you need to
# detect arrival at in order to test it. The grade still gates tradability
# through VALID_ZONE_GRADES; this only governs whether the system can
# perceive that price is there.
ZONE_AT_ZONE_PIPS = {
    "A": 5.0,
    "B": 6.0,
    "C": 8.0,
    "D": 12.0,
    "E": 15.0,
}

ZONE_PROXIMITY_PIPS_DEFAULT = 2.0
ZONE_TOUCH_COUNT_THRESHOLD = 3


# ============================================================
# SECTION 17: ATR TP MULTIPLIERS
# ============================================================

ATR_TP_MULTIPLIERS = {
    "FOREX": {"tp1": 2.0, "tp2": 3.0, "tp3": 4.0},
    "METALS": {"tp1": 1.6, "tp2": 2.4, "tp3": 3.2}
}

ATR_TP_MULTIPLIERS_M1 = {
    "FOREX": {"tp1": 1.5, "tp2": 2.2, "tp3": 3.0},
    "METALS": {"tp1": 1.2, "tp2": 1.8, "tp3": 2.4}
}


# ============================================================
# SECTION 18: FVG SETTINGS
# ============================================================

FVG_ENTRY_TOLERANCE_PIPS_BASE = 5.0
_FVG_TOLERANCE_MULTIPLIERS = {
    "XAU": 3.0,
    "XAG": 2.0,
    "DEFAULT": 1.0
}

FVG_BASE_TOLERANCE = {
    "XAU": 15.0,
    "XAG": 10.0,
    "DEFAULT": 5.0
}

FVG_MAX_TOLERANCE = {
    "XAU": 50.0,
    "XAG": 30.0,
    "DEFAULT": 20.0
}

FVG_ATR_MULTIPLIER = 0.3


# ============================================================
# SECTION 19: EMA SETTINGS
# ============================================================

EMA_MIN_SEPARATION_PIPS = 5.0
_EMA_SEPARATION_MULTIPLIERS = {
    "XAU": 0.6,
    "XAG": 0.8,
    "DEFAULT": 1.0
}


# ============================================================
# SECTION 20: SUPPORT/RESISTANCE
# ============================================================

RESISTANCE_PROXIMITY_WARNING_PIPS_BASE = 10.0
_RESISTANCE_PROXIMITY_MULTIPLIERS = {
    "XAU": 1.5,
    "XAG": 1.2,
    "DEFAULT": 1.0
}


# ============================================================
# SECTION 21: VOLUME SETTINGS
# ============================================================

VOLUME_IMBALANCE_THRESHOLDS_BASE = {
    "FOREX": 1.2,
    "METALS": 1.3,
    "INDICES": 1.25,
    "DEFAULT": 1.2
}

VOLUME_THRESHOLD_STRONG_TREND = 0.15
VOLUME_THRESHOLD_MODERATE_TREND = 0.20
# Halved for data collection: 525 low-volume vetoes, and off-session volume
# is structurally low rather than informative about the setup.
VOLUME_THRESHOLD_WEAK_TREND = 0.25

VOLUME_MULTIPLIER_EXTREME_LOW = 0.80
VOLUME_MULTIPLIER_VERY_LOW = 0.90
VOLUME_MULTIPLIER_LOW = 0.95
VOLUME_MULTIPLIER_BELOW_AVG = 1.00
VOLUME_MULTIPLIER_NORMAL = 1.00
VOLUME_MULTIPLIER_ABOVE_AVG = 1.15
VOLUME_MULTIPLIER_HIGH = 1.30

VOLUME_RATIO_EXTREME_LOW = 0.3
VOLUME_RATIO_VERY_LOW = 0.5
VOLUME_RATIO_LOW = 0.7
VOLUME_RATIO_BELOW_AVG = 0.85
VOLUME_RATIO_NORMAL_MAX = 1.15
VOLUME_RATIO_ABOVE_AVG = 1.5


# ============================================================
# SECTION 22: PROBABILITY CONSTANTS
# ============================================================

_BASE_PROBABILITY = 50.0
_MIN_PROBABILITY = 5.0
_MAX_PROBABILITY = 95.0
_RSI_DIVERGENCE_MULTIPLIER = 1.5
_MAX_RSI_DIVERGENCE_IMPACT = 30.0

_BEARISH_SIGNAL_CAP = 45.0
_BEARISH_SIGNAL_THRESHOLD = 4
_BULLISH_SIGNAL_CAP = 45.0
_BULLISH_SIGNAL_THRESHOLD = 4

CANDLE_READY_MULTIPLIER = 0.95
HIGH_VOLATILITY_MULTIPLIER = 0.9
INVALID_SPREAD_MULTIPLIER = 0.8


# ============================================================
# SECTION 23: WICK REVERSAL
# ============================================================

WICK_REVERSAL_RATIO_NORMAL = 3.0
WICK_REVERSAL_RATIO_SMALL = 5.0
WICK_SMALL_CANDLE_BODY_THRESHOLD = 1.0


# ============================================================
# SECTION 24: INSTRUMENT VOLUME MULTIPLIERS
# ============================================================

INSTRUMENT_VOLUME_MULTIPLIER_GOLD = 0.9
INSTRUMENT_VOLUME_MULTIPLIER_SILVER = 0.95
INSTRUMENT_VOLUME_MULTIPLIER_DEFAULT = 1.0


# ============================================================
# SECTION 25: ADX THRESHOLDS
# ============================================================

ADX_THRESHOLDS = {
    "XAUUSD": {"trend": 25.0, "strong_trend": 50.0},
    "XAGUSD": {"trend": 30.0, "strong_trend": 55.0},
    # ✅ FIXED: was {"trend": 40.0, "strong_trend": 70.0} -- a metals-scale
    # threshold that silently applied to EVERY non-XAU/XAG symbol (all FX
    # majors, indices, crypto, etc. fall into this bucket via
    # _get_adx_thresholds()'s substring match). 40.0 sat so far above
    # normal FX/index ADX readings that trend confirmation almost never
    # fired for anything but gold/silver, contradicting
    # RANGING_MARKET_ADX_THRESHOLD (25, defined below) which the rest of
    # the system already uses as the canonical trending bar for these
    # symbols. Aligned to 25/50 -- same trend threshold as XAUUSD's own
    # entry and the system-wide RANGING_MARKET_ADX_THRESHOLD, so
    # _detect_trend_bias, _detect_wyckoff_phase, and
    # classify_trading_regime all agree with each other and with the
    # rest of the codebase on what "trending" means for the same ADX
    # value, instead of three different thresholds silently disagreeing.
    "DEFAULT": {"trend": 25.0, "strong_trend": 50.0}
}

ADX_STRONG_TREND_THRESHOLD = 50

ADX_EXTREME_THRESHOLDS = {
    "XAUUSD": 50,
    "XAGUSD": 52,
    "DEFAULT": 55
}


# ============================================================
# SECTION 26: ATR RANGE MULTIPLIERS
# ============================================================

_ATR_RANGE_MULTIPLIERS = {
    "XAUUSD": 1.0,
    "XAGUSD": 1.0,
    "EURUSD": 1.0,
    "GBPUSD": 1.2,
    "DEFAULT": 1.0
}


# ============================================================
# SECTION 27: NORMAL ATR RANGES
# ============================================================

# ============================================================
# ✅ NEW: ADAPTIVE VOLATILITY BANDS (OPT-IN)
# ============================================================
# When True, check_volatility_protection() derives its min/max/extreme
# tiers from the instrument's OWN recent ATR distribution (10th / 90th /
# 98th percentile of the last 100 bars) instead of the hand-maintained
# _NORMAL_ATR_RANGES table below.
#
# Defaults to False deliberately. The static table being wrong is not a
# cosmetic problem -- on XAGUSD it scored mid-normal volatility as
# EXTREME and applied a ~75-point confidence penalty that floored
# probability to the 5.0 clamp on every single bar, so no trade could
# ever fire on that symbol regardless of setup quality. Flipping this to
# True removes that floor, which means trades that were being silently
# suppressed will start firing. That is the intended outcome, but it is a
# live-money behaviour change and should be switched on deliberately,
# after checking `volatility_protection.range_source` in a few payloads
# to confirm the adaptive band is being accepted rather than rejected as
# malformed.
#
# The band degrades to this static table on its own whenever there are
# fewer than 20 usable bars or the distribution is degenerate, so
# enabling it does not remove the table as a safety net.
# ✅ ENABLED, on evidence rather than argument.
#
# Five live snapshots across five instruments, all reporting probability
# 13.0 -- byte-identical on symbols whose ATR spans 0.7 to 171.6 pips, a
# factor of 245. That number is not a score. It is 5.0 (the hard clamp)
# plus 8.0 (the ADR mean-reversion constant), which is what you get when
# the static table's penalty floors probability before anything else runs:
#
#   XAUUSD  ATR 171.6  penalty -90.0  ->  5.0 + 8.0 = 13.0
#   XAGUSD  ATR  43.4  penalty -90.0  ->  5.0 + 8.0 = 13.0
#   GBPUSD  ATR   0.7  penalty -13.8  ->  5.0 + 8.0 = 13.0
#   USDCAD  ATR   0.9  penalty -12.4  ->  6.6 + 8.0 = 13.0 (clamped)
#
# _NORMAL_ATR_RANGES calls XAUUSD's normal range 15-40 pips with extreme
# above 70. Gold M1 routinely prints 100+. The table is not slightly off;
# it is describing a different instrument, and it applies a 90-point
# penalty for the difference.
#
# The percentile band -- computed from each instrument's OWN last 100
# bars, already present in every payload, and previously used for nothing
# -- calls the same readings NORMAL. volatility_verdicts prints the
# disagreement explicitly on every bar.
#
# With this True, the penalty is derived from what the instrument
# actually does. Probability starts varying with the setup instead of
# reporting a constant. Trades that were suppressed by a miscalibrated
# table will begin firing; that is the intended effect and the reason
# this was left off until there was direct evidence rather than an
# argument. The band degrades to the static table on its own whenever
# fewer than 20 usable bars exist or the distribution is degenerate, so
# the table remains the safety net it was always meant to be.
# USE_ADAPTIVE_VOLATILITY_BANDS: removed 2026-09-18 with core/adaptive_thresholds.py

# ============================================================
# ✅ NEW: ADAPTIVE OSCILLATOR BANDS (OPT-IN)
# ============================================================
# When True, the RSI and Stochastic reads that feed the probability chain
# and family voting come from core/adaptive_thresholds.py -- oversold/
# overbought derived from the instrument's OWN recent distribution
# (10th/90th percentile of the last 100 bars) -- instead of the flat
# textbook 30/70 and 20/80 constants.
#
# Those adaptive reads are ALREADY being computed on every bar. They are
# published under indicators.rsi.adaptive and indicators.stochastic.
# adaptive, roughly 1600 lines after family voting has already consumed
# the flat-threshold versions. Display only.
#
# They disagree, and not rarely. Live examples:
#   rsi 51.2, flat -> NEUTRAL conf 50 | adaptive -> SELL conf 65
#                     (adaptive band overbought 49.8 in a downtrend)
#   rsi 46.2, flat -> NEUTRAL conf 50 | adaptive -> SELL conf 65
# In both, family voting recorded rsi vote 0.0 while the adaptive read
# had a directional opinion at confidence 65.
#
# Defaults to False. Unlike the volatility switch, there is no clear
# a-priori winner here: an adaptive band adapts to regime, but it can
# also narrow to the point of firing constantly (one live band was only
# 20.7 RSI points wide against the textbook 40, which passes
# compute_adaptive_band's degenerate-distribution guard at 10). Leaving
# it off records HOW OFTEN the two disagree, via
# indicators.adaptive_disagreement in the payload, so the decision can be
# made on observed frequency rather than on argument.
#
# DECIDED 2026-09-15: keep False. On the 111 stored trades with tick paths,
# the adaptive RSI's directional calls were right about the market 31% of
# the time (CI 19-48%, n=35): when it opposed the trade, the trade was right
# 65-73% in both ranging and trending regimes. It is reversal logic on M1,
# where the measured behaviour is continuation. Round numbers (33%) and
# wave C (38%) are the same kind of call; none of the three feeds the
# probability or the entry decision (see tests/test_reversal_votes_removed.py).
# USE_ADAPTIVE_OSCILLATOR_BANDS: removed 2026-09-18 with core/adaptive_thresholds.py

# ============================================================
# ✅ NEW: MID PRICE FOR INDICATOR COMPARISONS (OPT-IN)
# ============================================================
# current_price is tick.ask. Every indicator LEVEL -- Bollinger bands,
# EMAs, pivots, zone levels, FVG boundaries, POC/VAH/VAL -- is derived
# from bar CLOSE prices, which are bid-side. So the pipeline compares an
# ask against bid-derived levels everywhere.
#
# On a tight-spread instrument that is rounding. On XAGUSD it is not:
# live band width 355.6 pips against a 43-pip spread means every
# Bollinger read sits 12.1% higher up the band than the price the band
# was built from. The 00:08 bar reads percent_b 0.426 on bid and 0.547
# on ask -- below the middle band and above it, same bar. The bias is
# systematically bullish and is LARGEST when spreads widen, which is
# when the read is least trustworthy.
#
# Buying at the ask is correct for ENTRY PRICING. Measuring distance
# from a bid-derived level with an ask is not. When True, comparisons
# use the mid ((bid+ask)/2) while entry price, lot sizing and margin
# keep using the ask.
#
# Defaults to False. This shifts zone distance, FVG proximity, S/R
# distance and Bollinger position simultaneously, so it wants to be
# switched on deliberately and watched. price_basis_delta in the payload
# reports what it WOULD change while it is off.
USE_MID_PRICE_FOR_INDICATORS = False

# ============================================================
# ✅ NEW: CONVICTION FILTER — SELECTIVITY AT CONSTANT R:R
# ============================================================
# The only way to raise win rate without shrinking TP is to decline the
# trades the system is least sure about. At the configured 2:1, break-even
# is 33%; the goal is not more trades, it is that the ones taken are right
# more often.
#
# The filter consumes signals ALREADY computed on every bar and currently
# discarded at decision time:
#
#   coherence        computed, reported, never consulted
#   gate near_miss   calculated for every gate, used for nothing
#   family consensus votes, moves probability by at most +5, never required
#   chain alignment  ~12 checks report aligned true/false; only the SUM of
#                    their adjustments is used, so three opposing checks
#                    can be masked by one strongly aligned one
#
# CONVICTION_MIN_SCORE is the soft bar. The hard requirements (a CRITICAL
# or ERROR coherence violation, a near-miss gate, families opposing the
# direction, 2+ confluence checks opposing) decline regardless of score,
# because an additive score is exactly what let a setup with three
# refusals still reach 95%.
#
# EXPECT FEWER TRADES. That is the mechanism, not a side effect. If the
# audit later shows conviction does not predict wins, loosen or remove it
# rather than defend it — it is a hypothesis with a number attached, and
# the outcome records are how it gets tested.
USE_CONVICTION_FILTER = True
CONVICTION_MIN_SCORE = 0.55
# Set True to log what conviction WOULD have declined without acting on
# it — useful for measuring the filter before trusting it.
CONVICTION_SHADOW_MODE = False


# ============================================================
# DEFENSIVE CORE  (pipeline stages 7, 8, 9)
# ============================================================
# Three independent refusals layered on top of the existing stack. None
# of them proposes a trade; each can only decline one, so they cannot
# manufacture entries no matter how they are tuned.
#
# They are deliberately ordered cheapest-and-hardest first when read,
# even though all three are evaluated for observability:
#
#   Stage 9  symbolic gate   arithmetic invariants of the trade itself.
#                            Pure boolean, no model, no market data.
#   Stage 7  meta-labeling   a model over outcomes: will THIS entry hit
#                            its target before its stop?
#   Stage 8  conformal       what the model's score was actually worth
#                            out of sample, and abstention when that
#                            cannot be established.
#
# SHADOW MODE FIRST. Each stage logs what it WOULD have declined before
# it is allowed to decline anything, exactly as the conviction filter
# was introduced. A filter is a hypothesis; these flags are how it gets
# measured before it is trusted with money.

# --- Stage 9: symbolic gate -------------------------------------
# Enabled outright, because it does not predict anything. It refuses
# trades whose own arithmetic is incoherent -- a stop the spread
# swallows, a target inside the spread, an unmeasurable R:R. Those are
# not judgement calls that need a trial period.
USE_SYMBOLIC_GATE = True
SYMBOLIC_GATE_SHADOW_MODE = False

# --- Stages 7 & 8: REMOVED (meta-labeling, conformal) -----------
# The pipeline is rule-based by decision. Stage 7 was its only trained
# model -- a logistic regression over replay outcomes -- and stage 8
# existed only to calibrate that model's scores, so both were removed
# from the decision path rather than left switched off behind a flag.
#
# Nothing measurable was lost: stage 7 never passed its own validation
# gate. Purged cross-validation scored it at AUC 0.5034 against a
# shuffled-label control of 0.5092, so it performed worse than random
# labels, core/train_meta_label.py refused to write an artifact, and
# the stage never influenced a single decision.

# --- Stage 10: online position sizing ---------------------------
# Follow-the-Regularised-Leader over {TRADE, CASH}: the weight on TRADE
# becomes a multiplier on the lot calculate_lot_proper() already sized
# from the stop distance. It can only make a position smaller, never
# larger, and it predicts nothing -- it just stops betting the same
# amount on a strategy that has stopped paying.
#
# Simulated on a sequence matching the measured expectancy it cut max
# drawdown 43.7% while a profitable sequence kept a 0.97 mean
# multiplier, which is the asymmetry worth having: it costs almost
# nothing when the strategy works and a great deal less when it does not.
#
# OFF by default because it changes live position sizing, and that is
# the operator's decision rather than a default. Turning it on with the
# current measured expectancy will correctly drive size toward the
# floor -- which is informative, not a malfunction.
#
# ENABLED. Measured on this project's own recorded trades:
#
#     total R        -2.589  ->  -1.936
#     max drawdown    7.898  ->   2.916   (-63.1%)
#     mean size       0.345x
#
# It is enabled rather than left off because it is the only change in
# this system with a measured, repeatable improvement AND no way to make
# things worse: the multiplier is bounded to [0.10, 1.00], so it can
# only ever reduce a position, never enlarge one. On a strategy whose
# measured expectancy is negative, sizing toward the floor is the
# correct response, not a malfunction.
#
# To revert: set this back to False. State lives in
# online_sizing_state.json (delete it to reset the sizer's memory).
#
# What it does NOT do is create edge. It reduces the cost of not having
# any, which on the current numbers is worth roughly 5R of drawdown.
# OFF as of 2026-09-10.
#
# It was scaling every lot by 0.50 with n_updates = 0 -- it had never resolved
# a single trade, so it was not responding to measured expectancy at all, it
# was just permanently halving size at its initial value.
#
# Worse, it rewrites lot_size WITHOUT recomputing risk_usd or
# margin_required_usd, so the stored analysis became internally incoherent: a
# live AUDNZD trade recorded LOT_SIZE 0.07 next to margin 50.53, when 0.07 lot
# is 25.08 by MT5's own order_calc_margin -- that margin belongs to the 0.15
# lot it started from, which is also what actually got traded. Checked against
# MT5, actual_risk_usd disagreed with the true stop cost on 14 of 14 trades,
# understating risk 3x typically and 32x on two AUDCHF fills.
#
# Turn it back on only once the recorded lot, risk and margin are recomputed
# together after scaling -- otherwise every trade it touches is mislabelled in
# the very fields the research depends on.
USE_ONLINE_SIZING = False


_NORMAL_ATR_RANGES = {
    "XAUUSD": {"min": 15.0, "max": 40.0, "extreme": 70.0},
    "XAGUSD": {"min": 10.0, "max": 25.0, "extreme": 45.0},
    "DEFAULT": {"min": 5.0, "max": 20.0, "extreme": 40.0}
}


# ============================================================
# SECTION 28: INDICATORS CONFIG
# ============================================================

# Wyckoff volume thresholds
WYCKOFF_MARKUP_STRONG_MIN_VOL = 1.5
WYCKOFF_MARKUP_MIN_VOL = 0.85
WYCKOFF_MARKDOWN_STRONG_MIN_VOL = 1.5
WYCKOFF_MARKDOWN_MIN_VOL = 0.85

WYCKOFF_SPIKE_THRESHOLDS = {
    "XAUUSD": 1.3,
    "XAGUSD": 1.4,
    "DEFAULT": 1.5
}

WYCKOFF_CONSOLIDATION_VOLUME_THRESHOLD = 0.7

WYCKOFF_LOOKBACK_BARS = {
    "M1": 100,
    "M5": 80,
    "M15": 60,
    "M30": 60,
    "H1": 50,
    "H4": 50,
    "D1": 30,
    "DEFAULT": 50
}

WYCKOFF_UPGRADE_ADX_THRESHOLD = 50

WYCKOFF_STRONG_TREND_SCORE = 95
WYCKOFF_CONFIRMED_SCORE = 85
WYCKOFF_BUILDING_SCORE = 70
WYCKOFF_TENTATIVE_SCORE = 40
WYCKOFF_NEUTRAL_SCORE = 25

MOMENTUM_THRESHOLDS = {
    "XAUUSD": 0.001,
    "XAGUSD": 0.0015,
    "DEFAULT": 0.002
}

ZONE_RESET_AFTER_HOURS = 24
ZONE_MAX_TOUCHES_FOR_GRADE = 50
ZONE_PERSISTENCE_SECONDS = 60

ZONE_TIME_DECAY_CONFIG = {
    "XAUUSD": {"decay_start_hours": 24, "decay_duration_hours": 72, "min_decay_factor": 0.3},
    "XAGUSD": {"decay_start_hours": 18, "decay_duration_hours": 60, "min_decay_factor": 0.3},
    "DEFAULT": {"decay_start_hours": 12, "decay_duration_hours": 48, "min_decay_factor": 0.3}
}

ZONE_LOOKBACK_BARS = {
    "M1": 100,
    "M5": 80,
    "M15": 60,
    "M30": 60,
    "H1": 50,
    "H4": 40,
    "D1": 30,
    "DEFAULT": 100
}

# ✅ NEW: floor the zone touch band at a fraction of the instrument's own
# ATR. The absolute pip table below has the same units problem the swing
# filter had: XAGUSD M1 resolves to 5.0 x 0.25 = 1.25 pips, on an
# instrument whose live ATR ran 24-66 pips across six consecutive
# payloads -- a touch band of 2-5% of one bar's average range. Almost
# nothing registered as a touch, touch_count came back 0 or 1 every
# time, and since grade is derived ENTIRELY from touch_count
# (ZONE_GRADE_THRESHOLDS: A>=15 B>=8 C>=4 D>=2) every zone graded E.
# Grade E is not tradable, so "SKIP - INVALID ZONE" was the outcome on
# every single bar regardless of setup quality.
ZONE_TOUCH_ATR_FRACTION = 0.10


# ============================================================
# ✅ NEW: ATR-RELATIVE PIP THRESHOLDS -- SHARED HELPER
# ============================================================
# The dominant failure mode in this codebase is an absolute pip constant
# that is correct on the instrument it was written for and meaningless on
# every other one. Found and fixed individually six times already:
#
#   MIN_SWING_SIZE_PIPS                0.05 pips on XAGUSD  (10-100x off)
#   ZONE_TOUCH_DISTANCE_PIPS           1.25 pips vs 63-pip ATR -> grade E always
#   detect_stop_hunts min_sweep_pips   0.5 pips vs a 20-pip spread
#   MICRO_STRUCTURE_MOMENTUM_THRESHOLD 10 ticks/s vs an observed 1.3-2.6
#   get_zone_volume_profile band       2.0 pips -> zero touches
#   _NORMAL_ATR_RANGES                 10-25 "normal" vs a real 30-90 band
#
# Fixing them one at a time does not stop the next one being added. This
# helper exists so a threshold can be expressed as "the larger of a floor
# and a fraction of what this instrument actually moves".
#
# Deliberately max(), never replace: an instrument the base value already
# suits is unaffected, so adopting this can only ever loosen a threshold
# that was too tight for a volatile symbol -- it never tightens one that
# was working.
def atr_relative_pips(base_pips: float, atr_pips: float = None,
                      fraction: float = 0.10, cap_pips: float = None) -> float:
    """
    Scale a pip threshold to the instrument's own volatility.

    base_pips : the existing absolute constant, kept as a floor
    atr_pips  : current ATR in pips; None/0 returns base_pips unchanged,
                so every call site is safe before ATR is threaded through
    fraction  : share of ATR the threshold represents
    cap_pips  : optional ceiling, for thresholds that should not grow without
                limit on a violently volatile bar

    Returns pips, not price units.
    """
    try:
        base = float(base_pips)
    except (TypeError, ValueError):
        return 0.0
    if not atr_pips or atr_pips <= 0:
        return base
    # ✅ FIXED (2026-09-15): was max(base, ATR x fraction). The base constants
    # were tuned on XAGUSD (M1 ATR ~40 pips), where ATR x fraction already
    # exceeds them -- but on a currency pair with an M1 ATR near 1 pip the
    # "floor" always won: an 8-pip fib proximity was 8 ATR, a 5-pip retest
    # tolerance 5 ATR. Every level looked "near", which is why these
    # components reported a setup on nearly every bar. With ATR known the
    # threshold is the ATR fraction (XAGUSD's calibrated behaviour, now on
    # every instrument); the pip constant is only the fallback without ATR.
    scaled = float(atr_pips) * fraction
    if cap_pips:
        scaled = min(scaled, float(cap_pips))
    return scaled


ZONE_TOUCH_DISTANCE_PIPS = {
    "XAUUSD": 3.0,
    "XAGUSD": 5.0,
    "DEFAULT": 2.0
}

# ============================================================
# MEASURED INDICATOR CONTRIBUTIONS (calculate_real_probability)
# ============================================================
# Set 2026-09-15 from the 111 stored trades with tick paths
# (ai/component_forensics). "Lift" = how much more often the trade's
# direction was right when the contribution pushed FOR the trade than when
# it pushed AGAINST it (5-ATR barrier, 8 h).
#
#   MACD (from signal_str)   lift -13   -> re-based on the HISTOGRAM:
#                                          histogram sign lift +21 (p=0.06).
#                                          "NEUTRAL_BULLISH" (line > 0,
#                                          histogram < 0) scored +8 for a BUY
#                                          and was followed by a FALL 73%.
#   M1 trend                 lift   0   -> halved
#   Bollinger                lift  +2   -> halved
#   Stochastic               lift  +1   -> halved
#   RSI impact               lift -27   -> removed (n=13 opposed; leans inverted)
#   ADX < 20 penalty         penalised trades right 70% vs 52% -> removed
#
# Halving rather than zeroing the no-edge terms keeps probability levels close
# to where the 75% entry threshold was calibrated; removing them outright
# would silently cut entries.
PROB_SCALE_TREND = 0.5
PROB_SCALE_BOLLINGER = 0.5
PROB_SCALE_STOCHASTIC = 0.5
PROB_SCALE_RSI_IMPACT = 0.0
ADX_LOW_PENALTY = 0.0            # was -5 when ADX < 20
#   Zone contribution        +5..+20 on 103 of 104 trades; grade did not rank
#                            outcomes (B +0.84R, A +0.07R, D -0.20R) -> removed
#   ICT contribution         +10 on 96 of 104 trades, never negative (the
#                            opposite case is a pre-flight veto) -> removed
#   Both were constant lift; see PROBABILITY_RECENTER_POINTS for the matching
#   shift of every probability threshold. The ICT pre-flight vetoes remain.
PROB_SCALE_ZONE = 0.0
PROB_SCALE_ICT = 0.0

# MACD, symmetric for both sides, by histogram (momentum) then line (position):
MACD_SCORE_WITH = 15             # histogram and line both with the side
MACD_SCORE_TURNING_WITH = 8      # histogram with the side, line not yet
MACD_SCORE_FADING = -10          # line with the side, histogram turned against
MACD_SCORE_AGAINST = -15         # histogram and line both against the side

# Zone contribution scores (used in calculations.py)
ZONE_CONTRIBUTION_A_AT_ZONE = 20
ZONE_CONTRIBUTION_B_AT_ZONE = 15
ZONE_CONTRIBUTION_C_AT_ZONE = 10
ZONE_CONTRIBUTION_D_AT_ZONE = 5
ZONE_CONTRIBUTION_A_AWAY = 10
ZONE_CONTRIBUTION_B_AWAY = 5
ZONE_CONTRIBUTION_E_PENALTY = -15

DIVERGENCE_LOOKBACK = {
    "M1": 240, "M5": 288, "M15": 240, "M30": 240,
    "H1": 168, "H4": 90, "D1": 60, "W1": 52, "MN1": 24
}
DEFAULT_DIVERGENCE_LOOKBACK = 60

M15_FALLBACK_ENABLED = True
M15_MIN_BARS = 50

MIN_BARS_FOR_TREND = {
    "M1": 200,
    "M5": 150,
    "M15": 120,
    "M30": 100,
    "H1": 100,
    "H4": 80,
    "D1": 60,
    "DEFAULT": 100
}

PIN_BAR_THRESHOLD = 2.0

# FVG scoring weights
FVG_WIDTH_SCORE_WEIGHT = 40
FVG_FRESHNESS_SCORE_WEIGHT = 30
FVG_VOLUME_SCORE_WEIGHT = 20

# Stochastic scoring with trend awareness
STOCHASTIC_SCORE_OVERSOLD_BULLISH = 15
STOCHASTIC_SCORE_OVERBOUGHT_BEARISH = 15
STOCHASTIC_SCORE_OVERSOLD_NEUTRAL = 0
STOCHASTIC_SCORE_OVERBOUGHT_NEUTRAL = 0

# RSI period divergence thresholds
RSI_PERIOD_DIVERGENCE_STRONG = 10
RSI_PERIOD_DIVERGENCE_MODERATE = 5

# Volume scoring with trend awareness
VOLUME_SCORE_STRONG_TREND_EXTREME_LOW = -30
VOLUME_SCORE_STRONG_TREND_VERY_LOW = -15
VOLUME_SCORE_STRONG_TREND_MODERATE = -10
VOLUME_SCORE_STRONG_TREND_LOW = -5
VOLUME_SCORE_NORMAL_TRENDING = 5
VOLUME_SCORE_HIGH_TRENDING = 15

VOLUME_SCORE_WEAK_TREND_EXTREME_LOW = -40
VOLUME_SCORE_WEAK_TREND_VERY_LOW = -25
VOLUME_SCORE_WEAK_TREND_MODERATE = -15
VOLUME_SCORE_WEAK_TREND_LOW = -10


# ============================================================
# SECTION 29: HELPERS CONFIG
# ============================================================

# Volume baseline configuration
VOLUME_BASELINE_BARS = {
    "M1": 200,
    "M5": 100,
    "M15": 100,
    "M30": 100,
    "H1": 100,
    "H4": 100,
    "D1": 50,
    "DEFAULT": 100
}

# Spread collapse thresholds
SPREAD_COLLAPSE_ABSOLUTE_THRESHOLD_PIPS = {
    "XAUUSD": 5.0,
    "XAGUSD": 3.0,
    "DEFAULT": 0.5
}

SPREAD_COLLAPSE_PERCENTAGE_THRESHOLD = 0.85
SPREAD_COLLAPSE_METALS_THRESHOLD = 0.70

# Minimum activity thresholds
MIN_ACTIVITY_SECONDS = {
    "XAUUSD": 5,
    "XAGUSD": 4,
    "DEFAULT": 3
}

# Micro-structure thresholds
MICRO_STRUCTURE_PROBABILITY_THRESHOLD = 60

# ✅ NEW: per-extra-signal bonus in EntryEngine.calculate_timing_confidence.
#
# That function takes max() over the tape-level signals, so corroboration
# was discarded entirely -- spread_collapse + momentum_burst +
# volume_imbalance together scored 70, the same as spread_collapse alone.
# Combined with min_timing_confidence (75) and absorption being the only
# signal worth more than 70, that meant ONLY absorption could ever set
# timing_ready, regardless of how many other signals agreed.
#
# Small and capped on purpose: these signals are correlated (a spread
# collapse and a volume-imbalance spike often describe the same moment on
# the tape), so agreement deserves a nudge rather than a sum. At 5, two
# agreeing non-absorption signals reach 75 and clear the gate; one alone
# still does not.
TIMING_CORROBORATION_BONUS = 5
MICRO_STRUCTURE_MAX_SPREAD_PIPS = 8.0
# ✅ REPLACED by acceleration-based detection. The old rule was
# `ticks_per_second > 10` -- an absolute tick rate, which is a property
# of the BROKER FEED far more than of the market. Live XAGUSD observed
# 1.32-2.63 ticks/s across six payloads; the peak was 26% of the
# threshold, so momentum_burst had never once fired.
#
# A burst is acceleration, not a rate. Comparing the second half of the
# tick window against the first half is feed-agnostic: it asks whether
# activity is picking up right now, which is the actual question, and it
# needs no per-broker calibration.
MICRO_STRUCTURE_MOMENTUM_ACCELERATION = 2.0

# Absolute floor so a dead-quiet window can't report a "burst" for going
# from 0.1 to 0.3 ticks/s. Deliberately inside the observed range (1.3-2.6)
# so it filters noise without becoming the binding constraint again.
MICRO_STRUCTURE_MOMENTUM_MIN_RATE = 2.0

MICRO_STRUCTURE_MOMENTUM_THRESHOLD = 10  # retained: still referenced by legacy callers
# ⚠️ STRUCTURALLY UNREACHABLE -- see the guard in analyze_micro_structure.
#
# avg_tick_volume = total_volume / len(tick_list), where total_volume is
# bid_tick_count + ask_tick_count. A tick carries the BID flag, the ASK
# flag, or both, so that ratio is bounded in [1.0, 2.0] BY CONSTRUCTION.
# A threshold of 5 is 2.5x the mathematical maximum: iceberg_detected
# could never be True for any input. Live observed range 0.97-1.06,
# exactly as the formula predicts.
#
# This is not a calibration problem. The detector compares flag DENSITY
# to order SIZE -- MT5 tick_volume on this feed is a tick count, not
# traded volume, so the quantity an iceberg would show up in is not
# present in the data at all. Retuning the number would make it fire on
# noise rather than on icebergs.
#
# Left at 5 and reported as unavailable rather than False, so the payload
# stops claiming "no iceberg detected" when the honest answer is "this
# feed cannot answer that question".
MICRO_STRUCTURE_ICEBERG_MIN_VOLUME = 5
MICRO_STRUCTURE_ICEBERG_MAX_PRANGE_PIPS = 2.0
MICRO_STRUCTURE_ICEBERG_MIN_TICKS = 50

# ✅ NEW: volume_imbalance (ask_volume/bid_volume, real tape-level
# aggression) was being computed in analyze_micro_structure() every
# call and then never read again by anything -- buried inside a
# "debug" sub-dict with no consumer. This is the confirmation
# threshold for actually using it: a BUY needs ask-side tick volume at
# least this many times bid-side (aggressive buying into the offer);
# a SELL needs the mirror image (bid_volume at least this many times
# ask_volume). 1.3 = at least 30% more aggressive activity on the
# expected side, not just a coin-flip majority.
# ✅ 1.3 -> 1.15. This is ask_tick_count / bid_tick_count -- a tick-FLAG
# ratio, which is far tighter around 1.0 than a traded-volume ratio would
# be. Live observed 0.88-1.16 across six payloads, so 1.3 (and its 0.77
# mirror) was never reached. 1.15 is a real 15% skew, reachable roughly
# one bar in six on the observed distribution -- present without being
# constant.
#
# Six payloads from one symbol on one broker is thin evidence for a
# number. If this fires far more or far less than ~1-in-6 in practice,
# that is the signal to move it, not an argument against it.
MICRO_STRUCTURE_VOLUME_IMBALANCE_CONFIRM_RATIO = 1.15


# ============================================================
# SECTION 30: ELLIOTT WAVE RECOMMENDATIONS
# ============================================================

ELLIOTT_WAVE_RECOMMENDATIONS = {
    "impulse": {
        "1": {"recommendation": "BUY", "action": "BUY NOW", "direction": "BULLISH", "confidence_bonus": 10},
        "2": {"recommendation": "WAIT", "action": "WAIT", "direction": "NEUTRAL", "confidence_bonus": 0},
        "3": {"recommendation": "STRONG_BUY", "action": "BUY NOW", "direction": "BULLISH", "confidence_bonus": 20},
        "4": {"recommendation": "WAIT", "action": "WAIT", "direction": "NEUTRAL", "confidence_bonus": 0},
        "5": {"recommendation": "BUY", "action": "BUY NOW", "direction": "BULLISH", "confidence_bonus": 0},
    },
    "corrective": {
        "A": {"recommendation": "SELL", "action": "SELL NOW", "direction": "BEARISH", "confidence_bonus": 0},
        "B": {"recommendation": "WAIT", "action": "WAIT", "direction": "NEUTRAL", "confidence_bonus": 0},
        "C": {"recommendation": "STRONG_SELL", "action": "SELL NOW", "direction": "BEARISH", "confidence_bonus": 10},
    },
    "diagonal": {"recommendation": "NEUTRAL", "action": "WATCH", "direction": "NEUTRAL", "confidence_bonus": 0},
    "triangle": {"recommendation": "WAIT", "action": "WAIT", "direction": "NEUTRAL", "confidence_bonus": 0},
}


# ============================================================
# SECTION 31: HELPER FUNCTIONS
# ============================================================

def get_instrument_type(symbol: str) -> str:
    """Determine instrument type from symbol name."""
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "XAG" in symbol_upper or "GOLD" in symbol_upper or "SILVER" in symbol_upper:
        return "METALS"
    elif "SPX" in symbol_upper or "NAS" in symbol_upper or "DAX" in symbol_upper or "DJ" in symbol_upper:
        return "INDICES"
    elif any(pair in symbol_upper for pair in ["EUR", "GBP", "USD", "AUD", "NZD", "CAD", "CHF", "JPY"]):
        return "FOREX"
    else:
        return "DEFAULT"


def get_instrument_factor(symbol: str, multiplier_dict: dict) -> float:
    """Get instrument-specific multiplier."""
    symbol_upper = symbol.upper()
    for key in multiplier_dict:
        if key in symbol_upper:
            return multiplier_dict[key]
    return multiplier_dict.get("DEFAULT", 1.0)


def get_typical_spread(symbol: str) -> float:
    """Get typical spread for a symbol (pips)."""
    symbol_upper = symbol.upper()
    return TYPICAL_SPREADS.get(symbol_upper, 10.0)


def get_max_spread(symbol: str, timeframe: str = "M1") -> int:
    """Get instrument and timeframe-aware maximum allowed spread."""
    symbol_upper = symbol.upper()
    if timeframe.upper() == "M1":
        spreads = MAX_SPREAD_PIPS_M1
    else:
        spreads = MAX_SPREAD_PIPS
    return spreads.get(symbol_upper, 40)


def get_bb_period(timeframe: str = "M1") -> int:
    """Get timeframe-appropriate Bollinger Band period."""
    return BB_PERIOD.get(timeframe.upper(), BB_PERIOD["DEFAULT"])


def get_bb_std(timeframe: str = "M1") -> float:
    """Get timeframe-appropriate Bollinger Band standard deviation."""
    return BB_STD.get(timeframe.upper(), BB_STD["DEFAULT"])


def get_bb_squeeze_threshold(symbol: str) -> float:
    """Get instrument-aware Bollinger Band squeeze threshold."""
    base_threshold = BB_SQUEEZE_THRESHOLD_BASE
    multiplier = get_instrument_factor(symbol, _BB_SQUEEZE_MULTIPLIERS)
    return base_threshold * multiplier


def get_fvg_tolerance_pips(symbol: str) -> float:
    """
    ⚠️ SUPERSEDED AND UNCALLED. Do not wire this up.

    The live implementation is calculations._get_fvg_tolerance_pips(),
    which takes atr_pips and returns max(base, atr * FVG_ATR_MULTIPLIER)
    with a per-instrument cap. This version is a flat per-symbol constant
    with no ATR awareness at all, and would return a materially different
    tolerance for the same symbol -- the value that gates ICT blocking,
    the ICT vote, and the FVG proximity checks.

    Kept rather than deleted because deleting a public config name can
    break an importer outside this tree, but labelled so nobody
    "reconnects" it thinking it is the canonical one.
    """
    return FVG_ENTRY_TOLERANCE_PIPS_BASE * get_instrument_factor(symbol, _FVG_TOLERANCE_MULTIPLIERS)


def get_resistance_proximity_pips(symbol: str) -> float:
    """Get instrument-aware resistance proximity warning in pips."""
    return RESISTANCE_PROXIMITY_WARNING_PIPS_BASE * get_instrument_factor(symbol, _RESISTANCE_PROXIMITY_MULTIPLIERS)


def get_ema_min_separation_pips(symbol: str) -> float:
    """Get instrument-aware EMA minimum separation in pips."""
    return EMA_MIN_SEPARATION_PIPS * get_instrument_factor(symbol, _EMA_SEPARATION_MULTIPLIERS)


# "At zone" distance as a share of ATR per grade. Derived from the pip table
# above on XAGUSD (x1.5, ATR ~40 pips), where it was tuned: A 7.5p ~0.2 ATR ...
# E 22.5p ~0.55 ATR. The pip table is 5-15 ATR on a 1-pip-ATR currency pair,
# so every graded zone read "at zone".
ZONE_AT_ZONE_ATR_FRACTION = {"A": 0.20, "B": 0.25, "C": 0.30, "D": 0.45, "E": 0.55}


def get_zone_proximity_pips(symbol: str, grade: str, atr_pips: float = None) -> float:
    """Get instrument-aware zone proximity in pips (ATR-scaled when ATR is known)."""
    if atr_pips and atr_pips > 0:
        return float(atr_pips) * ZONE_AT_ZONE_ATR_FRACTION.get(grade, 0.3)
    base_pips = ZONE_AT_ZONE_PIPS.get(grade, 8.0)
    multiplier = get_instrument_factor(symbol, {
        "XAU": 2.0,
        "XAG": 1.5,
        "DEFAULT": 1.0
    })
    return base_pips * multiplier


def get_atr_tp_multipliers(symbol: str, timeframe: str = "M1") -> dict:
    """Get instrument and timeframe-aware ATR TP multipliers."""
    instrument_type = get_instrument_type(symbol)
    if timeframe.upper() == "M1":
        multipliers = ATR_TP_MULTIPLIERS_M1
    else:
        multipliers = ATR_TP_MULTIPLIERS
    return multipliers.get(instrument_type, ATR_TP_MULTIPLIERS["FOREX"])


def get_rsi_thresholds(timeframe: str) -> tuple:
    """Get RSI thresholds based on timeframe."""
    if timeframe.upper() in ["M1", "M5"]:
        return RSI_OVERBOUGHT_M1, RSI_OVERSOLD_M1, RSI_DIVERGENCE_VETO_THRESHOLD_M1
    else:
        return RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_DIVERGENCE_VETO_THRESHOLD


def get_minimum_risk_reward(timeframe: str = "M1") -> float:
    """Get timeframe-appropriate minimum risk-reward ratio."""
    if timeframe.upper() == "M1":
        return MINIMUM_RISK_REWARD_M1
    else:
        return MINIMUM_RISK_REWARD


def get_volume_threshold(trend: str, adx: float) -> float:
    """
    Get trend-aware volume threshold.

    ✅ FIXED: the moderate-trend check used to match only the bare strings
    "BULLISH"/"BEARISH". Trend labels can also arrive as "STRONG_BULLISH"/
    "STRONG_BEARISH" -- not just from ADX > ADX_STRONG_TREND_THRESHOLD (the
    only case this function itself handled as "strong"), but also from
    divergence-confirmation escalation elsewhere in the pipeline (a trend
    can be labeled STRONG_ on conviction from a confirming divergence even
    when its own ADX is well under ADX_STRONG_TREND_THRESHOLD). A
    STRONG_-labeled trend that didn't come from a high enough ADX to hit
    the first branch fell through the second branch too (exact string
    match only) and silently landed on the least regime-aware threshold
    (WEAK_TREND) -- identical to "no trend at all". Stripping the STRONG_
    prefix before the membership check means any bullish/bearish trend
    label, however it was derived, gets at least the moderate threshold;
    an actual ADX > ADX_STRONG_TREND_THRESHOLD is still required for the
    tighter STRONG_TREND threshold.
    """
    if adx > ADX_STRONG_TREND_THRESHOLD:
        return VOLUME_THRESHOLD_STRONG_TREND
    base_trend = trend.replace("STRONG_", "") if trend else trend
    if base_trend in ["BULLISH", "BEARISH"]:
        return VOLUME_THRESHOLD_MODERATE_TREND
    return VOLUME_THRESHOLD_WEAK_TREND


def get_wick_reversal_ratio(body_pips: float) -> float:
    """Get wick reversal ratio based on candle size."""
    if body_pips < WICK_SMALL_CANDLE_BODY_THRESHOLD:
        return WICK_REVERSAL_RATIO_SMALL
    return WICK_REVERSAL_RATIO_NORMAL


def get_instrument_adx_thresholds(symbol: str) -> tuple:
    """
    ⚠️ SUPERSEDED AND UNCALLED. The live implementation is
    indicators._get_adx_thresholds(), which returns a Dict[str, int]
    ({"trend": ..., "strong_trend": ...}) rather than this tuple. Note
    they are not interchangeable: swapping one for the other would
    silently unpack a dict's KEYS. Labelled rather than deleted.
    """
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        return ADX_THRESHOLDS["XAUUSD"]["trend"], ADX_THRESHOLDS["XAUUSD"]["strong_trend"]
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        return ADX_THRESHOLDS["XAGUSD"]["trend"], ADX_THRESHOLDS["XAGUSD"]["strong_trend"]
    else:
        return ADX_THRESHOLDS["DEFAULT"]["trend"], ADX_THRESHOLDS["DEFAULT"]["strong_trend"]


def get_instrument_volume_multiplier(symbol: str) -> float:
    """Get instrument-appropriate volume multiplier adjustment."""
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        return INSTRUMENT_VOLUME_MULTIPLIER_GOLD
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        return INSTRUMENT_VOLUME_MULTIPLIER_SILVER
    else:
        return INSTRUMENT_VOLUME_MULTIPLIER_DEFAULT


def get_volume_multiplier(volume_ratio: float, timeframe: str = "M1", symbol: str = "XAUUSD") -> float:
    """
    ⚠️ UNCALLED DUPLICATE. calculations._get_volume_multiplier() is the
    live copy and its body is currently IDENTICAL to this one, line for
    line -- which is exactly the state _NORMAL_ATR_RANGES was in before
    one copy was edited and the other silently became a decoy. If you
    change the volume multiplier ladder, change it in calculations.py;
    editing here has no effect on anything.
    """
    is_small_tf = timeframe.upper() in ["M1", "M5"]
    instrument_factor = get_instrument_volume_multiplier(symbol)
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


def check_volatility_protection(symbol: str, atr_pips: float, market_regime: str) -> dict:
    """Instrument-aware volatility protection."""
    symbol_upper = symbol.upper()
    
    base_ranges = _NORMAL_ATR_RANGES.get(symbol_upper)
    if base_ranges is None:
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
        ranges = {
            "min": base_ranges["min"] * multiplier,
            "max": base_ranges["max"] * multiplier,
            "extreme": base_ranges["extreme"] * multiplier
        }
    else:
        ranges = base_ranges
    
    confidence_penalty = 0
    volatility_level = "NORMAL"
    warning = None
    
    if atr_pips > ranges["extreme"]:
        excess_ratio = min(1.0, (atr_pips - ranges["extreme"]) / ranges["extreme"])
        confidence_penalty = 70 + (excess_ratio * 20)
        volatility_level = "EXTREME"
        warning = f"EXTREME VOLATILITY: ATR {atr_pips:.1f} pips exceeds {ranges['extreme']:.1f}"
    elif atr_pips > ranges["max"]:
        excess_ratio = min(1.0, (atr_pips - ranges["max"]) / (ranges["extreme"] - ranges["max"]))
        confidence_penalty = 30 + (excess_ratio * 30)
        volatility_level = "HIGH"
        warning = f"HIGH VOLATILITY: ATR {atr_pips:.1f} pips above normal max {ranges['max']:.1f}"
    elif atr_pips < ranges["min"]:
        deficit_ratio = (ranges["min"] - atr_pips) / ranges["min"]
        confidence_penalty = min(20, deficit_ratio * 15)
        volatility_level = "LOW"
    
    if market_regime == "HIGH_VOLATILITY":
        confidence_penalty += 20
    
    return {
        "safe_to_trade": True,
        "volatility_level": volatility_level,
        "confidence_penalty": min(95, confidence_penalty),
        "reason": f"ATR {atr_pips:.1f} pips within {ranges['min']:.0f}-{ranges['max']:.0f} range" if confidence_penalty == 0 else f"Volatility penalty applied: -{confidence_penalty:.0f}%",
        "warning": warning,
        "atr_pips": round(atr_pips, 1),
        "normal_range": f"{ranges['min']:.0f}-{ranges['max']:.0f}",
        "extreme_threshold": ranges["extreme"]
    }


def get_decision_thresholds() -> dict:
    """Return current decision thresholds for debugging/inspection."""
    return {
        "strong_entry": DECISION_STRONG_ENTRY,
        "entry_with_zone": DECISION_ENTRY_WITH_ZONE,
        "wait": DECISION_WAIT_THRESHOLD,
        "monitor": DECISION_MONITOR_THRESHOLD,
        "min_probability": _MIN_PROBABILITY,
        "max_probability": _MAX_PROBABILITY
    }


# ============================================================
# SECTION 32: PATTERN CONFIG HELPERS
# ============================================================

def get_pattern_freshness_bars(timeframe: str) -> int:
    """Get pattern freshness in bars for a timeframe."""
    return PATTERN_MAX_AGE_BARS.get(timeframe.upper(), 10)


def get_pattern_proximity_pips(timeframe: str) -> float:
    """Get pattern proximity in pips for a timeframe."""
    return PATTERN_PROXIMITY_PIPS.get(timeframe.upper(), 0.0080)


def get_pattern_confidence_threshold(timeframe: str) -> float:
    """Get pattern confidence threshold for a timeframe."""
    return PATTERN_CONFIDENCE_THRESHOLDS.get(timeframe.upper(), 0.50)


def get_pattern_timeframe_weight(timeframe: str) -> float:
    """Get pattern timeframe weight."""
    return PATTERN_TIMEFRAME_WEIGHTS.get(timeframe.upper(), 0.15)


def get_pattern_min_bars_m1(pattern_name: str) -> int:
    """Get M1-specific minimum bars for a pattern type."""
    return PATTERN_MIN_BARS_M1.get(pattern_name.upper(), 20)


def get_pattern_min_size_pips(timeframe: str, pattern_name: str) -> float:
    """Get pattern minimum size in pips."""
    if timeframe.upper() == "M1" and pattern_name.upper() == "RECTANGLE":
        return PATTERN_MIN_SIZE_PIPS.get("RECTANGLE_M1", 0.00005)
    return PATTERN_MIN_SIZE_PIPS.get(pattern_name.upper(), 0.00005)


def get_elliott_wave_recommendation(wave_type: str, current_wave: str) -> dict:
    """Get Elliott Wave recommendation configuration."""
    if wave_type == "impulse":
        return ELLIOTT_WAVE_RECOMMENDATIONS["impulse"].get(current_wave, {"recommendation": "NEUTRAL", "action": "WAIT", "direction": "NEUTRAL", "confidence_bonus": 0})
    elif wave_type == "corrective":
        return ELLIOTT_WAVE_RECOMMENDATIONS["corrective"].get(current_wave, {"recommendation": "NEUTRAL", "action": "WAIT", "direction": "NEUTRAL", "confidence_bonus": 0})
    else:
        return ELLIOTT_WAVE_RECOMMENDATIONS.get(wave_type, {"recommendation": "NEUTRAL", "action": "WAIT", "direction": "NEUTRAL", "confidence_bonus": 0})


# ============================================================
# ✅ NEW: SMC ELITE SETUP - LOT SIZE / RISK CONFIG
# ============================================================
# Dedicated to evaluate_smc_trade_setup()'s market-order suggestion,
# kept separate from monitor_config.py's general FIXED_TRADE_SIZE_USD/
# RISK_PER_TRADE (which drive the bot's regular trade sizing across all
# entries) so the SMC "perfect setup" feature has its own explicit,
# independently-tunable budget rather than silently inheriting whatever
# the general config happens to be set to.
SMC_SETUP_TRADE_SIZE_USD = 200   # margin budget used as calculate_lot_proper()'s target_margin
SMC_SETUP_RISK_PER_TRADE = 0.05  # 5% -> target_risk = $10 on a $200 budget


# ============================================================
# ✅ NEW: BOLLINGER BANDS MEAN-REVERSION SETUP
# ============================================================
# Dedicated to evaluate_bb_mean_reversion_setup()'s market-order
# suggestion. Reuses SMC_SETUP_TRADE_SIZE_USD / SMC_SETUP_RISK_PER_TRADE
# for the $ budget and risk % (same $200 / 5% account-level setting),
# but keeps its own entry/exit geometry constants since BB mean
# reversion is a structurally different setup than SMC (band-to-band,
# not order-block-to-swing-point).
# ============================================================

# Entry: price must be AT or BEYOND the band to count as a "perfect"
# mean-reversion entry (percent_b <= this for BUY, >= 1 - this for SELL).
# 0.0 = price must have touched or pierced the band, not just be near it.
BB_MEAN_REVERSION_MAX_PIERCE_PCT_B = 0.0

# Squeeze bands make poor mean-reversion setups (a squeeze usually
# precedes a breakout, not a reversion) - setups are rejected while
# is_squeeze is True, using the existing BB_SQUEEZE_THRESHOLD.

# Exit target: instead of the exact middle band (unreliable - price
# often stalls just short of touching the mean), TP sits this fraction
# of the band's half-width BEFORE the middle, in the direction of travel.
# "Very close to middle" = 15% of the half-width short of it.
BB_MEAN_REVERSION_EXIT_APPROACH_PCT = 0.15

# SL: band boundary being pierced further, plus a spread-based buffer
# (mirrors SMC_SL_BUFFER_SPREAD_MULT / SMC_SL_MIN_BUFFER_PIPS).
BB_MEAN_REVERSION_SL_BUFFER_SPREAD_MULT = 1.5
BB_MEAN_REVERSION_SL_MIN_BUFFER_PIPS = 2.0

# Minimum acceptable reward:risk - since the target is only the approach
# to the middle band (not the full band width), this is deliberately
# lower than SMC's implicit bar.
BB_MEAN_REVERSION_MIN_RR = 1.2


# ============================================================
# The RSI reversal setup (Fibonacci targets) was removed 2026-09-18: the RSI
# setup is core/rsi_divergence_setup.py -- M1 divergence confirmed by a break
# of structure, stop at the swing, exit at RSI 80/20.


# ============================================================
# ✅ NEW: STOCHASTIC REVERSAL SETUP
# ============================================================
# Mirror of the RSI reversal setup above, for Stochastic + its own
# divergence merge (score_stochastic_indicator_with_divergence).
# ============================================================

STOCH_EXTREME_OVERBOUGHT = 90
STOCH_EXTREME_OVERSOLD = 10

STOCH_REVERSAL_SETUP_MIN_CONFIDENCE = 90

STOCH_REVERSAL_FIB_DEEP = 0.618      # K beyond the EXTREME threshold (90/10)
STOCH_REVERSAL_FIB_NORMAL = 0.5      # K beyond the normal threshold only (80/20)

STOCH_REVERSAL_SL_BUFFER_SPREAD_MULT = 1.5
STOCH_REVERSAL_SL_MIN_BUFFER_PIPS = 2.0

STOCH_REVERSAL_MIN_RR = 1.2


# ============================================================
# ✅ NEW: EMA CROSSOVER SETUP
# ============================================================
# Dedicated to evaluate_ema_crossover_setup(). Uses the EMA_FAST/
# EMA_MEDIUM (9/21) pair already computed elsewhere in the pipeline
# (ema_9/ema_21). Unlike the setups above, this one's exit is a SIGNAL
# (opposite EMA re-cross), not a fixed price - there is no take_profit
# level, so there's no min-RR gate either (reward is open-ended
# trend-following, unknowable up front). What IS gated is entry
# freshness/sanity, so this doesn't fire on a stale, already-extended
# cross.
# ============================================================

# SL sits beyond the slow EMA (the level whose reclaim invalidates the
# cross) plus a spread-based buffer - mirrors the other setups' buffer
# style.
EMA_CROSSOVER_SL_BUFFER_SPREAD_MULT = 1.5
EMA_CROSSOVER_SL_MIN_BUFFER_PIPS = 2.0

# Reject crosses where the resulting SL distance is already more than
# this many ATRs - a late/stale cross in an already-extended move, not
# a fresh, tight-risk trend start.
EMA_CROSSOVER_MAX_SL_ATR_MULT = 2.0


# ============================================================
# ✅ NEW: VOLUME PROFILE / POINT OF CONTROL (POC)
# ============================================================
# Dedicated to calculate_volume_profile() (indicators.py) and
# score_volume_profile_indicator() (asset_analysis.py). Scored as its
# own advisory indicator result (recommendation/score/confidence/
# reason, same shape as every other indicator's merged result) and
# surfaced in the report next to the other indicators, without
# affecting the probability output (which comes from probability_buy/
# probability_sell and the additive chain further down asset_
# analysis.py -- see the removal note near the former location of
# calculate_unified_indicator_score() for why that's a separate,
# non-load-bearing display path).
# ============================================================

VOLUME_PROFILE_NUM_BINS = 24          # price buckets across the lookback window's range
VOLUME_PROFILE_LOOKBACK_BARS = 100    # bars included in the profile
VOLUME_PROFILE_VALUE_AREA_PCT = 0.70  # standard 70% value-area convention

# Scoring: price beyond VAH/VAL is "extended past accepted fair value" -
# score/confidence scale with how far beyond, as a fraction of the
# profile's own range, capped at these bounds.
VOLUME_PROFILE_MAX_SCORE = 25
VOLUME_PROFILE_MIN_SCORE_AT_EDGE = 10
VOLUME_PROFILE_MAX_CONFIDENCE = 90
VOLUME_PROFILE_MIN_CONFIDENCE_AT_EDGE = 50
VOLUME_PROFILE_INSIDE_VA_SCORE = 3    # mild pull-toward-POC score when price is inside the value area
VOLUME_PROFILE_INSIDE_VA_CONFIDENCE = 35

# ✅ NEW: confluence gate for the mean-reversion-style "perfect entry"
# setups (BB mean-reversion, RSI reversal, Stochastic reversal). When
# True, those setups additionally require price to be OUTSIDE the value
# area (beyond VAH for a SELL, beyond VAL for a BUY) to count as
# "perfect" - i.e. the oscillator/band extreme must be confirmed by
# price also trading at a level with little recent volume behind it,
# not just sitting inside the normal, heavily-traded range. If volume
# profile data is unavailable for a given bar, the check is skipped
# (fails open, not closed) rather than blocking the setup on missing data.
VOLUME_PROFILE_REQUIRE_CONFLUENCE = True


# ============================================================
# ✅ NEW: WAVE C / A-B-C CORRECTION + FIBONACCI PROJECTION
# ============================================================
# Dedicated to detect_abc_correction() (indicators.py) and
# score_wave_c_fibonacci_indicator() / evaluate_wave_c_reversal_setup()
# (asset_analysis.py). Built as a standalone A-B-C detector on top of
# the shared swing-point detector — NOT an extension of the existing
# Elliott Wave engine in patterns.py, which wasn't provided and only
# exposes wave labels, not the price points a Fibonacci projection
# needs. See the function docstrings for the full rationale.
# ============================================================

WAVE_C_MIN_RETRACEMENT_B = 0.236   # wave B must retrace at least this much of wave A to count as a valid correction
WAVE_C_MAX_RETRACEMENT_B = 0.886   # beyond this it's not a B-wave retrace, it's a full reversal of wave A
WAVE_C_IDEAL_RETRACEMENT_MIN = 0.50   # "textbook" B retracement zone -> higher confidence read
WAVE_C_IDEAL_RETRACEMENT_MAX = 0.618

WAVE_C_FIB_EQUALITY = 1.0     # wave C = wave A (the single most common outcome)
WAVE_C_FIB_EXTENSION = 1.618  # extended wave C

# "Near the wave C target" zone: entered once price has covered this
# fraction of wave A's length short of the 100% target, through the
# 161.8% extension (with a little overshoot tolerance beyond that).
WAVE_C_ENTRY_ZONE_PCT = 0.15
WAVE_C_OVEREXTENSION_TOLERANCE = 1.2   # beyond fib_extension * this = considered invalidated

# Trade setup (evaluate_wave_c_reversal_setup) geometry
WAVE_C_SETUP_SL_BUFFER_SPREAD_MULT = 1.5
WAVE_C_SETUP_SL_MIN_BUFFER_PIPS = 2.0
WAVE_C_SETUP_MIN_RR = 1.2


# ============================================================
# ✅ NEW: MULTI-GAP FVG + INVERSE FVG (IFVG)
# ============================================================
# Dedicated to detect_all_fvgs() (indicators.py) and
# score_fvg_ifvg_indicator() / evaluate_fvg_ifvg_setup()
# (asset_analysis.py). This runs ALONGSIDE the existing single-nearest-
# FVG logic in get_ict_recommendation() (which uses _detect_fvg() and
# its own width/freshness/volume tier score) rather than replacing it —
# that scoring is already tuned and wired into the ICT component.
# score_fvg_ifvg_indicator() reuses the SAME tier-score formula
# (MIN_FVG_WIDTH_PIPS / FVG_AGE_GRACE_BARS / FVG_AGE_DECAY_BARS /
# FVG_TIER_MAX_WIDTH_PIPS / FVG_TIER_MIN_VOLUME_RATIO /
# FVG_TIER_MAX_VOLUME_RATIO / FVG_WIDTH_SCORE_WEIGHT /
# FVG_FRESHNESS_SCORE_WEIGHT / FVG_VOLUME_SCORE_WEIGHT, all already
# defined in asset_analysis.py) but applies it across ALL active gaps,
# including inverted ones, not just the single nearest.
# ============================================================

FVG_ALL_MAX_GAPS = 8              # max active (unmitigated or inverted) gaps tracked at once
FVG_ALL_LOOKBACK_BARS = 150       # bars scanned for gap formation
FVG_MITIGATION_FULL_THRESHOLD = 0.90   # a wick trading this far into a gap counts it as filled

FVG_IFVG_MIN_TIER_SCORE = 40      # minimum quality tier score (0-100) for a gap/IFVG to drive the merged indicator result

# ✅ NEW: weight for calculate_fvg_ifvg_final_score()'s contribution to
# best_probability, chained the same way pattern/GNN/SMC are (see
# calculate_fvg_ifvg_final_score() in asset_analysis.py). Set to match
# GNN_WEIGHT/SMC_WEIGHT (0.15) rather than PATTERN_WEIGHT (0.20), since
# this indicator only ever considers a single best-scored gap at a time,
# similar granularity to SMC's structural read rather than pattern's
# multi-timeframe aggregate. Tune independently if desired.
# Was 0.15 (up to +15 probability when aligned, -3 when opposed). Cut to 0.05
# on 2026-09-15: on the 111 stored trades with tick paths the FVG agreed with
# 74 of 97 voting trades, yet trades it OPPOSED were right more often (69.6%
# vs 55.4%) and booked +1.09R vs -0.25R. It raised probability on exactly the
# entries that stopped out. Use the gap as an entry LOCATION, not as evidence.
FVG_IFVG_WEIGHT = 0.05

FVG_IFVG_SETUP_SL_BUFFER_SPREAD_MULT = 1.5
FVG_IFVG_SETUP_SL_MIN_BUFFER_PIPS = 2.0
FVG_IFVG_SETUP_MIN_RR = 1.2


# ============================================================
# ✅ NEW: SUPPORT/RESISTANCE <-> VOLUME PROFILE CONFLUENCE
# ============================================================
# Dedicated to score_sr_volume_profile_confluence() (asset_analysis.py).
# Purely informational cross-check between the pivot-based S/R levels
# (calculate_pivot_levels — 100% price-formula derived, no volume input
# at all) and the volume-profile levels (POC/VAH/VAL — empirically
# derived from where volume actually transacted). Does NOT touch
# sr_data's own score/recommendation -- this only adds a "was this pivot
# level actually confirmed by real transacted volume nearby" flag per
# level, surfaced in the report.
# ============================================================
SR_VOLUME_CONFLUENCE_TOLERANCE_PIPS = 8.0


# ============================================================
# ✅ NEW: SUPPLY/DEMAND ZONE <-> VOLUME PROFILE CONFLUENCE
# ============================================================
# Dedicated to score_sd_volume_profile_confluence() (asset_analysis.py).
# Same pattern as the S/R cross-check above: _detect_supply_demand_zone()
# grades zones A-E purely on touch count (how many times price has
# bounced off the swing level) - zero volume input. This flags whether
# the active zone also has real transacted-volume backing (POC/VAH/VAL)
# nearby, WITHOUT touching zone_grade/zone_multiplier/zone_score.
# ============================================================
SD_VOLUME_CONFLUENCE_TOLERANCE_PIPS = 8.0


# ============================================================
# ✅ NEW: SMC ORDER BLOCK <-> VOLUME PROFILE CONFLUENCE
# ============================================================
# Dedicated to score_ob_volume_profile_confluence() (asset_analysis.py).
# Same pattern again: _detect_order_blocks() judges a block purely by
# candle range vs. average range (a displacement move) - zero volume-
# node input on whether that candle actually happened at a price level
# with real transacted volume behind it. Flags confluence WITHOUT
# touching evaluate_smc_trade_setup()'s own entry/SL logic, which
# already uses order blocks directly.
# ============================================================
OB_VOLUME_CONFLUENCE_TOLERANCE_PIPS = 8.0


# ============================================================
# ✅ NEW: LIQUIDITY SWEEP <-> VOLUME PROFILE CONFLUENCE
# ============================================================
# Dedicated to score_sweep_volume_profile_confluence() (asset_analysis.py).
# _detect_liquidity_sweep() judges a stop-hunt purely by wick-beyond-
# prior-swing + close-back-inside - zero volume-node input on whether
# the swept level actually had real resting size behind it. A sweep
# near VAH/VAL is a much more convincing "real stops got taken out" read
# than one in a thin, low-volume area. Does NOT touch evaluate_smc_
# trade_setup()'s own use of the sweep level for SL placement.
# ============================================================
SWEEP_VOLUME_CONFLUENCE_TOLERANCE_PIPS = 8.0


# ============================================================
# ✅ NEW: REMAINING VOLUME PROFILE CONFLUENCE CANDIDATES
# ============================================================
# Three gaps identified when auditing full Volume Profile coverage:
# 1. EMA crossover (trend/breakout setup) never got a confluence check
#    at all - and the mean-reversion "outside value area = confirms an
#    extreme" logic is actually INVERTED for a breakout setup: outside
#    value area there means confirmed momentum, not an extreme to fade.
# 2. Liquidity pools (order_flow_forensics.py's equal-highs/equal-lows)
#    never got the same "does this level have real volume behind it"
#    check already applied to SMC order blocks and sweeps.
# 3. Wyckoff phase never got any volume-profile cross-check.
# All three are informational only - none of them gate entry.
# ============================================================
LIQUIDITY_POOL_VOLUME_CONFLUENCE_TOLERANCE_PIPS = 8.0
WYCKOFF_VOLUME_CONFLUENCE_TOLERANCE_PIPS = 10.0


# ============================================================
# ✅ NEW: PATTERN / WAVE ANALYSIS TIMEFRAME SCOPE
# ============================================================
# analyze_patterns_multi_timeframe() used to unconditionally fetch
# (mt5.copy_rates_from_pos, 500 bars each - real broker round-trips)
# and run full pattern + Elliott Wave recognition on EVERY timeframe in
# PATTERN_TIMEFRAMES (M1/M5/M15/M30/H1), on every single analysis call
# - regardless of which one timeframe was actually being traded. That's
# 5x the IO and 5x the CPU for timeframes nothing downstream used.
#
# When True, pattern/wave analysis is scoped to ONLY the current
# timeframe being traded (whatever `timeframe` is passed into
# analyze_institutional_signal(), M1 by default) - not the full 5. Set
# False to restore full multi-timeframe pattern analysis if genuinely
# needed later.
#
# ✅ REMOVED: PATTERN_ANALYSIS_CONFIRMATION_TF ("H1" companion fetch).
# It was imported into asset_analysis.py but never actually referenced
# anywhere in that file - multi_tf_rates was always built as just
# {timeframe: rates} regardless of this constant, so it was dead
# config that didn't match its own docstring. Per requirements, pattern
# and Elliott Wave analysis must calculate and display ONLY the current
# timeframe (default M1) with nothing else fetched or computed - so
# this is now removed rather than wired up. wave_lattice.py stays
# inert under current-TF-only, as it did before too (the H1 fetch was
# never actually happening).
PATTERN_ANALYSIS_CURRENT_TF_ONLY = True


# ============================================================
# ✅ NEW: RISK MECHANICS
# ============================================================

# --- Absolute R:R floor ---
# Independent of best_probability -- probability is the single least
# reliable number in this whole pipeline (it's a MODEL estimate;
# reward-vs-risk is a MEASURED fact once SL/TP are set), so a trade
# should never be taken below this R:R no matter how high the
# estimated probability reads. This is the margin of safety against
# the probability estimate simply being wrong.
# ✅ FIXED: was 1.2, looser than MINIMUM_RISK_REWARD/MINIMUM_RISK_
# REWARD_M1 (both 2.0, used by calculate_atr_based_tp when TP levels
# are first set) -- two different thresholds for the same concept at
# two different pipeline stages. Explicit directive is a 1:2 minimum;
# now matches exactly, so a degraded R:R (e.g. from a later SL/TP
# adjustment) can't slip through this looser floor after already
# being held to the stricter standard at TP-calculation time.
# 1.2 since 2026-09-17 with MINIMUM_RISK_REWARD (operator decision).
MIN_ABSOLUTE_RISK_REWARD = 1.2

# --- Hard disagreement flag ---
# When two INDEPENDENT, high-conviction subsystems (SMC structure and
# Wyckoff phase) flatly contradict each other -- not just lean
# different ways, but one reads a confirmed BUY and the other a
# confirmed SELL -- that disagreement is itself information. Folding
# it into the same weighted average as everything else would let it
# get quietly smoothed into a middling score that LOOKS like ordinary
# uncertainty instead of what it actually is: two well-attested,
# independent reads of the same chart flatly disagreeing. This applies
# a real (but moderate -- not disqualifying on its own) probability
# penalty specifically so the disagreement can't get averaged away by
# the rest of an otherwise-agreeing confluence chain, on top of always
# being surfaced explicitly (see hard_disagreement in the output).
HARD_DISAGREEMENT_PROBABILITY_PENALTY = -15.0


# ============================================================
# END OF UNIFIED CONFIG
# ============================================================

# ============================================================
# CANDLESTICK BAR SELECTION  (Phase 2/6, defect D-07)
# ============================================================
# True  -> candlestick evidence is read from the last CLOSED bar.
# False -> legacy behaviour: read from rates[-1], the forming bar.
#
# The forming bar's OHLC is still changing, so a pattern read from it is
# provisional evidence being consumed as settled fact. More importantly
# it makes deterministic replay impossible: replaying history, rates[-1]
# is a completed bar, so the same code sees more than it saw live and
# every backtest built on it is quietly optimistic.
#
# Left as a flag rather than hard-coded so the change can be reverted
# without a code edit if live A/B shows the forming bar was carrying
# real signal. Phase 6 replay is the test that settles it.
CANDLESTICK_USE_CLOSED_BAR = True


# ============================================================
# TP3 CEILING  (Phase 2, defect D-11)
# ============================================================
# TP3 used a hardcoded `min(tp3_pips, 50)`. On instruments whose targets
# exceed 50 pips that ceiling landed BELOW TP1 and TP2 and inverted the
# ladder. The cap is now the larger of a floor constant and an ATR
# multiple, so it scales with the instrument the way every other TP
# input already does.
TP3_MAX_PIPS = 50
TP3_ATR_CAP_MULTIPLIER = 3.0

# ============================================================
# SPREAD-AWARE RISK:REWARD  (Phase 2, defect D-12)
# ============================================================
# TP1 is floored at `spread_pips * 2 + 1`, so on a wide-spread symbol the
# target is set BY THE SPREAD rather than by structure. That inflates the
# reported R:R exactly when trading conditions are worst:
#
#   XAGUSD 2026-09-01, spread 40p -> TP1 forced to 81p, SL 32.8p,
#   reported R:R 1:2.47, which cleared the 1:2.0 floor. Widen the spread
#   further and the reported R:R IMPROVES, while the trade gets worse.
#
# True  -> the absolute R:R floor is tested against reward NET of spread,
#          which is what the trade can actually realise.
# False -> legacy gross behaviour.
#
# This changes which trades qualify on wide-spread instruments, so it is
# a flag rather than a silent edit. Net is the honest measure; leave it
# on unless a live A/B says otherwise.
RISK_REWARD_NET_OF_SPREAD = True


# ============================================================
# WICK PATTERN CONFIRMATION  (defect D-15)
# ============================================================
# A rejection wick that ALSO closes against the rejected direction is
# the stronger version of the same signal, so the score is multiplied
# rather than the direction being flipped. 1.0 disables the modifier.
CANDLE_WICK_CONFIRMED_MULT = 1.25


# ============================================================
# EXPECTED VALUE: GATE, NOT EVIDENCE  (defect D-18)
# ============================================================
# EV = f(probability, reward, risk). Feeding it back into probability
# is double-counting probability against itself, and it formed a closed
# loop: high probability -> high EV -> higher probability, with nothing
# external validating it. Worse, reward_pips is TP1, which is floored at
# spread*2+1 -- so a wider spread inflated EV, which inflated
# probability.
#
# EXPECTED_VALUE_FEEDS_PROBABILITY = True restores the legacy loop for
# A/B comparison. Leave it False.
EXPECTED_VALUE_FEEDS_PROBABILITY = False

# With EV out of the chain it needs somewhere real to act. A trade whose
# expectancy is negative GIVEN the system's own estimate is not a trade.
EXPECTED_VALUE_IS_A_GATE = True
EXPECTED_VALUE_MIN_PIPS = 0.0