import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ExecutionApiService } from './execution-api.service';
import { ApiClient } from '../../http/api-client.service';
import { ApiError } from '../../http/api-error';
import { DataOrigin } from '../../http/backend-health.service';
import { SERVICE } from '../../http/services';
import { environment } from '../../../../environments/environment';
import { ExecuteTradeRequest, ExecuteTradeResponse } from '../../models/api/execution-api.model';
import { CopyTradeStatus } from '../../models/copy-trade.model';

/**
 * Mirrors execute_copy_trade.py's CopyTradeManager — a thin registration layer
 * around the exact same /trade/execute contract execution_controller.py uses,
 * but tracked and reported separately (running, tracked positions, Firebase
 * save health) because it exists to answer a different question: "did the
 * copy-trade pipeline pick this up and persist it?", independent of whether
 * the market-scanning monitor is running at all.
 */
@Injectable({ providedIn: 'root' })
export class CopyTradeApiService {
  private readonly execution = inject(ExecutionApiService);
  private readonly api = inject(ApiClient);

  private readonly startTime = Date.now();

  readonly origin = signal<DataOrigin>(environment.allowMockFallback ? 'mock' : 'stale');
  readonly lastError = signal<string | null>(null);

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  readonly status = signal<CopyTradeStatus>({
    running: true,
    openTrackedPositions: 4,
    openPositions: {},
    stats: {
      startTime: this.startTime,
      tradesRegistered: 4,
      tradesClosed: 0,
      firebaseSaves: 8,
      firebaseErrors: 0,
      webhookCloses: 0,
      trailingUpdates: 0,
      priceUpdates: 0,
      monitorErrors: 0,
    },
    webhookClosedTickets: 0,
    positionCacheSize: 4,
    priceUpdateInterval: 60,
    firebaseConnected: true,
  });

  /** POST /trade/execute, then register_trade_open()'s bookkeeping. */
  async executeAndRegister(req: ExecuteTradeRequest): Promise<ExecuteTradeResponse> {
    const result = await this.execution.executeTrade(req);
    if (result.success && result.ticket) {
      this.status.update((s) => ({
        ...s,
        openTrackedPositions: s.openTrackedPositions + 1,
        positionCacheSize: s.positionCacheSize + 1,
        stats: { ...s.stats, tradesRegistered: s.stats.tradesRegistered + 1, firebaseSaves: s.stats.firebaseSaves + 1 },
      }));
    }
    return result;
  }

  /** GET /copy-trade/status — the last value read from the service. */
  getStatus(): CopyTradeStatus {
    return this.status();
  }

  // ==================================================================
  // LIVE READS
  // ==================================================================

  startPolling(): void {
    if (this.pollTimer !== null) return;
    void this.refreshStatus();
    this.pollTimer = setInterval(
      () => void this.refreshStatus(),
      environment.pollIntervalMs.positions,
    );
  }

  stopPolling(): void {
    if (this.pollTimer === null) return;
    clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  /**
   * Read the copy-trade manager's own bookkeeping.
   *
   * The counters this returns (Firebase saves vs errors, tracked positions vs
   * position cache size) are the whole reason this panel exists: they are how a
   * trade that executed but never persisted becomes visible. Merging rather
   * than replacing keeps the locally-incremented counts from
   * `executeAndRegister` on screen if a field is missing from the payload.
   */
  async refreshStatus(): Promise<void> {
    try {
      const wire = await firstValueFrom(
        this.api.get<CopyTradeStatusWire>(SERVICE.copyTrade, '/status'),
      );

      const stats = wire.stats ?? {};
      this.status.update((current) => ({
        running: wire.running ?? current.running,
        openTrackedPositions:
          wire.open_tracked_positions ?? wire.openTrackedPositions ?? current.openTrackedPositions,
        openPositions: wire.open_positions ?? wire.openPositions ?? current.openPositions,
        stats: {
          // start_time is when the PYTHON process started, which is the number
          // the uptime display should show — not when this browser tab opened.
          startTime: parseStart(stats.start_time) ?? current.stats.startTime,
          tradesRegistered: stats.trades_registered ?? current.stats.tradesRegistered,
          tradesClosed: stats.trades_closed ?? current.stats.tradesClosed,
          firebaseSaves: stats.firebase_saves ?? current.stats.firebaseSaves,
          firebaseErrors: stats.firebase_errors ?? current.stats.firebaseErrors,
          webhookCloses: stats.webhook_closes ?? current.stats.webhookCloses,
          trailingUpdates: stats.trailing_updates ?? current.stats.trailingUpdates,
          priceUpdates: stats.price_updates ?? current.stats.priceUpdates,
          monitorErrors: stats.monitor_errors ?? current.stats.monitorErrors,
        },
        webhookClosedTickets:
          wire.webhook_closed_tickets ?? wire.webhookClosedTickets ?? current.webhookClosedTickets,
        positionCacheSize:
          wire.position_cache_size ?? wire.positionCacheSize ?? current.positionCacheSize,
        priceUpdateInterval:
          wire.price_update_interval ?? wire.priceUpdateInterval ?? current.priceUpdateInterval,
        firebaseConnected:
          wire.firebase_connected ?? wire.firebaseConnected ?? current.firebaseConnected,
      }));

      this.origin.set('live');
      this.lastError.set(null);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : String(error);
      this.lastError.set(message);

      if (environment.allowMockFallback && error instanceof ApiError && error.isPlatformFailure) {
        this.origin.set('mock');
        return;
      }
      // A dead copy-trade manager is not "running", whatever it last reported.
      // Leaving the pill green while the process is gone is the one state this
      // panel must never show.
      this.status.update((s) => ({ ...s, running: false }));
      if (this.origin() === 'live') this.origin.set('stale');
    }
  }
}

/**
 * execute_copy_trade.py's /copy-trade/status body.
 *
 * snake_case as Python sends it, with the camelCase alternatives accepted too:
 * the Java CopyTradeController re-serialises some of these through a DTO and
 * some straight through, so both spellings genuinely arrive.
 */
interface CopyTradeStatusWire {
  running?: boolean;
  open_tracked_positions?: number;
  openTrackedPositions?: number;
  open_positions?: Record<string, number>;
  openPositions?: Record<string, number>;
  webhook_closed_tickets?: number;
  webhookClosedTickets?: number;
  position_cache_size?: number;
  positionCacheSize?: number;
  price_update_interval?: number;
  priceUpdateInterval?: number;
  firebase_connected?: boolean;
  firebaseConnected?: boolean;
  stats?: {
    start_time?: number | string;
    trades_registered?: number;
    trades_closed?: number;
    firebase_saves?: number;
    firebase_errors?: number;
    webhook_closes?: number;
    trailing_updates?: number;
    price_updates?: number;
    monitor_errors?: number;
  };
}

/** Accepts epoch seconds, epoch millis or an ISO string. */
function parseStart(value: number | string | undefined): number | null {
  if (value === undefined || value === null) return null;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null;
    return value < 1e12 ? value * 1000 : value;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}
