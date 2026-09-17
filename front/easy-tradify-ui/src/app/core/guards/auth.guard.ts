import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

/**
 * Gate for every route inside the shell.
 *
 * Asks the BACKEND, not local storage. A stored token proves only that this
 * browser once had a session — it says nothing about whether that session is
 * still valid, and the tokens here are opaque and revocable server-side, so a
 * signed-out or locked account must stop working immediately rather than
 * whenever a signature would have expired.
 *
 * The redirect carries `returnUrl` so a user who deep-links into a position
 * lands back on it after signing in, instead of being dumped on the dashboard.
 */
export const authGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  // Trust the in-memory user only for navigations after the first: it is set
  // by restoreSession(), which did ask the backend.
  if (auth.isAuthenticated()) return true;

  const restored = await auth.restoreSession();
  if (restored) return true;

  return router.createUrlTree(['/auth/login'], {
    queryParams: state.url && state.url !== '/' ? { returnUrl: state.url } : {},
  });
};

/**
 * The inverse, for the auth screens themselves.
 *
 * Without it, a signed-in user following a bookmarked /auth/login sees a
 * sign-in form and reasonably concludes they have been logged out.
 */
export const guestGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (auth.isAuthenticated()) return router.createUrlTree(['/']);
  return true;
};
