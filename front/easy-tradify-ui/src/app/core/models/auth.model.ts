/**
 * Auth wire shapes, typed from the auth service's own DTOs.
 *
 * Note the endpoint root is `easytradify/trading/tool/v1`, NOT `/api/v1/**`
 * like every other service here — the auth module was ported from a codebase
 * with its own path convention, and the gateway routes that root verbatim.
 */

export interface LoginRequest {
  /** Email address or username — the backend resolves either. */
  login: string;
  password: string;
}

/**
 * The result of a sign-in attempt — one of two mutually exclusive outcomes,
 * which is why everything is optional.
 *
 *  - **Signed in**: `accessToken` and `refreshToken` are set.
 *  - **Second factor needed**: `requiresTwoFactor` is true and `mfaToken`
 *    holds a short-lived ticket. That ticket is NOT a session — it only
 *    authorises a code submission and expires in minutes.
 */
export interface AuthTokens {
  accessToken?: string;
  refreshToken?: string;
  requiresTwoFactor?: boolean;
  mfaToken?: string;
  /** "TOTP" | "EMAIL" | "NONE" */
  twoFactorMethod?: string;
}

export interface TwoFactorVerifyRequest {
  mfaToken: string;
  code: string;
}

export interface AuthCheck {
  /**
   * The backend serialises this key twice — `isAuthenticated` (explicit
   * `@JsonProperty`) and `authenticated` (Lombok's boolean getter). Both are
   * declared so a rename on either side cannot quietly read as `undefined`,
   * which is falsy and would log a signed-in user out.
   */
  isAuthenticated?: boolean;
  authenticated?: boolean;
  email?: string;
  userId?: number;
}

export interface RegisterRequest {
  firstName: string;
  lastName: string;
  email: string;
  username?: string;
  numTel: string;
  /** ISO yyyy-MM-dd — the backend binds a LocalDate. */
  birthDate?: string;
  password: string;
}

/** The signed-in user, as the shell and guard care about them. */
export interface AuthUser {
  email: string;
  userId: number | null;
}
