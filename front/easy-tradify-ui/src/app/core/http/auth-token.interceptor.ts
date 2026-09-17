import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, from, switchMap, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';

/**
 * Sends credentials with every request, and refreshes once on a 401.
 *
 * <h3>withCredentials is the important half</h3>
 * The session's real carrier is a pair of httpOnly cookies, which the browser
 * only attaches when this flag is set. The `Authorization` header below is a
 * fallback for the window right after an OAuth2 redirect, where the tokens
 * arrived on the query string.
 *
 * <h3>Why the refresh is guarded</h3>
 * A 401 on the refresh call itself must not trigger another refresh — that is
 * an infinite loop that hammers the auth service while the user sees a hung
 * page. The endpoint is excluded explicitly.
 */
export const authTokenInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);

  const isAuthCall = req.url.includes('/auth/authenticate') || req.url.includes('/auth/check-auth');
  const token = auth.accessToken;

  const authorised = req.clone({
    withCredentials: true,
    setHeaders: token && !isAuthCall ? { Authorization: `Bearer ${token}` } : {},
  });

  return next(authorised).pipe(
    catchError((error: unknown) => {
      const is401 = error instanceof HttpErrorResponse && error.status === 401;

      if (!is401 || isAuthCall || !auth.refreshToken) {
        return throwError(() => error);
      }

      return from(auth.refresh()).pipe(
        switchMap((refreshed) => {
          if (!refreshed) return throwError(() => error);

          const retryToken = auth.accessToken;
          return next(
            req.clone({
              withCredentials: true,
              setHeaders: retryToken ? { Authorization: `Bearer ${retryToken}` } : {},
            }),
          );
        }),
      );
    }),
  );
};
