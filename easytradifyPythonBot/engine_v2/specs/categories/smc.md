# SMC: liquidity sequence

**v1 members:** SMC overall, market structure, liquidity sweep, premium/discount, ICT FVG type,
FVG/IFVG.

**Trades:** a sweep of an obvious liquidity pool, then a displacement that breaks structure the
other way, then the retrace into the imbalance that displacement left.

**Timeframe:** M15 setup; fills and exits on M1.

## Setup (SELL shown; BUY is symmetric)
1. **Pool.** One of the following, available before the sweep bar:
   - the prior-day high;
   - the prior-week high;
   - the Asia high (from broker 09:00);
   - an M15 equal high.
2. **Sweep.** An M15 bar with `high > pool` and `close < pool`. The sweep extreme `X` is that bar's
   high. No entry can come from a sweep bar inside the rollover window.
3. **Displacement.** Within `SMC_BOS_WINDOW = 8` M15 bars after the sweep (including the sweep bar),
   all of the following:
   - a bar closes below `S`, the last confirmed M15 swing low whose `available_at` is at or before
     the sweep bar's close; this is a BOS_DOWN;
   - the leg from the sweep bar to that BOS bar contains a displacement bar;
   - the leg contains at least one bearish FVG.
4. **Location.** The **last** bearish FVG formed in the leg, `[top, bottom]`.
5. **Entry.** SELL LIMIT at the FVG midpoint, `valid_until` = BOS bar close + `SMC_ENTRY_BARS = 12`
   M15 bars.
6. **Stop.** `X + max(0.10 × ATR(M15), 1.5 × spread)`.
7. **Targets.**
   - **T1:** the lowest low of the leg (sweep bar to BOS bar), with share 0.5. If T1 is less than 1R
     from entry, T1 = entry − 1R.
   - **T2:** the nearest untaken sell-side pool below T1 (prior-day low, prior-week low, Asia low,
     M15 equal lows), with share 0.5. If none lies within 6R, T2 = entry − 3R.
8. **Management.**
   - Breakeven after T1.
   - Time stop: 96 M15 bars after the fill.
9. **Thesis.** Before or after the fill, an M15 close above the FVG top ends the setup: it is
   cancelled if pending, closed at market if filled.
10. **Setup validity.** At most one setup per sweep. If a new sweep of the same pool comes before
    the fill, the old setup is cancelled.

## Recorded conditions (never gates)
- pool type;
- HTF (H4) structure trend;
- the entry's side of the dealing range `[leg low, X]` (premium or discount);
- session;
- FVG size in ATR;
- displacement size in ATR.

## Variants
- `fvg_mid`: the default above.

## v2.1 rules (2026-09-17, `reports/v2/RULE_FINDINGS.md`)
- **Scale:** H4 setup, D1 context.
- **Pools:** prior-day, Asia and equal highs/lows only. Prior-week pools are removed.
- **Room to target:** the nearest confirmed opposing D1 swing beyond the entry must be at least
  `ROOM_MIN_R = 0.5` R away.
- **Exits:** no FVG-close thesis. The invalidation is the sweep extreme, which is the stop.
- **Measured:** 51% won, +0.24R (59 trades, 2010–2020); 69% won, +0.63R (35 trades, 2021–2026).
