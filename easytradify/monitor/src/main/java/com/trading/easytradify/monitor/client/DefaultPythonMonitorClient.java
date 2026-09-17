package com.trading.easytradify.monitor.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.monitor.config.monitor.MonitorConfig;
import com.trading.easytradify.monitor.config.monitor.PythonMonitorRetry;
import com.trading.easytradify.monitor.models.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.web.util.UriComponentsBuilder;

import java.util.List;
import java.util.Map;

/**
 * <h1>Default Python Monitor Client</h1>
 * <p>
 * Default implementation of {@link PythonMonitorClient} that communicates
 * with the Python monitor service via REST calls.
 * </p>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Fail-Fast:</b> Validation failures throw {@link TradingException}</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 *   <li><b>Thread-Safe:</b> All methods are thread-safe</li>
 * </ul>
 *
 * <h2>Error Handling</h2>
 * <p>
 * All errors are wrapped in {@link TradingException} with appropriate
 * error codes from {@link ErrorCodes}. This includes:
 * </p>
 * <ul>
 *   <li>{@link ErrorCodes#PYTHON_SERVICE_UNREACHABLE} - When the Python service is unreachable</li>
 *   <li>{@link ErrorCodes#PYTHON_SERVICE_TIMEOUT} - When the request times out</li>
 *   <li>{@link ErrorCodes#PYTHON_SERVICE_INVALID_RESPONSE} - When the response is invalid</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see PythonMonitorClient
 * @see PythonMonitorRetry
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class DefaultPythonMonitorClient implements PythonMonitorClient {

    private final WebClient monitorWebClient;
    private final PythonMonitorRetry retry;
    private final MonitorConfig config;

    @Value("${internal.api.key:}")
    private String internalApiKey;

    private static final String API_KEY_HEADER = "X-API-Key";
    private static final ObjectMapper objectMapper = new ObjectMapper();
    private static final ParameterizedTypeReference<List<SymbolRankResponse>> SYMBOL_RANK_LIST =
            new ParameterizedTypeReference<>() {};

    // ============================================================
    // PRIVATE HELPERS
    // ============================================================

    /**
     * Executes a REST request and returns the response.
     * <p>
     * <b>Zero Try-Catch:</b> All exceptions bubble up to the caller.
     * </p>
     *
     * @param method       The HTTP method (GET, POST, etc.)
     * @param path         The request path
     * @param body         The request body (may be null)
     * @param responseType The expected response type
     * @param <T>          The response type
     * @return The deserialized response
     * @throws TradingException If the request fails
     */
    private <T> T executeRequest(String method, String path, Object body, Class<T> responseType) {
        var url = config.getPythonServiceUrl() + path;
        log.debug("[Monitor] Calling {}: {}", method, url);

        var requestSpec = monitorWebClient
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
    }

    /**
     * Executes a REST request and returns the response as a Map.
     *
     * @param method The HTTP method (GET, POST, etc.)
     * @param path   The request path
     * @param body   The request body (may be null)
     * @return The response as a Map
     * @throws TradingException If the request fails
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> executeRequestForMap(String method, String path, Object body) {
        return (Map<String, Object>) executeRequest(method, path, body, Map.class);
    }

    /**
     * Executes a void request (no response body expected).
     *
     * @param method The HTTP method
     * @param path   The request path
     * @param body   The request body (may be null)
     * @throws TradingException If the request fails
     */
    private void executeVoidRequest(String method, String path, Object body) {
        executeRequest(method, path, body, Void.class);
    }

    /**
     * Extracts an error message from a WebClientResponseException.
     *
     * @param e The exception
     * @return The extracted error message
     */
    @SuppressWarnings("unchecked")
    private String extractErrorMessage(WebClientResponseException e) {
        try {
            var responseBody = e.getResponseBodyAsString();
            if (responseBody == null || responseBody.isEmpty()) {
                return e.getStatusText();
            }
            var json = objectMapper.readValue(responseBody, Map.class);

            if (json.containsKey("error")) return json.get("error").toString();
            if (json.containsKey("error_message")) return json.get("error_message").toString();
            if (json.containsKey("message")) return json.get("message").toString();
            if (json.containsKey("details")) return json.get("details").toString();

            return e.getStatusText();
        } catch (Exception ex) {
            return e.getStatusText();
        }
    }

    // ============================================================
    // 1. MONITOR CONTROL
    // ============================================================

    @Override
    public void startMonitor() {
        log.info("[Monitor] Starting monitor");
        executeVoidRequest("POST", "/monitor/start", null);
        log.info("[Monitor] Monitor started");
    }

    @Override
    public void stopMonitor() {
        log.info("[Monitor] Stopping monitor");
        executeVoidRequest("POST", "/monitor/stop", null);
        log.info("[Monitor] Monitor stopped");
    }

    @Override
    public void refreshMonitor() {
        log.info("[Monitor] Refreshing monitor");
        executeVoidRequest("POST", "/monitor/refresh", null);
        log.info("[Monitor] Monitor refreshed");
    }

    // ============================================================
    // 2. MONITOR STATUS
    // ============================================================

    @Override
    public MonitorStatusResponse getStatus() {
        log.debug("[Monitor] Getting status");

        // Deserialize to a Map and map the fields explicitly, rather than
        // binding hybrid_monitor.py's body straight onto MonitorStatusResponse.
        //
        // Binding directly looked like it worked and did not. The Python body
        // has no "success" key at all, and Jackson defaults a missing primitive
        // boolean to false -- so a perfectly healthy monitor answered
        // {"success":false,"running":true,...} on every call, and any client
        // that checked the flag first (as the Angular one does) read a live
        // monitor as failed.
        //
        // It also silently dropped everything the DTO has no field for:
        // filtered_count, top_count, open_positions, position_cache_size and
        // the whole restart block never reached the caller.
        var body = executeRequestForMap("GET", "/monitor/status", null);

        if (body == null) {
            return MonitorStatusResponse.error("Monitor returned an empty body");
        }

        // We got a 200 with a body, so the call succeeded. Whether the MONITOR
        // is running is a separate question, answered by "running".
        boolean running = asBoolean(body.get("running"));

        @SuppressWarnings("unchecked")
        Map<String, Object> stats = body.get("stats") instanceof Map
                ? (Map<String, Object>) body.get("stats")
                : Map.of();

        // "How many symbols is it tracking" is top_count where present; the
        // monitor reports filtered_count when it has filtered but not yet
        // ranked, and that is the more truthful number in that window.
        Integer totalSymbols = firstInteger(body.get("top_count"), body.get("filtered_count"));

        // Open positions arrive as a dict keyed by ticket. Its SIZE is the
        // count; position_cache_size is the fallback when the dict is omitted.
        Integer activePositions = body.get("open_positions") instanceof Map<?, ?> positions
                ? positions.size()
                : firstInteger(body.get("position_cache_size"));

        // last_refresh_time is epoch SECONDS as a float. Passed through as a
        // string the caller can parse; sending the raw float would be read as
        // milliseconds and land the timestamp in 1970.
        String lastScan = toIsoInstant(stats.get("last_refresh_time"));

        return MonitorStatusResponse.success(running, lastScan, totalSymbols, activePositions, stats);
    }

    /** Lenient truthiness: the flag arrives as a JSON boolean, but not always. */
    private boolean asBoolean(Object value) {
        if (value instanceof Boolean b) return b;
        if (value instanceof String str) return Boolean.parseBoolean(str);
        return false;
    }

    /** First value that is usable as an int, or null when none is. */
    private Integer firstInteger(Object... candidates) {
        for (Object candidate : candidates) {
            if (candidate instanceof Number number) return number.intValue();
            if (candidate instanceof String str && !str.isBlank()) {
                try {
                    return Integer.parseInt(str.trim());
                } catch (NumberFormatException ignored) {
                    // Not a number; try the next candidate.
                }
            }
        }
        return null;
    }

    /**
     * Epoch seconds (as Python sends them) to an ISO-8601 instant.
     *
     * Returns null rather than a default when the value is missing or
     * unparseable: "the monitor has not scanned yet" and "the monitor last
     * scanned at the epoch" are different statements, and only one of them is
     * true.
     */
    private String toIsoInstant(Object value) {
        if (!(value instanceof Number number)) return null;

        double seconds = number.doubleValue();
        if (seconds <= 0) return null;

        return java.time.Instant.ofEpochMilli((long) (seconds * 1000L)).toString();
    }

    @Override
    public List<SymbolRankResponse> getTopSymbols() {
        log.debug("[Monitor] Getting top symbols");

        // Python returns an OBJECT -- {"success":..,"count":..,"top_symbols":[..]}
        // -- not a bare array. Binding straight to List<SymbolRankResponse>
        // failed to deserialize, the retry spec then retried three times, and
        // the failure surfaced as PYTHON_SERVICE_UNREACHABLE even though the
        // service had answered 200 every time.
        var response = monitorWebClient
                .get()
                .uri(config.getPythonServiceUrl() + "/monitor/top_symbols")
                .header(API_KEY_HEADER, internalApiKey)
                .retrieve()
                .bodyToMono(TopSymbolsResponse.class)
                .retryWhen(retry.getRetrySpec())
                .block();

        return (response != null && response.symbols() != null)
                ? response.symbols()
                : List.of();
    }

    @Override
    public List<String> getFilteredSymbols() {
        log.debug("[Monitor] Getting filtered symbols");

        var response = executeRequestForMap("GET", "/monitor/filtered_symbols", null);
        return response != null && response.containsKey("symbols")
                ? (List<String>) response.get("symbols")
                : List.of();
    }

    @Override
    public Object getGateEvents(int limit, String symbol, boolean vetoedOnly) {
        log.debug("[Monitor] Getting gate events");

        var uriBuilder = UriComponentsBuilder
                .fromUriString(config.getPythonServiceUrl() + "/monitor/gate-events")
                .queryParam("limit", limit)
                // snake_case: the Flask route reads request.args.get("vetoed_only").
                // A camelCase key is simply absent as far as it is concerned, and
                // the filter silently does nothing.
                .queryParam("vetoed_only", vetoedOnly);

        if (symbol != null && !symbol.isBlank()) {
            uriBuilder.queryParam("symbol", symbol);
        }

        return monitorWebClient
                .get()
                .uri(uriBuilder.build().toUriString())
                .header(API_KEY_HEADER, internalApiKey)
                .retrieve()
                .bodyToMono(Object.class)
                .retryWhen(retry.getRetrySpec())
                .block();
    }

    @Override
    public Object getWatchlist(int limit) {
        log.debug("[Monitor] Getting watchlist");

        var uri = UriComponentsBuilder
                .fromUriString(config.getPythonServiceUrl() + "/monitor/watchlist")
                .queryParam("limit", limit)
                .build()
                .toUriString();

        return monitorWebClient
                .get()
                .uri(uri)
                .header(API_KEY_HEADER, internalApiKey)
                .retrieve()
                .bodyToMono(Object.class)
                .retryWhen(retry.getRetrySpec())
                .block();
    }

    @Override
    public Object getThreads() {
        log.debug("[Monitor] Getting thread pool state");

        return monitorWebClient
                .get()
                .uri(config.getPythonServiceUrl() + "/monitor/threads")
                .header(API_KEY_HEADER, internalApiKey)
                .retrieve()
                .bodyToMono(Object.class)
                .retryWhen(retry.getRetrySpec())
                .block();
    }

    @Override
    public Object getLogs(int limit, String symbol) {
        log.debug("[Monitor] Getting logs");

        var uriBuilder = UriComponentsBuilder.fromUriString(config.getPythonServiceUrl() + "/monitor/logs")
                .queryParam("limit", limit);
        if (symbol != null) {
            uriBuilder.queryParam("symbol", symbol);
        }

        return monitorWebClient
                .get()
                .uri(uriBuilder.build().toUriString())
                .header(API_KEY_HEADER, internalApiKey)
                .retrieve()
                .bodyToMono(Object.class)
                .retryWhen(retry.getRetrySpec())
                .block();
    }

    @Override
    public Object getExecutions(int limit, String symbol) {
        log.debug("[Monitor] Getting executions");

        var uriBuilder = UriComponentsBuilder.fromUriString(config.getPythonServiceUrl() + "/monitor/executions")
                .queryParam("limit", limit);
        if (symbol != null) {
            uriBuilder.queryParam("symbol", symbol);
        }

        return monitorWebClient
                .get()
                .uri(uriBuilder.build().toUriString())
                .header(API_KEY_HEADER, internalApiKey)
                .retrieve()
                .bodyToMono(Object.class)
                .retryWhen(retry.getRetrySpec())
                .block();
    }

    @Override
    public Object getClosedTrades(int limit, String symbol) {
        log.debug("[Monitor] Getting closed trades");

        var uriBuilder = UriComponentsBuilder.fromUriString(config.getPythonServiceUrl() + "/monitor/closed_trades")
                .queryParam("limit", limit);
        if (symbol != null) {
            uriBuilder.queryParam("symbol", symbol);
        }

        return monitorWebClient
                .get()
                .uri(uriBuilder.build().toUriString())
                .header(API_KEY_HEADER, internalApiKey)
                .retrieve()
                .bodyToMono(Object.class)
                .retryWhen(retry.getRetrySpec())
                .block();
    }

    // ============================================================
    // 3. WEBHOOKS
    // ============================================================

    @Override
    public WebhookResponse handleWebhookTrade(WebhookTradeRequest request) {
        log.info("[Monitor] Webhook trade: {} (Ticket: {})", request.symbol(), request.ticket());
        return executeRequest("POST", "/webhook/trade", request, WebhookResponse.class);
    }

    @Override
    public WebhookResponse handleWebhookTrailing(WebhookTrailingRequest request) {
        log.info("[Monitor] Webhook trailing: Ticket {}", request.ticket());
        return executeRequest("POST", "/webhook/trailing", request, WebhookResponse.class);
    }

    @Override
    public Map<String, Object> getWebhookHealth() {
        log.debug("[Monitor] Getting webhook health");
        return executeRequestForMap("GET", "/webhook/health", null);
    }

    @Override
    public Map<String, Object> getWebhookDebug() {
        log.debug("[Monitor] Getting webhook debug");
        return executeRequestForMap("GET", "/webhook/debug", null);
    }

    // ============================================================
    // 4. HEALTH
    // ============================================================

    @Override
    public HealthResponse healthCheck() {
        log.debug("[Monitor] Health check");

        var response = executeRequestForMap("GET", "/health", null);

        if (response != null) {
            return HealthResponse.operational(
                    (Boolean) response.getOrDefault("running", false)
            );
        }

        return HealthResponse.error();
    }
}