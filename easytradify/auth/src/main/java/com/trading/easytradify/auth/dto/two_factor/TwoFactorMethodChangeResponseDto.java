package com.trading.easytradify.auth.dto.two_factor;

import com.trading.easytradify.common.entities.enums.TwoFactorMethod;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * What the client needs to complete a method switch.
 *
 * <p>The shape differs by method, which is why the fields are nullable rather
 * than split into two responses: switching to the authenticator app needs a
 * secret and a QR code to scan, while switching to email needs nothing shown -
 * the code is already on its way to the inbox.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TwoFactorMethodChangeResponseDto {

    /** The method awaiting confirmation. Nothing has changed yet. */
    private TwoFactorMethod pendingMethod;

    /** Base32 secret, for TOTP only. Null when switching to email. */
    private String secret;

    /** otpauth:// URI to render as a QR code, for TOTP only. */
    private String otpAuthUri;

    /**
     * Whether the code actually went out, for email only.
     *
     * <p>Reported rather than assumed: the mailing service is a separate
     * process and may be down. A client that showed "check your inbox"
     * regardless would leave the user waiting for a message that was never
     * sent.
     */
    private boolean codeDelivered;

    /** Why delivery failed, when it did, so the UI can say something useful. */
    private String message;
}
