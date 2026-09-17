package com.trading.easytradify.ai.services;

import com.trading.easytradify.ai.client.PythonAIServiceClient;
import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.adverserial.*;
import com.trading.easytradify.ai.models.gnn.*;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * <h1>AI Service Implementation</h1>
 * <p>
 * Default implementation of the {@link AIService} interface.
 * This service acts as a facade between the application layer and the
 * Python AI service (port 5002).
 * </p>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Thin Service:</b> All business logic is delegated to the Python client</li>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Declarative Validation:</b> Input validation is explicit and throws domain exceptions</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * <h2>Error Handling Strategy</h2>
 * <ol>
 *   <li>Validate inputs → throws {@link TradingException} if invalid</li>
 *   <li>Delegate to client → returns a response object</li>
 *   <li>Check response success flag → throws {@link TradingException} if {@code false}</li>
 *   <li>Return successful response to caller</li>
 * </ol>
 *
 * <h2>Validation Rules</h2>
 * <ul>
 *   <li>Symbol must not be null or empty</li>
 *   <li>Analysis direction must be BUY, SELL, or HOLD</li>
 *   <li>Rollout must be between 0.0 and 1.0</li>
 *   <li>Intensity must be between 0.0 and 1.0</li>
 *   <li>Lookback must be positive</li>
 *   <li>Trade ID must be positive</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see AIService
 * @see PythonAIServiceClient
 * @see TradingException
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class AIServiceImpl implements AIService {

    private final PythonAIServiceClient aiClient;

    // ============================================================
    // VALIDATION HELPERS
    // ============================================================

    /**
     * Validates that a symbol is not {@code null} or empty.
     *
     * @param symbol The symbol to validate
     * @throws TradingException If the symbol is {@code null} or empty
     */
    private void validateSymbol(String symbol) {
        if (!StringUtils.hasText(symbol)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_INVALID_SYMBOL)
                    .message("Symbol cannot be null or empty")
                    .build();
        }
    }

    /**
     * Validates that an analysis direction is valid.
     *
     * @param direction The direction to validate
     * @throws TradingException If the direction is invalid
     */
    private void validateAnalysisDirection(String direction) {
        if (direction != null) {
            String upper = direction.toUpperCase();
            if (!"BUY".equals(upper) && !"SELL".equals(upper) && !"HOLD".equals(upper)) {
                throw TradingException.builder()
                        .errorCode(ErrorCodes.GNN_INVALID_SYMBOL)
                        .message("Analysis direction must be BUY, SELL, or HOLD: " + direction)
                        .build();
            }
        }
    }

    /**
     * Validates that a rollout value is between 0.0 and 1.0.
     *
     * @param rollout The rollout value to validate
     * @throws TradingException If the rollout is outside the valid range
     */
    private void validateRollout(double rollout) {
        if (rollout < 0.0 || rollout > 1.0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_ROLLOUT_UPDATE_FAILED)
                    .message("Rollout must be between 0.0 and 1.0: " + rollout)
                    .build();
        }
    }

    /**
     * Validates that an intensity value is between 0.0 and 1.0.
     *
     * @param intensity The intensity value to validate
     * @throws TradingException If the intensity is outside the valid range
     */
    private void validateIntensity(double intensity) {
        if (intensity < 0.0 || intensity > 1.0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_INVALID_INTENSITY)
                    .message("Intensity must be between 0.0 and 1.0: " + intensity)
                    .build();
        }
    }

    /**
     * Validates that a lookback value is positive.
     *
     * @param lookback The lookback value to validate
     * @throws TradingException If the lookback is not positive
     */
    private void validateLookback(int lookback) {
        if (lookback <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message("Lookback must be positive: " + lookback)
                    .build();
        }
    }

    /**
     * Validates a track result request.
     *
     * @param request The request to validate
     * @throws TradingException If the request is invalid
     */
    private void validateTrackResultRequest(GnnTrackResultRequest request) {
        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Track result request cannot be null")
                    .build();
        }
        if (request.tradeId() == null || request.tradeId() <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Trade ID must be positive: " + request.tradeId())
                    .build();
        }
    }

    /**
     * Validates an adversarial generate request.
     *
     * @param request The request to validate
     * @throws TradingException If the request is invalid
     */
    private void validateAdversarialGenerateRequest(AdversarialGenerateRequest request) {
        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Adversarial generate request cannot be null")
                    .build();
        }
        if (request.trade() == null || request.trade().isEmpty()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_NO_TRADES_PROVIDED)
                    .message("Trade data is required for adversarial generation")
                    .build();
        }
        if (request.outcome() == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Outcome is required for adversarial generation")
                    .build();
        }
    }

    /**
     * Validates an adversarial train request.
     *
     * @param request The request to validate
     * @throws TradingException If the request is invalid
     */
    private void validateAdversarialTrainRequest(AdversarialTrainRequest request) {
        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Adversarial train request cannot be null")
                    .build();
        }
        if (request.trades() == null || request.trades().isEmpty()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_NO_TRADES_PROVIDED)
                    .message("Trades data is required for adversarial training")
                    .build();
        }
        if (request.outcomes() == null || request.outcomes().isEmpty()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Outcomes are required for adversarial training")
                    .build();
        }
        if (request.trades().size() != request.outcomes().size()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_OUTCOMES_MISMATCH)
                    .message("Trades and outcomes length mismatch: " +
                            request.trades().size() + " vs " + request.outcomes().size())
                    .build();
        }
    }

    /**
     * Checks if a response was successful and throws an exception if not.
     *
     * @param success    Whether the response was successful
     * @param error      The error message
     * @param errorCode  The error code to use
     * @param message    The error message prefix
     * @throws TradingException If the response indicates failure
     */
    private void checkResponse(boolean success, String error, ErrorCodes errorCode, String message) {
        if (!success) {
            throw TradingException.builder()
                    .errorCode(errorCode)
                    .message(message + ": " + (error != null ? error : "Unknown error"))
                    .build();
        }
    }

    // ============================================================
    // HEALTH
    // ============================================================

    @Override
    public AIHealthResponse healthCheck() {
        log.info("[AIService] Health check");

        try {
            return aiClient.healthCheck();
        } catch (Exception e) {
            log.warn("[AIService] Health check failed: {}", e.getMessage());
            return AIHealthResponse.error("Service unavailable");
        }
    }

    // ============================================================
    // GNN ENDPOINTS
    // ============================================================

    @Override
    public GnnStatusResponse getGnnStatus() {
        log.info("[AIService] Getting GNN status");

        var response = aiClient.getGnnStatus();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_NOT_INITIALIZED)
                    .message("Failed to get GNN status: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public GnnContextResponse getGnnContext(String symbol, Integer tradeId) {
        log.info("[AIService] Getting GNN context for: {} (tradeId: {})", symbol, tradeId);

        validateSymbol(symbol);

        var response = aiClient.getGnnContext(symbol, tradeId);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_CONTEXT_FETCH_FAILED)
                    .message("Failed to get GNN context for " + symbol + ": " + response.error())
                    .symbol(symbol)
                    .build();
        }

        return response;
    }

    @Override
    public GnnInsightsResponse getGnnInsights(String symbol, String analysisDirection) {
        log.info("[AIService] Getting GNN insights for: {} (direction: {})", symbol, analysisDirection);

        validateSymbol(symbol);
        validateAnalysisDirection(analysisDirection);

        var response = aiClient.getGnnInsights(symbol, analysisDirection);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_INSIGHTS_FETCH_FAILED)
                    .message("Failed to get GNN insights for " + symbol + ": " + response.error())
                    .symbol(symbol)
                    .build();
        }

        return response;
    }

    @Override
    public GnnCorrelationsResponse getGnnCorrelations(String symbol) {
        log.info("[AIService] Getting GNN correlations for: {}", symbol);

        validateSymbol(symbol);

        var response = aiClient.getGnnCorrelations(symbol);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_CORRELATIONS_FETCH_FAILED)
                    .message("Failed to get GNN correlations for " + symbol + ": " + response.error())
                    .symbol(symbol)
                    .build();
        }

        return response;
    }

    @Override
    public GnnDivergencesResponse getGnnDivergences(String symbol) {
        log.info("[AIService] Getting GNN divergences for: {}", symbol);

        validateSymbol(symbol);

        var response = aiClient.getGnnDivergences(symbol);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_DIVERGENCES_FETCH_FAILED)
                    .message("Failed to get GNN divergences for " + symbol + ": " + response.error())
                    .symbol(symbol)
                    .build();
        }

        return response;
    }

    @Override
    public GnnSuggestionsResponse getGnnSuggestions(String symbol) {
        log.info("[AIService] Getting GNN suggestions for: {}", symbol);

        validateSymbol(symbol);

        var response = aiClient.getGnnSuggestions(symbol);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_SUGGESTIONS_FETCH_FAILED)
                    .message("Failed to get GNN suggestions for " + symbol + ": " + response.error())
                    .symbol(symbol)
                    .build();
        }

        return response;
    }

    @Override
    public GnnConflictResponse getGnnConflict(String symbol, String analysisDirection) {
        log.info("[AIService] Getting GNN conflict for: {} (direction: {})", symbol, analysisDirection);

        validateSymbol(symbol);

        if (!StringUtils.hasText(analysisDirection)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Analysis direction is required for conflict detection")
                    .build();
        }

        String upper = analysisDirection.toUpperCase();
        if (!"BUY".equals(upper) && !"SELL".equals(upper)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_INVALID_SYMBOL)
                    .message("Analysis direction must be BUY or SELL for conflict detection: " + analysisDirection)
                    .build();
        }

        var response = aiClient.getGnnConflict(symbol, upper);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_CONFLICT_DETECTION_FAILED)
                    .message("Failed to detect conflict for " + symbol + ": " + response.error())
                    .symbol(symbol)
                    .build();
        }

        return response;
    }

    @Override
    public GnnAbTestResponse getGnnAbTest() {
        log.info("[AIService] Getting GNN A/B test results");

        var response = aiClient.getGnnAbTest();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_AB_TEST_FETCH_FAILED)
                    .message("Failed to get GNN A/B test results: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public GnnHeatmapResponse getGnnHeatmap(List<String> symbols) {
        log.info("[AIService] Getting GNN heatmap for {} symbols", symbols != null ? symbols.size() : "all");

        var response = aiClient.getGnnHeatmap(symbols);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_HEATMAP_FETCH_FAILED)
                    .message("Failed to get GNN heatmap: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public GnnCorrelationChangesResponse getGnnCorrelationChanges(String symbol, int lookback) {
        log.info("[AIService] Getting GNN correlation changes for: {} (lookback: {})", symbol, lookback);

        validateSymbol(symbol);
        validateLookback(lookback);

        var response = aiClient.getGnnCorrelationChanges(symbol, lookback);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_CORRELATION_CHANGES_FAILED)
                    .message("Failed to get GNN correlation changes for " + symbol + ": " + response.error())
                    .symbol(symbol)
                    .build();
        }

        return response;
    }

    @Override
    public GnnRefreshResponse refreshGnn() {
        log.info("[AIService] Refreshing GNN");

        var response = aiClient.refreshGnn();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_REFRESH_FAILED)
                    .message("Failed to refresh GNN: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public GnnResetResponse resetGnn() {
        log.info("[AIService] Resetting GNN");

        var response = aiClient.resetGnn();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_RESET_FAILED)
                    .message("Failed to reset GNN: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public GnnRolloutResponse setGnnAbTestRollout(double rollout) {
        log.info("[AIService] Setting GNN A/B test rollout to: {}%", rollout * 100);

        validateRollout(rollout);

        var response = aiClient.setGnnAbTestRollout(rollout);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_ROLLOUT_UPDATE_FAILED)
                    .message("Failed to set GNN rollout: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public GnnTrackResultResponse trackGnnResult(GnnTrackResultRequest request) {
        log.info("[AIService] Tracking GNN result for trade: {}", request != null ? request.tradeId() : null);

        validateTrackResultRequest(request);

        var response = aiClient.trackGnnResult(request);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.GNN_TRACK_RESULT_FAILED)
                    .message("Failed to track GNN result: " + response.error())
                    .ticket(request.tradeId())
                    .build();
        }

        return response;
    }

    // ============================================================
    // ADVERSARIAL ENDPOINTS
    // ============================================================

    @Override
    public AdversarialStatusResponse getAdversarialStatus() {
        log.info("[AIService] Getting adversarial status");

        var response = aiClient.getAdversarialStatus();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_NOT_INITIALIZED)
                    .message("Failed to get adversarial status: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public AdversarialGenerateResponse generateAdversarialAttacks(AdversarialGenerateRequest request) {
        log.info("[AIService] Generating adversarial attacks");

        validateAdversarialGenerateRequest(request);

        var response = aiClient.generateAdversarialAttacks(request);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_GENERATION_FAILED)
                    .message("Failed to generate adversarial attacks: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public AdversarialTrainResponse trainAdversarial(AdversarialTrainRequest request) {
        log.info("[AIService] Training adversarial on {} trades", request != null && request.trades() != null ? request.trades().size() : 0);

        validateAdversarialTrainRequest(request);

        var response = aiClient.trainAdversarial(request);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_TRAIN_FAILED)
                    .message("Failed to train adversarial: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public AdversarialMetricsResponse getAdversarialMetrics() {
        log.info("[AIService] Getting adversarial metrics");

        var response = aiClient.getAdversarialMetrics();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_METRICS_FETCH_FAILED)
                    .message("Failed to get adversarial metrics: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public AdversarialIntensityResponse setAdversarialIntensity(double intensity) {
        log.info("[AIService] Setting adversarial intensity to: {}", intensity);

        validateIntensity(intensity);

        var response = aiClient.setAdversarialIntensity(intensity);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_INTENSITY_UPDATE_FAILED)
                    .message("Failed to set adversarial intensity: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public AdversarialEnableResponse enableAdversarial(boolean enabled) {
        log.info("[AIService] Setting adversarial enabled: {}", enabled);

        var response = aiClient.enableAdversarial(enabled);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.ADVERSARIAL_ENABLE_FAILED)
                    .message("Failed to " + (enabled ? "enable" : "disable") + " adversarial: " + response.error())
                    .build();
        }

        return response;
    }
}