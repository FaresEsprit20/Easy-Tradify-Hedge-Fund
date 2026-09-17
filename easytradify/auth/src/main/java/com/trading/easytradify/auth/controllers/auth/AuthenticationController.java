package com.trading.easytradify.auth.controllers.auth;

import com.trading.easytradify.auth.dto.two_factor.TwoFactorLoginVerifyRequestDto;
import com.trading.easytradify.common.dto.auth.AuthCheckResponse;
import com.trading.easytradify.common.dto.auth.AuthenticationRequest;
import com.trading.easytradify.common.dto.auth.AuthenticationResponse;
import com.trading.easytradify.auth.services.auth.AuthenticationService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@Slf4j
@RestController
@RequiredArgsConstructor
public class AuthenticationController implements AuthenticationApi {

    private final AuthenticationService authenticationService;

    @Value("${server.port:8082}")
    private int serverPort;

    @Override
    public ResponseEntity<AuthenticationResponse> authenticate(
            @Valid @RequestBody AuthenticationRequest request,
            HttpServletRequest httpRequest,
            HttpServletResponse response) {

        log.info("📝 Authentication attempt - login: {}", request.getLogin());

        String login = request.getLogin();
        String credential = request.getPassword();

        // Route based on login type
        if ("token".equalsIgnoreCase(login)) {
            AuthenticationResponse authResponse = authenticationService.authenticateWithToken(credential, httpRequest);
            log.info("✅ Token authentication successful");
            return ResponseEntity.ok(authResponse);
        } else if ("refresh".equalsIgnoreCase(login)) {
            AuthenticationResponse authResponse = authenticationService.refreshAccessToken(credential, httpRequest);
            log.info("✅ Token refreshed successfully");
            return ResponseEntity.ok(authResponse);
        } else {
            // Regular username/password login (keep this for backward compatibility)
            AuthenticationResponse authResponse = authenticationService.authenticate(request, httpRequest);
            log.info("✅ Username/password authentication successful");
            return ResponseEntity.ok(authResponse);
        }
    }

    @Override
    public ResponseEntity<AuthenticationResponse> verifyTwoFactor(
            @Valid @RequestBody TwoFactorLoginVerifyRequestDto request,
            HttpServletRequest httpRequest) {
        log.info("🔐 TOTP verification attempt");
        AuthenticationResponse authResponse = authenticationService.verifyTwoFactor(
                request.getMfaToken(), request.getCode(), httpRequest);
        return ResponseEntity.ok(authResponse);
    }

    @Override
    public ResponseEntity<Map<String, String>> getGoogleLoginUrl() {
        // Build the full URL dynamically
        String fullLoginUrl = "http://localhost:" + serverPort + "/oauth2/authorization/google";

        return ResponseEntity.ok(Map.of(
                "login_url", fullLoginUrl,
                "instruction", "Open this URL in your browser to login with Google"
        ));
    }

    @Override
    public ResponseEntity<AuthCheckResponse> checkAuthentication(Authentication authentication) {
        log.info("🔍 /check-auth called");

        if (authentication == null || !authentication.isAuthenticated()) {
            log.warn("❌ User NOT authenticated - returning false");
            return ResponseEntity.ok(new AuthCheckResponse(false, null, null));
        }

        String email = authentication.getName();
        log.info("✅ User IS authenticated: {}", email);

        AuthCheckResponse response = authenticationService.checkUserAuthentication(email);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<Void> refreshToken(HttpServletRequest request, HttpServletResponse response) {
        log.info("🔄 Refresh token request");
        try {
            authenticationService.refreshToken(request, response);
            return ResponseEntity.ok().build();
        } catch (Exception e) {
            log.error("❌ Refresh token failed: {}", e.getMessage());
            return ResponseEntity.status(401).build();
        }
    }
}