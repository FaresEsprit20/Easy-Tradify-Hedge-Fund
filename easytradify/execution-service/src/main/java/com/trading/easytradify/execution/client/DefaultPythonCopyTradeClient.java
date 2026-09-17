package com.trading.easytradify.execution.client;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.execution.config.broker.BrokerConfig;
import com.trading.easytradify.execution.models.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.time.Duration;
import java.util.Map;

/**
 * <h1>Default Python Copy Trade Client</h1>
 * <p>
 * Default implementation of {@link PythonCopyTradeClient} that communicates
 * with the Python copy trade executor service via REST calls.
 * </p>
 *
 * <h2>Service Configuration</h2>
 * <p>
 * The client connects to the Python service running on port 5003 by default.
 * The base URL can be configured via {@code python.copy-trade.url}.
 * </p>
 *
 * <h2>Error Handling</h2>
 * <p>
 * All errors are wrapped in {@link TradingException} with appropriate
 * error codes from {@link ErrorCodes}.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class DefaultPythonCopyTradeClient implements PythonCopyTradeClient {

    private final WebClient webClient;
    private final PythonClientRetry retry;

    @Value("${python.copy-trade.url:http://localhost:5003}")
    private String copyTradeServiceUrl;

    private static final String API_KEY_HEADER = "X-API-Key";

    @Value("${internal.api.key:}")
    private String internalApiKey;

    // ============================================================
    // PRIVATE HELPERS
    // ============================================================

    private <T> T executeRequest(String method, String path, Object body, Class<T> responseType) {
        try {
            var url = copyTradeServiceUrl + path;
            log.debug("[CopyTrade] Calling {}: {}", method, url);

            var requestSpec = webClient
                    .method(org.springframework.http.HttpMethod.valueOf(method))
                    .uri(url)
                    .header(API_KEY_HEADER, internalApiKey)
                    .contentType(MediaType.APPLICATION_JSON);

            if (body != null) {
                requestSpec.bodyValue(body);
            }

            return requestSpec
                    .retrieve()
                    .bodyToMono(responseType)
                    .retryWhen(retry.getRetrySpec())
                    .block();

        } catch (WebClientResponseException e) {
            var errorMessage = extractErrorMessage(e);
            log.error("[CopyTrade] HTTP error: {} - {}", e.getStatusCode(), errorMessage);
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                    .message("Copy trade service error (" + e.getStatusCode() + "): " + errorMessage)
                    .mt5RetCode(e.getStatusCode().value())
                    .build();
        } catch (Exception e) {
            log.error("[CopyTrade] Request failed: {}", e.getMessage());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                    .message("Copy trade service error: " + e.getMessage())
                    .build();
        }
    }

    private String extractErrorMessage(WebClientResponseException e) {
        try {
            var responseBody = e.getResponseBodyAsString();
            if (responseBody == null || responseBody.isEmpty()) {
                return e.getStatusText();
            }
            var objectMapper = new com.fasterxml.jackson.databind.ObjectMapper();
            var json = objectMapper.readValue(responseBody, Map.class);

            if (json.containsKey("error")) return json.get("error").toString();
            if (json.containsKey("error_message")) return json.get("error_message").toString();
            if (json.containsKey("message")) return json.get("message").toString();

            return e.getStatusText();
        } catch (Exception ex) {
            return e.getStatusText();
        }
    }

    // ============================================================
    // COPY TRADE EXECUTION
    // ============================================================

    @Override
    public CopyTradeResponse executeCopyTrade(CopyTradeRequest request) {
        log.info("[CopyTrade] Executing copy trade for: {}", request.symbol());

        try {
            var response = executeRequest("POST", "/execute", request, CopyTradeResponse.class);
            if (response != null && response.success()) {
                log.info("[CopyTrade] Copy trade executed successfully: {} (Ticket: {})",
                        request.symbol(), response.ticket());
            } else {
                log.error("[CopyTrade] Copy trade failed: {}", response != null ? response.error() : "Unknown error");
            }
            return response;
        } catch (TradingException e) {
            log.error("[CopyTrade] Copy trade execution failed: {}", e.getMessage());
            return CopyTradeResponse.error(request.symbol(), e.getMessage());
        }
    }

    // ============================================================
    // WEBHOOK HANDLING
    // ============================================================

    @Override
    public WebhookResponse handleWebhookTrade(WebhookTradeRequest request) {
        log.info("[CopyTrade] Webhook trade: {} (Ticket: {})", request.symbol(), request.ticket());

        try {
            var response = executeRequest("POST", "/webhook/trade", request, WebhookResponse.class);
            log.info("[CopyTrade] Webhook trade response: {}", response != null ? response.status() : "null");
            return response;
        } catch (TradingException e) {
            log.error("[CopyTrade] Webhook trade failed: {}", e.getMessage());
            return WebhookResponse.error(e.getMessage());
        }
    }

    @Override
    public WebhookResponse handleWebhookTrailing(WebhookTrailingRequest request) {
        log.info("[CopyTrade] Webhook trailing: Ticket {}", request.ticket());

        try {
            var response = executeRequest("POST", "/webhook/trailing", request, WebhookResponse.class);
            return response;
        } catch (TradingException e) {
            log.error("[CopyTrade] Webhook trailing failed: {}", e.getMessage());
            return WebhookResponse.error(e.getMessage());
        }
    }

    @Override
    public WebhookResponse webhookTest(Object payload) {
        log.info("[CopyTrade] Webhook test");

        try {
            return executeRequest("POST", "/webhook/test", payload, WebhookResponse.class);
        } catch (TradingException e) {
            log.error("[CopyTrade] Webhook test failed: {}", e.getMessage());
            return WebhookResponse.error(e.getMessage());
        }
    }

    // ============================================================
    // STATUS & HEALTH
    // ============================================================

    @Override
    public Map<String, Object> getWebhookHealth() {
        log.debug("[CopyTrade] Getting webhook health");
        return executeRequest("GET", "/webhook/health", null, Map.class);
    }

    @Override
    public Map<String, Object> getWebhookDebug() {
        log.debug("[CopyTrade] Getting webhook debug info");
        return executeRequest("GET", "/webhook/debug", null, Map.class);
    }

    @Override
    public Map<String, Object> getStatus() {
        log.debug("[CopyTrade] Getting executor status");
        return executeRequest("GET", "/status", null, Map.class);
    }

    @Override
    public HealthResponse healthCheck(BrokerConfig broker) {
        log.debug("[CopyTrade] Health check");

        try {
            var response = executeRequest("GET", "/health", null, Map.class);
            if (response != null) {
                return HealthResponse.operational(
                        (Boolean) response.getOrDefault("running", false)
                );
            }
            return HealthResponse.error();
        } catch (Exception e) {
            log.warn("[CopyTrade] Health check failed: {}", e.getMessage());
            return HealthResponse.error();
        }
    }
}