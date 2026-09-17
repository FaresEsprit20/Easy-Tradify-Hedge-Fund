package com.trading.easytradify.auth.controllers.auth;

import com.trading.easytradify.auth.dto.two_factor.TwoFactorLoginVerifyRequestDto;
import com.trading.easytradify.common.dto.auth.AuthCheckResponse;
import com.trading.easytradify.common.dto.auth.AuthenticationRequest;
import com.trading.easytradify.common.dto.auth.AuthenticationResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import static com.trading.easytradify.common.utils.constants.Constants.APP_ROOT;

@Tag(name = "Authentication", description = "API for user authentication")
public interface AuthenticationApi {

    String AUTHENTICATION_ENDPOINT = APP_ROOT + "/auth";

    @Operation(summary = "Authenticate user",
            description = "Supports Google OAuth2: login='google', password='authorization_code' | " +
                    "Token validation: login='token', password='access_token' | " +
                    "Token refresh: login='refresh', password='refresh_token'")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Authentication successful"),
            @ApiResponse(responseCode = "401", description = "Unauthorized - Invalid credentials"),
            @ApiResponse(responseCode = "400", description = "Bad request - Invalid input"),
            @ApiResponse(responseCode = "403", description = "Forbidden - Account locked or disabled")
    })
    @PostMapping(AUTHENTICATION_ENDPOINT + "/authenticate")
    ResponseEntity<AuthenticationResponse> authenticate(
            @Valid @RequestBody AuthenticationRequest request,
            HttpServletRequest httpRequest,
            HttpServletResponse response);

    @Operation(summary = "Get Google OAuth2 login URL",
            description = "Returns the Google OAuth2 login URL to redirect users")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "URL returned successfully")
    })
    @GetMapping(AUTHENTICATION_ENDPOINT + "/google/login-url")
    ResponseEntity<?> getGoogleLoginUrl();

    @Operation(summary = "Verify a TOTP code to complete login",
            description = "Second step of login when the account has two-factor auth enabled")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Login completed successfully"),
            @ApiResponse(responseCode = "400", description = "Invalid or expired code/session")
    })
    @PostMapping(AUTHENTICATION_ENDPOINT + "/two-factor/verify")
    ResponseEntity<AuthenticationResponse> verifyTwoFactor(
            @Valid @RequestBody TwoFactorLoginVerifyRequestDto request,
            HttpServletRequest httpRequest);

    @Operation(summary = "Check authentication state",
            description = "Checks if the current user is authenticated")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Authentication state returned")
    })
    @GetMapping(AUTHENTICATION_ENDPOINT + "/check-auth")
    ResponseEntity<AuthCheckResponse> checkAuthentication(Authentication authentication);

    @Operation(summary = "Refresh token",
            description = "Refreshes the access token using refresh token")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Token refreshed successfully"),
            @ApiResponse(responseCode = "401", description = "Unauthorized - Invalid refresh token")
    })
    @PostMapping(AUTHENTICATION_ENDPOINT + "/refresh-token")
    ResponseEntity<Void> refreshToken(HttpServletRequest request, HttpServletResponse response);
}