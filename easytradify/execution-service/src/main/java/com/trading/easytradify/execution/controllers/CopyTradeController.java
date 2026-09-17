package com.trading.easytradify.execution.controllers;

import com.trading.easytradify.execution.models.*;
import com.trading.easytradify.execution.services.CopyTradeService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * <h1>Copy Trade Controller</h1>
 * <p>
 * Concrete implementation of the {@link CopyTradeApi} interface.
 * This controller handles all REST endpoints for copy trade execution
 * and webhook processing.
 * </p>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Thin Controller:</b> All business logic is delegated to the service layer</li>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Validation:</b> All requests are validated via {@code @Valid}</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * <h2>Error Handling</h2>
 * <p>
 * This controller relies on the {@code GlobalExceptionHandler} for consistent
 * error responses. All exceptions propagate through the call stack without
 * being caught locally.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see CopyTradeApi
 * @see CopyTradeService
 */
@RestController
@RequiredArgsConstructor
@Slf4j
public class CopyTradeController implements CopyTradeApi {

    private final CopyTradeService copyTradeService;

    // ============================================================
    // COPY TRADE EXECUTION
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<CopyTradeResponse> executeCopyTrade(CopyTradeRequest request) {
        log.info("[CopyTrade] Received execute request for: {}", request.symbol());
        var response = copyTradeService.executeCopyTrade(request);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // WEBHOOK ENDPOINTS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<WebhookResponse> webhookTrade(WebhookTradeRequest request) {
        log.info("[CopyTrade] Received trade webhook: {} (Ticket: {})", request.symbol(), request.ticket());
        var response = copyTradeService.handleWebhookTrade(request);
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<WebhookResponse> webhookTrailing(WebhookTrailingRequest request) {
        log.info("[CopyTrade] Received trailing webhook: Ticket {}", request.ticket());
        var response = copyTradeService.handleWebhookTrailing(request);
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<WebhookResponse> webhookTest(Object payload) {
        log.info("[CopyTrade] Received webhook test");
        var response = copyTradeService.webhookTest(payload);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // STATUS & HEALTH ENDPOINTS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<Map<String, Object>> webhookHealth() {
        log.debug("[CopyTrade] Webhook health check");
        var response = copyTradeService.getWebhookHealth();
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<Map<String, Object>> webhookDebug() {
        log.debug("[CopyTrade] Getting webhook debug info");
        var response = copyTradeService.getWebhookDebug();
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<Map<String, Object>> getStatus() {
        log.debug("[CopyTrade] Getting executor status");
        var response = copyTradeService.getStatus();
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<HealthResponse> healthCheck() {
        log.debug("[CopyTrade] Health check");
        var response = copyTradeService.healthCheck();
        return ResponseEntity.ok(response);
    }
}