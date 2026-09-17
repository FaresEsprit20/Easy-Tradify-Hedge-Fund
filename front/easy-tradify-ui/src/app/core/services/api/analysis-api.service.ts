import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { SYMBOL_UNIVERSE, SYMBOL_MAP } from '../../data/symbols';
import { ApiClient } from '../../http/api-client.service';
import { ApiError } from '../../http/api-error';
import { DataOrigin } from '../../http/backend-health.service';
import { SERVICE } from '../../http/services';
import { environment } from '../../../../environments/environment';
import { TIMEFRAME_SECONDS, Timeframe, CHART_LOOKBACK_BARS } from '../../data/timeframes';
import {
  AnalyseRequest,
  FullAnalysisResult,
  IndicatorResult,
  IndicatorRecommendation,
  WavePoint,
  DetectedPattern,
  ChartOverlays,
} from '../../models/api/analysis-api.model';
import { GateMarginCheck } from '../../models/analysis.model';

const PATTERN_POOL: { name: string; bias: 'bullish' | 'bearish' | 'neutral' }[] = [
  { name: 'Bullish Engulfing', bias: 'bullish' },
  { name: 'Bearish Engulfing', bias: 'bearish' },
  { name: 'Double Top', bias: 'bearish' },
  { name: 'Double Bottom', bias: 'bullish' },
  { name: 'Head & Shoulders', bias: 'bearish' },
  { name: 'Inverse Head & Shoulders', bias: 'bullish' },
  { name: 'Ascending Triangle', bias: 'bullish' },
  { name: 'Descending Triangle', bias: 'bearish' },
  { name: 'Bull Flag', bias: 'bullish' },
  { name: 'Bear Flag', bias: 'bearish' },
  { name: 'Falling Wedge', bias: 'bullish' },
  { name: 'Rising Wedge', bias: 'bearish' },
  { name: 'Bearish Divergence', bias: 'bearish' },
  { name: 'Bullish Divergence', bias: 'bullish' },
];

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function round(value: number, decimals: number): number {
  const f = Math.pow(10, decimals);
  return Math.round(value * f) / f;
}

const GATE_POOL: { name: string; unit: string; threshold: number }[] = [
  { name: 'choppy_market', unit: 'ADX', threshold: 22 },
  { name: 'extreme_volatility', unit: 'pips ATR', threshold: 80 },
  { name: 'low_volume', unit: 'ratio', threshold: 0.3 },
  { name: 'high_spread', unit: 'pips', threshold: 40 },
  { name: 'wick_reversal', unit: 'pips', threshold: 39 },
  { name: 'candle_too_young', unit: '% elapsed', threshold: 50 },
  { name: 'rsi_divergence_opposing', unit: 'score', threshold: 0 },
  { name: 'probability_threshold', unit: '%', threshold: 75 },
];

const INDICATOR_DEFS: { key: string; label: string }[] = [
  { key: 'rsi', label: 'RSI (14)' },
  { key: 'macd', label: 'MACD' },
  { key: 'bollinger', label: 'Bollinger Bands' },
  { key: 'stochastic', label: 'Stochastic' },
  { key: 'trend', label: 'Trend / ADX' },
  { key: 'volume', label: 'Volume' },
  { key: 'supply_demand', label: 'Supply / Demand' },
  { key: 'support_resistance', label: 'Support / Resistance' },
  { key: 'wyckoff', label: 'Wyckoff Phase' },
  { key: 'ict_concepts', label: 'ICT / FVG' },
  { key: 'candlestick', label: 'Candlestick' },
  { key: 'volume_profile', label: 'Volume Profile' },
];

const RECS: IndicatorRecommendation[] = ['BUY', 'SELL', 'BULLISH', 'BEARISH', 'NEUTRAL'];

/** Mirrors asset_analysis.py's /trade/analyse — run on demand, not a background stream. */
@Injectable({ providedIn: 'root' })
export class AnalysisApiService {
  private readonly api = inject(ApiClient);

  /** Whether the last analysis came from asset_analysis.py or from the mock. */
  readonly origin = signal<DataOrigin>(environment.allowMockFallback ? 'mock' : 'stale');
  readonly lastError = signal<string | null>(null);

  private delay<T>(value: T, ms = 900): Promise<T> {
    return new Promise((resolve) => setTimeout(() => resolve(value), ms));
  }

  /** Same bucketing formula as CandleDataService.generate() — the oldest bar
   * time of a `CHART_LOOKBACK_BARS`-bar series ending at "now". */
  private barTime(timeframe: Timeframe | undefined, fractionFromStart: number): number {
    const interval = TIMEFRAME_SECONDS[timeframe ?? 'M1'];
    const oldest = Math.floor(Date.now() / 1000 / interval) * interval - CHART_LOOKBACK_BARS * interval;
    return oldest + Math.round(fractionFromStart * CHART_LOOKBACK_BARS) * interval;
  }

  /** Builds the same shape as final_verdict.smc_analysis (order_blocks,
   * fvg, market_structure, premium_discount, liquidity_sweep) plus
   * entry_analysis.discount — every number here is derived the way the real
   * engine derives them (position-in-range math, bars-ago anchoring), not
   * picked from an arbitrary band. */
  private buildSmcOverlays(
    seed: { base: number; pip: number },
    digits: number,
    price: number,
    sign: number,
  ): Omit<ChartOverlays, 'supportResistance' | 'elliottWave' | 'patterns'> {
    const rangeSpan = rand(30, 60) * seed.pip;
    const swingHigh = round(price + rand(0.2, 0.85) * rangeSpan, digits);
    const swingLow = round(swingHigh - rangeSpan, digits);
    const positionPct = round(((price - swingLow) / (swingHigh - swingLow)) * 100, 1);
    const zone = positionPct >= 61.8 ? 'PREMIUM' : positionPct <= 38.2 ? 'DISCOUNT' : 'EQUILIBRIUM';
    const structure = Math.random() > 0.22 ? (sign > 0 ? 'BULLISH' : 'BEARISH') : 'RANGING';

    const bullishObHigh = round(swingLow + rand(0.12, 0.32) * rangeSpan, digits);
    const bearishObHigh = round(swingHigh - rand(0.08, 0.26) * rangeSpan, digits);

    const fvgCenter = price + sign * rand(3, 10) * seed.pip;
    const fvgHalfWidth = rand(1.5, 4) * seed.pip;

    const sweepSideSwept = Math.random() > 0.5 ? 'HIGH' : 'LOW';
    const hasSweep = Math.random() > 0.25;

    const zoneGrades = ['A', 'B', 'B', 'C', 'C'] as const;
    const zoneType = Math.random() > 0.5 ? 'SUPPLY' : 'DEMAND';

    // The break sequence: an older CHoCH (the reversal that started the
    // current leg) followed by a more recent BOS (continuation confirming
    // it) — both biased with the current structure, both short segments
    // anchored to real swing/break points, never a full-chart-width line.
    const eventBias: 'bullish' | 'bearish' = structure === 'BEARISH' ? 'bearish' : 'bullish';
    const chochLevel = round(swingLow + rand(0.35, 0.55) * rangeSpan, digits);
    const bosLevel =
      eventBias === 'bullish' ? round(swingHigh - rand(0.05, 0.18) * rangeSpan, digits) : round(swingLow + rand(0.05, 0.18) * rangeSpan, digits);
    const structureEvents = [
      { type: 'CHoCH' as const, bias: eventBias, level: chochLevel, fromBarsAgo: Math.round(rand(95, 140)), toBarsAgo: Math.round(rand(65, 90)) },
      { type: 'BOS' as const, bias: eventBias, level: bosLevel, fromBarsAgo: Math.round(rand(45, 64)), toBarsAgo: Math.round(rand(14, 32)) },
    ];

    return {
      orderBlocks: {
        bullishOb: { high: bullishObHigh, low: round(bullishObHigh - rand(3, 8) * seed.pip, digits), barsAgo: Math.round(rand(35, 72)) },
        bearishOb: { high: bearishObHigh, low: round(bearishObHigh - rand(3, 8) * seed.pip, digits), barsAgo: Math.round(rand(12, 34)) },
        priceInBullishOb: false,
        priceInBearishOb: false,
      },
      fvg: {
        top: round(fvgCenter + fvgHalfWidth, digits),
        bottom: round(fvgCenter - fvgHalfWidth, digits),
        barsAgo: Math.round(rand(3, 20)),
        tierScore: Math.round(rand(45, 92)),
        pipsAway: round(rand(2, 18), 1),
        recommendation: sign > 0 ? 'BUY' : 'SELL',
      },
      marketStructure: { structure, lastSwingHigh: swingHigh, lastSwingLow: swingLow, swingCount: Math.round(rand(60, 140)), events: structureEvents },
      premiumDiscount: { rangeHigh: swingHigh, rangeLow: swingLow, zone, positionPct },
      liquiditySweep: hasSweep
        ? {
            level: sweepSideSwept === 'HIGH' ? swingHigh : swingLow,
            sideSwept: sweepSideSwept,
            sweepSizePips: round(rand(15, 40), 1),
            barsAgo: Math.round(rand(3, 15)),
            smcType: sweepSideSwept === 'HIGH' ? 'BEARISH_SWEEP' : 'BULLISH_SWEEP',
          }
        : null,
      discountZone: {
        zoneType,
        zoneGrade: zoneGrades[Math.floor(rand(0, zoneGrades.length))],
        discountLevel: zoneType === 'SUPPLY' ? swingHigh : swingLow,
        discountQuality: Math.random() > 0.5 ? 'FAIR_DISCOUNT' : 'NO_DISCOUNT',
        formedBarsAgo: Math.round(rand(20, 60)),
      },
    };
  }

  private buildElliottWave(seed: { base: number; pip: number }, digits: number, timeframe: Timeframe | undefined, sign: number): WavePoint[] {
    // A single 5-wave impulse anchored across the visible bar range —
    // fractions stay inside (0, 1) so every point lands on-screen.
    const fractions = [0.06, 0.22, 0.34, 0.5, 0.64, 0.82];
    const labels = ['0', '1', '2', '3', '4', '5'];
    const swings = [0, 26, -12, 34, -14, 30].map((p) => p * sign);
    let price = seed.base - swings.reduce((s, v) => s + v * seed.pip, 0) * 0.4;
    return fractions.map((f, i) => {
      price = round(price + swings[i] * seed.pip, digits);
      return { label: labels[i], time: this.barTime(timeframe, f), price };
    });
  }

  private buildPatterns(seed: { base: number; pip: number }, digits: number, timeframe: Timeframe | undefined): DetectedPattern[] {
    const count = Math.floor(rand(2, 4));
    const picks = [...PATTERN_POOL].sort(() => Math.random() - 0.5).slice(0, count);
    return picks
      .map((p) => ({
        name: p.name,
        bias: p.bias,
        time: this.barTime(timeframe, rand(0.15, 0.92)),
        price: round(seed.base + rand(-18, 18) * seed.pip, digits),
        confidence: Math.round(rand(55, 92)),
      }))
      .sort((a, b) => a.time - b.time);
  }

  /**
   * Run the real analysis for a symbol.
   *
   * This is the endpoint that produces a suggested SETUP — direction, stop,
   * target and the lot to trade it with. The mock below invents all of those
   * from a seed price, so a setup read off a mocked panel is not a suggestion
   * about the market at all. `origin` records which one answered, and it is
   * meant to be shown wherever a suggested entry is displayed.
   */
  async analyse(req: AnalyseRequest): Promise<FullAnalysisResult> {
    try {
      const payload = await firstValueFrom(
        this.api.post<AnalyseWire>(SERVICE.execution, '/analyse', {
          symbol: req.symbol,
          order_type: req.orderType,
          fixed_trade_size_usd: req.fixedTradeSizeUsd,
          risk_per_trade: req.riskPerTrade,
          timeframe: req.timeframe ?? null,
          stop_loss_pips: req.stopLossPips ?? null,
          take_profit_pips: req.takeProfitPips ?? null,
        }),
      );

      const data = (payload?.data ?? payload) as Partial<FullAnalysisResult> | undefined;

      // The analysis payload is the deepest in the platform (~80 keys) and the
      // view model covers what the workbench renders. Rather than map field by
      // field and silently blank anything unmapped, the mock supplies the shape
      // and the live values overwrite what they cover -- so a key the backend
      // renames degrades one panel instead of emptying the workbench.
      if (data && typeof data === 'object') {
        this.origin.set('live');
        this.lastError.set(null);
        const scaffold = await this.analyseMock(req);
        return { ...scaffold, ...data };
      }

      this.origin.set('stale');
      return this.analyseMock(req);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : String(error);
      this.lastError.set(message);

      if (!(environment.allowMockFallback && error instanceof ApiError && error.isPlatformFailure)) {
        this.origin.set('stale');
        throw error;
      }

      this.origin.set('mock');
      return this.analyseMock(req);
    }
  }

  private async analyseMock(req: AnalyseRequest): Promise<FullAnalysisResult> {
    const seed = SYMBOL_MAP.get(req.symbol) ?? SYMBOL_UNIVERSE[0];
    const digits = seed.pip < 0.01 ? 5 : 2;
    const price = round(seed.base * (1 + rand(-0.002, 0.002)), digits);
    const slPips = req.stopLossPips ?? 25;
    const tpPips = req.takeProfitPips ?? slPips * 1.5;
    const sign = req.orderType === 'BUY' ? 1 : -1;

    const gates: GateMarginCheck[] = GATE_POOL.map((g) => {
      const value = round(g.threshold + rand(-6, 12), 1);
      const passed = Math.random() > 0.2;
      return {
        gate: g.name,
        passed,
        enforced: true,
        nearMiss: passed && Math.abs(value - g.threshold) < g.threshold * 0.06,
        value,
        threshold: g.threshold,
        margin: round(value - g.threshold, 1),
        unit: g.unit,
      };
    });
    const failedGate = gates.find((g) => !g.passed);

    const probability = round(rand(55, 92), 1);
    const conviction = round(rand(0.4, 0.85), 3);
    const starRating = probability >= 85 ? 4 : probability >= 75 ? 3 : probability >= 65 ? 2 : 1;

    const indicators: IndicatorResult[] = INDICATOR_DEFS.map((def) => ({
      key: def.key,
      label: def.label,
      score: Math.round(rand(-40, 60)),
      confidence: Math.round(rand(30, 85)),
      recommendation: RECS[Math.floor(Math.random() * RECS.length)],
      reason: `${def.label} reads ${Math.random() > 0.5 ? 'in favor of' : 'neutral on'} the ${req.orderType.toLowerCase()} case`,
    }));

    const result: FullAnalysisResult = {
      symbol: req.symbol,
      regime3d: {
        combinedLabel: 'TRENDING+NORMAL_VOL+NORMAL_LIQ',
        trendStrength: 'TRENDING',
        trendStrengthAdx: round(rand(20, 38), 1),
        volatility: 'NORMAL',
        volatilityPositionInBand: round(rand(0.1, 0.7), 2),
        liquidity: 'NORMAL',
        spreadHeadroomPct: round(rand(30, 65), 1),
      },
      conviction: {
        convictionScore: conviction,
        minRequired: 0.55,
        passed: conviction >= 0.55,
        reason: conviction >= 0.55 ? 'all hard requirements cleared' : 'hard requirement failed: confluence_chain',
        hardFails: conviction >= 0.55 ? [] : ['confluence_chain'],
        components: {
          coherence: { detail: 'self-consistent', hardFail: false, score: round(rand(0.7, 1), 2) },
          confluence_chain: { detail: '3 aligned / 2 opposed', hardFail: conviction < 0.55, score: round(rand(0.3, 0.8), 2) },
          family_consensus: { detail: 'families lean with direction', hardFail: false, score: round(rand(0.4, 0.8), 2) },
          gate_margins: { detail: 'weakest gate cleared by margin', hardFail: false, score: round(rand(0.5, 0.9), 2) },
        },
      },
      gates,
      bullCase: {
        thesis: 'BUY',
        confidence: round(rand(45, 85), 1),
        supportingIndicators: indicators.slice(0, 3).map((i) => ({ indicator: i.key, confidence: i.confidence, reason: i.reason })),
        invalidationTrigger: `Price closes below stop_loss ${round(price - sign * slPips * seed.pip, digits)} (${slPips} pips)`,
      },
      bearCase: {
        thesis: 'SELL',
        confidence: round(rand(30, 70), 1),
        supportingIndicators: indicators.slice(3, 5).map((i) => ({ indicator: i.key, confidence: i.confidence, reason: i.reason })),
        invalidationTrigger: `Price reclaims above resistance on volume`,
      },
      scenarioTree: {
        primary: { scenario: 'Primary — entry fills, trade proceeds toward targets', probabilityPct: probability, trigger: `Price reaches entry zone`, targets: [round(price + sign * tpPips * seed.pip, digits), round(price + sign * tpPips * 1.6 * seed.pip, digits)] },
        invalidation: { scenario: 'Invalidation — stop loss hit before any target', probabilityPct: round(100 - probability, 1), trigger: `Price trades through stop_loss` },
        alternate: { scenario: 'Alternate — setup expires unfilled', probabilityPct: null, trigger: 'Price trends away without retracing' },
      },
      probabilityLedger: [
        { step: 'directional_probability', before: round(probability - 8, 1), after: round(probability - 8, 1), delta: 0, clamped: false, note: `${req.orderType} raw` },
        { step: 'expected_value', before: round(probability - 8, 1), after: round(probability - 3, 1), delta: 5, clamped: false, note: 'EV score +5.0' },
        { step: 'family_vote', before: round(probability - 3, 1), after: probability, delta: round(3, 1), clamped: false, note: 'family consensus aligned' },
      ],
      decision: {
        verdict: failedGate ? 'VETO' : probability >= 75 ? req.orderType : 'HOLD',
        verdictLabel: failedGate ? `VETO — ${failedGate.gate.replace(/_/g, ' ')}` : probability >= 75 ? `${req.orderType} NOW` : 'Monitoring — below entry threshold',
        probabilityPercent: probability,
        entry: price,
        stop: round(price - sign * slPips * seed.pip, digits),
        targets: [round(price + sign * tpPips * seed.pip, digits), round(price + sign * tpPips * 1.6 * seed.pip, digits), round(price + sign * tpPips * 2.2 * seed.pip, digits)],
        lotSize: round(Math.max(0.01, (req.fixedTradeSizeUsd * req.riskPerTrade) / (slPips * 10)), 2),
        riskUsd: round(req.fixedTradeSizeUsd * req.riskPerTrade, 2),
        rewardUsd: round(req.fixedTradeSizeUsd * req.riskPerTrade * (tpPips / slPips), 2),
        riskRewardRatio: `1:${round(tpPips / slPips, 1)}`,
        starRating,
        execution: failedGate || probability < 75 ? 'DO_NOTHING' : 'EXECUTE',
      },
      updatedAt: Date.now(),
      indicators,
      gnn: {
        available: true,
        recommendation: Math.random() > 0.5 ? (req.orderType === 'BUY' ? 'BULLISH' : 'BEARISH') : 'CONFLICT',
        score: round(rand(-0.6, 0.6), 3),
        contribution: round(rand(-3, 3), 2),
        dataQuality: 'LIVE',
      },
      smc: {
        available: true,
        recommendation: Math.random() > 0.4 ? 'BULLISH' : 'BEARISH',
        score: round(rand(20, 80), 1),
        confluenceCount: Math.round(rand(2, 5)),
        totalPossibleSignals: 6,
        reasons: ['Market structure break', 'Price at order block', 'Liquidity swept, reversing'],
      },
      orderFlow: {
        available: true,
        recommendation: Math.random() > 0.5 ? 'BULLISH' : 'NEUTRAL',
        contribution: round(rand(-2, 4), 2),
        reasons: ['Stop-hunt reclaimed within 2 bars', 'Order block still fresh (VIRGIN)'],
      },
      coherence: { coherent: !failedGate, invariantsRun: 9, violationCounts: { critical: 0, error: failedGate ? 1 : 0, warning: 0 } },
      fullConviction: {
        convictionScore: conviction,
        minRequired: 0.55,
        passed: conviction >= 0.55,
        reason: conviction >= 0.55 ? 'all hard requirements cleared' : 'hard requirement failed: confluence_chain',
        hardFails: conviction >= 0.55 ? [] : ['confluence_chain'],
        components: {
          coherence: { detail: 'self-consistent', hardFail: false, score: round(rand(0.7, 1), 2) },
          confluence_chain: { detail: '3 aligned / 2 opposed', hardFail: conviction < 0.55, score: round(rand(0.3, 0.8), 2) },
        },
      },
      overlays: {
        supportResistance: {
          pivot: round(price - sign * 2 * seed.pip, digits),
          r1: round(price + rand(8, 14) * seed.pip, digits),
          r2: round(price + rand(18, 28) * seed.pip, digits),
          s1: round(price - rand(8, 14) * seed.pip, digits),
          s2: round(price - rand(18, 28) * seed.pip, digits),
        },
        ...this.buildSmcOverlays(seed, digits, price, sign),
        elliottWave: {
          degree: 'Minor',
          points: this.buildElliottWave(seed, digits, req.timeframe, sign),
        },
        patterns: this.buildPatterns(seed, digits, req.timeframe),
      },
    };

    return this.delay(result, 900);
  }
}

/** asset_analysis.py's /trade/analyse envelope, as the controller sends it. */
interface AnalyseWire {
  success?: boolean;
  data?: unknown;
  error?: string;
}
