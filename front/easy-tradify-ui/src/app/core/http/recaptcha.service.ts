import { Injectable, signal } from '@angular/core';
import { environment } from '../../../environments/environment';

/** The reCAPTCHA v3 API, as the script attaches it to `window`. */
interface GrecaptchaV3 {
  ready(callback: () => void): void;
  execute(siteKey: string, options: { action: string }): Promise<string>;
}

declare global {
  interface Window {
    grecaptcha?: GrecaptchaV3;
  }
}

/**
 * Mints reCAPTCHA v3 tokens for the auth endpoints that require one.
 *
 * <h3>Why the script is loaded on demand</h3>
 * Google's reCAPTCHA script watches the whole page and phones home
 * continuously once loaded. Putting it in `index.html` means every visitor to
 * every screen — a dashboard nobody is signing in from — is fingerprinted for
 * the lifetime of the tab. Loading it the first time a token is actually needed
 * keeps that to the sign-in and registration flows.
 *
 * <h3>Tokens are single-use and short-lived</h3>
 * A v3 token is valid for about two minutes and is consumed by the first
 * verification. So one is minted per request rather than cached — a cached
 * token produces a confusing "validation failed" on the second submission,
 * which reads like a wrong password.
 */
@Injectable({ providedIn: 'root' })
export class RecaptchaService {
  /** Set when the script cannot load, so the UI can explain the failure. */
  readonly unavailable = signal(false);

  private scriptPromise: Promise<void> | null = null;

  get enabled(): boolean {
    return environment.recaptcha.enabled && !!environment.recaptcha.siteKey;
  }

  /**
   * A fresh token for `action`, or null when reCAPTCHA is not configured.
   *
   * `action` must match what the backend scores against — it derives it from
   * the last path segment, so "authenticate" here corresponds to a POST to
   * .../auth/authenticate. A mismatch scores the token as suspicious rather
   * than failing loudly, which is the harder bug to spot.
   */
  async getToken(action: string): Promise<string | null> {
    if (!this.enabled) return null;

    try {
      await this.loadScript();

      const grecaptcha = window.grecaptcha;
      if (!grecaptcha) {
        this.unavailable.set(true);
        return null;
      }

      await new Promise<void>((resolve) => grecaptcha.ready(resolve));
      const token = await grecaptcha.execute(environment.recaptcha.siteKey, { action });

      this.unavailable.set(false);
      return token;
    } catch {
      // Returning null rather than throwing: the request still goes out, and
      // the backend rejects it with a message about the missing token. That is
      // a clearer failure than a client-side exception with no server record.
      this.unavailable.set(true);
      return null;
    }
  }

  /** Loads the script once; concurrent callers share the same promise. */
  private loadScript(): Promise<void> {
    if (this.scriptPromise) return this.scriptPromise;

    this.scriptPromise = new Promise<void>((resolve, reject) => {
      if (window.grecaptcha) {
        resolve();
        return;
      }

      const script = document.createElement('script');
      script.src = `https://www.google.com/recaptcha/api.js?render=${encodeURIComponent(
        environment.recaptcha.siteKey,
      )}`;
      script.async = true;
      script.defer = true;
      script.onload = () => resolve();
      script.onerror = () => {
        // Clear the cached promise so a later attempt can retry rather than
        // being permanently poisoned by one offline moment.
        this.scriptPromise = null;
        reject(new Error('Failed to load reCAPTCHA'));
      };
      document.head.appendChild(script);
    });

    return this.scriptPromise;
  }
}

/**
 * Paths that require a token, matched by suffix.
 *
 * Kept in step with RecaptchaFilter.PROTECTED_SUFFIXES on the Java side. The
 * two lists are duplicated across languages, which is a real maintenance
 * hazard: a path added to the backend and missed here produces a 400 on an
 * endpoint that worked yesterday. The backend is the authority — this list only
 * decides whether to spend a round trip minting a token.
 */
export const RECAPTCHA_PROTECTED_SUFFIXES: readonly string[] = [
  '/authenticate',
  '/two-factor/verify',
  '/user/create',
  '/admin/create',
  '/send-link',
  '/resend-link',
  '/reset',
];

/** The action name to score this request under — the last path segment. */
export function recaptchaActionFor(url: string): string {
  const path = url.split('?')[0];
  const segments = path.split('/').filter(Boolean);
  return segments.length ? segments[segments.length - 1] : 'generic';
}

export function requiresRecaptcha(url: string, method: string): boolean {
  if (method.toUpperCase() === 'GET') return false;
  const path = url.split('?')[0];
  return RECAPTCHA_PROTECTED_SUFFIXES.some((suffix) => path.endsWith(suffix));
}
