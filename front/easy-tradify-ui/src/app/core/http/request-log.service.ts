import { Injectable, computed, signal } from '@angular/core';
import { ActivityLogEntry } from '../models/activity.model';

/** One backend call, start to finish. */
export interface RequestRecord {
  id: string;
  method: string;
  /** Path only — the base URL is noise repeated on every row. */
  path: string;
  startedAt: number;
  durationMs: number | null;
  status: number | null;
  outcome: 'pending' | 'ok' | 'error';
  error?: string;
}

/**
 * A rolling record of every call the UI makes to the gateway.
 *
 * This exists because the platform's logs live in three places — the Angular
 * console, the Java service logs and the Python `hybrid_monitor.log` — and
 * until now the first of those vanished on refresh. The terminal and activity
 * panels render this, so "the screen showed no positions at 17:06" can be
 * traced to the actual call that failed rather than reconstructed from memory.
 *
 * Bounded on purpose: an unbounded array behind a dashboard left open all day
 * is a slow leak, and nothing reads past the most recent few hundred entries.
 */
@Injectable({ providedIn: 'root' })
export class RequestLogService {
  private static readonly MAX_ENTRIES = 300;

  private readonly records = signal<readonly RequestRecord[]>([]);

  /** Newest first. */
  readonly entries = this.records.asReadonly();

  readonly inFlight = computed(() => this.records().filter((r) => r.outcome === 'pending').length);

  readonly failureCount = computed(() => this.records().filter((r) => r.outcome === 'error').length);

  /** Adapter for the existing activity-log panel, which predates this service. */
  readonly asActivityLog = computed<readonly ActivityLogEntry[]>(() =>
    this.records()
      .filter((r) => r.outcome !== 'pending')
      .map((r) => ({
        id: r.id,
        timestamp: r.startedAt,
        level: r.outcome === 'error' ? ('error' as const) : ('info' as const),
        message:
          r.outcome === 'error'
            ? `${r.method} ${r.path} — ${r.error ?? 'failed'}`
            : `${r.method} ${r.path} — ${r.status} in ${r.durationMs}ms`,
      })),
  );

  start(id: string, method: string, path: string): void {
    const record: RequestRecord = {
      id,
      method,
      path,
      startedAt: Date.now(),
      durationMs: null,
      status: null,
      outcome: 'pending',
    };
    this.records.update((list) => [record, ...list].slice(0, RequestLogService.MAX_ENTRIES));
  }

  finish(id: string, status: number, error?: string): void {
    this.records.update((list) =>
      list.map((r) =>
        r.id === id
          ? {
              ...r,
              status,
              durationMs: Date.now() - r.startedAt,
              outcome: error ? ('error' as const) : ('ok' as const),
              error,
            }
          : r,
      ),
    );
  }

  clear(): void {
    this.records.set([]);
  }
}
