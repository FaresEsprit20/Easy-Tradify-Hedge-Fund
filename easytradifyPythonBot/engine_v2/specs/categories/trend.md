# TREND: pullback continuation

**v1 members:** trend indicator, trend cascade M5–H4, H1 trend, price vs EMA200.

**Trades:** a pullback into value inside an established trend, entered when the lower timeframe
turns back with the trend.

**Timeframes:** H4 and H1 context, H1 impulse, M15 trigger, fills on M1.

## Setup (BUY in an uptrend; SELL is symmetric)
1. **Context.** H4 structure trend is UP **and** H1 structure trend is UP, at the trigger bar.
2. **Impulse.** The last completed H1 up-leg: the last confirmed H1 swing low `L` followed by the last
   confirmed H1 swing high `H`, with `H − L ≥ 2.0 × ATR(H1)`.
3. **Pullback into value.** After `H` is confirmed, an M15 bar trades into the 38.2–61.8%
   retracement zone of `[L, H]`, and no M15 close is below `L`.
4. **Trigger.** An M15 CHoCH_UP (a close above the last confirmed M15 swing high) after the pullback
   touched the zone and before any close below `L`.
5. **Entry.** BUY STOP at trigger bar high + spread, with `valid_until` = trigger close + 4 M15 bars.
6. **Stop.** The lowest low since `H` minus `0.10 × ATR(H1)`.
7. **Targets.**
   - **T1:** `H`, share 0.5. If less than 1R away, T1 = entry + 1R.
   - **T2:** entry + 2.5R, share 0.5.
8. **Management.**
   - Breakeven after T1.
   - Time stop: 96 M15 bars.
9. **Thesis.** An H1 close below `L` ends the trade.
10. **One setup per impulse.**

## Recorded conditions
- retracement depth band (38–50% / 50–62%);
- impulse size in ATR;
- session;
- ER(20) on H1.

## v2.1 rules (2026-09-17)
- **Scale:** H4 impulse, D1 context, H1 trigger.
- **Calm market:** ATR percentile of the trigger timeframe over 250 bars must be at most
  `VOL_PCT_MAX = 0.33`.
- **Measured:** 52% won, +0.06R (293 trades) → 53% won, +0.04R (174 trades).
