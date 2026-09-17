import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiError } from '../http/api-error';
import {
  AuthCheck,
  AuthTokens,
  AuthUser,
  LoginRequest,
  RegisterRequest,
} from '../models/auth.model';

/** Where the auth module's endpoints live. Not /api/v1 — see auth.model.ts. */
const AUTH_ROOT = '/easytradify/trading/tool/v1/auth';
const ACCOUNTS_ROOT = '/easytradify/trading/tool/v1/accounts/management';

/**
 * Session state and the calls that change it.
 *
 * <h3>Where the tokens live</h3>
 * The backend also sets them as httpOnly cookies, which is the stronger
 * channel — script on the page cannot read those, so an XSS flaw cannot
 * exfiltrate the session. They are mirrored into `sessionStorage` here only
 * because the OAuth2 redirect hands them back on the query string and the app
 * needs them across a full page load.
 *
 * `sessionStorage`, deliberately, not `localStorage`: the session dies with the
 * tab. On a shared machine a trading session that survives closing the browser
 * is a liability, and this app places real orders.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  private static readonly ACCESS_KEY = 'et.accessToken';
  private static readonly REFRESH_KEY = 'et.refreshToken';

  readonly user = signal<AuthUser | null>(null);
  readonly checking = signal(true);
  readonly lastError = signal<string | null>(null);

  readonly isAuthenticated = computed(() => this.user() !== null);

  /**
   * Set between a correct password and a correct 2FA code. Holding it in a
   * signal rather than storage is intentional — a refresh during this window
   * should send the user back to the password step, not resume a half-finished
   * login from a stale ticket.
   */
  readonly pendingMfa = signal<{ token: string; method: string } | null>(null);

  // ----------------------------------------------------------------

  get accessToken(): string | null {
    return safeRead(AuthService.ACCESS_KEY);
  }

  get refreshToken(): string | null {
    return safeRead(AuthService.REFRESH_KEY);
  }

  /**
   * Ask the backend whether this session is live.
   *
   * The cookies do the real work: even with empty sessionStorage the browser
   * sends them, so a reopened tab can still be signed in.
   */
  async restoreSession(): Promise<boolean> {
    this.checking.set(true);
    try {
      const check = await firstValueFrom(
        this.http.get<AuthCheck>(`${environment.apiBaseUrl}${AUTH_ROOT}/check-auth`, {
          withCredentials: true,
        }),
      );

      // Both spellings — see AuthCheck.
      const authenticated = check.isAuthenticated ?? check.authenticated ?? false;

      if (authenticated && check.email) {
        this.user.set({ email: check.email, userId: check.userId ?? null });
        return true;
      }

      this.clearSession();
      return false;
    } catch {
      // A failed check is not proof of being signed out — the service may be
      // down — but it is the only safe reading. Showing a dashboard to someone
      // whose session cannot be confirmed is the worse error.
      this.clearSession();
      return false;
    } finally {
      this.checking.set(false);
    }
  }

  /**
   * Sign in with a password.
   *
   * Returns `'mfa'` when the password was right but a second factor is needed;
   * the caller routes to the code prompt. It is NOT an error state.
   */
  async login(request: LoginRequest): Promise<'ok' | 'mfa'> {
    this.lastError.set(null);

    const tokens = await firstValueFrom(
      this.http.post<AuthTokens>(`${environment.apiBaseUrl}${AUTH_ROOT}/authenticate`, request, {
        withCredentials: true,
      }),
    );

    if (tokens.requiresTwoFactor && tokens.mfaToken) {
      this.pendingMfa.set({
        token: tokens.mfaToken,
        method: tokens.twoFactorMethod ?? 'TOTP',
      });
      return 'mfa';
    }

    this.storeTokens(tokens);
    await this.restoreSession();
    return 'ok';
  }

  /** Second step: exchange the ticket plus a code for a real session. */
  async verifyTwoFactor(code: string): Promise<void> {
    const pending = this.pendingMfa();
    if (!pending) throw new Error('No login in progress');

    const tokens = await firstValueFrom(
      this.http.post<AuthTokens>(
        `${environment.apiBaseUrl}${AUTH_ROOT}/two-factor/verify`,
        { mfaToken: pending.token, code },
        { withCredentials: true },
      ),
    );

    this.storeTokens(tokens);
    this.pendingMfa.set(null);
    await this.restoreSession();
  }

  async register(request: RegisterRequest): Promise<void> {
    await firstValueFrom(
      this.http.post(`${environment.apiBaseUrl}${ACCOUNTS_ROOT}/user/create`, request, {
        withCredentials: true,
      }),
    );
  }

  /**
   * Hand the browser to Google.
   *
   * A full navigation, not an XHR: the OAuth2 handshake redirects the BROWSER
   * through Google and back, and the backend owns `/oauth2/authorization/google`.
   * Fetching that URL would return Google's HTML into a promise nobody can use.
   */
  loginWithGoogle(): void {
    window.location.href = `${environment.apiBaseUrl}/oauth2/authorization/google`;
  }

  /** Called by the OAuth2 callback route with the tokens from the query string. */
  async completeOAuth2(accessToken: string | null, refreshToken: string | null): Promise<boolean> {
    if (accessToken) safeWrite(AuthService.ACCESS_KEY, accessToken);
    if (refreshToken) safeWrite(AuthService.REFRESH_KEY, refreshToken);
    return this.restoreSession();
  }

  async logout(): Promise<void> {
    try {
      await firstValueFrom(
        this.http.post(`${environment.apiBaseUrl}/logout`, {}, { withCredentials: true }),
      );
    } catch {
      // Clear locally regardless. A failed server call must never leave the
      // user looking signed in on a machine they are walking away from.
    }
    this.clearSession();
    void this.router.navigate(['/auth/login']);
  }

  /** Exchange the refresh token for a new access token. */
  async refresh(): Promise<boolean> {
    const token = this.refreshToken;
    if (!token) return false;

    try {
      const tokens = await firstValueFrom(
        this.http.post<AuthTokens>(
          `${environment.apiBaseUrl}${AUTH_ROOT}/authenticate`,
          // The backend overloads this endpoint: login "refresh" means the
          // password field carries a refresh token. Odd, but it is the
          // contract, and inventing a tidier one here would 404.
          { login: 'refresh', password: token },
          { withCredentials: true },
        ),
      );
      this.storeTokens(tokens);
      return !!tokens.accessToken;
    } catch {
      this.clearSession();
      return false;
    }
  }

  // ----------------------------------------------------------------

  private storeTokens(tokens: AuthTokens): void {
    if (tokens.accessToken) safeWrite(AuthService.ACCESS_KEY, tokens.accessToken);
    if (tokens.refreshToken) safeWrite(AuthService.REFRESH_KEY, tokens.refreshToken);
  }

  clearSession(): void {
    safeRemove(AuthService.ACCESS_KEY);
    safeRemove(AuthService.REFRESH_KEY);
    this.user.set(null);
    this.pendingMfa.set(null);
  }

  /** Turn a transport failure into something a form can display. */
  static describe(error: unknown): string {
    if (error instanceof ApiError) return error.message;

    const http = error as { status?: number; error?: { message?: string; error?: string } };
    const body = http?.error;

    if (body?.message) return body.message;
    if (body?.error) return body.error;

    switch (http?.status) {
      case 0:
        return 'Cannot reach the auth service.';
      case 400:
        return 'Bot check failed — reload the page and try again.';
      case 401:
        return 'Those credentials were not accepted.';
      case 403:
        return 'Bot check failed — reload the page and try again.';
      case 423:
        return 'This account is locked.';
      default:
        return 'Sign-in failed. Please try again.';
    }
  }
}

// sessionStorage throws outright in some privacy modes, so every access is
// guarded — a blocked storage API must not take the sign-in page down with it.
function safeRead(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeWrite(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* cookies remain the real channel */
  }
}

function safeRemove(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* nothing to do */
  }
}
