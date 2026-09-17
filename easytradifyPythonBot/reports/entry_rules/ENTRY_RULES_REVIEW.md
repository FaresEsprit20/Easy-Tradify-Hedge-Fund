# Entry rules review and entry foundation v2

*2026-09-17. Every check between a live analysis and an order, what was wrong with it, what changed, and how
each rule now earns its place. Code: `core/entry_engine.py`, `core/veto_engine.py`, `core/asset_analysis.py`,
`core/strategy_groups.py`, `ai/entry_rule_evidence.py`. Tests: `tests/test_entry_rule_table.py`,
`tests/test_entry_rule_evidence.py`.*

## 1. Why nothing traded

Since yesterday the monitor analysed the target markets all day and opened no trade. Of the 813 setups it
declined (`skipped_setups`):

| first rule that said no | setups | inside the 75–83 probability band |
|---|---|---|
| NO_POTENTIAL (signals + candle age + a probability bar) | 543 | 69 |
| WAITING_DISCOUNT (price not back at a zone) | 253 | 138 |
| INVALID_ZONE | 11 | 5 |
| POOR_DISCOUNT | 6 | 3 |

About 35 checks sit between an analysis and an order, all in series. Several of them checked the same
thing more than once with different numbers, and one checked something that no longer exists.

The monitor itself also analysed far less than it appeared to (`logs/hybrid_monitor.log`, 2026-09-17):

- **It froze for hours.** Every thread, including the once-a-minute health update, went silent at 05:29–06:07,
  06:12–07:56, 08:11–10:56, 11:26–12:48 and 13:05–14:23. The machine was awake. The likely cause is the
  console window's QuickEdit mode: a click in the window pauses output, and every thread that prints blocks
  until a key is pressed. Fixed: `core/console_safe.disable_quick_edit()` runs when each service starts.
- **The 2-hour refresh emptied the watch list.** It waited 20 s for about 35 analyses. At 14:24 it logged
  "0/12 chunks finished", then "No symbols above 65% confidence". Fixed: it now waits 240 s, and a symbol that
  did not report in time keeps its place.
- **Only the top three symbols were ever checked for entry.** Each 5-second step took symbols in confidence
  order, and a check takes longer than the 5-second cooldown. The same three were therefore due again every
  step. Fixed: the least recently checked symbols go first.
- **At 14:49–14:50 the monitor and the execution controller were shut down** by a console signal (not a
  crash) and did not come back.

## 2. The whole chain, in order

| # | where | rule | what it checks | before | now |
|---|---|---|---|---|---|
| 1 | analysis | direction | BUY or SELL from the analysis | — | unchanged |
| 2 | strategy groups | probability | best group score + context | hour-of-day penalty −8 to −28 points (broker hours 0, 19–23) | **hour penalty recorded, not applied** (no session rules) |
| 3 | entry engine | zone | supply/demand zone, grade A–D | block | block (measured, see §5) |
| 4 | entry engine | signals | golden signals ≥ 1 | ≥1 signal **and** probability ≥45 **and** candle 20–40% formed | **signal count only** |
| 5 | entry engine | probability | floor ≤ p ≤ 83 | band floor 25; a second floor 75 after the engine; tier bar 45 | **one rule: 75–83**, floor passed by the analysis |
| 6 | entry engine | discount | price back at the zone | block | block (measured, see §5) |
| 7 | entry engine | discount quality | zone on the trade's side, score ≥30 | block | block (measured) |
| 8 | entry engine | confirmation | last closed M1 bar confirms the side | checked only at the zone | **checked on every decision** |
| 9 | entry engine | timing | tick micro-structure confidence ≥65 | ×0.7 before the candle was 75% formed, ×0.5 on wide spread | **no candle or spread penalty** |
| 10 | entry engine | safety | spread valid **and** candle ≥75% formed **and** ≥40% | block | **removed** (spread is rule 16; candle age judges nothing) |
| 11 | veto engine | cooldown | 60 s after a session/news/weekend/holiday veto | block | unchanged; a recorded-only news veto no longer starts it |
| 12 | veto engine | session | market closed, not a trading day, close imminent | block | unchanged (availability, not a session filter) |
| 13 | veto engine | news | high-impact news near | block | **recorded, not blocking** (no news rules) |
| 14 | veto engine | choppy (ADX) | mode `off` | off | unchanged |
| 15 | veto engine | extreme volatility, RSI divergence, wick reversal, low volume | market conditions | block | unchanged (next to be measured) |
| 16 | veto engine | high spread | spread ≤ the symbol's maximum | block | unchanged: **the** spread rule |
| 17 | veto engine | candle too young | first 5–15% of the minute | block | **recorded, not blocking** |
| 18 | analysis | probability floor after the engine | p ≥ 75 | block | **removed**: it was rule 5 again |
| 19 | analysis | expected value | EV ≥ 0 pips | block | unchanged; see open item B |
| 20 | analysis | R:R | net-of-spread R:R ≥ 2.0 | block | unchanged |
| 21 | symbolic gate | trade arithmetic | stop ≥1 pip, spread ≤34% of stop, target > spread, lot > 0 | block | unchanged |
| 22 | monitor | top symbols | probability ≥65 at the 2-hour refresh | filter | unchanged; see open item C |
| 23 | monitor | entry check | `should_enter` and probability ≥65 | block | unchanged (inert: the rule table's 75 binds first) |
| 24 | monitor/executor | max trades, SL/TP present, SL/TP ≥1 pip, max spread 30 | execution safety | block | unchanged |

## 3. What was wrong

**A. The candle's age was checked four times and judged nothing.** Since 2026-09-15 every reading comes from
closed bars (`core/closed_bars.py`); within a minute only the live price moves. The four checks (tier table
20–40%, timing ×0.7 before 75%, safety ≥75% and ≥40%, the veto's 5–15%) were written when the analysis read
the half-formed bar. After that fix they only refused setups on the clock. The monitor analyses early in
the minute (median 8% at NO_POTENTIAL), so the ×0.7 penalty alone made timing impossible in the first
45 seconds of every minute, and the safety check left a window of about 15 seconds per minute.

**B. The probability was checked four times, with four numbers.** Tier table 45, engine band 25–83, the
floor after the engine 75, the monitor 65. The one that bound was 75 after the engine, so a setup at 60%
walked through the whole engine, was labelled by some later rule, and was then refused by a number the
engine never saw. Now it is checked once, at the scale the probability is on.

**C. The spread was checked five times.** Timing ×0.5, the engine's safety check, the high-spread veto, the
symbolic spread-to-stop check, and the monitor's filter. The veto (a cap) and the symbolic gate (cost against
the stop) are different questions and stay; the two copies inside the engine are gone.

**D. The engine stopped at the first rule that failed.** A setup stopped at WAITING_DISCOUNT never said
whether its confirmation or timing would have held. No rule could be measured on the setups another rule
had stopped, which is why this review had to replay history to answer anything.

**E. Two rules broke the operator's "no session or news rules".** The hour-of-day penalty inside the
probability and the news veto. Both are now recorded (`strategy_groups.context` with `counts: false`,
`vetos.checks.news_veto`) and no longer decide.

**F. 40% of live setups carry probability 5.0.** That is the clamp floor of the strategy-group score. The
context includes a trading-cost penalty of `100 × cost_r / (1 + target_r)` points. Under the original sizing
the EURUSD stop is about 1 pip, so commission alone is about 0.6R and the penalty pushes the score to the
floor. The probability rule is therefore refusing these setups for their cost, which is correct arithmetic,
but it sits in the probability rather than in a cost rule.

## 4. Entry foundation v2: one rule table

- **Every rule runs on every decision.** `entry_analysis.rules` holds, per rule: passed (true, false, or
  `null` when not measurable), mode, value, threshold, and why. `entry_analysis.blocked_by` lists every
  blocking failure in order.
- **Two modes.** `block`: a failure stops the entry. `observe`: evaluated and recorded, never blocks. Set in
  `ENTRY_RULE_MODES` (`core/asset_analysis_config.py`). A missing or unknown mode blocks.
- **The status keeps its meaning.** The first blocking rule names `entry_status` (INVALID_ZONE,
  NO_POTENTIAL, …). An entry reads `CONFIRMED_DISCOUNT` when discount and confirmation held, or
  `RULES_PASSED` when an observed rule failed.
- **Recorded everywhere the snapshot goes.** The decision log (whole snapshot every minute, with each rule's
  pass flag in the query codes `ea_r_*_p`), trade records (`analysis_at_open`, the audit's
  `entry.rules_passed` / `entry.blocked_by`), and the price-evolution points.
- **A rule changes mode only on evidence** (`ai/entry_rule_evidence.py`). The rule was written before any
  per-rule result was read:
  - a rule blocks only when its passed decisions beat its failed decisions at the primary geometry in both
    halves of the data, with at least 100 decisions in every group, among decisions inside the probability
    band;
  - anything else is `observe`: a rule that does not help, or one too rare to show that it helps;
  - an observed rule keeps being measured on every live decision and can earn `block` back;
  - the same module reads the history replay and the live decision log, so the weekly verdict (plan v5,
    phase 3) uses the same test.

## 5. Evidence

*History replay of this engine: 17 markets, 107,622 decisions (one every 15 minutes, June 9 – September 15).
Results are on true bid/ask M1 bars with commission. Primary geometry: stop 1× ATR(M15), target 1R. Earlier half
vs later half, split at July 30. Every number is in `ENTRY_RULES_HISTORY.md` in this folder.*

**How many winning decisions the entry let through.** With every rule blocking (the old engine): **2 of 45,474**.
With the verdict modes: **1,691 of 45,474**.

**Verdict per rule** (decisions inside the probability band; lift = net R of passed minus failed, earlier / later
half):

| rule | lift | mode now | note |
|---|---|---|---|
| probability | +0.110 / +0.078 | block | lifts the opposite side as much (+0.109 / +0.145): it screens out costly trades, not the wrong direction |
| discount_quality | +0.050 / +0.049 | block | zone on the trade's side |
| discount | −0.104 / −0.147 | observe | waiting for price to come back to the zone **hurt** in both halves |
| signals | −0.011 / −0.024 | observe | |
| confirmation | +0.013 / −0.031 | observe | |
| zone | unproven (4 and 7 failures) | observe | |
| timing | not measurable on bars | observe | measured live from the decision log |

**The entries these modes take, later half:** 1,892 trades.

| geometry | traded side | same trades, opposite side |
|---|---|---|
| stop 1× ATR(M15), 1R | 45.2% won, −0.254R | 47.5%, −0.207R |
| stop 1× ATR(H1), 1R | 47.4%, −0.104R | 45.9%, −0.133R |
| the engine's own levels (stop ≈ 1 pip, target ≥ 8 pips) | 18.6%, −0.523R | — |

No geometry meets the pass line (65% won, +0.20R).

**Per winning group, later half,** with each group's own verdict:

| group | trades | won | net R | opposite side |
|---|---|---|---|---|
| TREND | 172 | 51.7% | −0.090R | 43.6% |
| MEAN_REVERSION | 17 | 64.7% | +0.070R | too few to judge |
| WAVE | 233 | 47.6% | −0.261R | |
| ORDER_FLOW | 105 | 45.7% | −0.225R | |
| CROSS_ASSET | 756 | 43.6% | −0.311R | |
| MOMENTUM | 5,194 | 40.4% | −0.374R | |

## 5b. Each strategy trades its own setup (operator, 2026-09-17)

One entry for every strategy was wrong: SMC, mean reversion and waves each have their own idea of where and when
to enter. The analysis already computed a trade setup per strategy (entry, structural stop, target, and a lot
shrunk to the $4 budget), but only as advice. Now (`core/strategy_setups.py`):

- **The winning group trades its own setup:**
  - SMC: SMC trade setup, then FVG/IFVG retest
  - MEAN_REVERSION: Bollinger band extreme, then RSI divergence reversal
  - MOMENTUM: stochastic divergence reversal
  - TREND: fresh EMA crossover
  - WAVE: wave C reversal
- **For those groups**, the `setup` rule decides. Zone, discount, confirmation, signals and timing are recorded
  but do not block. The probability band still applies.
- **The setup's stop and target are the trade.** The lot starts from the $200 trade size and only shrinks, so the
  loss at the stop stays within $4. `core/execution.execute_trade(keep_stop=True)` keeps that stop; before this,
  the executor pulled any wider stop back to about 1 pip.
- **The target is the strategy's own** (operator): SMC's next opposing structure swing, mean reversion's middle
  band or Fibonacci retracement, wave C's wave B pivot, FVG/IFVG's nearest swing.
  - It is kept only if it pays at least 1:1.2 after the spread. A setup that can't is not traded, and its
    target is never stretched to reach the minimum.
  - Only TREND's EMA crossover has no price target (it exits on a crossover signal the monitor does not manage
    yet). Its target sits on the 1:1.2 floor.
- **STRUCTURE, ORDER_FLOW and CROSS_ASSET** have no setup of their own. The rule table above and the account
  levels decide for them.
- **SMC and STRUCTURE compete in the auction again.** They had been excluded as measuring at the base rate, but
  every other group measures at that same rate on this replay.
- **Minimum R:R is 1:1.2 everywhere** (operator). At 1:2 it never rejected a trade; it only pushed targets out.
  For groups without a setup, the target now sits on the floor itself: `TP1_FOLLOWS_RR_FLOOR` makes the target
  1.2 × stop + spread. The 8-pip minimum used to set FX targets at 4–8R against 1–2 pip stops. A floating-point
  miss that would have refused about 6% of targets placed exactly on the floor is fixed in
  `RiskReward.passes_floor`.

The setups were not captured by this replay, so they have no history numbers yet. The decision log records
every setup, valid or not, with its tick result 4 hours later. A replay that captures them is the next
measurement.

## 6. Open items

- **A. The rules not measurable on history.** Timing and the tick-based golden signals (absorption, momentum
  burst, volume imbalance) need live ticks. They are measured from the decision log as results arrive
  (`decision_outcomes`, 4 hours after each decision).
- **B. The EV gate — fixed 2026-09-17.** Found on a live SPY.NYSE entry that logged `[EV GATE] SKIP` and still
  executed. Two defects:
  - the gate changed only local variables, never `entry_analysis.should_enter`, which the monitor executes from,
    so it had never blocked a trade;
  - it judged EV on the additive-chain probability (19% on that bar) and the account geometry.
  It now judges EV on the probability the decision used and the geometry the order carries, and a negative EV
  blocks. At probability ≥ 75 and R:R ≥ 1:1.2 that is almost never negative. Live after the next restart.
- **C. The monitor's symbol list only ever rises.** Reanalysis replaces a symbol's confidence only when it
  is higher, and the full refresh runs every 2 hours. A symbol that fell below 65 keeps being checked, and
  one that rose between refreshes waits for the 5-minute batch.
- **D. The vetoes still stop at the first one that fires.** Checks after it are recorded as not evaluated,
  so the vetoes cannot yet be measured the way the entry rules now are.
- **E. The cost sits inside the probability** (item F above) instead of being its own rule.
