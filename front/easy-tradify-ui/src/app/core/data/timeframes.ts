export type Timeframe = 'M1' | 'M5' | 'M15' | 'M30' | 'H1' | 'H4' | 'D1';

export const TIMEFRAMES: readonly Timeframe[] = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'];

export const TIMEFRAME_SECONDS: Record<Timeframe, number> = {
  M1: 60,
  M5: 300,
  M15: 900,
  M30: 1800,
  H1: 3600,
  H4: 14400,
  D1: 86400,
};

export const DEFAULT_TIMEFRAME: Timeframe = 'M1';

/** How many bars CandleDataService generates for the chart — every overlay
 * anchored to a bar offset (order blocks, FVG, liquidity sweeps, patterns)
 * has to agree with this or it can land outside the visible range. */
export const CHART_LOOKBACK_BARS = 180;

/** Converts a real decision-snapshot `bars_ago` value (SMC order blocks,
 * liquidity-sweep events, ...) into the same bucketed candle time
 * CandleDataService.generate() would assign that bar, so the chart draws
 * the overlay exactly where the backend says it formed. */
export function barsAgoToTime(timeframe: Timeframe, barsAgo: number): number {
  const interval = TIMEFRAME_SECONDS[timeframe];
  const now = Math.floor(Date.now() / 1000 / interval) * interval;
  const clamped = Math.min(Math.max(barsAgo, 0), CHART_LOOKBACK_BARS - 4);
  return now - clamped * interval;
}
