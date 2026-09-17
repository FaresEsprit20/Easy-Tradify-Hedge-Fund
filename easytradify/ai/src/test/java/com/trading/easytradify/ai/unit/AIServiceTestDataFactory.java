package com.trading.easytradify.ai.unit;

import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.AdversarialIntensityRequest;
import com.trading.easytradify.ai.models.adverserial.*;
import com.trading.easytradify.ai.models.gnn.*;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * Factory for creating AI service test data.
 * Centralizes test fixture creation to avoid duplication.
 */
public final class AIServiceTestDataFactory {

    private AIServiceTestDataFactory() {
        // Private constructor
    }

    // ============================================================
    // HEALTH RESPONSE FIXTURES
    // ============================================================

    public static AIHealthResponse validHealthResponse() {
        return new AIHealthResponse(
                "healthy",
                "ai_controller",
                5002,
                true,
                Map.of(
                        "available", true,
                        "enabled", true,
                        "ready", true,
                        "assets", 50
                ),
                Map.of(
                        "available", true,
                        "enabled", true
                ),
                Instant.now().toString(),
                null
        );
    }

    public static AIHealthResponse errorHealthResponse() {
        return new AIHealthResponse(
                "error",
                null,
                null,
                false,
                null,
                null,
                null,
                "Service unavailable"
        );
    }

    // ============================================================
    // GNN STATUS RESPONSE FIXTURES
    // ============================================================

    public static GnnStatusResponse validGnnStatusResponse() {
        var status = Map.<String, Object>ofEntries(
                Map.entry("enabled", true),
                Map.entry("ready", true),
                Map.entry("assets", 50),
                Map.entry("update_interval", 60),
                Map.entry("ab_test_enabled", true),
                Map.entry("ab_test_rollout", 0.5)
        );
        return GnnStatusResponse.success(status);
    }

    public static GnnStatusResponse errorGnnStatusResponse(String error) {
        return GnnStatusResponse.error(error);
    }

    // ============================================================
    // GNN CONTEXT RESPONSE FIXTURES
    // ============================================================

    public static GnnContextResponse validGnnContextResponse() {
        var context = Map.<String, Object>ofEntries(
                Map.entry("dxy_strength", 0.65),
                Map.entry("risk_sentiment", -0.30),
                Map.entry("commodity_impact", 0.20),
                Map.entry("sector_sentiment", 0.15),
                Map.entry("global_confidence", 0.80),
                Map.entry("trend_alignment", 0.75),
                Map.entry("market_regime", "TRENDING"),
                Map.entry("correlation_shift", 0.10),
                Map.entry("gnn_influence", 0.60),
                Map.entry("gnn_connections", List.of(
                        Map.of("symbol", "EURUSD", "weight", 0.85),
                        Map.of("symbol", "GBPUSD", "weight", 0.70)
                ))
        );
        return GnnContextResponse.success("EURUSD", context);
    }

    public static GnnContextResponse errorGnnContextResponse(String error) {
        return GnnContextResponse.error(error);
    }

    // ============================================================
    // GNN INSIGHTS RESPONSE FIXTURES
    // ============================================================

    public static GnnInsightsResponse validGnnInsightsResponse() {
        var insights = Map.<String, Object>ofEntries(
                Map.entry("price_direction", 0.75),
                Map.entry("gnn_direction", 0.80),
                Map.entry("correlations", List.of(
                        Map.of("symbol", "GBPUSD", "correlation", 0.85),
                        Map.of("symbol", "USDCHF", "correlation", -0.65)
                )),
                Map.entry("divergence", Map.of(
                        "detected", false,
                        "type", "NONE"
                )),
                Map.entry("suggestions", List.of(
                        Map.of("symbol", "GBPUSD", "action", "BUY", "confidence", 0.80),
                        Map.of("symbol", "AUDUSD", "action", "SELL", "confidence", 0.70)
                ))
                // Removed null entry - Map.entry does not accept null values
        );
        return GnnInsightsResponse.success("EURUSD", insights);
    }

    public static GnnInsightsResponse errorGnnInsightsResponse(String error) {
        return GnnInsightsResponse.error(error);
    }

    // ============================================================
    // GNN CORRELATIONS RESPONSE FIXTURES
    // ============================================================

    public static GnnCorrelationsResponse validGnnCorrelationsResponse() {
        var correlations = List.<Map<String, Object>>of(
                Map.of("symbol", "GBPUSD", "correlation", 0.85, "confidence", 0.90),
                Map.of("symbol", "USDCHF", "correlation", -0.65, "confidence", 0.85)
        );
        return GnnCorrelationsResponse.success("EURUSD", correlations);
    }

    public static GnnCorrelationsResponse errorGnnCorrelationsResponse(String error) {
        return GnnCorrelationsResponse.error(error);
    }

    // ============================================================
    // GNN DIVERGENCES RESPONSE FIXTURES
    // ============================================================

    public static GnnDivergencesResponse validGnnDivergencesResponse() {
        var divergence = Map.<String, Object>of(
                "detected", false,
                "type", "NONE",
                "gnn_direction", 0.80,
                "price_direction", 0.75,
                "reason", "No divergence detected"
        );
        return GnnDivergencesResponse.success("EURUSD", divergence);
    }

    public static GnnDivergencesResponse errorGnnDivergencesResponse(String error) {
        return GnnDivergencesResponse.error(error);
    }

    // ============================================================
    // GNN SUGGESTIONS RESPONSE FIXTURES
    // ============================================================

    public static GnnSuggestionsResponse validGnnSuggestionsResponse() {
        var suggestions = List.<Map<String, Object>>of(
                Map.of("symbol", "GBPUSD", "action", "BUY", "confidence", 0.80),
                Map.of("symbol", "AUDUSD", "action", "SELL", "confidence", 0.70)
        );
        return GnnSuggestionsResponse.success("EURUSD", suggestions);
    }

    public static GnnSuggestionsResponse errorGnnSuggestionsResponse(String error) {
        return GnnSuggestionsResponse.error(error);
    }

    // ============================================================
    // GNN CONFLICT RESPONSE FIXTURES
    // ============================================================

    public static GnnConflictResponse validGnnConflictResponse() {
        return GnnConflictResponse.success(
                "EURUSD",
                "BUY",
                Map.of(
                        "severity", "NONE",
                        "message", "Your analysis aligns with GNN"
                ),
                Map.of(
                        "price_direction", 0.75,
                        "gnn_direction", 0.80,
                        "divergence_detected", false
                )
        );
    }

    public static GnnConflictResponse conflictDetectedResponse() {
        return GnnConflictResponse.success(
                "EURUSD",
                "BUY",
                Map.of(
                        "severity", "HIGH",
                        "message", "Strong contradiction: GNN suggests SELL"
                ),
                Map.of(
                        "price_direction", 0.75,
                        "gnn_direction", -0.80,
                        "divergence_detected", true
                )
        );
    }

    public static GnnConflictResponse errorGnnConflictResponse(String error) {
        return GnnConflictResponse.error(error);
    }

    // ============================================================
    // GNN AB TEST RESPONSE FIXTURES
    // ============================================================

    public static GnnAbTestResponse validGnnAbTestResponse() {
        var results = Map.<String, Object>ofEntries(
                Map.entry("gnn_trades", 100),
                Map.entry("non_gnn_trades", 100),
                Map.entry("gnn_win_rate", 65.0),
                Map.entry("non_gnn_win_rate", 55.0),
                Map.entry("gnn_total_profit", 5000.0),
                Map.entry("non_gnn_total_profit", 3500.0),
                Map.entry("significant", true)
        );
        return GnnAbTestResponse.success(results);
    }

    public static GnnAbTestResponse errorGnnAbTestResponse(String error) {
        return GnnAbTestResponse.error(error);
    }

    // ============================================================
    // GNN HEATMAP RESPONSE FIXTURES
    // ============================================================

    public static GnnHeatmapResponse validGnnHeatmapResponse() {
        var heatmap = Map.<String, Object>ofEntries(
                Map.entry("symbols", List.of("EURUSD", "GBPUSD", "USDCHF")),
                Map.entry("matrix", List.of(
                        List.of(1.0, 0.85, -0.65),
                        List.of(0.85, 1.0, -0.70),
                        List.of(-0.65, -0.70, 1.0)
                ))
        );
        return GnnHeatmapResponse.success(heatmap);
    }

    public static GnnHeatmapResponse errorGnnHeatmapResponse(String error) {
        return GnnHeatmapResponse.error(error);
    }

    // ============================================================
    // GNN CORRELATION CHANGES RESPONSE FIXTURES
    // ============================================================

    public static GnnCorrelationChangesResponse validGnnCorrelationChangesResponse() {
        var changes = List.<Map<String, Object>>of(
                Map.of("symbol", "GBPUSD", "change", 0.15, "significance", "HIGH"),
                Map.of("symbol", "USDCHF", "change", -0.10, "significance", "MEDIUM")
        );
        return GnnCorrelationChangesResponse.success("EURUSD", changes);
    }

    public static GnnCorrelationChangesResponse errorGnnCorrelationChangesResponse(String error) {
        return GnnCorrelationChangesResponse.error(error);
    }

    // ============================================================
    // GNN REFRESH RESPONSE FIXTURES
    // ============================================================

    public static GnnRefreshResponse validGnnRefreshResponse() {
        return GnnRefreshResponse.success("GNN cache cleared, will refresh on next update");
    }

    public static GnnRefreshResponse errorGnnRefreshResponse(String error) {
        return GnnRefreshResponse.error(error);
    }

    // ============================================================
    // GNN RESET RESPONSE FIXTURES
    // ============================================================

    public static GnnResetResponse validGnnResetResponse() {
        return GnnResetResponse.success("GNN state reset successfully");
    }

    public static GnnResetResponse errorGnnResetResponse(String error) {
        return GnnResetResponse.error(error);
    }

    // ============================================================
    // GNN ROLLOUT RESPONSE FIXTURES
    // ============================================================

    public static GnnRolloutResponse validGnnRolloutResponse() {
        return GnnRolloutResponse.success("A/B test rollout set to 50%", 0.5);
    }

    public static GnnRolloutResponse errorGnnRolloutResponse(String error) {
        return GnnRolloutResponse.error(error);
    }

    // ============================================================
    // GNN TRACK RESULT RESPONSE FIXTURES
    // ============================================================

    public static GnnTrackResultResponse validGnnTrackResultResponse() {
        return GnnTrackResultResponse.success("GNN result tracked successfully");
    }

    public static GnnTrackResultResponse errorGnnTrackResultResponse(String error) {
        return GnnTrackResultResponse.error(error);
    }

    // ============================================================
    // ADVERSARIAL STATUS RESPONSE FIXTURES
    // ============================================================

    public static AdversarialStatusResponse validAdversarialStatusResponse() {
        var status = Map.<String, Object>ofEntries(
                Map.entry("enabled", true),
                Map.entry("intensity", 0.5),
                Map.entry("variations_per_trade", 5),
                Map.entry("total_attacks", 150),
                Map.entry("buffer_size", 50)
        );
        return AdversarialStatusResponse.success(status);
    }

    public static AdversarialStatusResponse errorAdversarialStatusResponse(String error) {
        return AdversarialStatusResponse.error(error);
    }

    // ============================================================
    // ADVERSARIAL GENERATE RESPONSE FIXTURES
    // ============================================================

    public static AdversarialGenerateResponse validAdversarialGenerateResponse() {
        var attackedTrades = List.<Map<String, Object>>of(
                Map.of("symbol", "EURUSD", "attacked", true, "variation", 1),
                Map.of("symbol", "EURUSD", "attacked", true, "variation", 2)
        );
        return AdversarialGenerateResponse.success(attackedTrades, 2, true);
    }

    public static AdversarialGenerateResponse errorAdversarialGenerateResponse(String error) {
        return AdversarialGenerateResponse.error(error);
    }

    // ============================================================
    // ADVERSARIAL TRAIN RESPONSE FIXTURES
    // ============================================================

    public static AdversarialTrainResponse validAdversarialTrainResponse() {
        var result = Map.<String, Object>of(
                "improvement", 0.05,
                "trained_count", 10,
                "success", true
        );
        return AdversarialTrainResponse.success(result, true);
    }

    public static AdversarialTrainResponse errorAdversarialTrainResponse(String error) {
        return AdversarialTrainResponse.error(error);
    }

    // ============================================================
    // ADVERSARIAL METRICS RESPONSE FIXTURES
    // ============================================================

    public static AdversarialMetricsResponse validAdversarialMetricsResponse() {
        var metrics = Map.<String, Object>ofEntries(
                Map.entry("total_attacks", 150),
                Map.entry("attacks_applied", 120),
                Map.entry("trades_attacked", 100),
                Map.entry("success_rate", 0.80),
                Map.entry("diversity_score", 0.75)
        );
        return AdversarialMetricsResponse.success(metrics);
    }

    public static AdversarialMetricsResponse errorAdversarialMetricsResponse(String error) {
        return AdversarialMetricsResponse.error(error);
    }

    // ============================================================
    // ADVERSARIAL INTENSITY RESPONSE FIXTURES
    // ============================================================

    public static AdversarialIntensityResponse validAdversarialIntensityResponse() {
        return AdversarialIntensityResponse.success("Attack intensity set to 0.50", 0.5);
    }

    public static AdversarialIntensityResponse errorAdversarialIntensityResponse(String error) {
        return AdversarialIntensityResponse.error(error);
    }

    // ============================================================
    // ADVERSARIAL ENABLE RESPONSE FIXTURES
    // ============================================================

    public static AdversarialEnableResponse validAdversarialEnableResponse() {
        return AdversarialEnableResponse.success("Adversarial training enabled", true);
    }

    public static AdversarialEnableResponse errorAdversarialEnableResponse(String error) {
        return AdversarialEnableResponse.error(error);
    }

    // ============================================================
    // REQUEST FIXTURES
    // ============================================================

    public static GnnTrackResultRequest validGnnTrackResultRequest() {
        return new GnnTrackResultRequest(123456789, 50.0, 1, true);
    }

    public static AdversarialGenerateRequest validAdversarialGenerateRequest() {
        var trade = Map.<String, Object>of(
                "symbol", "EURUSD",
                "entry", 1.12345,
                "stop_loss", 1.12245,
                "take_profit", 1.12545
        );
        return new AdversarialGenerateRequest(trade, 1, 5);
    }

    public static AdversarialTrainRequest validAdversarialTrainRequest() {
        var trades = List.<Map<String, Object>>of(
                Map.of("symbol", "EURUSD", "entry", 1.12345),
                Map.of("symbol", "GBPUSD", "entry", 1.23456)
        );
        var outcomes = List.of(1, 0);
        return new AdversarialTrainRequest(trades, outcomes, "EURUSD", "component1", true);
    }

    public static GnnRolloutRequest validGnnRolloutRequest() {
        return new GnnRolloutRequest(0.5);
    }

    public static AdversarialIntensityRequest validAdversarialIntensityRequest() {
        return new AdversarialIntensityRequest(0.5);
    }

    public static AdversarialEnableRequest validAdversarialEnableRequest() {
        return new AdversarialEnableRequest(true);
    }

}