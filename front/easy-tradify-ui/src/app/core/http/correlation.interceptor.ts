import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { finalize, tap } from 'rxjs';
import { RequestLogService } from './request-log.service';

/**
 * Stamps every request with a correlation id and records it.
 *
 * WHY THE HEADER
 * --------------
 * A single click can cross four processes: Angular -> gateway -> a Java
 * service -> a Python controller. Without a shared id, correlating the Angular
 * failure with the line in `hybrid_monitor.log` means matching wall-clock
 * timestamps across machines, which is exactly the guesswork that made the
 * execution bugs so slow to pin down. `X-Correlation-Id` travels with the
 * request, and the Java services already log inbound headers.
 *
 * WHY IT ALSO LOGS LOCALLY
 * ------------------------
 * The requirement was to keep the platform's logs, and browser-side logs were
 * the ones being lost. RequestLogService keeps them addressable after the fact.
 */
export const correlationInterceptor: HttpInterceptorFn = (req, next) => {
  const log = inject(RequestLogService);
  const id = correlationId();

  // Path only: the log panel is narrow and the origin is identical on every row.
  const path = req.url.replace(/^.*\/api\/v1/, '');
  log.start(id, req.method, path);

  const stamped = req.clone({ setHeaders: { 'X-Correlation-Id': id } });

  let status = 0;
  let failure: string | undefined;

  return next(stamped).pipe(
    tap({
      next: (event) => {
        if ('status' in event && typeof event.status === 'number') status = event.status;
      },
      error: (err: unknown) => {
        const e = err as { status?: number; message?: string };
        status = e?.status ?? 0;
        failure = e?.message ?? 'request failed';
      },
    }),
    finalize(() => log.finish(id, status, failure)),
  );
};

function correlationId(): string {
  // randomUUID needs a secure context; plain http://localhost qualifies, but a
  // LAN address over http does not, and this must not throw there.
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
