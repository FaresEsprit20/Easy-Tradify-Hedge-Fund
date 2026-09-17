import { Injectable } from '@angular/core';
import { SYMBOL_UNIVERSE, SYMBOL_MAP } from '../data/symbols';
import { Candle } from '../models/candle.model';

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function round(value: number, decimals: number): number {
  const f = Math.pow(10, decimals);
  return Math.round(value * f) / f;
}

/**
 * Generates plausible OHLCV candle history for a symbol. There is no
 * backend feed yet, so this stands in for what a `/market/candles`-style
 * endpoint would return — same shape (time/open/high/low/close/volume)
 * a real one would need, so swapping later is a data-source change only.
 */
@Injectable({ providedIn: 'root' })
export class CandleDataService {
  generate(symbol: string, count = 180, intervalSeconds = 60): Candle[] {
    const seed = SYMBOL_MAP.get(symbol) ?? SYMBOL_UNIVERSE[0];
    const digits = seed.pip < 0.01 ? 5 : 2;
    const candles: Candle[] = [];

    let time = Math.floor(Date.now() / 1000 / intervalSeconds) * intervalSeconds - count * intervalSeconds;
    let last = seed.base * (1 - rand(0.002, 0.01));
    const drift = ((seed.base - last) / count) * 1.4;

    for (let i = 0; i < count; i++) {
      const open = last;
      const noise = (Math.random() - 0.5) * seed.pip * 10;
      const close = open + drift + noise;
      const wickUp = Math.random() * seed.pip * 5;
      const wickDown = Math.random() * seed.pip * 5;
      const high = Math.max(open, close) + wickUp;
      const low = Math.min(open, close) - wickDown;

      candles.push({
        time,
        open: round(open, digits),
        high: round(high, digits),
        low: round(low, digits),
        close: round(close, digits),
        volume: Math.round(rand(80, 640)),
      });

      last = close;
      time += intervalSeconds;
    }

    return candles;
  }
}
