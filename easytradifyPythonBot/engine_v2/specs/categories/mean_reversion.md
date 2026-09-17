# MEAN_REVERSION: stretch back to fair value

**v1 members:** OU dislocation, RSI extreme, stochastic extreme.

**Trades:** in a balanced market, a price stretched far from fair value that shows exhaustion, taken
back toward fair value.

**Timeframes:** H1 regime, M15 signal, fills on M1.

## Setup (BUY below value shown; SELL is symmetric)
1. **Regime.** H1 ER(20) < `MR_ER_MAX = 0.30` at the last closed H1 bar.
2. **Stretch.**
   - Let `dev = M15 close − developing daily VWAP`.
   - Let `σ` = standard deviation of `dev` over the last 96 M15 bars.
   - Require `dev ≤ −MR_SIGMA (2.0) × σ` on at least one of the last 4 bars (including the trigger
     bar).
   - Require RSI(14) to have been below 25 within the last 4 bars.
3. **Exhaustion trigger.** RSI(14) closes back above 30 on a bar with `close > open`.
4. **Entry.** MARKET at the next M1 open, with `valid_until` = trigger close + 1 M15 bar.
5. **Stop.** The lowest low of the last 8 M15 bars minus `0.20 × ATR(M15)`.
6. **Targets.**
   - **T1:** halfway from entry to the VWAP at trigger time, share 0.5.
   - **T2:** the VWAP at trigger time, share 0.5.
   - If T2 is less than 1R away, T1 = entry + 0.5R and T2 = entry + 1R.
7. **Management.**
   - Breakeven after T1.
   - Time stop: `MR_TIME_BARS = 16` M15 bars.
8. **Frequency.** One setup per stretch: after a trigger, no new setup on that side until price
   crosses back to the VWAP.

## Recorded conditions
- stretch in σ;
- VWAP distance in R;
- session;
- H4 structure trend.

## v2.1 (2026-09-17)
- **Scale:** H4 setup, D1 efficiency ratio. No new rules.
- **Measured:** 60% won, −0.09R (57 trades) → 65% won, +0.04R (46 trades).
