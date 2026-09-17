import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { MockStreamService } from '../mock-stream.service';
import { SYMBOL_UNIVERSE } from '../../data/symbols';
import { ApiClient } from '../../http/api-client.service';
import { ApiError } from '../../http/api-error';
import { DataOrigin } from '../../http/backend-health.service';
import { SERVICE } from '../../http/services';
import { environment } from '../../../../environments/environment';
import {
  MonitorStatusWire,
  SymbolRankWire,
  MonitorExecutionWire,
  MonitorClosedTradeWire,
} from '../../models/api/monitor-api.model';
import { GateEvent, Verdict } from '../../models/gate.model';
import { Opportunity, ScanPing } from '../../models/scanner.model';
import { WatchlistItem } from '../../models/market.model';
import {
  MonitorStatus,
  RestartStatus,
  TopSymbol,
  TopSymbolStability,
  FilteredSymbolsResponse,
  MonitorExecutionEntry,
  MonitorClosedTrade,
  FirebaseStatus,
  NewsStatus,
  SessionStatus,
} from '../../models/monitor.model';

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function round(value: number, decimals: number): number {
  const f = Math.pow(10, decimals);
  return Math.round(value * f) / f;
}

/**
 * The monitor's live face: GET/POST /api/v1/monitor/** through the gateway.
 *
 * HOW THE MOCK LAYER SURVIVED THE INTEGRATION
 * -------------------------------------------
 * Every signal below keeps its seeded value and every synchronous getter keeps
 * its signature, so no component or animation had to change. What changed is
 * where the values come from: `refresh*()` calls the backend and writes into
 * the same signals, and `startPolling()` keeps doing it. A component that reads
 * `topSymbols()` cannot tell the difference, which is the point — the process
 * animations, the gate ticker and the radar sweep are all driven by signal
 * transitions and would have had to be rebuilt if this had returned promises
 * to the components instead.
 *
 * `origin` says where the current values came from. It is rendered, never
 * assumed: seeded data on a screen that looks live is how a demo number gets
 * mistaken for a measurement.
 */
@Injectable({ providedIn: 'root' })
export class MonitorApiService {
  private readonly stream = inject(MockStreamService);
  private readonly api = inject(ApiClient);
  private readonly startedAt = Date.now();

  /** Where the values currently in the signals came from. */
  readonly origin = signal<DataOrigin>(environment.allowMockFallback ? 'mock' : 'stale');

  /** Last error surfaced by a poll, for the panel's error strip. */
  readonly lastError = signal<string | null>(null);

  /**
   * Which gates blocked, and how often, over the last ten minutes.
   *
   * The single most useful number when nothing is trading: one check dominating
   * this tally is the whole diagnosis, and it is invisible in the flat event
   * feed as soon as that feed is longer than a screen.
   */
  readonly gateSummary = signal<GateSummaryWire | null>(null);

  /** Worker pool capacity and live thread counts. */
  readonly threadPools = signal<readonly ThreadPoolWire[]>([]);

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  readonly status = signal<MonitorStatus>({
    running: true,
    uptimeSeconds: 0,
    symbolsTracked: SYMBOL_UNIVERSE.length,
    openPositions: 4,
    lastRefreshAt: Date.now(),
  });

  readonly restartStatus = signal<RestartStatus>({
    enabled: false,
    intervalSeconds: 3600,
    lastRestartAt: null,
    nextRestartAt: null,
    restartInProgress: false,
  });

  readonly topSymbols = signal<TopSymbol[]>(this.seedTopSymbols());
  readonly filteredSymbols = signal<FilteredSymbolsResponse>({
    symbols: ['USDCHF', 'NZDUSD'],
    permanentlyExcluded: ['USDTRY'],
    longTermExcluded: ['USDZAR'],
  });

  readonly firebaseStatus = signal<FirebaseStatus>({ connected: true, queueSize: 0, errors: 0, lastWriteAt: Date.now() });
  readonly newsStatus = signal<NewsStatus>({ cacheHealthy: true, highImpactEventsToday: 2, nextEvent: 'USD Non-Farm Payrolls — 13:30 UTC', lastRefreshAt: Date.now() });
  readonly sessionStatus = signal<SessionStatus>({ activeSessions: ['LONDON', 'NEW_YORK'], isMarketOpen: true, minutesToClose: null, lastRefreshAt: Date.now() });

  private executionLog: MonitorExecutionEntry[] = this.seedExecutions();
  private closedTradeLog: MonitorClosedTrade[] = this.seedClosedTrades();

  private delay<T>(value: T, ms = 260): Promise<T> {
    return new Promise((resolve) => setTimeout(() => resolve(value), ms));
  }

  private seedExecutions(): MonitorExecutionEntry[] {
    return SYMBOL_UNIVERSE.slice(0, 42).map((s, i) => {
      const success = Math.random() > 0.12;
      const orderType = i % 2 === 0 ? 'BUY' : 'SELL';
      const dir = orderType === 'BUY' ? 1 : -1;
      return {
        timestamp: Date.now() - Math.round(rand(1, 5200)) * 1000,
        symbol: s.symbol,
        success,
        ticket: success ? 90_100_000 + i : null,
        orderType,
        entryPrice: s.base,
        stopLoss: round(s.base - dir * s.base * 0.008, s.pip < 0.01 ? 5 : 2),
        takeProfit: success ? round(s.base + dir * s.base * 0.014, s.pip < 0.01 ? 5 : 2) : null,
        volume: round(rand(0.1, 2.5), 2),
      };
    }).sort((a, b) => b.timestamp - a.timestamp);
  }

  private seedClosedTrades(): MonitorClosedTrade[] {
    const winReasons = ['TP_HIT', 'TRAILING_STOP', 'BREAK_EVEN'];
    const lossReasons = ['SL_HIT', 'MANUAL_CLOSE'];
    return SYMBOL_UNIVERSE.slice(6, 38).map((s, i) => {
      const isWinning = Math.random() > 0.35;
      return {
        timestamp: Date.now() - Math.round(rand(60, 7200)) * 1000,
        symbol: s.symbol,
        ticket: 90_200_000 + i,
        closeReason: isWinning ? winReasons[Math.floor(rand(0, winReasons.length))] : lossReasons[Math.floor(rand(0, lossReasons.length))],
        profit: round(isWinning ? rand(5, 240) : -rand(5, 180), 2),
        isWinning,
      };
    }).sort((a, b) => b.timestamp - a.timestamp);
  }

  private seedTopSymbols(): TopSymbol[] {
    return SYMBOL_UNIVERSE.slice(0, 8).map((s, i) => ({
      symbol: s.symbol,
      confidence: Math.round(rand(35, 92)),
      isActive: i < 5,
      inPosition: i % 3 === 0,
      ticket: i % 3 === 0 ? 90_000_001 + i : null,
      exchange: 'FX',
      reason: 'Discount zone retest pending',
      entryPrice: i % 3 === 0 ? s.base : null,
      lastCheckTime: Date.now() - Math.round(rand(2, 40)) * 1000,
      stabilityStatus: i < 6 ? 'STABLE' : 'WATCH',
    }));
  }

  // ------------------------------------------------------------------
  // POST /monitor/start, /monitor/stop, /monitor/refresh, /monitor/shutdown
  // ------------------------------------------------------------------
  async start(): Promise<{ success: boolean; message: string }> {
    return this.command('/start', 'Monitor started', () =>
      this.status.update((s) => ({ ...s, running: true, lastRefreshAt: Date.now() })),
    );
  }

  async stop(): Promise<{ success: boolean; message: string }> {
    return this.command('/stop', 'Monitor stopped', () =>
      this.status.update((s) => ({ ...s, running: false })),
    );
  }

  async refresh(): Promise<{ success: boolean; message: string }> {
    const result = await this.command('/refresh', 'Refresh triggered', () =>
      this.status.update((s) => ({ ...s, lastRefreshAt: Date.now() })),
    );
    // A refresh is only meaningful if the ranking is re-read afterwards.
    await this.refreshTopSymbols();
    return result;
  }

  /**
   * POST a control endpoint, applying the optimistic local change either way.
   *
   * The optimistic update is deliberate: these three buttons drive visible
   * state transitions (the running pill, the sweep animation) and waiting for a
   * round trip before moving makes the UI feel broken. If the call fails the
   * next poll corrects the signal within `pollIntervalMs.monitorStatus`, and
   * `lastError` shows why in the meantime.
   */
  private async command(
    path: string,
    successMessage: string,
    optimistic: () => void,
  ): Promise<{ success: boolean; message: string }> {
    optimistic();
    this.log(successMessage);

    try {
      await firstValueFrom(this.api.post<void>(SERVICE.monitor, path));
      this.lastError.set(null);
      this.origin.set('live');
      return { success: true, message: successMessage };
    } catch (error) {
      const message = error instanceof ApiError ? error.message : String(error);
      this.lastError.set(message);
      this.log(`FAILED ${path} — ${message}`);

      if (environment.allowMockFallback && error instanceof ApiError && error.isPlatformFailure) {
        this.origin.set('mock');
        return { success: true, message: `${successMessage} (offline — simulated)` };
      }
      return { success: false, message };
    }
  }

  // ------------------------------------------------------------------
  // POST /monitor/restart, /monitor/restart/auto, GET /monitor/restart/status
  // ------------------------------------------------------------------
  async restart(reason = 'manual (ui)'): Promise<{ success: boolean; message: string }> {
    this.restartStatus.update((r) => ({ ...r, restartInProgress: true }));
    this.log(`Restart triggered (${reason})`);
    setTimeout(() => {
      this.restartStatus.update((r) => ({ ...r, restartInProgress: false, lastRestartAt: Date.now() }));
      this.status.update((s) => ({ ...s, uptimeSeconds: 0, lastRefreshAt: Date.now() }));
      this.log('Restart complete — process re-exec\'d');
    }, 1200);
    return this.delay({ success: true, message: `Restart triggered (${reason}) — process re-execs in ~1s` });
  }

  async configureAutoRestart(enabled: boolean, intervalSeconds: number): Promise<RestartStatus> {
    const next: RestartStatus = {
      ...this.restartStatus(),
      enabled,
      intervalSeconds,
      nextRestartAt: enabled ? Date.now() + intervalSeconds * 1000 : null,
    };
    this.restartStatus.set(next);
    this.log(enabled ? `Auto-restart enabled — every ${Math.round(intervalSeconds / 60)}m` : 'Auto-restart disabled');
    return this.delay(next);
  }

  // ------------------------------------------------------------------
  // GET /monitor/status, /health
  // ------------------------------------------------------------------
  getStatus(): MonitorStatus {
    return { ...this.status(), uptimeSeconds: this.status().running ? Math.floor((Date.now() - this.startedAt) / 1000) : 0 };
  }

  // ------------------------------------------------------------------
  // GET /monitor/top_symbols, /monitor/filtered_symbols
  // ------------------------------------------------------------------
  getTopSymbols(): TopSymbol[] {
    return this.topSymbols();
  }

  getFilteredSymbols(): FilteredSymbolsResponse {
    return this.filteredSymbols();
  }

  // ------------------------------------------------------------------
  // GET /monitor/logs, /monitor/executions, /monitor/closed_trades, POST /monitor/logs/clear
  // ------------------------------------------------------------------
  getExecutions(symbol?: string, limit = 100): MonitorExecutionEntry[] {
    const list = symbol ? this.executionLog.filter((e) => e.symbol === symbol) : this.executionLog;
    return list.slice(-limit);
  }

  getClosedTrades(symbol?: string, limit = 100): MonitorClosedTrade[] {
    const list = symbol ? this.closedTradeLog.filter((t) => t.symbol === symbol) : this.closedTradeLog;
    return list.slice(-limit);
  }

  clearLogs(): void {
    this.executionLog = [];
    this.closedTradeLog = [];
  }

  // ==================================================================
  // LIVE READS
  // ==================================================================

  /**
   * Begin polling the monitor. Idempotent — calling it twice does not stack
   * timers, which matters because the shell and the monitor page both want the
   * status and either may mount first.
   */
  startPolling(): void {
    if (this.pollTimer !== null) return;

    void this.refreshAll();
    this.pollTimer = setInterval(() => void this.refreshAll(), environment.pollIntervalMs.monitorStatus);
  }

  stopPolling(): void {
    if (this.pollTimer === null) return;
    clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  async refreshAll(): Promise<void> {
    // Settled, not all: one dead endpoint must not blank the other three
    // panels. Each refresh reports its own failure.
    await Promise.allSettled([
      this.refreshStatus(),
      this.refreshTopSymbols(),
      this.refreshFilteredSymbols(),
      this.refreshGateEvents(),
      this.refreshWatchlist(),
      this.refreshThreads(),
    ]);
  }

  async refreshStatus(): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<MonitorStatusWire>(SERVICE.monitor, '/status'),
      );

      // `success: false` is a 200 carrying an error — the Java layer reports
      // an unreachable Python monitor this way rather than as a 5xx.
      if (wire.success === false) {
        this.markStale(wire.error ?? 'Monitor reported failure');
        this.status.update((s) => ({ ...s, running: false }));
        return;
      }

      this.status.set({
        running: wire.running ?? false,
        // The backend does not report uptime; it is derived from when this tab
        // first saw the monitor running. Labelled as approximate in the model.
        uptimeSeconds: wire.running ? Math.floor((Date.now() - this.startedAt) / 1000) : 0,
        symbolsTracked: wire.totalSymbols ?? 0,
        openPositions: wire.activePositions ?? 0,
        lastRefreshAt: parseTimestamp(wire.lastScan) ?? Date.now(),
      });
      this.markLive();
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  async refreshTopSymbols(): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<SymbolRankWire[]>(SERVICE.monitor, '/top-symbols'),
      );
      if (Array.isArray(wire)) {
        const ranked = wire.map(toTopSymbol);
        this.topSymbols.set(ranked);

        // The opportunities panel reads the same ranking rather than its own
        // seeded list. Derived here instead of in the component so there is
        // one definition of what an "opportunity" is.
        this.stream.claim('opportunities');
        this.stream.opportunities.set(ranked.map(toOpportunity));

        this.markLive();
      }
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  async refreshFilteredSymbols(): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<string[] | FilteredSymbolsResponse>(SERVICE.monitor, '/filtered-symbols'),
      );

      // The Java signature is List<String>, but the Python service behind it
      // returns the three-bucket object. Accept both rather than depend on
      // which layer answered.
      if (Array.isArray(wire)) {
        this.filteredSymbols.set({ symbols: wire, permanentlyExcluded: [], longTermExcluded: [] });
      } else if (wire && typeof wire === 'object') {
        this.filteredSymbols.set({
          symbols: wire.symbols ?? [],
          permanentlyExcluded: wire.permanentlyExcluded ?? [],
          longTermExcluded: wire.longTermExcluded ?? [],
        });
      }
      this.markLive();
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  /** Replaces the seeded execution log with what the monitor actually did. */
  async refreshExecutions(symbol?: string, limit = 100): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<unknown>(SERVICE.monitor, '/executions', { symbol, limit }),
      );
      const rows = unwrapList<MonitorExecutionWire>(wire, 'executions');
      if (rows) {
        this.executionLog = rows.map(toExecutionEntry).sort((a, b) => b.timestamp - a.timestamp);
        this.markLive();
      }
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  async refreshClosedTrades(symbol?: string, limit = 100): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<unknown>(SERVICE.monitor, '/closed-trades', { symbol, limit }),
      );
      const rows = unwrapList<MonitorClosedTradeWire>(wire, 'closedTrades', 'closed_trades');
      if (rows) {
        this.closedTradeLog = rows.map(toClosedTrade).sort((a, b) => b.timestamp - a.timestamp);
        this.markLive();
      }
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  /** Pulls the monitor's own log lines into the activity stream. */
  async refreshLogs(limit = 200): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<unknown>(SERVICE.monitor, '/logs', { limit }),
      );
      const rows = unwrapList<string | { message?: string; line?: string }>(wire, 'logs');
      if (!rows) return;

      // The monitor's own log lines replace the invented activity feed.
      this.stream.claim('activityLog');
      this.stream.activityLog.set(
        rows.slice(-80).map((row, i) => ({
          id: `monitor-log-${i}`,
          timestamp: Date.now(),
          level: 'info' as const,
          message: typeof row === 'string' ? row : (row.message ?? row.line ?? ''),
        })),
      );
      this.markLive();
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  /**
   * Gate decisions -> the gate ticker, and the scanner's ping/opportunity view.
   *
   * These three panels were reading invented data until now. The feed is the
   * veto engine's own record of what it evaluated, so a gate shown here fired
   * on a real decision — and critically, a check ABSENT from a decision is not
   * reported as a pass, because the engine short-circuits on the first veto and
   * never ran the rest.
   */
  async refreshGateEvents(limit = 60): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<GateEventsWire>(SERVICE.monitor, '/gate-events', { limit }),
      );

      const events = wire?.events ?? [];

      // Claim before writing: the mock generator ticks every 1.8s and would
      // otherwise overwrite these with invented events.
      this.stream.claim('gateEvents');
      this.stream.claim('scanPings');

      this.stream.gateEvents.set(events.map(toGateEvent));
      this.gateSummary.set(wire?.summary ?? null);

      // The scanner's radar reads the same decisions. Angle and radius are
      // pure geometry with no backend meaning, so they are derived here from
      // the symbol rather than pretended to be data.
      this.stream.scanPings.set(events.slice(0, 24).map(toScanPing));

      this.markLive();
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  /** Live quotes -> the watchlist panel. */
  async refreshWatchlist(limit = 24): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<WatchlistWire>(SERVICE.monitor, '/watchlist', { limit }),
      );

      const items = wire?.items ?? [];
      if (items.length) {
        this.stream.claim('watchlist');
        this.stream.watchlist.set(items.map(toWatchlistItem));
        this.markLive();
      }
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  /** Worker pool state -> the thread-pool panel. */
  async refreshThreads(): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<ThreadsWire>(SERVICE.monitor, '/threads'),
      );
      if (wire?.success !== false) {
        this.stream.claim('threads');
        this.threadPools.set(wire?.pools ?? []);
        this.markLive();
      }
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  // ------------------------------------------------------------------

  private markLive(): void {
    this.origin.set('live');
    this.lastError.set(null);
  }

  private markStale(message: string): void {
    this.lastError.set(message);
    // Values already on screen came from somewhere real; mark them stale rather
    // than mock, so the panel says "last known" instead of "sample data".
    if (this.origin() === 'live') this.origin.set('stale');
  }

  private handleReadFailure(error: unknown): void {
    const message = error instanceof ApiError ? error.message : String(error);

    if (environment.allowMockFallback && error instanceof ApiError && error.isPlatformFailure) {
      // Keep the seeded values visible and say so. The alternative — blanking
      // the dashboard — loses the design surface the whole UI was built on.
      this.origin.set('mock');
      this.lastError.set(message);
      return;
    }
    this.markStale(message);
  }

  private log(message: string): void {
    this.stream.activityLog.update((list) => [
      ...list.slice(-79),
      { id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, timestamp: Date.now(), level: 'info', message: `[Monitor] ${message}` },
    ]);
  }

  // ------------------------------------------------------------------
  // GET /monitor/firebase/status, /monitor/news/status, /monitor/session/status
  // POST /monitor/news/refresh, /monitor/session/refresh
  // ------------------------------------------------------------------
  getFirebaseStatus(): FirebaseStatus {
    return this.firebaseStatus();
  }

  getNewsStatus(): NewsStatus {
    return this.newsStatus();
  }

  async refreshNews(): Promise<NewsStatus> {
    const next = { ...this.newsStatus(), lastRefreshAt: Date.now() };
    this.newsStatus.set(next);
    return this.delay(next);
  }

  getSessionStatus(): SessionStatus {
    return this.sessionStatus();
  }

  async refreshSession(): Promise<SessionStatus> {
    const next = { ...this.sessionStatus(), lastRefreshAt: Date.now() };
    this.sessionStatus.set(next);
    return this.delay(next);
  }
}

// ====================================================================
// WIRE -> VIEW MAPPERS
// ====================================================================
// Kept as free functions so they are testable without constructing the
// service, and so the null-handling is in one place. Every field the backend
// declares as nullable gets a default here rather than at each render site.

/**
 * Accept an epoch (number), an ISO string, or nothing.
 *
 * The Python monitor sends epoch seconds in some payloads and the Java layer
 * re-serialises `lastScan` as ISO-8601, so both reach the UI. Returning null
 * for an unparseable value keeps `new Date(NaN)` off the screen.
 */
function parseTimestamp(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined) return null;

  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null;
    // Epoch seconds vs milliseconds: anything below this threshold is seconds.
    // 1e12 ms is 2001, so any real ms timestamp is above it and any plausible
    // seconds timestamp is below.
    return value < 1e12 ? value * 1000 : value;
  }

  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

const STABILITY: readonly TopSymbolStability[] = ['STABLE', 'WATCH', 'UNSTABLE', 'UNKNOWN'];

function toTopSymbol(wire: SymbolRankWire): TopSymbol {
  const status = (wire.stabilityStatus ?? 'UNKNOWN').toUpperCase() as TopSymbolStability;

  return {
    symbol: wire.symbol,
    confidence: wire.confidence ?? 0,
    isActive: wire.isActive ?? false,
    inPosition: wire.inPosition ?? false,
    ticket: wire.ticket ?? null,
    exchange: wire.exchange ?? 'FX',
    reason: wire.reason ?? '',
    entryPrice: wire.entryPrice ?? null,
    lastCheckTime: parseTimestamp(wire.lastCheckTime) ?? Date.now(),
    // Narrow rather than cast blindly: the backend's `stabilityStatus` is a
    // free String, and an unexpected value would otherwise reach a template
    // that switches on the four known ones and render nothing at all.
    stabilityStatus: STABILITY.includes(status) ? status : 'UNKNOWN',
  };
}

function toExecutionEntry(wire: MonitorExecutionWire): MonitorExecutionEntry {
  return {
    timestamp: parseTimestamp(wire.timestamp) ?? Date.now(),
    symbol: wire.symbol ?? '',
    success: wire.success ?? false,
    ticket: wire.ticket ?? null,
    // snake_case from Python, camelCase if a Java DTO ever wraps it.
    orderType: wire.orderType ?? wire.order_type ?? '',
    entryPrice: wire.entryPrice ?? wire.entry_price ?? 0,
    stopLoss: wire.stopLoss ?? wire.stop_loss ?? 0,
    takeProfit: wire.takeProfit ?? wire.take_profit ?? null,
    volume: wire.volume ?? 0,
  };
}

function toClosedTrade(wire: MonitorClosedTradeWire): MonitorClosedTrade {
  const profit = wire.profit ?? 0;
  return {
    timestamp: parseTimestamp(wire.timestamp) ?? Date.now(),
    symbol: wire.symbol ?? '',
    ticket: wire.ticket ?? 0,
    closeReason: wire.closeReason ?? wire.close_reason ?? 'UNKNOWN',
    profit,
    // Derived, not trusted: `isWinning` is a UI concept and the backend has no
    // such field. A zero-profit scratch counts as not winning.
    isWinning: profit > 0,
  };
}

/**
 * Pull a list out of a response that may be the list itself or an envelope.
 *
 * The three log endpoints are `ResponseEntity<Object>` on the Java side and
 * forward the Python body verbatim, which is sometimes a bare array and
 * sometimes `{executions: [...]}`. Returning null when neither shape is present
 * lets the caller keep its current data instead of clearing the panel because
 * of an unrecognised envelope.
 */
function unwrapList<T>(body: unknown, ...keys: string[]): T[] | null {
  if (Array.isArray(body)) return body as T[];

  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    for (const key of [...keys, 'data', 'items', 'results']) {
      if (Array.isArray(record[key])) return record[key] as T[];
    }
  }
  return null;
}

// ====================================================================
// UI FEED WIRE SHAPES  (/monitor/gate-events, /watchlist, /threads)
// ====================================================================

interface GateEventWire {
  timestamp?: number;
  symbol?: string;
  gate?: string;
  vetoed?: boolean;
  reason?: string;
}

export interface GateSummaryWire {
  window_seconds?: number;
  evaluated?: number;
  vetoed?: number;
  symbols_seen?: number;
  by_gate?: Record<string, { evaluated: number; vetoed: number }>;
}

interface GateEventsWire {
  success?: boolean;
  count?: number;
  events?: GateEventWire[];
  summary?: GateSummaryWire;
}

interface WatchlistItemWire {
  symbol?: string;
  last?: number;
  bid?: number;
  ask?: number;
  change_pct?: number;
  series?: number[];
  updated_at?: number;
}

interface WatchlistWire {
  success?: boolean;
  items?: WatchlistItemWire[];
}

export interface ThreadPoolWire {
  name?: string;
  configured?: number | null;
  alive?: number;
  queued?: number | null;
}

interface ThreadsWire {
  success?: boolean;
  running?: boolean;
  pools?: ThreadPoolWire[];
  tracked_symbols?: number;
  open_positions?: number;
}

// --------------------------------------------------------------------

function toGateEvent(wire: GateEventWire, index: number): GateEvent {
  return {
    id: `${wire.timestamp ?? index}-${wire.symbol ?? ''}-${wire.gate ?? ''}`,
    timestamp: (wire.timestamp ?? Date.now() / 1000) * 1000,
    verdict: wire.vetoed ? 'fail' : 'pass',
    gateName: wire.gate ?? 'unknown',
    // The engine records a reason only when a check blocks. Showing an empty
    // string for a pass is honest; inventing "OK" would imply the check
    // reported something it did not.
    margin: wire.reason ?? '',
    symbol: wire.symbol ?? '',
  };
}

/**
 * A gate decision rendered as a radar ping.
 *
 * `angle` and `radius` are presentation only — the backend has no such notion.
 * They are derived deterministically from the symbol so a given symbol always
 * lands in the same place, which makes the radar readable instead of a
 * shimmer of random dots.
 */
function toScanPing(wire: GateEventWire, index: number): ScanPing {
  const symbol = wire.symbol ?? '';
  let hash = 0;
  for (let i = 0; i < symbol.length; i++) {
    hash = (hash * 31 + symbol.charCodeAt(i)) % 360;
  }

  const verdict = wire.vetoed ? 'veto' : 'pass';

  return {
    id: `${wire.timestamp ?? index}-${symbol}`,
    symbol,
    verdict,
    angle: hash,
    // Vetoed symbols sit further out, so the healthy centre reads at a glance.
    radius: wire.vetoed ? 0.75 : 0.45,
    createdAt: (wire.timestamp ?? Date.now() / 1000) * 1000,
  };
}

function toWatchlistItem(wire: WatchlistItemWire): WatchlistItem {
  const change = wire.change_pct ?? 0;

  return {
    symbol: wire.symbol ?? '',
    last: wire.last ?? 0,
    changePct: change,
    bid: wire.bid ?? 0,
    ask: wire.ask ?? 0,
    // The backend does not classify regime, and guessing one from a 32-bar
    // change would be a fabricated signal sitting next to measured prices.
    // 'range' is the neutral value until a real classifier is exposed.
    regime: 'range',
    conviction: 0,
    series: wire.series ?? [],
    updatedAt: (wire.updated_at ?? Date.now() / 1000) * 1000,
  };
}

/** Map a gate verdict onto an Opportunity verdict. Exported for the scanner. */
export function verdictFor(vetoed: boolean): Verdict {
  return vetoed ? 'fail' : 'pass';
}

/**
 * A ranked symbol as the opportunities panel shows it.
 *
 * `gatesPassed`/`gatesTotal` are reported as 0 rather than guessed: the
 * ranking carries a confidence, not a gate tally, and the two are different
 * measurements. The gate counts belong to the veto feed, and pairing a real
 * confidence with an invented gate count is exactly the kind of number that
 * gets read as measured.
 */
function toOpportunity(symbol: TopSymbol): Opportunity {
  return {
    symbol: symbol.symbol,
    verdict: symbol.isActive ? 'pass' : 'near',
    conviction: symbol.confidence,
    gatesPassed: 0,
    gatesTotal: 0,
    note: symbol.reason || (symbol.inPosition ? 'In position' : ''),
    updatedAt: symbol.lastCheckTime,
  };
}
