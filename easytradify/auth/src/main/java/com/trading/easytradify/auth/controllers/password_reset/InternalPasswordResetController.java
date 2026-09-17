package com.trading.easytradify.auth.controllers.password_reset;

import com.trading.easytradify.auth.dto.password_reset.TokenVerificationResponse;
import com.trading.easytradify.auth.services.password_reset.PasswordResetService;
import com.trading.easytradify.common.dto.auth.ChangePasswordUserRequestDto;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/internal/password-reset")
@RequiredArgsConstructor
@Slf4j
public class InternalPasswordResetController {

    private final PasswordResetService passwordResetService;

    @Value("${internal.api.key}")
    private String internalApiKey;

    private void validateApiKey(String apiKey) {
        if (apiKey == null || !apiKey.equals(internalApiKey)) {
            log.warn("Invalid internal API key for password reset");
            throw new SecurityException("Invalid API key");
        }
    }

    /**
     * Send password reset link
     * POST /internal/password-reset/send-link
     * Body: { "email": "user@example.com", "recaptchaToken": "xxx", "userIp": "127.0.0.1", "action": "reset" }
     */
    @PostMapping("/send-link")
    public ResponseEntity<?> sendResetLink(
            @RequestBody Map<String, String> request,
            @RequestHeader("X-API-Key") String apiKey) {

        validateApiKey(apiKey);

        String email = request.get("email");
        String recaptchaToken = request.get("recaptchaToken");
        String userIp = request.get("userIp");
        String action = request.get("action");

        passwordResetService.sendResetLink(email, recaptchaToken, userIp, action);

        return ResponseEntity.ok().body(Map.of(
                "success", true,
                "message", "Reset link sent to " + email
        ));
    }

    /**
     * Reset password using token
     * POST /internal/password-reset/reset
     * Body: { "token": "xxx", "password": "newPassword", "confirmPassword": "newPassword" }
     */
    @PostMapping("/reset")
    public ResponseEntity<?> resetPassword(
            @RequestBody Map<String, String> request,
            @RequestHeader("X-API-Key") String apiKey) {

        validateApiKey(apiKey);

        String token = request.get("token");
        String password = request.get("password");
        String confirmPassword = request.get("confirmPassword");

        if (!password.equals(confirmPassword)) {
            return ResponseEntity.badRequest().body(Map.of(
                    "success", false,
                    "error", "Passwords do not match"
            ));
        }

        ChangePasswordUserRequestDto changePasswordDto = new ChangePasswordUserRequestDto();
        changePasswordDto.setToken(token);
        changePasswordDto.setId(11);
        changePasswordDto.setPassword(password);
        changePasswordDto.setConfirmPassword(confirmPassword);

        boolean success = passwordResetService.resetPassword(token, changePasswordDto);

        return ResponseEntity.ok().body(Map.of(
                "success", success,
                "message", "Password reset successfully"
        ));
    }

    /**
     * Resend reset link
     * POST /internal/password-reset/resend-link
     * Body: { "email": "user@example.com", "recaptchaToken": "xxx", "userIp": "127.0.0.1", "action": "reset" }
     */
    @PostMapping("/resend-link")
    public ResponseEntity<?> resendResetLink(
            @RequestBody Map<String, String> request,
            @RequestHeader("X-API-Key") String apiKey) {

        validateApiKey(apiKey);

        String email = request.get("email");
        String recaptchaToken = request.get("recaptchaToken");
        String userIp = request.get("userIp");
        String action = request.get("action");

        boolean success = passwordResetService.resendResetLink(email, recaptchaToken, userIp, action);

        return ResponseEntity.ok().body(Map.of(
                "success", success,
                "message", "Reset link resent to " + email
        ));
    }

    /**
     * Verify reset token
     * GET /internal/password-reset/verify/{token}
     */
    @GetMapping("/verify/{token}")
    public ResponseEntity<TokenVerificationResponse> verifyToken(
            @PathVariable String token,
            @RequestHeader("X-API-Key") String apiKey) {

        validateApiKey(apiKey);

        TokenVerificationResponse response = passwordResetService.verifyToken(token);

        return ResponseEntity.ok(response);
    }

}