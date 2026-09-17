import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { PanelComponent } from '../../shared/panel/panel.component';
import { AnalysisPanelComponent } from '../../shared/widgets/analysis-panel/analysis-panel.component';
import { IndicatorGridComponent } from '../../shared/widgets/indicator-grid/indicator-grid.component';
import { PriceChartComponent } from '../../shared/widgets/price-chart/price-chart.component';
import { TimeframeSelectorComponent } from '../../shared/widgets/timeframe-selector/timeframe-selector.component';
import { SymbolPickerComponent } from '../../shared/widgets/symbol-picker/symbol-picker.component';
import { StatusPillComponent, PillVariant } from '../../shared/status-pill/status-pill.component';
import { InfoHintComponent } from '../../shared/hint/info-hint.component';
import { OVERLAY_HINTS, DECISION_HINTS } from '../../core/data/hint-copy';
import { AnalysisApiService } from '../../core/services/api/analysis-api.service';
import { CandleDataService } from '../../core/services/candle-data.service';
import { FullAnalysisResult } from '../../core/models/api/analysis-api.model';
import { ChartPriceLine, ChartZone, ChartWavePoint, ChartPatternMarker, ChartStructureEvent, ChartLevelMarker } from '../../core/models/candle.model';
import { CHART_COLORS } from '../../core/chart-theme';
import { DEFAULT_TIMEFRAME, TIMEFRAME_SECONDS, CHART_LOOKBACK_BARS, barsAgoToTime, Timeframe } from '../../core/data/timeframes';

// Order blocks, FVG, and structure (BOS/CHoCH + liquidity sweeps) are all
// Smart Money Concepts output from the same analysis pass — one "SMC"
// toggle draws all of it together instead of splitting it into three
// separately-named switches for what is, conceptually, a single indicator.
type OverlayKey = 'entryStopTargets' | 'supportResistance' | 'supplyDemand' | 'smc' | 'premiumDiscount' | 'elliottWave' | 'patterns';

function round4(value: number): number {
  return Math.round(value * 100000) / 100000;
}

@Component({
  selector: 'app-analysis',
  standalone: true,
  imports: [
    FormsModule,
    PanelComponent,
    AnalysisPanelComponent,
    IndicatorGridComponent,
    PriceChartComponent,
    TimeframeSelectorComponent,
    SymbolPickerComponent,
    StatusPillComponent,
    InfoHintComponent,
  ],
  templateUrl: './analysis.component.html',
  styleUrl: './analysis.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnalysisComponent {
  protected readonly overlayHints = OVERLAY_HINTS;
  protected readonly hints = DECISION_HINTS;

  private readonly api = inject(AnalysisApiService);
  private readonly candleData = inject(CandleDataService);
  private readonly route = inject(ActivatedRoute);

  // Angular reuses this component instance across same-route navigations
  // that only change query params (e.g. a second "Full Analysis →" deep
  // link for a different symbol while already on this page) — reading
  // `route.snapshot` once in the constructor would miss that entirely, so
  // this tracks `queryParamMap` reactively instead.
  private readonly urlSymbol = toSignal(this.route.queryParamMap.pipe(map((p) => p.get('symbol'))), {
    initialValue: this.route.snapshot.queryParamMap.get('symbol'),
  });

  protected readonly symbol = signal(this.route.snapshot.queryParamMap.get('symbol') ?? 'XAUUSD');
  protected readonly orderType = signal<'BUY' | 'SELL'>('BUY');
  protected readonly timeframe = signal<Timeframe>(DEFAULT_TIMEFRAME);
  protected readonly fixedTradeSizeUsd = signal(200);
  protected readonly riskPerTradePct = signal(5);

  protected readonly loading = signal(false);
  protected readonly result = signal<FullAnalysisResult | null>(null);

  // Every overlay is OFF by default except the trade levels themselves —
  // each is real analysis output, not decoration, so it's opt-in per the
  // "don't show what wasn't asked for" density rule.
  protected readonly overlays = signal<Record<OverlayKey, boolean>>({
    entryStopTargets: true,
    supportResistance: false,
    supplyDemand: false,
    smc: false,
    premiumDiscount: false,
    elliottWave: false,
    patterns: false,
  });

  protected readonly candles = computed(() => this.candleData.generate(this.symbol(), 180, TIMEFRAME_SECONDS[this.timeframe()]));

  // A result is only valid for the exact symbol+timeframe it was computed
  // for — switching either invalidates it below, and this guard is a second
  // line of defense so a stale result can never draw overlays priced for a
  // different instrument on top of the new chart.
  private readonly liveResult = computed(() => {
    const r = this.result();
    return r && r.symbol === this.symbol() ? r : null;
  });

  protected readonly priceLines = computed<ChartPriceLine[]>(() => {
    const r = this.liveResult();
    if (!r) return [];
    const on = this.overlays();
    const lines: ChartPriceLine[] = [];

    if (on.entryStopTargets) {
      lines.push({ price: r.decision.entry, color: CHART_COLORS.amber, title: 'Entry' });
      lines.push({ price: r.decision.stop, color: CHART_COLORS.coral, title: 'Stop' });
      r.decision.targets.forEach((t, i) => lines.push({ price: t, color: CHART_COLORS.jade, title: `TP${i + 1}` }));
    }
    if (on.supportResistance) {
      const sr = r.overlays.supportResistance;
      lines.push({ price: sr.pivot, color: CHART_COLORS.textDim, title: 'Pivot' });
      lines.push({ price: sr.r1, color: CHART_COLORS.coral, title: 'R1' });
      lines.push({ price: sr.r2, color: CHART_COLORS.coral, title: 'R2' });
      lines.push({ price: sr.s1, color: CHART_COLORS.jade, title: 'S1' });
      lines.push({ price: sr.s2, color: CHART_COLORS.jade, title: 'S2' });
    }
    return lines;
  });

  // Structure and supply/demand read as short, time-anchored segments with
  // a break-point label — not full-chart lines — matching how a real
  // market-structure plugin draws BOS/CHoCH and graded levels.
  protected readonly structureEvents = computed<ChartStructureEvent[]>(() => {
    const r = this.liveResult();
    if (!r || !this.overlays().smc) return [];
    const tf = this.timeframe();
    return r.overlays.marketStructure.events.map((ev) => ({
      fromTime: barsAgoToTime(tf, ev.fromBarsAgo),
      toTime: barsAgoToTime(tf, ev.toBarsAgo),
      level: ev.level,
      type: ev.type,
      bias: ev.bias,
    }));
  });

  protected readonly levelMarkers = computed<ChartLevelMarker[]>(() => {
    const r = this.liveResult();
    if (!r || !this.overlays().supplyDemand) return [];
    const tf = this.timeframe();
    const dz = r.overlays.discountZone;
    return [
      {
        time: barsAgoToTime(tf, dz.formedBarsAgo),
        price: dz.discountLevel,
        label: `${dz.zoneType} (${dz.zoneGrade})`,
        bias: dz.zoneType === 'DEMAND' ? 'bullish' : 'bearish',
      },
    ];
  });

  protected readonly zones = computed<ChartZone[]>(() => {
    const r = this.liveResult();
    if (!r) return [];
    const on = this.overlays();
    const tf = this.timeframe();
    const zones: ChartZone[] = [];

    if (on.smc) {
      const ob = r.overlays.orderBlocks;
      if (ob.bullishOb) {
        zones.push({
          top: ob.bullishOb.high,
          bottom: ob.bullishOb.low,
          fromTime: barsAgoToTime(tf, ob.bullishOb.barsAgo),
          fill: CHART_COLORS.jadeZone,
          border: CHART_COLORS.jade,
          label: 'Bullish OB',
          icon: '■',
        });
      }
      if (ob.bearishOb) {
        zones.push({
          top: ob.bearishOb.high,
          bottom: ob.bearishOb.low,
          fromTime: barsAgoToTime(tf, ob.bearishOb.barsAgo),
          fill: CHART_COLORS.coralZone,
          border: CHART_COLORS.coral,
          label: 'Bearish OB',
          icon: '■',
        });
      }

      // FVG direction has to read at a glance — bullish/bearish share the
      // same shape, so color + icon + label all flip together with
      // `recommendation` instead of a single neutral amber box.
      const fvg = r.overlays.fvg;
      const fvgBullish = fvg.recommendation === 'BUY';
      zones.push({
        top: fvg.top,
        bottom: fvg.bottom,
        fromTime: barsAgoToTime(tf, fvg.barsAgo),
        fill: fvgBullish ? CHART_COLORS.jadeZone : CHART_COLORS.coralZone,
        border: fvgBullish ? CHART_COLORS.jade : CHART_COLORS.coral,
        label: `${fvgBullish ? 'Bullish' : 'Bearish'} FVG · tier ${fvg.tierScore}`,
        icon: fvgBullish ? '▲' : '▼',
      });
    }
    if (on.premiumDiscount) {
      const pd = r.overlays.premiumDiscount;
      const span = pd.rangeHigh - pd.rangeLow;
      const eqTop = round4(pd.rangeLow + span * 0.618);
      const eqBottom = round4(pd.rangeLow + span * 0.382);
      const fromTime = this.candles()[0]?.time ?? barsAgoToTime(tf, CHART_LOOKBACK_BARS - 4);
      zones.push({ top: pd.rangeHigh, bottom: eqTop, fromTime, fill: CHART_COLORS.coralZone, border: CHART_COLORS.coral, label: 'Premium', icon: '▲' });
      zones.push({ top: eqTop, bottom: eqBottom, fromTime, fill: CHART_COLORS.infoZone, border: CHART_COLORS.info, label: 'Equilibrium', icon: '◆' });
      zones.push({ top: eqBottom, bottom: pd.rangeLow, fromTime, fill: CHART_COLORS.jadeZone, border: CHART_COLORS.jade, label: 'Discount', icon: '▼' });
    }
    return zones;
  });

  protected readonly wavePoints = computed<ChartWavePoint[]>(() => {
    const r = this.liveResult();
    if (!r || !this.overlays().elliottWave) return [];
    return r.overlays.elliottWave.points.map((p) => ({ time: p.time, price: p.price, label: p.label }));
  });

  protected readonly patternMarkers = computed<ChartPatternMarker[]>(() => {
    const r = this.liveResult();
    if (!r) return [];
    const on = this.overlays();
    const tf = this.timeframe();
    const markers: ChartPatternMarker[] = [];

    if (on.patterns) {
      markers.push(...r.overlays.patterns.map((p) => ({ time: p.time, price: p.price, name: p.name, bias: p.bias, confidence: p.confidence })));
    }
    if (on.smc && r.overlays.liquiditySweep) {
      const sw = r.overlays.liquiditySweep;
      markers.push({
        time: barsAgoToTime(tf, sw.barsAgo),
        price: sw.level,
        name: `Liquidity Sweep (${sw.sweepSizePips}p)`,
        bias: sw.sideSwept === 'HIGH' ? 'bearish' : 'bullish',
        confidence: Math.round(sw.sweepSizePips),
      });
    }
    return markers;
  });

  constructor() {
    // Drives `symbol` from the URL on every navigation into this page —
    // first load and every subsequent deep link, not just the first one.
    let firstUrlSync = true;
    effect(() => {
      const urlSym = this.urlSymbol();
      if (firstUrlSync) {
        firstUrlSync = false;
        if (urlSym) void this.runAnalysis();
        return;
      }
      if (urlSym && urlSym !== this.symbol()) {
        this.symbol.set(urlSym);
        void this.runAnalysis();
      }
    });

    // Invalidate the on-screen analysis the moment the instrument or
    // timeframe changes — a stale result for the old symbol would otherwise
    // keep drawing overlays priced for a completely different chart.
    let first = true;
    effect(() => {
      this.symbol();
      this.timeframe();
      if (first) {
        first = false;
        return;
      }
      this.result.set(null);
    });
  }

  protected toggleOverlay(key: OverlayKey): void {
    this.overlays.update((o) => ({ ...o, [key]: !o[key] }));
  }

  async runAnalysis(): Promise<void> {
    this.loading.set(true);
    try {
      this.result.set(
        await this.api.analyse({
          symbol: this.symbol(),
          orderType: this.orderType(),
          timeframe: this.timeframe(),
          fixedTradeSizeUsd: this.fixedTradeSizeUsd(),
          riskPerTrade: this.riskPerTradePct() / 100,
        }),
      );
    } finally {
      this.loading.set(false);
    }
  }

  protected gnnVariant(rec: string): PillVariant {
    return rec === 'BULLISH' ? 'jade' : rec === 'BEARISH' ? 'coral' : 'muted';
  }

  protected smcVariant(rec: string): PillVariant {
    return rec === 'BULLISH' ? 'jade' : rec === 'BEARISH' ? 'coral' : 'muted';
  }
}
