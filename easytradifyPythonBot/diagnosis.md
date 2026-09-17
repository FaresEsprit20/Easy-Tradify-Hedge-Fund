# Diagnosis — 2026-09-16

What was tested, what it returned, what changed in the code, and what not to
repeat. Every number below is measured on **true bid/ask tick data** unless the
row says "bars", and every claim names the sample size.

---

## 1. The headline

The system's components carry **no directional information** at 1h–72h
horizons on 15 FX majors. This is not a cost problem, an exit problem, or a
tuning problem — it was measured with **every cost removed**.

The day's work therefore split in two:

- **Edge search** — six information channels tested, all empty. Three strategy
  families closed (mean reversion, zones/structure, SMC).
- **Damage repair** — the aggregation layer was found to be actively harmful
  and was fixed. **Holdout expectancy went from −0.199R to −0.099R.**

Half the bleeding was removed. The target (+0.2R, 65% win) was **not** reached,
and the remaining gap is not closable by tuning.

---

## 2. The decisive test

`ai/pure_direction.py` — barriers on **mid price**, symmetric at 1.5 × H1 ATR,
**no spread, no commission**. 7,999 entries, four horizons, three actions.

| action | 1h | 4h | 24h | 72h |
|---|---|---|---|---|
| follow | 49.4% | 50.7% | 50.0% | 50.0% |
| fade | 50.7% | 49.4% | 50.1% | 50.0% |
| **always_buy (control)** | 50.3% | 49.9% | 49.9% | 49.7% |

48 cells, largest \|z\| = **2.20**, where 48 draws from the null typically
produce a max near 2.6–2.8. **Nothing survives correction.**

The `always_buy` control landing on 50.0% with \|z\| ≤ 0.53 is what makes every
other number in this document trustworthy. **Any future study must carry a
control like this.**

This single test would have closed the entire search on its own. It was built
late. That was the day's biggest process failure.

---

## 3. Every channel tested

| channel | sample | result |
|---|---|---|
| price position (13 readings: zones, S/R, SMC, EMA, POC) | holdout study | 44.2–45.4% vs a 44.6% baseline — one reading copied 13 ways |
| price behaviour (stretch, stall, velocity) | 7,999 ticks | 49.4–50.7%, max \|z\| 2.20 of 48 cells |
| participation (tick volume vs same-hour mean) | 608k bars / 54k ticks | clean monotone ladder on **bars**, **gone on ticks** |
| cross-asset cointegration | 105 pairs, 11y H1 | half-lives 48–660 days, or algebraic identities |
| order-flow imbalance (`up_ticks`/`down_ticks`) | 31,388 | IC 0.015 — significant at z −2.7, economically nothing |
| OU mean reversion (fitted process) | 4y H1, 15 symbols | forward β 0.06 vs theory 0.50 |

### Coverage is the tell
`supply_demand_side` fires on **100%** of bars, `ema200_side` 99.3%,
`poc_side` 98.7%. A reading available on every bar is not a signal about that
bar — it is a restatement of where price is. All thirteen answer *where price
is*; none answered *what price is doing*, which is why
`core/behaviour_readings.py` was built.

---

## 4. Strategy families closed

### 4.1 Mean reversion — closed

The original implementation could **not fire at all**: every `MEAN_REVERSION`
member was wrapped in `_trend_confirmed`, which returns `None` when a reading
disagrees with the trend cascade. An oversold RSI in a downtrend — the only
call the group exists to make — was deleted before it could vote. The group's
own self-check asserted this as correct.

Rebuilt properly as `core/ou_mean_reversion.py`: fitted half-life, thresholds
in equilibrium sigma, partial-reversion exit, time stop at three half-lives,
z-scaled sizing, pre-trade cost gate.

Then measured:

- **forward β median 0.06** against the theoretical **0.50** — dislocations
  recover about one eighth of what the model assumes
- **`price_share` 45–51%** — roughly half of all apparent reversion is the
  **baseline catching up to price**, not price returning. Only the latter pays.
- **XAUUSD β = −0.184 at t = −4.90** — gold dislocations *extend*. Never fade gold.
- **Walk-forward, prior-only fits, on bid bars that flatter fades by ~0.14R**:
  gate passed **53 times in 40,323** evaluations (0.13%), those trades returned
  **−0.1984R at 49.1% won**.

The correct build was produced and it loses. Do not reopen.

### 4.2 Zones / structure — closed, with a useful forensic

11,736 first-touch zone trades on ticks, 43.7% won, gross −0.10 to −0.15R.

**Why they fail** (this is the valuable part):

| of the LOSING trades | share |
|---|---|
| reached +0.10R first | **86.1%** |
| reached +0.25R first | 63.1% |
| **never moved our way** | **13.9%** |

Median favourable excursion of a loser: **+0.352R**.

So only 14% are detection failures. **The zones are real levels — price
genuinely reacts at them.** But the reaction is ~0.35R of symmetric noise with
no follow-through. Zone quality changes whether price *reacts* (12.0% vs 15.7%
no-reaction for strong vs weak departure) but **not whether it continues**.

**Zone grading is inverted.** Grade-vs-expectancy correlation **−0.286**; the
4-of-4 "perfect" setup is the worst cell (39.4%, −0.327R). Most of that is
arithmetic, not markets: a tight "A-grade" zone gives a tight stop, and
commission is charged per unit of risk, so the cleanest setup pays **0.156R**
against **0.081R** for the sloppiest.

451 attribute combinations searched with holdout + FDR: best cell **z = +0.73
(p = 0.47)**. The cells that *do* clear FDR are significantly **negative**.

**The trap to avoid:** "86% of losers reacted first" suggests taking profit
earlier. It does not work — measured at a 0.25R target: 79.8% win rate,
**−0.041R net**. Cutting targets converts the distribution; it does not create
edge (see §5).

### 4.3 SMC — closed, and independently falsified

Published, rigorous work reaches the same conclusion with larger samples:

- **StatOasis**, 648 backtests, SPY/QQQ/DIA/IWM: Order Blocks t = **+1.22**,
  FVG t = **−0.08**, 31 of 32 scores below significance, **0 of 648 beat
  buy-and-hold**, *"Survivors: none."*
- **arXiv 2605.04004**, *"Structural Limits of OHLCV-Based Intraday Signals"*,
  MNQ futures: liquidity grab **faded** −2.20 pts (T −14.12), **followed**
  −1.80 pts (T −13.24).

Our tick numbers land on top of theirs. The last untested claim — that sweeps
of **daily/weekly** levels are more reliable — was run on **3,579 sweeps**, mid
price, zero cost: 18 cells, max \|z\| **1.36**, control in the same range.

---

## 5. Accuracy is a dial, not an edge

`ai/mean_reversion_lab.py::frontier()` — same 6,406 trades, every target priced
off one walk:

| target | won | net R | | target | won | net R |
|---|---|---|---|---|---|---|
| 0.15R | **86.8%** | −0.040 | | 1.0R | 49.2% | −0.053 |
| 0.25R | 79.8% | −0.041 | | 2.0R | 36.1% | −0.049 |
| 0.33R | **74.6%** | −0.046 | | 4.0R | 32.3% | −0.029 |

**75% accuracy is free** — set the target to 0.33R — and it is worth −0.046R.
Fifty-four points of win rate move expectancy by two hundredths of an R, and
every setting loses.

**Never quote a win rate without the target that produced it.** No exit rule,
trailing stop or R:R change can rescue an entry with no directional edge — that
whole family of work is measured flat.

---

## 6. The aggregation was actively harmful

Measured on **61,950 engine decisions** against tick outcomes.

### 6.1 Confluence is inverted

| groups agreeing | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| right | 42.7% | 41.3% | 41.5% | 41.4% | 40.4% | **37.7%** |
| net R | **−0.130** | −0.195 | −0.195 | −0.201 | −0.221 | **−0.278** |

The system's core premise — stack agreement, raise probability — is backwards.
Four independent confirmations: the table above; holdout deciles (35.1 → 48.6%
then **D10 collapses to 42.9%**); top 5% −0.234R vs top 50% −0.129R; and the
project's own earlier finding (4-of-5 agreement 36.8%, 1-of-5 51.7%).

### 6.2 The published probability was noise
`corr(sg_final, was right) = +0.0113`.

### 6.3 Root cause
`OPPOSITION_WEIGHT = 1.0` amplified exactly the wrong end. With every group
agreeing, nothing sits below 50, opposition is 0, and the published probability
is the winner's **full** score — maximum confidence on the bars that measure
worst. It was fitted on 105 stored trades and inverted on 61,950.

---

## 6.4 ROOT CAUSE — the system is one signal in eight costumes

Audited all eight groups on **110,603 decisions** with tick outcomes
(`/tmp/group_audit.py` pattern).

**No group's score predicts.** AUC, full / holdout:

| group | n scored | AUC | holdout |
|---|---|---|---|
| TREND | 110,603 | 0.4906 | 0.4868 |
| MOMENTUM | 37,278 | 0.4937 | 0.4818 |
| MEAN_REVERSION | 22,501 | 0.4935 | 0.4900 |
| STRUCTURE | 2,329 | 0.5031 | 0.5299 |
| SMC | 59,860 | 0.5063 | 0.5077 |
| ORDER_FLOW | 6,543 | 0.4790 | 0.4794 |
| WAVE | 14,264 | 0.5017 | 0.4947 |
| CROSS_ASSET | 56,914 | 0.4966 | 0.5059 |

When a group wins the auction it is right 40.7–44.6% against a **41.8%**
baseline. ORDER_FLOW is nominally best (44.6%, holdout 46.4%, net −0.137,
n=1,663) but its AUC is 0.479 — anti-predictive — so it is not ranking, merely
winning in slightly better conditions.

**Why they are all the same number:**

- **25 of 33 members are `trend-confirmed`** — they return `None` unless they
  agree with the trend cascade
- **74.8%** of traded sides agree with the cascade (the disagreeing cell was
  too small to report)
- **61.0%** of decisions have *every* scored group pointing the same way

The groups are not eight opinions being aggregated. They are **one signal**,
filtered so only readings agreeing with it may speak, then counted as
independent confirmations. The cascade itself is 41.4% right vs a 41.8%
baseline.

This mechanically explains every other result: thirteen "independent" readings
all landing on 44.6%; confluence being **inverted** (unanimity means the cascade
is loud, not that evidence accumulated); and final-probability AUC 0.50.

### Two architecture fixes tested and REFUTED

**1. Un-gate the groups from the cascade.** Hypothesis: `_trend_confirmed` is
hiding information. Rescored 68,017 decisions with every wrapper stripped
(`core.calibrated_model.raw_reader`), so each group speaks on all decisions
instead of a filtered subset:

| group | gated AUC | ungated AUC | holdout ungated |
|---|---|---|---|
| TREND | 0.4954 | 0.4980 | 0.5065 |
| MOMENTUM | 0.4928 | 0.4983 | 0.4929 |
| MEAN_REVERSION | — | 0.4998 | 0.5074 |
| STRUCTURE | 0.4913 | 0.4936 | 0.4917 |
| SMC | 0.5056 | 0.4986 | 0.4996 |
| ORDER_FLOW | 0.4707 | 0.4977 | 0.4926 |
| WAVE | 0.4946 | 0.4988 | 0.5035 |
| CROSS_ASSET | 0.4957 | 0.4949 | 0.5019 |

Nothing moves off 0.50. **The gate was not hiding information; the members do
not have any.**

**2. Feed all groups into every category (joint/interaction effects).**
Individually-useless features can be jointly informative, so this needed a real
test — all eight scores, every pairwise interaction, and a 200-tree nonlinear
model:

| model | train AUC | holdout AUC |
|---|---|---|
| best single group | — | 0.5065 |
| logistic, 8 group scores | 0.5274 | **0.4956** |
| logistic + all pair interactions | 0.5318 | **0.4964** |
| gradient boosting, 200 trees | 0.6059 | **0.5068** |
| **same model, SHUFFLED labels** | **0.6005** | **0.4972** |

The boosted model reaches 0.6059 on real labels and **0.6005 on scrambled
ones** — it learns as much from noise as from the market. Holdout real vs
shuffled differ by 0.0096. **The aggregation architecture cannot be fixed by
restructuring, because the inputs are empty.** Without the shuffled control,
"train AUC 0.61" would have read as a breakthrough.

### CROSS_ASSET should not be a group
Both members are the GNN (`GNN direction (ranging regimes)`, `GNN
recommendation`), sitting at the bare `MIN_GROUP_MEMBERS = 2`. One only speaks
in ranging regimes, so in a trend the group drops to one member and cannot
score. AUC 0.4966. Giving a single model a group label lets it win the entire
auction alone — it belongs as a member of another group, or not in the auction.

---

## 7. What changed in the code

| file | change |
|---|---|
| `core/strategy_groups.py` | `OPPOSITION_WEIGHT` 1.0 → **0.0**; `MEASURED_EMPTY_GROUPS = ("STRUCTURE","SMC")`; `DEAD_SESSION_PENALTY`; `contested` / `other_side_best` / `groups_agreeing` published; `_ou_side` + `_ou_gated` replace the behaviour gate; dead `_reversion` and `_stretch_side` removed |
| `core/ou_mean_reversion.py` | **new** — OU fit, half-life, σ_eq, forward-β guard, cost gate, `live()` |
| `core/behaviour_readings.py` | **new** — the behaviour axis (stretch, stall, velocity, volatility transition) |
| `core/asset_analysis_config.py` | `MAX_PROBABILITY_FOR_ENTRY = 83.0` |
| `core/entry_engine.py` | entry gate is a **band**, not a floor |
| `core/asset_analysis.py` | `_broker_hour()`, behaviour + OU wired into the payload, `strategy` on `final_decision`, `_picked_strategy()` |
| `core/calibrated_model.py` | `raw_reader` unwraps `_ou_gated` |
| `ai/` labs (new) | `mean_reversion_lab`, `strategy_selector_lab`, `participation_lab`, `participation_ticks`, `pure_direction` |

`final_decision.strategy` now reports which strategy won, who agreed, who
opposed, the runner-up, and for a reversion pick the z, half-life, forward β,
price share, expected gain, cost and net edge that admitted it.

### Verified improvement

| | before | after |
|---|---|---|
| AUC(probability, right) | 0.5096 | **0.5395** |
| corr(probability, net R) | +0.0118 | **+0.0498** |
| holdout net (D6–D9 band) | −0.192R | **−0.099R** |

Full test suite: **green**.

---

## 8. Instrument universe

3,964 instruments scanned by spread as a share of H1 ATR (the selector that
correlated **−0.673** with profitability):

| category | median spread/ATR |
|---|---|
| **FX** | **4.82%** |
| TSE | 5.10% |
| NYSE | 10.53% |
| NAS | 12.22% |
| CRYPTO | **120.44%** |

**You are already in the cheapest market this broker offers.** Switching to
equities or crypto makes the arithmetic worse. That option is closed.

---

## 9. Method — the protocol that emerged

These exist because each was violated at least once today.

1. **Ticks decide, bars only suggest.** Bid-only bars **manufacture mean
   reversion** — the bid dips and recovers on every spread flicker, so a fade
   always looks like it worked. Measured gap to ticks: **0.14R**, ~3× the
   calibrated `MODEL_OPTIMISM_R = 0.05`, and directional. This artifact has
   produced **four** false edges in this project.
2. **Every test carries a control.** `always_buy` at 50.0% is the only reason
   the null results are believable.
3. **Separate gross from net before any claim.** "Tight zones are worse" was
   65% commission arithmetic.
4. **Pre-register the kill criterion.** The vicious circle is powered by moving
   the line after seeing the data.
5. **Arithmetic before features.** If spread is 5% of an hourly range, no
   feature can save it — decided before any signal exists.
6. **Non-overlapping windows for forward tests.** Overlapping windows inflate
   t by roughly √horizon.
7. **A detrended series is stationary by construction.** Fitting an AR(1) to it
   proves nothing — a random walk passes. Test the forward **price** move.

---

## 10. Mistakes made today

Recorded so they can be weighted against the conclusions.

- Ran hours of feature studies before building the mid-price test that closed
  the question in minutes.
- **Three shipped bugs:** `ranked[1]` on a one-element list (crashed the whole
  analysis); `LIVE_BARS = 1400` gave only ~12 non-overlapping windows so the OU
  gate refused for *want of data*, not want of reversion; a barrier-settlement
  bug scored every timeout as a full win and printed a fake **+0.77R**.
- Built a random-walk guard (`price_share`) that **failed on a random walk** —
  attribution can't distinguish luck from a restoring force. Replaced with the
  forward-β test.
- Asked for approval on the probability ceiling **before** running the test
  that weakened its evidence (see §11).
- Let a stale memory ("supply/demand in New York 61–65%") send me chasing a
  bar-label artifact. Now retracted — NY is the **worst** session (37.7%,
  z −8.46), confirmed on two independent constructs.

---

## 11. Open risk

**`MAX_PROBABILITY_FOR_ENTRY = 83.0` is the weakest shipped change.** On the
*new* probability it is better on both halves (train −0.166 vs −0.193, holdout
−0.099 vs −0.192). On the *old* raw `sg_final` over 110,603 decisions it helps
on holdout (+0.0095R) but **hurts on train**. The system now uses the new
probability, so the supporting evidence applies — but this belongs on the live
re-measurement list, not treated as settled. Set it to 100 to revert.

---

## 12. Next steps

**Immediate (highest value, not yet done):**

1. **Audit TREND, MOMENTUM, WAVE and CROSS_ASSET on ticks** the way SMC was
   audited. None has had it. The project's earlier research rated
   **CROSS_ASSET highest at 64%** — it is the last place in the existing system
   where something could still be hiding.
2. **Re-measure the probability ceiling on live trades** (§11).

**Also settled (do not retry):** un-gating the groups from the cascade, and
combining all groups into every category — both tested with holdout and a
shuffled-label control, both empty (§6.4).

**Volume profile**, specifically: it appears in the auction exactly once
(`ORDER_FLOW / "volume profile (trend-confirmed)"`), gated on agreeing with the
cascade, so it cannot report an institutional move the cascade disagrees with.
Un-gating it moved ORDER_FLOW's AUC from 0.4707 to 0.4977 — i.e. to the noise
line, not above it. Its position readings measure at baseline too
(`poc_side` 44.8% at 98.7% coverage, `value_area_side` 45.3%). A *behaviour*
reading of volume (a genuine institutional-participation burst, rather than
where price sits vs POC) was tested separately as `ai/participation_lab.py` and
died on ticks.

**Tested directly per group** (110,603 decisions, `/tmp/vp_per_group.py`
pattern): split each winning group's trades by whether VP agreed with the
traded side.

    VP recommendation (44.1% coverage): agree 41.5% right / -0.179R,
      disagree 42.0% / -0.189R  ->  agreeing is WORSE, holds on holdout
    POC side (100% coverage):   agree 42.0% / -0.187R,
      disagree 41.6% / -0.187R  ->  +0.4pp, inside noise, sign flips per group
      (CROSS_ASSET runs -2.9pp the other way)

**Volume profile does not help any category**, pooled or individually, on
either reading. Settled; do not retry without a genuinely new construction of
"volume profile" (not position-vs-POC, not the existing recommendation).

**Do NOT do:**

- Another OHLC feature study for FX majors at intraday horizons. Six channels,
  tick-verified, all empty.
- Reopen mean reversion, zones or SMC. The correct builds were produced and
  they lose.
- Spend more time on costs, exits, targets, stops or R:R. Measured flat (§5).

**If the target is still the goal, it requires changing an input:**

- **Frequency.** +0.2R at 200 trades/year is **Sharpe 2.8** — elite fund
  territory. At 20–40 trades/year it is **Sharpe 0.9–1.3**, which is real and
  achievable. The target is not impossible; the target *at high frequency* is.
- **Data not in OHLC.** L2 depth, economic calendar, or CFTC COT positioning
  (free, weekly, and the system already has a `cot_report` field that is
  **hardcoded to 0** and has never fetched anything).
- **A structural premium** instead of a forecast. Carry measured ~0.5%/yr
  against 5–6% spot vol on EURUSD — carry/vol ≈ 0.09, dominated by spot risk.

---

## 13. Reusable tools built today

| tool | use |
|---|---|
| `ai/pure_direction.py` | zero-cost mid-price direction test **with an unbiased control** — run this FIRST on any new idea |
| `ai/participation_ticks.py` | tick verification harness with real bid/ask and a participation count |
| `core/ou_mean_reversion.py` | `analyse()` returns half-life, σ_eq, forward β, and a pre-trade cost gate for any series |
| `reports/cache/structure_lab/` | 51,462 cached zone trades on ticks — expensive to rebuild, cheap to re-slice |
| `C:/Users/msi/tradify_study/ticks_m1/*.npz` | 16 weeks true bid/ask M1 with `ticks`/`up_ticks`/`down_ticks` |
| `C:/Users/msi/tradify_study/full/*.labelled.jsonl.gz` | ~110k engine decisions with tick-accurate outcomes |

A new idea can now be killed or confirmed in under an hour. That capability is
the durable output of this session.
