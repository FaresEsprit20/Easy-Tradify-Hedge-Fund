package com.trading.easytradify.auth.config.security.config;

import com.trading.easytradify.auth.entities.UnifiedToken;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.auth.repository.UnifiedTokenRepository;
import com.trading.easytradify.auth.services.users.CustomUserDetailsService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.oauth2.core.OAuth2AuthenticatedPrincipal;
import org.springframework.security.oauth2.core.OAuth2TokenIntrospectionClaimNames;
import org.springframework.security.oauth2.server.resource.introspection.OAuth2IntrospectionAuthenticatedPrincipal;
import org.springframework.security.oauth2.server.resource.introspection.OpaqueTokenIntrospector;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Component
@RequiredArgsConstructor
public class OAuth2ResourceServer implements OpaqueTokenIntrospector {

    private final UnifiedTokenRepository tokenRepository;
    private final CustomUserDetailsService userDetailsService;

    @Override
    @Transactional
    public OAuth2AuthenticatedPrincipal introspect(String token) {
        log.debug("Resource Server validating token: {}", token.substring(0, Math.min(20, token.length())));

        // Find token in database
        Optional<UnifiedToken> tokenOpt = tokenRepository.findOAuth2TokenByToken(token);

        if (tokenOpt.isEmpty()) {
            log.warn("Token not found in database");
            throw new RuntimeException("Invalid token");
        }

        UnifiedToken unifiedToken = tokenOpt.get();

        // Check if token is valid
        if (unifiedToken.isRevoked() || unifiedToken.isExpired() ||
                unifiedToken.getExpirationDate().isBefore(LocalDateTime.now())) {
            log.warn("Token revoked or expired");
            throw new RuntimeException("Token expired or revoked");
        }

        // Get user with roles from database - FETCH EAGERLY
        User user;
        if (unifiedToken.getUser() != null) {
            user = unifiedToken.getUser();
        } else {
            user = (User) userDetailsService.loadUserByUsername(unifiedToken.getUserEmail());
        }

        // Force initialization of authorities while in transaction
        Collection<GrantedAuthority> authorities = new ArrayList<>(user.getAuthorities());

        // Build introspection claims with roles
        Map<String, Object> claims = new HashMap<>();
        claims.put(OAuth2TokenIntrospectionClaimNames.ACTIVE, true);
        claims.put(OAuth2TokenIntrospectionClaimNames.USERNAME, user.getEmail());
        claims.put(OAuth2TokenIntrospectionClaimNames.SUB, user.getId().toString());
        claims.put("email", user.getEmail());
        claims.put("user_id", user.getId());
        claims.put("roles", authorities.stream()
                .map(GrantedAuthority::getAuthority)
                .toList());

        log.info("Resource Server: Token valid for user: {}, roles: {}", user.getEmail(), authorities);

        // Return authenticated principal with roles
        return new OAuth2IntrospectionAuthenticatedPrincipal(
                user.getEmail(),
                claims,
                authorities
        );
    }
}