package com.trading.easytradify.auth.config.security.config;

import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.codec.digest.DigestUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.List;

@Slf4j
@Component
public class IpUaExtractor {

    @Value("${application.security.ip-salt:d6f644b79a844c8a9b32f12e4a7c8d1e5f309a8714b247d5c12e8a7d6f4b29a}")
    private String ipSalt;

    @Value("${application.security.trusted-proxies:}")
    private List<String> trustedProxies;

    public String hashIp(HttpServletRequest request) {
        String ip = getValidatedIp(request);
        return DigestUtils.sha256Hex(ip + ipSalt);
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
        return trustedProxies.contains(ip);
    }
}