package com.trading.easytradify.auth.config.security.filters;

import com.trading.easytradify.auth.config.security.oauth2.OAuth2TokenService;
import com.trading.easytradify.auth.entities.UnifiedToken;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.auth.services.users.CustomUserDetailsService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.NonNull;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

import static com.trading.easytradify.common.utils.constants.Constants.AUTHENTICATION_ENDPOINT;
import java.util.Optional;

@Slf4j
@RequiredArgsConstructor
@Component
public class OAuth2AuthenticationFilter extends OncePerRequestFilter {

    private final OAuth2TokenService tokenService;
    private final CustomUserDetailsService userDetailsService;

    @Override
    protected void doFilterInternal(
            @NonNull HttpServletRequest request,
            @NonNull HttpServletResponse response,
            @NonNull FilterChain filterChain
    ) throws ServletException, IOException {

        String path = request.getServletPath();

        // Skip filter for public endpoints.
        //
        // Built from AUTHENTICATION_ENDPOINT rather than written out: this line
        // still read "/tunindex/market/tool/v1/auth/" after the port, which
        // would have left the auth endpoints running through the token filter
        // that is supposed to skip them -- so /authenticate would have demanded
        // the very token it exists to issue.
        if (path.startsWith("/oauth2/") || path.startsWith("/login/") ||
                path.startsWith("/" + AUTHENTICATION_ENDPOINT + "/") ||
                path.equals("/logout")) {  // Also skip logout
            filterChain.doFilter(request, response);
            return;
        }

        log.debug("🔍 OAuth2Filter processing: {}", path);

        // Extract token ONLY from cookie (NO Bearer token)
        String token = extractTokenFromCookie(request);

        if (token == null) {
            log.debug("⏭️ No token cookie found, continuing filter chain");
            filterChain.doFilter(request, response);
            return;
        }

        log.debug("✅ Token cookie found, validating...");

        // Validate token with OAuth2TokenService
        Optional<UnifiedToken> tokenOpt = tokenService.validateToken(token, request);

        if (tokenOpt.isEmpty()) {
            log.warn("❌ Invalid or expired token");
            // Clear the invalid cookie
            clearCookie(response, "accessToken");
            filterChain.doFilter(request, response);
            return;
        }

        UnifiedToken unifiedToken = tokenOpt.get();
        String userEmail = unifiedToken.getUserEmail();

        log.debug("📧 Extracted email from token: {}", userEmail);

        if (userEmail != null && SecurityContextHolder.getContext().getAuthentication() == null) {
            log.debug("🔐 Loading user details for: {}", userEmail);
            UserDetails userDetails = userDetailsService.loadUserByUsername(userEmail);

            boolean isTokenValid = !unifiedToken.isRevoked() &&
                    !unifiedToken.isExpired() &&
                    unifiedToken.getExpirationDate() != null &&
                    unifiedToken.getExpirationDate().isAfter(java.time.LocalDateTime.now());

            log.debug("🎫 Token in DB: revoked={}, expired={}, valid={}",
                    unifiedToken.isRevoked(), unifiedToken.isExpired(), isTokenValid);

            if (isTokenValid && userDetails instanceof User) {
                UsernamePasswordAuthenticationToken authToken = new UsernamePasswordAuthenticationToken(
                        userDetails,
                        null,
                        userDetails.getAuthorities()
                );
                authToken.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
                SecurityContextHolder.getContext().setAuthentication(authToken);
                log.info("✅ Authentication set in SecurityContext for user: {}", userEmail);
            } else {
                log.warn("❌ Token validation failed for user: {}", userEmail);
                // Clear invalid cookie
                clearCookie(response, "accessToken");
                filterChain.doFilter(request, response);
                return;
            }
        }

        filterChain.doFilter(request, response);
    }

    /**
     * Extract token ONLY from cookie (NO Authorization header)
     */
    private String extractTokenFromCookie(HttpServletRequest request) {
        if (request.getCookies() != null) {
            for (Cookie cookie : request.getCookies()) {
                if ("accessToken".equals(cookie.getName())) {
                    log.debug("Token extracted from cookie");
                    return cookie.getValue();
                }
            }
        }
        log.debug("No accessToken cookie found");
        return null;
    }

    /**
     * Clear a specific cookie
     */
    private void clearCookie(HttpServletResponse response, String cookieName) {
        Cookie cookie = new Cookie(cookieName, null);
        cookie.setPath("/");
        cookie.setHttpOnly(true);
        cookie.setMaxAge(0);
        response.addCookie(cookie);
        log.debug("Cleared cookie: {}", cookieName);
    }
}