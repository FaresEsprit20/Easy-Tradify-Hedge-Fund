import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiClient } from '../../http/api-client.service';
import { ApiError } from '../../http/api-error';
import { DataOrigin } from '../../http/backend-health.service';
import { SERVICE } from '../../http/services';
import { environment } from '../../../../environments/environment';
import {
  TradeFilterCatalog,
  TradeQueryRequest,
  TradeQuerySummary,
  TradeStats,
  TradeWire,
  TradesEnvelope,
  TradesPagination,
} from '../../models/api/trades-api.model';

/**
 * The MongoDB trade store, through /api/v1/trades/** on the gateway.
 *
 * This is the only service in the app with NO mock fallback whatsoever, and
 * that is deliberate. Everything else here renders a view of the market, which
 * a plausible sample can stand in for during design. This renders the RECORD —
 * what was actually traded, at what size, with what result. A fabricated trade
 * history is not a degraded view of the truth, it is a different document, and
 * the entire research layer downstream treats these rows as measurements.
 *
 * <h3>One query path</h3>
 * Every read goes through POST /query with a JSON body. The earlier GET-based
 * `list()` sent `limit`, `offset`, `since` and `until`, and neither the Java
 * nor the Python layer reads any of those names — every one of those filters
 * was silently ignored and the caller got the default page back.
 */
@Injectable({ providedIn: 'root' })
export class TradesApiService {
  private readonly api = inject(ApiClient);

  readonly trades = signal<readonly TradeWire[]>([]);
  readonly pagination = signal<TradesPagination | null>(null);

  /**
   * Win/loss figures over the WHOLE filtered set, overall and per leverage.
   * Not over the rows on screen — a win rate that changed every time the user
   * paged would say nothing about the filter.
   */
  readonly summary = signal<TradeQuerySummary | null>(null);

  /** The filters the server says it applied, normalised. Echo, don't assume. */
  readonly appliedFilters = signal<Partial<TradeQueryRequest>>({});

  readonly catalog = signal<TradeFilterCatalog | null>(null);
  readonly stats = signal<TradeStats | null>(null);
  readonly loading = signal(false);
  readonly lastError = signal<string | null>(null);

  /** Never 'mock' — see the class note. */
  readonly origin = signal<DataOrigin>('stale');

  /** The body of the last successful query, so paging can reuse the filters. */
  private lastRequest: TradeQueryRequest = {};

  readonly openTrades = computed(() => this.trades().filter((t) => t.status === 'OPEN'));
  readonly closedTrades = computed(() => this.trades().filter((t) => t.status === 'CLOSED'));

  /**
   * Rows whose recorded risk looks computed rather than measured.
   *
   * `actual_risk_usd` was written as `target_risk * volume` by a sizer that
   * threw away MT5's own figure, so a 0.34-lot position with a $4 budget was
   * stored as $1.36 of risk. Surfaced rather than corrected, because rewriting
   * stored history to match a new belief about it is how a record stops being
   * a record.
   */
  readonly suspectRiskRows = computed(() =>
    this.trades().filter((t) => {
      const risk = t.actual_risk_usd;
      const volume = t.volume ?? t.entry?.volume;
      if (risk == null || !volume) return false;
      return Math.abs(risk - 4.0 * volume) < 0.06;
    }),
  );

  // ------------------------------------------------------------------
  // QUERY
  // ------------------------------------------------------------------

  /**
   * Filter trades with a JSON body.
   *
   * The server rejects unknown fields with a 400, which surfaces here as a
   * thrown ApiError with the server's message — e.g. "unknown field(s)
   * ['levrage']". That is intended: a typo should fail loudly, not return every
   * trade unfiltered.
   */
  async query(request: TradeQueryRequest = {}): Promise<readonly TradeWire[]> {
    this.loading.set(true);
    try {
      const envelope = await firstValueFrom(
        this.api.post<TradesEnvelope<TradeWire[]>>(SERVICE.trades, '/query', request),
      );

      const rows = this.unwrap(envelope) ?? [];
      this.trades.set(rows);
      this.pagination.set(envelope.meta?.pagination ?? null);
      this.summary.set(envelope.meta?.summary ?? null);
      this.appliedFilters.set(envelope.meta?.appliedFilters ?? {});
      this.lastRequest = { ...request };

      this.origin.set('live');
      this.lastError.set(null);
      return rows;
    } catch (error) {
      this.fail(error);
      throw error;
    } finally {
      this.loading.set(false);
    }
  }

  /** Same filters, another page. */
  goToPage(page: number): Promise<readonly TradeWire[]> {
    return this.query({ ...this.lastRequest, page });
  }

  /** Closed trades, optionally narrowed — the common case, spelled out. */
  closed(request: Omit<TradeQueryRequest, 'status'> = {}): Promise<readonly TradeWire[]> {
    return this.query({ ...request, status: 'CLOSED' });
  }

  /** Closed winners. */
  winners(request: Omit<TradeQueryRequest, 'status' | 'outcome'> = {}): Promise<readonly TradeWire[]> {
    return this.query({ ...request, status: 'CLOSED', outcome: 'WIN' });
  }

  /** Every filter the server accepts, with the values that exist. Cached. */
  async loadCatalog(force = false): Promise<TradeFilterCatalog | null> {
    if (this.catalog() && !force) return this.catalog();
    try {
      const envelope = await firstValueFrom(
        this.api.get<TradesEnvelope<TradeFilterCatalog>>(SERVICE.trades, '/filters'),
      );
      const catalog = this.unwrap(envelope);
      this.catalog.set(catalog);
      this.origin.set('live');
      return catalog;
    } catch (error) {
      this.fail(error);
      return null;
    }
  }

  // ------------------------------------------------------------------
  // SINGLE TRADES & AGGREGATES
  // ------------------------------------------------------------------

  async get(tradeId: string): Promise<TradeWire | null> {
    try {
      const envelope = await firstValueFrom(
        this.api.get<TradesEnvelope<TradeWire>>(SERVICE.trades, `/${encodeURIComponent(tradeId)}`),
      );
      this.origin.set('live');
      return this.unwrap(envelope);
    } catch (error) {
      // A 404 is an answer, not a failure: the trade genuinely is not there.
      if (error instanceof ApiError && error.status === 404) return null;
      this.fail(error);
      throw error;
    }
  }

  async refreshStats(): Promise<TradeStats | null> {
    try {
      const envelope = await firstValueFrom(
        this.api.get<TradesEnvelope<TradeStats>>(SERVICE.trades, '/stats'),
      );
      const stats = this.unwrap(envelope);
      this.stats.set(stats);
      this.origin.set('live');
      return stats;
    } catch (error) {
      this.fail(error);
      return null;
    }
  }

  async statsBySymbol(): Promise<readonly Record<string, unknown>[]> {
    const envelope = await firstValueFrom(
      this.api.get<TradesEnvelope<Record<string, unknown>[]>>(SERVICE.trades, '/stats/by-symbol'),
    );
    return this.unwrap(envelope) ?? [];
  }

  async priceEvolution(tradeId: string): Promise<readonly Record<string, unknown>[]> {
    const envelope = await firstValueFrom(
      this.api.get<TradesEnvelope<Record<string, unknown>[]>>(
        SERVICE.trades,
        `/${encodeURIComponent(tradeId)}/price-evolution`,
      ),
    );
    return this.unwrap(envelope) ?? [];
  }

  /**
   * Ask the store to check its own contract — which stored rows are missing an
   * entry price, a stop or a direction. It is the check that turns "R is 0 for
   * two trades" into "those two rows never had an `entry` sub-document".
   */
  async selfCheck(): Promise<Record<string, unknown> | null> {
    const envelope = await firstValueFrom(
      this.api.post<TradesEnvelope<Record<string, unknown>>>(SERVICE.trades, '/diagnostics/self-check'),
    );
    return this.unwrap(envelope);
  }

  // ------------------------------------------------------------------

  /**
   * Unwrap the envelope, turning a reported failure into a thrown one.
   *
   * A failed query can arrive with HTTP 200. Without this it would read as an
   * empty result — "no trades match" instead of "the query failed", which is
   * the more misleading of the two by a wide margin.
   *
   * Reads `ok` (what Java emits) OR `success` (what Python emits), and treats
   * only an EXPLICIT false as failure: a response that simply lacks the flag
   * must not be mistaken for an error.
   */
  private unwrap<T>(envelope: TradesEnvelope<T> | null | undefined): T | null {
    if (!envelope) return null;

    const flag = envelope.ok ?? envelope.success;
    if (flag === false) {
      const error = envelope.error;
      throw new ApiError(
        'rejected',
        error?.message ?? 'Trades service reported a failure',
        200,
        '/api/v1/trades',
        error,
      );
    }
    return envelope.data ?? null;
  }

  private fail(error: unknown): void {
    this.lastError.set(error instanceof ApiError ? error.message : String(error));
    this.origin.set('stale');

    if (!environment.production) {
      // Loud in development: a trade-store failure that is only visible as an
      // empty table is the one this project has already lost time to.
      console.error('[trades] request failed', error);
    }
  }
}
