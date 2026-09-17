package com.trading.easytradify.auth.services.totp;

import org.apache.commons.codec.binary.Base32;
import org.springframework.stereotype.Service;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;

/**
 * RFC 6238 (TOTP) / RFC 4226 (HOTP) implementation — hand-rolled on top of
 * commons-codec's Base32 (already a dependency) rather than pulling in a
 * third-party TOTP library, so the whole primitive is auditable in one
 * place. Compatible with any standard authenticator app (Google
 * Authenticator, Authy, 1Password, etc.): 160-bit secret, HMAC-SHA1,
 * 30-second step, 6 digits — the universal defaults every app assumes when
 * an otpauth:// URI omits the algorithm/digits/period params.
 */
@Service
public class TotpService {

    private static final int SECRET_BYTES = 20;
    private static final int TIME_STEP_SECONDS = 30;
    private static final int CODE_DIGITS = 6;
    // Tolerates up to 1 step (30s) of clock drift between server and device
    // in either direction, which is standard practice for TOTP verifiers.
    private static final int ALLOWED_DRIFT_STEPS = 1;
    private static final String HMAC_ALGO = "HmacSHA1";
    /**
     * Shown in the user's authenticator app beside the code. Display text, so
     * it uses the product spelling; changing it re-labels existing entries the
     * next time a user re-enrols, but does not invalidate current secrets.
     */
    private static final String ISSUER = "Tunidex";

    private final SecureRandom secureRandom = new SecureRandom();
    private final Base32 base32 = new Base32();

    public String generateSecret() {
        byte[] bytes = new byte[SECRET_BYTES];
        secureRandom.nextBytes(bytes);
        return base32.encodeToString(bytes).replace("=", "");
    }

    public String buildOtpAuthUri(String secret, String accountEmail) {
        String label = URLEncoder.encode(ISSUER + ":" + accountEmail, StandardCharsets.UTF_8).replace("+", "%20");
        String encodedIssuer = URLEncoder.encode(ISSUER, StandardCharsets.UTF_8).replace("+", "%20");
        return "otpauth://totp/" + label
                + "?secret=" + secret
                + "&issuer=" + encodedIssuer
                + "&algorithm=SHA1&digits=" + CODE_DIGITS + "&period=" + TIME_STEP_SECONDS;
    }

    public boolean verifyCode(String base32Secret, String submittedCode) {
        if (base32Secret == null || submittedCode == null) {
            return false;
        }
        String normalized = submittedCode.trim();
        if (!normalized.matches("\\d{6}")) {
            return false;
        }

        long currentStep = System.currentTimeMillis() / 1000L / TIME_STEP_SECONDS;
        for (long drift = -ALLOWED_DRIFT_STEPS; drift <= ALLOWED_DRIFT_STEPS; drift++) {
            String candidate = generateCode(base32Secret, currentStep + drift);
            if (candidate != null && constantTimeEquals(candidate, normalized)) {
                return true;
            }
        }
        return false;
    }

    private String generateCode(String base32Secret, long timeStep) {
        try {
            byte[] key = base32.decode(base32Secret);

            byte[] counter = new byte[8];
            long value = timeStep;
            for (int i = 7; i >= 0; i--) {
                counter[i] = (byte) (value & 0xff);
                value >>= 8;
            }

            Mac mac = Mac.getInstance(HMAC_ALGO);
            mac.init(new SecretKeySpec(key, HMAC_ALGO));
            byte[] hash = mac.doFinal(counter);

            // RFC 4226 dynamic truncation.
            int offset = hash[hash.length - 1] & 0x0f;
            int binary = ((hash[offset] & 0x7f) << 24)
                    | ((hash[offset + 1] & 0xff) << 16)
                    | ((hash[offset + 2] & 0xff) << 8)
                    | (hash[offset + 3] & 0xff);

            int otp = (int) (binary % Math.pow(10, CODE_DIGITS));
            return String.format("%0" + CODE_DIGITS + "d", otp);
        } catch (Exception e) {
            return null;
        }
    }

    private boolean constantTimeEquals(String a, String b) {
        if (a.length() != b.length()) {
            return false;
        }
        int result = 0;
        for (int i = 0; i < a.length(); i++) {
            result |= a.charAt(i) ^ b.charAt(i);
        }
        return result == 0;
    }
}
