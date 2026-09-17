package com.trading.easytradify.auth.config.security.filters;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.Arrays;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

@EnableScheduling
@Component
@RequiredArgsConstructor
@Slf4j
public class RateLimitingFilter extends OncePerRequestFilter {

    @Value("${security.rate-limit.second:10}")
    private int maxPerSecond;

    @Value("${security.rate-limit.minute:100}")
    private int maxPerMinute;

    @Value("${security.rate-limit.enabled:true}")
    private boolean enabled;

    private static final long IP_TRACKER_TTL = TimeUnit.MINUTES.toMillis(5);

    private final ConcurrentHashMap<String, IpRateTracker> ipRequestTrackers = new ConcurrentHashMap<>();
    private final AntPathMatcher pathMatcher = new AntPathMatcher();

    @Scheduled(fixedRate = 60_000)
    public void cleanupOldTrackers() {
        long now = System.currentTimeMillis();
        ipRequestTrackers.entrySet().removeIf(entry ->
                now - entry.getValue().getLastAccessTime() > IP_TRACKER_TTL
        );
        log.debug("Cleaned up old IP trackers.");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws IOException, ServletException {
        if (!enabled || shouldExclude(request)) {
            chain.doFilter(request, response);
            return;
        }

        String clientIp = getClientIpDirect(request);
        if (clientIp == null) {
            log.warn("Blocked request due to invalid or suspicious IP");
            sendInvalidIpResponse(response);
            return;
        }

        IpRateTracker tracker = ipRequestTrackers.compute(clientIp, (k, v) ->
                (v == null || (System.currentTimeMillis() - v.getLastAccessTime() > IP_TRACKER_TTL))
                        ? new IpRateTracker(maxPerSecond, maxPerMinute)
                        : v
        );

        if (tracker.allowRequest()) {
            addRateLimitHeaders(response, tracker);
            chain.doFilter(request, response);
        } else {
            log.warn("Rate limit exceeded for IP: {}", clientIp);
            sendRateLimitExceeded(response);
        }
    }

    private String getClientIpDirect(HttpServletRequest request) {
        String ip = request.getRemoteAddr();
        log.debug("Incoming IP: {}", ip);

        if (!isValidIp(ip)) {
            log.warn("Invalid or disallowed IP detected: {}", ip);
            return null;
        }

        return ip;
    }

    private boolean isValidIp(String ip) {
        if (ip == null || ip.isEmpty()) {
            return false;
        }
        try {
            InetAddress inet = InetAddress.getByName(ip);

            if (inet.isMulticastAddress()) {
                return false;
            }

            // Allow loopback, private, reserved IPs
            return true;
        } catch (UnknownHostException e) {
            log.error("Failed to validate IP address: {}", ip, e);
            return false;
        }
    }

    private void sendInvalidIpResponse(HttpServletResponse response) throws IOException {
        response.setStatus(HttpStatus.FORBIDDEN.value());
        response.setContentType("application/json");
        response.getWriter().write(
                "{\"error\":\"invalid_ip\", " +
                        "\"message\":\"Request contains malformed or suspicious IP address headers\"}"
        );
    }

    /**
     * Paths the limiter does not count.
     *
     * <p>The price stream is here because it is one long-lived SSE connection
     * per session, not a repeatable request: counting it means an unlucky
     * ordering during a page-load burst rejects the stream and the user
     * silently loses live quotes for the rest of the session. It cannot be
     * used to amplify load — the server pushes on its own schedule regardless
     * of how many times a client connects.
     */
    private boolean shouldExclude(HttpServletRequest request) {
        return Arrays.asList(
                "/public/**",
                "/health",
                "/actuator/**",
                "/**/prices/stream"
        ).stream().anyMatch(pattern -> pathMatcher.match(pattern, request.getRequestURI()));
    }

    private void addRateLimitHeaders(HttpServletResponse response, IpRateTracker tracker) {
        response.setHeader("X-RateLimit-Limit-Second", String.valueOf(maxPerSecond));
        response.setHeader("X-RateLimit-Limit-Minute", String.valueOf(maxPerMinute));
        response.setHeader("X-RateLimit-Remaining-Second",
                String.valueOf(tracker.getRemainingSecond()));
        response.setHeader("X-RateLimit-Remaining-Minute",
                String.valueOf(tracker.getRemainingMinute()));
    }

    private void sendRateLimitExceeded(HttpServletResponse response) throws IOException {
        response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
        response.setContentType("application/json");
        response.getWriter().write(String.format(
                "{\"error\":\"rate_limit_exceeded\", " +
                        "\"message\":\"Maximum %d/second and %d/minute requests allowed\", " +
                        "\"retry_after_seconds\":%d}",
                maxPerSecond,
                maxPerMinute,
                60 - (System.currentTimeMillis() / 1000 % 60)
        ));
    }

}
