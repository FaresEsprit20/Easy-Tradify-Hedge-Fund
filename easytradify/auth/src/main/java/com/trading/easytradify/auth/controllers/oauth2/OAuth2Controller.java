package com.trading.easytradify.auth.controllers.oauth2;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/oauth2")
public class OAuth2Controller {

    @GetMapping("/error")
    public ResponseEntity<Map<String, Object>> handleError(
            @RequestParam(value = "message", required = false) String message,
            @RequestParam(value = "error", required = false) String error) {

        log.error("OAuth2 error: message={}, error={}", message, error);

        Map<String, Object> response = new HashMap<>();
        response.put("success", false);
        response.put("error", error != null ? error : "authentication_failed");
        response.put("message", message != null ? message : "Authentication failed");

        return ResponseEntity.badRequest().body(response);
    }

    @GetMapping("/success")
    public ResponseEntity<Map<String, Object>> handleSuccess(
            @RequestParam(value = "accessToken", required = false) String accessToken,
            @RequestParam(value = "refreshToken", required = false) String refreshToken) {

        log.info("OAuth2 success - accessToken: {}, refreshToken: {}", accessToken, refreshToken);

        Map<String, Object> response = new HashMap<>();
        response.put("success", true);
        response.put("accessToken", accessToken);
        response.put("refreshToken", refreshToken);

        return ResponseEntity.ok(response);
    }
}