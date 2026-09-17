/**
 * Development configuration.
 *
 * `apiBaseUrl` stays empty here too — `proxy.conf.json` forwards /api/** to the
 * gateway on :8080, which keeps the browser on one origin. Pointing straight at
 * http://localhost:8080 also works (the gateway allows the 4200 origin), but
 * then every request is preflighted and a cookie-bearing call needs
 * credentialed CORS. The proxy avoids that whole class of problem.
 */
export const environment = {
  production: false,

  apiBaseUrl: '',

  /**
   * On in development: the Python services and MT5 are frequently not running
   * while front-end work happens, and a dead backend should degrade the screen
   * to sample data rather than to a wall of red. Every mocked value is labelled
   * as such in the UI — see ConnectionService.degraded.
   */
  allowMockFallback: true,

  requestTimeoutMs: 60_000,

  /**
   * reCAPTCHA v3.
   *
   * Off by default in development: with no site key the browser cannot mint a
   * token, and the auth service -- which fails CLOSED -- would reject every
   * sign-in attempt. Set a site key and flip this to true to exercise the real
   * flow locally.
   *
   * Only the public SITE key belongs here. The secret stays in the auth
   * service's .env.
   */
  recaptcha: {
    enabled: false,
    siteKey: '',
  },

  pollIntervalMs: {
    monitorStatus: 5_000,
    positions: 3_000,
    account: 10_000,
    portfolio: 15_000,
  },
} as const;
