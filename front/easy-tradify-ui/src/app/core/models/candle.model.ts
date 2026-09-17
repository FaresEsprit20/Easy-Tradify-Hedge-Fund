export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartPriceLine {
  price: number;
  color: string;
  title: string;
}

/** A shaded price band anchored to its formation candle and extended to the
 * current price (supply/demand, SMC order block, FVG) — rendered as an
 * absolutely-positioned overlay since lightweight-charts v4 has no native
 * filled-rectangle series. Time-anchored (not full-chart-width) so it reads
 * like a real zone-marking plugin instead of a generic highlighted band. */
export interface ChartZone {
  top: number;
  bottom: number;
  fromTime: number;
  fill: string;
  border: string;
  label: string;
  icon: string;
}

/** One labeled point of an Elliott Wave count, drawn as a connected line
 * series with markers. */
export interface ChartWavePoint {
  time: number;
  price: number;
  label: string;
}

export type ChartPatternBias = 'bullish' | 'bearish' | 'neutral';

/** A detected chart pattern, drawn as a marker on the candle series. */
export interface ChartPatternMarker {
  time: number;
  price: number;
  name: string;
  bias: ChartPatternBias;
  confidence: number;
}

/** A market-structure break — BOS (continuation) or CHoCH (reversal) —
 * drawn as a short horizontal segment from the swing point to the breaking
 * candle with a label at the break, the way real structure-mapping
 * indicators draw it. Never a full-chart-width line. */
export interface ChartStructureEvent {
  fromTime: number;
  toTime: number;
  level: number;
  type: 'BOS' | 'CHoCH';
  bias: 'bullish' | 'bearish';
}

/** A single graded level (e.g. a supply/demand zone the entry logic is
 * watching) drawn as a short bracket + label at a specific point in time,
 * not a line spanning the whole chart. */
export interface ChartLevelMarker {
  time: number;
  price: number;
  label: string;
  bias: 'bullish' | 'bearish';
}
