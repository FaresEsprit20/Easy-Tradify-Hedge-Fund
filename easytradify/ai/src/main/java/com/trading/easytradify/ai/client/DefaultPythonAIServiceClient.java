package com.trading.easytradify.ai.client;

import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.adverserial.*;
import com.trading.easytradify.ai.models.gnn.*;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.web.util.UriComponentsBuilder;

import java.util.List;
import java.util.Map;

/**
 * <h1>Default Python AI Service Client</h1>
 * <p>
 * Default implementation of the {@link PythonAIServiceClient} interface.
 * Handles all HTTP communication with the Python AI service on port 5002.
 * </p>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to the caller</li>
 *   <li><b>Error Extraction:</b> Extracts meaningful error messages from Python responses</li>
 *   <li><b>Retry Support:</b> Configurable retry logic for transient failures</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see PythonAIServiceClient
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class DefaultPythonAIServiceClient implements PythonAIServiceClient {

    private final WebClient pythonWebClient;

    @Value("${ai.service.url:http://localhost:5002}")
    private String aiServiceUrl;

    @Value("${internal.api.key:}")
    private String internalApiKey;

    private static final String API_KEY_HEADER = "X-API-Key";

    // ============================================================
    // PRIVATE HELPERS
    // ============================================================

    /**
     * Executes a request to the Python AI service.
     *
     * @param method The HTTP method (GET, POST, PUT)
     * @param url    The full URL
     * @param body   The request body (nullable)
     * @return The response as a Map
     * @throws TradingException If the request fails or returns an error
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> executeRequest(String method, String url, Object body) {
        try {
            log.debug("[AIService] Calling Python: {} {}", method, url);

            var requestSpec = pythonWebClient.method(
                            org.springframework.http.HttpMethod.valueOf(method)
                    )
                    .uri(url)
                    .header(API_KEY_HEADER, internalApiKey)
                    .contentType(MediaType.APPLICATION_JSON);

            if (body != null) {
                requestSpec.bodyValue(body);
            }

            var response = requestSpec
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();

            if (response == null) {
                throw TradingException.builder()
                        .errorCode(ErrorCodes.PYTHON_SERVICE_INVALID_RESPONSE)
                        .message("Empty response from Python AI service")
                        .build();
            }

            return response;

        } catch (WebClientResponseException e) {
            String errorMessage = extractErrorMessage(e);
            log.error("[AIService] HTTP error: {} - {}", e.getStatusCode(), errorMessage);

            throw TradingException.builder()
                    .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                    .message("Python AI service error (" + e.getStatusCode() + "): " + errorMessage)
                    .mt5RetCode(e.getStatusCode().value())
                    .build();

        } catch (TradingException e) {
            throw e;
        } catch (Exception e) {
            log.error("[AIService] Request failed: {}", e.getMessage());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                    .message("Python AI service error: " + e.getMessage())
                    .build();
        }
    }

    /**
     * Extracts the actual error message from Python's response body.
     *
     * @param e The WebClientResponseException
     * @return The extracted error message
     */
    @SuppressWarnings("unchecked")
    private String extractErrorMessage(WebClientResponseException e) {
        try {
            String responseBody = e.getResponseBodyAsString();
            if (responseBody == null || responseBody.isEmpty()) {
                return e.getMessage();
            }

            var objectMapper = new com.fasterxml.jackson.databind.ObjectMapper();
            var json = objectMapper.readValue(responseBody, Map.class);

            if (json.containsKey("error")) {
                return json.get("error").toString();
            }
            if (json.containsKey("error_message")) {
                return json.get("error_message").toString();
            }
            if (json.containsKey("message")) {
                return json.get("message").toString();
            }
            if (json.containsKey("details")) {
                return json.get("details").toString();
            }

            return e.getStatusText();

        } catch (Exception parseError) {
            String responseBody = e.getResponseBodyAsString();
            if (responseBody != null && !responseBody.isEmpty()) {
                return responseBody;
            }
            return e.getStatusText();
        }
    }

    /**
     * Extracts error from Python response for non-exception cases.
     *
     * @param response The response map
     * @return The extracted error message
     */
    private String extractErrorFromResponse(Map<String, Object> response) {
        if (response == null) {
            return "Unknown error: Empty response";
        }

        if (response.containsKey("error")) {
            return response.get("error").toString();
        }
        if (response.containsKey("error_message")) {
            return response.get("error_message").toString();
        }
        if (response.containsKey("message")) {
            return response.get("message").toString();
        }
        if (response.containsKey("details")) {
            return response.get("details").toString();
        }

        return "Unknown error";
    }

    /**
     * Builds the full URL for an AI service endpoint.
     *
     * @param path The endpoint path
     * @return The full URL
     */
    private String buildUrl(String path) {
        return aiServiceUrl + path;
    }

    // ============================================================
    // HEALTH
    // ============================================================

    @Override
    public AIHealthResponse healthCheck() {
        var url = buildUrl("/health");

        log.info("[AIService] Health check");

        try {
            var response = executeRequest("GET", url, null);

            return new AIHealthResponse(
                    (String) response.get("status"),
                    (String) response.get("service"),
                    (Integer) response.get("port"),
                    (Boolean) response.get("initialized"),
                    (Map<String, Object>) response.get("gnn"),
                    (Map<String, Object>) response.get("adversarial"),
                    (String) response.get("timestamp"),
                    null  // error is null for success case
            );

        } catch (TradingException e) {
            throw e;
        } catch (Exception e) {
            log.error("[AIService] Health check failed: {}", e.getMessage());
            return AIHealthResponse.error("Service unavailable");
        }
    }

    // ============================================================
    // GNN ENDPOINTS
    // ============================================================

    @Override
    public GnnStatusResponse getGnnStatus() {
        var url = buildUrl("/gnn/status");

        log.info("[AIService] Getting GNN status");

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var status = (Map<String, Object>) response.get("status");
                return GnnStatusResponse.success(status);
            }

            String error = extractErrorFromResponse(response);
            return GnnStatusResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnContextResponse getGnnContext(String symbol, Integer tradeId) {
        var url = buildUrl("/gnn/context/" + symbol);
        var uriBuilder = UriComponentsBuilder.fromUriString(url);
        if (tradeId != null) {
            uriBuilder.queryParam("trade_id", tradeId);
        }

        log.info("[AIService] Getting GNN context for: {}", symbol);

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var context = (Map<String, Object>) response.get("context");
                return GnnContextResponse.success(symbol, context);
            }

            String error = extractErrorFromResponse(response);
            return GnnContextResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnInsightsResponse getGnnInsights(String symbol, String analysisDirection) {
        var url = buildUrl("/gnn/insights/" + symbol);
        var uriBuilder = UriComponentsBuilder.fromUriString(url);
        if (analysisDirection != null) {
            uriBuilder.queryParam("analysis_direction", analysisDirection);
        }

        log.info("[AIService] Getting GNN insights for: {}", symbol);

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var insights = (Map<String, Object>) response.get("insights");
                return GnnInsightsResponse.success(symbol, insights);
            }

            String error = extractErrorFromResponse(response);
            return GnnInsightsResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnCorrelationsResponse getGnnCorrelations(String symbol) {
        var url = buildUrl("/gnn/correlations/" + symbol);

        log.info("[AIService] Getting GNN correlations for: {}", symbol);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var correlations = (List<Map<String, Object>>) response.get("correlations");
                return GnnCorrelationsResponse.success(symbol, correlations);
            }

            String error = extractErrorFromResponse(response);
            return GnnCorrelationsResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnDivergencesResponse getGnnDivergences(String symbol) {
        var url = buildUrl("/gnn/divergences/" + symbol);

        log.info("[AIService] Getting GNN divergences for: {}", symbol);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var divergence = (Map<String, Object>) response.get("divergence");
                return GnnDivergencesResponse.success(symbol, divergence);
            }

            String error = extractErrorFromResponse(response);
            return GnnDivergencesResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnSuggestionsResponse getGnnSuggestions(String symbol) {
        var url = buildUrl("/gnn/suggestions/" + symbol);

        log.info("[AIService] Getting GNN suggestions for: {}", symbol);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var suggestions = (List<Map<String, Object>>) response.get("suggestions");
                return GnnSuggestionsResponse.success(symbol, suggestions);
            }

            String error = extractErrorFromResponse(response);
            return GnnSuggestionsResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnConflictResponse getGnnConflict(String symbol, String analysisDirection) {
        var url = buildUrl("/gnn/conflict/" + symbol);
        var uriBuilder = UriComponentsBuilder.fromUriString(url)
                .queryParam("analysis_direction", analysisDirection);

        log.info("[AIService] Getting GNN conflict for: {} with direction: {}", symbol, analysisDirection);

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return GnnConflictResponse.success(
                        symbol,
                        analysisDirection,
                        response.get("conflict"),
                        (Map<String, Object>) response.get("gnn_insights")
                );
            }

            String error = extractErrorFromResponse(response);
            return GnnConflictResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnAbTestResponse getGnnAbTest() {
        var url = buildUrl("/gnn/ab_test");

        log.info("[AIService] Getting GNN A/B test results");

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var results = (Map<String, Object>) response.get("results");
                return GnnAbTestResponse.success(results);
            }

            String error = extractErrorFromResponse(response);
            return GnnAbTestResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnHeatmapResponse getGnnHeatmap(List<String> symbols) {
        var url = buildUrl("/gnn/heatmap");
        var uriBuilder = UriComponentsBuilder.fromUriString(url);
        if (symbols != null && !symbols.isEmpty()) {
            uriBuilder.queryParam("symbols", String.join(",", symbols));
        }

        log.info("[AIService] Getting GNN heatmap");

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var heatmap = (Map<String, Object>) response.get("heatmap");
                return GnnHeatmapResponse.success(heatmap);
            }

            String error = extractErrorFromResponse(response);
            return GnnHeatmapResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnCorrelationChangesResponse getGnnCorrelationChanges(String symbol, int lookback) {
        var url = buildUrl("/gnn/correlation_changes/" + symbol);
        var uriBuilder = UriComponentsBuilder.fromUriString(url)
                .queryParam("lookback", lookback);

        log.info("[AIService] Getting GNN correlation changes for: {} (lookback: {})", symbol, lookback);

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var changes = (List<Map<String, Object>>) response.get("changes");
                return GnnCorrelationChangesResponse.success(symbol, changes);
            }

            String error = extractErrorFromResponse(response);
            return GnnCorrelationChangesResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnRefreshResponse refreshGnn() {
        var url = buildUrl("/gnn/refresh");

        log.info("[AIService] Refreshing GNN");

        try {
            var response = executeRequest("POST", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return GnnRefreshResponse.success((String) response.get("message"));
            }

            String error = extractErrorFromResponse(response);
            return GnnRefreshResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnResetResponse resetGnn() {
        var url = buildUrl("/gnn/reset");

        log.info("[AIService] Resetting GNN");

        try {
            var response = executeRequest("POST", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return GnnResetResponse.success((String) response.get("message"));
            }

            String error = extractErrorFromResponse(response);
            return GnnResetResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnRolloutResponse setGnnAbTestRollout(double rollout) {
        var url = buildUrl("/gnn/ab_test/rollout");
        var body = Map.of("rollout", rollout);

        log.info("[AIService] Setting GNN A/B test rollout to: {}%", rollout * 100);

        try {
            var response = executeRequest("POST", url, body);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return GnnRolloutResponse.success(
                        (String) response.get("message"),
                        (Double) response.get("rollout")
                );
            }

            String error = extractErrorFromResponse(response);
            return GnnRolloutResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public GnnTrackResultResponse trackGnnResult(GnnTrackResultRequest request) {
        var url = buildUrl("/gnn/track_result");

        log.info("[AIService] Tracking GNN result for trade: {}", request.tradeId());

        try {
            var response = executeRequest("POST", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return GnnTrackResultResponse.success((String) response.get("message"));
            }

            String error = extractErrorFromResponse(response);
            return GnnTrackResultResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // ADVERSARIAL ENDPOINTS
    // ============================================================

    @Override
    public AdversarialStatusResponse getAdversarialStatus() {
        var url = buildUrl("/adversarial/status");

        log.info("[AIService] Getting adversarial status");

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var status = (Map<String, Object>) response.get("status");
                return AdversarialStatusResponse.success(status);
            }

            String error = extractErrorFromResponse(response);
            return AdversarialStatusResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public AdversarialGenerateResponse generateAdversarialAttacks(AdversarialGenerateRequest request) {
        var url = buildUrl("/adversarial/generate");

        log.info("[AIService] Generating adversarial attacks");

        try {
            var response = executeRequest("POST", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var attackedTrades = (List<Map<String, Object>>) response.get("attacked_trades");
                return AdversarialGenerateResponse.success(
                        attackedTrades,
                        (Integer) response.get("count"),
                        (Boolean) response.get("gnn_used")
                );
            }

            String error = extractErrorFromResponse(response);
            return AdversarialGenerateResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public AdversarialTrainResponse trainAdversarial(AdversarialTrainRequest request) {
        var url = buildUrl("/adversarial/train");

        log.info("[AIService] Training adversarial");

        try {
            var response = executeRequest("POST", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var result = (Map<String, Object>) response.get("result");
                return AdversarialTrainResponse.success(
                        result,
                        (Boolean) response.get("gnn_used")
                );
            }

            String error = extractErrorFromResponse(response);
            return AdversarialTrainResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public AdversarialMetricsResponse getAdversarialMetrics() {
        var url = buildUrl("/adversarial/metrics");

        log.info("[AIService] Getting adversarial metrics");

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var metrics = (Map<String, Object>) response.get("metrics");
                return AdversarialMetricsResponse.success(metrics);
            }

            String error = extractErrorFromResponse(response);
            return AdversarialMetricsResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public AdversarialIntensityResponse setAdversarialIntensity(double intensity) {
        var url = buildUrl("/adversarial/intensity");
        var body = Map.of("intensity", intensity);

        log.info("[AIService] Setting adversarial intensity to: {}", intensity);

        try {
            var response = executeRequest("POST", url, body);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return AdversarialIntensityResponse.success(
                        (String) response.get("message"),
                        (Double) response.get("intensity")
                );
            }

            String error = extractErrorFromResponse(response);
            return AdversarialIntensityResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public AdversarialEnableResponse enableAdversarial(boolean enabled) {
        var url = buildUrl("/adversarial/enable");
        var body = Map.of("enabled", enabled);

        log.info("[AIService] Setting adversarial enabled: {}", enabled);

        try {
            var response = executeRequest("POST", url, body);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return AdversarialEnableResponse.success(
                        (String) response.get("message"),
                        (Boolean) response.get("enabled")
                );
            }

            String error = extractErrorFromResponse(response);
            return AdversarialEnableResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }
}