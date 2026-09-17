import { Injectable, computed, signal } from '@angular/core';
import { ApiError } from './api-error';

/** Which backend a panel's data came from. Rendered, never inferred. */
export type DataOrigin = 'live' | 'mock' | 'stale';

/**
 * Tracks whether the platform is answering, and which services are not.
 *
 * The point of this service is that the UI must never present fabricated data
 * as real. When a call falls back to a mock generator the panel is marked
 * `mock`; when a poll fails but a previous real answer is still on screen the
 * panel is marked `stale`. Both are visible states, because the failure mode
 * this project has already hit once is a number that looks like a measurement
 * and is not one.
 */
@Injectable({ providedIn: 'root' })
export class BackendHealthService {
  /** Services that have failed with a platform-level error, by gateway prefix. */
  private readonly down = signal<ReadonlySet<string>>(new Set());

  /** Last successful response from any service. Drives the liveness pulse. */
  readonly lastContactAt = signal<number | null>(null);

  /** Set once the gateway has answered anything at all. */
  readonly gatewayReachable = signal<boolean | null>(null);

  readonly downServices = computed(() => [...this.down()].sort());

  /** True when at least one service is unreachable. */
  readonly degraded = computed(() => this.down().size > 0 || this.gatewayReachable() === false);

  recordSuccess(service: string): void {
    this.lastContactAt.set(Date.now());
    this.gatewayReachable.set(true);
    if (this.down().has(service)) {
      const next = new Set(this.down());
      next.delete(service);
      this.down.set(next);
    }
  }

  recordFailure(service: string, error: ApiError): void {
    // Only platform failures mark a service down. A 400 or a 404 is a fact
    // about the request, and marking the service down for it would make the
    // whole screen cry wolf over one bad symbol.
    if (!error.isPlatformFailure) return;

    if (error.kind === 'unreachable') this.gatewayReachable.set(false);

    if (!this.down().has(service)) {
      const next = new Set(this.down());
      next.add(service);
      this.down.set(next);
    }
  }

  isDown(service: string): boolean {
    return this.down().has(service);
  }
}
