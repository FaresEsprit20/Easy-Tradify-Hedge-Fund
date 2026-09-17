package com.trading.easytradify.auth.controllers.twofactor;

import com.trading.easytradify.auth.services.two_facor.TwoFactorAuthService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/internal/2fa")
@RequiredArgsConstructor
@Slf4j
public class InternalTwoFactorController {

    private final TwoFactorAuthService twoFactorAuthService;

    @Value("${internal.api.key}")
    private String internalApiKey;

    private void validateApiKey(String apiKey) {
        if (apiKey == null || !apiKey.equals(internalApiKey)) {
            log.warn("Invalid internal API key for 2FA");
            throw new SecurityException("Invalid API key");
        }
    }

    /**
     * Generate and send OTP
     * POST /internal/2fa/generate
     * Body: { "email": "user@example.com", "method": "EMAIL", "phoneNumber": "+21612345678" }
     */
    @PostMapping("/generate")
    public ResponseEntity<?> generateOtp(
            @RequestBody Map<String, String> request,
            @RequestHeader("X-API-Key") String apiKey) {

        validateApiKey(apiKey);

        String email = request.get("email");
        String method = request.get("method"); // "EMAIL" or "SMS"
        String phoneNumber = request.get("phoneNumber");

        String verificationToken = twoFactorAuthService.generateAndSendOtp(email);

        return ResponseEntity.ok(Map.of(
                "verificationToken", verificationToken,
                "success", true
        ));
    }

    /**
     * Verify OTP
     * POST /internal/2fa/verify
     * Body: { "verificationToken": "xxx", "otpCode": "123456" }
     */
    @PostMapping("/verify")
    public ResponseEntity<?> verifyOtp(
            @RequestBody Map<String, String> request,
            @RequestHeader("X-API-Key") String apiKey) {

        validateApiKey(apiKey);

        String verificationToken = request.get("verificationToken");
        String otpCode = request.get("otpCode");

        boolean verified = twoFactorAuthService.verifyOtp(verificationToken, otpCode);

        return ResponseEntity.ok(Map.of(
                "verified", verified,
                "success", true
        ));
    }

    /**
     * Resend OTP
     * POST /internal/2fa/resend
     * Body: { "email": "user@example.com", "method": "EMAIL", "phoneNumber": "+21612345678" }
     */
    @PostMapping("/resend")
    public ResponseEntity<?> resendOtp(
            @RequestBody Map<String, String> request,
            @RequestHeader("X-API-Key") String apiKey) {

        validateApiKey(apiKey);

        String email = request.get("email");
        String method = request.get("method");
        String phoneNumber = request.get("phoneNumber");

        String verificationToken = twoFactorAuthService.resendOtp(email);

        return ResponseEntity.ok(Map.of(
                "verificationToken", verificationToken,
                "success", true
        ));
    }

    /**
     * Get user email by verification token
     * GET /internal/2fa/user/{verificationToken}
     */
    @GetMapping("/user/{verificationToken}")
    public ResponseEntity<?> getUserEmail(
            @PathVariable String verificationToken,
            @RequestHeader("X-API-Key") String apiKey) {

        validateApiKey(apiKey);

        String email = twoFactorAuthService.getUserEmailByVerificationToken(verificationToken);

        return ResponseEntity.ok(Map.of(
                "email", email,
                "success", true
        ));
    }
}