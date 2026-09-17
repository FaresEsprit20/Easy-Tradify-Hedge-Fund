import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { from, switchMap } from 'rxjs';
import { RecaptchaService, recaptchaActionFor, requiresRecaptcha } from './recaptcha.service';

/**
 * Attaches `X-Recaptcha-Token` to the auth requests that require one.
 *
 * <h3>Why an interceptor rather than each caller</h3>
 * The token has to be minted immediately before the request — it is single-use
 * and expires in about two minutes — so it cannot be fetched when a form loads
 * and held until submit. Doing it here means the mint happens at send time by
 * construction, and no sign-in path can forget it.
 *
 * <h3>Only the protected endpoints pay for it</h3>
 * `requiresRecaptcha` narrows this to the unauthenticated routes the backend
 * guards. Minting on every request would add a network round trip to ordinary
 * calls and hand Google a record of the user's whole session.
 */
export const recaptchaInterceptor: HttpInterceptorFn = (req, next) => {
  const recaptcha = inject(RecaptchaService);

  if (!recaptcha.enabled || !requiresRecaptcha(req.url, req.method)) {
    return next(req);
  }

  return from(recaptcha.getToken(recaptchaActionFor(req.url))).pipe(
    switchMap((token) => {
      // No token: send the request anyway. The backend answers 400 with a
      // message naming the problem, which is a better diagnostic than a
      // request that never left the browser.
      if (!token) return next(req);

      return next(req.clone({ setHeaders: { 'X-Recaptcha-Token': token } }));
    }),
  );
};
