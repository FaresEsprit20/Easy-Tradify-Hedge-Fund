# MOMENTUM: squeeze release

**v1 members:** MACD momentum, TTM squeeze momentum, RVAM direction, VWAP side, stochastic cross,
Bollinger band walk.

**Trades:** the release of a volatility squeeze in the direction momentum confirms.

**Timeframe:** M15; fills on M1.

## Setup (BUY shown; SELL is symmetric)
1. **Squeeze.** Bollinger(20, 2) sits inside Keltner(20, 1.5 × ATR) for at least `MOM_SQUEEZE_BARS = 6`
   consecutive M15 bars.
2. **Release.** The first bar after the squeeze where the Bollinger bands are outside the Keltner
   channel, **and** all of:
   - MACD histogram > 0 at that close;
   - close > EMA(20);
   - close > the developing daily VWAP;
   - the bar's range is at least 1.0 × ATR(M15).
3. **Entry.** BUY STOP at release high + spread, with `valid_until` = release close + 3 M15 bars.
4. **Stop.** The lowest low of the squeeze bars minus `0.10 × ATR(M15)`. If that is more than
   3 × ATR(M15) below the entry, the stop is the midpoint of the squeeze range instead.
5. **Targets.**
   - **T1:** entry + 1R, share 0.5.
   - **T2:** entry + max(2R, 2 × squeeze range height), share 0.5.
6. **Management.**
   - Breakeven after T1.
   - Trail after T1: an M15 close below the Bollinger midline closes the rest.
   - Time stop: 48 M15 bars.
7. **Thesis.** Before T1, an M15 close back below the squeeze range high ends the trade.

## Recorded conditions
- squeeze length;
- H1 ER(20);
- H4 structure trend;
- session.

## v2.1 rules (2026-09-17)
- **Scale:** H4 setup, D1 efficiency ratio and context.
- **Room to target:** the nearest opposing D1 swing must be at least `ROOM_MIN_R = 0.38` R beyond
  the entry.
- **Session:** no releases in the New York-only session (broker 18–23).
- **Exits:** no "back inside squeeze" exit before T1. The band-walk trail after T1 is kept.
- **Measured:** 61% won, +0.19R (132 trades) → 54% won, +0.12R (56 trades).
