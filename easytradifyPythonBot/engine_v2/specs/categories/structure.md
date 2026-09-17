# STRUCTURE: fresh supply and demand zones

**v1 members:** supply/demand, support/resistance, Fibonacci confluence.

**Trades:** the first return to a fresh zone that price left strongly.

**Timeframes:** H1 zones, M15 confirmation, fills and exits on M1.

## Zone
H1 supply/demand zone as defined in `services.md`. Only FRESH zones produce setups. S/R and
Fibonacci confluence are recorded as conditions.

## Variant `first_touch` (BUY at demand shown; SELL at supply is symmetric)
- **Entry:** BUY LIMIT at the zone's proximal edge. It is placed at the zone's `available_at`, with
  `valid_until` = `available_at` + `STRUCT_VALID_H1 = 120` H1 bars. It is cancelled if the zone is
  invalidated first.
- **Stop:** `distal − max(0.10 × ATR(H1), 1.5 × spread)`.
- **T1:** the high of the departure leg (the highest high from the base to the departure bar), share
  0.5. If less than 1R from entry, T1 = entry + 1R.
- **T2:** entry + 3R, share 0.5.
- **Management:**
  - breakeven after T1;
  - time stop: 72 H1 bars after the fill.
- **Thesis:** an H1 close below the distal edge ends the trade (normally the stop is hit first).

## Variant `confirmation`
- **Trigger:** the first M15 bar that closes with its low inside the zone (at or below proximal, at or
  above distal) **and** is a bullish rejection or bullish engulfing candle. Only the zone's first
  touch counts.
- **Entry:** BUY STOP at trigger high + spread, with `valid_until` = trigger close + 4 M15 bars.
- **Stop, targets, management and thesis:** the same as `first_touch`. T1 must be at least 1R from the
  stop-order price.

## Recorded conditions
- H4 structure trend;
- S/R confluence;
- Fibonacci confluence;
- departure size in ATR;
- base bars;
- session;
- zone age at touch.

## v2.1 rules (2026-09-17)
- **Scale:** D1 zones, H4 confirmation trigger, D1 context.
- **Location:** the side-adjusted position of the entry in the 20-day D1 range must be at most
  `RANGE_POS_MAX = 0.34`: demand in the lower third, supply in the upper third.
- **Trend age:** the current D1 structure trend state must be at most `TREND_AGE_MAX = 4` bars old.
- **Targets:** T1 at the nearest opposing zone-timeframe swing at least 1R away. T2 at the departure
  leg extreme.
- **Measured:** 41% won, +0.10R (175 trades) → 51% won, +0.25R (88 trades). The first-touch variant
  alone measured 52% won, +0.30R on 75 holdout trades.
