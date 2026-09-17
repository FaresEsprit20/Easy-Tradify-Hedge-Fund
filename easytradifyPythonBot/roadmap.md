# Roadmap — building v2

> **2026-09-17: superseded for new work by `strategic_plan_v4.md`.** The v2 build below is complete and measured
> (`reports/v2/RESULTS.md`). No category reached the target, so v4 changes the order: measure the M1 predictability
> limit per market first (Gate 1), build rules only where the target is reachable.


*2026-09-16. This file carries out `strategic_plan.md`. Update the status table at the end of every
session.*

- **`strategic_plan.md` is the why and the what:** the decision, what v1 really trades, the defects
  by layer, the v2 philosophy, the categories, the architecture.
- **This file is the how and the when:** phases, the files each one delivers, when each is done,
  estimates, order.
- **v1 is frozen** (plan §1). No phase changes v1's `core/`, `monitor/` or `api/`, except the shared
  infrastructure listed in plan §8, and only when v2 needs it.
- **Earlier content moved:** the broken-parts inventory that used to be here is now plan §2–3.

---

## Order of work

```
0 Freeze v1 ─► 1 Specs ─► 2 Data ─► 3 Market model ─► 4 Triggers & context ─► 5 Categories ─┐
                    │                                                                     │
                    └──────────► 6 Execution (in parallel, once the Setup contract exists)│
                                                                                          ▼
          11 Demo ◄── 10 Shadow ◄── 9 Risk, journal, ledger ◄── 8 Probability ◄── 7 Trade manager
```

## Package layout (proposed)

```
engine_v2/
  specs/          philosophy.md, setup_contract.md, v1_building_map.md,
                  services/*.md, categories/*.md
  golden_cases/   <service or category>/*.json   symbol, time window, expected detection
  data/           bars from ticks (mid/bid/ask, closed bars); live and replay adapters
  market_model/   structure.py, liquidity.py, zones.py, volume.py, fair_value.py, regime.py, session.py
  triggers/       events.py
  context/        htf_trend.py, regime_state.py
  categories/     trend.py, momentum.py, mean_reversion.py, structure.py, smc.py,
                  order_flow.py, wave.py, cross_asset.py   (each a separate strategy)
  setup.py        Setup contract and lifecycle
  probability/    win-frequency tables, measured condition effects
  selection.py    highest real probability among tradeable setups
  risk.py         lot from the caller's risk
  execution/      limit / stop / market orders, pending lifecycle, fills
  manager/        thesis checks and exits
  journal/        MongoDB setup journal
  config_ledger.py
  analysis.py     analyze_institutional_signal (v2)
tests/engine_v2/
```

---

## Phase 0 — Freeze v1 (½–1 session)
**Goal:** v1 becomes the unchanged reference.

**Deliverables**
- **A git tag, `v1-frozen-2026-09-16`.** Pending changes are committed first, with the operator's
  go-ahead.
- **`engine_v2/specs/v1_building_map.md`**, containing:
  - the traced trade path (plan §2);
  - the defects by layer (plan §3);
  - where every v1 rule goes in v2 (plan §5).
- **v1 keeps running on demo, unchanged.**

**Done when:** the tag exists and the map is written.

## Phase 1 — Specifications (2–3 sessions)
**Goal:** every part of v2 is defined before any code is written.

**Deliverables**
- **`specs/philosophy.md`:** the ten rules of plan §4, each with how code or tests enforce it.
- **`specs/setup_contract.md`:** the fields, the lifecycle states, who may set each field, and the
  format of a thesis condition.
- **`specs/services/`** for structure, liquidity, zones, volume, fair value, regime and session.
  Each defines inputs (timeframe, mid bars), outputs, and parameters with starting values and the
  reason for each.
- **`specs/categories/<category>.md`** for TREND, MOMENTUM, MEAN_REVERSION, STRUCTURE, SMC,
  ORDER_FLOW, WAVE and CROSS_ASSET: each category's setup anatomy from plan §5, as exact rules:
  - applies when;
  - location and trigger;
  - entry order type and price;
  - stop and targets;
  - thesis conditions and their actions;
  - validity window;
  - parameters (N, k).
- **`golden_cases/`:** 10–20 historical chart examples per service and per category, each with its
  symbol, time and expected detection, plus examples that must not be detected.

**Done when:** the operator approves each category spec, starting with SMC and STRUCTURE.

## Phase 2 — Data layer (1–2 sessions)
**Deliverables**
- **Bars from ticks:** mid/bid/ask OHLC, spread and tick count for every timeframe from M1 to D1,
  served through a closed-bar API on the broker clock.
- **One interface, two adapters:** MT5 for live, and `ticks_m1` plus Dukascopy for replay.
- **Replay history:** finish the Dukascopy bid/ask M1 download for 2022–2025
  (`C:/Users/msi/tradify_study/dukascopy_m1.py`).

**Done when:**
- for a live week, live bars equal replay bars;
- a test proves a decision cannot read the forming bar.

## Phase 3 — Market model services (4–5 sessions)
Built in dependency order:
1. **Structure:** swings, HH/HL/LH/LL, BOS and CHoCH per timeframe.
2. **Liquidity map:**
   - prior day, week and session highs and lows;
   - equal highs and lows;
   - sweeps (a break that closes back).
3. **Zones:**
   - S/D bases with range, departure strength, freshness, touches and invalidation;
   - order blocks, FVGs and S/R;
   - overlapping areas merged into one zone with a confluence count and its sources.
4. **Volume:**
   - tick volume;
   - session and day profile (POC, VAH, VAL, high- and low-volume nodes);
   - delta from up/down ticks;
   - acceptance and rejection of value.
5. **Fair value:** session VWAP, EMA baselines, fitted mean.
6. **Volatility, regime, session:** ATR per timeframe, trend/range/balance state, session clock.

**Done when (each service):**
- golden cases are detected as specified;
- unit tests are green;
- output is identical live and in replay;
- it has been reviewed against the 2026-09-15 defect classes (plan §6 rule 9).

## Phase 4 — Trigger and context libraries (1–2 sessions)
- **Triggers:**
  - closed rejection candle, lower-timeframe BOS, sweep-and-reclaim;
  - MACD histogram re-cross, stochastic or RSI crossing back from an extreme;
  - squeeze release, divergence;
  - value-area acceptance and rejection.
- **Context:**
  - HTF trend by structure, regime state, session;
  - Elliott phase (optional, strict impulse rules only).

**Done when:**
- golden cases pass;
- every trigger fires at a bar time;
- its coverage is reported, and it is false on most bars.

## Phase 5 — Category strategies (1–2 sessions per category, 10–14 in total)
**Order:** SMC and STRUCTURE → TREND → ORDER_FLOW → MOMENTUM → WAVE → MEAN_REVERSION → CROSS_ASSET.

**For each category:**
1. Implement the spec on top of the services, triggers and context.
2. Pass the golden cases.
3. Replay the full history into a **setup journal**: every proposed setup, with its full trade
   configuration and its outcome on bid/ask ticks.
4. Operator review: the journal's setups look like the category on the chart.
5. Build the **win-frequency table** per variant, with sample size and range, from the holdout period.

**Done when:**
- golden cases pass;
- the operator has reviewed the journal;
- the category wins ≥ 55% at its own geometry on the holdout period.

## Phase 6 — Execution layer (1–2 sessions; can start after Phase 1)
**Deliverables**
- **Orders from the Setup's entry:** limit, stop and market orders, expiring at `valid_until`, with
  cancel and modify.
- **Bid/ask placement:** entry and stop placed correctly for the bid/ask side, from mid-price levels.
- **Pending-order support:** check that the MT5 EA and Python path support pending orders (today the
  bot only sends market orders); extend them if not.
- **Reconciliation:** fills reconciled with broker deals (`core/broker_facts.py`).

**Done when:** on demo, pending orders are placed, filled, expired and cancelled exactly as the setups
specify, and the journal matches the broker's deals.

## Phase 7 — Trade manager (2 sessions; after the first category exists)
**Deliverables**
- **Thesis checks:** every thesis condition evaluated on each closed bar.
- **Actions:** exit, partial exit, move the stop to structure, time exit.
- **Management plans:** one per category, from its spec.
- **Reversal report per category:** trades that reached +0.25R and ended at the stop, with the thesis
  event that came before each.

**Done when:**
- every exit, in replay and on demo, carries its thesis reason;
- each category's reversal share is reported, and is lower than for the same setups replayed without
  management.

## Phase 8 — Probability and selection (2 sessions)
**Deliverables**
- **Win-frequency tables** per category and variant, from the setup journals on the holdout period,
  with sample size and range. Below the minimum sample the probability is **"unknown"**, and the
  setup cannot trade live.
- **Condition effects:** context, or another category agreeing, is measured as a change in win
  frequency, and used only where the information is independent.
- **Selection:** the tradeable setup with the **highest real probability**, within exposure and
  correlation limits.
- **No scores anywhere:** a test proves every probability comes from a frequency table. No points,
  clamps or hand-set weights exist in v2.

**Done when:** predicted and realised win rates agree within ±3 points per decile on holdout.

## Phase 9 — Risk, journal, monitoring, config ledger (1–2 sessions)
**Deliverables**
- **Lot sizing:** the lot comes from the caller's `risk_per_trade` × `fixed_trade_size_usd`, capped
  by `MAX_RISK_PER_TRADE`. Unaffordable setups are flagged, never re-stopped.
- **Setup journal in MongoDB:** taken, skipped and expired setups, with thesis and outcome.
- **Per-category live view:** win rate, R, reversal share, sample size.
- **Config ledger:** a test fails on any unused flag or any constant without a ledger entry.
- **v2 `analyze_institutional_signal`:** returns `setups`, `not_tradeable`, `probabilities`,
  `selected` and `market_model` (plan §6).

**Done when:** all tests are green and the ledger is complete.

## Phase 10 — Shadow run (2–4 weeks)
- v2 runs beside v1 on live data. It journals every setup and sends no orders.
- Weekly review per category: setups vs spec, live win frequency vs replay frequency.

**Done when:** every category has live setups journaled, with live frequencies inside their replay
ranges.

## Phase 11 — Demo trading and promotion
- Categories are switched on one at a time on demo, in build order.
- v1 stops when v2 is live (operator decision).

**Done when:** ≥ 65% won and ≥ +0.2R net per trade over ≥ 50 demo trades, with each category inside its
measured range.

---

## Estimates

| phase | sessions |
|---|---|
| 0 Freeze v1 | ½–1 |
| 1 Specs | 2–3 |
| 2 Data | 1–2 |
| 3 Market model | 4–5 |
| 4 Triggers and context | done: rejection/engulfing triggers, BOS triggers, H4/H1 structure context | 2026-09-16 |
| 5 Category strategies | v3 (2026-09-17): v2.1 rules failed on 19 unseen pairs; cross-pair discovery on 30 pairs passed only STRUCTURE+medium-volatility+secure-half (t=2.19 held-out) and it weakened to t=1.3 on full rebuild. No category validated (`reports/v2/RESULTS.md`) | 2026-09-17 |
| 6 Execution | 1–2 |
| 7 Trade manager | built: T1 partial, breakeven, time stop, thesis exits (same rules as replay); unit-tested | 2026-09-16 |
| 8 Probability and selection | built: holdout win-frequency tables with Wilson range, unknown below 100 trades, highest-real-probability selection. All probabilities 17–48% | 2026-09-16 |
| 9 Risk, journal, ledger | built: lot from caller risk, JSONL journal (Mongo off), config ledger + orphan test, v2 analysis entry point | 2026-09-16 |
| **Total** | **≈ 26–35 sessions**, then 2–4 weeks of shadow, then demo |

## Next session: checklist
1. Read `strategic_plan.md`, then this file.
2. **Phase 0:** ask the operator to commit or confirm the pending changes, tag v1, and write
   `v1_building_map.md`.
3. **Phase 1:** write `philosophy.md`, `setup_contract.md`, `specs/categories/smc.md` and
   `specs/categories/structure.md`, with golden-case candidates, for the operator to review.
4. Update the status table below.

## Status

| phase | status | date |
|---|---|---|
| Strategic plan and roadmap written | done | 2026-09-16 |
| 0 Freeze v1 | done: frozen at commit 853243e (no tag without operator OK); `engine_v2/specs/v1_building_map.md` | 2026-09-16 |
| 1 Specs | done: philosophy, setup contract, services, 8 category specs; golden cases as synthetic tests (pending) | 2026-09-16 |
| 2 Data layer | done: clock, bid/ask/mid bars, replay loader, live MT5 tick adapter, symbol facts. Dukascopy 2022–2025 download stopped (throttled, gappy); see `reports/v2/RESULTS.md` | 2026-09-16 |
| 3 Market model services | done: indicators, zigzag structure, BOS/CHoCH, liquidity pools + sweeps, FVG, displacement, S/D zones, VWAP, day profiles; synthetic golden tests pass | 2026-09-16 |
| 4 Triggers and context | done: rejection/engulfing triggers, BOS triggers, H4/H1 structure context | 2026-09-16 |
| 5 Category strategies | v3 (2026-09-17): v2.1 rules failed on 19 unseen pairs; cross-pair discovery on 30 pairs passed only STRUCTURE+medium-volatility+secure-half (t=2.19 held-out) and it weakened to t=1.3 on full rebuild. No category validated (`reports/v2/RESULTS.md`) | 2026-09-17 |
| 6 Execution layer | built: MT5 pending/market requests, dry-run broker, `V2_LIVE_ORDERS = False`; not sent live | 2026-09-16 |
| 7 Trade manager | built: T1 partial, breakeven, time stop, thesis exits (same rules as replay); unit-tested | 2026-09-16 |
| 8 Probability and selection | built: holdout win-frequency tables with Wilson range, unknown below 100 trades, highest-real-probability selection. All probabilities 17–48% | 2026-09-16 |
| 9 Risk, journal, ledger | built: lot from caller risk, JSONL journal (Mongo off), config ledger + orphan test, v2 analysis entry point | 2026-09-16 |
| 10 Shadow run | v2.1 runner on live MT5 H1 data works (`python -m engine_v2.run.shadow`); forward run needed to prove v2.1 rules on unseen trades | 2026-09-17 |
| 11 Demo and promotion | blocked: promotion criteria not met by any category | 2026-09-16 |
