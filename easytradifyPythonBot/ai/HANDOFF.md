# Handoff — resume here

Written 2026-09-09. Read this first, then `ai/EDGE_RESEARCH.md` for the detail.

---

## 1. Do this first

**Run the monitor:**

```
cd C:\Users\msi\OneDrive\Bureau\tradify\easytradifyPythonBot
python api\hybrid_monitor.py
```

**After the first trade opens, confirm storage:**

```
python -c "import sys;sys.path.insert(0,'.');import core.console_safe;from core.mongo import get_trades_service as g;s=g();d=list(s.collection.find().limit(1));print('trades:',s.collection.count_documents({}));print('points:',len((d[0].get('price_evolution') or [])) if d else 0);print('analysis:',bool(d[0].get('analysis_at_open')) if d else False)"
```

Expected: `trades ≥ 1`, `points` growing by one per minute, `analysis True`.
Anything zero means the mirror is not landing — investigate before collecting.

**Check the sink is healthy after any restart:**

```
python -c "import sys;sys.path.insert(0,'.');import core.console_safe;import monitor.trade_sink as s;print(s.get_status())"
```

`degraded: False`, `failures: 0`.

---

## 2. State at the end of the session

**Everything is built, tested and green.** Full suite passes (exit 0). Trades
save to MongoDB only; Firestore receives none. Verified end to end: open, price
points, close, zero sink failures, Firestore trade count 0.

**Verified but worth re-confirming live:** a completeness gate script
(`scratchpad/gate2.py`) was written to check every stored field in one report.
It hung on the Mongo connection and never produced output. The individual facts
it checks were each verified separately — this is a nice-to-have report, not an
open question. Do not spend long on it.

---

## 3. What the data says

**Two confirmed edges** (walk-forward + permutation null):

| edge | strength | notes |
|---|---|---|
| `pattern` / WAVE | +0.4880R, p=0.0035, 3/3 folds | corroborated four ways |
| microstructure order flow | +0.2646R, p=0.0180, 4/4 folds | only edge from *new information* |

**Fifteen hypotheses killed** with proper controls. Closest miss:
regime-conditional family selection at **p=0.0775** — revisit this first with
more data.

**Structural facts** (no significance test needed):

- TREND and MEAN_REVERSION conflict on **91.2%** of trades — the probability
  chain adds a buy signal to a sell signal nine times in ten
- **Confluence does not work**: 4-of-5 family agreement wins **36.8%**
  (−0.0640R); 1-of-5 wins **51.7%** (+0.0991R)
- Regime dominates: RANGING 48.3% / +0.0245R, TRENDING 36.8% / −0.0983R
- 330 of 1,251 analysis fields never vary

**The bottleneck is trade count.** With 215 trades, the best subset of *shuffled
noise* still reaches 61.5% win rate. Nothing at 60% is distinguishable from luck
until there are far more trades.

---

## 4. Next steps, in order

1. **Collect.** Every trade now records `microstructure_at_entry`,
   `strategy_family_scores` (23 categories), `component_reads`, and per-minute
   `risk_state` + flow — none of which touches a decision.

2. **At ~500 trades**, re-run:
   ```python
   from ai import edge_discovery, strategy_families, trade_repository as repo
   trades = repo.load_trades(status="CLOSED")
   edge_discovery.search_all(trades=trades)
   strategy_families.analyse(trades=trades)
   ```
   Settle: `pattern` forward, microstructure forward, and the regime question
   currently stuck at p=0.0775.

3. **At ~1,000 trades**, meta-labeling becomes trainable — the standard
   technique when entries carry no directional edge but signal exists. Keep the
   entries, train a second model to predict whether *this* signal wins, size on
   that probability. `core/meta_labeling.py` exists but is wired for replay
   captures, not stored trades.

4. **Only then** edit the rule base around the discovered categories. Fares
   plans this and is right to wait for the data.

---

## 5. Things that will bite you

**Uniqueness weighting.** Concurrency is unlimited
(`MAX_SIMULTANEOUS_TRADES = 100000`, `MAX_TRADES_PER_SYMBOL = 100000`,
`TOP_SYMBOLS_COUNT = 100`). Ten EURUSD trades opened together are **one bet**,
not ten — at 2% risk that is 20% of the account on a single position, and
statistically they carry ~one trade of information. `core/exposure_risk.py`
measures both (`concurrent_exposure`, `effective_sample_size`) but blocks
nothing. **Weight by uniqueness in every statistic once concurrency is high**,
or p-values will be inflated by ~√(trades/effective).

**No storage fallback.** Firestore no longer stores trades. If Mongo is down at
trade open, that trade has no record anywhere.

**Nothing new is wired into the probability.** `microstructure`,
`component_reads` and `strategy_family_scores` all carry
`contribution = 0.0`, enforced by tests. That is deliberate — adding an
unvalidated component to the chain is how `pattern` came to push 12 probability
points the wrong way on 26% of trades. Do not wire any of them in until the
forward data validates them.

**GNN is enabled live** (`use_gnn=True` by default, `is_gnn_available()` returns
True). It was 0/215 in the historical data only because *enrichment* passed
`use_gnn=False`. Forward trades will carry a real GNN read for the first time.

---

## 6. Where things live

| file | what it is |
|---|---|
| `ai/EDGE_RESEARCH.md` | full detail: every file explained, all findings, the strategy |
| `core/mongo/trades_service.py` | the only module that touches the trades collection |
| `api/trades_controller.py` | 23 REST routes — query, search, stats, diagnostics |
| `monitor/trade_sink.py` | fail-soft mirror into Mongo (counts failures) |
| `ai/trade_repository.py` | the bridge every AI model reads trades through |
| `ai/edge_discovery.py` | rule-space search with walk-forward, FDR, permutation |
| `ai/strategy_families.py` | 23 categories, opposition discovery, regime split |
| `ai/component_audit_360.py` | 8-layer audit of all 1,251 scoreable fields |
| `core/microstructure_features.py` | tick-level order flow (the new channel) |
| `core/component_reads.py` | scores subsystems that never enter the ledger |
| `core/exposure_risk.py` | correlation-adjusted exposure, trade uniqueness |

Every module has `get_status()` and `self_check()`. Each `self_check` plants a
known answer and requires recovery — including the negative case, because a
check that cannot fail is indistinguishable from a stub returning success.

**Run the tests before changing anything:** `python -m pytest tests/ -q`

---

## 7. The one habit that matters

Four "improvements" looked good in-sample and reversed out of sample this
session — including one that was **shipped** before being validated and had to
be reverted. Every rule change goes through the chronological split, a
permutation null, FDR across all hypotheses tested, and a per-symbol check.

Ruling a hypothesis out is worth as much as confirming one. Fifteen were ruled
out here; each would have looked like an edge and cost months.
