package com.trading.easytradify.auth.config.security.logout;

import com.trading.easytradify.auth.entities.UnifiedToken;
import com.trading.easytradify.auth.entities.enums.TokenType;
import com.trading.easytradify.auth.repository.UnifiedTokenRepository;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.oauth2.client.authentication.OAuth2AuthenticationToken;
import org.springframework.security.web.authentication.logout.LogoutHandler;
import org.springframework.stereotype.Service;

import java.util.Optional;

import static com.trading.easytradify.common.utils.constants.Constants.PRODUCTION_ENVIRONMENT;

@Slf4j
@Service
@RequiredArgsConstructor
public class LogoutService implements LogoutHandler {

    private final UnifiedTokenRepository tokenRepository;

    @Override
    public void logout(
            HttpServletRequest request,
            HttpServletResponse response,
            Authentication authentication
    ) {
        log.info("Processing logout request");

        // Extract token from cookie
        String token = extractTokenFromCookie(request);

        if (token == null) {
            log.warn("No token found in cookie during logout");
            clearCookiesAndSession(request, response);
            return;
        }

        // Find OAuth2 token in database
        Optional<UnifiedToken> tokenOpt = tokenRepository.findOAuth2TokenByToken(token);

        if (tokenOpt.isPresent()) {
            UnifiedToken unifiedToken = tokenOpt.get();

            // Revoke the token
            unifiedToken.setRevoked(true);
            unifiedToken.setExpired(true);
            tokenRepository.save(unifiedToken);

            log.info("Token revoked: {}", token);

            // Also revoke all other tokens for this user (optional - for complete logout)
            if (unifiedToken.getUser() != null && unifiedToken.getUser().getId() != null) {
                tokenRepository.revokeAllOAuth2TokensByUser(unifiedToken.getUser().getId());
                log.info("All tokens revoked for user: {}", unifiedToken.getUser().getEmail());
            } else if (unifiedToken.getUserEmail() != null) {
                // Fallback if user entity not loaded
                revokeTokensByEmail(unifiedToken.getUserEmail());
            }

            // Log user info
            if (authentication != null && authentication.getPrincipal() instanceof UserDetails userDetails) {
                log.info("Logging out user: {}", userDetails.getUsername());
            } else if (authentication instanceof OAuth2AuthenticationToken oauthToken) {
                log.info("Logging out OAuth2 user: {}", Optional.ofNullable(oauthToken.getPrincipal().getAttribute("email")));
            }
        } else {
            log.warn("Token not found in database: {}", token);
        }

        // Clear cookies and session
        clearCookiesAndSession(request, response);

        log.info("Logout completed successfully");
    }

    /**
     * Revoke all tokens for a user by email
     */
    private void revokeTokensByEmail(String email) {
        var tokens = tokenRepository.findByUserEmailAndType(email, TokenType.OAUTH2_ACCESS);
        tokens.forEach(token -> {
            token.setRevoked(true);
            token.setExpired(true);
            tokenRepository.save(token);
        });

        var refreshTokens = tokenRepository.findByUserEmailAndType(email, TokenType.OAUTH2_REFRESH);
        refreshTokens.forEach(token -> {
            token.setRevoked(true);
            token.setExpired(true);
            tokenRepository.save(token);
        });

        log.info("All tokens revoked for email: {}", email);
    }

    /**
     * Clear all cookies and invalidate session
     */
    private void clearCookiesAndSession(HttpServletRequest request, HttpServletResponse response) {
        // Delete access token cookie
        deleteCookie(response, "accessToken");

        // Delete refresh token cookie
        deleteCookie(response, "refreshToken");

        // Delete JSESSIONID cookie
        deleteCookie(response, "JSESSIONID");

        // Delete OAuth2 session cookie if present
        deleteCookie(response, "SESSION");

        // Invalidate the session
        if (request.getSession() != null) {
            request.getSession().invalidate();
            log.info("Session invalidated");
        }

        // Clear security context
        SecurityContextHolder.clearContext();
        log.info("Security context cleared");
    }

    /**
     * Extract token from cookie
     */
    private String extractTokenFromCookie(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (Cookie cookie : cookies) {
                if ("accessToken".equals(cookie.getName())) {
                    return cookie.getValue();
                }
            }
        }
        return null;
    }

    /**
     * Delete a cookie by setting max age to 0
     */
    private void deleteCookie(HttpServletResponse response, String cookieName) {
        Cookie cookie = new Cookie(cookieName, null);
        cookie.setPath("/");
        cookie.setHttpOnly(true);
        cookie.setSecure(PRODUCTION_ENVIRONMENT);
        cookie.setMaxAge(0);
        response.addCookie(cookie);
        log.debug("Cookie deleted: {}", cookieName);
    }
}