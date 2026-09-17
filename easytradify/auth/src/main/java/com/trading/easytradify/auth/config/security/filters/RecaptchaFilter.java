package com.trading.easytradify.auth.config.security.filters;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import static com.trading.easytradify.common.utils.constants.Constants.ACCOUNTS_ENDPOINT;
import static com.trading.easytradify.common.utils.constants.Constants.AUTHENTICATION_ENDPOINT;

/**
 * Requires a valid reCAPTCHA token on the endpoints bots actually attack.
 *
 * <h2>Why this protects a short list rather than every mutation</h2>
 * <p>
 * The version this was ported from demanded a token on every POST, PUT, PATCH
 * and DELETE that was not explicitly bypassed. That is worse protection, not
 * better: it forces the front end to attach a token to routine authenticated
 * actions like editing a profile, so the token becomes something the client
 * mints constantly and nobody reads carefully — and it protects nothing extra,
 * because those routes already require a valid opaque access token, and an
 * attacker holding one has no captcha to defeat.
 * </p>
 * <p>
 * What a captcha is actually for is the UNAUTHENTICATED surface, where the only
 * cost of an attempt is an HTTP request:
 * </p>
 * <ul>
 *   <li><b>authenticate</b> — credential stuffing against leaked password lists.</li>
 *   <li><b>two-factor/verify</b> — brute-forcing a six-digit code. The token
 *       itself blocks after a few attempts, but without a captcha an attacker
 *       can cheaply cycle fresh login sessions to reset that counter.</li>
 *   <li><b>account creation</b> — mass signup, which costs the platform real
 *       money once email is wired in.</li>
 * </ul>
 *
 * <h2>Fails closed</h2>
 * <p>
 * If the reCAPTCHA service cannot be reached, requests to protected paths are
 * REJECTED rather than waved through. That is a deliberate availability
 * trade-off: failing open turns any outage of that service — including one an
 * attacker causes — into a window with no bot protection at all, which is
 * precisely when it is most wanted. {@code security.recaptcha.fail-open} exists
 * to invert this, and should stay false.
 * </p>
 *
 * <h2>Ordering</h2>
 * <p>
 * Runs ahead of the security chain so a bot's request is dropped before it
 * reaches password verification. Note this sits BEHIND the rate limiter by
 * design — the cheap local check should reject a flood before this one spends a
 * network round trip per request.
 * </p>
 */
@Component
@RequiredArgsConstructor
@Slf4j
@Order(Ordered.HIGHEST_PRECEDENCE + 2)
public class RecaptchaFilter extends OncePerRequestFilter {

    private final WebClient.Builder webClientBuilder;

    @Value("${recaptcha.service.url:http://localhost:8089}")
    private String recaptchaServiceUrl;

    @Value("${internal.api.key:}")
    private String internalApiKey;

    /**
     * Master switch. Off in local development by default, because a developer
     * without the reCAPTCHA service running would otherwise be unable to sign
     * in at all — and the natural response to that is to disable the filter and
     * forget to re-enable it.
     */
    @Value("${security.recaptcha.enabled:false}")
    private boolean enabled;

    /** See the class note. Inverting this removes the protection during an outage. */
    @Value("${security.recaptcha.fail-open:false}")
    private boolean failOpen;

    @Value("${security.recaptcha.timeout-ms:3000}")
    private long timeoutMs;

    /**
     * Exactly the paths a captcha is worth spending a round trip on.
     *
     * <p>
     * Suffix matches against the full request path, so they stay correct if
     * APP_ROOT changes — the endpoint constants are the same ones the
     * controllers build their mappings from.
     * </p>
     */
    private static final List<String> PROTECTED_SUFFIXES = List.of(
            "/authenticate",
            "/two-factor/verify",
            "/user/create",
            "/admin/create",
            "/send-link",
            "/resend-link",
            "/reset"
    );

    /** Only requests under these roots are candidates at all. */
    private static final List<String> PROTECTED_ROOTS = List.of(
            "/" + AUTHENTICATION_ENDPOINT,
            "/" + ACCOUNTS_ENDPOINT
    );

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {

        if (!enabled) {
            filterChain.doFilter(request, response);
            return;
        }

        String method = request.getMethod();
        String path = request.getServletPath();

        // A GET changes nothing and is not worth a captcha.
        if (HttpMethod.GET.matches(method) || !isProtected(path)) {
            filterChain.doFilter(request, response);
            return;
        }

        String recaptchaToken = request.getHeader("X-Recaptcha-Token");

        if (recaptchaToken == null || recaptchaToken.isBlank()) {
            log.warn("Missing reCAPTCHA token for {} {}", method, path);
            sendErrorResponse(response, HttpServletResponse.SC_BAD_REQUEST,
                    "Missing reCAPTCHA token");
            return;
        }

        if (!validateRecaptcha(recaptchaToken, clientIp(request), actionFor(path))) {
            log.warn("reCAPTCHA validation failed for {} {}", method, path);
            // 403, not 401: 401 means "your credentials were wrong" and would
            // send the client into a re-authentication loop over what is really
            // a bot check. The caller has not proved they are human.
            sendErrorResponse(response, HttpServletResponse.SC_FORBIDDEN,
                    "reCAPTCHA validation failed");
            return;
        }

        filterChain.doFilter(request, response);
    }

    // ----------------------------------------------------------------

    private boolean isProtected(String path) {
        if (path == null) return false;

        boolean underProtectedRoot = PROTECTED_ROOTS.stream().anyMatch(path::startsWith);
        if (!underProtectedRoot) return false;

        return PROTECTED_SUFFIXES.stream().anyMatch(path::endsWith);
    }

    private boolean validateRecaptcha(String token, String userIp, String action) {
        try {
            Map<String, Object> result = webClientBuilder.build()
                    .post()
                    .uri(recaptchaServiceUrl + "/internal/recaptcha/validate")
                    .header("X-API-Key", internalApiKey)
                    .contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(Map.of(
                            "token", token,
                            "userIp", userIp != null ? userIp : "",
                            "action", action
                    ))
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofMillis(timeoutMs))
                    .block();

            // A null body is not a pass. Without this the filter would admit
            // anything the service failed to answer for.
            return result != null && Boolean.TRUE.equals(result.get("success"));

        } catch (Exception e) {
            log.error("reCAPTCHA service call failed ({}) — {}",
                    e.getMessage(), failOpen ? "ALLOWING (fail-open)" : "rejecting");
            return failOpen;
        }
    }

    /**
     * The action name reCAPTCHA v3 scores against.
     *
     * <p>
     * It must match what the browser passed to {@code grecaptcha.execute}, or
     * the score is meaningless — Google returns the token's own action, and a
     * mismatch means the token was minted for a different page and possibly
     * replayed from one.
     * </p>
     */
    private String actionFor(String path) {
        String[] parts = path.split("/");
        for (int i = parts.length - 1; i >= 0; i--) {
            if (!parts[i].isEmpty()) {
                return parts[i];
            }
        }
        return "generic";
    }

    /**
     * The caller's IP, for reCAPTCHA's own risk scoring.
     *
     * <p>
     * {@code X-Forwarded-For} is trusted here only because this service sits
     * behind the gateway. Note the header is attacker-controlled on a direct
     * connection, so this value is a HINT passed to the scorer — it must never
     * be used for an access decision. Rate limiting, which does make decisions
     * from the IP, resolves it separately and honours only trusted proxies.
     * </p>
     */
    private String clientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            return forwarded.split(",")[0].trim();
        }
        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) {
            return realIp;
        }
        return request.getRemoteAddr();
    }

    private void sendErrorResponse(HttpServletResponse response, int status, String message)
            throws IOException {
        response.setStatus(status);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        response.getWriter().write(new ObjectMapper().writeValueAsString(Map.of(
                "success", false,
                "error", message,
                "timestamp", System.currentTimeMillis()
        )));
    }
}
