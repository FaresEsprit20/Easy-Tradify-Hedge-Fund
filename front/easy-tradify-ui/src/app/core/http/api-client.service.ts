import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, of, tap, throwError, timeout } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiError, ApiFailureKind } from './api-error';
import { BackendHealthService } from './backend-health.service';

/** Query values as callers naturally have them. */
export type QueryParams = Record<string, string | number | boolean | undefined | null>;

/**
 * The single door to the Spring gateway.
 *
 * Every service route is `/api/v1/<service>/...` on port 8080, and no call in
 * the app builds a URL any other way — that is what makes the dev proxy, the
 * timeout, the degraded-mode bookkeeping and the error normalisation apply
 * uniformly instead of being reimplemented six times with six different
 * behaviours on failure.
 *
 * WHAT THIS DELIBERATELY DOES NOT DO
 * ----------------------------------
 * It does not retry. The gateway already retries idempotent GETs (see its
 * `default-filters`), and retrying here would multiply that; more to the point,
 * a POST to /execution/trade must never be replayed by a client that got bored
 * waiting. Callers that want a retry ask for one explicitly.
 */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);
  private readonly health = inject(BackendHealthService);

  get<T>(service: string, path: string, params?: QueryParams): Observable<T> {
    return this.request<T>('GET', service, path, undefined, params);
  }

  post<T>(service: string, path: string, body?: unknown, params?: QueryParams): Observable<T> {
    return this.request<T>('POST', service, path, body, params);
  }

  put<T>(service: string, path: string, body?: unknown, params?: QueryParams): Observable<T> {
    return this.request<T>('PUT', service, path, body, params);
  }

  delete<T>(service: string, path: string, params?: QueryParams): Observable<T> {
    return this.request<T>('DELETE', service, path, undefined, params);
  }

  /**
   * Run a call that must not take the screen down with it.
   *
   * Returns `fallback` on failure and reports the origin, so the caller can
   * label the panel `mock` rather than silently presenting invented numbers as
   * measured ones. In production `allowMockFallback` is false and the error is
   * rethrown instead — a fabricated account balance on a live trading screen is
   * worse than an error state.
   */
  withFallback<T>(source: Observable<T>, fallback: () => T): Observable<T> {
    return source.pipe(
      catchError((error: ApiError) => {
        if (!environment.allowMockFallback || !error.isPlatformFailure) {
          return throwError(() => error);
        }
        return of(fallback());
      }),
    );
  }

  // ------------------------------------------------------------

  private request<T>(
    method: string,
    service: string,
    path: string,
    body?: unknown,
    params?: QueryParams,
  ): Observable<T> {
    const url = `${environment.apiBaseUrl}/api/v1/${service}${path}`;

    return this.http
      .request<T>(method, url, { body, params: toHttpParams(params) })
      .pipe(
        timeout(environment.requestTimeoutMs),
        tap(() => this.health.recordSuccess(service)),
        catchError((raw: unknown) => {
          const error = normalise(raw, url);
          this.health.recordFailure(service, error);
          return throwError(() => error);
        }),
      );
  }
}

function toHttpParams(params?: QueryParams): HttpParams | undefined {
  if (!params) return undefined;
  let out = new HttpParams();
  for (const [key, value] of Object.entries(params)) {
    // Undefined and null mean "not supplied". Serialising them produces the
    // literal strings "undefined"/"null", which Spring binds as a real value
    // and then rejects with a 400 that is very hard to read back.
    if (value === undefined || value === null) continue;
    out = out.set(key, String(value));
  }
  return out;
}

/** Collapse every failure shape into one ApiError. */
function normalise(raw: unknown, url: string): ApiError {
  if (raw instanceof ApiError) return raw;

  // rxjs timeout() throws a TimeoutError, not an HttpErrorResponse.
  if (raw instanceof Error && raw.name === 'TimeoutError') {
    return new ApiError(
      'timeout',
      `No response within ${environment.requestTimeoutMs / 1000}s`,
      0,
      url,
    );
  }

  if (raw instanceof HttpErrorResponse) {
    // status 0 is the browser refusing to say more: connection refused, DNS,
    // offline, or a CORS rejection. All of them mean "nothing answered".
    if (raw.status === 0) {
      return new ApiError('unreachable', 'Gateway unreachable on :8080', 0, url, raw.error);
    }

    const kind: ApiFailureKind =
      // 503 from the gateway specifically means Eureka has no live instance
      // for that route — the gateway is up, the service behind it is not.
      raw.status === 503 ? 'no-instance' : raw.status >= 500 ? 'server-error' : 'rejected';

    return new ApiError(kind, messageFrom(raw), raw.status, url, raw.error);
  }

  return new ApiError('server-error', String(raw), 0, url, raw);
}

/**
 * Pull the most specific message available.
 *
 * Three body shapes reach here: Spring's `GlobalExceptionHandler`
 * (`{message}`), Spring Boot's default error body (`{error, message}`), and a
 * Python service's own JSON forwarded by the proxying Java service
 * (`{error}` or `{detail}`). Preferring the innermost message is what keeps a
 * real cause like "MT5 not connected" from being replaced by "500 Internal
 * Server Error" on its way to the screen.
 */
function messageFrom(response: HttpErrorResponse): string {
  const body = response.error as Record<string, unknown> | string | null;

  if (typeof body === 'string' && body.trim()) return body;

  if (body && typeof body === 'object') {
    for (const key of ['message', 'error', 'detail', 'reason'] as const) {
      const value = body[key];
      if (typeof value === 'string' && value.trim()) return value;
    }
  }

  return response.message || `HTTP ${response.status}`;
}
