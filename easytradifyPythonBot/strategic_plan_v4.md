# Strategic plan v4: find the edge on M1 before building rules

*2026-09-17. Follows `strategic_plan.md` (v2), whose build is complete. Its results are in
`reports/v2/RESULTS.md`: every category was rebuilt and measured, and none reached the target.*

## Target
- **Win rate:** at least 65% of trades won.
- **Expectancy:** at least +0.20R net per trade.
- **Proof:** on data the rules were not built on.
- **Scope:** every category.

## Fixed constraints (operator, 2026-09-17)
- **M1 only.** Two arenas, and each category trades the one its strategy fits:
  - **M1 scalp:** M1 trigger, with stop and target from M1–M5 structure.
  - **M1 precision entry:** M1 trigger, with stop and target from M15–H1 structure.
- **No session or news rules.** Session, hour and weekday are not used as features or filters.
- **Markets:** FX, gold, silver, stock indices and oil. **No crypto.**
- **The operator's own trades** (Gate 2) come later, after the target has been reached.

## Why the order changes
- **What the target needs:** at a 1:1 stop and target, +0.20R needs a win rate of (1.2 + cost) / 2.
  - cost 0.05R: 65% win rate needed, an edge of +15 points over a coin flip;
  - cost 0.15R: 67.5%, +17.5 points;
  - cost 0.30R: 75%, +25 points.
- **Exits cannot create that edge:** measured three times.
- **What M1 FX showed so far:** about ±1 point of edge.
- **Consequence:** measure first where price carries enough predictability, then build rules only there.

## Gate 1 — The predictability limit, per market and category
1. **Data.** True bid/ask M1 bars built from MT5 ticks for every allowed market:
   - the 17 FX pairs and metals already on disk;
   - indices and oil, added to Market Watch with the operator's approval.
2. **Events.** Every base setup of every category, at the scale that fits it (scalp or precision), with
   the H4/D1 rules off.
3. **Labels.** The setup's own outcome on bid/ask ticks, with commission and swap, under the category's
   exit families (standard, secure-half).
4. **Features.** Causal, known at the trigger close, and never time-of-day. They cover:
   - price structure;
   - multi-timeframe trend and position;
   - volatility bursts;
   - tick flow (up/down ticks, tick rate);
   - spread relative to ATR;
   - extension and momentum.
5. **Model.** Gradient boosting, trained on earlier weeks and training markets, then scored on later weeks
   and held-out markets. A shuffled-label control is trained the same way.
6. **Pass line (fixed now).** A slice of at least 10% of a category's events and at least 300
   out-of-sample trades must reach **at least 65% won and at least +0.20R net** on held-out weeks and
   markets. The shuffled control must show no such slice.
7. **Output.** The map of the markets and categories where the target is reachable at all.

**Decision gate.** If no market or category passes, no rule can reach the target on M1 in this setup. The
choice then goes back to the operator: the timeframe, the broker/costs, or the goal.

## Gate 3 — Rules from the edge (only where Gate 1 passed)
- Translate the high-accuracy slice into readable rules inside the category. For example: "SMC sweep +
  tick-flow burst + stop beyond the sweep".
- The rules must keep the model's out-of-sample accuracy.
- Exits are designed last, under the 65% constraint.

## Gate 4 — Proof
- Rules are frozen before testing.
- They must hold on unseen markets, unseen weeks, and against the shuffled control.
- Then a forward shadow run for a fixed number of trades.

## Build
Rules that pass go into the v2 engine. Data, simulator (with swap), execution, risk, journal and the
config ledger already exist.

## Gate 2 — The operator's method (after the target is reached)
20–30 real M1 trades from the operator, encoded and tested the same way.

## Status

| gate | status |
|---|---|
| 1 Predictability limit | **FAIL** 2026-09-17: no category/scale/exit/market-class reaches ≥65% won and ≥+0.20R out of sample (`reports/v4/GATE1_RESULT.md`); decision gate reached |
| 1b Open M1 search (lead/lag + microstructure, 618k events) | **FAIL** 2026-09-17: AUC 0.52–0.53, best top slices 46–49% won at −0.04 to −0.14R (`reports/v4/GATE1B_RESULT.md`) |
| 1c Order-book depth (new input) | **VOID** 2026-09-17: only 5 of 30 markets publish a book, and it is the liquidity provider's fixed size ladder, not orders (bid volume = ask volume on every level in 98–100% of snapshots, one ladder per market; gold the only exception). Imbalance is always zero, so there is nothing to wait for. Recorder still runs (relaunched via WMI) for a narrow gold ladder-skew check |
| 1d Sub-minute tick microstructure, own + related markets (24 features) | **FAIL** 2026-09-17: premise fails at 10/30/60/300 s (predicted move 0.02–0.11 U vs round-trip cost ≈1.1 U); tick features leave the Gate 1b model unchanged (AUC 0.519→0.519, top slices 45–49% won) (`reports/v4/GATE1D_RESULT.md`) |
| 1e Entry at sub-minute bursts (162 configs, ~40M trades) | **FAIL** 2026-09-17: chosen config 18.7% won −0.75R on holdout; 0/162 beat random-time entries; reversal beats continuation by 0.13R on average but is a fraction of the cost (`reports/v4/GATE1E_RESULT.md`) |
| 1f Cross-market lag at the moment it opens (correlated pairs + FX triangles) | **FAIL** 2026-09-17: chosen config 19.8% won −0.57R on holdout vs 22.2% −0.37R at random times; triangles −2.17R; 0 configs positive in both periods (`reports/v4/GATE1F_RESULT.md`) |
| 1g Round-number levels (order clustering) with non-round control levels | **FAIL** 2026-09-17: chosen config 41.8% won −0.19R on holdout vs 40.4% −0.22R at non-round levels; 0/36 positive in both periods (`reports/v4/GATE1G_RESULT.md`) |
| 1h Relative strength: cross-section of all markets + currency strength | **FAIL** 2026-09-17: chosen config 45.7% won −0.10R on holdout = random market/side control; 0/48 positive in both periods (`reports/v4/GATE1H_RESULT.md`) |
| Protocol check (positive control) | **OK** 2026-09-17: a planted 72%-win pocket covering 2% of the real events is recovered on held-out markets/weeks (top 2%: 71.2% won, +0.37R, PASS); null run stays silent (`reports/v4/POSITIVE_CONTROL.md`) |
| 1i Gate 1b search on 57 never-used markets (FX minors, exotics, minor indices) | **FAIL** 2026-09-17: 1,075,490 events; top slices 31–47% won at −0.08 to −0.24R in both unseen-market tests; best class indices 48.6% −0.03R; higher AUC (0.55–0.66) only separates cheap from expensive trades (`reports/v4/GATE1I_RESULT.md`) |
| v5 Live data plan | **ACTIVE** 2026-09-17: every price-history input failed, so the search moves to live data (decision log, result factory, weekly out-of-sample verdicts, live-only questions, operator trades) -- `strategic_plan_v5_live_data.md` |
| 3 Rules from the edge | waiting on Gate 1 |
| 4 Proof | waiting |
| Build | waiting |
| 2 Operator's method | after the target is reached |
