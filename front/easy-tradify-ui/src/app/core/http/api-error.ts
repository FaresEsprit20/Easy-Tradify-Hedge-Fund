/**
 * A backend failure, normalised.
 *
 * The gateway can fail in ways that look nothing alike — a Netty connection
 * refusal, a 503 from the load balancer when no instance is registered, a
 * Spring `GlobalExceptionHandler` body, or a Python traceback forwarded
 * verbatim by one of the proxy services. Panels need one shape to render, and
 * more importantly they need to distinguish "the platform is down" from "this
 * particular call was rejected": the first should degrade the whole screen, the
 * second should mark one panel.
 */
export type ApiFailureKind =
  /** No response at all — gateway down, DNS, connection refused, offline. */
  | 'unreachable'
  /** Reached the gateway; no instance was registered to serve the route. */
  | 'no-instance'
  /** The request was understood and refused (4xx). */
  | 'rejected'
  /** The service errored while handling it (5xx). */
  | 'server-error'
  /** Exceeded environment.requestTimeoutMs. */
  | 'timeout'
  /** Cancelled by the caller. */
  | 'cancelled';

export class ApiError extends Error {
  constructor(
    readonly kind: ApiFailureKind,
    override readonly message: string,
    readonly status: number,
    readonly path: string,
    /** The raw body, when there was one — kept for the terminal/log panels. */
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /**
   * True when the failure says something about the PLATFORM rather than about
   * this request. Only these should flip the app into degraded mode; a 404 on
   * one symbol means that symbol is unknown, not that the backend is gone.
   */
  get isPlatformFailure(): boolean {
    return this.kind === 'unreachable' || this.kind === 'no-instance';
  }

  /** Retrying an unreachable or timed-out call can succeed; a 400 cannot. */
  get isRetryable(): boolean {
    return this.kind === 'unreachable' || this.kind === 'timeout' || this.kind === 'no-instance';
  }
}
