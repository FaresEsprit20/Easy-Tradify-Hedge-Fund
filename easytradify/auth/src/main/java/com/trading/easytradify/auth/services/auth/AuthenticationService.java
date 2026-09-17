package com.trading.easytradify.auth.services.auth;

import com.trading.easytradify.common.dto.auth.AuthCheckResponse;
import com.trading.easytradify.common.dto.auth.AuthenticationRequest;
import com.trading.easytradify.common.dto.auth.AuthenticationResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.oauth2.client.authentication.OAuth2AuthenticationToken;

import java.io.IOException;

public interface AuthenticationService {

    AuthenticationResponse authenticate(AuthenticationRequest request, HttpServletRequest httpRequest);

    AuthenticationResponse verifyTwoFactor(String mfaToken, String code, HttpServletRequest request);

    AuthenticationResponse authenticateWithOAuth2(OAuth2AuthenticationToken oauthToken, HttpServletRequest request);

    AuthenticationResponse authenticateWithToken(String token, HttpServletRequest request);

    AuthenticationResponse refreshAccessToken(String refreshToken, HttpServletRequest request);

    AuthenticationResponse exchangeGoogleCode(String authorizationCode, HttpServletRequest request);

    void refreshToken(HttpServletRequest request, HttpServletResponse response) throws IOException;

    AuthCheckResponse checkUserAuthentication(String email);
}