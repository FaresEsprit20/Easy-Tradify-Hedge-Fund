package com.trading.easytradify.auth.config.security.oauth2;

import com.trading.easytradify.auth.entities.UnifiedToken;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.auth.entities.enums.TokenType;
import com.trading.easytradify.auth.repository.UnifiedTokenRepository;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.codec.digest.DigestUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;

@Slf4j
@Service
@RequiredArgsConstructor
public class OAuth2TokenService {

    private final UnifiedTokenRepository tokenRepository;

    @Value("${application.security.ip-salt}")
    private String ipSalt;

    @Value("${application.security.trusted-proxies:}")
    private List<String> trustedProxies;

    // ============================================================
    // TOKEN GENERATION
    // ============================================================

    public String generateAccessToken() {
        return "at_" + UUID.randomUUID().toString().replace("-", "");
    }

    public String generateRefreshToken() {
        return "rt_" + UUID.randomUUID().toString().replace("-", "");
    }

    // ============================================================
    // TOKEN STORAGE & BINDING
    // ============================================================

    public UnifiedToken storeToken(String token, TokenType tokenType, Integer userId, String userEmail,
                                   HttpServletRequest request, int expirationMinutes) {

        String ipHash = hashIp(getValidatedIp(request));
        String uaHash = hashUserAgent(request);

        UnifiedToken unifiedToken = UnifiedToken.builder()
                .token(token)
                .tokenType(tokenType)
                .userEmail(userEmail)
                .ipHash(ipHash)
                .userAgentHash(uaHash)
                .expirationDate(LocalDateTime.now().plusMinutes(expirationMinutes))
                .revoked(false)
                .expired(false)
                .isUsed(false)
                .build();

        if (userId != null) {
            User user = new User();
            user.setId(userId);
            unifiedToken.setUser(user);
        }

        return tokenRepository.save(unifiedToken);
    }

    /**
     * Validate OAuth2 token - IP binding only (User-Agent validation removed for compatibility)
     */
    public Optional<UnifiedToken> validateToken(String token, HttpServletRequest request) {
        Optional<UnifiedToken> tokenOpt = tokenRepository.findOAuth2TokenByToken(token);

        if (tokenOpt.isEmpty()) {
            log.warn("Token not found: {}", token);
            return Optional.empty();
        }

        UnifiedToken unifiedToken = tokenOpt.get();

        if (unifiedToken.isRevoked() || unifiedToken.isExpired()) {
            log.warn("Token is revoked or expired: {}", token);
            return Optional.empty();
        }

        if (unifiedToken.getExpirationDate().isBefore(LocalDateTime.now())) {
            log.warn("Token expired: {}", token);
            return Optional.empty();
        }

        // Validate IP binding only (User-Agent validation removed)
        String currentIpHash = hashIp(getValidatedIp(request));
        if (!unifiedToken.getIpHash().equals(currentIpHash)) {
            log.warn("IP mismatch for token: {} (stored: {}, current: {})",
                    token, unifiedToken.getIpHash(), currentIpHash);
            return Optional.empty();
        }

        // User-Agent validation is SKIPPED - makes it work across different clients
        // String currentUaHash = hashUserAgent(request);
        // if (!unifiedToken.getUserAgentHash().equals(currentUaHash)) {
        //     log.warn("User-Agent mismatch for token: {}", token);
        //     return Optional.empty();
        // }

        return tokenOpt;
    }

    public Optional<String> refreshAccessToken(String refreshToken, HttpServletRequest request) {
        Optional<UnifiedToken> refreshTokenOpt = tokenRepository.findOAuth2TokenByToken(refreshToken);

        if (refreshTokenOpt.isEmpty()) {
            log.warn("Refresh token not found: {}", refreshToken);
            return Optional.empty();
        }

        UnifiedToken refreshTokenEntity = refreshTokenOpt.get();

        if (refreshTokenEntity.isRevoked() || refreshTokenEntity.isExpired() ||
                refreshTokenEntity.getExpirationDate().isBefore(LocalDateTime.now())) {
            log.warn("Refresh token invalid or expired");
            return Optional.empty();
        }

        String currentIpHash = hashIp(getValidatedIp(request));
        if (!refreshTokenEntity.getIpHash().equals(currentIpHash)) {
            log.warn("IP mismatch for refresh token");
            return Optional.empty();
        }

        String newAccessToken = generateAccessToken();

        storeToken(newAccessToken, TokenType.OAUTH2_ACCESS,
                refreshTokenEntity.getUser() != null ? refreshTokenEntity.getUser().getId() : null,
                refreshTokenEntity.getUserEmail(), request, 15);

        return Optional.of(newAccessToken);
    }

    public boolean revokeToken(String token) {
        Optional<UnifiedToken> tokenOpt = tokenRepository.findOAuth2TokenByToken(token);
        if (tokenOpt.isEmpty()) {
            return false;
        }

        UnifiedToken unifiedToken = tokenOpt.get();
        unifiedToken.setRevoked(true);
        unifiedToken.setExpired(true);
        tokenRepository.save(unifiedToken);

        log.info("Token revoked: {}", token);
        return true;
    }

    public void revokeAllUserTokens(Integer userId) {
        tokenRepository.revokeAllOAuth2TokensByUser(userId);
        log.info("All tokens revoked for user: {}", userId);
    }

    // ============================================================
    // IP & USER-AGENT METHODS
    // ============================================================

    public String hashIp(String ipAddress) {
        return DigestUtils.sha256Hex(ipAddress + ipSalt);
    }

    public String hashUserAgent(HttpServletRequest request) {
        String userAgent = request.getHeader("User-Agent");
        return DigestUtils.sha256Hex((userAgent != null ? userAgent : "unknown") + ipSalt);
    }

    public String getValidatedIp(HttpServletRequest request) {
        String ipChain = request.getHeader("X-Forwarded-For");
        String clientIp = null;

        if (ipChain != null && !ipChain.isEmpty()) {
            String[] ips = ipChain.split(",");
            for (int i = ips.length - 1; i >= 0; i--) {
                String ip = ips[i].trim();
                if (!isTrustedProxy(ip)) {
                    clientIp = ip;
                    break;
                }
            }
        }

        if (clientIp == null) clientIp = request.getRemoteAddr();
        validateIpFormat(clientIp);
        return normalizeLoopback(clientIp);
    }

    /**
     * Windows/Chrome can resolve "localhost" to either 127.0.0.1 or the IPv6
     * loopback (::1 / 0:0:0:0:0:0:0:1) depending on the request path — a
     * plain XHR vs. a full-page navigation (as happens mid-OAuth2 redirect)
     * can land on different loopback forms for the *same* machine. Without
     * this, IP-bound tokens issued on one form fail validation on the other.
     */
    private String normalizeLoopback(String ip) {
        if ("127.0.0.1".equals(ip) || "::1".equals(ip) || "0:0:0:0:0:0:0:1".equals(ip)) {
            return "127.0.0.1";
        }
        return ip;
    }

    private boolean isTrustedProxy(String ip) {
        return trustedProxies.contains(ip) || trustedProxies.stream().anyMatch(proxy -> ip.startsWith(proxy + "."));
    }

    private void validateIpFormat(String ip) {
        if (ip == null || ip.isEmpty()) {
            throw new SecurityException("IP address cannot be null or empty");
        }
        boolean isValidIpv4 = ip.matches("^(\\d{1,3}\\.){3}\\d{1,3}$");
        boolean isLocalhost = ip.equals("127.0.0.1") || ip.equals("0:0:0:0:0:0:0:1");
        boolean isIpv6 = ip.contains(":");
        if (!isValidIpv4 && !isLocalhost && !isIpv6) {
            throw new SecurityException("Invalid IP address format: " + ip);
        }
    }

    // ============================================================
    // FAKE TOKEN GENERATOR
    // ============================================================

    private static final String FAKE_PREFIX = "decoy_";
    private static final List<String> FAKE_SUBJECTS = Arrays.asList("anonymous", "guest", "system", "admin", "user");
    private static final List<String> FAKE_ROLES = Arrays.asList("FAKE_ADMIN", "FAKE_USER", "FAKE_READONLY");

    public String generateFakeAccessToken() {
        String fakeIp = ThreadLocalRandom.current().nextInt(256) + "." +
                ThreadLocalRandom.current().nextInt(256) + "." +
                ThreadLocalRandom.current().nextInt(256) + "." +
                ThreadLocalRandom.current().nextInt(256);

        return FAKE_PREFIX + UUID.randomUUID().toString().replace("-", "") + "_" +
                hashIp(fakeIp).substring(0, 16);
    }

    public boolean isFakeToken(String token) {
        if (token == null) return false;
        return token.startsWith(FAKE_PREFIX);
    }
}