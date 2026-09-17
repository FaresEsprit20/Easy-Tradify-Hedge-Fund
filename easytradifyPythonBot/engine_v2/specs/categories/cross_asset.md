# CROSS_ASSET: linked-instrument divergence (built last)

**v1 members:** GNN direction, GNN recommendation.

**Trades:** a cross rate that has diverged from the rate its two legs imply, entered after the legs
confirm the move.

**Timeframe:** M15; fills on M1.

## Variant `triangle_lag` (EURGBP shown; also EURJPY and GBPJPY against their USD legs)
1. **Implied rate.** `EURUSD mid / GBPUSD mid` on the same closed M15 bar.
2. **Divergence.**
   - Let `d = (EURGBP mid close − implied) / ATR(M15, EURGBP)`.
   - Let `σ_d` = standard deviation of `d` over 96 bars.
   - Require `|d| ≥ 2.5 × σ_d` for **3 consecutive** M15 closes. v1's single-minute fades lost, so a
     persisting divergence is required.
3. **Direction.** Toward the implied rate: SELL EURGBP when it is rich.
4. **Entry.** MARKET at the next M1 open.
5. **Stop.** The extreme of the last 3 bars ± `0.20 × ATR(M15)`.
6. **Targets.**
   - **T1:** halfway to the implied rate, share 0.5.
   - **T2:** the implied rate, share 0.5.
   - If T2 is less than 1R away, T1 = 0.5R and T2 = 1R.
7. **Management.**
   - Breakeven after T1.
   - Time stop: 16 M15 bars.

## Status
Built after the other seven categories. The GNN is not used as a trade source. It may later be
recorded as a condition.
