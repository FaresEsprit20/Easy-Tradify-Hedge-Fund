# Strategic plan — rebuilding Tradify as a real trading system (v2)

*2026-09-16. `roadmap.md` turns this plan into phases, deliverables and status.
`diagnosis.md` holds the measurements referred to below.*

---

## 1. The decision

**v1 is not repaired any further.** It stays frozen and keeps running on demo as the reference. v2 is
built from the trading philosophy down.

Why:
- The building does not implement the strategies it names (§2).
- Every layer of it is broken (§3).
- Testing or patching a broken building cannot turn it into a working one. This is an engineering
  and philosophy problem.

**Goal for v2:** ≥ 65% of trades won and ≥ +0.2R net per trade, on live demo trades.

---

## 2. What v1 really trades, traced through the code

Question (operator): *when the system says SMC, does it really trade SMC? Or mean reversion, or
structure? Or is it just a shape?*

**Answer: it trades none of them.** Every trade, whatever its label, goes through the same six steps:

| step | what v1 does | where (`easytradifyPythonBot/`) |
|---|---|---|
| 1. Choose the side | adds indicator points for BUY and for SELL; the bigger total wins, and a tie goes to the trend | `core/asset_analysis.py:2405, 2441, 2529-2566` (`calculate_real_probability`) |
| 2. "Strategy" | the eight categories score that side **after** it has been chosen; no category ever proposes a trade | `core/asset_analysis.py:3883` → `core/strategy_groups.py:617` |
| 3. Name | the highest-scoring category's name is written into the report | `core/asset_analysis.py:1062, 4048`; only `core/skipped_setups.py:106` reads it |
| 4. Entry | a market order at analysis time, never at a level | `core/execution.py:2614-2625` (`TRADE_ACTION_DEAL`); the bot never sends a limit or stop order |
| 5. Stop / target | 1.5 × H1 ATR and 1R, identical for every category | `core/asset_analysis.py:2809-2810` → `core/market_stop.py:53-54` |
| 6. Management | none: no trailing, no breakeven, no partial profit, no thesis check | `monitor/monitor_core.py:1887` (`enable_trailing_stop=False`) |

What each label is missing:

| label | what the strategy actually trades | what v1 does instead |
|---|---|---|
| **SMC** | sweep → displacement → entry at the FVG or order block, stop beyond the swept extreme, target at the opposing liquidity | market order, ATR stop, 1R |
| **STRUCTURE** | waits for price at the zone, stop beyond the zone | market order, ATR stop, 1R |
| **MEAN_REVERSION** | targets fair value, with a time stop | market order, ATR stop, 1R |
| **WAVE (Elliott)** | end of a corrective wave within strict impulse rules → entry for the next impulse, stop at wave 1's origin, target by wave projection | market order, ATR stop, 1R |

**The categories are names on a score.** The shape is borrowed; the trade is the same market order
every time. This is the root failure, and every defect in §3 sits on top of it.

### The side chooser: `calculate_real_probability`
- **Is it used?** Yes, on every analysis. It is called once for BUY and once for SELL
  (`core/asset_analysis.py:2405, 2441`), and the larger number decides the side of the trade
  (`:2529-2566`).
- **What is it?** About 400 lines of point additions and subtractions
  (`core/calculations.py:1758-2151`). It feeds on trend, S/D grade, at-zone, Wyckoff score and
  phase, volume ratio, RSI, ICT signal, ADX, Bollinger, MACD, stochastic, RSI divergence, candle
  score, FVG distance and resistance distance, all as hand-set points.
- **What happens to its number?** The category score overwrites it later
  (`core/asset_analysis.py:3896-3898`), but **the side it chose stays**. The strategies only ever
  grade that side.
- **Measured:** on stored bars it scored both sides ≥ 75 on 42 of 105 bars, AUC 0.479 (note above
  `USE_STRATEGY_GROUP_PROBABILITY` in `core/asset_analysis_config.py`).
- **v2: removed.** No side exists before a category proposes a setup.

---

## 3. The building: defects by layer

Verified on 2026-09-16 in the code and in recorded measurements.

### 3.1 Philosophy and architecture
- **Strategies don't create setups.** They grade a side chosen by an additive indicator chain (§2).
- **Categories can only repeat the trend.** 24 of the 33 category rules are wrapped in
  `_trend_confirmed` (`core/strategy_groups.py:314-322`), so they speak only when they agree with
  the trend cascade. 61% of decisions have every category agreeing.
- **Those wrappers were fitted on a broken test.** The repair table they came from (`:258-299`)
  used 3,528 snapshots from 111 trades, bid bars and no control, and reported 61–89%. On 110,603
  decisions scored against real bid/ask ticks, the same categories measure AUC 0.48–0.53.
- **Sequences are scored as votes.** An SMC sequence is scored as sweep, structure and FVG type all
  voting at the same moment.
- **Some categories exist in name only:**
  - CROSS_ASSET is the GNN listed twice (`:524-525`).
  - MEAN_REVERSION never speaks: its OU gate opened 53 times in 40,323 checks.
  - STRUCTURE and SMC are excluded from every decision (`:109`).
- **Rules contradict each other:**
  - Bollinger band walk counts as continuation (`:482-483`), while RSI and stochastic extremes count
    as reversal (`:486-489`).
  - Premium/discount is inverted (`:502-503`).

### 3.2 Market model (how price is read)
- **No shared market model.** Each indicator computes its own swings, levels and trend. S/D, S/R,
  Fibonacci, order blocks and FVGs mark overlapping areas and vote separately.
- **Levels and price disagree.** Levels are built on bid bars and compared with the ask
  (`USE_MID_PRICE_FOR_INDICATORS = False`, `core/asset_analysis_config.py:1062`, used at
  `core/asset_analysis.py:1944`). The config's own note says this biases readings bullish, most of
  all when spreads widen.
- **Zones are half-built:**
  - A zone is a single level: no range and no invalidation level.
  - Zone grading runs backwards (grade vs result −0.286).
  - The engine's S/D call speaks on ~4% of bars; its state version speaks on 100%.
  - Zone weight in the probability is 0 (`PROB_SCALE_ZONE`, config `:1376`).
- **States instead of events.** Zone side, EMA200 side and POC side are true on 98.7–100% of bars,
  so they cannot time an entry.
- **Readings measured inverted still vote their original way** (MACD histogram, price vs EMA200:
  `core/strategy_groups.py:470, 472`).

### 3.3 Volume
- **Volume profile barely enters.** It appears only as position vs POC (98.7% of bars) and as one
  trend-gated vote (`:509-510`). Its levels are built on bid bars.
- **No volume events** exist: no acceptance or rejection of value, no participation burst at a
  level, no delta divergence.
- **Shipped while unstable.** The volume repairs were unstable in their own repair table (49/85 and
  77/46) and shipped anyway.

### 3.4 Probability
- **The score measures the gate, not the evidence.** A category scores `50 + 45 × agreement`
  (`:650-652`). Whenever two wrapped rules speak, that is exactly 95.
- **Penalties admit trades.**
  - That 95 becomes the decision probability (`core/asset_analysis.py:3896-3898`).
  - Entry needs 75–83 (`core/entry_engine.py:882-883`).
  - So a trade passes only when penalties pull 12–20 points off the 95.
- **Not a frequency.** Correlation with being right was +0.011, and AUC is 0.54 after the
  2026-09-16 fix. The most confident decile is among the worst.
- **Thresholds set on tiny samples.** The floor of 75 was set on 66 entries, and
  `PROBABILITY_RECENTER_POINTS = 20` on stored trades.
- **The calibrated model used the old labels.** It was fitted before the tick relabel and runs in
  shadow only.

### 3.5 Execution and management
- **One trade for every label.** Market entry only, with one stop/target geometry (§2).
- **Winners are given back.** 72.7% of trades reach +0.25R and 70.6% still end at the stop. A peak
  inside the first hour holds only 2.8% of the time (`core/market_stop.py:34-40`). Nothing reacts
  inside the trade.
- **A veto learned from 11 trades.** The symbolic gate blocks entries based on 11 stored failures
  (`core/asset_analysis.py:5817`).
- **An interface that promises what it doesn't do.** `analyze_institutional_signal` accepts
  `stop_loss_pips` and `take_profit_pips` and ignores them (`core/asset_analysis.py:1721-1745`).

### 3.6 Config set on weak or invalid evidence

| config | value | set on | problem |
|---|---|---|---|
| member repairs (24 wrappers, 2 inversions, ranging-only GNN) | — | 3,528 snapshots / 111 trades, bid bars | contradicted on 110,603 tick decisions |
| `STRATEGY_GROUP_MIN_PROBABILITY` | 75 | 66 stored entries | tiny sample, on a score stuck at 95 |
| `PROBABILITY_RECENTER_POINTS` | 20 | stored trades | moved every threshold at once |
| `MAX_PROBABILITY_FOR_ENTRY` | 83 | 61,950 tick decisions | selects trades by their penalties (§3.4) |
| `USE_SYMBOLIC_GATE` (enforcing) | on | 11 stored failures | veto on a tiny sample |
| `USE_CONVICTION_FILTER` | True | — | **orphan**: the filter was deleted (note near `core/asset_analysis.py:5743`), but the flag still reads as active |
| `REVERSION_FADES_ENABLED` | True | — | its own note says it "stays False" |
| `ALLOW_UNCONFIRMED_ENTRIES` | False | n = 14 | tiny sample |
| `PROB_SCALE_ZONE`, `PROB_SCALE_ICT` | 0 | stored trades | zones removed from the probability |
| `FVG_IFVG_WEIGHT` | 0.05 | stored trades | — |
| ADR exhaustion adjustment | −12 both ways | stored trades | also admits trades through the band |
| `USE_MID_PRICE_FOR_INDICATORS` | False | — | bid levels compared with the ask price |
| `core/calibrated_model.json` | shadow | fitted before the tick relabel | its +0.232R / 77.3% result used bid labels |

### 3.7 Why v1's repairs kept failing
Repairs were accepted on bid bars, about a hundred trades, and no control. Bid bars produce about
0.14R of fake reversion, and four false edges came from them. A 200-tree model scored the same on
shuffled labels as on real ones. v1 was repaired again and again, but the changes only fit noise.

---

## 4. v2 trading philosophy

These are binding rules for every part of v2.

1. **A trade is a setup, not a score. Every category proposes its own setup.** Each category
   proposes its own trade configuration:
   - side, context, location and trigger;
   - entry order (type and price);
   - stop at the thesis's invalidation;
   - targets, management plan and validity window.

   Nothing else can create or flip a trade.
2. **Risk belongs to the user, not to the category.** Every setup uses the risk the caller passes to
   asset analysis: `risk_per_trade` × `fixed_trade_size_usd`, capped by `MAX_RISK_PER_TRADE` (today
   $4). The category sets the stop; the lot is that risk divided by the stop distance. A setup whose
   stop needs more than that risk at the minimum lot is marked **unaffordable**. It is never
   resized to a tighter stop.
3. **Each category is traded the way the category defines it.** If the system says SMC, the trade is an
   SMC trade from entry to exit (§5).
4. **Categories are independent.** No category gates another. Agreement between categories counts only when
   their information is independent.
5. **Location, then trigger, then entry.** A trade enters at the level or on the event its category
   names, never as a market order because a score crossed a line.
6. **Every trade carries its thesis.** The conditions that justified the trade are re-checked on
   every closed bar, and the trade manager acts when they break. This is v2's answer to trades that
   reverse mid-trade.
7. **Stop at invalidation, target before opposition.** The stop sits where the thesis is proven
   wrong. The target sits before the next opposing level. The lot follows the stop at the user's risk (rule 2).
8. **No scores. Only real probabilities.** v2 contains no scores, points, clamps or hand-set
   weights.
   - The only number on a setup is its probability: how often that category and variant has won
     under the same conditions, measured on data not used to build it.
   - Every probability is shown with its sample size and range.
   - Below the minimum sample it reads **unknown**, never a guess, and the setup cannot trade live.
   - A condition that changes the odds (context, another category agreeing) enters only as its
     measured effect on that frequency.
   - Nothing admits or blocks a trade by adding or removing points.
9. **One market model, one truth.** Swings, structure, liquidity, zones, volume and trend are
   computed once, on closed mid-price bars, and shared by every category.
10. **Every constant has a reason on record.** No flag without code, no threshold without evidence,
   no silent gate.

---

## 5. The categories as v2 trades them

**Every v1 category stays, and each one becomes a separate, complete strategy.** A category proposes
its own setups with its own trade configuration. Its members become the parts of that strategy
(context, location, trigger, confirmation) instead of votes. Categories share the market model
services (§6), so a swing or a zone is computed once, but no category gates or scores another.

### TREND
- **v1 members:** trend indicator, trend cascade M5–H4, H1 trend, price vs EMA200.
- **Trades:** pullbacks and continuations inside an established trend.
- **Applies when:** the higher-timeframe trend is defined by structure (HH/HL or LH/LL) and agrees
  with the cascade, and the last leg is not over-extended (cap in ATR).
- **Location:** value inside the trend: the prior breakout level, the EMA band, or a 38.2–61.8%
  retrace of the last impulse.
- **Trigger:** a lower-timeframe break of structure back in the trend direction.
- **Entry:** a stop order beyond the trigger bar.
- **Stop:** beyond the pullback swing.
- **Targets:** the prior swing extreme, then a measured move, trailing by structure.
- **Thesis breaks when:** the higher-timeframe structure breaks.
- **What v1 did:** used the trend as a gate on 24 rules of other categories, and never traded a
  pullback.

### MOMENTUM
- **v1 members:** MACD momentum, TTM squeeze momentum, RVAM direction, VWAP side, stochastic cross,
  Bollinger band walk.
- **Trades:** momentum release and continuation.
- **Applies when:** a squeeze release or MACD histogram zero-cross closes with range expansion, price
  is on the momentum side of VWAP, and the Bollinger band walk confirms continuation. Compression
  alone is not a setup: a quiet 4h is followed by a quieter 4h (candidate #1).
- **Entry:** a stop order beyond the release bar, or a limit on the first pullback to VWAP or the band
  mid.
- **Stop:** beyond the origin of the release (the squeeze range).
- **Targets:** a measured expansion (a multiple of the squeeze range), then the next HTF level,
  trailing while the band walk holds.
- **Thesis breaks when:** price closes back inside the squeeze range, or VWAP is lost.
- **What v1 did:** signs voting on every bar, trend-gated.

### MEAN_REVERSION
- **v1 members:** OU dislocation, RSI extreme, stochastic extreme.
- **Trades:** a stretched price returning to fair value.
- **Applies when:** the market is in a balance or range regime, price is stretched k σ from fair
  value (VWAP, EMA or fitted mean), and exhaustion shows (RSI or stochastic back from an extreme,
  divergence, stall).
- **Entry:** after the exhaustion trigger closes.
- **Stop:** beyond the stretch extreme.
- **Target:** fair value, with a partial exit halfway, and a time stop.
- **Thesis breaks when:** a new extreme closes beyond the stop side, the regime turns to trend, or the
  time stop is reached.
- **What v1 did:** wrapped it in the trend filter so it could never fire, then added an OU gate that
  never opens.

### STRUCTURE
- **v1 members:** supply/demand, support/resistance, Fibonacci confluence.
- **Trades:** the reaction at fresh zones.
- **Applies when:** the zone is fresh (0–1 prior touches), its departure was strong, and S/D
  confluence with S/R or Fibonacci is counted once per zone.
- **Location:** price inside the zone range, between its proximal and distal edges.
- **Trigger:** a closed rejection candle, or a lower-timeframe break of structure away from the zone.
- **Entry:** one of two variants: a limit at the proximal edge (first touch), or a stop order beyond
  the trigger bar (confirmation).
- **Stop:** beyond the distal edge, plus a spread buffer.
- **Targets:** before the opposing zone, then the opposing zone itself.
- **Thesis breaks when:** price closes beyond the distal edge, or an opposite lower-timeframe break of
  structure happens before target 1. Once used, the zone is marked mitigated.
- **What v1 did:** a level without a range, a market entry anywhere, an ATR stop, and the category
  excluded from decisions.

### SMC
- **v1 members:** SMC overall, market structure, liquidity sweep, premium/discount, ICT FVG type,
  FVG/IFVG.
- **Trades:** the liquidity sequence.
- **Applies when:** a named liquidity pool is swept (prior day, week or session high/low, or equal
  highs/lows). Within N bars, a displacement breaks structure (CHoCH/BOS) and leaves an FVG or order
  block. Premium/discount places the entry on the right side of the dealing range.
- **Location:** the FVG or order block left by the displacement.
- **Trigger:** price returns into it, optionally with a lower-timeframe rejection.
- **Entry:** a limit inside the FVG or order block.
- **Stop:** beyond the sweep extreme.
- **Targets:** first internal structure, then the opposing liquidity pool.
- **Thesis breaks when:** price closes back beyond the sweep extreme or through the FVG or order
  block. The retrace also has a time limit.
- **What v1 did:** the pieces voted at one moment, trend-gated. Never a sequence, and excluded from
  decisions.

### ORDER_FLOW
- **v1 members:** volume, volume profile, liquidity sweeps bias, order flow.
- **Trades:** the auction, meaning how volume accepts or rejects price.
- **Variants:**
  - (a) failed auction: price goes outside value, comes back inside and is accepted; target the
    opposite value edge;
  - (b) acceptance outside value: continuation to the next high-volume node;
  - (c) absorption: heavy volume with opposing delta at a swept level or value edge; reversal.
- **Built from:** tick volume profiles on mid prices (POC, VAH, VAL, nodes), delta from up/down ticks,
  and volume normalised by time of day.
- **Stop:** beyond the excursion extreme, or back through the value edge.
- **Targets:** POC, the opposite value edge, the next node.
- **Thesis:** acceptance or rejection is re-checked on every bar.
- **What v1 did:** position vs POC on every bar, plus one trend-gated vote.

### WAVE
- **v1 members:** chart patterns, wave lattice, Elliott wave, Wyckoff, candlestick.
- **Trades:** the next leg after a recognised price structure completes.
- **Variants:**
  - (a) Elliott: the end of a corrective wave (2, 4 or C) within strict impulse rules; enter the next
    impulse;
  - (b) Wyckoff: a spring or upthrust, with a lower-volume test inside a defined range;
  - (c) chart pattern: a completed pattern breaking its boundary.
- **Trigger:** a candlestick rejection, or a lower-timeframe break of structure, at the completion
  point.
- **Entry:** a stop order beyond the trigger bar.
- **Stop:** beyond the structure's invalidation: wave 1's origin for a wave 2, the spring low, or the
  pattern's opposite side.
- **Targets:** projected by the structure (Fibonacci extension of wave 1, range height, pattern
  height).
- **Thesis breaks when:** price trades through the invalidation level.
- **What v1 did:** Wyckoff copied the trend label and wave C fired on any three legs (both fixed on
  2026-09-15), then everything was trend-gated.

### CROSS_ASSET (built last)
- **v1 members:** GNN direction, GNN recommendation.
- **Trades:** divergence between linked instruments where one leads: USD pairs vs the dollar basket,
  crosses vs their legs, gold vs the dollar.
- **Built last.** The GNN becomes one input of this strategy, not the whole category.
- **Evidence to beat:** v1's relative-value fades lost −0.70 to −1.09R.

### Retired from v1
- the additive side chooser (`calculate_real_probability`);
- category scores and the auction;
- the `_trend_confirmed` wrappers and the continuation inversions;
- context points and the penalty band;
- orphan flags.

---

## 6. v2 architecture

```
ticks ─► DATA ─► MARKET MODEL SERVICES ─► TRIGGER & CONTEXT LIBRARIES
                                                   │
                                        CATEGORY STRATEGIES (8) ─► Setup
                                                                      │
                               PROBABILITY ─► SELECTION ─► RISK & SIZING
                                                                      │
                                        EXECUTION (limit / stop / market)
                                                                      │
                                        TRADE MANAGER (thesis per closed bar)
                                                                      │
                                        JOURNAL & MONITORING ◄────────┘
```

| layer | responsibility | replaces in v1 |
|---|---|---|
| **Data** | ticks → mid/bid/ask bars per timeframe; closed bars only; broker clock; spread series; same interface live and in replay | mixed live/replay bars, bid-only levels |
| **Market model services** | structure and swings, liquidity map, zones (S/D + order block + FVG + S/R merged, with range, invalidation, freshness and origin), volume profile and delta, fair value, volatility/regime, session; computed once, versioned, shared | each indicator computing its own levels |
| **Trigger & context libraries** | named events with bar times; context states | readings true on every bar |
| **Category strategies** | TREND, MOMENTUM, MEAN_REVERSION, STRUCTURE, SMC, ORDER_FLOW, WAVE, CROSS_ASSET, each a separate strategy that emits complete `Setup` objects | category auction and additive side chooser |
| **Probability** | measured win frequency per category and variant, with sample size and range; conditions enter as measured effects; "unknown" below the minimum sample | every score: `calculate_real_probability`, category scores, context points, penalty band |
| **Selection** | chooses among concurrent setups; exposure and correlation limits | highest score wins |
| **Risk & sizing** | risk = the caller's `risk_per_trade` × `fixed_trade_size_usd`, capped by `MAX_RISK_PER_TRADE`; lot = risk ÷ the category's stop distance; unaffordable setups flagged, never re-stopped | reuse the `core/market_stop.py` lot sizing |
| **Execution** | limit, stop or market order as the setup says; pending-order lifecycle; bid/ask-correct fills | market orders only |
| **Trade manager** | re-checks the thesis each closed bar; partials, structural trail, time and invalidation exits | nothing |
| **Journal & monitoring** | every setup (taken, skipped, expired) with thesis, fills, path and outcome; per-category live view | scattered payload fields |
| **Config ledger** | every constant with owner, reason, evidence and date | config with orphans and tiny-sample thresholds |

### The Setup contract

```
Setup
  id, category, variant, symbol, timeframe, side
  created_at        closed-bar time
  valid_until
  context           htf_trend, regime, session, ...
  location          type, zone {proximal, distal} or level, source ids
  trigger           type, bar_time, details
  entry             order_type LIMIT | STOP | MARKET, price
  stop              price, reason ("beyond sweep extreme")
  targets           [ {price, reason, share} ]
  thesis            [ {condition, checked_on, action_when_broken} ]
  probability       value, sample_size, range, conditions [ {name, measured_effect, evidence_id} ]
                    ("unknown" below the minimum sample)
  risk              usd (from the caller's risk_per_trade), lot, affordable
  lifecycle         PROPOSED → PENDING → FILLED → MANAGED → CLOSED | EXPIRED | CANCELLED
```

### What asset analysis returns in v2
`analyze_institutional_signal(symbol, order_type, fixed_trade_size_usd, risk_per_trade, ...)` keeps
its signature and returns:
- **`setups`:** every setup proposed by every category on this closed bar. Each carries its full trade
  configuration and its lot at the caller's risk.
- **`not_tradeable`:** setups that were proposed but are unaffordable at that risk, or expired, each
  with its reason.
- **`probabilities`:** base and adjusted, per setup.
- **`selected`:** the tradeable setup (known probability, affordable) with the **highest real
  probability**, or none. The system still picks the highest-probability side, as the operator set
  it; in v2 that probability is measured.
- **`market_model`:** the shared structure, liquidity, zones, volume and regime that the categories
  read.

Every parameter the function accepts is either used or removed. Today `stop_loss_pips` and
`take_profit_pips` are not used.

### Engineering rules
1. **Same code live and in replay:** pure functions over a data snapshot.
2. **Decisions read closed bars only.** The forming bar never reaches a decision.
3. **Levels on mid, fills on bid/ask.**
4. **Every service and category has a written spec and golden chart cases:** known historical
   examples it must detect exactly.
5. **No silent gate.** Every block, adjustment and skip is written on the setup record with its
   reason.
6. **No orphan flags.** A test fails when a config flag is not used by code.
7. **Each category ships behind its own switch.** It starts in shadow and trades only after
   acceptance.
8. **v1 stays untouched.** v2 lives in its own package (proposed: `engine_v2/`). It reuses only
   verified infrastructure: the MT5 bridge and EA, `core/broker_facts.py`, MongoDB storage, the
   tick/bar data tooling and lot sizing.
9. **The 2026-09-15 defect classes are a review checklist** for every v2 service: call-history
   state, forming bar, pip floors, direction-parse inversion, always-firing readings.

---

## 7. How v2 reaches the goal

**Success rate comes from independent categories.** Truly independent evidence adds up; copies of one
rule add nothing. The table shows how often the majority is right:

| each independent source right | 5 sources | 9 sources | 15 sources |
|---|---|---|---|
| 55% | 59.3% | 62.1% | **65.4%** |
| 60% | **68.3%** | 73.3% | 78.7% |

v1's 24 trend-gated rules are one source counted 24 times. v2 counts a category's context, location,
trigger and confirmation separately, and counts across categories only where the information is
independent.

**Expectancy comes from keeping winners.** At 65% won, with wins as large as losses, a trade is
worth +0.30R before costs. v1 gives that back: 72.7% of its trades reach +0.25R, and 70.6% still
end at the stop. The v2 trade manager (philosophy rule 6) and structural stops (rule 7) exist for
exactly this.

**Acceptance is on v2, never on v1:**
1. Each service and category passes its golden cases.
2. The shadow journal shows every setup executed as specified.
3. Each category wins ≥ 55% at its own geometry on holdout ticks.
4. The whole system reaches ≥ 65% won and ≥ +0.2R net per trade on demo.

---

## 8. What is kept from v1

- **Infrastructure:**
  - the MT5 EA bridge (fixed 2026-09-15) and `core/broker_facts.py`;
  - MongoDB trade storage;
  - lot sizing from `core/market_stop.py`;
  - tick and bar tooling (`C:/Users/msi/tradify_study/ticks_m1`, the Dukascopy downloader);
  - tick-accurate outcome tooling.
- **Knowledge:**
  - the defect classes (§6 rule 9);
  - the list of what already failed (`diagnosis.md`), used as the evidence each v2 category must
    beat, not as a ban.

---

## 9. Decisions for the operator

1. **v2 location:** `engine_v2/` beside `core/` (recommended; v1 stays intact as the reference).
2. **Category build order.** Proposed:
   1. SMC and STRUCTURE (they share the structure, liquidity and zone services);
   2. TREND;
   3. ORDER_FLOW;
   4. MOMENTUM;
   5. WAVE;
   6. MEAN_REVERSION;
   7. CROSS_ASSET.
3. **v1 on demo during the build:** keep it running as the reference (recommended), or stop it.
4. **Category definitions:** review each category spec in `roadmap.md` Phase 1 before it is coded. The
   parameters marked N and k above are set in the specs.

---

## 10. What we do, in order

Deliverables, estimates and status for each step are in `roadmap.md`.

| # | step | what it produces | done when |
|---|---|---|---|
| 0 | **Freeze v1** | git tag; v1 keeps running on demo; map of v1's trade path (§2) and its rules and configs (§3) | tag exists, map written |
| 1 | **Specs** | philosophy (§4) as binding rules; Setup contract; one spec per service; one spec per category with exact definitions; golden chart cases | operator approves each category spec |
| 2 | **Data layer** | mid/bid/ask closed bars from ticks, one interface live and in replay; Dukascopy 2022–2025 finished | a live bar equals its replay bar |
| 3 | **Market model services** | structure and swings → liquidity map → zones → volume profile and delta → fair value → volatility, regime, session | every golden case detected as specified |
| 4 | **Trigger and context libraries** | events with bar times; HTF trend by structure, regime, session | golden cases pass; no event is true on every bar |
| 5 | **Category engines** | SMC and STRUCTURE, then TREND, ORDER_FLOW, MOMENTUM, WAVE, MEAN_REVERSION, CROSS_ASSET; each proposes complete setups at the user's risk | golden cases pass; the replay journal shows each setup's anatomy |
| 6 | **Execution** | limit, stop and market orders; pending-order lifecycle; bid/ask fills; EA support | demo orders are placed, filled and cancelled as the setups specify |
| 7 | **Trade manager** | thesis re-check on each closed bar; partials, structural trail, time and invalidation exits | every exit in the journal carries its thesis reason |
| 8 | **Probability and selection** | measured win frequency per category and variant; measured condition effects; the highest real probability among tradeable setups | calibration within ±3 points per decile |
| 9 | **Risk, journal, config ledger** | lot from the user's risk; setup journal in MongoDB; per-category view; ledger plus orphan-flag test | no constant without a ledger entry |
| 10 | **Shadow run** | v2 beside v1 on live data, no orders, 2–4 weeks | setups journaled for every category |
| 11 | **Demo and promotion** | categories switched on one at a time | ≥ 65% won and ≥ +0.2R net per trade over ≥ 50 demo trades |

**Estimate:** 25–30 working sessions, plus the shadow period.

**First session:** step 0 and the start of step 1:
- freeze v1;
- write the philosophy and the Setup contract;
- write the SMC and STRUCTURE specs with their golden cases, for the operator to review.
