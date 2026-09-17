# Strategic plan v5: use the live data to reach the target

*2026-09-17. Follows `strategic_plan_v4.md`. Every test on price history (Gate 1, 1b, 1d–1i) failed, and the
positive control proved those tests can find a real edge. What is left is data history cannot give: what
happens live, during real trades, and the operator's own decisions. This plan says how to use it.*

## Target and fixed rules (unchanged)
- **Target:** at least 65% of trades won **and** at least +0.20R net per trade, on data the rule was not built on, for every category.
- **Scope:** M1 only (M1 scalp or M1 precision entry per category). FX, metals, stock indices, oil. No crypto. No session or news rules.
- **Risk:** $200 trade size, 2% risk = $4 fixed; the lot shrinks to keep the $4 (original sizing, no market stop).
- **Account:** demo only until a rule passes Phase 5.

## The new data: what it is, and what it is not

| Source | What it stores | How much | What history cannot give |
|---|---|---|---|
| `trades.analysis_at_open` | the full analysis at the moment of entry | 1 per trade | real spread and account state at entry |
| `trades.price_evolution` | full analysis + live order flow + stop state | every 60 s while a trade is open | how the analysis and order flow move **during** a real trade |
| `trades.analysis_at_close` + `close_data` | analysis at exit, real fill, commission, slippage | 1 per trade | real costs |
| `skipped_setups` | decisions that reached the strategy groups and did **not** enter (probability, group scores, stop/target, skip reason) | 1 per symbol per minute (384 on 2026-09-17, outcomes not filled yet) | what the gates stop |
| engine_v2 shadow journal | each category's **own** setup (entry, stop, targets, exits), no orders | every M15 close (not running yet) | per-category evidence without risking money |
| depth recorder | broker order book | every second | nothing useful: the book is a fixed size ladder (gold skew only) |
| operator's trades (Gate 2) | your own M1 entries and reasons | none yet | your judgment, the one input never tested |

What it can and cannot do:
- It **can** measure the truth fast: real costs, real fills, and forward (future) results for any rule.
- It **can** add new information: live order flow during trades, and your decisions.
- It **cannot** turn the same readings into an edge. Minute snapshots of one trade share one result, so for "which entries win" they count as **one** sample, not sixty.

## Rules for using live data (non-negotiable)
1. **One result per decision.** Consecutive minutes with the same side and group are one decision episode.
2. **Never mix engine versions.** Every record carries the engine version and config. The sizing change of 2026-09-17 starts a new era; older records are compared, never pooled.
3. **No leakage.** Features come only from the snapshot at decision time. Results come only from ticks after it. Profit, close and outcome fields are never features.
4. **Decide the test before looking.** Each test is written down first, run on later weeks than it was built on, and compared with the same rule at random times and random sides. The planted-edge positive control runs with every report.
5. **Same pass line as v4.** At least 300 out-of-sample trades, at least 65% won, at least +0.20R net, t ≥ 2, and the control fails. Checked per category.
6. **Target markets only.** The monitor also scans stock CFDs (CSCO.NAS, MCD.NYSE, SPY.NYSE…); they are kept out of the target dataset.

## Phase 0 — Make every record usable (days 1–3)
- **0.1 Version stamp** on every analysis, trade and skipped setup:
  - git commit and schema versions (codec 3, audit 2);
  - `USE_MARKET_STOP`, entry floor, strategy-groups version, calibrated model version and mode.
- **0.2 Prove the pipeline on the next real trade:** MT5 deal → Mongo trade → price points every 60 s → close record, all with the version stamp.
  - A daily check compares closed MT5 deals with Mongo trades.
  - Today the monitor shows 0 Mongo saves since Sept 16, and the 39 trades of Sept 11–15 are not in Mongo.
- **0.3 Import MT5 deal history** (the 39 trades, 18% won, −$2.63 per trade) as `source: mt5_history`: results and costs only, no snapshots.
- **0.4 Keep the alignment tests green** (`tests/test_price_evolution_alignment.py`, `tests/test_monitor_audit_alignment.py`). Rerun the live check after any engine change.

**Done when:** one live trade is verified end to end in Mongo, and the daily check has run for 3 days.

## Phase 1 — Log every decision, not only trades (week 1)
- **1.1 Decision log.** For each target-market symbol every minute, entered or not, store the **whole** analysis snapshot (lossless, about 21 KB with order flow) plus the version stamp.
  - About 10–15 symbols × 1,440 minutes ≈ 15,000–20,000 decisions per day, about 300–420 MB per day.
  - This replaces trade count as the bottleneck: thousands of decisions per week instead of dozens of trades.
- **1.2 Live-only inputs at the decision:** tick order flow (the last 15 minutes), live spread, and later the spread at the fill.
- **1.3 Start the engine_v2 shadow run** (`python -m engine_v2.run.shadow`). Each category proposes its own setup live with no orders, so every category collects its own evidence.

**Done when:** 7 days of continuous decision log with under 1% gaps.

## Phase 2 — Result factory (weeks 1–2)
- **2.1 Daily job:** for every logged decision, the result on real MT5 ticks (true bid/ask, commission, $4 risk, lot follows):
  - the engine's own proposed trade (its stop and target, original sizing);
  - a fixed geometry grid per arena, on both sides (the other side is the random-side control): M1 scalp (stop 1× and 2× ATR M1, 1× ATR M5; target 0.5, 1, 2R) and M1 precision (stop 1× ATR M15 or 1× ATR H1; target 1, 2R);
  - the path: best and worst excursion in R after 5, 15, 60 and 240 minutes.
- **2.2 Declined setups are scored through the decision log.** Every declined setup is also a decision with its whole snapshot. `ai/skipped_setup_outcomes.py` is not scheduled: it caches 8 hours of ticks to disk per setup, which would fill the disk within days.
- **2.3 Keep results in their own collection** (`decision_outcomes`), never inside a snapshot.

**Done when:** results exist for at least 95% of decisions older than 4 hours, and 20 are checked by hand against MT5 ticks.

## Phase 3 — Weekly verdict (every Monday, from week 2)
- **3.1 Report on last week's decisions only** (future data for every rule), with the random-time and random-side controls plus the planted-edge control.
  - Slices: per category (v1 winner group and engine_v2 category setups) × market class × geometry.
  - Numbers per slice: count, % won, net R, t.
- **3.2 Promotion:** a slice that passes the pass line on **two consecutive** out-of-sample weeks goes to Phase 5.
- **3.3 Fixed slice list,** corrected for the number of slices tested. No slice is added after the week starts.

## Phase 4 — The five questions only live data can answer (weeks 2–8)
Each one is written down before it runs and has its own control.

| # | Question | Data | What a "yes" gives |
|---|---|---|---|
| Q1 | Does live order flow at the decision separate the engine's winners from its losers? | decision log + tick order flow | an entry filter (prior is low: history showed very little information in ticks) |
| Q2 | Does the analysis turning **during** a trade predict the stop? (probability drop, winning group flips, a veto starts firing, order flow turns against) | `price_evolution` every 60 s + ticks | an exit rule that cuts losses, measured as net R, not win rate |
| Q3 | Do the gates (vetoes, probability floor, discount, timing) remove more winners than losers? | `skipped_setups` + results | keep or remove each gate on evidence |
| Q4 | Do **your** M1 entries beat the engine and the random control on the same bars? Which snapshot fields separate them? | 20–30 of your trades encoded as decisions | the rule candidates most likely to reach 65% |
| Q5 | Do real spread, slippage and commission match what the analysis assumed? | `close_data` vs snapshots | correct net R for every other verdict |

## Phase 5 — Build and prove (only after a pass)
- **5.1 Freeze the rule** (code and config version). Shadow-log its would-be trades until 300 trades: it must still pass.
- **5.2 Run it on demo** for 300 trades: it must still pass after real costs.
- **5.3 Real money** only after 5.2, at the same $4 risk.

## Stop rule
Stop and return the decision to the operator if, after 8 weeks of decision logs (about 1 million decisions), both hold:
- no pre-written slice has passed;
- live order flow (Q1) and mid-trade signals (Q2) show no out-of-sample lift over their controls.

Then the target cannot be reached with this data, and the choice is Gate 2 (your method), the timeframe, or the target.

## What to expect, honestly
- **Most likely gains:** smaller losses from exits (Q2), removing gates that block winners (Q3), and correct cost numbers (Q5). These raise net R but do not by themselves reach 65% won.
- **Real chances of an entry edge:** new information — live order flow (Q1) and your own decisions (Q4).

## What the operator needs to do
- **Keep the demo monitor running.** It is running (restarted 2026-09-17).
- **Approve Phases 0–2.** They change monitor code: version stamp, decision log, daily result job.
- **Send 20–30 of your M1 trades** for Q4: market, time, direction, entry, stop, target, and why.

## Status

| phase | status |
|---|---|
| 0 Make records usable | **BUILT 2026-09-17, active after restart.** Version stamp `core/engine_version.py` on trades, price points, close records, skipped setups and decisions (fingerprint = code + config; `engine_versions` collection). Reconciliation `ai/data_reconciliation.py`: all 39 closed MT5 trades (Sept 11–15) were missing from Mongo; imported into `mt5_history_trades` (7 won, −$102.52). Codec and monitor audit aligned and tested. |
| 1 Decision log | **BUILT 2026-09-17, active after restart.** `core/decision_log.py` hooked into `analyze_institutional_signal`: whole snapshot per symbol per minute (decodes exactly), live order flow over 15 min, engine stamp; target markets only. Verified live on EURUSD (21 KB per decision). engine_v2 shadow added to `scripts/start_services.bat`. |
| 2 Result factory | **BUILT 2026-09-17, active after restart.** `ai/decision_outcomes.py`: engine trade, 26-geometry grid on both sides, path MFE/MAE, true bid/ask + commission, entry after the decision, no Market Watch changes. Verified on real EURUSD ticks. `ai/data_jobs.py` runs it every 15 min, plus the daily reconciliation and history import. |
| Entry foundation v2 (operator, 2026-09-17) | **LIVE since 16:49 UTC (engine 5cd813c757a3).** Evidence and verdict: 107,622 replayed decisions; all rules blocking allowed 2 of 45,474 winning decisions, the verdict modes 1,691 (probability + zone side block). Those entries lost on history (45% won, −0.25R at M15 1R; the probability rule screens cost, not direction). Since then: each winning strategy group trades its own setup (`core/strategy_setups.py`, setup stop kept, lot ≤ $200 lot and ≤ $4 risk), SMC/STRUCTURE compete, R:R minimum 1:1.2, monitor freeze/refresh/rotation fixed. Nothing traded because about 35 checks ran in series, several duplicated with different numbers: candle age ×4 (judging nothing since the closed-bar fix), probability ×4 (45 / 25–83 / 75 / 65), spread ×5. `core/entry_engine.py` is now one rule table: every rule on every decision, `entry_analysis.rules` + `blocked_by`, block/observe modes in `ENTRY_RULE_MODES`. Candle age, the hour-of-day probability penalty and the news veto are recorded, not blocking (operator: no session/news rules). `ai/entry_rule_evidence.py` sets modes on evidence (pre-registered: block only if a rule helps in both halves). History replay of the current engine (17 markets, June 12–Sep 15): `reports/entry_rules/`. Review: `reports/entry_rules/ENTRY_RULES_REVIEW.md`. This is Q3 answered on history; the decision log answers it live. Also: strategy targets kept only if they pay 1:1.2 net of spread (other targets on the floor); `STRATEGY_SELECTION` ALL or one group; the chosen strategy and its setup in `final_verdict`. Final-engine replay per strategy in progress. |
| 3 Weekly verdict | waiting on 1–2 data (first report after one full week of decisions) |
| 4 Live-only questions | waiting on 1–2 data; Q4 waiting on the operator's trades |
| 5 Build and prove | waiting on a pass |
