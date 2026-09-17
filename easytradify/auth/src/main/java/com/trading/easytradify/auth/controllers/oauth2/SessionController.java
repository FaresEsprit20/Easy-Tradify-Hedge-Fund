package com.trading.easytradify.auth.controllers.oauth2;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
public class SessionController {

    @GetMapping("/session")
    public ResponseEntity<Map<String, Object>> getSessionInfo() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();

        if (authentication == null || !authentication.isAuthenticated()
                || "anonymousUser".equals(authentication.getPrincipal())) {
            return ResponseEntity.status(401).body(Map.of("authenticated", false));
        }

        Map<String, Object> sessionInfo = new HashMap<>();
        sessionInfo.put("authenticated", true);
        sessionInfo.put("email", authentication.getName());
        sessionInfo.put("roles", authentication.getAuthorities().stream()
                .map(auth -> auth.getAuthority())
                .toList());

        return ResponseEntity.ok(sessionInfo);
    }

    @GetMapping("/me")
    public ResponseEntity<Map<String, Object>> getCurrentUser(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()) {
            return ResponseEntity.status(401).body(Map.of("error", "Not authenticated"));
        }

        Map<String, Object> userInfo = new HashMap<>();
        userInfo.put("email", authentication.getName());
        userInfo.put("roles", authentication.getAuthorities().stream()
                .map(auth -> auth.getAuthority())
                .toList());

        return ResponseEntity.ok(userInfo);
    }
}