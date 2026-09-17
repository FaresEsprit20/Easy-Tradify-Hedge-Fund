package com.trading.easytradify.auth.services.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.easytradify.auth.config.security.config.IpUaExtractor;
import com.trading.easytradify.auth.config.security.oauth2.OAuth2TokenService;
import com.trading.easytradify.common.dto.auth.AuthCheckResponse;
import com.trading.easytradify.common.dto.auth.AuthenticationRequest;
import com.trading.easytradify.common.dto.auth.AuthenticationResponse;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.auth.entities.enums.TokenType;
import com.trading.easytradify.common.exception.EntityNotFoundException;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.InvalidOperationException;
import com.trading.easytradify.auth.repository.UnifiedTokenRepository;
import com.trading.easytradify.auth.repository.UserRepository;
import com.trading.easytradify.auth.entities.UnifiedToken;
import com.trading.easytradify.auth.services.totp.TotpService;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.transaction.Transactional;
import com.trading.easytradify.common.entities.enums.TwoFactorMethod;
import com.trading.easytradify.auth.services.two_facor.TwoFactorAuthService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.client.authentication.OAuth2AuthenticationToken;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static com.trading.easytradify.common.utils.constants.Constants.PRODUCTION_ENVIRONMENT;

@Slf4j
@Service
@Transactional
@RequiredArgsConstructor
public class AuthenticationServiceImpl implements AuthenticationService {

    private final UserRepository userRepository;
    private final UnifiedTokenRepository unifiedTokenRepository;
    private final OAuth2TokenService oauth2TokenService;
    private final TwoFactorAuthService twoFactorAuthService;
    private final IpUaExtractor ipUaExtractor;
    private final AuthenticationManager authenticationManager;
    private final PasswordEncoder passwordEncoder;
    private final TotpService totpService;

    @Value("${spring.security.oauth2.client.registration.google.client-id}")
    private String googleClientId;

    @Value("${spring.security.oauth2.client.registration.google.client-secret}")
    private String googleClientSecret;

    @Value("${spring.security.oauth2.client.registration.google.redirect-uri}")
    private String googleRedirectUri;

    @Override
    public AuthenticationResponse authenticate(AuthenticationRequest authRequest, HttpServletRequest request) {
        log.info("🔐 Username/password authentication attempt for user: {}", authRequest.getLogin());

        try {
            authenticationManager.authenticate(
                    new UsernamePasswordAuthenticationToken(
                            authRequest.getLogin(),
                            authRequest.getPassword()
                    )
            );
        } catch (BadCredentialsException e) {
            throw new InvalidOperationException(
                    "Invalid credentials",
                    ErrorCodes.BAD_CREDENTIALS,
                    List.of("Username or password is incorrect")
            );
        }

        User user = userRepository.findUserByEmailOrUsername(authRequest.getLogin())
                .orElseThrow(() -> new InvalidOperationException(
                        "User not found",
                        ErrorCodes.USER_NOT_FOUND,
                        List.of("No user found with email or username: " + authRequest.getLogin())
                ));

        if (user.getLocked()) {
            throw new InvalidOperationException(
                    "User account is locked",
                    ErrorCodes.USER_ACCOUNT_LOCK_NOT_VALID,
                    List.of("Contact support to unlock your account")
            );
        }

        if (Boolean.TRUE.equals(user.getTwoFactorEnabled())) {
            String mfaToken = "mfa_" + java.util.UUID.randomUUID().toString().replace("-", "");
            oauth2TokenService.storeToken(mfaToken, TokenType.TOTP_LOGIN_PENDING,
                    user.getId(), user.getEmail(), request, 5);

            // Honours the user's chosen delivery method. This branch used to
            // assume the authenticator app, which is why the email route
            // existed in the codebase but was unreachable - and why the
            // account page had nothing to offer but on/off.
            TwoFactorMethod method = user.resolvedTwoFactorMethod();
            if (method == TwoFactorMethod.EMAIL) {
                try {
                    twoFactorAuthService.generateAndSendOtp(user.getEmail());
                } catch (Exception e) {
                    // The password was correct, so the account is not at
                    // fault; the delivery channel is. Failing the sign-in
                    // with a clear reason beats returning a challenge for a
                    // code that was never sent.
                    log.error("Could not send the 2FA code to {}: {}", user.getEmail(), e.getMessage());
                    throw new InvalidOperationException(
                            "Could not send your verification code",
                            ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                            List.of("Email delivery is unavailable right now. Try again shortly."));
                }
            }

            log.info("🔐 Password OK, {} code required for user: {}", method, user.getEmail());
            return AuthenticationResponse.builder()
                    .requiresTwoFactor(true)
                    .mfaToken(mfaToken)
                    .twoFactorMethod(method.name())
                    .build();
        }

        String accessToken = oauth2TokenService.generateAccessToken();
        String refreshToken = oauth2TokenService.generateRefreshToken();

        String ipHash = ipUaExtractor.hashIp(request);
        String uaHash = ipUaExtractor.hashUserAgent(request);

        revokeAllUserTokens(user);

        oauth2TokenService.storeToken(accessToken, TokenType.OAUTH2_ACCESS,
                user.getId(), user.getEmail(), request, 15);
        oauth2TokenService.storeToken(refreshToken, TokenType.OAUTH2_REFRESH,
                user.getId(), user.getEmail(), request, 10080);

        setAuthCookies(request, accessToken, refreshToken);

        log.info("✅ Username/password authentication successful for user: {}", user.getEmail());

        return AuthenticationResponse.builder()
                .accessToken(accessToken)
                .refreshToken(refreshToken)
                .build();
    }

    @Override
    public AuthenticationResponse verifyTwoFactor(String mfaToken, String code, HttpServletRequest request) {
        UnifiedToken pending = unifiedTokenRepository.findByTokenAndType(mfaToken, TokenType.TOTP_LOGIN_PENDING)
                .orElseThrow(() -> new InvalidOperationException(
                        "Invalid or expired login session", ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                        List.of("The login session has expired — please sign in again")));

        if (pending.isUsed() || pending.getExpirationDate().isBefore(java.time.LocalDateTime.now())) {
            throw new InvalidOperationException(
                    "This login session has expired", ErrorCodes.TWO_FACTOR_TOKEN_EXPIRED,
                    List.of("Please sign in again"));
        }

        User user = userRepository.findUserByEmail(pending.getUserEmail())
                .orElseThrow(() -> new InvalidOperationException(
                        "User not found", ErrorCodes.USER_NOT_FOUND, List.of("email: " + pending.getUserEmail())));

        if (!totpService.verifyCode(user.getTotpSecret(), code)) {
            throw new InvalidOperationException(
                    "Invalid authentication code", ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                    List.of("The code you entered is incorrect or has expired"));
        }

        pending.setUsed(true);
        unifiedTokenRepository.save(pending);

        String accessToken = oauth2TokenService.generateAccessToken();
        String refreshToken = oauth2TokenService.generateRefreshToken();

        revokeAllUserTokens(user);

        oauth2TokenService.storeToken(accessToken, TokenType.OAUTH2_ACCESS,
                user.getId(), user.getEmail(), request, 15);
        oauth2TokenService.storeToken(refreshToken, TokenType.OAUTH2_REFRESH,
                user.getId(), user.getEmail(), request, 10080);

        setAuthCookies(request, accessToken, refreshToken);

        log.info("✅ TOTP verification successful for user: {}", user.getEmail());

        return AuthenticationResponse.builder()
                .accessToken(accessToken)
                .refreshToken(refreshToken)
                .build();
    }

    @Override
    public AuthenticationResponse authenticateWithOAuth2(OAuth2AuthenticationToken oauthToken, HttpServletRequest request) {
        log.info("🔐 OAuth2 authentication attempt");

        Map<String, Object> attributes = oauthToken.getPrincipal().getAttributes();
        String email = (String) attributes.get("email");
        String name = (String) attributes.get("name");
        String provider = oauthToken.getAuthorizedClientRegistrationId();
        String providerId = (String) attributes.get("sub");

        log.info("OAuth2 user: email={}, provider={}", email, provider);

        User user = userRepository.findByProviderAndProviderId(provider, providerId)
                .orElseGet(() -> userRepository.findUserByEmail(email)
                        .map(existingUser -> {
                            existingUser.setProvider(provider);
                            existingUser.setProviderId(providerId);
                            return userRepository.save(existingUser);
                        })
                        .orElseGet(() -> {
                            User newUser = new User();
                            newUser.setEmail(email);
                            if (name != null) {
                                String[] nameParts = name.split(" ", 2);
                                newUser.setFirstName(nameParts[0]);
                                if (nameParts.length > 1) {
                                    newUser.setLastName(nameParts[1]);
                                }
                            } else {
                                newUser.setFirstName(provider);
                                newUser.setLastName("User");
                            }
                            newUser.setProvider(provider);
                            newUser.setProviderId(providerId);
                            newUser.setLocked(false);
                            newUser.setNumTel("0000000000");
                            newUser.setPassword(passwordEncoder.encode("OAUTH2_USER_" + System.currentTimeMillis()));
                            return userRepository.save(newUser);
                        })
                );

        String accessToken = oauth2TokenService.generateAccessToken();
        String refreshToken = oauth2TokenService.generateRefreshToken();

        String ipHash = ipUaExtractor.hashIp(request);
        String uaHash = ipUaExtractor.hashUserAgent(request);

        revokeAllUserTokens(user);

        oauth2TokenService.storeToken(accessToken, TokenType.OAUTH2_ACCESS,
                user.getId(), user.getEmail(), request, 15);
        oauth2TokenService.storeToken(refreshToken, TokenType.OAUTH2_REFRESH,
                user.getId(), user.getEmail(), request, 10080);

        setAuthCookies(request, accessToken, refreshToken);

        log.info("✅ OAuth2 authentication successful for user: {}", user.getEmail());

        return AuthenticationResponse.builder()
                .accessToken(accessToken)
                .refreshToken(refreshToken)
                .build();
    }

    @Override
    public AuthenticationResponse authenticateWithToken(String token, HttpServletRequest request) {
        log.info("🔐 Token authentication attempt for token: {}",
                token != null ? token.substring(0, Math.min(20, token.length())) : "null");

        if (token == null || token.isBlank()) {
            throw new InvalidOperationException(
                    "Token is required",
                    ErrorCodes.INVALID_PARAMETER,
                    List.of("Authentication token cannot be null or empty")
            );
        }

        var tokenOpt = oauth2TokenService.validateToken(token, request);

        if (tokenOpt.isEmpty()) {
            throw new InvalidOperationException(
                    "Invalid or expired token",
                    ErrorCodes.USER_NOT_AUTHENTICATED,
                    List.of("The provided token is invalid or has expired. Please login again.")
            );
        }

        var unifiedToken = tokenOpt.get();
        String email = unifiedToken.getUserEmail();

        log.info("Token validated for user: {}", email);

        User user = userRepository.findUserByEmail(email)
                .orElseThrow(() -> new InvalidOperationException(
                        "User not found for token",
                        ErrorCodes.USER_NOT_FOUND,
                        List.of("No user associated with this token")
                ));

        // Return the same valid token (no need to generate new ones for validation)
        return AuthenticationResponse.builder()
                .accessToken(token)
                .refreshToken(null)
                .build();
    }

    @Override
    public AuthenticationResponse refreshAccessToken(String refreshToken, HttpServletRequest request) {
        log.info("🔐 Refresh token authentication attempt");

        if (refreshToken == null || refreshToken.isBlank()) {
            throw new InvalidOperationException(
                    "Refresh token is required",
                    ErrorCodes.INVALID_PARAMETER,
                    List.of("Refresh token cannot be null or empty")
            );
        }

        Optional<String> newAccessTokenOpt = oauth2TokenService.refreshAccessToken(refreshToken, request);

        if (newAccessTokenOpt.isEmpty()) {
            throw new InvalidOperationException(
                    "Invalid refresh token",
                    ErrorCodes.USER_NOT_AUTHENTICATED,
                    List.of("The provided refresh token is invalid or has expired")
            );
        }

        String newAccessToken = newAccessTokenOpt.get();

        return AuthenticationResponse.builder()
                .accessToken(newAccessToken)
                .refreshToken(refreshToken)
                .build();
    }

    @Override
    public AuthenticationResponse exchangeGoogleCode(String authorizationCode, HttpServletRequest request) {
        log.info("Exchanging Google authorization code for tokens");

        if (authorizationCode == null || authorizationCode.isBlank()) {
            throw new InvalidOperationException(
                    "Authorization code is required",
                    ErrorCodes.INVALID_PARAMETER,
                    List.of("Google authorization code cannot be null or empty")
            );
        }

        try {
            RestTemplate restTemplate = new RestTemplate();

            String tokenUrl = "https://oauth2.googleapis.com/token";
            HttpHeaders headers = new HttpHeaders();
            headers.setBasicAuth(googleClientId, googleClientSecret);
            headers.set("Content-Type", "application/x-www-form-urlencoded");

            String body = "code=" + authorizationCode +
                    "&redirect_uri=" + googleRedirectUri +
                    "&grant_type=authorization_code";

            HttpEntity<String> entity = new HttpEntity<>(body, headers);
            ResponseEntity<Map> response = restTemplate.exchange(tokenUrl, HttpMethod.POST, entity, Map.class);

            if (!response.getStatusCode().is2xxSuccessful() || response.getBody() == null) {
                throw new InvalidOperationException(
                        "Failed to exchange Google code",
                        ErrorCodes.PROVIDER_AUTHENTICATION_ERROR,
                        List.of("Google authentication failed: " + response.getStatusCode())
                );
            }

            Map<String, Object> tokenResponse = response.getBody();
            String googleAccessToken = (String) tokenResponse.get("access_token");

            String userInfoUrl = "https://www.googleapis.com/oauth2/v3/userinfo";
            HttpHeaders userInfoHeaders = new HttpHeaders();
            userInfoHeaders.setBearerAuth(googleAccessToken);
            HttpEntity<?> userInfoEntity = new HttpEntity<>(userInfoHeaders);

            ResponseEntity<Map> userInfoResponse = restTemplate.exchange(userInfoUrl, HttpMethod.GET, userInfoEntity, Map.class);
            Map<String, Object> userInfo = userInfoResponse.getBody();

            String email = (String) userInfo.get("email");
            String name = (String) userInfo.get("name");
            String providerId = (String) userInfo.get("sub");

            log.info("Google user info - email: {}, name: {}", email, name);

            User user = userRepository.findByProviderAndProviderId("google", providerId)
                    .orElseGet(() -> userRepository.findUserByEmail(email)
                            .map(existingUser -> {
                                existingUser.setProvider("google");
                                existingUser.setProviderId(providerId);
                                return userRepository.save(existingUser);
                            })
                            .orElseGet(() -> {
                                User newUser = new User();
                                newUser.setEmail(email);
                                if (name != null) {
                                    String[] nameParts = name.split(" ", 2);
                                    newUser.setFirstName(nameParts[0]);
                                    if (nameParts.length > 1) {
                                        newUser.setLastName(nameParts[1]);
                                    }
                                } else {
                                    newUser.setFirstName("Google");
                                    newUser.setLastName("User");
                                }
                                newUser.setProvider("google");
                                newUser.setProviderId(providerId);
                                newUser.setLocked(false);
                                newUser.setNumTel("0000000000");
                                newUser.setPassword(passwordEncoder.encode("OAUTH2_USER_" + System.currentTimeMillis()));
                                return userRepository.save(newUser);
                            })
                    );

            String accessToken = oauth2TokenService.generateAccessToken();
            String refreshToken = oauth2TokenService.generateRefreshToken();

            String ipHash = ipUaExtractor.hashIp(request);
            String uaHash = ipUaExtractor.hashUserAgent(request);

            revokeAllUserTokens(user);

            oauth2TokenService.storeToken(accessToken, TokenType.OAUTH2_ACCESS,
                    user.getId(), user.getEmail(), request, 15);
            oauth2TokenService.storeToken(refreshToken, TokenType.OAUTH2_REFRESH,
                    user.getId(), user.getEmail(), request, 10080);

            setAuthCookies(request, accessToken, refreshToken);

            log.info("✅ Google code exchange successful for user: {}", user.getEmail());

            return AuthenticationResponse.builder()
                    .accessToken(accessToken)
                    .refreshToken(refreshToken)
                    .build();

        } catch (InvalidOperationException e) {
            throw e;
        } catch (Exception e) {
            log.error("Google code exchange failed: {}", e.getMessage());
            throw new InvalidOperationException(
                    "Google authentication failed",
                    ErrorCodes.PROVIDER_AUTHENTICATION_ERROR,
                    List.of("Failed to authenticate with Google: " + e.getMessage())
            );
        }
    }

    private void setAuthCookies(HttpServletRequest request, String accessToken, String refreshToken) {
        HttpServletResponse response = ((ServletRequestAttributes) RequestContextHolder
                .currentRequestAttributes()).getResponse();

        if (response != null) {
            ResponseCookie accessCookie = ResponseCookie.from("accessToken", accessToken)
                    .httpOnly(true)
                    .secure(PRODUCTION_ENVIRONMENT)
                    .path("/")
                    .maxAge(Duration.ofMinutes(15))
                    .sameSite(PRODUCTION_ENVIRONMENT ? "Strict" : "Lax")
                    .build();

            ResponseCookie refreshCookie = ResponseCookie.from("refreshToken", refreshToken)
                    .httpOnly(true)
                    .secure(PRODUCTION_ENVIRONMENT)
                    .path("/")
                    .maxAge(Duration.ofDays(7))
                    .sameSite(PRODUCTION_ENVIRONMENT ? "Strict" : "Lax")
                    .build();

            response.addHeader(HttpHeaders.SET_COOKIE, accessCookie.toString());
            response.addHeader(HttpHeaders.SET_COOKIE, refreshCookie.toString());

            log.info("✅ OAuth2 cookies set successfully");
        }
    }

    @Transactional
    public void revokeAllUserTokens(User user) {
        unifiedTokenRepository.revokeAllOAuth2TokensByUser(user.getId());
        log.info("Revoked all tokens for user: {}", user.getEmail());
    }

    @Override
    public void refreshToken(HttpServletRequest request, HttpServletResponse response) throws IOException {
        response.setContentType("application/json");

        String refreshToken = extractRefreshToken(request);
        if (refreshToken == null) {
            response.sendError(HttpServletResponse.SC_UNAUTHORIZED, "Missing refresh token");
            return;
        }

        try {
            Optional<String> newAccessTokenOpt = oauth2TokenService.refreshAccessToken(refreshToken, request);

            if (newAccessTokenOpt.isEmpty()) {
                response.sendError(HttpServletResponse.SC_UNAUTHORIZED, "Invalid refresh token");
                return;
            }

            String newAccessToken = newAccessTokenOpt.get();
            setAccessTokenCookie(response, newAccessToken);

            AuthenticationResponse authResponse = AuthenticationResponse.builder()
                    .accessToken(newAccessToken)
                    .refreshToken(refreshToken)
                    .build();

            new ObjectMapper().writeValue(response.getWriter(), authResponse);

        } catch (Exception e) {
            log.error("Token refresh failed", e);
            response.sendError(HttpServletResponse.SC_INTERNAL_SERVER_ERROR, "Token refresh failed");
        }
    }

    @Override
    public AuthCheckResponse checkUserAuthentication(String email) {
        if (email == null || email.isBlank()) {
            return AuthCheckResponse.builder()
                    .isAuthenticated(false)
                    .build();
        }

        User user = userRepository.findUserByEmail(email)
                .orElse(null);

        if (user == null) {
            return AuthCheckResponse.builder()
                    .isAuthenticated(false)
                    .build();
        }

        long validTokensCount = unifiedTokenRepository.countActiveOAuth2TokensByUser(user.getId(), java.time.LocalDateTime.now());

        return AuthCheckResponse.builder()
                .isAuthenticated(validTokensCount > 0)
                .email(user.getEmail())
                .userId(user.getId())
                .build();
    }

    private String extractRefreshToken(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (Cookie cookie : cookies) {
                if ("refreshToken".equals(cookie.getName())) {
                    return cookie.getValue();
                }
            }
        }
        return null;
    }

    private void setAccessTokenCookie(HttpServletResponse response, String token) {
        ResponseCookie cookie = ResponseCookie.from("accessToken", token)
                .httpOnly(true)
                .secure(PRODUCTION_ENVIRONMENT)
                .path("/")
                .maxAge(Duration.ofMinutes(15))
                .sameSite("Strict")
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }
}