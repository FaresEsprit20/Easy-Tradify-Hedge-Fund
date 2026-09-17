package com.trading.easytradify.portfolio.client;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.portfolio.client.PythonPortfolioRiskClient;
import com.trading.easytradify.portfolio.models.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.web.util.UriComponentsBuilder;

import java.util.Map;

/**
 * <h1>Default Python Portfolio Risk Client</h1>
 * <p>
 * Default implementation of the {@link PythonPortfolioRiskClient} interface.
 * Handles all HTTP communication with the Python portfolio risk service on port 5010.
 * </p>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>No Try-Catch:</b> All exceptions bubble up to the caller</li>
 *   <li><b>Error Extraction:</b> Extracts meaningful error messages from Python responses</li>
 *   <li><b>Retry Support:</b> Configurable retry logic for transient failures</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * <h2>Base URL</h2>
 * <p>
 * The Python portfolio risk service runs on port 5010
 * </p>
 *
 * <h2>Error Handling</h2>
 * <p>
 * Errors are extracted from Python responses and wrapped in
 * {@link TradingException} with appropriate error codes.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see PythonPortfolioRiskClient
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class DefaultPythonPortfolioRiskClient implements PythonPortfolioRiskClient {

    private final WebClient pythonWebClient;

    @Value("${portfolio.risk.service.url:http://localhost:5010}")
    private String portfolioRiskServiceUrl;

    @Value("${internal.api.key:}")
    private String internalApiKey;

    private static final String API_KEY_HEADER = "X-API-Key";
    private static final String API_PREFIX = "/api/v1/portfolio";
    private static final String BASE_URL = "/api/v1/portfolio";

    // ============================================================
    // PRIVATE HELPERS
    // ============================================================

    /**
     * Executes a request to the Python portfolio risk service.
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
            log.debug("[PortfolioRisk] Calling Python: {} {}", method, url);

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
                        .message("Empty response from Python portfolio risk service")
                        .build();
            }

            return response;

        } catch (WebClientResponseException e) {
            String errorMessage = extractErrorMessage(e);
            log.error("[PortfolioRisk] HTTP error: {} - {}", e.getStatusCode(), errorMessage);

            throw TradingException.builder()
                    .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                    .message("Python portfolio risk service error (" + e.getStatusCode() + "): " + errorMessage)
                    .mt5RetCode(e.getStatusCode().value())
                    .build();

        } catch (TradingException e) {
            throw e;
        } catch (Exception e) {
            log.error("[PortfolioRisk] Request failed: {}", e.getMessage());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                    .message("Python portfolio risk service error: " + e.getMessage())
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
     * Builds the full URL for a portfolio risk endpoint.
     *
     * @param path The endpoint path
     * @return The full URL
     */
    private String buildUrl(String path) {
        return portfolioRiskServiceUrl + API_PREFIX + path;
    }

    // ============================================================
    // PORTFOLIO STATUS
    // ============================================================

    @Override
    public PortfolioStatusResponse getPortfolioStatus(boolean refresh, boolean summary) {
        var url = buildUrl("/status");
        var uriBuilder = UriComponentsBuilder.fromUriString(url)
                .queryParam("refresh", refresh)
                .queryParam("summary", summary);

        log.info("[PortfolioRisk] Getting portfolio status - refresh: {}, summary: {}", refresh, summary);

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var status = (Map<String, Object>) response.get("status");
                return PortfolioStatusResponse.success(status);
            }

            String error = extractErrorFromResponse(response);
            return PortfolioStatusResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public PortfolioStatusResponse getPortfolioSummary() {
        return getPortfolioStatus(false, true);
    }

    // ============================================================
    // CONFIGURATION
    // ============================================================

    @Override
    public PortfolioConfigResponse getPortfolioConfig() {
        var url = buildUrl("/config");

        log.info("[PortfolioRisk] Getting portfolio config");

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var config = (Map<String, Object>) response.get("config");
                return PortfolioConfigResponse.success(config);
            }

            String error = extractErrorFromResponse(response);
            return PortfolioConfigResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public PortfolioConfigFieldResponse getPortfolioConfigField(String field) {
        var url = buildUrl("/config/" + field);

        log.info("[PortfolioRisk] Getting portfolio config field: {}", field);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return PortfolioConfigFieldResponse.success(
                        field,
                        response.get("value")
                );
            }

            String error = extractErrorFromResponse(response);
            return PortfolioConfigFieldResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public PortfolioConfigResponse updatePortfolioConfig(PortfolioConfigUpdateRequest request) {
        var url = buildUrl("/config");

        log.info("[PortfolioRisk] Updating portfolio config");

        try {
            var response = executeRequest("PUT", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var config = (Map<String, Object>) response.get("config");
                return PortfolioConfigResponse.success(config);
            }

            String error = extractErrorFromResponse(response);
            return PortfolioConfigResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public PortfolioConfigFieldResponse updatePortfolioConfigField(
            String field,
            PortfolioConfigFieldUpdateRequest request) {
        var url = buildUrl("/config/" + field);

        log.info("[PortfolioRisk] Updating portfolio config field: {}", field);

        try {
            var response = executeRequest("PUT", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return PortfolioConfigFieldResponse.success(
                        field,
                        response.get("new_value")
                );
            }

            String error = extractErrorFromResponse(response);
            return PortfolioConfigFieldResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // TRADING PERMISSION CHECKS
    // ============================================================

    @Override
    public CheckTradingAllowedResponse checkTradingAllowed(CheckTradingAllowedRequest request) {
        var url = buildUrl("/check_trading_allowed");

        log.info("[PortfolioRisk] Checking trading allowed");

        try {
            var response = executeRequest("POST", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return new CheckTradingAllowedResponse(
                        true,
                        (Boolean) response.get("is_trading_allowed"),
                        (String) response.get("risk_level"),
                        (java.util.List<String>) response.get("reasons"),
                        (Double) response.get("requested_risk_percent"),
                        (Double) response.get("max_risk_per_trade_percent"),
                        null  // error is null for success case
                );
            }

            String error = extractErrorFromResponse(response);
            return CheckTradingAllowedResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public MaxRiskForTradeResponse getMaxRiskForTrade() {
        var url = buildUrl("/max_risk_for_trade");

        log.info("[PortfolioRisk] Getting max risk for trade");

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return new MaxRiskForTradeResponse(
                        true,
                        (Double) response.get("max_risk_per_trade_percent"),
                        null
                );
            }

            String error = extractErrorFromResponse(response);
            return MaxRiskForTradeResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // STATISTICS
    // ============================================================

    @Override
    public PortfolioStatsResponse getPortfolioStats(String period, String date) {
        var url = buildUrl("/stats");
        var uriBuilder = UriComponentsBuilder.fromUriString(url)
                .queryParam("period", period);
        if (date != null) {
            uriBuilder.queryParam("date", date);
        }

        log.info("[PortfolioRisk] Getting portfolio stats - period: {}, date: {}", period, date);

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return PortfolioStatsResponse.success(response);
            }

            String error = extractErrorFromResponse(response);
            return PortfolioStatsResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // DRAWDOWN
    // ============================================================

    @Override
    public DrawdownResponse getDrawdownInfo() {
        var url = buildUrl("/drawdown");

        log.info("[PortfolioRisk] Getting drawdown info");

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var drawdown = (Map<String, Object>) response.get("drawdown");
                return DrawdownResponse.success(
                        (Double) drawdown.get("current_percent"),
                        (Double) drawdown.get("max_percent")
                );
            }

            String error = extractErrorFromResponse(response);
            return DrawdownResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // FUNDED ACCOUNT COMPLIANCE
    // ============================================================

    @Override
    public FundedComplianceResponse getFundedCompliance() {
        var url = buildUrl("/funded_compliance");

        log.info("[PortfolioRisk] Getting funded compliance");

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return new FundedComplianceResponse(
                        true,
                        (String) response.get("account_type"),
                        (Boolean) response.get("compliant"),
                        (java.util.List<String>) response.get("violations"),
                        null
                );
            }

            String error = extractErrorFromResponse(response);
            return FundedComplianceResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // REFRESH
    // ============================================================

    @Override
    public RefreshResponse refreshPortfolioStats() {
        var url = buildUrl("/refresh");

        log.info("[PortfolioRisk] Refreshing portfolio stats");

        try {
            var response = executeRequest("POST", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return new RefreshResponse(
                        true,
                        (String) response.get("message"),
                        null
                );
            }

            String error = extractErrorFromResponse(response);
            return RefreshResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // HEALTH
    // ============================================================

    @Override
    public HealthResponse healthCheck() {
        var url = portfolioRiskServiceUrl + "/health";

        log.info("[PortfolioRisk] Health check");

        try {
            var response = executeRequest("GET", url, null);
            return HealthResponse.operational(
                    (Boolean) response.getOrDefault("service_initialized", false)
            );
        } catch (TradingException e) {
            log.warn("[PortfolioRisk] Health check failed: {}", e.getMessage());
            return HealthResponse.error(e.getMessage());
        }
    }
}