import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  input,
  viewChild,
} from '@angular/core';
import {
  ColorType,
  CrosshairMode,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  LineStyle,
  SeriesMarker,
  Time,
  createChart,
} from 'lightweight-charts';
import { Candle, ChartPriceLine, ChartZone, ChartWavePoint, ChartPatternMarker, ChartStructureEvent, ChartLevelMarker } from '../../../core/models/candle.model';
import { CHART_COLORS } from '../../../core/chart-theme';

@Component({
  selector: 'app-price-chart',
  standalone: true,
  template: `
    <div class="chart-wrap">
      <div #container class="chart-host"></div>
      <div #zoneLayer class="overlay-layer"></div>
      <div #structureLayer class="overlay-layer overlay-layer--structure"></div>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
        width: 100%;
        height: 100%;
        min-height: 0;
      }
      .chart-wrap {
        position: relative;
        width: 100%;
        height: 100%;
      }
      .chart-host {
        width: 100%;
        height: 100%;
      }
      .overlay-layer {
        position: absolute;
        inset: 0;
        z-index: 2;
        pointer-events: none;
        overflow: hidden;
      }
      .overlay-layer--structure {
        z-index: 3;
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PriceChartComponent implements AfterViewInit, OnDestroy {
  readonly candles = input<Candle[]>([]);
  readonly priceLines = input<ChartPriceLine[]>([]);
  readonly zones = input<ChartZone[]>([]);
  readonly wavePoints = input<ChartWavePoint[]>([]);
  readonly patterns = input<ChartPatternMarker[]>([]);
  readonly structureEvents = input<ChartStructureEvent[]>([]);
  readonly levelMarkers = input<ChartLevelMarker[]>([]);

  private readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('container');
  private readonly zoneLayerRef = viewChild.required<ElementRef<HTMLDivElement>>('zoneLayer');
  private readonly structureLayerRef = viewChild.required<ElementRef<HTMLDivElement>>('structureLayer');

  private chart?: IChartApi;
  private series?: ISeriesApi<'Candlestick'>;
  private volumeSeries?: ISeriesApi<'Histogram'>;
  private waveSeries?: ISeriesApi<'Line'>;
  private activeLines: IPriceLine[] = [];
  private resizeObserver?: ResizeObserver;

  constructor() {
    effect(() => {
      this.candles();
      this.applyCandles();
      this.applyZones();
    });
    effect(() => {
      this.priceLines();
      this.applyPriceLines();
    });
    effect(() => {
      this.zones();
      this.applyZones();
    });
    effect(() => {
      this.wavePoints();
      this.applyWave();
    });
    effect(() => {
      this.patterns();
      this.applyPatterns();
    });
    effect(() => {
      this.structureEvents();
      this.levelMarkers();
      this.applyStructure();
    });
  }

  ngAfterViewInit(): void {
    const el = this.containerRef().nativeElement;

    this.chart = createChart(el, {
      width: el.clientWidth || 300,
      height: el.clientHeight || 240,
      layout: {
        background: { type: ColorType.Solid, color: CHART_COLORS.panelBg },
        textColor: CHART_COLORS.textDim,
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: CHART_COLORS.gridLine },
        horzLines: { color: CHART_COLORS.gridLine },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: CHART_COLORS.amber, width: 1, style: LineStyle.Dashed, labelBackgroundColor: CHART_COLORS.amber },
        horzLine: { color: CHART_COLORS.amber, width: 1, style: LineStyle.Dashed, labelBackgroundColor: CHART_COLORS.amber },
      },
      timeScale: { borderColor: CHART_COLORS.border, timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: CHART_COLORS.border },
    });

    this.series = this.chart.addCandlestickSeries({
      upColor: CHART_COLORS.jade,
      downColor: CHART_COLORS.coral,
      borderVisible: false,
      wickUpColor: CHART_COLORS.jade,
      wickDownColor: CHART_COLORS.coral,
    });

    this.volumeSeries = this.chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    this.chart.priceScale('').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    this.waveSeries = this.chart.addLineSeries({
      color: CHART_COLORS.amber,
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      pointMarkersVisible: true,
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    });

    this.applyCandles();
    this.applyPriceLines();
    this.applyZones();
    this.applyWave();
    this.applyPatterns();
    this.applyStructure();

    this.chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
      this.applyZones();
      this.applyStructure();
    });

    this.resizeObserver = new ResizeObserver(() => {
      if (!this.chart) return;
      this.chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
      this.applyZones();
      this.applyStructure();
    });
    this.resizeObserver.observe(el);
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    this.chart?.remove();
  }

  private applyCandles(): void {
    if (!this.series || !this.volumeSeries) return;
    const data = this.candles();
    this.series.setData(data.map((c) => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })));
    this.volumeSeries.setData(
      data.map((c) => ({
        time: c.time as Time,
        value: c.volume,
        color: c.close >= c.open ? CHART_COLORS.jadeVolume : CHART_COLORS.coralVolume,
      })),
    );
    this.chart?.timeScale().fitContent();
  }

  private applyPriceLines(): void {
    if (!this.series) return;
    for (const line of this.activeLines) this.series.removePriceLine(line);
    this.activeLines = this.priceLines().map((l) =>
      this.series!.createPriceLine({
        price: l.price,
        color: l.color,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: l.title,
      }),
    );
  }

  /** Rewrites a `#rrggbb` or `rgb(a)(...)` string to a new alpha — used to
   * build the two-stop gradient fill and the soft border tone from a single
   * base color, without hand-maintaining extra palette entries per zone type. */
  private withAlpha(color: string, alpha: number): string {
    const hex = color.match(/^#([0-9a-f]{6})$/i);
    if (hex) {
      const n = parseInt(hex[1], 16);
      return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
    }
    const rgb = color.match(/rgba?\(([^)]+)\)/);
    if (rgb) {
      const [r, g, b] = rgb[1].split(',').map((s) => s.trim());
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    return color;
  }

  // Zone divs are created imperatively (not through Angular's template), so
  // they never receive the emulated-encapsulation attribute — every visual
  // rule has to be set inline here rather than in the component stylesheet.
  // Styled to read like a real zone-marking plugin: anchored to its
  // formation candle (not the full chart width), gradient fill, a solid
  // "origin" edge, HUD-style corner brackets matching the app's signature
  // reticle motif, and a floating label chip instead of raw text.
  private applyZones(): void {
    const layer = this.zoneLayerRef()?.nativeElement;
    const chart = this.chart;
    if (!layer || !this.series || !chart) return;
    layer.replaceChildren();

    const plotRight = layer.clientWidth - 56;

    for (const zone of this.zones()) {
      const topPx = this.series.priceToCoordinate(zone.top);
      const bottomPx = this.series.priceToCoordinate(zone.bottom);
      if (topPx == null || bottomPx == null) continue;

      const rawLeft = chart.timeScale().timeToCoordinate(zone.fromTime as Time);
      const leftPx = Math.max(0, Math.min(rawLeft ?? 0, plotRight - 4));
      const width = Math.max(4, plotRight - leftPx);
      const top = Math.min(topPx, bottomPx);
      const height = Math.max(3, Math.abs(bottomPx - topPx));
      const border = this.withAlpha(zone.border, 0.6);
      const borderStrong = this.withAlpha(zone.border, 0.95);

      const box = document.createElement('div');
      box.style.position = 'absolute';
      box.style.left = `${leftPx}px`;
      box.style.width = `${width}px`;
      box.style.top = `${top}px`;
      box.style.height = `${height}px`;
      box.style.boxSizing = 'border-box';
      box.style.background = `linear-gradient(180deg, ${this.withAlpha(zone.fill, 0.22)}, ${this.withAlpha(zone.fill, 0.06)})`;
      box.style.borderTop = `1px solid ${border}`;
      box.style.borderBottom = `1px solid ${border}`;
      box.style.borderLeft = `2px solid ${borderStrong}`;
      box.style.opacity = '0';
      box.style.transition = 'opacity 260ms ease-out';

      // HUD reticle corner brackets — same 2px/amber-style language as the
      // panel chrome, just recolored per zone, so overlays feel native to
      // the app rather than bolted on.
      for (const corner of ['tl', 'bl'] as const) {
        const bracket = document.createElement('div');
        bracket.style.position = 'absolute';
        bracket.style.left = '-1px';
        bracket.style.width = '7px';
        bracket.style.height = '7px';
        if (corner === 'tl') {
          bracket.style.top = '-1px';
          bracket.style.borderTop = `2px solid ${borderStrong}`;
          bracket.style.borderLeft = `2px solid ${borderStrong}`;
        } else {
          bracket.style.bottom = '-1px';
          bracket.style.borderBottom = `2px solid ${borderStrong}`;
          bracket.style.borderLeft = `2px solid ${borderStrong}`;
        }
        box.appendChild(bracket);
      }

      const chip = document.createElement('span');
      chip.textContent = `${zone.icon} ${zone.label}`;
      chip.style.position = 'absolute';
      chip.style.top = height > 20 ? '3px' : '-16px';
      chip.style.left = '4px';
      chip.style.padding = '2px 6px';
      chip.style.background = this.withAlpha(zone.border, 0.16);
      chip.style.border = `1px solid ${border}`;
      chip.style.borderRadius = '2px';
      chip.style.font = "600 8.5px 'IBM Plex Mono', monospace";
      chip.style.letterSpacing = '0.03em';
      chip.style.whiteSpace = 'nowrap';
      chip.style.color = zone.border;
      box.appendChild(chip);

      layer.appendChild(box);
      requestAnimationFrame(() => {
        box.style.opacity = '1';
      });
    }
  }

  private applyWave(): void {
    if (!this.waveSeries) return;
    const points = this.wavePoints();
    this.waveSeries.setData(points.map((p) => ({ time: p.time as Time, value: p.price })));
    const markers: SeriesMarker<Time>[] = points.map((p) => ({
      time: p.time as Time,
      position: 'inBar',
      color: CHART_COLORS.amber,
      shape: 'circle',
      text: p.label,
    }));
    this.waveSeries.setMarkers(markers);
  }

  private applyPatterns(): void {
    if (!this.series) return;
    const biasColor: Record<ChartPatternMarker['bias'], string> = {
      bullish: CHART_COLORS.jade,
      bearish: CHART_COLORS.coral,
      neutral: CHART_COLORS.textDim,
    };
    const markers: SeriesMarker<Time>[] = this.patterns().map((p) => ({
      time: p.time as Time,
      position: p.bias === 'bearish' ? 'aboveBar' : 'belowBar',
      color: biasColor[p.bias],
      shape: p.bias === 'bearish' ? 'arrowDown' : p.bias === 'bullish' ? 'arrowUp' : 'circle',
      text: `${p.name} (${p.confidence}%)`,
    }));
    this.series.setMarkers(markers);
  }

  // Structural breaks (BOS/CHoCH) and single-level markers (graded
  // supply/demand) drawn as short, time-bounded segments with a label right
  // at the break — the "ultra market structure" style real SMC plugins use,
  // never a full-chart-width price line.
  private applyStructure(): void {
    const layer = this.structureLayerRef()?.nativeElement;
    const chart = this.chart;
    if (!layer || !this.series || !chart) return;
    layer.replaceChildren();

    const plotRight = layer.clientWidth - 56;
    const timeScale = chart.timeScale();

    for (const ev of this.structureEvents()) {
      const yPx = this.series.priceToCoordinate(ev.level);
      const rawLeft = timeScale.timeToCoordinate(ev.fromTime as Time);
      const rawRight = timeScale.timeToCoordinate(ev.toTime as Time);
      if (yPx == null || rawLeft == null || rawRight == null) continue;

      const leftPx = Math.max(0, Math.min(rawLeft, plotRight));
      const rightPx = Math.max(0, Math.min(rawRight, plotRight));
      const color = ev.bias === 'bullish' ? CHART_COLORS.jade : CHART_COLORS.coral;
      const y = Math.round(yPx);

      const line = document.createElement('div');
      line.style.position = 'absolute';
      line.style.left = `${Math.min(leftPx, rightPx)}px`;
      line.style.width = `${Math.max(2, Math.abs(rightPx - leftPx))}px`;
      line.style.top = `${y}px`;
      line.style.borderTop = ev.type === 'CHoCH' ? `1.5px dashed ${this.withAlpha(color, 0.85)}` : `1.5px solid ${this.withAlpha(color, 0.85)}`;
      layer.appendChild(line);

      const dot = document.createElement('div');
      dot.style.position = 'absolute';
      dot.style.left = `${Math.min(leftPx, rightPx) - 2}px`;
      dot.style.top = `${y - 2}px`;
      dot.style.width = '4px';
      dot.style.height = '4px';
      dot.style.borderRadius = '50%';
      dot.style.background = color;
      layer.appendChild(dot);

      const label = document.createElement('span');
      label.textContent = `${ev.bias === 'bullish' ? '▲' : '▼'} ${ev.type}`;
      label.style.position = 'absolute';
      label.style.left = `${Math.max(leftPx, rightPx) + 4}px`;
      label.style.top = `${y - 8}px`;
      label.style.padding = '1px 5px';
      label.style.background = this.withAlpha(color, 0.18);
      label.style.border = `1px solid ${this.withAlpha(color, 0.7)}`;
      label.style.borderRadius = '2px';
      label.style.font = "700 8px 'IBM Plex Mono', monospace";
      label.style.color = color;
      label.style.whiteSpace = 'nowrap';
      layer.appendChild(label);
    }

    for (const m of this.levelMarkers()) {
      const yPx = this.series.priceToCoordinate(m.price);
      const xPx = timeScale.timeToCoordinate(m.time as Time);
      if (yPx == null || xPx == null) continue;

      const leftPx = Math.max(0, Math.min(xPx, plotRight - 4));
      const color = m.bias === 'bullish' ? CHART_COLORS.jade : CHART_COLORS.coral;
      const y = Math.round(yPx);

      const seg = document.createElement('div');
      seg.style.position = 'absolute';
      seg.style.left = `${leftPx}px`;
      seg.style.width = `${Math.max(4, plotRight - leftPx)}px`;
      seg.style.top = `${y}px`;
      seg.style.borderTop = `1.5px solid ${color}`;
      seg.style.opacity = '0.85';
      layer.appendChild(seg);

      const label = document.createElement('span');
      label.textContent = m.label;
      label.style.position = 'absolute';
      label.style.left = `${leftPx + 4}px`;
      label.style.top = `${y - 16}px`;
      label.style.padding = '1px 5px';
      label.style.background = this.withAlpha(color, 0.18);
      label.style.border = `1px solid ${this.withAlpha(color, 0.7)}`;
      label.style.borderRadius = '2px';
      label.style.font = "700 8px 'IBM Plex Mono', monospace";
      label.style.color = color;
      label.style.whiteSpace = 'nowrap';
      layer.appendChild(label);
    }
  }
}
