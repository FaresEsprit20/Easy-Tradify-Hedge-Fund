import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  viewChild,
} from '@angular/core';

interface Candle {
  open: number;
  high: number;
  low: number;
  close: number;
}

/**
 * A live candlestick chart, drawn on canvas, for the auth screen's hero panel.
 *
 * <h3>Why canvas and not an image</h3>
 * A stock photograph of "trading" is instantly recognisable as stock
 * photography and says nothing about this product. This draws the actual thing
 * the platform works on, costs no asset download, scales to any viewport
 * without art direction, and moves — which is the point: the first impression
 * of a trading terminal should be that it is alive.
 *
 * <h3>The data is synthetic, and that is stated</h3>
 * A random walk, not market data. The template labels the panel as a
 * simulation for exactly the reason this codebase keeps relearning: a
 * plausible-looking number that is not a measurement gets read as one. Nobody
 * should be able to screenshot this and call it a backtest.
 *
 * <h3>Runs outside change detection</h3>
 * The animation loop only touches the canvas, never a signal or a binding, so
 * it never schedules a render. A 60fps loop that dirtied component state would
 * re-render the whole sign-in form sixty times a second.
 */
@Component({
  selector: 'app-market-canvas',
  standalone: true,
  templateUrl: './market-canvas.component.html',
  styleUrl: './market-canvas.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MarketCanvasComponent implements AfterViewInit, OnDestroy {
  private readonly canvasRef = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');

  private ctx: CanvasRenderingContext2D | null = null;
  private frame = 0;
  private resizeObserver: ResizeObserver | null = null;

  private candles: Candle[] = [];
  private price = 1.1642;
  private tick = 0;

  /** Bars visible at once. Fewer, wider bars read better than a dense chart. */
  private static readonly BAR_COUNT = 46;

  /** Frames between new bars — the chart advances roughly twice a second. */
  private static readonly FRAMES_PER_BAR = 30;

  ngAfterViewInit(): void {
    const canvas = this.canvasRef().nativeElement;
    this.ctx = canvas.getContext('2d');
    if (!this.ctx) return;

    this.seed();

    // The canvas has no intrinsic size once it is CSS-stretched, so its backing
    // store has to be resized explicitly or it renders blurry on any DPI above 1.
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.resize();

    // Honour a reduced-motion preference: draw the chart once and leave it.
    // The decoration is not worth triggering motion sickness.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      this.draw();
      return;
    }

    this.loop();
  }

  ngOnDestroy(): void {
    cancelAnimationFrame(this.frame);
    this.resizeObserver?.disconnect();
  }

  // ----------------------------------------------------------------

  private seed(): void {
    for (let i = 0; i < MarketCanvasComponent.BAR_COUNT; i++) {
      this.candles.push(this.nextCandle());
    }
  }

  /**
   * One bar of a random walk with a gentle upward drift.
   *
   * The drift is cosmetic — a chart that trends down is a poor greeting — and
   * is the main reason this must never be mistaken for real data.
   */
  private nextCandle(): Candle {
    const open = this.price;
    const drift = 0.00006;
    const volatility = 0.0012;

    const close = open + drift + (Math.random() - 0.5) * volatility;
    const wick = Math.random() * volatility * 0.6;

    this.price = close;

    return {
      open,
      close,
      high: Math.max(open, close) + wick,
      low: Math.min(open, close) - wick,
    };
  }

  private resize(): void {
    const canvas = this.canvasRef().nativeElement;
    const dpr = window.devicePixelRatio || 1;
    const { width, height } = canvas.getBoundingClientRect();

    if (width === 0 || height === 0) return;

    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    this.ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);

    this.draw();
  }

  private loop = (): void => {
    this.tick++;

    if (this.tick % MarketCanvasComponent.FRAMES_PER_BAR === 0) {
      this.candles.push(this.nextCandle());
      this.candles.shift();
    }

    this.draw();
    this.frame = requestAnimationFrame(this.loop);
  };

  private draw(): void {
    const ctx = this.ctx;
    const canvas = this.canvasRef().nativeElement;
    if (!ctx) return;

    const { width: w, height: h } = canvas.getBoundingClientRect();
    if (w === 0 || h === 0) return;

    ctx.clearRect(0, 0, w, h);

    // Pad so wicks never clip against the panel edge.
    const padX = 18;
    const padY = 34;
    const plotW = w - padX * 2;
    const plotH = h - padY * 2;

    const highs = this.candles.map((c) => c.high);
    const lows = this.candles.map((c) => c.low);
    const max = Math.max(...highs);
    const min = Math.min(...lows);
    const range = max - min || 1;

    const y = (price: number) => padY + (1 - (price - min) / range) * plotH;

    this.drawGrid(ctx, w, h, padX, padY, plotW, plotH);
    this.drawArea(ctx, y, padX, plotW, h - padY);
    this.drawCandles(ctx, y, padX, plotW);
    this.drawLastPrice(ctx, y, padX, plotW, w);
  }

  private drawGrid(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    padX: number,
    padY: number,
    plotW: number,
    plotH: number,
  ): void {
    ctx.strokeStyle = 'rgba(38, 44, 56, 0.75)';
    ctx.lineWidth = 1;

    for (let i = 0; i <= 4; i++) {
      // The 0.5 offset puts the stroke on a device pixel instead of across
      // two, which is the difference between a hairline and a grey smudge.
      const gy = Math.round(padY + (plotH / 4) * i) + 0.5;
      ctx.beginPath();
      ctx.moveTo(padX, gy);
      ctx.lineTo(padX + plotW, gy);
      ctx.stroke();
    }

    for (let i = 0; i <= 6; i++) {
      const gx = Math.round(padX + (plotW / 6) * i) + 0.5;
      ctx.beginPath();
      ctx.moveTo(gx, padY);
      ctx.lineTo(gx, padY + plotH);
      ctx.stroke();
    }
  }

  /** A soft jade wash under the closes — depth without competing with the bars. */
  private drawArea(
    ctx: CanvasRenderingContext2D,
    y: (p: number) => number,
    padX: number,
    plotW: number,
    baseline: number,
  ): void {
    const step = plotW / this.candles.length;

    const gradient = ctx.createLinearGradient(0, 0, 0, baseline);
    gradient.addColorStop(0, 'rgba(43, 217, 142, 0.18)');
    gradient.addColorStop(1, 'rgba(43, 217, 142, 0)');

    ctx.beginPath();
    ctx.moveTo(padX, baseline);
    this.candles.forEach((c, i) => ctx.lineTo(padX + i * step + step / 2, y(c.close)));
    ctx.lineTo(padX + plotW, baseline);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
  }

  private drawCandles(
    ctx: CanvasRenderingContext2D,
    y: (p: number) => number,
    padX: number,
    plotW: number,
  ): void {
    const step = plotW / this.candles.length;
    const bodyW = Math.max(2, step * 0.56);

    this.candles.forEach((c, i) => {
      const cx = padX + i * step + step / 2;
      const rising = c.close >= c.open;

      // The same jade/coral the rest of the app uses for up/down, so the
      // colour language is learned here and holds everywhere else.
      const colour = rising ? '#2bd98e' : '#f2495c';

      // Older bars recede, so the eye lands on the live end of the chart.
      ctx.globalAlpha = 0.35 + (i / this.candles.length) * 0.65;

      ctx.strokeStyle = colour;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(Math.round(cx) + 0.5, y(c.high));
      ctx.lineTo(Math.round(cx) + 0.5, y(c.low));
      ctx.stroke();

      const top = y(Math.max(c.open, c.close));
      const bottom = y(Math.min(c.open, c.close));
      ctx.fillStyle = colour;
      ctx.fillRect(cx - bodyW / 2, top, bodyW, Math.max(1, bottom - top));
    });

    ctx.globalAlpha = 1;
  }

  /** The live price: a dashed rule and a glowing dot at the last close. */
  private drawLastPrice(
    ctx: CanvasRenderingContext2D,
    y: (p: number) => number,
    padX: number,
    plotW: number,
    w: number,
  ): void {
    const last = this.candles[this.candles.length - 1];
    if (!last) return;

    const step = plotW / this.candles.length;
    const cx = padX + (this.candles.length - 1) * step + step / 2;
    const cy = y(last.close);
    const rising = last.close >= last.open;
    const colour = rising ? '#2bd98e' : '#f2495c';

    ctx.save();
    ctx.setLineDash([3, 4]);
    ctx.strokeStyle = rising ? 'rgba(43, 217, 142, 0.5)' : 'rgba(242, 73, 92, 0.5)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padX, Math.round(cy) + 0.5);
    ctx.lineTo(w - padX, Math.round(cy) + 0.5);
    ctx.stroke();
    ctx.restore();

    ctx.shadowColor = colour;
    ctx.shadowBlur = 10;
    ctx.fillStyle = colour;
    ctx.beginPath();
    ctx.arc(cx, cy, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.font = '500 11px "IBM Plex Mono", monospace';
    ctx.fillStyle = colour;
    ctx.textAlign = 'right';
    ctx.fillText(last.close.toFixed(5), w - padX, cy - 8);
  }
}
