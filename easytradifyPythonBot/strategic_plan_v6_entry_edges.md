# Strategic plan v6 — build the entry edge, per category

Status: OPENED 2026-09-17. Supersedes the entry-rule work of v5 (the rule table
stays; what it is *made of* is what this plan rebuilds).

Operator's target, unchanged: **≥65% won AND ≥+0.20R net per trade, per category,
on unseen data.** M1 decisions, no session/news rules, no crypto, $200 size, $4
risk, no market stop, demo until a rule passes.

---

## 1. The number that defines the problem

A trade with a stop and a target is a race between two barriers. With no
predictive skill at all, the probability of touching the target first is
`stop / (stop + target)` — pure geometry, no forecasting. Any win rate on that
line is free and pays exactly zero before costs, and minus the cost after.
(Already in memory as *accuracy is a dial, not an edge*.)

So the only thing that matters is: **how far above that line can we predict?**
That is "edge in points". The target sets how many points we need.

From the broker's own facts (`engine_v2/data/symbols.json`), EURUSD, $4 risk:

| stop | lot | commission | cost in R | target for 65% & +0.2R | free win% | **edge needed** |
|---|---|---|---|---|---|---|
| 1 pip (today) | 0.40 | $2.81 | **0.703R** | 1:1.93 | 34.2% | **30.8 points** |
| 2 pips | 0.20 | $1.41 | 0.352R | 1:1.39 | 41.9% | 23.1 points |
| 5 pips | 0.08 | $0.56 | 0.141R | 1:1.06 | 48.5% | 16.5 points |
| 10 pips | 0.04 | $0.28 | 0.070R | 1:0.95 | 51.2% | 13.8 points |
| **40 pips** | **0.01** | **$0.07** | **0.018R** | 1:0.87 | 53.4% | **11.6 points** |
| 100 pips | 0.01 (min) | $0.07 | 0.007R | 1:0.86 | 53.9% | 11.1 points |

Two things fall out of this table, and they are the whole plan.

**(a) The 1-pip account stop is the single most expensive thing in the system.**
It forces a 0.40 lot to hold $4, and 0.40 lot costs $2.81 in commission — 70% of
the risk unit, paid on every trade before the market moves. It demands
**31 points** of forecasting skill. Nothing we could ever build pays that. A
40-pip stop at the minimum lot costs **0.018R** — the same edge is worth 40×
more. This is not an optimisation; it is the difference between a solvable and
an unsolvable problem.

**(b) Even with the cost gone, your two requirements together demand ~11.6
points.** That floor does not come from costs — it comes from asking for a high
win rate *and* high expectancy at the same time. Requiring 65% forces the target
below the stop (1:0.87), which puts the free line at 53.4%, so the 65% has to be
bought with 11.6 points of real skill.

Drop the 65% and keep only +0.2R, at the same 0.018R cost:

| R:R | win rate needed | free win rate | edge needed |
|---|---|---|---|
| 1:1.2 | 55.5% | 45.5% | 10.0 points |
| 1:2 | 40.7% | 33.3% | 7.3 points |
| 1:3 | 30.5% | 25.0% | 5.5 points |
| 1:5 | 20.3% | 16.7% | 3.7 points |
| 1:10 | 11.1% | 9.1% | **2.0 points** |

**The 65% requirement costs about 5× more edge than the money target does.** A
high win rate is a feeling about the equity curve, not a source of profit. The
same skill that makes +0.2R impossible at 65% makes it comfortable at 1:5.

## 2. What we actually have

Measured, on true bid/ask M1 labels, over 100k+ decisions, across every feature
family in the engine:

- every entry is 49–51% at mid-price with zero cost (*no directional edge before costs*)
- every group's AUC is 0.50–0.51 (*system is one signal in eight costumes*)
- all 13 component readings are the same reading — position vs a mean — copied
  (*components are one reading copied*)
- the final replay: every category wins 29–31% on its own plan, identical
- momentum inside a category: −0.05R, i.e. nothing (measured today, 26,731 decisions)

**Current edge: 0 to 1 point. Required: 11.6 points.** That gap is why no entry
rule has ever separated winners from losers — not because the rules are wrong,
but because nothing they are reading carries direction. Filtering a coin flip
harder produces a smaller, more expensive coin flip. This is the honest reason
"entry blocks winners": it blocks winners and losers at exactly the same rate,
which is what a filter on noise does.

**So: no filter, threshold or rule table can reach the target from the current
inputs. New edges have to be found, not tuned.** That is what this plan does.

---

## 3. The rebuild

### Phase 0 — remove the cost wall (no decision needed; every route requires it)

The 1-pip stop is not a risk choice, it is an artefact: the $200 margin-first lot
is so large that $4 is consumed in one pip. Sizing rule stays exactly as you set
it ($200 size, $4 risk, lot shrinks to hold $4, no market stop) — but the stop
scale becomes the *strategy's* structural stop, which is tens of pips, and the
lot lands at or near the 0.01 minimum. Cost per trade goes 0.703R → ~0.02R.

Gate: cost in R, measured per category on replay, must be ≤ 0.05R.
This alone moves the required edge from 31 points to ~11.

### Phase 1 — find out, per category, whether any edge exists at all

For every category, sweep the axes we have never swept, on the replay data:

- **horizon**: 15m, 1h, 4h, 1 day, 3 days (today: 240 minutes, fixed)
- **stop scale**: 0.5×, 1×, 2×, 4× the M1 ATR, and D1-ATR-based
- **target scale**: 1:0.9 through 1:10
- **side**: the category's own direction, and its opposite (random-side control)

For each cell, the one number that matters: **realised win rate minus the free
barrier win rate**, with cluster-robust errors over (symbol, day), computed
separately in the earlier and later half of history, plus a pre-registered
verdict written before the results are read.

A category passes Phase 1 only if its edge is:
1. positive in **both** halves,
2. ≥ 3 points with the cluster-robust interval excluding zero,
3. present on unseen symbols (the 7 markets held out of every fit so far).

Anything else is recorded and **silenced** — the category keeps scoring and
publishing, it cannot win the auction. That is the real answer to "accept only
successful trades, reject bad ones": the rejection happens one level up, at the
category, where it is measurable, instead of at a per-trade filter, where we have
proved fifteen times that it is not.

### Phase 2 — new inputs for the categories that fail

Every family we have tested is a *position* reading. The families never tested,
in order of prior:

1. **Tick order flow** — signed trade imbalance, not the synthetic depth ladder
   (`broker-depth-is-synthetic-ladder`). We have `ticks_m1_v5` bid/ask data;
   this is a *behaviour* input, the first one.
2. **Longer-horizon trend** — the only anomaly in the literature that replicates
   (time-series momentum, ~55–57% hit, i.e. 5–7 points). Our sizing permits a
   40–100 pip stop at minimum lot, so for the first time this is *reachable*
   (`risk-unit-locks-the-move-scale` flagged it as never tested). Swap becomes
   the cost term and is already in the facts.
3. **Cross-instrument lead–lag** — index/metal/FX at sub-minute offsets. The GNN
   already computes the relationships; they have never been tested as a
   *predictor*, only published as advice.
4. **Spread/liquidity regime transitions** — the one microstructure quantity that
   is genuinely observable here.

Each is tested by the same protocol as Phase 1, pre-registered, both halves,
unseen symbols. A family that fails is written into memory as dead and not
retried.

### Phase 3 — build the entry from what survived, per category

Only then does entry logic get written, and it is written *as* the surviving
edge: the rule table's `block` modes are set by the evidence
(`ai/entry_rule_evidence.py`), every other rule observes. Each surviving category
trades its own setup at its own horizon and geometry, sized by your rule.

### Phase 4 — live on demo, one category at a time

A category goes live only after passing Phase 1/2 on unseen symbols. Plan-v5 pass
line applies. No commits without your approval.

---

## 4. The decision that changes the shape of the work

Phases 0–2 are identical either way, so they start now. But Phase 3 needs to know
which constraint is real:

- **Keep 65% AND +0.2R** → we need ~11.6 points. Nothing published or measured
  reaches it; this is a research bet with a low prior, and I will say so at each
  gate rather than quietly fitting until it appears.
- **+0.2R first, win rate free** → we need 2–7 points depending on R:R. Still
  hard, but inside the range where real effects exist. The equity curve is
  lumpier — 1:5 wins 20% of the time — but it compounds.

My recommendation: **make +0.2R the pass line and let the win rate land where the
geometry puts it**, then raise the win rate later only if an edge is found that
pays for it. Reason: the 65% is costing 5× more edge than it can ever return, and
it is the requirement that has made every previous version fail.

---

## 5. Phase 1 result — the rule search is exhausted (2026-09-17)

`C:/Users/msi/tradify_study/entry_edges_v1/mine_rules.py` swept every one of the
384 fields recorded at decision time (thresholds at 20 quantiles, categorical
equality, direction-relative @signed / @dir versions, singles and pairs):
**~14,000 candidate rules per category**, discovered on the earlier half of
history and confirmed on the later half. 77,828 labelled decisions, true bid/ask
M1 outcomes.

| category | confirm n | base won | rules tried | best rule won | n | gross R | net R |
|---|---|---|---|---|---|---|---|
| SMC | 6,939 | 30.4% | 12,173 | 39.8% | 108 | +0.145 | -0.345 |
| all | 38,919 | 29.2% | 14,382 | 42.7% | 274 | +0.053 | -0.445 |
| CROSS_ASSET | 7,024 | 28.7% | 12,186 | 41.3% | 104 | +0.011 | -0.512 |
| TREND | 18,126 | 29.1% | 13,644 | 44.0% | 218 | -0.015 | -0.431 |
| MOMENTUM | 6,087 | 28.2% | 12,644 | 38.0% | 389 | -0.075 | -0.540 |

**No rule selects successful trades.** The luckiest rule per category sits
between -0.08R and +0.145R gross on 100-400 trades -- the best-of-luck level for
13,000 trials. Every rule loses money net.

Three diagnostics from the search:

1. `symbol == USDJPY` outranked all 384 signals. Which pair you trade carries
   more information than every reading in the engine combined.
2. The win-rate winners are geometry: `cost.target_r < 1.25` -> 41% won at
   -0.085R gross. The win rate rose, the accuracy did not. The dial, caught in
   the act.
3. Entry "blocking winners" is explained: it blocks winners and losers at the
   same rate, which is what a filter on noise does. The rules were never at fault.

**Conclusion: rule search over the current feature space is closed.** No further
threshold, combination or rule-table work on these inputs can reach the target.
Phase 2 (new input classes) is now the only live route.

Ranked by prior, the gap is specific: all 384 readings describe *where price is*
(position vs a mean, band, level, or wave count). None describes *what
participants are doing*. Signed transaction flow is the untested family with the
strongest short-horizon prior, and the tick data for it is already on disk.

## Log

- 2026-09-17: opened. Phase 0 arithmetic computed from broker facts (above).
  Final-config replay (advisory CROSS_ASSET + MOMENTUM, corrected setup mapping)
  running to produce the per-category baseline this plan measures against.
