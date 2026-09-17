import { Injectable, computed, inject, signal } from '@angular/core';
import { ConnectionState } from '../models/connection.model';
import { BackendHealthService } from '../http/backend-health.service';
import { SERVICE_LABELS, ServiceName } from '../http/services';

/**
 * The app's live-data connection state, as every panel reads it.
 *
 * WHAT CHANGED WHEN THE BACKEND WENT LIVE
 * ---------------------------------------
 * This used to be a manual toggle so the mock stream could be paused and the
 * "going stale" behaviour demonstrated. That toggle is still here — it is how
 * the degraded states get exercised without stopping a service — but the state
 * is now DERIVED: if any real service is failing, the app is disconnected
 * whatever the toggle says. A screen that reports itself live while the gateway
 * is refusing connections is the exact failure this signal exists to prevent,
 * so a manual "connected" can never override an actual outage.
 */
@Injectable({ providedIn: 'root' })
export class ConnectionService {
  private readonly health = inject(BackendHealthService);

  /** The manual override used for demonstrating stale states. */
  private readonly forcedDisconnect = signal(false);

  readonly connectionState = computed<ConnectionState>(() => {
    if (this.forcedDisconnect()) return 'disconnected';
    return this.health.degraded() ? 'disconnected' : 'live';
  });

  /** Human-readable names of the services currently failing. */
  readonly downServiceLabels = computed(() =>
    this.health
      .downServices()
      .map((name) => SERVICE_LABELS[name as ServiceName] ?? name),
  );

  /** When the platform last answered anything. Drives the liveness pulse. */
  readonly lastContactAt = this.health.lastContactAt.asReadonly();

  setDisconnected(disconnected: boolean): void {
    this.forcedDisconnect.set(disconnected);
  }

  toggle(): void {
    this.forcedDisconnect.update((v) => !v);
  }
}
