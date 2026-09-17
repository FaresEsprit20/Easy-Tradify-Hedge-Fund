/**
 * Production configuration.
 *
 * `apiBaseUrl` is empty on purpose: in production the built bundle is served
 * from the same origin as the gateway, so every request is a relative path and
 * there is no CORS exchange and no hostname baked into the artefact. Setting an
 * absolute URL here is how a build ends up pinned to one developer's machine.
 */
export const environment = {
  production: true,

  /** Relative — same-origin. See note above. */
  apiBaseUrl: '',

  /**
   * When true the API services fall back to their mock generators if the
   * gateway cannot be reached, so the UI stays demonstrable. Off in production:
   * fabricated positions and account balances must never be mistaken for real
   * ones on a live screen.
   */
  allowMockFallback: false,

  /** Per-request ceiling. The AI research endpoints are the slow ones. */
  requestTimeoutMs: 60_000,

  /**
   * reCAPTCHA v3, matching the auth service's `security.recaptcha.enabled`.
   *
   * The SITE key is public by design — it is embedded in the page and
   * identifies which site is asking. The SECRET key is what verifies a token
   * and never leaves the auth service; if one ever appears in this file, it has
   * been leaked and must be rotated at Google.
   */
  recaptcha: {
    enabled: true,
    siteKey: '',
  },

  /** How often the live polls refresh, in milliseconds. */
  pollIntervalMs: {
    monitorStatus: 5_000,
    positions: 3_000,
    account: 10_000,
    portfolio: 15_000,
  },
} as const;
