// Typed from asset_analysis.py's /trade/analyse response. This is the fullest
// payload in the whole backend (indicators, GNN, SMC, order flow, coherence,
// conviction) — modeled to the depth the Analysis workbench actually renders,
// not every one of the ~80 output keys.

import { AnalysisSnapshot } from '../analysis.model';

export interface AnalyseRequest {
  symbol: string;
  orderType: 'BUY' | 'SELL';
  fixedTradeSizeUsd: number;
  riskPerTrade: number;
  timeframe?: 'M1' | 'M5' | 'M15' | 'M30' | 'H1' | 'H4' | 'D1';
  stopLossPips?: number;
  takeProfitPips?: number;
}

export type IndicatorRecommendation = 'BUY' | 'SELL' | 'BULLISH' | 'BEARISH' | 'NEUTRAL';

export interface IndicatorResult {
  key: string;
  label: string;
  score: number;
  confidence: number;
  recommendation: IndicatorRecommendation;
  reason: string;
}

export interface GnnResult {
  available: boolean;
  recommendation: 'BULLISH' | 'BEARISH' | 'CONFLICT' | 'NEUTRAL';
  score: number;
  contribution: number;
  dataQuality: 'LIVE' | 'STALE' | 'UNAVAILABLE';
}

export interface SmcResult {
  available: boolean;
  recommendation: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  score: number;
  confluenceCount: number;
  totalPossibleSignals: number;
  reasons: string[];
}

export interface OrderFlowResult {
  available: boolean;
  recommendation: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  contribution: number;
  reasons: string[];
}

export interface CoherenceResult {
  coherent: boolean | null;
  invariantsRun: number;
  violationCounts: { critical: number; error: number; warning: number };
}

export interface ConvictionComponentResult {
  detail: string;
  hardFail: boolean;
  score: number;
}

export interface ConvictionResult {
  convictionScore: number;
  minRequired: number;
  passed: boolean;
  reason: string;
  hardFails: string[];
  components: Record<string, ConvictionComponentResult>;
}

/** Numeric pivot levels — support_resistance's actual price grid, not just its score. */
export interface SupportResistanceLevels {
  pivot: number;
  r1: number;
  r2: number;
  s1: number;
  s2: number;
}

/** One order block from final_verdict.smc_analysis.order_blocks — `barsAgo`
 * is the real anchor the backend reports (bar index offset from "now"), not
 * a guessed formation point, so the chart box lands exactly where the
 * backend says the block formed. */
export interface OrderBlock {
  high: number;
  low: number;
  barsAgo: number;
}

/** Mirrors final_verdict.smc_analysis.order_blocks 1:1 — both blocks are
 * independent and can both be present at once. */
export interface OrderBlocks {
  bullishOb: OrderBlock | null;
  bearishOb: OrderBlock | null;
  priceInBullishOb: boolean;
  priceInBearishOb: boolean;
}

/** Mirrors final_verdict.smc_analysis.fvg — the real payload reports this as
 * a "FVG [top-bottom]" string inside `reason`; parsed to numbers here. */
export interface FvgZone {
  top: number;
  bottom: number;
  barsAgo: number;
  tierScore: number;
  pipsAway: number;
  recommendation: 'BUY' | 'SELL';
}

/** One structural break — BOS (break of structure, trend continuation) or
 * CHoCH (change of character, the first break against the prior trend).
 * `fromBarsAgo`/`toBarsAgo` are the swing point and the breaking candle. */
export interface StructureEvent {
  type: 'BOS' | 'CHoCH';
  bias: 'bullish' | 'bearish';
  level: number;
  fromBarsAgo: number;
  toBarsAgo: number;
}

/** Mirrors final_verdict.smc_analysis.market_structure — the swing points
 * plus the BOS/CHoCH break sequence a real structure-mapping plugin draws. */
export interface MarketStructureLevels {
  structure: 'BULLISH' | 'BEARISH' | 'RANGING';
  lastSwingHigh: number;
  lastSwingLow: number;
  swingCount: number;
  events: StructureEvent[];
}

/** Mirrors final_verdict.smc_analysis.premium_discount — the ICT "OTE" range:
 * the swept high/low split into discount/equilibrium/premium thirds. */
export interface PremiumDiscountRange {
  rangeHigh: number;
  rangeLow: number;
  zone: 'PREMIUM' | 'EQUILIBRIUM' | 'DISCOUNT';
  positionPct: number;
}

/** Mirrors final_verdict.smc_analysis.liquidity_sweep.event — a stop-hunt
 * wick that swept a prior high/low and reclaimed. */
export interface LiquiditySweep {
  level: number;
  sideSwept: 'HIGH' | 'LOW';
  sweepSizePips: number;
  barsAgo: number;
  smcType: string;
}

/** Mirrors entry_analysis.discount — the supply/demand zone the entry logic
 * is actually waiting on, graded A/B/C same as the backend. */
export interface DiscountZone {
  zoneType: 'SUPPLY' | 'DEMAND';
  zoneGrade: 'A' | 'B' | 'C';
  discountLevel: number;
  discountQuality: string;
  formedBarsAgo: number;
}

/** One labeled pivot of an Elliott Wave count, anchored to a real candle time
 * so it lands on the chart's actual visible bar range. */
export interface WavePoint {
  label: string;
  time: number;
  price: number;
}

export interface ElliottWaveCount {
  degree: string;
  points: WavePoint[];
}

export type PatternBias = 'bullish' | 'bearish' | 'neutral';

/** One chart/candlestick pattern detection, anchored to a real candle time. */
export interface DetectedPattern {
  name: string;
  bias: PatternBias;
  time: number;
  price: number;
  confidence: number;
}

/** Everything the Analysis workbench's chart-overlay toggles draw — field
 * shapes mirror final_verdict.smc_analysis / entry_analysis.discount from
 * the real decision-snapshot payload, not generic placeholder bands. */
export interface ChartOverlays {
  supportResistance: SupportResistanceLevels;
  orderBlocks: OrderBlocks;
  fvg: FvgZone;
  marketStructure: MarketStructureLevels;
  premiumDiscount: PremiumDiscountRange;
  liquiditySweep: LiquiditySweep | null;
  discountZone: DiscountZone;
  elliottWave: ElliottWaveCount;
  patterns: DetectedPattern[];
}

/** Full workbench result: the existing AnalysisSnapshot sections plus the deeper ones. */
export interface FullAnalysisResult extends AnalysisSnapshot {
  indicators: IndicatorResult[];
  gnn: GnnResult;
  smc: SmcResult;
  orderFlow: OrderFlowResult;
  coherence: CoherenceResult;
  fullConviction: ConvictionResult;
  overlays: ChartOverlays;
}
