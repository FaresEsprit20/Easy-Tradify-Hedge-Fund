package com.trading.easytradify.auth.config.security.handler;

import com.trading.easytradify.auth.config.security.oauth2.OAuth2TokenService;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.auth.entities.enums.TokenType;
import com.trading.easytradify.auth.repository.UnifiedTokenRepository;
import com.trading.easytradify.auth.services.users.CustomUserDetailsService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.client.authentication.OAuth2AuthenticationToken;
import org.springframework.security.oauth2.core.user.OAuth2User;
import org.springframework.security.web.authentication.SimpleUrlAuthenticationSuccessHandler;
import org.springframework.stereotype.Component;
import org.springframework.web.util.UriComponentsBuilder;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;

import static com.trading.easytradify.common.utils.constants.Constants.PRODUCTION_ENVIRONMENT;

@Slf4j
@Component
@RequiredArgsConstructor
public class OAuth2LoginSuccessHandler extends SimpleUrlAuthenticationSuccessHandler {

    private final CustomUserDetailsService userDetailsService;
    private final OAuth2TokenService tokenService;
    private final UnifiedTokenRepository tokenRepository;

    @Value("${app.oauth2.success-url:/oauth2/success}")
    private String successUrl;

    @Override
    public void onAuthenticationSuccess(HttpServletRequest request,
                                        HttpServletResponse response,
                                        Authentication authentication) throws IOException {

        OAuth2AuthenticationToken oauthToken = (OAuth2AuthenticationToken) authentication;
        OAuth2User oauth2User = oauthToken.getPrincipal();

        String provider = oauthToken.getAuthorizedClientRegistrationId();
        Map<String, Object> attributes = oauth2User.getAttributes();

        // Extract user info from provider
        String providerId = extractProviderId(provider, attributes);
        String email = extractEmail(provider, attributes);
        String name = extractName(provider, attributes);

        log.info("OAuth2 login success - Provider: {}, ProviderId: {}, Email: {}", provider, providerId, email);

        // Load or create user
        User user = (User) userDetailsService.loadUserByOAuth2Provider(provider, providerId, email, name);

        // Generate new opaque tokens
        String accessToken = tokenService.generateAccessToken();
        String refreshToken = tokenService.generateRefreshToken();

        // Store access token (15 minutes expiry)
        tokenService.storeToken(accessToken, TokenType.OAUTH2_ACCESS,
                user.getId(), user.getEmail(), request, 15);

        // Store refresh token (7 days expiry)
        tokenService.storeToken(refreshToken, TokenType.OAUTH2_REFRESH,
                user.getId(), user.getEmail(), request, 10080);

        log.info("OAuth2 tokens stored for user: {}", user.getEmail());

        // Set cookies (for Postman to auto-capture)
        setAuthCookies(response, accessToken, refreshToken);

        // Spring Security persisted the OAuth2AuthenticationToken it built during
        // the handshake into the HttpSession (JSESSIONID), with the provider's
        // raw subject id as its principal name — not this app's email. Every
        // other endpoint authenticates purely via the opaque accessToken/
        // refreshToken cookies (OAuth2AuthenticationFilter), which only sets a
        // new Authentication when the context is empty. Left alone, that stale
        // session-based principal would win on every later request in this
        // browser session and get treated as if "email" == the provider id,
        // breaking checkUserAuthentication() and anything else keyed by email.
        // The cookies above are the real source of truth from here on, so drop
        // the session entirely rather than let two auth mechanisms compete.
        request.getSession().invalidate();
        SecurityContextHolder.clearContext();

        // Redirect with tokens in URL for Angular to capture
        String targetUrl = UriComponentsBuilder.fromUriString(successUrl)
                .queryParam("accessToken", accessToken)
                .queryParam("refreshToken", refreshToken)
                .build()
                .toUriString();

        getRedirectStrategy().sendRedirect(request, response, targetUrl);
    }

    private String extractProviderId(String provider, Map<String, Object> attributes) {
        switch (provider) {
            case "google":
                return attributes.get("sub").toString();
            case "github":
                return attributes.get("id").toString();
            case "facebook":
                return attributes.get("id").toString();
            default:
                return attributes.get("sub") != null ? attributes.get("sub").toString() :
                        attributes.get("id") != null ? attributes.get("id").toString() : null;
        }
    }

    private String extractEmail(String provider, Map<String, Object> attributes) {
        String email = (String) attributes.get("email");
        if (email == null || email.isEmpty()) {
            String providerId = extractProviderId(provider, attributes);
            return providerId + "@" + provider + ".com";
        }
        return email;
    }

    private String extractName(String provider, Map<String, Object> attributes) {
        String name = (String) attributes.get("name");
        if (name == null || name.isEmpty()) {
            name = (String) attributes.get("login");
        }
        if (name == null || name.isEmpty()) {
            name = provider + "_user";
        }
        return name;
    }

    private void setAuthCookies(HttpServletResponse response, String accessToken, String refreshToken) {
        // Access token cookie (15 minutes)
        ResponseCookie accessCookie = ResponseCookie.from("accessToken", accessToken)
                .httpOnly(true)
                .secure(PRODUCTION_ENVIRONMENT)
                .path("/")
                .maxAge(Duration.ofMinutes(15))
                .sameSite("Lax")
                .build();

        // Refresh token cookie (7 days)
        ResponseCookie refreshCookie = ResponseCookie.from("refreshToken", refreshToken)
                .httpOnly(true)
                .secure(PRODUCTION_ENVIRONMENT)
                .path("/")
                .maxAge(Duration.ofDays(7))
                .sameSite("Lax")
                .build();

        response.addHeader(HttpHeaders.SET_COOKIE, accessCookie.toString());
        response.addHeader(HttpHeaders.SET_COOKIE, refreshCookie.toString());

        // JSESSIONID cookie is automatically created by Spring Security

        log.info("OAuth2 cookies set successfully");
    }
}