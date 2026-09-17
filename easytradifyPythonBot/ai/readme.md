# EasyTradify

Enterprise-grade algorithmic trading research, market-intelligence, portfolio-risk, AI-analysis, replay, simulation, and controlled-execution platform.

> **Important:** EasyTradify is designed as a research, paper-trading, backtesting, replay, and controlled-validation platform. AI components must not be promoted to live autonomous trading merely because backtests look good. Every learned component requires leakage-safe, walk-forward, out-of-sample, stress, and replay validation.

---

# 0. Implementation Status and Engineering Standards

Everything from section 1 onward is **design specification**. This section is the
**as-built record**: what actually runs, what is verified, and the standards any new
AI module is expected to meet. Read it before adding a module — every rule below
exists because its absence caused a real, measured defect in this package.

## 0.05 Storage: MongoDB, not Firestore (2026-09-10)

**Trades live in MongoDB.** `TRADES_TO_FIRESTORE = False` in
`monitor/firebase_helpers.py`. Firestore still owns `portfolio_config` and
`ai_models`; it holds **no trades**, by design rather than by accident.

| | |
|---|---|
| Database | `easytradify`, collection `trades`, local `mongod` on 27017 |
| Owner | `core/mongo/trades_service.py` — the only module that touches the collection |
| Write path | `monitor/trade_sink.py` (`record_open` / `record_price_point` / `record_close`), fail-soft, counts failures |
| Read path | `ai/trade_repository.py` — **every** model reads through this |
| Health | `trade_sink.get_status()` reports `degraded` and `mongo_healthy` |

Why: a Firestore document is capped at 1 MiB and a trade carrying a full
minute-by-minute forward walk is several megabytes, so `price_evolution`
stopped accepting points after two. Mongo's 16 MB limit holds a whole trade as
one document with `price_evolution` as a plain array — the shape every model
already expects.

**The trade-off:** there is no fallback store. If Mongo is down when a trade
opens, that trade has no record anywhere.

### The canonical stored shape

`ai/mt5_history.to_trade()` defines it, and the live writer
(`monitor/firebase_helpers.save_trade_open_to_firebase`) now matches it. Both
of these are load-bearing and were silently absent from live writes:

```
trade_id, ticket, symbol,
direction        "BUY" | "SELL"      <- models read this, not order_type
opened_at        ISO timestamp        <- default sort, own index, every
                                         walk-forward split orders on it
entry: { price, volume, stop_loss, take_profit }
close_data: { close_price, close_reason, profit_usd, is_winning, ... }
analysis_at_open: { ... }
price_evolution: [ { price, analysis, risk_state, microstructure, ... } ]
```

Every reader (`trade_repository._r_multiple`, `edge_discovery`,
`strategy_families`, `component_audit_360`) does:

```python
entry = trade.get("entry") or {}
ep, sl = entry.get("price"), entry.get("stop_loss")
if not all(isinstance(v, (int, float)) for v in (ep, sl, cp)):
    return None          # trade silently skipped
```

so a flat document scores `None` and is **dropped without a warning**. Measured
before the fix: R computable on 220/250 history trades and **0/2** live ones.
That is the most expensive kind of missing data, because collection looks like
it is working — rows accumulate and every model quietly ignores them.

Read stored trades through `trade_repository.load_trades()`, never raw from
Mongo: it applies `canonicalise()`, which flattens the `analysis_at_open`
envelope and decodes each price point. Passing raw documents to
`strategy_families.build_rows()` yields 0 rows; through the repository it
yields all of them.

### Data-integrity defects fixed 2026-09-10

Each of these corrupted the stored record silently — the values looked
plausible and nothing raised.

| Defect | Consequence |
|---|---|
| `TradesService._lock` was a non-reentrant `threading.Lock`; `_ensure_indexes()` held it and then read `self.client`, which acquires the same lock | **Self-deadlock on the first `collection` access in a process** — exactly what `record_open` does. Every trade open hung forever and nothing was ever written. Hidden from every health check, because `is_healthy()` reaches `client` *without* holding the lock, so `mongo_healthy: True` while live writes deadlocked. Now an `RLock` |
| Open path read direction only from `analysis_result["config"]["executed_direction"]`, defaulting to `"BUY"` | That key exists on the monitor's path and **not** on the copy-trade path, which passes `analysis_result={}`. Every copy-trade SELL was stored as a BUY — and `order_type` is passed into `get_all_timeframe_analysis_raw()`, so `analysis_at_open` was computed for the **opposite side** of the open trade |
| Close path: `order_type = "BUY"; if price_close < price_open: order_type = "SELL"` | Direction inferred from the **outcome**. A losing BUY was stored as a SELL, and because direction always agreed with the price move, **every closed trade read back as a winner**. Seven copies of this existed across `firebase_helpers`, `monitor_core` and `execute_copy_trade` |
| `profit = move * volume * 100000` in five places, and both branches returned a **positive** value | 100000 is the FX contract size; XAUUSD is 100 oz and UKOIL is not FX. A +$4.77 gold trade was stored as **-$3,960.00**; a UKOIL trade recorded **$8,500.00** on a fraction of a lot. The always-positive sign manufactured a 100% win rate in the profit field |
| Close fell back to `price_close = sl` when the history lookup missed | Assumes every trade closed at its stop. False for any manual or webhook close, and the lookup routinely misses in the moment right after a close |
| `microstructure_at_entry` referenced an undefined `mt5_symbol` | `NameError` on **every** trade, swallowed and recorded as `{"available": False, "reason": "capture failed: ..."}`. It read as "no tick data", so it went unnoticed while discarding the one edge confirmed from new information (order flow, +0.2646R, p=0.0180) |

Direction and profit now come from the broker: `core/broker_facts.py` —
`closing_deal()` reads `history_deals_get(position=...)` (authoritative on
exit, slippage, swap, commission and partial fills; costs summed over **both**
legs), `contract_size()` reads `trade_contract_size`, and both return `None`
rather than guess. A close that cannot be reconstructed is left unsaved: a
visible gap beats a fabricated record.

**These defects never contaminated the 215-trade research set.** That set comes
from `ai/mt5_history.py`, which reads `direction` from the opening deal's type
and profit from the broker's deals — it never touches the live save path.
Verified empirically: applied to the 250 real closed positions, the old
inference rule would have been wrong on **57.2%** of them and would have
manufactured a **98.8%** win rate. The research reports 42.4%.

## 0.1 Current state

| Subsystem | State |
|---|---|
| Trade storage | **MongoDB only.** See §0.05 |
| GNN (`ai_gnn.py`, `ai_gnn_lightweight.py`) | **Live.** Contributing to the probability chain, and now running forward on real trades |
| Price-evolution encoder | **Live.** Called on every `price_evolution` write |
| Decode boundary (`price_evolution_bridge.py`) | **Live.** Sole read path into stored trades |
| Measurement channels (`microstructure_at_entry`, `strategy_family_scores`, `component_reads`) | **Recorded on every trade**, `contribution: 0.0`, and now **read** by `edge_discovery.features_of()` — see §0.06 |
| Adversarial (`ai_adversarial.py`) | Correct + A/B instrumented. **Not called by live trading** |
| RL (`ai_reinforcement.py`) | Consumes whole trades. **Offline research only** |
| Non-RL (`non_rl_intelligence.py`) | Consumes whole trades. **Not called by live trading** |
| Root-cause (`root_cause_*.py`) | Redesigned, evidence-only. **Never instantiated** |
| `ai_controller.py` (Flask, :5002) | Starts and serves. **Nothing calls it over HTTP** |

## 0.06 The measurement channels are now searchable

Every trade records `microstructure_at_entry`, `strategy_family_scores` (23
categories) and `component_reads` (GNN, Elliott, Wyckoff, volume profile, SMC
setup), all carrying `contribution: 0.0` so they cannot move the probability
until validated.

Until 2026-09-10 **nothing in `ai/` read any of them**: `extract_samples()`
built rows from the probability ledger and the price path only, so the one
confirmed edge from new information was invisible to the search meant to find
it.

Now:

- `edge_discovery.features_of(trade)` flattens the channels to numeric
  features (~35 per trade), booleans as 1.0/0.0, prefixed by channel.
- `extract_samples()` puts them on each row as `features`.
- `edge_discovery.search_features()` **conditions** on them — "would skipping
  trades where flow opposes the fill have helped?" — with train-fold-only
  thresholds, walk-forward folds, a permutation null and BH-FDR across every
  hypothesis tested.

They are deliberately kept out of `deltas`. `deltas` are probability
contributions and the reweighting search multiplies them into the probability;
putting an unvalidated measurement there wires it straight into the chain,
which is the mistake that had `pattern` pushing 12 probability points the wrong
way on 26% of trades.

`feature_names()` enforces `min_present=10`: a feature on three trades produces
a spectacular subset that means nothing, and costs an FDR correction against
the ones that might be real.

`ai_asset_analysis.py` is an empty file. `ai_ab_testing.py` and `ai_diffusion.py`
do not exist. `save_root_cause` / `save_correction` / `save_evolution` in
`core/firebase/firebase_service.py` still have **zero call sites**, so the
`ai_root_causes` / `ai_corrections` / `ai_evolutions` collections are never written.

### Defects found and fixed

| Defect | Consequence |
|---|---|
| Empty `ai_config.py` + stale `__init__.py` importing ~15 non-existent modules | `import ai` raised `ImportError` **always**. Callers guard with `try/except ImportError`, so GNN silently scored **zero on every decision**, and price-evolution compression was silently off |
| Encoder fabricated `success=False`, `timestamp=now()`, `model_version="v4.0.1"` | Healthy decisions labelled failed; encode time impersonating decision time. Fixed both ends — **repairs existing Firebase rows**, since the phantoms were added on read |
| Adversarial clamp wrote back the *stale* pre-update weight | Adaptive attack selection frozen at 0.0 — uniform random forever, while appearing to work |
| Adversarial `outcomes * len(all_attacked)` | Every variation trained against **another trade's label** |
| `NonRLIntelligenceController.__init__` called `random.seed()` | Reseeded the **process-wide** RNG merely on construction |
| `ai_controller.py` imported two non-existent modules | Service could not start at all |

### Known, unfixable in place

`price_evolution` exists in two storage shapes, split at the moment the `ai`
package import was repaired: rows written while it was broken are raw
(`_encoded: False`, `*_analysis_raw` keys) and hold only an `_audit_slice()` of
M5/H1. `to_canonical()` reads both, but the missing M5/H1 detail is gone.
**Always branch on `_encoded`. Never assume a format.**


## 0.07 DATA-COLLECTION MODE — the live gates are loosened (2026-09-10)

The bottleneck for this research is trade **count**, not signal purity, so the
entry gates were deliberately widened. **Any statistic computed on trades
collected under these settings measures the loosened rules, not the strategy.**
Every site carries a comment with its original value.

| Setting | Was | Now | Why |
|---|---|---|---|
| `MIN_ENTRY_CONFIDENCE`, `min_probability_for_entry`, `min_timing_confidence`, all `signal_thresholds[*].min_probability` | 75 | **65** | Requested. Note this was *not* the binding constraint — probability on rejected setups had median 82.5% |
| `signal_thresholds[*].min_candle_progress` | 40–75 | **20–40** | **The actual wall.** A 1-signal setup needed the candle 75% formed — a 45-second window each minute |
| `instrument_adx_thresholds` (XAUUSD/XAGUSD/DEFAULT) | 20/22/25 | **12/13/15** | Largest single veto. Vetoed ADX had median 18.8, p75 22.0 — the whole 15–25 band. The research finds RANGING **outperforms** TRENDING (48.3%/+0.0245R vs 36.8%/−0.0983R), so an ADX floor rejects the better regime |
| `min_discount_score` | 50 | **30** | Became the dominant blocker once the earlier gates opened |
| `VOLUME_THRESHOLD_*` | 0.3/0.4/0.5 | **0.15/0.20/0.25** | Off-session volume is structurally low, not informative |
| `tradable_grades` | A/B/C | **A/B/C/D** | 616 `INVALID_ZONE` rejections, all grade D. **Most aggressive change and the first to revert** — it admits setups the strategy calls untradeable |
| `MIN_SYMBOLS_TO_TRADE` | *(did not exist)* | **10** | See below |

**`min_adx_for_trend` is dead config for the choppy veto.** The veto reads
`_get_instrument_adx_threshold()`, i.e. the `instrument_adx_thresholds` table.
Changing `min_adx_for_trend` alone does nothing — verified by it continuing to
fire at `ADX=20.1 < 25` for eight hours after that value was lowered.

### Two config traps that stopped trading entirely

**`TOP_SYMBOLS_COUNT` is a cap, not a floor.** `_run_filter_step()` compared
its pass-count against it and returned `False` when short. With a 64-symbol
universe, 45 passing and a cap of 100, the gate could never be satisfied:
`_refresh_top_symbols()` was never called, `top_symbols` stayed empty, and the
monitor ran healthy and idle **forever**, opening nothing. The floor is now a
separate `MIN_SYMBOLS_TO_TRADE`.

**`RISK_PER_TRADE` is not account risk.** `core/calculations.py` computes
`target_risk = fixed_trade_size_usd * risk_per_trade`, i.e. a fraction of the
**$200 trade-size budget**: `0.05` → $10, `0.02` → $4. On a $22k account that
is ~0.02–0.05% of equity, not 2–5%. Expressing real account-percentage risk
requires sizing off equity and is a genuine change, not a constant edit.

It also does **not** shrink the position — the lot is capped by margin (0.09 on
XAUUSD at both settings). What changes is the **stop distance**: 44.4 pips at
0.02 versus 111.1 at 0.05. At $4 the stop is squeezed to ~1 pip, which is
inside the spread on some pairs.

### The consequence, measured

First 3 closed trades under these settings:

```
win rate    1/3 = 33%
mean R      +9.49      <- one trade returned +30.42R on a 1.2-pip stop
MEDIAN R    -0.95      <- what a typical trade actually does
stop pips   median 3.9,  3 of 6 under 3 pips
```

A mean of +9.49 against a median of −0.95 is the signature of a risk unit that
is too small to be meaningful. **Do not run edge discovery on this population**
until a minimum stop distance (e.g. `max(8 pips, 2×ATR)`) makes R a real
quantity. Rate is ~24 trades/day, so 500 trades is roughly three weeks.

### Trade independence

`MAX_SIMULTANEOUS_TRADES` and `MAX_TRADES_PER_SYMBOL` are both 100000, so
clustered same-symbol fills are permitted. Weight by uniqueness once
concurrency is high (`core/exposure_risk.py` measures `concurrent_exposure`
and `effective_sample_size` but blocks nothing): ten overlapping trades are not
ten observations, and p-values inflate by roughly √(trades/effective).

Separately: running **two monitor instances at once** produces duplicate fills
on the same signal (observed: AUDCHF ×3 in 4s, EURUSD ×2 in 1s). Those pairs
are one observation, not two. `app.run(..., use_reloader=False)` now prevents
Flask's reloader forking a second trading process; check for a second
`hybrid_monitor.py` before starting one.

## 0.15 First replay on real data — what it found

The `trades` collection was empty, but the trades were never missing: **245
positions sat in the MT5 account history**, 215 with stops. The broker keeps
the order and not the reasoning, so `analysis_at_open` was absent for all of
them — and every model that reads the decision snapshot had nothing to read.

`ai/history_enrichment.py` recovers it. The analysis layer is deterministic
over bars, so feeding it the bars as they stood at the entry moment reproduces
what the bot would have computed then. `HistoricalFeed.verify_no_lookahead()`
proves the slice is causal, and enrichment refuses any trade where it is not.
**All 215 enriched, 56 analysis sections each, zero look-ahead violations.**

This is not simulated data. The fills are the broker's; the analysis is the
same functions on the same bars.

### The account, in R

| | Actual | Needed to break even |
|---|---|---|
| Win rate | 43.3% | — |
| Avg win | +0.899R | **+0.968R** |
| Avg loss | −0.738R | **−0.685R** |
| Payoff | 1.22 | **1.31** |
| Mean | **−0.0298R** | 0 |

**+12,732 USD and −6.45R over the same 215 trades.** Both are true only if the
profit came from position sizing rather than edge — large wins landing on large
size. That is exposure, not a repeatable property.

### The ADX choppy-market veto is inverted

| | n | mean R | win rate |
|---|---|---|---|
| Choppy-vetoed | 118 | **+0.0189R** | **48.3%** |
| Not vetoed | 97 | **−0.0890R** | 37.1% |

The trades the veto blocks are the only profitable group; the trades it
approves lose. Separation −0.108R at p=0.49 — **not** evidence the veto is
harmful, but strong evidence it does not discriminate. The effect is larger
than the 0.07R gap to break-even, which is what makes it worth an experiment.

### Confidence does not rank outcomes

| Confidence | n | mean R | win rate |
|---|---|---|---|
| 5–37% | 43 | −0.319R | 37% |
| 37–58% | 43 | **+0.192R** | **53%** |
| 58–76% | 43 | −0.061R | 35% |
| 76–88% | 43 | +0.000R | 44% |
| 88–95% | 43 | +0.039R | 47% |

The best decile is 37–58%. High versus low overall: p=0.62. Any gate that
sizes or filters on this number is keying on noise.

### What the wide scan proves about wide scans

1,430 real analysis features, 1,756 buckets, Benjamini-Hochberg at q=0.10:
**zero survivors.** At 215 trades the top rank needs p ≤ 0.000057 and the best
available was 0.0040 — short by a factor of 70.

That is the useful result. Two focused, pre-registered questions found more
than a scan over every feature in the payload, because the scan's own
correction is what makes 1,756 comparisons meaningless at this sample size.
Detecting a +0.10R effect here needs ~4,200 trades; +0.30R needs ~470.

**38. Recompute the reasoning rather than mourning it.**
Analysis that was never stored is not necessarily lost. When the analysis
layer is deterministic over market data, it can be recomputed at the decision
moment — and the only thing that makes that legitimate is a look-ahead check
that refuses rather than warns. An analysis holding one bar of the future
produces features that predict the outcome perfectly and generalise to
nothing, which is the most expensive error available here.

**39. An experiment must end in a decision.**
`ai/rule_experiments.py` runs the ADX finding forward through the governance
A/B, and `recommended_change()` turns a settled verdict into the specific edit
to make. It speaks only when `verdict_is_actionable` — significant *and*
directionally clear — and otherwise returns NO CHANGE with the reason, because
the default in a live trading system is to change nothing.

The seam is `VetoEngine._veto_active`, which already separated "did this veto
fire" from "is it allowed to block": a disabled veto still runs and still
records, so both arms produce identical telemetry and differ in exactly one
respect. Off unless `AI_RULE_EXPERIMENTS` is set, and every uncertain path —
no id, unknown veto, any exception — leaves the veto ACTIVE. The failure that
matters is suppressing a veto by accident, never keeping one.

**40. A component's contribution must be signed against the trade, not the
market.**
`base_probability` in the scoring chain is the probability the CHOSEN
direction is correct — not an absolute bullish/bearish read. A scorer that
signs its contribution from its own market read alone raises the probability
of a SELL on bullish evidence. Found and fixed three separate times here
(`calculate_gnn_final_score`, `calculate_smc_final_score`, and
`calculate_pattern_final_score` — the last of which never received
`best_direction` at all).

The measurement is the point. On 215 causally-recomputed trades, `pattern`
carried +0.4063R on BUY trades and −0.4296R on SELL trades: near-equal
magnitude, opposite sign. Pooled, the two halves cancelled to +0.0260R
(p=0.89), so a component firing on 80.5% of trades measured as pure noise.
Corrected, the same deltas give +0.4880R pooled (p=0.0046), holding
+0.3017R out of sample and beating the 95th percentile of a 2,000-shuffle
permutation null.

`tests/test_scorer_direction_alignment.py` enforces the property rather than
the three instances: every `*_final_score` in the chain must accept a
direction or be listed in `DIRECTION_SYMMETRIC` with a written reason. An
unclassified scorer fails, so the question gets answered once, on the record,
for every contributor to the probability. (`gap_slippage` is a pure penalty,
`nested_zone` measures level quality, `rvam` is signed upstream — all three
are genuinely symmetric.)

**41. An injected feed is not a firewall if components can call around it.**
`verify_no_lookahead` verifies the `MarketData` a replay HANDS OVER. It cannot
see a component that ignores that argument and calls MetaTrader5 itself, and
several do — they were written for live trading, where
`copy_rates_from_pos(symbol, tf, 0, n)` simply means "the latest bars":
`nested_zone_confluence`, `trend_cascade`, `adr_exhaustion`, the H1/M15 paths
in `indicators.py` and `calculations.py`.

`ai/history_enrichment.py` passed `market_data=` and never entered
`core/mt5_shim.replay_context`, so during enrichment of a trade from weeks ago
every one of those returned TODAY'S bars — not the trade's future, simply the
wrong data, identical across every trade of a symbol in the same run. A
component fed that way cannot help measuring as noise, which made "this
component does not work" an unsafe conclusion for all of them. Re-measured on
a properly shimmed dataset, the picture changed materially: `trend_cascade`'s
apparent sign error disappeared, `adr_exhaustion`'s reversed, and only
`pattern` and `rvam` survived a permutation control.

The shim is fail-closed by design: an unservable timeframe returns None and
the component reports unavailable. Inert is a correct answer; contaminated is
not. `MIN_HTF_BARS` is now per-timeframe for the same reason — a flat 150-bar
floor meant D1 needed seven months of history per decision and was served 0
times out of 1,212 requests, starving its only consumer.

**42. Verify the capture format BEFORE spending money to fill it.**
Every component measurement in this package reads
`analysis_at_open.final_verdict.probability_ledger` and
`analysis_at_open.best_direction`. A live trade stores neither at that path:
`api/execute_copy_trade.py` writes `analysis_at_open = {}` on the fast path,
then a background thread overwrites the field with a snapshot envelope whose
payload sits under `m1_analysis_raw`, while `firebase_service` wraps under
`full_raw_analysis` instead.

A capture run would therefore have produced hundreds of real-money trades that
look complete and answer none of the questions they were collected for.
`PriceEvolutionBridge.to_canonical` now unwraps both envelopes at the single
boundary every consumer already passes through, and
`tests/test_live_capture_readiness.py` asserts the two fields are reachable
from all three stored shapes. Check the pipeline end-to-end on a synthetic
document before running it with capital, not after.

Assignment is by symbol, because the veto call site has no per-decision id.
That makes it a cluster-randomised trial with ~27 units rather than 215, and a
symbol carrying its own edge lands wholly in one arm. Stated rather than
hidden: read the verdict knowing the effective sample is closer to the symbol
count, and give it more time. Trade-level assignment becomes possible once the
decision path carries an id, which `live_recording` already mints.


## 0.2 Standards for any new AI module

**1. One decode boundary. Never reason off stored form.**
Stored analysis is compressed and multi-format. Everything reads through
`PriceEvolutionBridge.to_canonical()`. Training on short keys (`c`, `tb`, `sd`)
produces a model fitted to field names no analysis layer emits.

**2. Enforce the leakage firewall by construction.**
```text
analysis_at_open + entry        -> FEATURES
price_evolution[]               -> forward walk
close_data + analysis_at_close  -> LABELS ONLY
```
Leakage is the failure that does not announce itself: it yields excellent
validation numbers and a worthless model. Assert its absence in a test, and make
that test able to fail (`test_non_rl_self_check_would_catch_leakage`).

**3. Extract schema-free. Never enumerate components by name.**
`_flatten` walks whatever is present, so a new subsystem is picked up without
touching the extractor. Hardcoded mirrors drift — see `ai_asset_diagnostic.py`'s
`ParameterRegistry`, a hand-maintained copy of constants nothing cross-checks.

**4. Prove coverage; do not claim it.**
"The AI sees everything" is falsifiable. `feature_coverage()` reports per-section
counts; `test_no_unexplained_information_loss` fails if any source leaf is
dropped without a stated reason. Current: 128 leaves → 486 features, 0 loss.

**5. Never fabricate. Absent stays absent.**
No default timestamps, versions, or success flags. A fabricated field is
indistinguishable from a real one downstream. If provenance must be recorded,
name it for what it is (`encoded_at`, not `timestamp`).

**6. Fail loudly on structural error; degrade quietly on data error.**
Mismatched sample/label counts `raise`. One malformed row is skipped so a batch
survives. Silent mistraining is the worst outcome; a dead batch is second.

**7. Normalizers must be idempotent.**
`to_canonical()` on canonical input previously blanked the analysis it had just
decoded. Test double application.

**8. Respect episode boundaries.**
`CounterfactualSimulator` walks to the end of the list it is given, so
concatenating trades resolves one entry against another trade's price path.
`snapshots_from_trades()` returns one sequence **per trade**.

**9. No global state mutation.**
Instance-scoped RNG (`random.Random(seed)`). Global seeding belongs only in an
explicit training entry point (`seed_everything()` in `train_from_replay`), never
in a constructor or a data path.

**10. Reuse the existing pattern; never write a second one.**
Adversarial's A/B mirrors `ai_gnn.py`'s schema deliberately. This codebase has
repeatedly been bitten by duplicate implementations that silently disagreed — two
swing detectors, two lot-sizers, two liquidity-sweep detectors. RL and non-RL got
**no** A/B bolted on, because `evaluate_agent()` gates and
`ValidationEngine`/`ExperimentEngine` already fill that role.

**11. A/B testing, properly.**
Deterministic hash-based arm assignment (random assignment puts one trade in both
arms across retries); a control arm that is genuinely untouched; minimum samples
before acting; automatic rollback on degradation; and `NO_DIFFERENCE` /
`INSUFFICIENT_DATA` as first-class verdicts. The system must be able to conclude
*"this changed nothing."*

**12. Every module exposes `get_status()` and `self_check()`.**
`get_status()` distinguishes "disabled" from "enabled but unusable".
`self_check(trades)` proves the data path on real input and **returns** the
failure reason rather than raising, so it is safe to poll.

**13. One regression test per fixed bug.**
Each test in `tests/` names the defect it prevents. A test guarding nothing that
ever broke is maintenance cost.

**14. Comment the *why*, with evidence.**
Match the convention already in `core/`: state the defect, the measured
consequence, and why the fix is shaped as it is.

**15. Your control must preserve structure and remove only the edge.**
Learned the hard way. `exit_model.py` initially **promoted a model trained on
pure noise** — AUC 0.777, +0.34R, and it beat its shuffled-label control. Two
controls failed before one worked:

| Control | Why it failed |
|---|---|
| Shuffled labels | Destroys the structure being exploited, so real data beats it even when the real data is noise |
| Synthetic random walk | Has to *guess* the data's statistical character. A driftless walk is far less exit-timing exploitable than an iid-around-a-level series, so the bar lands in the wrong place |
| **Permuted increments** ✓ | Preserves entry, endpoint, length, volatility and the exact multiset of moves. Destroys **only temporal order** |

The permutation control works because it isolates exactly the claim being made:
a genuinely *temporal* edge must degrade when time is scrambled, while an
artifact like "exit near the path's peak" survives permutation and is correctly
refused. On the noise set the permuted control now scores *higher* than the real
data (0.88 vs 0.78 AUC), which is the right answer.

The general rule: **ask what your model claims, then build the control that
removes that one thing and nothing else.** A control that removes too much
flatters the model — and one that removes too little makes the gate unpassable
for the wrong reason.

`target_model.py` hit the second half of that immediately. Within-trade
permutation preserves each trade's **endpoint** (the increments still sum to the
same total), which is fine for a path-shape label but wrong for an
endpoint-adjacent one — "does price run further" is largely decided by per-trade
drift, so the control kept the very structure under test and scored **0.99 AUC /
1.59R, above the real model**. The fix was to pool increments across all trades
(`permuted_path_trades(pool_across_trades=True)`), removing per-trade drift while
preserving the global distribution of moves. Same model, same data, correct
verdict: 1.24R against a 0.92R floor.

**Match the null to the label**: path-shape labels take within-trade
permutation, endpoint-adjacent labels take pooled.

**15b. Scanning many conditions finds "signal" in pure noise.**
`abstention_model.py` scans every candidate condition for buckets with bad
expectancy. Run against 200 trades with **randomised outcomes**, it found
**12 decline rules** — including `session=LONDON` at −0.36R over 51 trades,
which reads as compelling evidence. All of it was luck.

Two independent gates caught it: the out-of-sample expectancy gain was negative,
and the rules would have declined 100% of trades. Neither alone was sufficient.
The shuffled-outcome floor exists for exactly this — it destroys any real
condition-outcome link while preserving bucket structure and the R distribution,
so whatever the scan still "finds" is what the method invents from nothing.

**Any procedure that searches over many hypotheses needs a floor built the same
way.** The more conditions you scan, the more this matters.

**17. Learn from success on the same terms as from loss.**
`abstention_model.py` originally scanned only for buckets to decline. Measured
on data where ASIA ran **−1.03R** and NY ran **+1.16R**, it found the ASIA rule
and was completely blind to NY — the strongest signal in the set. A system that
only learns where it loses cannot say where to lean in, and the Monitor ranks
competing candidates with no idea which conditions have historically paid.

The scan now runs in both directions on the same evidence standard, producing
`DECLINE` / `FAVOR` / `NEUTRAL`. Two rules govern the asymmetry that remains,
and both are deliberate:

- **Decline outranks favour.** A realised loss beats an estimated gain: the
  downside is measured, the upside is a projection.
- **Favour is advisory, not gating.** It changes candidate ranking, never what
  is traded, so a weak favour set cannot veto a sound decline set.

Note the same multiple-comparison hazard applies to *both* directions —
scanning for the best buckets finds spurious winners exactly as readily as
scanning for the worst — so favour rules are validated out of sample too.

Checked across the package while fixing this: `calibration_model` is symmetric
by construction, `exit_model` carries balanced labels (verified 40/40 on matched
winners and losers), and `exit_model` + `target_model` are symmetric **as a
pair** — one owns losing trades, the other owns winning ones. Directional
symmetry was also verified: a BUY and its mirrored SELL produce byte-identical
features, which is the failure `core/` hit repeatedly in its RSI, MACD,
stochastic and volume scorers.

**16. A gate that cannot be computed is a gate that has not been met.**
Both models originally *skipped* the noise-floor comparison whenever the control
could not be scored (too few resolved samples), so a model could be promoted
with its most important safety check silently absent — and the report still
looked clean. Both now fail closed and say so. This is the same failure shape as
GNN scoring zero unnoticed: the absence of a check is invisible unless the
absence is itself reported.

Related: the root cause was that the label (`final < current`) was nearly a
function of a *feature* (`current`). Whenever a label is defined by comparison
against something derived from the features, check for this before trusting any
metric.

**18. Measure coverage on the object that is consumed, not the one that is
produced.**
`analysis_coverage()` reported extraction "lossless" and was correct: every one
of the 24 analysis sections was carried onto the `CanonicalTrade`. The object
replay actually reads is the `DecisionSnapshot`, and it carried **20 of 75
analysis leaves**. The loss happened one hop later — `DecisionGenome` had no
field for the unmapped sections, so `build_genome` dropped `account_info`
(leverage), all the numbered `components` sub-analyzers, the SMC blocks beyond
market_structure, `pattern_analysis`, `wave_lattice`, `vetos`, `family_vote`,
`nested_zone`, `trend_cascade`, `higher_timeframe` and `news_analysis` on the
way in. Three declared snapshot fields (`non_rl_state`, `trade_quality_state`,
`rl_state`) were never populated at all.

Nothing raised, and the coverage report kept saying lossless the whole time,
because it was measuring the wrong artifact. A pipeline is only as lossless as
its narrowest hop; measure at the point of consumption.

`snapshot_coverage()` now measures this at leaf level against the **raw stored
analysis**, never against anything derived from the extraction — a check that
compares the output to a reconstruction of itself cannot fail. It is enforced in
`self_check()['ok']` and printed by the CLI.

**18b. A matcher built to excuse renames will excuse omissions too.**
The first version of that check compared trailing path segments, because the
snapshot legitimately re-homes sections (`final_verdict` → `market_synthesis`).
It reported 10 phantom missing leaves — and would equally have marked a genuinely
dropped leaf as present whenever any unrelated section ended in the same name.
It now rewrites source paths through `MARKET_STATE_SOURCES`, the same table the
extraction uses. A negative control (delete a section, confirm the check fails)
is part of the test suite: a coverage check that cannot fail proves nothing.

**19. `ok` is tri-state. A boolean cannot say "not exercised".**
Six `self_check()` functions left `ok` at its initialised `False` whenever no
samples could be built, so a healthy module given thin data reported itself
broken — and `/verify`, aggregating those, sat red until people learned to
ignore it. The opposite reflex (report "not exercised" and move on) is the same
error mirrored: it lets a broken decode path pass unnoticed. The two states are
now separated by `count_usable_trades()` — one shared probe, not six copies:

| input | verdict | meaning |
|---|---|---|
| nothing can decode it | `ok=False` | the data path is broken; fail the gate |
| decodes, nothing eligible | `ok=None` + `reason` | not exercised; no verdict |
| decodes, checks run | `ok=True/False` | a real result |

**20. A gate that silently drops what it cannot measure is worse than no gate.**
`/verify` built its verdict from components carrying a dict `self_check` — and
GNN and `ai_adversarial` had none, so they were filtered out of the numerator
entirely. The whole-layer gate could answer `ok=True` having verified nothing
about the component the controller itself prints as ESSENTIAL. Standard 16
again, in the one place it matters most: the top-level gate.

Both now expose module-level `get_status()`/`self_check()`, and `/verify`
reports `unverified_components`, `unavailable_components` and `not_exercised`
by name. A component that cannot report withholds `ok` instead of vanishing
from it.

Two related repairs the same audit forced:
- `non_rl_intelligence` had both endpoints, but only as *methods*, so the
  module-level call every other module answers raised `AttributeError`.
- The first version of adversarial's `adaptive_weights_move` check was decided
  by the attack-probability and rollout gates — i.e. by a coin flip. It now
  forces those gates open and restores them, and is stable across RNG seeds.
  A check whose outcome is random proves nothing in either direction.

**21. Every model gets A/B assignment and a real rollback, from one
implementation.**
The audit found A/B in 2 of 8 models and rollback in none. `save()` and
`load()` existed everywhere, but nothing recorded *which* saved artifact was
known to work, so "put it back the way it was" was not an operation anyone
could perform. `ai/model_governance.py` now provides both:

- **Assignment** is a pure function of the trade id — never random, never
  stateful — so a trade lands in the same arm across restarts, retries and
  processes. An assignment that can change puts one trade in both arms.
- **The hash is a parameter.** `ai_adversarial` uses SHA-256 and `ai_gnn` MD5.
  Unifying them would reassign every in-flight trade between control and test,
  silently invalidating any comparison already running — the exact corruption
  A/B exists to prevent. Unify at a rollout boundary, never mid-test. Those
  two keep their own counters and are *delegated to*, not mirrored: a second
  empty experiment reporting `INSUFFICIENT_DATA` beside a real one is two
  answers to one question.
- **Rollback refuses when it cannot act.** It returns `409`, not a cheerful
  `200` that changed nothing — this endpoint is called precisely when someone
  believes production is broken. It never deletes the version it left; a model
  that looked bad on 40 trades may be fine on 400.
- **Every training attempt is registered, including rejected ones.** "Tried on
  this data, did not beat the noise floor" is the fact that stops it being
  retried in three months. Promoted versions are exempt from trimming, because
  they are the set rollback can return to.

`direction` and `significant` are separate fields, and only
`verdict_is_actionable` should drive automation. A caller that reads
`TEST_BETTER` and ships it has been told the sign of a difference, not whether
the difference is real: with 30 trades an 8-point win-rate gap is routine.

**22. The selection IS the multiple comparison. It belongs inside the
denominator.**
Widening the abstention scan from 10 hand-listed conditions to the whole
snapshot multiplies the false-discovery hazard of standard 15b. A
Benjamini-Hochberg correction was added — and the first version applied it
*after* filtering candidates by effect size, so the denominator was the count
of already-extreme buckets (~12) rather than the hypotheses actually examined
(~600).

Measured over 30 pure-noise runs, that let a false rule through in **67%** of
them against a 10% target. Testing every eligible bucket and correcting over
all of them brings it to **16.7%** (the residual is bucket correlation; BH
assumes independence). Power is intact: a planted −1.2R and −0.6R effect is
found in 100% of runs, −0.3R in 25%.

Two consequences worth carrying forward: a control must search the *same space*
as the claim it tests, so the shuffled floor now scans the identical condition
list (standard 15); and rejected candidates are kept, because "we looked and it
did not survive" is a finding.

**23. Coverage means the model reads it, not that the extractor produces it.**
The bridge was already extracting ~125 analysis features per trade —
leverage, SMC, volume profile, S/R, patterns, waves, indicators, session — and
`exit_model` and `target_model` were deciding from 11 price-path features and
nothing else. The evidence existed; nothing consumed it.

`context_features()` now exposes the full decision-time snapshot, sourced from
`analysis_at_open` and `entry` only so nothing can leak the outcome. It is off
by default, and that is not timidity: these columns are constant within a
trade, so under trade-grouped splits they let a model identify the trade rather
than the situation, and ~123 extra columns on a few hundred trades memorises.
The flag only lets them *compete*; the permutation noise floor still decides.

The wiring bug this exposed is the general case worth remembering: `TargetModel`
wraps `ExitModel`, and `ExitModel.fit` picks its columns from its **own**
config. Leaving the flag behind meant the estimator kept 11 columns while the
sample builder produced 130 — `_matrix` silently dropping every context column
and training on a feature set nobody chose. It looked normal and reported
normal.


**24. A subsystem nobody can call is a subsystem that does not work.**
`root_cause_*.py` was 1,082 lines with no test file, no `self_check` and no
endpoint. Fed a stored trade it returned **0 component evidence, no diagnosis,
0 recommendations** and the report "No Replay artifact was supplied."

The analyzer was behaving correctly — it refuses to name a cause it cannot
evidence — but nothing was ever going to supply that evidence. `ai/aireplay/`
produced every artifact it wanted and the two were never connected.
`root_cause_adapter.py` connects them. Measured on the same fixture
afterwards: **4 divergences, 2 attributions, 10 counterfactuals, 28 component
evidence rows, 16 deterministic sections.**

Three silent shape mismatches were doing the damage, and all three fail the
same way — an empty result that renders as a complete report:

| producer | consumer | consequence |
|---|---|---|
| `divergences` as dict-of-kinds | read with `_list()` | iterates as key *strings*; every one discarded as "not a Mapping" |
| `deterministic_features` | reads `deterministic` | component evidence 0 for every trade, always |
| `"COMPONENT"` | `AttributionType` enum | not a member → silently degrades to `UNKNOWN` |

A key mismatch between a producer and a consumer is invisible unless one of
them insists on checking. `earliest` was also being counted as a fifth
divergence when it is a *pointer* to the first — a narrative built on that
count reports more going wrong than did.

**25. An explanation must be traceable, not fluent.**
`diagnosis_narrative.py` writes the diagnosis in plain language. It uses no
language model, deliberately: a generated explanation reads as fluent whether
or not the evidence supports it, and a confident-sounding cause that nothing
measured is the one output this system cannot afford. Every clause is emitted
only when a specific field exists and carries the path it came from, so any
claim can be checked against the record. Fluency is worth nothing here;
traceability is the product.

The verb is calibrated to what the evidence establishes:

```text
UNPROVEN   -> "is consistent with ... it was present at the failure,
               which is not evidence that it produced one"
SUPPORTED  -> "would have been avoided by" (a counterfactual on the
               recorded path shows a better result)
PROVEN     -> "caused"
```

Two things it says that a conventional report would not:

- **A single loss does not indict a probability.** When the system stated 72%
  and lost, the narrative says so explicitly: at 72%, ~3 in 10 such trades are
  expected to lose, calibration is a property of a *cohort*, and it can only be
  judged over one. The most tempting reading of any individual loss is "the
  model was wrong", and acting on that one trade at a time is how a calibrated
  model gets tuned into an uncalibrated one.
- **Oracle branches are labelled as bounds.** "The best hindsight-only branch
  reached 1.00R — that is a BOUND on what this path offered, not a change
  anyone could have made: it required knowing the future." Quoting oracle and
  implementable results together is how a backtest starts promising returns
  nobody can capture.

**26. Track whether a model is RIGHT, not just whether it FITTED.**
Every model could report its fit state; none could report its performance once
a trade settled. A model that trains successfully and predicts badly looked
identical to a good one from every status endpoint in the system.
`model_performance.py` scores them.

The headline metric is **expectancy in R**, never accuracy. A model right 70%
of the time taking +0.3R wins and −1.0R losses loses money; direction entropy
here measured 1.0000, so any metric that rewards being right rather than being
right *when it pays* selects for noise. There is a test asserting exactly that
case scores NEGATIVE.

Zero variance is the **strongest** evidence available, not the weakest — a
model returning exactly −1.0R on eighty consecutive trades has no sampling
error to speak of. The first version of that branch called it `UNMEASURABLE`,
reporting the most clear-cut loser in the system as unknowable.

The ensemble section answers the question worth asking: **does agreement carry
information?** If outcomes are no better when models agree, the extra models
are decoration paid for in latency; if they are, agreement is a filter
abstention can use. One R per *trade*, never one per model — a trade with six
models attached would otherwise count six times and inflate every sample size
sixfold.

All of it is **observational, not causal**. These records are what the models
said and what subsequently happened; nothing randomised anything, and a model
that scores well may simply have been consulted on easier trades. Causal
claims need the A/B machinery in standard 21, and the wording keeps that
distinction rather than blurring it.


**27. A stress that always breaks measures nothing.**
Stress replay (phase 3 item 10) perturbs the recorded path and reports the
**breaking point** — the smallest magnitude at which the outcome flips. The
first version sized the adverse gap by the path's own range, which made the
smallest gap tested larger than most stops: every trade flipped at magnitude
1.0 and `most_fragile_to` came back "gap" for the entire cohort. Sized in R
instead (half the stop distance per unit), the family became informative. A
control that always fires is a constant wearing a result's clothes.

The load-bearing property is that the **unstressed magnitude runs through the
same code as every stressed one**. If the 1.0 volatility scenario disagrees
with the baseline, the perturbation is leaking into the control and every
delta is wrong — so that identity is asserted in `self_check` and in a test.

Stress output is **never historical truth**. `counterfactual.py` walks
alternative rules over recorded prices; this modifies the prices, and says so
on every scenario and every report. Quoting the two side by side as "what
would have happened" is how fiction acquires the authority of measurement.

**28. Correct the control before believing the result.**
Two validators built in this pass promoted noise on their first version, and
both for the same reason — comparing against the **mean** of a null
distribution instead of its upper tail:

| validator | bar | noise promoted |
|---|---|---|
| GNN OOS (phase 5.7) | shuffled **mean** | 1 run in 5 (20%) |
| GNN OOS | shuffled **95th percentile** | 0 in 5 |

The mean is the centre of the null; a delta sitting inside the null's ordinary
spread beats it roughly half the time by construction. Power was checked
separately and survived the tightening: a planted signal is still found in 5
runs of 5. A control that rejects everything is as useless as one that accepts
everything, so both directions have to be measured before either is trusted.

The RL policy search (phase 7.2/7.3) carries the same control, and its
permutation runs the **whole procedure including the parameter search**.
Controlling only the final policy ignores that the search picks the best of 19
candidates, which is where most of the optimism lives.

**29. Ask whether the DIAGNOSIS survives, not just the model.**
Adversarial testing perturbs a trade and checks the model holds. Phase 6 item
6 asks the harder question: does the *attribution* hold? If the failure class
or the first divergence flips when an unrelated field is nudged, the diagnosis
was reading noise and every recommendation built on it inherits that.

`adversarial_replay.py` runs replay on the original and on variants from the
real 28 attack families, then reports stability per conclusion. Stability is
explicitly **necessary, not sufficient** — a consistently wrong attribution is
perfectly stable — and the report says so rather than letting a high score
read as validation.

**30. A learned size is a leveraged bet on your own validation.**
Phase 7 item 4 is bounded sizing, and the bound is the point. A learned
multiplier may move size only *within* caps set by risk policy, never past
them: multiplier limits, per-trade risk limits, and a portfolio ceiling that
can zero a size outright. Every clamp is checked on each call and reported,
never silently applied — a size cut from 1.4% to 1.0% and reported only as
"1.0%" hides that the model wanted something the limits refused, which is
precisely what a risk reviewer needs to see. Non-finite multipliers are
replaced rather than trusted, because the one code path that must not exist is
the one where a NaN reaches an order.

Deployment (item 8) means versioned, gated, and behind a **10% rollout** with
a rollback available — never "switch every trade to the new policy". A policy
that just cleared its gates on a few hundred historical trades has earned an
experiment, not the book.

**Why these are small parameterised policies and not deep RL.** Management,
exit and sizing each reduce to a handful of thresholds over quantities already
expressed in R. A deep policy over those, trained on a few hundred trades, has
enough capacity to memorise every path it saw and no way to prove it did not —
the same reasoning behind the readme's own rejection of deep RL for entry
direction. `ai_reinforcement.py` keeps the deep apparatus for entry timing,
where the action space is genuinely sequential. A small policy space is not a
compromise here; it is the only space in which a result on this much data
could mean anything.


**31. A progress table is a claim, not a record.**
Phase 2 was marked "items 1–7 already exist in `core/`". Two of them did not.
`core/` has `vwap.py` and `rvam.py`, but nothing computed close location
value, and the dozen per-component scores (RSI, stochastic, pattern, GNN, ADR)
are not a Trade Quality layer. The claim was inherited from this document and
repeated — by me, in a completion report — on the strength of a filename
search. Locating a file is not verifying a capability, which is the same
mistake as trusting a status endpoint that has gone stale (standard 20).

The audit that caught it also found:

- **Phase 3 item 9 was half-built.** `ExperimentEngine.ablate_components`
  produced ablated feature sets and nothing re-scored them — the data half of
  an ablation and the only half. `ai/ablation.py` measures the effect, with a
  noise band from random subsets of the same size, because retraining on a
  different feature set moves the score even when what was removed was noise.
  Its most useful output is the list of sections whose removal *improves* the
  model.
- **Phase 0 item 7 was never verified, and was false.** The spec says "verify
  that closed trades stop receiving evolution updates". `update_price` had one
  guard — `if not trade_id: return` — and would append to a CLOSED trade,
  putting post-close prices into `price_evolution`: the field every model
  treats as the pre-close forward walk. The leakage firewall is enforced
  everywhere downstream and was open at the write. It now fails closed on an
  explicit `CLOSED` status only, since absence of a status is not evidence of
  closure.

**32. An aggregation layer must not be able to promote.**
Readme 26.20 forbids a point system: "arbitrary points create false precision
and encourage redundant voting". `ai/trade_quality.py` has no score. It has
one equation —

```text
E[R] = p x reward_R - (1 - p) x 1R
```

— and everything else is a **gate that can only refuse**. Stack every
favourable dimension onto a trade with negative expectancy and the verdict
stays UNACCEPTABLE; that property is asserted in a test, because it is the one
a points system silently loses.

It also withholds rather than computes when the calibration model reports the
stated probability carries no ranking information: E[R] from an uninformative
p is arithmetic on noise, and a confident number there is worse than none.

**33. Undefined is not neutral.**
`close_location_value` returns None for a zero-range bar, never 0.0. Zero means
"closed exactly mid-range" — a real observation — and a bar that cannot be
measured must not be indistinguishable from a balanced one. Absorption
likewise requires high participation **and** a contained range: either alone
is unremarkable, and the disagreement between effort and result is the entire
signal.

## 0.25 Component standards compliance

Audited by `tests/test_component_standards.py`, which runs the checks below
against every component on every test run. It is deliberately a test and not a
document: a compliance table maintained by hand is a claim, and standard 31
exists because this file already carried two false ones.

**33 components**, each verified for:

| Check | Rule |
|---|---|
| module-level `get_status()` / `self_check()` | standard 12 |
| `ok` is tri-state (True / False / **None**) | standard 19 |
| refuses garbage input rather than passing | standard 20 |
| does not report valid data as broken | the other direction of 19 |
| reachable from `/verify` | standard 20 |

What the audit found on its first run:

- **The single decode boundary was the one component `/verify` could not
  check.** `price_evolution_bridge` is standard 1 — every model's view of a
  trade passes through it — and it had neither `get_status` nor `self_check`.
  `/verify` had been printing `price_evolution: NO self_check` for as long as
  that endpoint existed, and nobody read it as a gap because it looked like a
  category label. Its `self_check` now proves decoding is idempotent, invents
  no fields (the encoder once stamped `success=False`, `model_version` and an
  encode-time timestamp onto payloads that asserted none of them), and that
  every context feature comes from `analysis_at_open` or `entry`.
- **`aireplay.recorder` had `get_status` as a method only**, so the
  module-level call every other component answers raised `AttributeError` —
  the same shape as the `non_rl_intelligence` defect in standard 20.
- **Four `self_check`s returned `ok=True` on pure garbage.** Their synthetic
  invariants genuinely held; that is the problem. Invariants hold on *any*
  input — that is what makes them invariants and what makes them worthless as
  evidence that a pipeline works. All four now distinguish undecodable input
  (`False`, the data path is broken) from decodable-but-insufficient (`None`,
  not exercised).

**34. Classify a check by what it consumes, not by what it accepts.**
The first run of the audit produced four failures that were the *test's* fault.
`ai_gnn`, `root_cause_trackers` and `recorder` all accept a `trades` argument
and ignore it — their subject is a graph, a snapshot index and a buffer — and
`clv_absorption` consumes OHLCV bars, not trades. Feeding trades to a bar
analyser and calling the refusal a defect is a category error, and the fix was
to classify each component by its actual subject and state the exemptions
explicitly, so the garbage test's silence about five modules is documented
rather than accidental.

The general form: a signature tells you what a function will accept, never
what it means. An audit written against signatures measures the wrong thing
confidently.


**35. Telemetry in a trading path is judged by what it cannot do.**
`aireplay/live_recording.py` wires the recorder into `EntryEngine`, which
unblocks the pre-trade timeline replay needed and never had:
`CANDIDATE_DETECTED`, `MICROSTRUCTURE_TRIGGER`, `CONFIRMATION`, `RL_DECISION`,
`RISK_APPROVAL`. That was the single limitation stamped on
`replay_engine.get_status()`.

It runs between a signal and a real order, so the design is a list of
refusals:

| Guarantee | Why |
|---|---|
| **OFF by default** (`AIREPLAY_RECORD_LIVE`) | telemetry that switches itself on in a live system is a change nobody approved |
| **Never raises into the caller** | a trade must not fail to open because its telemetry did |
| **Never mutates the decision** | a recorded run and an unrecorded run must be the same run |
| **No network in the hot path** | pre-trade events buffer in memory; nothing is written until a ticket exists |
| **Unbound candidates are discarded** | a fictional trade in the record is worse than a missing one — every model downstream treats it as fact |

The test that matters is `test_recording_does_not_change_the_decision`: the
same inputs through `EntryEngine` with recording on and off must produce an
identical dict. If those can differ, the recording is no longer telemetry —
it is part of the strategy, and every replay built on it describes a system
that did not run.

**One seam, not fifteen.** The events are emitted from
`EntryEngine.get_entry_decision`, the wrapper — not from the eight return
paths inside the implementation. This codebase already learned that lesson:
diagnostics were hand-written into three of those paths and silently missing
from the other five, which are over 90% of real decisions. The wrapper fix was
structural there and is structural here, and each avoided touch point is one
less place a change can go wrong in an order path.

Rejections are recorded, not just entries — those five early exits are most of
what actually happens, and a timeline covering only entries covers almost
nothing. They are buffered and dropped when no ticket ever arrives, because
there is no trade document to attach them to.

**Historical trades are unaffected.** These events exist only for trades taken
after the flag is enabled. Replay still refuses to synthesise them backwards.

**36. Initialisation that depends on `__main__` is initialisation that will
not happen.**
`initialize_services()` was reachable only from `main()`, so GNN and
adversarial existed only when `ai_controller.py` was run as a script. Serve
the same app any other way — `gunicorn ai_controller:app`, `waitress-serve`,
importing `app` into a parent process, a test client — and `_gnn` and
`_adversarial` stay None for the life of the process. Every GNN and
adversarial endpoint answers "not initialized" with a 400 while the server
returns 200 on everything else and looks entirely healthy.

That is why `/verify` reported them `available: False` for as long as that
endpoint existed. Initialisation now runs from a `before_request` hook:
idempotent, measured at 0.00s once Firebase is a cached singleton, and safe to
attempt per request. Not at import — importing a module should not open a
database connection, and the test suite imports this app.

`available: False` now carries `unavailable_reason`. A bare False with no
explanation is what sent this investigation down the wrong path twice.

**37. "Offline mode" that never reconnects is data loss with a reassuring
name.**
`api/` was missing from the Firebase credential search, so any process started
from the package root fell back to offline mode. The service's own warning
says what that means:

```text
Running in OFFLINE MODE - writes will be queued in memory
and NEVER flushed to Firestore (the batch processor only
starts once initialized=True) until this is fixed.
```

So GNN and adversarial A/B state, saved models and training history were being
written into a queue that had no consumer. The bot worked only because it
happens to run from `api/` — every other entry point, including the replay CLI
and the AI controller, silently discarded everything it wrote.

Fixed once in the search list rather than per caller (standard 10), and
resolved from the module's own path rather than the working directory, so it
no longer matters where a process is started from.

## 0.3 Verification

```bash
cd easytradifyPythonBot
python -m pytest            # 730 tests
```

| Endpoint | Purpose |
|---|---|
| `POST /verify` | Whole-layer gate over all 33 components, including the decode boundary and the recorder. `ok` only if every component passes; `null` if no trades supplied |
| `GET /rl/status`, `GET /non_rl/status` | Capability and fit state |
| `POST /rl/self_check`, `POST /non_rl/self_check` | Prove the data path (422 on failure) |
| `GET /adversarial/ab_test` | Control vs test, and the verdict |
| `POST /adversarial/ab_test/rollout` \| `/track` | Set rollout \| record a settled trade |
| `GET /exit_model/status` | Gates, feature count, whether a model is loaded |
| `POST /exit_model/self_check` | Prove causal sampling and group-disjoint splits |
| `POST /exit_model/train` | Train + validate; returns the promotion verdict and why |
| `GET /target_model/status` | Label definition, population, thresholds, gates |
| `POST /target_model/self_check` | Prove in-profit filtering and split disjointness |
| `POST /target_model/train` | Train + validate; returns the promotion verdict and why |
| `GET /calibration/status` | Method, measures, why it does not gate on AUC |
| `POST /calibration/self_check` | Extraction + whether the probability is worth calibrating |
| `POST /calibration/train` | Fit + reliability curves before/after, promotion verdict |
| `GET /abstention/status` | Decline rules, conditions scanned, why not meta-labeling |
| `POST /abstention/self_check` | Which pre-entry conditions are populated |
| `POST /abstention/train` | Discover decline rules + out-of-sample verdict |
| `GET /replay/phase1/status` | What Phase 1 implements and cannot recover |
| `POST /replay/phase1/extract` | Trades -> canonical records + leakage reports |
| `GET /rules/experiments` | Rule experiments and the evidence that motivated them |
| `GET /rules/experiments/<veto>` | The governed A/B verdict for one rule |
| `GET /rules/experiments/<veto>/recommendation` | **The specific rule edit to make**, or NO CHANGE with the reason |
| `POST /rules/experiments/<veto>/track` | Record one settled trade into its arm |
| `GET /replay/live_recording/status` | Is the pre-trade timeline being recorded, and the guarantees |
| `POST /replay/live_recording/self_check` | Proves OFF-by-default, no mutation, no fictional trades |
| `GET /clv_absorption/status` | CLV formula, thresholds, zero-range policy (phase 2.2) |
| `POST /clv_absorption/analyze` | Where participation and movement disagreed |
| `GET /trade_quality/status` | Why this is an expectancy, not a point score (phase 2.7) |
| `POST /trade_quality/assess` | E[R] verdict, or a refusal with its reason |
| `GET /ablation/status` | Ablation target and noise band (phase 3.9) |
| `POST /ablation/study` | Per-section contribution; names sections that HURT |
| `GET /replay/stress/status` | Stress families, magnitudes, simulation disclaimer |
| `POST /replay/stress` | Breaking points and cohort fragility (modifies prices; not historical truth) |
| `GET /gnn/embeddings` | Per-asset embeddings from the live graph (phase 5.2) |
| `GET /gnn/conflicts` | Assets moving against their correlated peers (phase 5.5) |
| `POST /gnn/validate` | Does GNN context predict anything out of sample (phase 5.7) |
| `POST /adversarial/replay/probe` | Does the DIAGNOSIS survive perturbation (phase 6.6) |
| `GET /rl/policies/status` | Policy class, sizing limits, why not deep RL |
| `POST /rl/policies/train` | Management or exit policy + permutation control (phase 7.2/7.3) |
| `POST /rl/policies/size` | Bounded size with every clamp reported (phase 7.4) |
| `POST /rl/policies/deploy` | Version, gate and start a 10% rollout (phase 7.8) |
| `GET /root_cause/status` | Policy and capability of analyzer, tracker and adapter |
| `POST /root_cause/self_check` | Proves it reads real evidence -- and refuses without it |
| `POST /root_cause/analyze` | Diagnose one stored trade end to end (adapter builds the bundle) |
| `POST /root_cause/coverage` | Which evidence sections a trade actually supports |
| `POST /root_cause/narrative` | The diagnosis in plain language, every claim citing its evidence |
| `GET /narrative/status` | How the narrative is produced, and why no language model |
| `GET /performance/status` | Scorecards for tracked models, plus governed models that are not |
| `POST /performance/record` | Record what a model said and what happened |
| `GET /performance/<model>/scorecard` | Expectancy in R with the sample size behind it |
| `GET /performance/<model>/drift` | Recent vs baseline, as a difference with a standard error |
| `GET /performance/ranking` | Models by expectancy; the unrankable are named |
| `GET /performance/ensemble` | Whether model agreement carries information |
| `POST /performance/self_check` | Scoring, gating, drift and agreement on known inputs |
| `GET /governance/status` | A/B state and version registry for every governed model |
| `POST /governance/self_check` | Assignment determinism, verdict honesty, rollback actually moves |
| `GET /governance/<model>/ab_test` | Verdict with p-value; `verdict_is_actionable` is the only automation key |
| `GET /governance/<model>/ab_test/assign/<id>` | Which arm a trade falls in, checkable from outside |
| `POST /governance/<model>/ab_test/track` | Record one settled trade into its arm |
| `POST /governance/<model>/ab_test/rollout` | Set the test-arm share (409 for natively-governed models) |
| `POST /governance/<model>/ab_test/reset` | Discard arm counters (destructive; the counters are the experiment) |
| `GET /governance/<model>/registry` | Version history, active version, whether rollback is possible |
| `POST /governance/<model>/promote` | Make a registered version active |
| `POST /governance/<model>/rollback` | Revert to last known good; **409** when there is nothing to revert to |
| `GET /synthesis/status` | Confirms no score/direction is produced |
| `POST /synthesis/synthesise` | Hierarchy, conflicts, uncertainty, determinism hash |

A new module is done when: it reads through `to_canonical()`, passes a leakage
test that can fail, exposes `get_status()`/`self_check()`, is registered in
`/verify`, and ships a regression test per bug fixed.

## 0.35 AI_MarketReplay build progress

Built in the order section 60 specifies.

| Phase | Items | Status |
|---|---|---|
| 0 — Legacy inventory & preservation gate | 10 | **Complete** — inventory and KEEP/REDESIGN statuses in 0.1; encode/decode compatibility, `trade_{ticket}` identity and legacy behaviour characterised by the test suite; adapters built before anything was deleted |
| 1 — Data Foundation | 6 | **Complete** — `ai/aireplay/`, 42 tests |
| 2 — Deterministic Intelligence | 10 | **Complete** — items 8–10 in `ai/market_synthesis.py`; items 1, 3–6 reused from `core/` (`vwap.py`, `rvam.py`, `asset_analysis_smc.py`, `indicators.analyze_micro_structure`) per 26.1. Items 2 and 7 did NOT exist and were built: `core/clv_absorption.py`, `ai/trade_quality.py` |
| 3 — Replay | 14 | **Complete** — items 1–7 and 14 in `replay_engine.py` (30), `counterfactual.py` (23), `recorder.py` (23), `consistency.py` (17); item 10 stress replay in `stress.py`; item 8 A/B in `model_governance.py`; item 9 ablation MEASUREMENT built in `ai/ablation.py` (`ablate_components` produced ablated feature sets and nothing scored them); items 11–13 in `core/replay_forensics.py`, `core/phase_report.py`, `core/replay.py`, `ai_reinforcement.CounterfactualSimulator` |
| 4 — Non-RL | 8 | **Complete** — all eight in `non_rl_intelligence.py`: OutcomePredictor, SetupQualityModel, FailureClassifier, RegimeModel, AnomalyDetector, ProbabilityCalibrator, ComponentAttributionEngine, PatternDiscovery |
| 5 — GNN | 7 | **Complete** — graph/context/correlation in `ai_gnn.py`, A/B native; embeddings, divergence-conflict and OOS validation in `gnn_analysis.py` |
| 6 — Adversarial | 6 | **Complete** — 28 attack families in `ai_adversarial.py`; replay integration in `adversarial_replay.py` |
| 7 — RL | 8 | **Complete** — entry timing and replay training in `ai_reinforcement.py`; management, exit, bounded sizing and controlled deployment in `rl_policies.py` |
| 8 — Later Research | — | **Not planned** — self-supervised, world models, diffusion and meta-learning are all rejected on evidence in 0.4; the spec gates them on justification that does not exist at this data size |

**Phase 1** (`ai/aireplay/`) implements the canonical trade schema (22), immutable
snapshots (26), temporal metadata (23), feature availability metadata (24), the
Decision Genome (21) and replay extraction. Its defining property: the temporal
firewall is *derived from a field registry* rather than a blocklist, so an
unregistered field fails closed as `UNCLASSIFIED` instead of being silently
trusted. Extraction is lossless — verified at 107 source leaves, 0 lost — with
`decision_state.coverage` reporting mapped/carried/dropped per trade.

**Phase 2 items 8–10** (`ai/market_synthesis.py`) implement the canonical
synthesis (10.2), hierarchical reasoning (10.3), explicit conflict
representation (10.4), the missing/stale/zero distinction (10.7) and replay
determinism (10.8). It produces **no score and no direction** — section 10.1
prohibits exactly that, and the module is shaped by the prohibition.

**Phase 3, previously blocked:** only `EXECUTION` and `CLOSE` snapshots were recoverable, because the live pipeline emitted nothing else. `aireplay/live_recording.py` now emits the pre-trade events for new trades when `AIREPLAY_RECORD_LIVE` is set (standard 35). Historically stored trades are unchanged and always will be.

Originally: The live pipeline never emitted `CANDIDATE_DETECTED`,
`CONFIRMATION`, `MICROSTRUCTURE_TRIGGER`, `RL_DECISION` or `RISK_APPROVAL`, and
first-divergence detection needs that timeline. Emitting them is a live-pipeline
change, not an extraction one.

## 0.4 Planned AI features

### The constraint these are designed around

Replay measured **direction entropy at 1.0000** — a fair coin at every timeframe
tested. Meta-labeling independently confirmed it (AUC 0.5034 against a shuffled
control at 0.5092) and was correctly refused promotion. **No model will produce a
high win rate from this data.** Anything that appears to is fitting noise.

Expectancy does not require one:

```text
E = (win_rate × avg_win) − (loss_rate × avg_loss)
```

With win rate pinned near 50%, the whole lever is the **payoff ratio**. Cutting
losers at −0.5R while winners reach +2R is strongly positive at a coin-flip hit
rate. Every feature below therefore targets payoff asymmetry, selectivity, or
sizing — never hit rate.

### Ranked by expectancy impact

| # | Feature | Mechanism | Status |
|---|---|---|---|
| 1 | **Mid-trade exit model** | Cuts `avg_loss` | **Built** — `exit_model.py`, 42 tests, awaiting real trades |
| 2 | **Adaptive target extension** | Raises `avg_win` | **Built** — `target_model.py`, 28 tests |
| 3 | **Selective abstention** | Raises expectancy by subtraction *and* addition | **Built** — `abstention_model.py`, 36 tests |
| — | **Probability calibration** | Makes every downstream gate honest | **Built** — `calibration_model.py`, 34 tests |

**1. Mid-trade exit model.** Classifies an *unfolding* trade as deteriorating from
its `price_evolution` path so far. Does not predict direction — that is the coin
flip. Trains on data already stored and never read. Turns −1R into −0.4R across
the loss distribution; one avoided full loss outweighs two extra wins.

**2. Adaptive target extension.** Whether to extend TP or close, conditioned on
realized volatility and structure. Current ATR-based targets are static, and the
largest expectancy gains live in the right tail. Same feature basis as #1, opposite
question.

**3. Selective abstention.** Learn where edge exists and decline elsewhere.
Already-measured example: spread/stop ≥ 0.8 → 18.6% win rate. Trading less is a
legitimate, often the largest, expectancy improvement.

### Not planned, and why

| Rejected | Reason |
|---|---|
| Diffusion / learned world model | Layer 4 of the generator hierarchy; the spec's own *"Why Diffusion Is Not the First Step"*. Unvalidatable against a dataset this size |
| Deep RL for entry direction | Direction is a coin flip; RL cannot learn absent signal |
| Meta-labeling (retry) | Already tested and refused on evidence. Do not re-litigate without new features |
| More indicators | ~30 exist; family-weight calibration measured `trend` at 0.00 — negative discrimination on all four test symbols |

### Evaluation standard for every feature above

AUC is **not** the acceptance criterion. Each must show an **expectancy delta in R**
on held-out trades, against a shuffled-label control, with trade-grouped splits
(samples from one trade may never straddle train and test). A feature that improves
AUC without improving expectancy is rejected — the same standard that correctly
stopped meta-labeling from shipping.

---

## 1. Vision

EasyTradify combines deterministic market intelligence, machine learning, graph intelligence, adversarial robustness testing, AI Market Replay, counterfactual analysis, specialized reinforcement learning, portfolio risk controls, and controlled execution.

The central design principle is:

```text
Raw Market Data
      ↓
Deterministic Market Intelligence
      ↓
Market Synthesis
      ↓
GNN Market Context
      ↓
Non-RL Intelligence
      ↓
Trade Quality
      ↓
Specialized RL
      ↓
Portfolio Risk Gate
      ↓
Execution
      ↓
Observed Market Evolution
      ↓
AI Market Replay
      ↓
Learning / Diagnosis / Validation
      └──────────────────────────────→
```

AI is not a collection of independent BUY/SELL voters. Each AI component has a specific job, measurable inputs, outputs, validation criteria, and provenance.

---

# 2. Core Design Philosophy

EasyTradify follows these rules:

1. **Deterministic market intelligence comes first.**
2. **Features are evidence, not independent AI agents.**
3. **No simplistic majority voting between models.**
4. **Microstructure is a final trigger, not the primary market predictor.**
5. **Trade Quality is downstream of validated probabilities and expectations.**
6. **Portfolio Risk can veto AI decisions. AI cannot override hard risk limits.**
7. **Historical observations are immutable.**
8. **Future information may be used for labels/outcomes and replay scoring, never as decision-time features.**
9. **Every learned model has a version and validation record.**
10. **Live deployment requires explicit promotion after validation.**
11. **Replay is a first-class system, not merely a debugging feature.**
12. **Generative models and adaptive learning remain research features until independently validated.**

---

# 3. Architecture

```text
                         ┌───────────────────────┐
                         │      Market Data      │
                         └───────────┬───────────┘
                                     ↓
                 ┌────────────────────────────────────┐
                 │ Deterministic Market Intelligence  │
                 │                                    │
                 │ Structure / Liquidity / FVG        │
                 │ VWAP / RVAM / Absorption           │
                 │ Order Flow / Volume Profile        │
                 │ Momentum / Volatility / Sessions   │
                 │ Microstructure                     │
                 └────────────────┬───────────────────┘
                                  ↓
                       ┌────────────────────┐
                       │ Market Synthesis   │
                       └─────────┬──────────┘
                                 ↓
                       ┌────────────────────┐
                       │       GNN          │
                       │ Cross-market graph │
                       └─────────┬──────────┘
                                 ↓
                 ┌────────────────────────────────┐
                 │      Non-RL Intelligence       │
                 │                                │
                 │ Outcome / Quality / Regime     │
                 │ Failure / Attribution / Anomaly│
                 │ Calibration / Patterns         │
                 └───────────────┬────────────────┘
                                 ↓
                       ┌────────────────────┐
                       │   Trade Quality    │
                       └─────────┬──────────┘
                                 ↓
                  ┌─────────────────────────────┐
                  │     Specialized RL          │
                  │                             │
                  │ Entry / Management / Risk   │
                  │ Exit Optimization           │
                  └──────────────┬──────────────┘
                                 ↓
                       ┌────────────────────┐
                       │ Portfolio Risk     │
                       │       Gate         │
                       └─────────┬──────────┘
                                 ↓
                       ┌────────────────────┐
                       │     Execution      │
                       │       + MT5        │
                       └─────────┬──────────┘
                                 ↓
                       ┌────────────────────┐
                       │ Market Evolution   │
                       └─────────┬──────────┘
                                 ↓
                       ┌────────────────────┐
                       │   AI Market Replay │
                       └─────────┬──────────┘
                                 ↓
               ┌────────────────────────────────────┐
               │ Diagnosis / Counterfactual / A-B   │
               │ Ablation / Stress / Walk-Forward    │
               │ OOS Validation / Learning Datasets  │
               └────────────────────────────────────┘
```

---

# 4. Microservices

## 4.1 Discovery Server

Directory:

```text
discovery-server/
```

Port:

```text
8761
```

Technology:

- Spring Cloud Netflix Eureka

Responsibilities:

- service registration
- service discovery
- service health visibility

---

## 4.2 Execution Service

Directory:

```text
execution-service/
```

Port:

```text
8081
```

Responsibilities:

- trade execution
- position management
- SL/TP
- trailing stop
- MT5 connectivity
- account information
- symbol information
- market conditions
- lot-size calculation
- trade history
- webhooks
- copy trading

### Execution API

```text
POST /api/v1/execution/trade
POST /api/v1/execution/analyse
POST /api/v1/execution/probability

POST /api/v1/execution/position/close
PUT  /api/v1/execution/position/partial-close
POST /api/v1/execution/positions/close/all

GET  /api/v1/execution/positions
GET  /api/v1/execution/positions/open
GET  /api/v1/execution/position/{ticket}

PUT  /api/v1/execution/position/stop-loss
PUT  /api/v1/execution/position/take-profit

PUT  /api/v1/execution/position/trailing/enable
PUT  /api/v1/execution/position/trailing/disable
PUT  /api/v1/execution/position/trailing/update

GET /api/v1/execution/trailing/status
GET /api/v1/execution/trailing/stats

GET /api/v1/execution/account
GET /api/v1/execution/symbol/{symbol}
GET /api/v1/execution/symbols

GET /api/v1/execution/market/status/{symbol}
GET /api/v1/execution/market/volatility/{symbol}
GET /api/v1/execution/market/spread/{symbol}
GET /api/v1/execution/market/conditions/{symbol}

POST /api/v1/execution/mt5/connect
POST /api/v1/execution/mt5/disconnect

GET  /api/v1/execution/trades/history
POST /api/v1/execution/calculate-lot
```

### Copy-trade API

```text
POST /api/v1/copy-trade/execute
POST /api/v1/copy-trade/webhook/trade
POST /api/v1/copy-trade/webhook/trailing
POST /api/v1/copy-trade/webhook/test

GET /api/v1/copy-trade/webhook/health
GET /api/v1/copy-trade/webhook/debug
GET /api/v1/copy-trade/status
```

---

# 5. Monitor Service

Directory:

```text
monitor/
```

Port:

```text
8082
```

Responsibilities:

- symbol discovery
- market scanning
- confidence and quality scoring
- filtering
- execution monitoring
- closed-trade tracking
- fast-entry checks
- webhook support
- health monitoring
- watchdogs
- automatic recovery/restart
- synchronization with broker positions

API:

```text
POST /api/v1/monitor/start
POST /api/v1/monitor/stop
POST /api/v1/monitor/refresh

GET /api/v1/monitor/status
GET /api/v1/monitor/top-symbols
GET /api/v1/monitor/filtered-symbols
GET /api/v1/monitor/logs
GET /api/v1/monitor/executions
GET /api/v1/monitor/closed-trades
```

The monitor must continue operating after recoverable scan-cycle failures.

Broker positions remain the external execution authority; after a process restart, the monitor must re-synchronize with broker state.

---

# 6. Portfolio Risk Management

Directory:

```text
porfolio_risk_management/
```

Port:

```text
8083
```

Responsibilities:

- portfolio status
- P&L
- drawdown
- risk limits
- trading permissions
- funded-account compliance
- portfolio statistics
- configurable risk policy

API:

```text
GET /api/v1/portfolio/status
GET /api/v1/portfolio/summary
GET /api/v1/portfolio/config
PUT /api/v1/portfolio/config

GET /api/v1/portfolio/config/{field}
PUT /api/v1/portfolio/config/{field}

POST /api/v1/portfolio/check-trading-allowed

GET /api/v1/portfolio/max-risk-per-trade
GET /api/v1/portfolio/stats
GET /api/v1/portfolio/drawdown
GET /api/v1/portfolio/funded-compliance

POST /api/v1/portfolio/refresh
```

## Critical rule

```text
AI Decision
    ↓
Portfolio Risk Gate
    ↓
ALLOW / MODIFY WITHIN POLICY / BLOCK
```

AI cannot override hard portfolio limits.

---

# 7. AI Service

Directory:

```text
ai/
```

Port:

```text
8084
```

The AI service contains specialized components rather than one generic AI.

---

# 8. Deterministic Market Intelligence

The deterministic layer is the foundation of the AI system.

## Structure

- swing detection
- market structure
- BOS
- CHOCH
- higher-timeframe structure
- microstructure transitions

## Liquidity

- liquidity zones
- liquidity sweeps
- stop-run context
- liquidity quality

The two historical liquidity-sweep implementations should be unified into one canonical engine.

## Order Blocks

- detection
- validation
- mitigation
- lifecycle state

## Fair Value Gaps

FVG is treated as a lifecycle:

```text
DETECTED
   ↓
VALIDATED
   ↓
ACTIVE
   ↓
PARTIALLY_FILLED
   ↓
MITIGATED / INVALIDATED
```

The exact lifecycle implementation must preserve timestamps and state transitions.

## VWAP

VWAP is a first-class deterministic engine.

Potential state:

- session VWAP
- deviation bands
- distance from VWAP
- VWAP slope
- interaction/rejection
- regime context

## RVAM

Relative Volume / Activity Metrics provide normalized participation context.

## CLV Absorption

Close Location Value and absorption analysis help identify situations where price movement and participation disagree.

## Volume Profile

- value area
- POC
- high/low-volume areas
- acceptance/rejection context

## Order Flow

- buy/sell pressure
- imbalance
- directional participation
- flow transitions

## Momentum and Volatility

- RSI
- RSI divergence
- EMA20
- EMA200
- Stochastic
- Bollinger Bands
- ATR
- volatility state

## Sessions

- session identification
- session behavior
- session transitions
- session-specific context

---

# 9. Microstructure

Microstructure is a final trigger layer.

It should not attempt to predict the entire market by itself.

Conceptually:

```text
Macro / Structure
      ↓
Liquidity
      ↓
Context
      ↓
Market Synthesis
      ↓
Microstructure
      ↓
Final Entry Trigger
```

This prevents every indicator from becoming an equal vote.

---

# 10. Market Synthesis

Market Synthesis is the **canonical semantic interpretation of the deterministic market-intelligence layer**.

It is not another indicator, not an ensemble vote, and not a BUY/SELL classifier.

Its job is to transform many deterministic observations into one structured description of the current market state.

```text
Raw Market Data
      ↓
Deterministic Intelligence
      ↓
┌───────────────────────────────────────────────┐
│ Market Synthesis                              │
│                                               │
│ Structure                                     │
│ Liquidity                                     │
│ Imbalance / FVG                               │
│ Value / VWAP / RVAM                           │
│ Volume / Order Flow / Absorption              │
│ Momentum / Volatility                         │
│ Sessions                                      │
│ Multi-timeframe relationships                 │
│ Microstructure                                │
│ Conflicts                                     │
│ Regime                                        │
│ Uncertainty                                   │
└───────────────────────────────────────────────┘
      ↓
GNN / Non-RL / Decision Genome / Replay / RL
```

## 10.1 Canonical Principle

The old architecture must **not** be recreated as:

```text
RSI → score
MACD → score
FVG → score
VWAP → score
GNN → score
RL → score

sum(scores)
↓
BUY / SELL
```

This is explicitly prohibited.

Different observations have different semantic roles.

For example:

```text
Structure
    tells the system about market organization.

Liquidity
    tells the system where price may interact with resting liquidity.

FVG / imbalance
    tells the system about displacement/inefficiency state.

VWAP / value
    tells the system about value location.

Order flow / absorption
    tells the system about participation and local pressure.

Microstructure
    tells the system whether the immediate trigger is actually occurring.

Volatility
    tells the system how unstable the environment is.

GNN
    tells the system about relationships outside the local instrument.

Regime
    tells the system which behavioral environment is active.
```

These are **different dimensions of information**, not interchangeable votes.

---

## 10.2 Market Synthesis Internal Structure

The canonical output should be logically equivalent to:

```text
MarketSynthesis
├── identity
│   ├── symbol
│   ├── timestamp
│   ├── data_version
│   └── feature_version
│
├── structural_state
│   ├── trend
│   ├── swing_structure
│   ├── BOS
│   ├── CHOCH
│   ├── structure_strength
│   └── structural_levels
│
├── liquidity_state
│   ├── liquidity_zones
│   ├── recent_sweeps
│   ├── sweep_direction
│   ├── sweep_quality
│   └── unresolved_liquidity
│
├── imbalance_state
│   ├── active_FVGs
│   ├── FVG_age
│   ├── FVG_fill_percentage
│   ├── FVG_status
│   ├── displacement_quality
│   └── invalidated_FVGs
│
├── value_state
│   ├── VWAP
│   ├── distance_to_VWAP
│   ├── RVAM
│   ├── value_area
│   └── location_relative_to_value
│
├── participation_state
│   ├── volume
│   ├── volume_profile
│   ├── order_flow
│   ├── CLV
│   ├── absorption
│   └── participation_quality
│
├── momentum_state
│   ├── momentum
│   ├── momentum_acceleration
│   ├── RSI/divergence
│   ├── stochastic
│   └── other validated momentum observations
│
├── volatility_state
│   ├── ATR
│   ├── realized_volatility
│   ├── volatility_regime
│   └── abnormal_volatility
│
├── session_state
│   ├── session
│   ├── market_open
│   ├── session_age
│   └── session_characteristics
│
├── timeframe_relationships
│   ├── M1
│   ├── M5
│   ├── M15
│   ├── H1
│   ├── H4
│   ├── D1
│   ├── alignment
│   └── divergence
│
├── microstructure_state
│   ├── local_direction
│   ├── absorption
│   ├── momentum_burst
│   ├── local_break
│   ├── trigger_quality
│   └── trigger_age
│
├── regime_state
│   ├── regime
│   ├── regime_confidence
│   ├── regime_transition
│   └── regime_age
│
├── conflicts
│   ├── structural_conflicts
│   ├── timeframe_conflicts
│   ├── liquidity_conflicts
│   ├── value_conflicts
│   ├── GNN_conflicts
│   └── execution_conflicts
│
├── uncertainty
│   ├── missing_data
│   ├── stale_data
│   ├── model_uncertainty
│   ├── conflicting_evidence
│   └── overall_uncertainty
│
└── synthesis_metadata
    ├── evidence
    ├── source_timestamps
    ├── feature_versions
    └── computation_status
```

The exact Python classes may differ, but the **responsibility boundaries must remain**.

---

## 10.3 Synthesis Is Hierarchical, Not Additive

Market Synthesis should reason in a hierarchy.

Example:

```text
1. Is the market structurally coherent?
        ↓
2. Where is price relative to liquidity/value?
        ↓
3. What is the participation/imbalance state?
        ↓
4. What regime is active?
        ↓
5. Are timeframes aligned or conflicting?
        ↓
6. Is the setup approaching a valid trigger?
        ↓
7. Is microstructure confirming the expected local transition?
        ↓
8. What uncertainty/conflicts remain?
```

It should not reduce these questions to arbitrary points.

---

## 10.4 Explicit Conflict Representation

Conflicts must be preserved, not averaged away.

Example:

```text
H1 structure = bullish
M5 structure = bullish
M1 = bearish pullback
VWAP = below price
liquidity = sell-side sweep
microstructure = bullish reversal
GNN = neutral
```

This should be represented as a coherent state:

```text
higher_timeframe_bias = bullish
local_state = corrective
liquidity_event = sell_side_sweep
trigger_state = bullish_reversal
cross_market_context = neutral
```

Not:

```text
bullish = +70
bearish = -30
net = +40
```

The relationship is more informative than the arbitrary sum.

---

## 10.5 Market Synthesis Output Is Input to Other Systems

### GNN

GNN receives the structured local market state plus cross-asset data.

### Non-RL

Non-RL receives the state and predicts:

- outcome probabilities
- setup quality
- failure probability
- regime suitability
- anomaly probability
- time-to-event where validated

### Decision Genome

The exact synthesized state at a decision point is recorded in the Decision Genome.

### Replay

Replay reconstructs the historical synthesis using only information available at that time.

### RL

RL receives the synthesized state as part of its state representation. RL does not rebuild market intelligence independently.

---

## 10.6 Microstructure Has a Special Role

Microstructure is **not the primary market predictor**.

The canonical hierarchy is:

```text
Market Synthesis
      ↓
Context / setup
      ↓
Microstructure
      ↓
Trigger validation
```

Microstructure answers:

> "Is the immediate price-action condition required for execution actually occurring now?"

It should therefore be treated as a **final trigger/confirmation layer**, not as a replacement for structural context.

---

## 10.7 Missing Data and Stale Data

Market Synthesis must explicitly distinguish:

```text
value = 0
```

from:

```text
value unavailable
```

and:

```text
value stale
```

Every important field should carry or inherit:

```text
timestamp
available_at
source
freshness
quality
```

A missing GNN result must not silently become:

```text
GNN = neutral
```

unless that fallback is explicitly represented.

Example:

```json
{
  "gnn": {
    "status": "UNAVAILABLE",
    "reason": "timeout",
    "fallback_used": false
  }
}
```

---

## 10.8 Market Synthesis Must Be Replayable

For every historical decision:

```text
same input snapshot
+
same feature version
+
same configuration
+
same model version
```

must produce a reproducible synthesis, subject to explicitly documented nondeterminism.

If the new synthesis differs from the original recorded synthesis:

```text
Replay
    ↓
compare original vs reconstructed
    ↓
identify first divergence
    ↓
determine whether the difference came from:
    data
    feature calculation
    configuration
    model version
    implementation
```

This makes Market Synthesis part of the audit system rather than an opaque black box.

---

## 10.9 Legacy Root-Cause Mapping

The old root-cause system extracted 21 categories including trend, supply/demand, Wyckoff, higher-timeframe alignment, ADX, volatility, news, session, support/resistance, FVG, M15 divergence, vetoes, breakout, candlesticks, microstructure, golden signals, discount, candle progress, spread, volume, and indicators. fileciteturn25file0L232-L288

These observations are valuable, but their old architecture must not become the new synthesis architecture.

The correct migration is:

```text
Legacy extractor
      ↓
canonical feature adapter
      ↓
Market Synthesis field
```

not:

```text
21 legacy analyzers
      ↓
21 scores
      ↓
weighted sum
```

---

# 11. GNN Market Intelligence

GNN is a core component.

Its role is:

> **What does the rest of the market tell us about this market state?**

The GNN models relationships between instruments, sectors, correlated assets, macro proxies, and other graph nodes defined by the project.

It should provide context rather than act as an autonomous BUY/SELL authority.

## GNN capabilities

- cross-market context
- correlations
- divergences
- correlation changes
- conflict detection
- graph embeddings
- structured insights
- A/B testing
- result tracking

## Existing API

```text
GET  /api/v1/ai/gnn/status
GET  /api/v1/ai/gnn/context/{symbol}
GET  /api/v1/ai/gnn/insights/{symbol}
GET  /api/v1/ai/gnn/correlations/{symbol}
GET  /api/v1/ai/gnn/divergences/{symbol}
GET  /api/v1/ai/gnn/suggestions/{symbol}
GET  /api/v1/ai/gnn/conflict/{symbol}

GET /api/v1/ai/gnn/ab-test
GET /api/v1/ai/gnn/heatmap
GET /api/v1/ai/gnn/correlation-changes/{symbol}

POST /api/v1/ai/gnn/refresh
POST /api/v1/ai/gnn/reset
POST /api/v1/ai/gnn/ab-test/rollout
POST /api/v1/ai/gnn/track-result
```

`heatmap` is a visualization/reporting output, not the core intelligence mechanism.

---

# 12. Non-RL Intelligence

The Non-RL layer answers:

> **What is likely to happen, what happened historically, and why did decisions fail?**

Components:

- outcome prediction
- setup quality prediction
- failure classification
- component attribution
- regime modeling
- anomaly detection
- pattern discovery
- probability calibration
- time-to-event estimation
- decision explanation
- experiment/validation engine

## Important limitations

Pattern and regime clusters are descriptive unless causal evidence is established.

Failure classification is provisional until sufficient historical labels exist.

Attribution must not be described as causal merely because a feature correlates with failure. Production attribution should use robust held-out techniques such as permutation-based or SHAP-like methods where appropriate.

Probability calibration requires separate validation data and sufficient sample sizes.

---

# 13. Counterfactual Engine

The Counterfactual Engine asks:

> **What would have happened if we had made a different decision?**

Examples:

```text
Actual:
ENTER at T0 → loss

Counterfactual:
WAIT 2 candles → no trade

Counterfactual:
ENTER at T1 → winner

Counterfactual:
ENTER at T0 + earlier protection → smaller loss
```

Counterfactual results are used for:

- replay
- RL training
- decision diagnosis
- strategy improvement
- ablation
- experiment generation

Counterfactual outputs must be labeled as simulated/hypothetical unless supported by an actual observed path.

---

# 14. AI Market Replay

AI Market Replay is one of the most important systems in EasyTradify.

It is not simply:

```text
"Show me what happened to the trade."
```

It is:

```text
Reconstruct exactly what the system knew
        ↓
Reconstruct what the market actually did
        ↓
Align the two timelines
        ↓
Find the first material divergence
        ↓
Identify the responsible component/gate
        ↓
Test alternatives
        ↓
Generate validated learning evidence
```

## 14.1 Replay goals

Replay must answer:

1. What did the system know at each moment?
2. Which features were actually available?
3. What did every AI component output?
4. What did the deterministic layer believe?
5. What did the GNN believe?
6. What did Non-RL models predict?
7. What did the RL agent decide?
8. What did the portfolio risk gate allow/block?
9. What did the market actually do afterward?
10. Where did the decision first diverge from reality?
11. Was the failure caused by data, feature interpretation, model prediction, timing, execution, risk, or regime change?
12. What alternative decisions would have produced?
13. Was the failure systematic?
14. Did the proposed fix survive unseen data?

---

# 15. World-Class Replay Architecture

```text
Firebase / Historical Source of Truth
              ↓
        Replay Extractor
              ↓
      Canonical Event Model
              ↓
 ┌───────────────────────────────┐
 │ Decision Genome               │
 │ + Market Reality              │
 │ + Execution Reality           │
 └───────────────┬───────────────┘
                 ↓
         Temporal Aligner
                 ↓
           Replay Engine
                 ↓
        Error Attribution
                 ↓
 ┌───────────────────────────────┐
 │ Component / Gate / Scenario   │
 │ Analysis                      │
 └───────────────┬───────────────┘
                 ↓
        AI Diagnostic Layer
                 ↓
 ┌─────────────────────────────────────┐
 │ Counterfactual Branching            │
 │ A/B Testing                         │
 │ Ablation                            │
 │ Adversarial Replay                 │
 │ Regime-Aware Replay                │
 │ Stress Testing                     │
 └─────────────────┬───────────────────┘
                   ↓
          Walk-Forward Validation
                   ↓
             OOS Validation
                   ↓
      Paper / Controlled Validation
                   ↓
              Promotion
```

---

# 16. Replay Event Model

Replay must operate on an immutable chronological event stream.

Conceptually:

```text
ReplayEvent
├── event_id
├── event_type
├── timestamp
├── source
├── symbol
├── timeframe
├── payload
├── version
├── available_at
└── provenance
```

Examples of event types:

```text
MARKET_SNAPSHOT
FEATURE_SNAPSHOT
STRUCTURE_UPDATE
LIQUIDITY_UPDATE
FVG_UPDATE
VWAP_UPDATE
RVAM_UPDATE
ABSORPTION_UPDATE
ORDERFLOW_UPDATE
MICROSTRUCTURE_UPDATE
SYNTHESIS_UPDATE

GNN_OUTPUT
NON_RL_OUTPUT
ADVERSARIAL_OUTPUT
TRADE_QUALITY_OUTPUT
RL_OUTPUT

RISK_GATE
EXECUTION_REQUEST
EXECUTION_RESULT

POSITION_UPDATE
PRICE_UPDATE
EXIT_EVENT
OUTCOME_EVENT
```

The event stream must preserve order and timestamps.

---

# 17. Replay Decision Timeline

A replay should produce a timeline such as:

```text
T0  Market state reconstructed
T1  Structure state reconstructed
T2  Liquidity state reconstructed
T3  GNN context reconstructed
T4  Non-RL probability reconstructed
T5  Trade Quality reconstructed
T6  Microstructure changes
T7  RL chooses ENTER
T8  Risk gate allows
T9  Execution occurs
T10 Market moves against position
T11 Management decision
T12 Exit
T13 Outcome
```

The replay engine then identifies the first **material** divergence.

Example:

```text
T0-T4: correct
T5: probability slightly miscalibrated
T6: microstructure deteriorates
T7: RL enters despite deteriorating trigger
```

The system should distinguish:

- first anomaly
- first prediction error
- first decision error
- first material divergence
- final outcome

These are not necessarily the same timestamp.

---

# 18. Replay Error Attribution

Replay should classify failures across layers:

```text
DATA
FEATURE
STRUCTURE
LIQUIDITY
FVG
VWAP
RVAM
ABSORPTION
ORDER_FLOW
MICROSTRUCTURE

MARKET_SYNTHESIS
GNN
NON_RL
CALIBRATION
TRADE_QUALITY

RL_ENTRY
RL_MANAGEMENT
RL_EXIT
RL_SIZING

RISK_GATE
EXECUTION
LATENCY
SPREAD
SLIPPAGE
REGIME
UNKNOWN
```

A replay result should contain:

```text
first_divergence
failure_class
responsible_component_candidates
confidence
evidence
affected_decisions
market_regime
```

Attribution must distinguish correlation from causation.

---

# 19. Replay Counterfactual Branching

Replay should create alternative branches from a common historical state.

```text
                 Historical State
                       │
          ┌────────────┼────────────┐
          ↓            ↓            ↓
       ENTER         WAIT        CANCEL
          │            │            │
          ↓            ↓            ↓
     Market Path   Market Path   Market Path
          │            │            │
          └────────────┼────────────┘
                       ↓
                 Compare Outcomes
```

Possible branches:

- different entry time
- different cancellation time
- different stop/protection policy
- different management action
- different sizing within hard limits
- different model version
- feature ablation
- GNN enabled/disabled
- RL enabled/disabled
- strategy configuration A/B

The branch must use the historical market path when evaluating historical counterfactual decisions.

---

# 20. Replay as Learning Infrastructure

## 20.1 Replay Must Consume the Existing Historical Assets

Replay must not invent a parallel historical data store when the existing Firebase trade lifecycle and price-evolution data can serve as the source.

The preferred flow is:

```text
Existing Firebase Trade History
        ↓
Schema/version inspection
        ↓
Replay Extractor
        ↓
Canonical Event Model
        ↓
Decision Snapshots + Market Reality
        ↓
Replay
```

Replay artifacts are separate from the source-of-truth trade record.

If historical records do not contain a required field, mark the field as:

```text
UNKNOWN / UNAVAILABLE
```

Do not reconstruct it from future data and silently label it as original knowledge.



Replay should generate structured datasets for:

- Non-RL training
- RL training
- failure classification
- probability calibration
- component attribution
- regime analysis
- GNN evaluation
- adversarial testing
- A/B experiments
- ablation experiments
- model comparison

Replay is therefore the central feedback mechanism:

```text
Decision
   ↓
Market Outcome
   ↓
Replay
   ↓
Diagnosis
   ↓
Learning Dataset
   ↓
New Candidate Model
   ↓
Walk-Forward
   ↓
OOS
   ↓
Stress Test
   ↓
Controlled Promotion
```

---

# 21. Decision Genome

The Decision Genome is the canonical representation of a decision.

It should capture:

```text
DecisionGenome
├── decision_id
├── symbol
├── strategy
├── timeframe
├── decision_timestamp
│
├── market_state
│   ├── structure
│   ├── liquidity
│   ├── FVG
│   ├── VWAP
│   ├── RVAM
│   ├── absorption
│   ├── volume_profile
│   ├── order_flow
│   ├── momentum
│   ├── volatility
│   ├── sessions
│   └── microstructure
│
├── market_synthesis
│
├── gnn_state
│
├── non_rl_state
│
├── adversarial_state
│
├── trade_quality
│
├── rl_state
│
├── risk_state
│
└── provenance
```

It is the common language shared by live AI, Replay, experiments, and training.

---

# 22. Canonical Firebase Trade Data Contract

Firebase/Firestore stores the evolving trade audit and replay record.

A trade document should follow a versioned logical structure similar to:

```json
{
  "trade_id": "trade_<ticket>",
  "schema_version": "1.x",
  "ticket": 123456,
  "symbol": "EURUSD",
  "direction": "BUY",
  "strategy": "SMC",
  "timeframe": "M5",

  "timestamps": {
    "created_at": "...",
    "decision_at": "...",
    "entry_at": "...",
    "exit_at": "...",
    "updated_at": "..."
  },

  "decision_state": {
    "market_snapshot": {},
    "deterministic": {
      "structure": {},
      "liquidity": {},
      "order_blocks": {},
      "fvg": {},
      "vwap": {},
      "rvam": {},
      "clv_absorption": {},
      "volume_profile": {},
      "order_flow": {},
      "momentum": {},
      "volatility": {},
      "sessions": {},
      "microstructure": {}
    },
    "market_synthesis": {}
  },

  "ai_state": {
    "gnn": {},
    "non_rl": {
      "outcome_prediction": {},
      "setup_quality": {},
      "failure_probability": {},
      "regime": {},
      "anomaly": {},
      "calibration": {}
    },
    "adversarial": {},
    "trade_quality": {},
    "rl": {},
    "decision_genome": {}
  },

  "execution": {
    "requested": {},
    "filled": {},
    "entry_price": null,
    "stop_loss": null,
    "take_profit": null,
    "size": null,
    "spread": null,
    "slippage": null,
    "fees": null
  },

  "price_evolution": [],

  "management": {
    "snapshots": [],
    "actions": []
  },

  "outcome": {
    "exit_price": null,
    "pnl": null,
    "return": null,
    "mfe": null,
    "mae": null,
    "duration": null,
    "result": null
  },

  "replay": {
    "replay_version": null,
    "first_divergence": null,
    "failure_class": null,
    "attribution": [],
    "counterfactuals": [],
    "replay_score": null
  },

  "provenance": {
    "analysis_version": null,
    "model_versions": {},
    "config_version": null,
    "data_version": null,
    "feature_version": null
  }
}
```

> This is a **canonical logical contract**, not a claim that every field currently exists in Firebase. Existing implementation must be migrated toward this contract incrementally.

---

# 23. Firebase Temporal Data Rules

Every field must have a clear temporal meaning.

## Available at decision time

Examples:

```text
market_snapshot
deterministic features
market_synthesis
GNN state
Non-RL predictions
Trade Quality
RL state
risk state
execution configuration
```

## Available during the trade

Examples:

```text
price_evolution
position updates
spread evolution
microstructure transitions
management decisions
trailing state
```

## Outcome-only

Examples:

```text
exit price
final P&L
MFE
MAE
duration
final result
future path
replay diagnosis
counterfactual results
```

Outcome-only information must never be fed back into a historical decision as if it had been known at the time.

---

# 24. AI Data Contract

Every AI feature should have metadata:

```text
feature
type
source
timestamp
available_at
timeframe
units
nullable
historical
future_or_outcome_only
version
```

Example:

```json
{
  "feature": "vwap_distance",
  "type": "float",
  "source": "deterministic.vwap",
  "timestamp": "...",
  "available_at": "...",
  "timeframe": "M5",
  "units": "price",
  "historical": true,
  "future_or_outcome_only": false,
  "version": "v2"
}
```

This contract is essential for leakage-safe training and replay.

---

# 25. Price Evolution Storage

The monitor already stores compressed price evolution.

Conceptually:

```text
price_evolution[]
    ├── timestamp
    ├── price
    └── relevant market state / delta
```

The implementation may use compression/encoding to reduce storage.

Current system behavior includes a price-evolution encoder that substantially reduces per-point storage.

The exact encoded representation is an implementation detail and must be versioned so Replay can decode historical records correctly.

---

# 26. Immutable Historical Snapshots

Historical analysis must never be silently overwritten.

For example:

```text
analysis_at_open
analysis_at_close
price_evolution
decision snapshots
model outputs
```

must remain historically reproducible.

If the system changes its analysis later, it creates a new version/snapshot rather than rewriting the original decision state.

---

# 26.1 Legacy Implementation Preservation Contract

This section is **mandatory implementation guidance**.

The existing EasyTradify implementation contains useful infrastructure that must not be accidentally discarded during the AI architecture rewrite. At the same time, several older AI concepts are too tightly coupled, overly autonomous, duplicated, or insufficiently validated for the new architecture.

The rule is:

> **Preserve valuable data, telemetry, proven infrastructure, and reusable algorithms. Preserve old AI code only when its responsibility remains valid. Redesign orchestration and decision authority where the old architecture was unsafe or conceptually weak.**

The old implementation already contains Firebase trade lifecycle persistence, compressed price evolution, decoding, a learning bridge, root-cause analysis, win analysis, confidence calibration, adversarial metrics, GNN tracking, model persistence, rollback, and performance analytics. The new architecture must use these as building blocks rather than recreating them from zero.

The previous implementation also demonstrates why explicit contracts are required: some components were duplicated, some responsibilities were moved between processes, and some broad exception handling could hide initialization failures. The new README therefore treats **ownership, data contracts, temporal availability, provenance, and validation** as first-class requirements.

---

## 26.2 Keep / Preserve / Redesign / Retire Classification

Every legacy AI file or capability must be assigned one of these four statuses before implementation work begins.

### KEEP

The implementation or algorithm remains useful and should be retained with minimal conceptual change.

Examples:

- Firebase trade lifecycle persistence
- `analysis_at_open`
- `analysis_at_close`
- `price_evolution`
- price-evolution encoding/decoding
- price-evolution learning bridge
- execution information
- trailing-stop history
- trade outcome data
- performance metrics
- confidence calibration
- GNN infrastructure and tracking
- adversarial attack generation and metrics
- rollback infrastructure
- diagnostic/observability infrastructure

### PRESERVE AS INFRASTRUCTURE

The code may remain, but it becomes a lower-level service used by the new architecture rather than a top-level decision maker.

Examples:

- existing Firebase helpers
- existing model persistence
- existing GNN fetcher
- existing monitoring hooks
- existing component training infrastructure
- existing performance state storage
- existing anomaly/diagnostic utilities

### REDESIGN

The underlying capability is useful, but the old responsibility boundary is not.

Examples:

- root-cause analysis
- self-correction
- AI evolution
- adaptive thresholds/weights
- meta-learning
- component ensemble logic
- AI scoring
- component attribution
- training orchestration

These must be connected to Replay, Decision Genome, provenance, validation, and controlled promotion.

### RETIRE FROM CORE DECISIONING

The capability may remain for research, diagnostics, visualization, or historical compatibility, but it must not control the production decision path.

Examples:

- independent AI per indicator
- generic AI BUY/SELL voting
- simplistic majority voting
- generic autonomous trade suggestions
- uncontrolled online learning
- autonomous production self-modification
- autonomous risk-limit modification
- LLM as quantitative/risk authority
- diffusion as the primary market predictor
- unsupported claims such as "unbreakable AI"

---

# 26.2A Root-Cause Files — Forensic Preservation and Redesign Specification

The existing root-cause implementation is substantial and must be treated as a **legacy subsystem to mine for reusable intelligence**, not as a subsystem to blindly copy.

The current files contain:

```text
root_cause_models.py
root_cause_analyzers.py
root_cause_trackers.py
```

The model file defines enums and a large family of structured analysis objects, including price analysis, timeframe analysis, stability, component failures, institutional behavior, patterns, hidden gems, behavioral analysis, predictive signals, performance, tracking, GNN data, win analysis, and the final root-cause result. fileciteturn24file1L107-L167

The analyzer/trackers contain real reusable analysis logic, including price-path analysis, timeframe extraction, component analysis, confidence tracking, alignment tracking, regime tracking, signal tracking, institutional-behavior analysis, pattern discovery, predictive warnings, behavioral analysis, performance analytics, win analysis, and suggestions. fileciteturn25file0L111-L171 fileciteturn26file0L96-L194

However, several methods contain **hard-coded thresholds, outcome-derived labels, arbitrary scores, action recommendations, and direct self-learning mutations**. These must not be transplanted into the new architecture unchanged.

---

## 26.2A.1 `root_cause_models.py` — WHAT TO KEEP

### KEEP: Domain vocabulary

Keep and formalize:

```text
Severity
Urgency
Phase
Regime
ComponentStatus
```

The existing implementation already distinguishes trade phases and regimes. fileciteturn24file9L1047-L1071

These concepts are useful for Replay and diagnostics.

### KEEP: Structured analysis dimensions

Keep the idea behind:

```text
PriceAnalysis
TimeframeAnalysis
StabilityAnalysis
ComponentFailures
InstitutionalBehavior
PatternAnalysis
BehavioralAnalysis
PredictiveSignals
PerformanceMetrics
ConfidenceTracking
AlignmentTracking
ComponentTracking
VolumeTracking
RegimeTracking
SignalTracking
GNNData
WinAnalysis
```

These should become separate **typed analysis artifacts**, rather than one giant mutable result object.

### REDESIGN: `RootCauseAnalysisResult`

The existing result object aggregates nearly everything into one large object, including suggestions and actions. fileciteturn24file1L107-L167

New architecture:

```text
ReplayResult
├── market_reality
├── decision_reconstruction
├── first_divergence
├── failure_candidates
├── component_attribution
├── regime_analysis
├── behavior_analysis
├── win_analysis
├── counterfactuals
├── validation_evidence
└── provenance
```

Do not create another giant `RootCauseAnalysisResult` that becomes a dumping ground.

---

## 26.2A.2 `PriceAnalysis` — KEEP THE OBSERVATIONS, REDESIGN THE LABELING

The existing `PriceAnalysis` tracks:

- entry/exit price
- price change
- range
- volatility
- velocity
- acceleration
- price path
- profit peak
- drawdown
- reversal point
- phases
- volatility spikes
- levels hit
- timing to peak/reversal
- momentum
- jerk

This is valuable Replay evidence. fileciteturn24file9L1089-L1120

### KEEP

```text
price_path
MFE/MAE-like observations
peak
drawdown
reversal timing
phase transitions
volatility changes
price dynamics
```

### REDESIGN

The old code assumes a fixed 10-second-ish relationship when converting index to time:

```text
time_to_peak = index * 10
time_to_reversal = index * 10
```

Do not preserve that assumption.

Use actual timestamps:

```text
timestamp[i] - timestamp[entry]
```

Also do not call every crossing from positive to negative profit a "reversal" without contextual validation.

---

## 26.2A.3 `TimeframeAnalysis` — KEEP RELATIONSHIP ANALYSIS, REMOVE ARBITRARY TRUST

The old system compares M1/M5/H1 components and determines a "best timeframe." It also compares discount, supply/demand, FVG and trend across timeframes. fileciteturn25file0L232-L288

### KEEP

- multi-timeframe extraction
- alignment detection
- divergence detection
- timeframe-specific evidence
- component/timeframe history
- first alignment break

### REDESIGN

Do not automatically assume:

```text
H1 > M5 > M1
```

or:

```text
best timeframe = highest local score
```

Instead store:

```text
timeframe_evidence
historical_reliability
regime_condition
sample_size
calibration
uncertainty
```

A timeframe may be useful for one component and useless for another.

---

## 26.2A.4 Component Failure Analysis — KEEP THE 21 OBSERVERS, REBUILD THE FAILURE LOGIC

The old analyzer contains 21 component analyzers. fileciteturn25file0L733-L808

This is valuable because it provides a broad inventory of the existing intelligence.

### Preserve as feature/diagnostic adapters

```text
trend
supply_demand
wyckoff
h1_alignment
adx
volatility
news
session
support_resistance
fvg
m15_divergence
veto_system
breakout
candlestick
microstructure
golden_signals
discount
candle_progress
spread
volume
indicators
```

### But DO NOT preserve their current interpretation as causal truth

For example, the old trend analyzer says:

```text
ADX < 20
→ trend failed
→ weak trend caused loss
→ require ADX > 25
```

That is not proven causality. fileciteturn25file1L814-L826

Likewise, the old H1 analyzer immediately attributes a loss to higher-timeframe conflict and proposes requiring H1 alignment. fileciteturn25file1L858-L870

The new version must say:

```text
Observed:
ADX was 17.4 at decision time.

Association:
Similar historical states had lower outcome probability.

Counterfactual:
Removing/altering this condition changed outcome by X on held-out replay.

Conclusion:
Evidence supports / does not support this as a causal contributor.
```

This is one of the most important corrections in the entire rewrite.

---

## 26.2A.5 Component Interactions — KEEP, GENERALIZE

The old system has explicit interaction rules such as:

```text
trend + H1 alignment
supply/demand + support/resistance + FVG
```

and labels them as conflicts. fileciteturn25file1L1140-L1163

Keep the idea.

Replace hard-coded pair rules with a general interaction graph:

```text
component_A
component_B
relationship
direction
timestamp
evidence
effect_on_decision
effect_on_outcome
regime
```

Eventually, GNN/replay analysis can discover interactions rather than requiring every pair to be manually coded.

---

## 26.2A.6 Timeline Failure Tracking — KEEP AND UPGRADE TO FIRST DIVERGENCE

The old tracker identifies the first component whose score drops substantially. fileciteturn26file0L96-L159

This is a **very valuable concept**.

But:

```text
score drop
≠
failure
```

A score can change because the market legitimately changed.

The new implementation must compare:

```text
belief/state transition
vs
market-reality transition
vs
decision transition
```

The new result should be:

```text
FIRST_DIVERGENCE
├── timestamp
├── event
├── component
├── previous_state
├── new_state
├── expected_market_behavior
├── actual_market_behavior
├── decision_effect
└── evidence
```

This becomes one of the central Replay outputs.

---

## 26.2A.7 Confidence Tracking — KEEP THE RAW HISTORY, REMOVE FAKE PREDICTION ACCURACY

The old system tracks:

- entry confidence
- exit confidence
- peak/minimum confidence
- volatility
- confidence trend
- confidence drops
- whether a drop preceded a loss

This is useful. fileciteturn26file0L20-L26 fileciteturn26file0L1210-L1268

### KEEP

```text
raw confidence timeline
confidence changes
timing of changes
relationship to later events
```

### REDESIGN

The old code creates a prediction accuracy such as:

```text
70 + predictive_lead * 2
```

This is not a real measured accuracy.

Remove it.

Replace with empirical metrics:

```text
lead_time_distribution
precision
recall
false_alarm_rate
calibration
sample_size
OOS performance
```

---

## 26.2A.8 Regime Tracking — KEEP, REPLACE FIXED CODE-ONLY SEMANTICS

The old implementation tracks regime changes over price evolution and maps codes into:

```text
NORMAL
TRENDING
RANGING
HIGH_VOLATILITY
LOW_VOLATILITY
```

This is useful. fileciteturn26file0L196-L242

Keep:

- regime timeline
- transition timestamps
- duration
- entry regime
- exit regime

Add:

- regime confidence
- transition probability
- feature evidence
- model/version
- uncertainty

Do not assume that a single integer code is permanently meaningful without schema/version metadata.

---

## 26.2A.9 Signal Tracking — KEEP EVOLUTION, REMOVE MAJORITY-VOTE SEMANTICS

The old system tracks signal changes and calculates signal consistency from the most common direction. fileciteturn26file0L244-L290

Keep:

```text
signal timeline
signal changes
signal age
signal persistence
```

Do not turn:

```text
most common signal
```

into:

```text
correct direction
```

Signal persistence can be an explanatory variable, not proof of correctness.

---

## 26.2A.10 Institutional Behavior — KEEP AS HYPOTHESIS DETECTORS, NOT FACT DETECTORS

The old system detects:

- stop hunting
- liquidity grabs
- institutional distribution
- institutional accumulation

using simple price/volume heuristics. fileciteturn26file0L292-L369

These are potentially valuable features.

But statements such as:

```text
"Smart money is accumulating"
"Price is being manipulated by algorithms"
```

must not be treated as observed facts.

Use labels:

```text
liquidity_sweep_pattern
volume_price_divergence
possible_accumulation_signature
possible_distribution_signature
```

with:

```text
evidence
confidence
alternative_explanations
validation_status
```

The model must distinguish:

```text
observable market behavior
```

from:

```text
inferred actor intent
```

---

## 26.2A.11 Pattern Recognition — KEEP AS DISCOVERY, NOT ENTRY AUTHORITY

The old system contains:

- double bottom
- double top
- head and shoulders
- inverse head and shoulders
- triangle
- ABC correction
- momentum break
- mean reversion

and assigns confidence values. fileciteturn26file0L371-L506

Keep this infrastructure for:

- pattern discovery
- historical analysis
- clustering
- replay explanation
- research

Do not allow:

```text
pattern detected
→ EXIT IMMEDIATELY
```

or:

```text
pattern detected
→ ADD TO POSITION
```

without a validated policy.

The old implementation contains exactly those types of game-changer actions. fileciteturn26file1L1022-L1083

---

## 26.2A.12 Hidden Gems — KEEP AS RESEARCH DISCOVERY, REMOVE CLAIMS OF CERTAINTY

The old hidden-gem subsystem detects:

- institutional accumulation
- liquidity sweep
- algorithmic trap
- smart-money divergence
- FVG trap

This is interesting research infrastructure. fileciteturn26file0L508-L639

Keep:

```text
candidate pattern
evidence
historical context
confidence
subsequent outcome
```

Redesign:

```text
implication
action
```

so they are treated as hypotheses:

```text
hypothesis
→ replay
→ statistical test
→ OOS validation
```

Do not hard-code claims such as "price will likely reverse" as if they were ground truth.

---

## 26.2A.13 Predictive Signals — KEEP AS LABELLED EARLY-WARNING RESEARCH

The old predictive subsystem searches for confidence drops and reversal-like price behavior. fileciteturn26file0L642-L722

Keep:

- early-warning feature extraction
- event timing
- subsequent outcome measurement

Redesign:

```text
signal_quality
prediction_accuracy
```

to be empirically measured on datasets.

A signal occurring before a reversal in the same trade does not prove predictive power.

---

## 26.2A.14 Behavioral Analysis — KEEP AS POST-TRADE EXECUTION DIAGNOSTICS

The old behavioral analysis classifies entry timing and exit behavior and computes a simple behavior score. fileciteturn26file0L725-L805

Keep:

- entry timing observation
- exit timing observation
- relation between peak opportunity and actual exit
- behavior timeline

Redesign:

```text
"emotional_exit"
```

unless the system has actual evidence of behavior.

A technically early exit is not necessarily emotional.

Use:

```text
early_exit_relative_to_MFE
exit_during_adverse_excursion
exit_reason = known/unknown
```

Then let the analysis infer possible explanations.

Also remove arbitrary:

```text
GOOD = 25
FAIR = 12
```

behavior scores.

---

## 26.2A.15 Performance Metrics — KEEP METRICS, REMOVE SINGLE-TRADE "STRATEGY SCORE"

The old performance logic includes Sharpe, win rate, profit factor, drawdown, and a performance score. fileciteturn26file1L829-L866

Keep portfolio/dataset-level metrics.

Be careful with single-trade calculations.

A single trade's price-evolution series should not be treated as a valid statistical sample for strategy-level Sharpe or win rate.

Move metrics into:

```text
trade-level:
MFE
MAE
return
duration
cost
drawdown path

dataset-level:
Sharpe
Sortino
Omega
profit factor
win rate
drawdown
calibration
stability
```

---

## 26.2A.16 Win Analysis — KEEP THE IDEA, REDESIGN THE LEARNING

The existing Win Analysis extracts:

- success factors
- winning patterns
- winning conditions
- replicable strategy
- confidence
- suggestions

and learns from winning trades. fileciteturn25file0L26-L105

This is worth keeping.

But a single winning trade must never create a new rule.

For example:

```text
one winning trade
→ confidence > 0.7
→ "Require 2 golden signals"
```

is not sufficient evidence.

The new system should aggregate:

```text
many wins
+
many losses
+
matched contexts
+
regime slices
+
OOS validation
```

Then determine whether a factor actually improves expected outcomes.

---

## 26.2A.17 Suggestions and Game-Changer Actions — REDESIGN COMPLETELY

The old system generates natural-language suggestions and direct actions such as:

- widen stop
- take partial profit
- move stop
- add to position
- exit immediately
- adjust position
- reduce size

These are not safe as direct outputs of post-trade root-cause heuristics. fileciteturn26file1L1022-L1083

New architecture:

```text
Analysis
   ↓
Evidence-backed finding
   ↓
Hypothesis
   ↓
Proposed experiment
   ↓
Validation
   ↓
Candidate policy
```

For live operation, only the validated policy/risk system may authorize actions.

---

## 26.2A.18 Learning Mutation — THIS IS A MAJOR LEGACY BUG TO REMOVE

The old `_learn_from_analysis()` directly modifies:

```text
component_performance
timeframe_hierarchy_weights
confidence_thresholds
pattern_database
timeframe_rules
```

after trades. fileciteturn26file1L1222-L1274

The old win-learning path also directly increases timeframe weights. fileciteturn26file1L1276-L1314

This must **not** be copied.

Correct design:

```text
Trade outcome
    ↓
Replay dataset
    ↓
Research statistics
    ↓
Candidate update
    ↓
Walk-forward
    ↓
OOS
    ↓
Stress/adversarial
    ↓
Candidate artifact
    ↓
Promotion
```

No trade may directly mutate the live policy.

This is one of the primary reasons the old architecture must be redesigned rather than copied.

---

## 26.2A.19 Legacy Root-Cause Package — Final Status

| Existing capability | Preserve? | New responsibility |
|---|---|---|
| Enums | YES | Shared domain vocabulary |
| Price path | YES | Replay Market Reality |
| Trade phases | YES | Event/phase reconstruction |
| Timeframe extraction | YES | Feature adapter |
| Timeframe "best" score | NO | Reliability analysis |
| Stability tracking | YES | State stability features |
| 21 component analyzers | YES, redesigned | Feature/diagnostic observers |
| Component failures | YES | Failure candidates |
| Component interactions | YES | Interaction graph |
| Timeline failures | YES | First Divergence Engine |
| Confidence history | YES | Calibration/reliability |
| Confidence fake accuracy | NO | Empirical evaluation |
| Regime history | YES | Regime model |
| Signal history | YES | State evolution |
| Majority signal consistency | NO as authority | Descriptive feature |
| Institutional detectors | YES as hypotheses | Pattern evidence |
| Pattern detectors | YES | Discovery |
| Hidden gems | YES as research | Hypothesis generation |
| Predictive signals | YES | Early-warning research |
| Behavioral analysis | YES | Execution/management diagnostics |
| Performance metrics | YES | Evaluation layer |
| Single-trade performance score | NO | Dataset-level evaluation |
| Win analysis | YES | Symmetric outcome analysis |
| NLP suggestions | YES as reporting | Evidence-backed explanation |
| Game-changer actions | NO as autonomous authority | Experiment proposals |
| GNN correlation tracking | YES | GNN observability |
| GNN divergence/conflict | YES | Context/diagnostics |
| Direct weight mutation | NO | Versioned policy search |
| Direct threshold mutation | NO | Versioned calibration/policy |
| In-memory learning history | NO as source of truth | Persistent versioned dataset |
| Giant aggregate result object | REDESIGN | Separate typed artifacts |

---

## 26.2A.20 The Core Lesson From the Root-Cause Files

The old root-cause subsystem has a **large amount of useful observational intelligence**.

Its main weakness is not that it observes too much.

Its weakness is that it often jumps too quickly from:

```text
observation
```

to:

```text
failure
```

and from:

```text
failure
```

to:

```text
fix
```

and sometimes from:

```text
fix
```

to:

```text
live parameter mutation
```

The new architecture must enforce:

```text
OBSERVE
   ↓
RECONSTRUCT
   ↓
COMPARE
   ↓
FIND FIRST DIVERGENCE
   ↓
ATTRIBUTE
   ↓
TEST COUNTERFACTUAL
   ↓
VALIDATE
   ↓
PROPOSE
   ↓
PROMOTE ONLY IF VALIDATED
```

That is the correct evolution of the existing root-cause work.

---

# 26.3 Exact Legacy Components and How They Must Be Reused

## 26.3.1 Firebase Trade Lifecycle — KEEP AS A FOUNDATION

The Firebase trade document is one of the most valuable parts of the old system.

The existing monitor already uses a consistent `trade_{ticket}` document identity and contains explicit open/close handling. It also prevents continued price-evolution updates after a trade is closed.

The new architecture must retain these guarantees.

### Required behavior

```text
Trade detected
    ↓
Create immutable/open trade record
    ↓
Capture decision-time state
    ↓
Capture execution state
    ↓
Capture decision snapshots
    ↓
Append market evolution
    ↓
Capture management actions
    ↓
Capture close/outcome
    ↓
Freeze historical trade record
    ↓
Replay reads the frozen historical record
```

### Never do this

```text
Replay analysis
    ↓
Modify original historical trade
```

Replay must produce a new replay artifact/version.

### Canonical identity

The historical trade identifier must remain stable:

```text
trade_{ticket}
```

If a broker/execution identifier changes or multiple execution events exist, use additional event IDs instead of changing the historical trade identity.

### Required distinction

Do not mix:

- original execution truth
- replay diagnosis
- later model predictions
- counterfactual outcomes

These are different namespaces.

Recommended logical separation:

```text
trade document
├── original/
├── decision_snapshots/
├── price_evolution/
├── management/
├── outcome/
├── replay/
└── provenance/
```

---

## 26.3.2 `analysis_at_open` — KEEP, BUT FREEZE IT

`analysis_at_open` is valuable because it captures what the system actually knew when the trade began.

It must become an immutable historical snapshot.

### It represents

```text
"What did the system know at the original decision point?"
```

### It must not represent

```text
"What do we know now after seeing the trade outcome?"
```

### Required rule

When the trade opens:

```text
analysis_at_open.timestamp = decision/entry timestamp
analysis_at_open.available_at <= decision timestamp
```

Afterward:

- never overwrite it
- never enrich it with future indicators
- never replace it with a newer analysis
- never recompute it using today's model versions and call the result the original state

If a replay needs a reconstructed version, create:

```text
replay.reconstructed_decision_state
```

and preserve the original snapshot separately.

---

## 26.3.3 `analysis_at_close` — KEEP AS OUTCOME-TIME OBSERVATION

`analysis_at_close` is useful and should remain.

However, it must be explicitly classified as a **post-decision observation**.

It answers:

```text
"What did the market/system look like at the time the trade ended?"
```

It must never be fed into a model as an input to the original entry decision.

It is useful for:

- understanding how conditions evolved
- diagnosing late invalidation
- studying management
- labeling trade outcomes
- identifying regime transitions
- replay comparison
- failure classification
- win analysis

It is not a valid original-entry feature.

---

# 26.4 Price Evolution — KEEP AS CANONICAL MARKET HISTORY

The existing price-evolution system is a major asset.

The previous implementation added:

- `price_evolution_encoder.py`
- `price_evolution_decoder.py`
- `price_evolution_maps.py`
- `price_evolution_bridge.py`

The encoder reduced the stored representation dramatically while preserving reconstruction, and the monitor uses periodic updates while a trade is open.

This infrastructure must be retained.

### What price evolution means

Price evolution answers:

> **"What actually happened after the decision?"**

It is not the same thing as a decision snapshot.

### Keep both

```text
Decision Snapshot
    =
What the system believed at a meaningful decision point

Price Evolution
    =
What the market actually did through time
```

### Why both are required

If a trade loses, price evolution alone can show:

```text
price moved against the position
```

but cannot reliably explain:

```text
which internal belief changed
which component became wrong
which gate should have rejected the setup
which alternative action would have helped
```

Decision snapshots provide the missing internal state.

### Existing 60-second cadence

The existing monitor uses a 60-second price-evolution update interval.

Keep this as a **market-history sampling layer**, not as the only replay observation layer.

Do not force Replay to depend on 60-second snapshots.

Replay must also use event-driven decision snapshots:

```text
T0 candidate
T1 confirmation
T2 microstructure trigger
T3 RL decision
T4 risk approval
T5 management decision
T6 exit decision
```

### Compression rules

The encoder/decoder must satisfy:

```text
encode(original) -> compressed
decode(compressed) -> reconstructed
reconstructed == original
```

or an explicitly documented lossless equivalent for every supported schema version.

Add:

- schema version
- encoder version
- checksum/hash when practical
- timestamp
- source trade ID
- compression format version

Never silently decode a new schema with an old map.

---

# 26.5 Price Evolution Bridge — KEEP, BUT TURN IT INTO A FORMAL DATA ADAPTER

The existing `price_evolution_bridge.py` is valuable because it already connects stored evolution data to AI learning.

Do not allow the bridge to become an uncontrolled source of features.

Its responsibility must be:

```text
Firebase historical representation
        ↓
Decoder
        ↓
Canonical Replay/Market-Reality model
        ↓
Leakage-safe feature extraction
        ↓
Learning datasets
```

The bridge must know the temporal classification of every extracted field.

For every extracted feature:

```text
feature_name
source
timestamp
available_at
timeframe
units
historical
future_or_outcome_only
schema_version
feature_version
```

### Critical rule

A bridge must never do this:

```text
historical trade
    ↓
extract entire trade
    ↓
train entry model with all fields
```

Instead:

```text
decision timestamp
    ↓
filter fields available at that timestamp
    ↓
build decision-state features
    ↓
attach future outcome only as label
```

---

# 26.6 Decision Snapshots — NEW REQUIRED LAYER

The old implementation stores important trade analysis and periodic evolution, but the new architecture requires a stronger event-level representation.

Create:

```text
decision_snapshots[]
```

inside the canonical trade history.

Recommended snapshot types:

| Snapshot | Purpose |
|---|---|
| `CANDIDATE_DETECTED` | setup first became eligible |
| `CONFIRMATION` | setup passed confirmation |
| `MICROSTRUCTURE_TRIGGER` | final trigger became active |
| `RL_DECISION` | specialized RL selected an action |
| `RISK_APPROVAL` | portfolio risk gate approved/rejected |
| `EXECUTION` | actual order/execution state |
| `MANAGEMENT` | hold/protect/adjust decision |
| `EXIT_DECISION` | exit decision |
| `CLOSE` | terminal state |

Every snapshot must contain:

```text
snapshot_id
trade_id
event_type
timestamp
available_at
market_snapshot
deterministic_features
market_synthesis
gnn_state
non_rl_state
trade_quality_state
rl_state
risk_state
execution_state
decision
confidence/probabilities
model_versions
config_version
feature_version
data_version
```

Only fields actually available at the snapshot timestamp are permitted.

---

# 26.7 Root Cause Analysis — PRESERVE CAPABILITY, REBUILD THE AUTHORITY MODEL

The old project has a substantial root-cause subsystem and split package:

```text
root_cause/
├── __init__.py
├── root_cause_models.py
├── root_cause_analyzers.py
└── root_cause_trackers.py
```

It also supports both loss analysis and win analysis.

This capability should absolutely survive.

However, the old conceptual flow:

```text
trade loss
    ↓
root cause
    ↓
AI fixes itself
    ↓
next trade uses changed AI
```

is too uncontrolled for the new architecture.

### New flow

```text
Trade outcome
    ↓
Replay
    ↓
First Divergence
    ↓
Candidate failure causes
    ↓
Component attribution
    ↓
Counterfactual tests
    ↓
Ablation tests
    ↓
Validation
    ↓
Proposed change
    ↓
Candidate model/config version
    ↓
Walk-forward + OOS
    ↓
Promotion decision
```

### Root cause must distinguish

```text
Observed fact
    ≠
Correlated factor
    ≠
Likely causal factor
    ≠
Proven causal factor
```

The system must not claim causality from correlation alone.

### Root cause output should contain

```text
failure_class
first_divergence
affected_component
affected_gate
evidence
confidence
alternative_explanations
counterfactual_result
validation_status
recommended_change
```

---

# 26.8 Win Analysis — KEEP AND MAKE SYMMETRIC WITH FAILURE ANALYSIS

The old system explicitly added Win Analysis.

Keep it.

A learning system that studies only failures creates selection bias toward negative examples.

Use:

```text
WIN
    ↓
What worked?
Why did it work?
Which conditions were present?
Which components agreed?
Which components were unnecessary?
Which components added risk?
Would the same behavior work in another regime?

LOSS
    ↓
What failed?
Why?
Where was the first divergence?
Which component failed?
Which gate failed?
Could another action have improved the outcome?
```

Do not interpret a win as proof that every component involved was correct.

A trade can win despite a bad prediction.

Therefore attribution must evaluate:

```text
decision quality
+
process quality
+
outcome
```

rather than:

```text
win = every component was correct
```

---

# 26.9 Confidence Calibration — KEEP AS A CORE RELIABILITY LAYER

The old implementation contains confidence calibration.

This is one of the most important pieces to preserve.

Never equate:

```text
confidence = probability
```

unless calibration evidence supports it.

The canonical pipeline should be:

```text
Raw model output
    ↓
Calibration layer
    ↓
Validated probability
    ↓
Trade Quality / decision logic
```

Track:

- calibration method
- calibration dataset
- calibration version
- sample size
- reliability metrics
- regime breakdown
- OOS performance

Calibration must be fitted without leaking the evaluation period.

---

# 26.10 GNN — KEEP, BUT CHANGE ITS ROLE

The existing project contains:

```text
ai_gnn.py
ai_gnn_lightweight.py
```

and GNN-related:

- root-cause integration
- NLP suggestions
- conflict detection
- correlation tracking
- divergence tracking
- performance tracking
- cross-asset context

These capabilities remain useful.

The GNN's canonical question is:

> **"What does the rest of the market tell us about the current asset and regime?"**

It should produce contextual information such as:

```text
cross_asset_context
dependency_structure
market_regime_context
divergence
correlation
graph_embedding
anomaly/context signals
```

It must not become:

```text
GNN says BUY
```

and then act as an autonomous trading authority.

### GNN integration with Replay

At each replayed decision point:

```text
historical graph state
    ↓
GNN inference using only then-available information
    ↓
recorded GNN state
    ↓
compare original vs reconstructed inference
```

This enables detection of:

- stale context
- graph drift
- incorrect dependencies
- missing assets
- regime-specific failures
- inference differences caused by model/version changes

---

# 26.11 Adversarial AI — KEEP, BUT MAKE IT REPLAY-AWARE

The old adversarial implementation already attacks many dimensions and persists attack metrics/configuration while keeping attacked trade data in memory.

This is valuable infrastructure.

The new architecture must integrate it with Replay.

### Preserve

- attack generation
- attack diversity
- field coverage
- component attacks
- decision attacks
- disaster/edge-case attacks
- attack success metrics
- model improvement tracking
- persistent metrics
- configuration persistence

### Change

Adversarial attacks must no longer be treated merely as random corruption.

They should answer:

```text
Can this model be fooled?
Can this decision be destabilized?
Which component is fragile?
Which regime is fragile?
Does the system recover?
Does the risk gate remain safe?
```

### Attack classes

```text
Feature attacks
Timing attacks
Regime attacks
Liquidity attacks
Graph/GNN attacks
Missing-data attacks
Conflicting-signal attacks
Decision perturbations
Execution perturbations
Extreme-market scenarios
```

### Critical rule

Attacked data must never contaminate the canonical historical source of truth.

Use:

```text
original historical data
    ↓
temporary attack transformation
    ↓
test
    ↓
discard attack instance
```

Persist only:

```text
attack specification
attack seed/version
result
metrics
model/version
```

unless an explicit experiment dataset is being created.

---

# 26.12 Performance Analytics — KEEP AS OBSERVABILITY, NOT AS A DECISION MAKER

The old project tracks metrics including Sharpe, Sortino, Omega, skewness, kurtosis, daily performance, monthly trends, and alerts.

Keep these.

They answer:

```text
"How is the system performing?"
```

They must not silently become:

```text
"Therefore change the strategy now."
```

Performance analytics may trigger a **review workflow**:

```text
degradation detected
    ↓
freeze candidate promotion
    ↓
open investigation
    ↓
Replay + validation
```

Do not directly alter production weights or risk limits.

---

# 26.13 Model Persistence — KEEP, ADD VERSIONED ARTIFACTS

Existing Firebase model-state persistence is useful.

However, a single mutable model state is insufficient for scientific replay.

Every model artifact should have:

```text
model_id
model_family
model_version
training_dataset_version
feature_version
config_version
code_version
training_window
validation_window
OOS_window
regime_coverage
metrics
created_at
status
parent_version
rollback_target
```

Use immutable artifacts:

```text
candidate_v17
validated_v17
promoted_v17
retired_v17
```

Do not overwrite:

```text
model_v16
```

with v17.

---

# 26.14 Rollback — KEEP, STRENGTHEN

The old evolution system already contains rollback.

Keep it, but make rollback deterministic.

Rollback must mean:

```text
restore the exact previously validated artifact
```

not:

```text
recalculate something approximately similar
```

A rollback record must identify:

```text
from_version
to_version
reason
trigger
metrics
timestamp
operator/system authorization
```

No rollback may modify historical trades.

---

# 26.15 Self-Correction — KEEP AS A PROPOSAL ENGINE, NOT AN AUTONOMOUS MODIFIER

The old `ai_self_correction.py` concept is useful but must be redesigned.

### Old dangerous pattern

```text
loss
 ↓
AI identifies issue
 ↓
AI changes itself
 ↓
next trade uses change
```

### New pattern

```text
loss/win
 ↓
Replay
 ↓
diagnosis
 ↓
proposed correction
 ↓
candidate configuration/model
 ↓
offline evaluation
 ↓
walk-forward
 ↓
OOS
 ↓
stress/adversarial
 ↓
approval/promotion
 ↓
new version
```

The correction engine can propose:

- feature changes
- model retraining
- threshold candidates
- component disabling
- calibration updates
- regime-specific candidates
- architecture candidates

It cannot directly:

- increase portfolio risk
- remove hard risk gates
- promote itself
- modify historical data
- bypass validation

---

# 26.16 Adaptive Thresholds and Weights — REDESIGN AS VERSIONED POLICY SEARCH

The old `ai_adaptive.py` dynamically updates thresholds and weights.

Keep the optimization capability, but remove uncontrolled live mutation.

Instead:

```text
historical dataset
    ↓
candidate parameter search
    ↓
walk-forward validation
    ↓
OOS validation
    ↓
stress test
    ↓
candidate policy
    ↓
promotion
```

Every parameter change must be versioned.

Example:

```text
policy_v12
    threshold_A = ...
    weight_B = ...
    feature_version = ...
```

Never allow:

```text
trade 101 changes weight
trade 102 immediately trusts changed weight
```

unless that behavior is itself an explicitly validated online-learning experiment.

---

# 26.17 Component Trainer — KEEP, MOVE TRAINING OUT OF THE LIVE DECISION PATH

The old component trainer supports incremental learning and adversarial training.

Keep the trainer.

But separate:

```text
INFERENCE
```

from:

```text
TRAINING
```

Production inference should read a validated artifact.

Training should produce a candidate artifact.

```text
LIVE
    ↓
validated_model_vN
```

while training produces:

```text
candidate_model_vN+1
```

Only validation can move the candidate toward promotion.

---

# 26.18 Ensemble — KEEP ONLY IF IT HAS A MEASURABLE JOB

The old ensemble includes ensemble pruning.

Do not recreate an ensemble merely because "more models" sounds stronger.

An ensemble is allowed only if it demonstrates measurable improvement over its components.

Required evidence:

```text
component baseline
vs
ensemble
```

under:

- same data
- same evaluation window
- same leakage rules
- same transaction assumptions
- same regime slices

If the ensemble adds no robust OOS value, remove it.

The ensemble must not become majority voting.

---

# 26.19 Meta-Learner — PRESERVE AS RESEARCH, NOT LIVE AUTHORITY

The old meta-learner learns which components to trust.

This is conceptually useful.

The new version should learn:

```text
P(component reliability | context)
```

rather than:

```text
component says BUY → trust it
```

Useful context includes:

- regime
- volatility
- liquidity
- setup age
- session
- cross-asset context
- historical calibration
- component reliability in similar regimes

The meta-learner must be:

- versioned
- leakage-safe
- OOS-tested
- rollback-capable
- bounded
- unable to override hard risk constraints

---

# 26.20 AI Scoring — REPLACE GENERIC SCORING WITH TRADE QUALITY

The old system contains AI scoring and learned component scores.

Do not recreate a giant arbitrary point system.

The new Trade Quality Engine should combine validated quantities such as:

```text
P(success)
expected return
MFE/MAE distribution
failure probability
regime suitability
GNN context
liquidity quality
microstructure state
calibration quality
execution quality
uncertainty
```

Trade Quality is an aggregation layer.

It is not:

```text
RSI = +10
VWAP = +10
GNN = +20
RL = +30
```

because arbitrary points create false precision and encourage redundant voting.

---

# 26.21 Existing Monitor Behavior — PRESERVE THE RELIABILITY LESSONS

The old monitor contains several fixes that must become explicit architecture requirements:

- state initialized before discovery
- consistent Firebase trade IDs
- closed trades stop receiving price-evolution updates
- fallback close detection
- position cache synchronization
- SL/TP fallback behavior
- permanent exclusion of invalid/non-tradable symbols
- separation of webhook responsibilities
- GNN moved out of the monitor into the AI controller
- price evolution encoding centralized
- `analysis_at_close` persistence
- execution and market-state checks

These are not merely historical bug fixes.

They are architecture requirements because the same classes of bugs can otherwise reappear during the rewrite.

---

# 26.22 Failure Containment and Exception Handling

One particularly important lesson from the old implementation is that broad exception handling can hide serious initialization failures.

Bad pattern:

```python
try:
    initialize_critical_component()
except Exception:
    log("component unavailable")
    continue
```

This can turn:

```text
critical initialization failure
```

into:

```text
system appears healthy but silently runs without the component
```

The new system must classify failures:

```text
FATAL
DEGRADED
RECOVERABLE
OPTIONAL
```

Example:

```text
GNN unavailable
    ↓
if required by current policy:
    fail closed / block that experiment
else:
    enter explicitly logged degraded mode
```

Never silently pretend a missing model is active.

Every degraded mode must expose:

```text
component_status
reason
timestamp
fallback_used
impact
```

---

# 26.23 Historical Truth vs Derived Knowledge

This distinction must be enforced everywhere.

### Historical truth

Examples:

- original market observation
- original analysis snapshot
- original execution
- original spread
- original position state
- original close
- original price evolution

These are immutable.

### Derived knowledge

Examples:

- replay diagnosis
- first divergence
- attribution
- counterfactual
- anomaly label
- calibration result
- model prediction
- failure classification
- experiment result

These are versioned derived artifacts.

### Never mix them

```text
Historical Truth
        ↓
Derived Artifact
        ↓
New Model
```

Never:

```text
Historical Truth
   ← modified by new model
```

---

# 26.24 Provenance Is Mandatory

Every derived AI result must answer:

```text
Which data?
Which features?
Which code?
Which model?
Which configuration?
Which timestamp?
Which experiment?
Which validation window?
```

Minimum provenance:

```text
data_version
feature_version
model_versions
config_version
replay_version
code_version
experiment_id
created_at
```

If provenance is missing, the result should not be treated as reproducible evidence.

---

# 26.25 No "Second Rewrite" Mistake

Before implementing a replacement for any existing component, perform this checklist:

```text
1. Does the old component already store valuable data?
2. Does it already solve a persistence problem?
3. Does it already have tests?
4. Does another component depend on it?
5. Does it contain historical compatibility logic?
6. Can its useful portion become an adapter?
7. What exact responsibility is being removed?
8. What exact responsibility replaces it?
9. What data must remain byte/schema compatible?
10. What migrations are required?
```

Do not delete an old component simply because the new architecture has a better name for it.

First identify its reusable assets.

---

# 26.26 Migration Pattern

The preferred migration pattern is:

```text
LEGACY COMPONENT
      ↓
Inventory
      ↓
Tests / characterization
      ↓
Extract reusable data contracts
      ↓
Create adapter
      ↓
Connect adapter to canonical architecture
      ↓
Run old vs new comparison
      ↓
Replay historical trades
      ↓
Validate
      ↓
Switch ownership
      ↓
Deprecate old entry point
      ↓
Delete only after dependency audit
```

Do not perform:

```text
delete old AI
↓
write new AI
↓
hope behavior is equivalent
```

---

# 26.27 Required Characterization Tests Before Replacement

For every preserved legacy component, create characterization tests where practical.

Examples:

### Price evolution

```text
raw snapshot
→ encode
→ decode
→ compare
```

### Firebase lifecycle

```text
open
→ updates
→ close
→ no further evolution updates
```

### Root cause

```text
known trade
→ analysis
→ stable schema
```

### Calibration

```text
known prediction set
→ calibrator
→ expected probability output
```

### GNN

```text
known market state
→ GNN
→ deterministic/reproducible output under pinned version
```

### Adversarial

```text
seed + attack spec
→ generated perturbation
→ reproducible result
```

### Rollback

```text
candidate
→ promotion
→ degradation
→ rollback
→ exact previous artifact restored
```

---

# 26.28 Legacy-to-New Architecture Mapping

The following mapping is mandatory.

| Legacy capability | New owner | Status |
|---|---|---|
| Firebase trade lifecycle | Canonical Trade Data Layer | KEEP |
| `analysis_at_open` | Decision Snapshot / Decision Genome | KEEP + FREEZE |
| `analysis_at_close` | Market Reality / Outcome | KEEP |
| `price_evolution` | Replay Market Reality | KEEP |
| Encoder | Historical Storage Adapter | KEEP |
| Decoder | Replay Extractor | KEEP |
| Price Evolution Bridge | Replay/Data Adapter | KEEP + FORMALIZE |
| Root Cause Analyzer | Replay Intelligence / Attribution | REDESIGN |
| Win Analysis | Replay Intelligence | KEEP + REFRAME |
| Confidence Calibration | Reliability Layer | KEEP |
| GNN | Market Context Layer | KEEP + REFRAME |
| GNN tracking | GNN observability | KEEP |
| Adversarial AI | Robustness Engine | KEEP + REPLAY-AWARE |
| Performance analytics | Evaluation/Observability | KEEP |
| Component trainer | Offline Training | KEEP + ISOLATE |
| Ensemble | Optional validated aggregator | CONDITIONAL |
| Meta-learner | Research reliability/adaptation | CONDITIONAL |
| Self-correction | Proposal Engine | REDESIGN |
| Adaptive thresholds | Versioned policy search | REDESIGN |
| AI evolution | Model/policy lifecycle manager | REDESIGN |
| Rollback | Artifact lifecycle | KEEP + STRENGTHEN |
| Generic AI scoring | Trade Quality | REPLACE |
| Indicator AI voters | Deterministic intelligence | RETIRE AS CORE |
| Generic BUY/SELL AI | Specialized decision pipeline | RETIRE AS CORE |
| Uncontrolled online learning | Controlled experiments only | RETIRE AS CORE |

---

# 26.29 Definition of Done for Legacy Preservation

The rewrite is **not complete** until:

- every legacy component has a KEEP/PRESERVE/REDESIGN/RETIRE status
- every kept data field has an owner
- historical Firebase data remains readable
- historical trade IDs remain stable
- price evolution can still be decoded
- original decision snapshots remain immutable
- close snapshots remain distinguishable from entry snapshots
- Replay can reconstruct historical decisions
- Replay cannot contaminate original history
- all derived AI artifacts are versioned
- all model artifacts have provenance
- rollback can restore exact artifacts
- adversarial data cannot contaminate source-of-truth history
- training is separated from production inference
- model promotion requires validation
- no component silently disappears because of an import/initialization failure
- old and new behavior can be compared on historical trades
- the new architecture has no duplicate source of truth

---

# 26.30 Golden Rule for the Rewrite

> **Do not rewrite EasyTradify as if the old system never existed.**

The correct approach is:

```text
Existing System
      ↓
Preserve Historical Truth
      ↓
Preserve Valuable Infrastructure
      ↓
Extract Reusable Algorithms
      ↓
Formalize Data Contracts
      ↓
Introduce Decision Snapshots
      ↓
Build Replay as the Learning Backbone
      ↓
Move AI responsibilities into explicit layers
      ↓
Version everything
      ↓
Validate every change
      ↓
Retire only what has a verified replacement
```

This prevents the two most expensive rewrite mistakes:

1. **Rebuilding functionality that already works**, and
2. **Recreating the same architectural problems under new class names.**

---

# 27. Adversarial AI

Adversarial AI is a core robustness component.

Its role is:

> **How can this decision or model break, and under what conditions?**

It does not exist to manufacture fake profitable trades.

## Current design coverage

The current adversarial implementation contains:

- 200+ attackable fields
- 21 component attacks
- 5 disaster attacks
- 6 decision attacks
- 5 edge-case attacks

Attack categories include areas such as:

- final decision/verdict
- prices/sizing
- entry analysis
- indicator scores
- pattern analysis
- directional analysis
- M15 divergence
- higher-timeframe state
- volatility protection
- veto system
- news/session state
- position management
- GNN state
- OHLC + GNN
- entry details
- anti-cheat checks
- account/configuration information
- market disasters
- decision attacks
- edge cases

## Existing API

```text
GET  /api/v1/ai/adversarial/status
POST /api/v1/ai/adversarial/generate
POST /api/v1/ai/adversarial/train
GET  /api/v1/ai/adversarial/metrics
POST /api/v1/ai/adversarial/intensity
POST /api/v1/ai/adversarial/enable
```

Attacked data should be isolated/discarded after the experiment and never silently become production truth.

Persistent AI state currently uses collections including:

```text
ai_component_models
ai_ensemble_models
ai_performance_state
ai_config_state
ai_training_data
```

---

# 28. Specialized Reinforcement Learning

RL answers:

> **Given everything validated that we know, what should the agent do now?**

RL is not the primary market predictor.

## Specialists

### Entry Timing

Actions:

```text
WAIT
ENTER
CANCEL
```

### Management

Actions:

```text
HOLD
EXIT
PROTECT
```

### Risk / Sizing

Actions remain bounded by hard portfolio constraints.

### Exit Optimization

Optimizes exit decisions using observed and replayed market paths.

---

# 29. RL State

The RL state can include:

```text
Decision Genome
Temporal history
Market Reality
GNN embeddings
Regime
Setup age
Time since signal
Spread
Volatility
Liquidity
Microstructure transitions
FVG lifecycle
VWAP state
RVAM
Absorption
Non-RL predictions
Failure probabilities
Trade Quality
Counterfactual information
```

---

# 30. RL Reward

Reward should be based on outcomes, not indicator agreement.

Relevant quantities include:

```text
realized return
MFE
MAE
transaction costs
spread
slippage
time/opportunity cost
invalidation
risk constraints
```

A model should not receive a positive reward simply because it agreed with an indicator.

---

# 31. RL Safety Constraints

RL must be bounded.

The agent cannot:

- bypass Portfolio Risk
- invent unlimited position sizes
- modify hard risk limits
- promote itself
- rewrite production policy
- deploy an unvalidated model
- perform uncontrolled online learning

RL is research infrastructure until it passes validation.

---

# 32. Trade Quality Engine

Trade Quality is a downstream synthesis layer.

It should be based on validated quantities such as:

```text
P(success)
Expected return
Expected R
Expected MFE
Expected MAE
Regime suitability
GNN confirmation/context
Liquidity quality
Microstructure quality
Failure probability
Anomaly probability
Calibration quality
Execution quality
Uncertainty
```

Avoid arbitrary scoring such as:

```text
RSI = +10
FVG = +10
VWAP = +10
GNN = +10
```

The score must be statistically grounded and calibrated.

---

# 33. Live AI Architecture

The live system must have explicit responsibilities and timing.

```text
                    LIVE MARKET DATA
                           ↓
              Deterministic Intelligence
                           ↓
                  Market Synthesis
                           ↓
                         GNN
                           ↓
                   Non-RL Models
                           ↓
                    Trade Quality
                           ↓
                Microstructure Trigger
                           ↓
                 RL Entry Timing
                           ↓
                Portfolio Risk Gate
                           ↓
                      Execution
                           ↓
                Position Monitoring
                           ↓
                RL Management / Exit
                           ↓
                      Position Exit
                           ↓
                    Replay Record
```

## Live execution matrix

| Component | Live | Replay | Training |
|---|---:|---:|---:|
| Deterministic features | Yes | Yes | Yes |
| Market Synthesis | Yes | Yes | Yes |
| GNN | Yes, after validation | Yes | Yes |
| Non-RL predictions | Yes, after validation | Yes | Yes |
| Adversarial AI | Monitoring/stress | Yes | Yes |
| Trade Quality | Yes, after validation | Yes | Yes |
| RL Entry | Later, gated | Yes | Yes |
| RL Management | Later, gated | Yes | Yes |
| RL Risk/Sizing | Later, bounded | Yes | Yes |
| Counterfactual | No direct live authority | Yes | Yes |
| Replay | No | Core | Core |
| World Model | No initially | Research | Research |
| Diffusion | No initially | Research | Research |
| Meta-Learning | No initially | Research | Research |

---

# 34. Live AI Timing

A live AI component must declare its execution cadence.

Examples:

```text
Every tick:
    execution-critical market state
    spread
    position monitoring
    microstructure-sensitive values

Every new candle:
    structure
    FVG
    VWAP
    RVAM
    absorption
    volume profile
    Non-RL updates
    GNN updates where appropriate

At candidate setup:
    Market Synthesis
    GNN context
    Non-RL prediction
    Trade Quality
    microstructure trigger

Before order:
    RL Entry Timing
    Portfolio Risk Gate
    execution checks

During position:
    market evolution
    management state
    RL Management
    trailing/protection

At exit:
    outcome capture

After exit:
    immutable Replay record
```

The exact cadence must be configured per feature/timeframe rather than assuming every model should run on every tick.

---

# 35. Market Simulator / World Model

The Market Simulator is a **counterfactual and scenario infrastructure layer**.

Its first purpose is not to predict prices.

Its first purpose is:

> **Given the exact historical state at time T, simulate what would have happened under a different action or controlled scenario.**

This distinction is mandatory.

---

## 35.1 Simulator Hierarchy

The project must evolve through four levels.

```text
LEVEL 1
Historical Replay Simulator
        ↓
LEVEL 2
Counterfactual Branch Simulator
        ↓
LEVEL 3
Probabilistic Scenario Simulator
        ↓
LEVEL 4
Learned World Model
```

Do not jump directly to Level 4.

---

## 35.2 Level 1 — Historical Replay Simulator

This is the ground-truth foundation.

Input:

```text
historical market data
+
historical execution conditions
+
historical decision state
```

Output:

```text
what actually happened after T
```

It must reproduce:

- price path
- time progression
- spreads where available
- execution assumptions
- position state
- stop/target interactions where data supports them
- MFE
- MAE
- duration
- terminal outcome

The simulator should be deterministic when the same data/configuration is supplied.

---

## 35.3 Level 2 — Counterfactual Branching

At a historical decision point:

```text
Historical State T
       │
       ├── Original Action
       │      ↓
       │   Historical outcome
       │
       ├── WAIT
       │      ↓
       │   branch outcome
       │
       ├── ENTER later
       │      ↓
       │   branch outcome
       │
       ├── EXIT earlier
       │      ↓
       │   branch outcome
       │
       └── HOLD / PROTECT
              ↓
           branch outcome
```

Counterfactuals must use only information available at the branch point.

The future historical path is used **to score the branch after the fact**, not as an input to the decision.

---

## 35.4 Counterfactual Action Space

The simulator should support, where the historical data is sufficient:

### Entry

```text
WAIT
ENTER_NOW
ENTER_AFTER_N_BARS
CANCEL
```

### Management

```text
HOLD
PROTECT
PARTIAL_EXIT
FULL_EXIT
```

### Exit

```text
EXIT_NOW
EXIT_AT_TARGET
EXIT_AT_INVALIDATION
```

### Risk/sizing

Only actions within the hard portfolio/risk policy may be simulated.

The simulator must never use counterfactuals to justify violating hard risk constraints.

---

## 35.5 Branch Definition

Every counterfactual branch should contain:

```text
branch_id
parent_decision_id
branch_timestamp
action
parameters
constraints
market_state_at_branch
execution_assumptions
future_path_reference
simulator_version
result
```

Example:

```json
{
  "branch_id": "cf_001",
  "parent_decision_id": "decision_123",
  "branch_timestamp": "2026-01-01T10:15:00Z",
  "action": "WAIT",
  "parameters": {
    "bars": 2
  },
  "constraints": {
    "risk_policy_version": "risk_v4"
  },
  "result": {
    "pnl": null,
    "mfe": null,
    "mae": null,
    "outcome": null
  }
}
```

The result is populated by simulation, never by manually inferred labels.

---

## 35.6 Simulator Must Separate Market Dynamics From Policy

Do not build:

```text
Simulator = strategy + market model + risk + execution + evaluator
```

as one giant class.

Use:

```text
Market State
    ↓
Market Evolution Engine

Policy / Action
    ↓
Action Application Engine

Execution Model
    ↓
Execution Simulation

Position State
    ↓
Outcome Calculator

Experiment
    ↓
Evaluator
```

This allows the same historical market path to test many policies.

---

## 35.7 Historical Market Reality Is the First Authority

When historical observations exist:

```text
actual historical path
```

has priority over:

```text
learned world model
```

The learned model may generate hypothetical scenarios, but it cannot rewrite historical truth.

---

## 35.8 Probabilistic Scenario Simulator

Later, the system may generate multiple plausible trajectories:

```text
State T
 ↓
Scenario generator
 ├── Path A
 ├── Path B
 ├── Path C
 ├── Path D
 └── ...
```

The system may estimate:

- probability distributions
- expected path characteristics
- uncertainty
- tail scenarios
- time-to-event distributions
- regime-conditioned scenarios

But generated paths must be tagged:

```text
synthetic = true
```

and must never be mixed with historical observations.

---

## 35.9 Learned World Model

A learned world model may eventually model:

```text
P(next_market_state | current_state, context, action)
```

or a richer transition representation.

Potential uses:

- policy evaluation
- scenario generation
- rare-event testing
- long-horizon planning
- RL research

It must be evaluated against held-out historical data.

---

## 35.10 World Model Validation

A world model must not be judged primarily by:

```text
"generated charts look realistic"
```

Required evaluation should include, where applicable:

- distributional similarity
- volatility behavior
- autocorrelation characteristics
- regime transitions
- tail behavior
- event timing
- dependency structure
- conditional behavior
- calibration
- out-of-sample performance
- downstream policy robustness

A visually realistic synthetic path can still be quantitatively wrong.

---

## 35.11 Simulator Leakage Rules

Strictly prohibited:

```text
Future path
    ↓
Decision state
```

Allowed:

```text
Decision state at T
    ↓
Action
    ↓
Future path
    ↓
Outcome evaluation
```

Also allowed:

```text
Decision state at T
    ↓
Learned simulator
    ↓
synthetic future scenarios
    ↓
policy evaluation
```

provided the simulator itself was trained without leaking the evaluation period.

---

## 35.12 Simulator + Replay

Replay determines:

```text
What actually happened?
Where did the original decision diverge?
```

Simulator determines:

```text
What would have happened if we changed the action?
```

Together:

```text
Firebase Historical Truth
        ↓
Replay
        ├── Original decision
        ├── First divergence
        └── Failure attribution
        ↓
Simulator
        ├── WAIT branch
        ├── alternate entry
        ├── alternate management
        └── alternate exit
```

This is the core of serious counterfactual learning.

---

## 35.13 Simulator + RL

RL should eventually learn from:

```text
historical experience
+
validated counterfactual experience
+
validated simulator scenarios
```

But simulator-generated experience must be clearly tagged.

```text
experience_type =
    HISTORICAL
    COUNTERFACTUAL_HISTORICAL
    SYNTHETIC
```

Do not allow synthetic experience to silently dominate real historical experience.

---

## 35.14 Simulator Must Never Become a Hidden Price Predictor

Prohibited architecture:

```text
Market Simulator
      ↓
predict exact future price
      ↓
BUY/SELL
```

Preferred architecture:

```text
Historical Reality
      ↓
Replay
      ↓
Counterfactual Simulator
      ↓
Evaluate alternative actions
      ↓
RL / policy research
```

---

# 36. Diffusion Models — Later Research

Diffusion models may eventually be useful for:

- scenario generation
- trajectory generation
- conditional market-state simulation
- stress scenarios

They must **not** be introduced as:

```text
Diffusion → primary price predictor → trade
```

They are research infrastructure until validated.

---

# 37. Meta-Learning — Later Research

Meta-learning may help models adapt across:

- regimes
- instruments
- timeframes
- tasks

However, uncontrolled online adaptation is dangerous.

Any future meta-learning system must have:

```text
Versioning
Offline evaluation
Walk-forward testing
OOS testing
Rollback
Monitoring
Promotion gates
No self-promotion
```

---

# 38. Other Later AI Research

Potential future work:

- self-supervised representation learning
- pattern discovery
- time-to-event models
- advanced temporal models
- foundation-style market representations
- generative scenario models
- learned world models
- meta-learning

These are conditional research directions, not mandatory architecture dependencies.

---

# 39. Features Explicitly Removed or Demoted

The following should not become core architecture:

### Independent AI per indicator

Do not build:

```text
RSI AI
EMA AI
FVG AI
VWAP AI
ATR AI
...
```

### Generic AI Trade Suggestions

No generic:

```text
AI says BUY
AI says SELL
```

without a defined prediction/decision job.

### Simplistic Majority Voting

Avoid:

```text
7 AIs say BUY
3 AIs say SELL
→ BUY
```

### Duplicate Correlation Models

GNN provides structured graph context. Do not create redundant correlation AIs without a distinct validated purpose.

### Heatmap as Intelligence

Heatmaps are visualization/reporting tools.

### Autonomous Production Self-Modification

No model may rewrite production logic and promote itself.

### Autonomous Risk-Limit Modification

Hard portfolio controls remain outside AI authority.

### Uncontrolled Online Learning

No uncontrolled live self-training.

### LLM as Quantitative Authority

LLMs may assist with explanation, documentation, research, or tooling, but should not become the authoritative quantitative risk/execution model.

### “Unbreakable AI”

The project must never claim that a model cannot fail.

---

# 40. Data and Persistence

## PostgreSQL

Use PostgreSQL for relational application data such as:

- users/accounts where applicable
- configuration
- relational trading entities
- structured service state

## Firebase / Firestore

Used for real-time/evolving trading and AI data such as:

- active trades
- trade history
- analytics
- price evolution
- analysis snapshots
- replay data
- AI state
- training/experiment artifacts

Known AI collections:

```text
ai_component_models
ai_ensemble_models
ai_performance_state
ai_config_state
ai_training_data
```

Trade documents may use:

```text
trade_<ticket>
```

The canonical trade contract in this README defines the target logical schema.

---

# 41. AI Replay Data Lifecycle

```text
Trade Open
    ↓
analysis_at_open
    ↓
Periodic / event snapshots
    ↓
price_evolution
    ↓
management decisions
    ↓
analysis_at_close
    ↓
outcome
    ↓
Replay
    ↓
diagnosis
    ↓
counterfactuals
    ↓
training / experiments
```

All timestamps must be preserved.

---

# 42. Anti-Leakage Architecture

This is a hard requirement.

For any decision timestamp `T`:

```text
Allowed:
features with available_at <= T

Not allowed:
features whose availability time > T
```

Formally:

```text
available_at <= decision_timestamp
```

Future market data may be used for:

- labels
- outcomes
- replay
- counterfactual scoring
- evaluation

Future market data may not be used as model input to reconstruct the original decision.

This distinction must be enforced in code, not merely documented.

---

# 43. Replay Leakage Protection

Replay must verify:

```text
feature_timestamp
feature_available_at
decision_timestamp
model_timestamp
data_version
```

If a feature cannot be proven available at decision time, Replay should flag it as:

```text
LEAKAGE_RISK
```

rather than silently accepting it.

---

# 44. AI Market Replay Python Structure

Recommended structure:

```text
ai/
└── aireplay/
    ├── controller.py
    ├── config.py
    ├── models.py
    ├── data_engine.py
    ├── replay_engine.py
    ├── intelligence_engine.py
    ├── experiment_engine.py
    ├── learning_engine.py
    ├── validation_engine.py
    ├── reporting_engine.py
    ├── cli.py
    │
    ├── datasets/
    ├── experiments/
    ├── artifacts/
    ├── reports/
    └── tests/
```

Recommended responsibilities:

- `data_engine.py`: source extraction and temporal-safe loading
- `models.py`: canonical replay/event models
- `replay_engine.py`: timeline reconstruction and comparison
- `intelligence_engine.py`: diagnosis and attribution
- `experiment_engine.py`: A/B, ablation, stress, counterfactual
- `learning_engine.py`: dataset generation
- `validation_engine.py`: walk-forward/OOS evaluation
- `reporting_engine.py`: human-readable replay reports

---

# 45. Current Non-RL Implementation

A unified Non-RL implementation has been developed around:

```text
IntelligenceConfig
DecisionRecord
OutcomeLabel
Prediction
FailureDiagnosis
CounterfactualLabel
DecisionGenomeAdapter
MarketRealityAdapter
TabularFeatureEncoder
OutcomeLabeler
CounterfactualLabelEngine
OutcomePredictor
SetupQualityModel
FailureClassifier
ComponentAttributionEngine
RegimeModel
AnomalyDetector
PatternDiscovery
ProbabilityCalibrator
TimeToEventModel
DecisionExplainer
ValidationEngine
ExperimentEngine
NonRLIntelligenceController
```

The implementation is designed to be leakage-safe and can use optional scikit-learn-style backends.

Important caveats:

- time-to-event is currently an approximation rather than formal survival analysis
- clusters are descriptive
- failure classification requires historical labels
- fallback attribution is association rather than proven causality
- calibration requires sufficient validation data
- stronger tree libraries can be added later if justified

---

# 46. Current RL Implementation

A unified research RL implementation contains:

```text
Entry Timing
Management
Risk / Sizing
Exit Optimization
```

It uses:

- Decision Genome
- temporal history
- Market Reality
- GNN embeddings
- regime
- setup age
- time since signal
- spread
- volatility
- liquidity
- microstructure
- FVG lifecycle
- VWAP
- RVAM
- absorption
- Non-RL predictions
- failure probabilities
- Trade Quality
- counterfactual information

Current research limitations include:

- management/exit counterfactuals may use simplified approximations until fully wired to Replay
- evaluation and training history handling must be made identical
- sizing may use a discrete size grid rather than continuous optimization
- production orchestration must enforce specialist dependency ordering
- no claim of profitability or production validation is made

---

# 47. Adversarial + Replay + RL Relationship

The strongest architecture is:

```text
Replay
  ├── diagnoses RL mistakes
  ├── diagnoses Non-RL mistakes
  ├── evaluates GNN
  ├── generates counterfactuals
  └── produces learning data

Adversarial
  ├── attacks features
  ├── attacks regimes
  ├── attacks graph context
  ├── attacks timing
  └── attacks decisions

Non-RL
  ├── predicts outcomes
  ├── estimates failure
  ├── models regimes
  └── explains patterns

GNN
  └── provides cross-market context

RL
  └── chooses actions under validated state
```

No component is allowed to hide its uncertainty or validation status.

---

# 48. Validation Framework

Every AI candidate should pass progressively stronger tests.

```text
Unit Tests
    ↓
Integration Tests
    ↓
Historical Backtest
    ↓
Replay Validation
    ↓
A/B Test
    ↓
Ablation Test
    ↓
Stress Test
    ↓
Walk-Forward
    ↓
Out-of-Sample
    ↓
Regime-Specific Evaluation
    ↓
Adversarial Evaluation
    ↓
Paper / Controlled Validation
    ↓
Explicit Promotion
```

A model failing an earlier stage cannot be rescued by a good later aggregate metric.

---

# 49. A/B Testing

Every significant architecture change should support:

```text
Model A = current baseline
Model B = candidate
```

Compare:

- outcome metrics
- calibration
- drawdown impact
- failure rates
- regime performance
- latency
- stability
- adverse scenarios

Do not select a model from one aggregate metric alone.

---

# 50. Ablation Testing

Ablation answers:

> Does this component actually add information?

Examples:

```text
Full system
Full - GNN
Full - VWAP
Full - RVAM
Full - absorption
Full - microstructure
Full - Non-RL
Full - RL
```

A component should remain only when its contribution survives validation.

---

# 51. Regime-Aware Evaluation

Performance must be evaluated by regime.

Possible dimensions:

```text
Trending
Ranging
High volatility
Low volatility
High liquidity
Low liquidity
Session
Instrument
Timeframe
News/event conditions
```

A model that works only in one regime must not be presented as universally effective.

---

# 52. Reliability

The monitor and services should be designed for failure recovery.

Current monitoring architecture includes:

```text
Fast Entry Check
Position Monitor
Health Monitor
Main Controller
Restart Watchdog
```

The monitor can restart itself using process replacement and then re-synchronize with broker positions.

Recoverable scan errors should not terminate the entire monitoring process.

---

# 53. Project Structure

```text
EasyTradify/
│
├── discovery-server/
├── execution-service/
├── monitor/
├── porfolio_risk_management/
├── ai/
│
├── common/
│
├── pom.xml
├── README.md
└── docs/
```

AI area:

```text
ai/
├── aireplay/
├── models/
├── datasets/
├── experiments/
├── artifacts/
├── reports/
└── tests/
```

Exact implementation structure may evolve while preserving service boundaries and contracts.

---

# 54. Technology Stack

## Backend

- Java 17
- Spring Boot 3.2.x
- Spring Cloud 2023.0.x
- Spring Data JPA
- Spring WebFlux
- Maven 3.9.x

## Service Discovery

- Eureka

## Database

- PostgreSQL 15+

## Realtime / Audit / AI Persistence

- Firebase
- Firestore

## Python

Python services support:

```text
MT5 / Execution      :5000
Hybrid Monitor       :5001
AI Controller        :5002
```

## Testing

- JUnit 5
- Mockito 5.x
- Testcontainers

## API Documentation

- SpringDoc
- OpenAPI / Swagger

---

# 55. Configuration

Never commit secrets.

Use environment variables or secure secret storage for:

```text
DATABASE_URL
DATABASE_USERNAME
DATABASE_PASSWORD

FIREBASE_CREDENTIALS
FIREBASE_PROJECT_ID

MT5_LOGIN
MT5_PASSWORD
MT5_SERVER

AI_MODEL_PATH
AI_MODEL_VERSION

SERVICE_DISCOVERY_URL
```

Use placeholders in configuration examples.

---

# 56. Getting Started

## Prerequisites

Install:

```text
Java 17
Maven 3.9+
PostgreSQL 15+
Python 3.x
MetaTrader 5
Node.js if Angular frontend is present
```

Configure environment variables and service-specific application configuration.

## Build

```bash
mvn clean install
```

## Run services

Start in approximately this order:

```text
1. PostgreSQL / Firebase dependencies
2. Discovery Server
3. Execution Service
4. Monitor
5. Portfolio Risk Service
6. AI Service
7. Python controllers
8. MT5 bridge
```

Service dependencies should be verified through health endpoints and logs.

---

# 57. Testing Standards

Minimum target:

```text
80%+ unit test coverage
```

Public APIs require integration testing.

Important tests include:

- execution
- position synchronization
- risk blocking
- trailing stop
- replay reconstruction
- temporal ordering
- leakage detection
- counterfactual branches
- GNN outputs
- calibration
- adversarial attacks
- RL action constraints

---

# 58. Development Standards

## Controllers

Keep controllers thin.

Do not place business logic in controllers.

## Exceptions

Use centralized exception handling.

Avoid scattered `try/catch` blocks in controllers.

## DTOs

Prefer Java records where appropriate.

## JSON

Use snake_case JSON naming where required:

```java
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
```

## Documentation

Important classes and public methods should contain useful JavaDoc.

## Logging

Logs must identify:

- service
- operation
- symbol/ticket where relevant
- failure reason
- model/version where relevant

Never log secrets.

---

# 59. Research-to-Execution Lifecycle

```text
Hypothesis
   ↓
Implement
   ↓
Backtest
   ↓
Replay
   ↓
Ablation
   ↓
A/B
   ↓
Stress
   ↓
Walk-Forward
   ↓
OOS
   ↓
Paper / Controlled Validation
   ↓
Promotion Review
   ↓
Live Shadow
   ↓
Limited Live Authority
```

Promotion is explicit.

No model automatically promotes itself.

---

# 60. Recommended Implementation Order

## Phase 0 — Legacy Inventory and Preservation Gate

Before changing the AI implementation:

1. Inventory every existing AI, Firebase, monitor, GNN, adversarial, training, calibration, and replay-related component.
2. Assign every component KEEP / PRESERVE / REDESIGN / RETIRE status.
3. Identify all historical Firebase fields and their owners.
4. Characterize critical legacy behavior with tests.
5. Verify price-evolution encode/decode compatibility.
6. Verify `trade_{ticket}` identity behavior.
7. Verify that closed trades stop receiving evolution updates.
8. Verify `analysis_at_open` and `analysis_at_close` remain distinguishable.
9. Freeze the historical-data schema before building Replay.
10. Build adapters before deleting old implementations.

**No destructive rewrite is permitted before Phase 0 is complete.**

## Phase 1 — Data Foundation

1. Canonical trade schema
2. Immutable snapshots
3. Temporal metadata
4. Feature availability metadata
5. Decision Genome
6. Replay extraction

## Phase 2 — Deterministic Intelligence

1. VWAP
2. CLV Absorption
3. RVAM
4. FVG lifecycle
5. unified liquidity sweep
6. microstructure
7. Trade Quality
8. canonical Market Synthesis
9. Market Synthesis conflict/uncertainty model
10. Market Synthesis replay determinism

1. VWAP
2. CLV Absorption
3. RVAM
4. FVG lifecycle
5. unified liquidity sweep
6. microstructure
7. Trade Quality

## Phase 3 — Replay

1. Event model
2. Temporal aligner
3. Market Reality reconstruction
4. Decision reconstruction
5. First divergence detection
6. Attribution
7. Counterfactual branching
8. A/B
9. Ablation
10. Stress replay
11. Replay reports
12. historical simulator
13. counterfactual simulator
14. simulator/replay consistency tests

## Phase 4 — Non-RL

1. Outcome prediction
2. Quality prediction
3. Failure classification
4. Regime
5. Anomaly
6. Calibration
7. Attribution
8. Pattern discovery

## Phase 5 — GNN

1. Graph construction
2. Embeddings
3. Context
4. Correlation changes
5. Divergence/conflict
6. A/B
7. OOS validation

## Phase 6 — Adversarial

1. Component attacks
2. Decision attacks
3. disaster scenarios
4. edge cases
5. robustness metrics
6. replay integration

## Phase 7 — RL

1. Entry timing
2. Management
3. Exit
4. bounded sizing
5. Replay training
6. offline validation
7. OOS
8. controlled deployment

## Phase 8 — Later Research

Only if justified:

```text
Self-supervised learning
World Models
Diffusion
Meta-Learning
Advanced Temporal Models
Foundation-style representations
```

---

# 61. AI Maturity Levels

## Level 1

Deterministic market intelligence.

## Level 2

Market Synthesis + validated Non-RL predictions.

## Level 3

GNN + Replay + adversarial robustness.

## Level 4

Specialized RL trained and evaluated through Replay.

## Level 5

World-model / advanced generative research.

The project should not skip levels.

---

# 62. What Makes EasyTradify Different

The strongest differentiator is not:

```text
"we use many AIs."
```

It is:

```text
Every decision
    ↓
has a canonical state
    ↓
has temporal provenance
    ↓
can be replayed
    ↓
can be challenged
    ↓
can be counterfactually tested
    ↓
can be ablated
    ↓
can be validated OOS
    ↓
and only then can it be promoted.
```

This creates a closed research loop rather than a black-box prediction engine.

---

# 63. Final AI Architecture

```text
MARKET DATA
    ↓
DETERMINISTIC MARKET INTELLIGENCE
    ├── Structure
    ├── Liquidity
    ├── FVG lifecycle
    ├── VWAP
    ├── RVAM
    ├── CLV / Absorption
    ├── Order Flow / Volume Profile
    ├── Momentum / Volatility
    └── Microstructure
    ↓
MARKET SYNTHESIS
    ↓
GNN
    ↓
DECISION GENOME
    ├── Non-RL Intelligence
    ├── AI Market Replay
    └── Counterfactual Engine
    ↓
MARKET SIMULATOR / WORLD MODEL
    ↓
SPECIALIZED RL
    ├── Entry Timing
    ├── Management
    └── Risk / Sizing
    ↓
TRADE QUALITY
    ↓
PORTFOLIO RISK GATE
    ↓
EXECUTION
    ↓
RESULT
    └──→ REPLAY
```

Cross-cutting:

```text
ADVERSARIAL AI
    ├── Feature attacks
    ├── Regime attacks
    ├── Graph attacks
    ├── Timing attacks
    └── Decision attacks
```

Later research:

```text
Meta-Learning
Diffusion
Advanced World Models
Foundation-style Temporal Models
```

These remain sandboxed until validated.

---

# 64. Final Principles

EasyTradify should always prefer:

```text
Evidence over votes
Calibration over confidence
Replay over guessing
Counterfactuals over hindsight
OOS validation over backtest optimization
Robustness over complexity
Bounded autonomy over unrestricted autonomy
Immutable history over overwritten state
Specialized AI over generic AI
Risk gates over AI authority
```

The objective is not to build the largest number of AI models.

The objective is to build a **measurable, replayable, explainable, adversarially tested, leakage-safe, continuously validated decision system**.

---

# 65. Disclaimer

Algorithmic trading involves substantial financial risk.

No architecture, AI model, backtest, replay result, simulation, or validation metric guarantees future performance or profitability.

All learned trading components should be treated as experimental until they pass independent, leakage-safe, walk-forward, out-of-sample, stress, and controlled validation.

Hard portfolio risk controls must remain independent of AI predictions.

