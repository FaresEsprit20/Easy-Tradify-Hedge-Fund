package com.trading.easytradify.ai.controllers;

import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.AdversarialIntensityRequest;
import com.trading.easytradify.ai.models.adverserial.*;
import com.trading.easytradify.ai.models.gnn.*;
import com.trading.easytradify.ai.services.AIService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.util.Arrays;
import java.util.List;

/**
 * <h1>AI Controller</h1>
 * <p>
 * Concrete implementation of the {@link AIApi} interface.
 * This controller handles all REST endpoints for AI-powered trading intelligence.
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
 * @see AIApi
 * @see AIService
 */
@RestController
@RequiredArgsConstructor
@Slf4j
public class AIController implements AIApi {

    private final AIService aiService;

    // ============================================================
    // HEALTH
    // ============================================================

    @Override
    public ResponseEntity<AIHealthResponse> healthCheck() {
        log.debug("[AIController] Health check");
        var response = aiService.healthCheck();
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // GNN ENDPOINTS (14)
    // ============================================================

    @Override
    public ResponseEntity<GnnStatusResponse> getGnnStatus() {
        log.info("[AIController] Getting GNN status");
        var response = aiService.getGnnStatus();
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnContextResponse> getGnnContext(String symbol, Integer tradeId) {
        log.info("[AIController] Getting GNN context for: {} (tradeId: {})", symbol, tradeId);
        var response = aiService.getGnnContext(symbol, tradeId);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnInsightsResponse> getGnnInsights(String symbol, String analysisDirection) {
        log.info("[AIController] Getting GNN insights for: {} (direction: {})", symbol, analysisDirection);
        var response = aiService.getGnnInsights(symbol, analysisDirection);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnCorrelationsResponse> getGnnCorrelations(String symbol) {
        log.info("[AIController] Getting GNN correlations for: {}", symbol);
        var response = aiService.getGnnCorrelations(symbol);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnDivergencesResponse> getGnnDivergences(String symbol) {
        log.info("[AIController] Getting GNN divergences for: {}", symbol);
        var response = aiService.getGnnDivergences(symbol);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnSuggestionsResponse> getGnnSuggestions(String symbol) {
        log.info("[AIController] Getting GNN suggestions for: {}", symbol);
        var response = aiService.getGnnSuggestions(symbol);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnConflictResponse> getGnnConflict(String symbol, String analysisDirection) {
        log.info("[AIController] Getting GNN conflict for: {} (direction: {})", symbol, analysisDirection);
        var response = aiService.getGnnConflict(symbol, analysisDirection);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnAbTestResponse> getGnnAbTest() {
        log.info("[AIController] Getting GNN A/B test results");
        var response = aiService.getGnnAbTest();
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnHeatmapResponse> getGnnHeatmap(String symbols) {
        log.info("[AIController] Getting GNN heatmap for symbols: {}", symbols);
        List<String> symbolList = null;
        if (symbols != null && !symbols.isEmpty()) {
            symbolList = Arrays.asList(symbols.split(","));
        }
        var response = aiService.getGnnHeatmap(symbolList);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnCorrelationChangesResponse> getGnnCorrelationChanges(String symbol, int lookback) {
        log.info("[AIController] Getting GNN correlation changes for: {} (lookback: {})", symbol, lookback);
        var response = aiService.getGnnCorrelationChanges(symbol, lookback);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnRefreshResponse> refreshGnn() {
        log.info("[AIController] Refreshing GNN");
        var response = aiService.refreshGnn();
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnResetResponse> resetGnn() {
        log.info("[AIController] Resetting GNN");
        var response = aiService.resetGnn();
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnRolloutResponse> setGnnAbTestRollout(GnnRolloutRequest request) {
        log.info("[AIController] Setting GNN A/B test rollout to: {}%", request.rollout() * 100);
        var response = aiService.setGnnAbTestRollout(request.rollout());
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<GnnTrackResultResponse> trackGnnResult(GnnTrackResultRequest request) {
        log.info("[AIController] Tracking GNN result for trade: {}", request.tradeId());
        var response = aiService.trackGnnResult(request);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // ADVERSARIAL ENDPOINTS (6)
    // ============================================================

    @Override
    public ResponseEntity<AdversarialStatusResponse> getAdversarialStatus() {
        log.info("[AIController] Getting adversarial status");
        var response = aiService.getAdversarialStatus();
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<AdversarialGenerateResponse> generateAdversarialAttacks(AdversarialGenerateRequest request) {
        log.info("[AIController] Generating adversarial attacks");
        var response = aiService.generateAdversarialAttacks(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<AdversarialTrainResponse> trainAdversarial(AdversarialTrainRequest request) {
        log.info("[AIController] Training adversarial on {} trades",
                request.trades() != null ? request.trades().size() : 0);
        var response = aiService.trainAdversarial(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<AdversarialMetricsResponse> getAdversarialMetrics() {
        log.info("[AIController] Getting adversarial metrics");
        var response = aiService.getAdversarialMetrics();
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<AdversarialIntensityResponse> setAdversarialIntensity(AdversarialIntensityRequest request) {
        log.info("[AIController] Setting adversarial intensity to: {}", request.intensity());
        var response = aiService.setAdversarialIntensity(request.intensity());
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<AdversarialEnableResponse> enableAdversarial(AdversarialEnableRequest request) {
        log.info("[AIController] Setting adversarial enabled: {}", request.enabled());
        var response = aiService.enableAdversarial(request.enabled());
        return ResponseEntity.ok(response);
    }
}