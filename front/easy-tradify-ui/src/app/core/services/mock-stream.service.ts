import { Injectable, inject, signal } from '@angular/core';
import { ConnectionService } from './connection.service';
import { SYMBOL_UNIVERSE, SYMBOL_MAP } from '../data/symbols';
import { AccountSummary, WatchlistItem, MarketDepth, MarketRegime } from '../models/market.model';
import { Position } from '../models/position.model';
import { ThreadWorker, ThreadStatus } from '../models/thread.model';
import { GateEvent, Verdict } from '../models/gate.model';
import { ScanPing, Opportunity, PingVerdict } from '../models/scanner.model';
import { ActivityLogEntry, ActivityLevel } from '../models/activity.model';
import { AnalysisSnapshot } from '../models/analysis.model';

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function pick<T>(items: readonly T[]): T {
  return items[Math.floor(Math.random() * items.length)];
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
  { name: 'session_veto', unit: 'bool', threshold: 0 },
  { name: 'news_veto', unit: 'bool', threshold: 0 },
];

const ACTIVITY_TEMPLATES: { level: ActivityLevel; message: (s: string) => string }[] = [
  { level: 'info', message: (s) => `Analysis pass complete for ${s}` },
  { level: 'success', message: (s) => `Position opened on ${s} — BUY filled` },
  { level: 'success', message: (s) => `TP1 hit on ${s} — partial close 33%` },
  { level: 'warn', message: (s) => `Spread widened on ${s} — order deferred` },
  { level: 'warn', message: (s) => `Conviction filter declined ${s} setup` },
  { level: 'error', message: (s) => `Order rejected on ${s} — requote` },
  { level: 'info', message: (s) => `Trailing stop advanced on ${s}` },
  { level: 'info', message: (s) => `Regime reclassified for ${s}: TRENDING+NORMAL_VOL` },
];

const REGIMES: MarketRegime[] = ['trend', 'range', 'volatile'];

@Injectable({ providedIn: 'root' })
export class MockStreamService {
  private readonly connection = inject(ConnectionService);

  readonly accountSummary = signal<AccountSummary>(this.seedAccount());
  readonly watchlist = signal<WatchlistItem[]>(this.seedWatchlist());
  readonly positions = signal<Position[]>(this.seedPositions());
  readonly threads = signal<ThreadWorker[]>(this.seedThreads());
  readonly gateEvents = signal<GateEvent[]>([]);
  readonly scanPings = signal<ScanPing[]>([]);
  readonly opportunities = signal<Opportunity[]>(this.seedOpportunities());
  readonly activityLog = signal<ActivityLogEntry[]>([]);
  readonly marketDepth = signal<MarketDepth>(this.seedDepth('XAUUSD'));
  readonly analysisSnapshot = signal<AnalysisSnapshot>(this.seedAnalysis());

  constructor() {
    setInterval(() => this.tickFast(), 900);
    setInterval(() => this.tickThreads(), 1300);
    setInterval(() => this.tickGateEvent(), 1800);
    setInterval(() => this.tickScanPing(), 850);
    setInterval(() => this.tickActivity(), 2600);
    setInterval(() => this.tickAnalysis(), 4200);
    setInterval(() => this.pruneScanPings(), 1000);
  }

  private isLive(): boolean {
    return this.connection.connectionState() === 'live';
  }

  // ====================================================================
  // LIVE-SOURCE CLAIMS
  // ====================================================================
  /**
   * Signals that a real backend feed now writes.
   *
   * WHY THIS EXISTS
   * ---------------
   * The generators below were gated only on `isLive()`, which means they ran
   * precisely WHEN the backend was reachable — so a real gate event written by
   * the monitor service would be overwritten by a fabricated one within two
   * seconds. The gate was inverted relative to what it needed to be, and the
   * symptom would have been real data that flickers and then disappears.
   *
   * An API service calls `claim()` the first time it successfully writes a
   * signal, and the matching generator becomes a no-op permanently. Claiming is
   * one-way on purpose: if the backend later fails, the last real values go
   * stale and are marked stale, which is honest. Resuming invented data at that
   * point would silently replace measurements with fiction on a screen that had
   * been showing the real thing.
   */
  private readonly claimed = new Set<string>();

  claim(signalName: string): void {
    this.claimed.add(signalName);
  }

  private isClaimed(signalName: string): boolean {
    return this.claimed.has(signalName);
  }

  // ---------------------------------------------------------------------
  // Seeds
  // ---------------------------------------------------------------------

  private seedAccount(): AccountSummary {
    return {
      equity: 22414.42,
      balance: 22414.42,
      margin: 198.26,
      marginLevelPct: 11308.4,
      dayPnl: 312.87,
      dayPnlPct: 1.42,
      openPositions: 4,
      updatedAt: Date.now(),
    };
  }

  private seedWatchlist(): WatchlistItem[] {
    return SYMBOL_UNIVERSE.map((s) => ({
      symbol: s.symbol,
      last: s.base,
      changePct: round(rand(-1.2, 1.2), 2),
      bid: s.base - s.pip,
      ask: s.base + s.pip,
      regime: pick(REGIMES),
      conviction: Math.round(rand(20, 92)),
      series: Array.from({ length: 24 }, (_, i) => s.base * (1 + Math.sin(i / 3) * 0.004)),
      updatedAt: Date.now(),
    }));
  }

  private seedPositions(): Position[] {
    const picks = ['EURUSD', 'XAUUSD', 'GBPJPY', 'US500'];
    return picks.map((symbol, i) => {
      const seed = SYMBOL_MAP.get(symbol)!;
      const side = i % 2 === 0 ? 'long' : 'short';
      const entry = seed.base * (1 - (side === 'long' ? 0.004 : -0.004));
      const mark = seed.base;
      const pnl = round((mark - entry) * (side === 'long' ? 1 : -1) * 1000, 2);
      const dir = side === 'long' ? 1 : -1;
      // First two seed positions demo a full 3-tier TP split; the rest show a plain single-TP position.
      const hasSplit = i < 2;
      return {
        id: `POS-${1000 + i}`,
        ticket: 90_000_001 + i,
        symbol,
        side,
        qty: round(rand(0.2, 2.5), 2),
        entry: round(entry, 4),
        mark: round(mark, 4),
        pnl,
        pnlPct: round((pnl / 2000) * 100, 2),
        stop: round(entry * (1 - dir * 0.015), 4),
        target: round(entry * (1 + dir * (hasSplit ? 0.012 : 0.02)), 4),
        target2: hasSplit ? round(entry * (1 + dir * 0.02), 4) : null,
        target3: hasSplit ? round(entry * (1 + dir * 0.03), 4) : null,
        openedAt: Date.now() - Math.round(rand(5, 240)) * 60_000,
        updatedAt: Date.now(),
      };
    });
  }

  private seedThreads(): ThreadWorker[] {
    const statuses: ThreadStatus[] = ['scanning', 'analyzing', 'executing', 'idle'];
    return Array.from({ length: 6 }, (_, i) => ({
      id: `W-${i + 1}`,
      status: statuses[i % statuses.length],
      symbol: statuses[i % statuses.length] === 'idle' ? null : pick(SYMBOL_UNIVERSE).symbol,
      load: Array.from({ length: 8 }, () => rand(0.1, 1)),
      startedAt: Date.now() - Math.round(rand(60, 5000)) * 1000,
      changedAt: Date.now(),
    }));
  }

  private seedOpportunities(): Opportunity[] {
    return SYMBOL_UNIVERSE.slice(0, 6).map((s) => ({
      symbol: s.symbol,
      verdict: pick<PingVerdict>(['pass', 'near', 'veto']),
      conviction: Math.round(rand(30, 90)),
      gatesPassed: Math.round(rand(6, 12)),
      gatesTotal: 12,
      note: 'Awaiting discount entry retest',
      updatedAt: Date.now(),
    }));
  }

  private seedDepth(symbol: string): MarketDepth {
    const seed = SYMBOL_MAP.get(symbol)!;
    const mk = (dir: 1 | -1) =>
      Array.from({ length: 10 }, (_, i) => ({
        price: round(seed.base + dir * i * seed.pip * 3, 4),
        size: Math.round(rand(0.5, 40) * 10) / 10,
      }));
    return { symbol, bids: mk(-1), asks: mk(1), updatedAt: Date.now() };
  }

  private seedAnalysis(): AnalysisSnapshot {
    return {
      symbol: 'XAGUSD',
      regime3d: {
        combinedLabel: 'TRENDING+NORMAL_VOL+NORMAL_LIQ',
        trendStrength: 'TRENDING',
        trendStrengthAdx: 30.5,
        volatility: 'NORMAL',
        volatilityPositionInBand: 0.3,
        liquidity: 'NORMAL',
        spreadHeadroomPct: 50,
      },
      conviction: {
        convictionScore: 0.693,
        minRequired: 0.55,
        passed: false,
        reason: 'hard requirement failed: confluence_chain',
        hardFails: ['confluence_chain'],
        components: {
          coherence: { detail: 'self-consistent', hardFail: false, score: 1.0 },
          confluence_chain: { detail: '2 aligned / 4 opposed', hardFail: true, score: 0.333 },
          family_consensus: { detail: 'families NEUTRAL (+0.17) vs BUY', hardFail: false, score: 0.4 },
          gate_margins: { detail: 'weakest gate cleared by 7.7%', hardFail: false, score: 0.773 },
        },
      },
      gates: GATE_POOL.map((g) => {
        const passed = Math.random() > 0.18;
        const value = round(g.threshold + rand(-6, 12), 1);
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
      }),
      bullCase: {
        thesis: 'BUY',
        confidence: 62.7,
        supportingIndicators: [
          { indicator: 'expected_value', confidence: 65, reason: 'Positive EV: +6.8 pips (+0.21R) at 81% win prob' },
          { indicator: 'trend', confidence: 65, reason: 'Bullish trend, ADX 30.5' },
          { indicator: 'support_resistance', confidence: 75.2, reason: 'reads BUY (score 71.4)' },
          { indicator: 'fvg_ifvg', confidence: 66.1, reason: 'FVG [64.903-64.931], tier score 78' },
        ],
        invalidationTrigger: 'Price closes below stop_loss 64.971 (32.8 pips)',
      },
      bearCase: {
        thesis: 'SELL',
        confidence: 80,
        supportingIndicators: [
          { indicator: 'macd', confidence: 80, reason: 'Bearish crossover, hist falling' },
        ],
        invalidationTrigger: 'Price reclaims above resistance r1 65.088 on volume',
      },
      scenarioTree: {
        primary: {
          scenario: 'Discount entry fills, trade proceeds toward TP1/TP2/TP3',
          probabilityPct: 80.8,
          trigger: 'Price reaches discount level 65.019 (15.0 pips away)',
          targets: [65.045, 65.066, 65.126],
        },
        invalidation: {
          scenario: 'Stop loss hit before any target',
          probabilityPct: 19.2,
          trigger: 'Price trades through stop_loss 64.971 (32.8 pips)',
        },
        alternate: {
          scenario: 'Price never reaches discount, setup expires unfilled',
          probabilityPct: null,
          trigger: 'Price trends away from discount level without retracing',
        },
      },
      probabilityLedger: [
        { step: 'directional_probability', before: 80.75, after: 80.75, delta: 0, clamped: false, note: 'BUY raw' },
        { step: 'expected_value', before: 80.75, after: 88.75, delta: 8, clamped: false, note: 'EV score +8.0' },
        { step: 'h1_alignment', before: 88.75, after: 95, delta: 6.25, clamped: true, note: 'H1 bonus +10.0' },
        { step: 'trend_cascade', before: 95, after: 87.8, delta: -7.2, clamped: false, note: 'against BEARISH cascade' },
        { step: 'adr_exhaustion', before: 87.8, after: 95, delta: 7.2, clamped: true, note: 'fades exhausted ADR move' },
        { step: 'gap_slippage', before: 95, after: 87, delta: -8, clamped: false, note: 'slippage risk HIGH' },
      ],
      decision: {
        verdict: 'VETO',
        verdictLabel: 'VETO — Wick reversal (upper wick 42.0p > 39.0p)',
        probabilityPercent: 87,
        entry: 65.004,
        stop: 64.971,
        targets: [65.045, 65.066, 65.126],
        lotSize: 0.61,
        riskUsd: 20,
        rewardUsd: 25,
        riskRewardRatio: '1:1.3',
        starRating: 1,
        execution: 'DO_NOTHING',
      },
      updatedAt: Date.now(),
    };
  }

  // ---------------------------------------------------------------------
  // Tickers
  // ---------------------------------------------------------------------

  private tickFast(): void {
    if (!this.isLive()) return;

    // Each block yields to its own live feed. They are gated separately
    // because they are claimed separately — positions arrive from the
    // execution service and the watchlist from the monitor, and either can be
    // live while the other is not.
    if (!this.isClaimed('watchlist')) this.driftWatchlist();
    if (!this.isClaimed('positions')) this.driftPositions();
    if (!this.isClaimed('accountSummary')) this.driftAccount();
  }

  private driftWatchlist(): void {
    this.watchlist.update((list) =>
      list.map((item) => {
        // Defaulted, not asserted. The original `SYMBOL_MAP.get(...)!` throws
        // outright on any symbol outside the seeded universe — and the live
        // watchlist returns whatever the monitor is tracking, which includes
        // symbols this map has never heard of.
        const seed = SYMBOL_MAP.get(item.symbol) ?? { pip: 0.0001 };
        const drift = item.last * rand(-0.0009, 0.0009);
        const last = round(item.last + drift, seed.pip < 0.01 ? 5 : 2);
        const series = [...item.series.slice(1), last];
        return {
          ...item,
          last,
          bid: round(last - seed.pip, 5),
          ask: round(last + seed.pip, 5),
          changePct: round(((last - series[0]) / series[0]) * 100, 2),
          series,
          updatedAt: Date.now(),
        };
      }),
    );
  }

  private driftPositions(): void {
    this.positions.update((list) =>
      list.map((p) => {
        const seed = SYMBOL_MAP.get(p.symbol);
        const mark = round(p.mark * (1 + rand(-0.0006, 0.0006)), seed && seed.pip < 0.01 ? 5 : 2);
        const pnl = round((mark - p.entry) * (p.side === 'long' ? 1 : -1) * 1000, 2);
        return { ...p, mark, pnl, pnlPct: round((pnl / 2000) * 100, 2), updatedAt: Date.now() };
      }),
    );
  }

  private driftAccount(): void {
    this.accountSummary.update((a) => {
      const dayPnl = round(a.dayPnl + rand(-8, 10), 2);
      return {
        ...a,
        equity: round(a.balance + dayPnl, 2),
        dayPnl,
        dayPnlPct: round((dayPnl / a.balance) * 100, 2),
        updatedAt: Date.now(),
      };
    });

    this.marketDepth.update((d) => ({ ...d, updatedAt: Date.now() }));
  }

  private tickThreads(): void {
    if (!this.isLive() || this.isClaimed('threads')) return;
    const statuses: ThreadStatus[] = ['scanning', 'analyzing', 'executing', 'idle'];

    this.threads.update((list) =>
      list.map((t) => {
        const load = t.load.map(() => rand(0.1, 1));
        if (Math.random() < 0.3) {
          const status = pick(statuses);
          return {
            ...t,
            status,
            symbol: status === 'idle' ? null : pick(SYMBOL_UNIVERSE).symbol,
            load,
            changedAt: Date.now(),
          };
        }
        return { ...t, load };
      }),
    );
  }

  private tickGateEvent(): void {
    if (!this.isLive() || this.isClaimed('gateEvents')) return;
    const g = pick(GATE_POOL);
    const symbol = pick(SYMBOL_UNIVERSE).symbol;
    const value = round(g.threshold + rand(-8, 14), 1);
    const margin = round(value - g.threshold, 1);
    const verdict: Verdict = Math.abs(margin) < g.threshold * 0.05 ? 'near' : margin >= 0 ? 'pass' : 'fail';

    const event: GateEvent = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      timestamp: Date.now(),
      verdict,
      gateName: g.name,
      margin: `${margin >= 0 ? '+' : ''}${margin} ${g.unit}`,
      symbol,
    };
    this.gateEvents.update((list) => [...list.slice(-59), event]);
  }

  private tickScanPing(): void {
    if (!this.isLive() || this.isClaimed('scanPings')) return;
    const verdict: PingVerdict = pick(['pass', 'pass', 'near', 'veto']);
    const ping: ScanPing = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      symbol: pick(SYMBOL_UNIVERSE).symbol,
      verdict,
      angle: rand(0, 360),
      radius: rand(0.25, 0.95),
      createdAt: Date.now(),
    };
    this.scanPings.update((list) => [...list.slice(-30), ping]);
  }

  private pruneScanPings(): void {
    const cutoff = Date.now() - 1200;
    this.scanPings.update((list) => list.filter((p) => p.createdAt > cutoff));
  }

  private tickActivity(): void {
    if (!this.isLive() || this.isClaimed('activityLog')) return;
    const template = pick(ACTIVITY_TEMPLATES);
    const symbol = pick(SYMBOL_UNIVERSE).symbol;
    const entry: ActivityLogEntry = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      timestamp: Date.now(),
      level: template.level,
      message: template.message(symbol),
      symbol,
    };
    this.activityLog.update((list) => [...list.slice(-79), entry]);
  }

  private tickAnalysis(): void {
    if (!this.isLive()) return;
    this.analysisSnapshot.update((snap) => ({
      ...snap,
      decision: {
        ...snap.decision,
        probabilityPercent: round(Math.min(96, Math.max(4, snap.decision.probabilityPercent + rand(-3, 3))), 1),
      },
      updatedAt: Date.now(),
    }));
  }
}
