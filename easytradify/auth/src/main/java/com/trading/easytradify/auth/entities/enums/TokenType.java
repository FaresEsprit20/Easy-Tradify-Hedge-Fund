package com.trading.easytradify.auth.entities.enums;

public enum TokenType {
    @Deprecated JWT,              // To be removed after migration
    OAUTH2_ACCESS,                // OAuth2 access token (short-lived)
    OAUTH2_REFRESH,               // OAuth2 refresh token (long-lived)
    PASSWORD_RESET,               // Password reset tokens
    TWO_FACTOR,                   // Legacy email-OTP verification tokens
    TOTP_LOGIN_PENDING            // Short-lived ticket issued after password check, while awaiting a TOTP code
}