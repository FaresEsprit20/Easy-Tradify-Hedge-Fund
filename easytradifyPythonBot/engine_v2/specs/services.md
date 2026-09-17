# Market model services

All services read **closed mid-price bars** built from bid/ask M1 data. Every output carries the
time it became known (`available_at`); nothing is visible to a decision before that time. Every
parameter below has a matching entry in `engine_v2/config_ledger.py`.

## Clock (`data/clock.py`)
- **Broker time:** UTC + 3h while US daylight saving is in effect (second Sunday of March 07:00 UTC →
  first Sunday of November 06:00 UTC), otherwise UTC + 2h. This matches IC Markets' New York-close
  server clock.
- **Trading day:** starts at broker 00:00. Rollover window: broker 23:55–01:05, when no entries are
  created.
- **Sessions (broker hours):** Asia 01–09, London 10–18, New York 15–23.

## Bars (`data/bars.py`)
- **M1 fields:** time (bar open, broker epoch), bid and ask OHLC, mid OHLC = (bid + ask) / 2, spread
  = ask close − bid close, volume (MT5 tick count or Dukascopy volume), up/down ticks (MT5 source
  only).
- **Resampling:** M5, M15, H1, H4 and D1 are built from M1 on broker time. A bar is **closed** at
  `open_time + tf_seconds`, and only closed bars are exposed to decisions.
- **Sources:** Dukascopy (UTC, converted to broker time) up to 2026-05-24, then `ticks_m1` (broker
  time) from 2026-05-25. When both exist for a minute, `ticks_m1` wins.

## ATR (`market_model/indicators.py`)
Wilder ATR(14) on mid bars per timeframe, known at bar close.

## Structure (`market_model/structure.py`)
- **Zigzag swings** per timeframe, threshold `SWING_ATR = 1.0` × ATR(14) of that timeframe:
  - the running extreme is tracked;
  - a swing is confirmed when the mid close retraces from it by at least the threshold;
  - the swing's price and bar are the extreme's; `available_at` is the close of the confirming bar.
- **Trend by structure:** built from the last two confirmed swing highs and lows:
  - UP when the highs are rising (HH) and the lows are rising (HL);
  - DOWN when the highs are lower (LH) and the lows are lower (LL);
  - RANGE otherwise.
- **BOS / CHoCH events:**
  - BOS_UP: a bar closes above the last confirmed swing high.
  - It is labelled CHoCH_UP when the structure trend before that bar was DOWN.
  - BOS_DOWN and CHoCH_DOWN are symmetric.

## Liquidity map (`market_model/liquidity.py`)
- **Pools, with their `available_at`:**
  - prior-day high/low: from the day's close;
  - prior-week high/low;
  - Asia high/low: from broker 09:00;
  - equal highs/lows: two confirmed swings on the timeframe within `EQUAL_ATR = 0.10` × ATR, not yet
    taken.
- **A pool is taken** when price trades beyond it, then marked used.
- **Sweep of a high pool:** a bar with `high > level` and `close < level`, where the bar's high is the
  sweep extreme. A sweep of a low pool is symmetric.

## Displacement and imbalance (`market_model/zones.py`)
- **Bullish FVG at bar i:** `low[i] > high[i-2]`, with the gap at least `FVG_MIN_ATR = 0.10` × ATR.
  The zone is `[high[i-2], low[i]]`, known at the close of bar i. A bearish FVG is symmetric.
- **Displacement bar:** a bar whose range is at least `DISPLACEMENT_ATR = 1.2` × ATR, with its body
  at least 60% of its range.

## Supply/demand zones (`market_model/zones.py`, STRUCTURE)
- **Base:** 1–3 consecutive bars, each with body ≤ 50% of range, and combined high−low ≤
  `BASE_MAX_ATR = 1.2` × ATR.
- **Departure (demand):** within 3 bars after the base, a close ≥ base high + `DEPARTURE_ATR = 1.5` ×
  ATR.
- **Demand zone:** proximal = highest body top of the base, distal = lowest low of the base.
  `available_at` is the departure bar's close. Supply is symmetric.
- **Zone state:**
  - FRESH until price first enters the zone after `available_at`;
  - TOUCHED after that;
  - INVALIDATED when a bar closes beyond the distal edge.
- **Confluence attributes (recorded, never scored):**
  - S/R: at least 2 prior confirmed swings within 0.25 ATR inside the zone;
  - Fibonacci: the 50–61.8% retracement of the departure leg's prior impulse overlaps the zone.

## Volume (`market_model/volume.py`)
- **Day profile (broker day):**
  - input: M1 mid closes;
  - bin size: 0.02 × the day's D1 ATR(14), known from the prior day;
  - weight: volume;
  - POC: the highest-weight bin;
  - value area: 70%, grown around the POC by adding the larger adjacent bin;
  - VAH/VAL: its edges.
- **Profile availability:** a day's profile is available from the next day's 00:00.
- **Developing VWAP:** per broker day, Σ(mid close × volume) ÷ Σ(volume), known at each M1 close.
- **Delta:** up ticks − down ticks per bar (MT5 source only; otherwise missing).

## Regime and oscillators (`market_model/indicators.py`)
- **Efficiency ratio:** ER(20) = |close[t] − close[t−20]| ÷ Σ|Δclose| over 20 bars.
- **EMAs:** EMA(20) and EMA(50).
- **Bollinger:** Bollinger(20, 2).
- **Keltner:** Keltner(20, 1.5 × ATR).
- **MACD:** MACD(12, 26, 9) histogram.
- **RSI:** Wilder RSI(14).

All are computed on mid closes and known at bar close.

## Triggers (`triggers/events.py`)
- **Bullish rejection:** lower wick ≥ 50% of range and close in the top third of the range.
  Bearish is symmetric.
- **Bullish engulfing:** close > open, body covers the previous bar's body, and the previous bar
  closed down.
- **CHoCH/BOS:** from the structure service, on the trigger timeframe.
