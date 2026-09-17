# WAVE: completed price structures

**v1 members:** chart patterns, wave lattice, Elliott wave, Wyckoff, candlestick.

**Trades:** the next leg after a recognised structure completes.

**Timeframe:** H1; fills on M1. Candles act as triggers.

## Variant `wyckoff_spring` (BUY; `upthrust` is the SELL mirror)
1. **Range.**
   - Take the last `WY_RANGE_BARS = 30` H1 bars before the candidate spring.
   - The range high is their highest high and the range low their lowest low, with height ≤ 4 ×
     ATR(H1).
   - At least 2 bars have lows within 0.25 ATR of the range low.
   - At least 2 bars have highs within 0.25 ATR of the range high.
2. **Spring.** An H1 bar whose low is below `range low − 0.10 × ATR` and whose close is back above the
   range low.
3. **Test.** Within 1–10 H1 bars after the spring, all of:
   - a bar whose low is within ±0.5 ATR of the range low;
   - volume below the spring bar's volume;
   - a close above its open;
   - no close below the spring low.
4. **Entry.** BUY STOP at test bar high + spread, with `valid_until` = test close + 3 H1 bars.
5. **Stop.** Spring low − `0.10 × ATR(H1)`.
6. **Targets.**
   - **T1:** range midpoint, share 0.5. If less than 1R away, T1 = entry + 1R.
   - **T2:** range high, share 0.5. If less than 2R away, T2 = entry + 2R.
7. **Management.**
   - Breakeven after T1.
   - Time stop: 72 H1 bars.
8. **Thesis.** An H1 close below the spring low ends the trade.

## Variant `double_bottom` (BUY; `double_top` is the SELL mirror)
1. **Pattern.** Two confirmed H1 swing lows `B1`, `B2` that:
   - are within 0.30 × ATR(H1) of each other;
   - are 5–60 H1 bars apart;
   - have a confirmed swing high `N` (the neckline) between them, at least 1.5 × ATR above the higher
     bottom.
2. **Break.** The first H1 close above `N` after `B2` is confirmed.
3. **Entry.** BUY STOP at break bar high + spread, with `valid_until` = break close + 3 H1 bars.
4. **Stop.** `min(B1, B2) − 0.10 × ATR(H1)`. If that is more than 4 × ATR below the entry, the stop is
   the midpoint between the neckline and the bottoms instead.
5. **Targets.**
   - **T1:** entry + 1R, share 0.5.
   - **T2:** neckline + (neckline − bottoms), share 0.5. If less than 2R away, T2 = entry + 2R.
6. **Management.**
   - Breakeven after T1.
   - Time stop: 72 H1 bars.
7. **Thesis.** An H1 close below the neckline before T1 ends the trade.

## Variant `elliott_w2` (BUY after a wave 2 in an up-impulse; SELL is the mirror)
1. **Wave 1.** A confirmed H1 swing low `L0` followed by a confirmed swing high `P1`, with
   `P1 − L0 ≥ 3.0 × ATR(H1)`.
2. **Wave 2.** The next confirmed swing low `L2`, with a retracement `(P1 − L2)/(P1 − L0)` between
   0.50 and 0.786, and `L2 > L0`.
3. **Trigger.** After `L2` is confirmed, the first M15 CHoCH_UP before any close below `L2`, provided
   price has not yet closed above `P1`.
4. **Entry.** BUY STOP at trigger high + spread, with `valid_until` = trigger close + 4 M15 bars.
5. **Stop.** `L2 − 0.20 × ATR(H1)`.
6. **Targets.**
   - **T1:** `P1`, share 0.5. If less than 1R away, T1 = entry + 1R.
   - **T2:** `L2 + 1.618 × (P1 − L0)`, share 0.5. If less than 2R away, T2 = entry + 2R.
7. **Management.**
   - Breakeven after T1.
   - Time stop: 120 H1 bars.
8. **Thesis.** An H1 close below `L0` ends the trade (the wave count is invalid).

## Recorded conditions
- H4 structure trend;
- pattern or range height in ATR;
- session.

## v2.1 rules (2026-09-17)
- **Scale:** H4 patterns, H1 trigger, D1 context.
- **Wyckoff:** spring/upthrust disabled (`WY_ENABLED = False`). It lost in both periods, so the
  definition must be rebuilt.
- **Friday:** no Friday entries (`NO_FRIDAY`).
- **Exits:** no thesis exits. The stop is the invalidation.
- **Measured:** 52% won, +0.05R (2,292 trades) → 47% won, −0.03R (1,483 trades). Still negative on
  holdout.
