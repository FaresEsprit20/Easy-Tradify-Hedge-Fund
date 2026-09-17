# Edge Research — Storage Migration, Component Audit, and the Path to High Expectancy

This document covers the work done in this session: the move of trade storage to
MongoDB, the instrumentation added so components can be measured at all, every
hypothesis tested against real outcomes, and the strategy that follows from what
the measurements actually say.

It is written to be read by someone who was not present. Where a claim is
measured, the number is given. Where something is unproven, it says so.

---

## 1. Why any of this was necessary

The system had been running for months, and none of its components could be
evaluated. Not because the analysis was weak — because the data recording it was
broken in ways that produced no error message.

Found and fixed this session, each verified against live documents:

| defect | consequence |
|---|---|
| `pattern` signed its contribution from the market read alone, never receiving `best_direction` | on every SELL it pushed probability the **wrong way**; 26% of trades got a mean 12.3 points inverted |
| `_canonical_point` tested `_encoded` *inside* `analysis`, the writer put it *beside* it | **every price point decoded to `{}`** — the AI layer trained on nothing |
| `analysis_at_open` stored as a triple-nested envelope | `final_verdict`, `probability_ledger` and `best_direction` unreachable by any reader |
| `analysis_at_close` writer looked for 3 key spellings, producer used a 4th | closing analysis stored **empty** on every trade |
| price-evolution encoder raised on `None` `timing_confidence` (17 sites) | exception swallowed, **price point silently dropped** |
| price-update throttle was one global clock, not per-ticket | at most **one open position per 60s** got a point |
| Firestore 1 MiB document cap | `price_evolution` stopped accepting points after **two** |
| `close_reason` hardcoded to `"SL_TP_HIT"` | winners that hit target and losers that hit stop recorded **identically** |
| MQ5 parsed broker free-text `DEAL_COMMENT`, testing `"sl"` before `"tp"` | close reason unreliable at the source |

The common shape: **the data was present, the reader looked one level too high,
and the result was silence rather than an error.** Nothing logged, nothing
raised, and every model concluded the trade had no analysis.

---

## 2. Storage: Firestore → MongoDB

### Why the move

Every problem traced to Firestore's document model:

| | Firestore | MongoDB |
|---|---|---|
| document limit | **1 MiB** | **16 MB** |
| a trade with 180 price points | impossible — needed a subcollection | fits as **one document** |
| array append | read-modify-write, O(n²) | `$push`, atomic, O(1) |
| analytical queries | composite index per query shape | aggregation pipeline |
| missing index | returned `[]`, indistinguishable from "no trades" | ad-hoc queries work |

The migration was cheap because all 30 Firestore call sites lived in **one file**
behind a service class, and the Angular UI never touched Firestore at all — it
talks to the Flask API, and `firebase` is not even a dependency in its
`package.json`.

**Trades now live in MongoDB only.** `TRADES_TO_FIRESTORE = False` in
`monitor/firebase_helpers.py`. Firestore keeps `portfolio_config` and
`ai_models`.

**The trade-off, stated plainly:** this removes the fallback. If Mongo is down
when a trade opens, that trade has no record anywhere. `trade_sink` counts
failures and reports `degraded`, so the loss is visible rather than silent — but
it is a real loss. Check `trade_sink.get_status()` after any database
interruption.

### New files

#### `core/mongo/mongo_config.py`
Connection, pooling, timeouts. One place that knows how to reach MongoDB.

- **Credentials never logged.** `safe_uri` redacts to `mongodb://***:***@host/db`.
  A connection string in a log file is a leaked password, and log files get
  pasted into issues.
- **Short timeouts (5s).** This client is used from the position-monitor loop; a
  dead database must surface in seconds, not block the thread that has to keep
  up with the market.
- **`w=majority` + journal.** A trade record is money. Acknowledged-and-lost is
  not acceptable for the one artefact that says what the system did.
- **Lazy connection.** Constructing this must never stop a trading process from
  starting.

#### `core/mongo/trades_service.py`
The only module that reads or writes the trades collection.

- **Full CRUD**: `create_trade`, `upsert_trade` (idempotent — a retry after a
  timeout must converge on one record), `get_trade`, `list_trades`,
  `update_trade`, `append_price_point`, `close_trade`.
- **Delete is a strategy, not a verb**: `SOFT` (default, reversible) → `ARCHIVE`
  (moved, recoverable) → `HARD` (requires `confirm=True`). **An OPEN trade is
  refused in every mode** unless `allow_open` — deleting the record of a live
  position leaves money at risk with nothing describing it. `purge_deleted` is a
  dry run until confirmed.
- **Query safety**: sort and filter fields are **whitelisted**. An arbitrary sort
  field is a collection scan on every request; a whitelist also means no request
  can smuggle in `$where` or an unanchored regex.
- **Oversized pages are refused, not clamped.** Asking for 10,000 rows and
  silently getting 200 leaves you believing you received everything.
- **Heavy fields excluded by default** — 25 trades with `price_evolution`
  attached is tens of megabytes.
- **Document-size guard before the write**, warning at 80% of 16 MB. Firestore's
  equivalent limit was only discovered when appends started failing.
- **Streaming** (`iter_trades`) for the AI layer, which reads the whole
  collection — a keyset cursor, so cost per batch is constant at any depth.
- **Statistics computed in the database**: `performance_stats` (win rate,
  expectancy in **dollars and R**, payoff, profit factor), `stats_by_symbol`,
  `stats_timeseries`.

#### `api/trades_controller.py`
23 routes under `/api/v1/trades`.

- **Consistent envelope on success and failure**, with a `request_id` so a
  user-reported failure can be found in the logs.
- **Error type maps to status**: 400 (caller's fault) / 404 (not an error) /
  503 (ours, retryable). Collapsing them into 500 makes retry logic impossible
  to write. Internal exception text is logged, never returned — tested that a
  URI with a password in the message does not leak.
- **JSON even for 404/405 and malformed bodies.** Flask's defaults return HTML,
  which breaks client error handling exactly when it is needed.
- Pagination (offset **and** cursor), sorting, filtering, numeric ranges,
  search, distinct values, bulk upsert, bulk delete, stats, diagnostics.

#### `monitor/trade_sink.py`
Mirrors live trades into MongoDB. **Fail-soft absolutely** — nothing here may
raise into a trading path. Because it swallows exceptions, failures are
**counted** and surfaced by `get_status()`, rather than being invisible.

#### `core/mongo/trade_data_monitor.py`
Watches what the live system is actually writing, unattended.

Every check is written against a **real defect that actually occurred** and
would have caught it: starved `price_evolution`, unreachable analysis, empty
closing analysis, ambiguous `close_reason`, a direction that disagrees with
itself, a document nearing the size limit. `self_check()` feeds it a
deliberately broken trade and requires the known defects to be detected, then a
clean one and requires silence — a monitor that reports healthy on garbage is a
stub.

---

## 3. Instrumentation: making components measurable

### `ai/trade_repository.py`
The bridge between the trading database and the AI layer. Every model reads
trades through it.

Two shapes had to be reconciled. What the monitor writes:

```
analysis_at_open = {"m1_analysis_raw": <the analysis>, "_encoded": False, ...}
price_evolution  = [{"analysis": {"m1": <blob>}, "_encoded": True, ...}]
```

What every model reads:

```
trade["analysis_at_open"]["final_verdict"]["probability_ledger"]
trade["price_evolution"][i]["analysis"]["m1"]["final_verdict"]
```

Neither resolved. The repository guarantees canonicalisation is always applied.

`load_training_set()` returns **features / path / labels separately** rather than
one merged dict, so a feature builder cannot reach outcome data by accident.
Merging them and trusting discipline is how a model ends up predicting the past.

### `core/microstructure_features.py`
The channel the system was blind to.

Every feature the system traded on came from **M1 bars**. On XAUUSD, 28,647
ticks arrive in thirty minutes and the analysis reduced them to one scalar,
`timing_confidence`, which then fell back to a constant 50 whenever the tick
fetch failed.

Computes order-flow imbalance, tick intensity, spread dynamics, micro-momentum,
realised volatility and price resilience across multiple windows. Signed against
the trade, never against the market.

**Honest limit:** retail MT5 ticks carry no true trade direction, so aggression
is inferred with the tick rule. That is a proxy and is labelled as one. `flags`
is deliberately not trusted — brokers populate it inconsistently.

### `ai/strategy_families.py`
The system is several contradictory strategies summed into one number.

23 categories: TREND, MEAN_REVERSION, SMC_STRUCTURE, ORDER_FLOW, FVG, ZONES,
SUPPORT_RESISTANCE, VOLUME_PROFILE, PARTICIPATION, VWAP, PATTERN, ELLIOTT_WAVE,
GNN, VOLATILITY, EXHAUSTION_ADR, MACRO, CONSENSUS, EXPECTED_VALUE, EXECUTION,
WYCKOFF, SESSION, NEWS, MICROSTRUCTURE.

Classification uses **longest-token matching** — first-match-wins made the result
depend on dict order, and `adr_exhaustion` was being swallowed by
MEAN_REVERSION's shorter `exhaustion` token.

`discover_opposition()` **measures** which families contradict each other rather
than assuming; `component_opposition()` does the same one level down, with no
family assumption at all.

### `core/component_reads.py`
Scores the subsystems that never enter the ledger.

`volume_profile`, `wyckoff`, `elliott_waves`, `wave_lattice`, `gnn`,
`smc.trade_setup` each produce a real directional read, are published in the
payload, and **had never been tested against an outcome**.

Signed against the trade. `contribution` is fixed at `0.0` — none has been
validated, and wiring an unvalidated component into the chain is exactly how
`pattern` came to push 12 points the wrong way.

An unrecognised recommendation returns `None`, not `0.0`: "we do not know what
this component said" and "this component said neutral" are different facts.

### `ai/component_audit_360.py`
Discovers and tests **every** scoreable field — 1,072 numeric + 179 categorical.

Eight layers: numeric, categorical, quantile/monotonicity, mutual information,
interaction, redundancy clustering, regime-conditional, per-symbol robustness.

Three bugs in this module were caught by its own self-check, each of which would
have produced a clean-looking report with the interesting fields silently
missing:

1. `MIN_DISTINCT = 3` discarded **every boolean flag** (a flag has 2 values)
2. `statistics.median` on a binary field returns one of the two values, so
   `v > median` selects an **empty side** and the field vanishes
3. after both fixes it still failed — a **second copy** of the threshold logic
   sat inline, which the fix never reached

### `ai/edge_discovery.py`
Searches the rule space on real outcomes.

The ledger records each component's exact delta, so a rule configuration is a
weight vector: `probability(w) = base + Σ wᵢ·δᵢ`. One expensive analysis pass can
be re-scored under thousands of configurations for free, and **every outcome is a
real price that really happened**.

Searches components × direction-flip × exit geometry × thresholds, scored on
walk-forward folds with paired significance and Benjamini-Hochberg FDR.

**Why not a diffusion model or GAN:** a generative model trained on this history
reproduces its statistical properties, so a strategy optimised against it
exploits the *generator's* artifacts. Synthetic markets are for stress-testing an
edge you already have, never for discovering one.

### `core/exposure_risk.py`
What unlimited concurrency actually costs.

At 2% risk per trade with unlimited same-symbol concurrency:

| book | nominal | correlated | effective bets |
|---|---|---|---|
| 10× EURUSD BUY @ 2% | 20.0% | **20.0%** | **1.00** |
| 10 uncorrelated @ 2% | 20.0% | 6.6% | 9.09 |

**Ten EURUSD trades put 20% of the account on a single bet.** Nothing else in the
system measures this.

It also computes **trade uniqueness** — those same ten trades carry roughly *one*
trade's worth of information, so treating them as ten independent samples
shrinks every confidence interval by ~√10 and manufactures significance exactly
where the current edges sit.

`effective_bets` was initially **inverted** (10 identical positions reported as
100 independent bets) — caught by self-check.

---

## 4. What the measurements actually say

### Confirmed — survives walk-forward folds AND a permutation null

**`pattern` / WAVE family** — +0.4880R pooled (p=0.0035), walk-forward +0.5897R,
**3/3 folds positive**. Corroborated four independent ways: ledger delta, family
decomposition, Elliott read, and the direction sign-correction.

**Microstructure order flow** — when flow agrees with the trade on both
horizons: **+0.2646R, positive in 4/4 folds**, beats a 500-shuffle null at
**p=0.0180**. The only edge from *new information* rather than new analysis.

### Killed with proper controls — fifteen

component inversion (P=0.945) · 82 entry filters (62% → 25% out of sample) ·
2,560 rule configs · exit geometry (the 77.6% was measuring a fifth of the data)
· MAE early warning (tautological at 6 points/trade) · log-odds aggregation
(fixes saturation 18%→0%, changes discrimination by 0.0013R) · probability
inversion · BUY/SELL asymmetry (0.0012R, p=1.0) · the 1,251-field audit (0 EDGE)
· wyckoff (in-sample +0.37R → −0.10R walk-forward) · volume profile ·
wave lattice · Elliott as independent (78.4% same as `pattern`) ·
regime-conditional selection (**p=0.0775 — closest miss**)

### Structural facts that do not need significance

- **TREND and MEAN_REVERSION conflict on 91.2% of trades.** The chain adds a buy
  signal to a sell signal nine times in ten.
- **`adr_exhaustion` vs `trend_cascade`: 98.3% conflict.** They essentially never
  agree, and both are summed anyway.
- **Confluence does not work.** 4-of-5 family agreement: **36.8% win, −0.0640R**.
  1-of-5: **51.7% win, +0.0991R**. More agreement is slightly *worse* — and
  "stack confluence, raise probability" is the system's core premise.
- **Regime dominates everything.** RANGING: 48.3% win, +0.0245R. TRENDING:
  36.8% win, −0.0983R.
- **330 of 1,251 fields never vary.**

### Group performance (in-sample; only WAVE is validated)

| group | n | win rate | expectancy | payoff |
|---|---|---|---|---|
| FLOW + WAVE both support | 31 | 48.4% | +0.4444R | 2.39 |
| WAVE supports \| RANGING | 52 | **51.9%** | +0.2653R | 1.65 |
| TREND + WAVE both support | 73 | 47.9% | +0.1915R | 1.66 |
| **baseline** | 215 | **43.3%** | **−0.0298R** | 1.22 |
| STRUCTURE supports \| TRENDING | 54 | 35.2% | −0.2124R | 0.86 |
| MEAN_REVERSION \| TRENDING | 15 | 33.3% | −0.3836R | 0.22 |

---

## 5. The strategy for high expectancy and high win rate

### What the numbers permit

Direction entropy on 215 trades is **1.0000** — entries carry no directional
information. Win rate is a function of entry direction accuracy, so **win rate is
not the reachable lever at the current edge**. Expectancy is.

Measured on real paths, the frontier at the *current* edge:

| geometry | win rate | expectancy |
|---|---|---|
| TP 0.5R / SL 1.0R | **65.2%** | +0.0280R |
| TP 0.5R / SL 1.5R | 68.2% | +0.0703R |
| TP 2.0R / SL 1.0R (current) | 42.4% | **+0.1948R** |

All three ≥60% geometries **hold out of sample**. So 60%+ win rate with positive
expectancy is genuinely available — it costs about **0.17R per trade** versus
letting winners run. You can have 60% *with* positive expectancy; you cannot have
60% *and* the highest expectancy, at this edge.

**That last clause is the whole point.** The frontier is a property of the
current edge. A larger edge moves it outward and both rise together. Which is
why the strategy is not "pick a point on the frontier" but "enlarge the edge".

### Target, in numbers

60% win at a 2R target = **+0.8R expectancy**. Currently 42.4% at 2R = +0.195R.
The goal is roughly **4× the current edge**. A coin-flip entry hitting +2R before
−1R lands at ~33%; you are at 42%, so real edge exists — it needs to roughly
double in accuracy terms.

### The four moves, in order

**1. Stop summing opposed strategies.**
Trend says buy strength, mean-reversion says buy weakness. Summing them means in
a trend the trend components are right and the reversion components are wrong,
and averaged over a mixed sample they cancel — which is a mechanical explanation
for entropy 1.0000. Measured: they conflict on **91.2%** of trades. Regime
selection currently sits at **p=0.0775**; family scores are now recorded
separately so forward data can settle it.

**2. Add information, do not re-slice it.**
Fifteen hypotheses died. All but one re-sliced bar-derived features. The one that
survived came from **ticks** — a channel operating at a timescale bars cannot
represent. 215 trades × ~20 bar features has finite information content, and no
technique redistributes it into an edge.

**3. Attack payoff, not win rate.**
The `pattern` fix moved held-out expectancy from −0.0764R to +0.0680R **through
payoff** (1.39 → 1.72), not through winning more often. At ~2:1 R:R you do not
need a high win rate — 40% at 2:1 is profitable, and chasing 60% would cost more
in payoff than it gains.

**4. Collect enough trades to resolve anything.**
With 215 trades, the best configuration found in **pure noise** still reaches
**61.5% win rate**. Nothing at 60% is distinguishable from luck. That is
arithmetic about 82 hypotheses over 65 test trades, not pessimism.

### Sequence

1. **Run the monitor.** Every trade now records microstructure at entry, 23
   family scores, component reads, and per-minute `risk_state` + flow.
2. **At ~500 trades**: re-run `edge_discovery.search_all()` and
   `strategy_families.analyse()`. Settle `pattern` forward, microstructure
   forward, and the regime question.
3. **At ~1,000 trades**: meta-labeling becomes trainable — the standard technique
   for exactly this situation (no directional edge, some signal present). Keep
   the entries, train a second model to predict whether *this* signal wins, and
   size on that probability.
4. **Only then** edit the rule base. Every change goes through the chronological
   split first.

### The discipline that makes this work

Four separate "improvements" looked good in-sample and reversed out of it this
session — including one that was **shipped** before being validated
(`choppy_market_mode`, reverted after the held-out split showed the original
rules were best). Every rule change must survive:

1. a chronological or walk-forward split, chosen on train, scored on test
2. a permutation null — what the identical search finds with no signal at all
3. FDR across every hypothesis tested, not only those that already looked good
4. a per-symbol check — an edge carried by one instrument is that instrument's

**Weight by uniqueness once concurrency is high.** Ten overlapping trades are not
ten observations, and `core/exposure_risk.py` computes the correction.

---

## 6. Files added

| file | purpose |
|---|---|
| `core/mongo/mongo_config.py` | connection, pooling, timeouts, credential redaction |
| `core/mongo/trades_service.py` | full CRUD, `$push` price points, 3 delete strategies, stats |
| `core/mongo/trade_data_monitor.py` | unattended defect detection on live trades |
| `core/mongo/trade_generator.py` | generate trades from historical bars, stamped `is_simulated` |
| `api/trades_controller.py` | 23 REST routes with pagination, search, diagnostics |
| `monitor/trade_sink.py` | fail-soft mirror of live trades into MongoDB |
| `core/microstructure_features.py` | tick-level order flow — the new information channel |
| `core/component_reads.py` | scores subsystems that never enter the ledger |
| `core/exposure_risk.py` | correlation-adjusted exposure and trade uniqueness |
| `ai/trade_repository.py` | the bridge between the trading DB and the AI layer |
| `ai/strategy_families.py` | 23 strategy categories, opposition discovery |
| `ai/component_audit_360.py` | 8-layer audit of every scoreable field |
| `ai/edge_discovery.py` | rule-space search with walk-forward, FDR, permutation |
| `tests/test_trades_service.py` | 23 tests |
| `tests/test_trades_controller.py` | 25 tests |
| `tests/test_edge_research.py` | 29 tests |
| `tests/test_ai_reads_live_shape.py` | 12 tests |
| `tests/test_trade_persistence.py` | 12 tests |
| `tests/test_scorer_direction_alignment.py` | 17 tests |
| `tests/test_live_capture_readiness.py` | 12 tests |

Every new module has `get_status()` and `self_check()`. Every `self_check` plants
a known answer and requires recovery, including the negative case where the
correct answer is "nothing here" — because a check that cannot fail is
indistinguishable from a stub returning success.
