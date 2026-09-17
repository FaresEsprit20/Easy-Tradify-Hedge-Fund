package com.trading.easytradify.common.dto.auth;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * The result of a sign-in attempt.
 *
 * <p>
 * Carries one of two mutually exclusive outcomes, which is why every field is
 * nullable and omitted when empty:
 * </p>
 * <ul>
 *   <li><b>Signed in</b> — {@code accessToken} and {@code refreshToken} are set.</li>
 *   <li><b>Second factor required</b> — {@code requiresTwoFactor} is true and
 *       {@code mfaToken} holds a short-lived ticket proving the password was
 *       correct. That ticket is NOT a session: it only authorises a code
 *       submission, and expires in minutes.</li>
 * </ul>
 *
 * <p>
 * The tokens are opaque, not JWTs — they are looked up in {@code unified_tokens}
 * on every request, which is what makes revocation immediate rather than
 * "immediate once the signature expires".
 * </p>
 */
@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AuthenticationResponse {

    private String accessToken;
    private String refreshToken;

    /** True when the password was right but a second factor is still needed. */
    private Boolean requiresTwoFactor;

    /** Short-lived ticket authorising a two-factor code submission. */
    private String mfaToken;

    /** Which factor to prompt for — see TwoFactorMethod. */
    private String twoFactorMethod;
}
