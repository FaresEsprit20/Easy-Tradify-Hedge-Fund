package com.trading.easytradify.trades.client;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.trades.models.TradeModels.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.web.util.UriComponentsBuilder;

import java.util.List;
import java.util.Map;

/**
 * <h1>Default Python Trades Client</h1>
 * <p>
 * Default implementation of {@link PythonTradesClient}. Handles HTTP
 * communication with the Python trades service on port 5011 and unwraps its
 * response envelope.
 * </p>
 *
 * <h2>Design principles</h2>
 * <ul>
 *   <li><b>Envelope-aware:</b> the Python side returns the same envelope on
 *       success and failure, so {@code ok == false} is turned into a
 *       {@link TradingException} here rather than surfacing as a
 *       null-payload success.</li>
 *   <li><b>No silent defaults:</b> a transport failure is distinguished from a
 *       rejected request, because "Mongo is unreachable" and "that trade does
 *       not exist" call for different handling.</li>
 *   <li><b>Stateless:</b> no instance state between requests.</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see PythonTradesClient
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class DefaultPythonTradesClient implements PythonTradesClient {

    private final WebClient pythonWebClient;
    private final ObjectMapper objectMapper;

    @Value("${trades.service.url:http://localhost:5011}")
    private String tradesServiceUrl;

    @Value("${internal.api.key:}")
    private String internalApiKey;

    private static final String API_KEY_HEADER = "X-API-Key";
    private static final String BASE_URL = "/api/v1/trades";

    // ============================================================
    // PRIVATE HELPERS
    // ============================================================

    /**
     * Executes a request and returns the raw envelope as a map.
     *
     * <p>
     * A {@link WebClientResponseException} means the service answered and
     * rejected the request — its body still carries the envelope, so the real
     * error code and message are extracted from it. A
     * {@link WebClientRequestException} means it never answered at all, which
     * for this service almost always means the Python process or MongoDB is
     * down; that is reported as a service-unavailable condition rather than as
     * a bad request, because retrying the same call may well succeed.
     * </p>
     */
    private Map<String, Object> exchange(HttpMethod method, String url, Object body) {
        try {
            WebClient.RequestBodySpec spec = pythonWebClient
                    .method(method)
                    .uri(tradesServiceUrl + url)
                    .accept(MediaType.APPLICATION_JSON);

            if (internalApiKey != null && !internalApiKey.isBlank()) {
                spec = spec.header(API_KEY_HEADER, internalApiKey);
            }

            WebClient.RequestHeadersSpec<?> headersSpec = (body == null)
                    ? spec
                    : spec.contentType(MediaType.APPLICATION_JSON).bodyValue(body);

            return headersSpec
                    .retrieve()
                    .bodyToMono(new org.springframework.core.ParameterizedTypeReference<Map<String, Object>>() {
                    })
                    .block();

        } catch (WebClientResponseException e) {
            throw toTradingException(method, url, e);
        } catch (WebClientRequestException e) {
            log.error("Trades service unreachable at {}{}: {}", tradesServiceUrl, url, e.getMessage());
            throw new TradingException(
                    ErrorCodes.TRADE_STORE_UNAVAILABLE,
                    "Trades service unreachable at " + tradesServiceUrl + url
                            + " — is api/trades_controller.py running on 5011, and is mongod up?");
        }
    }

    /**
     * Turns a rejected request into a {@link TradingException}, preferring the
     * Python envelope's own error code and message over the bare HTTP status.
     */
    private TradingException toTradingException(HttpMethod method, String url, WebClientResponseException e) {
        ErrorCodes code = ErrorCodes.TRADE_STORE_REJECTED;
        String message = e.getMessage();
        try {
            Map<String, Object> envelope = objectMapper.readValue(
                    e.getResponseBodyAsString(), new TypeReference<Map<String, Object>>() {
                    });
            Object err = envelope.get("error");
            if (err instanceof Map<?, ?> errorMap) {
                Object c = errorMap.get("code");
                Object m = errorMap.get("message");
                if (c != null) message = String.valueOf(c) + ": " + message;
                if (m != null) message = String.valueOf(m);
            }
        } catch (Exception ignored) {
            // Body was not the expected envelope; the HTTP status stands on its own.
        }
        log.warn("Trades service rejected {} {}: {} {}", method, url, code, message);
        return new TradingException(code, message);
    }

    /**
     * Unwraps an envelope into a typed record, converting {@code ok == false}
     * into an exception so a caller cannot mistake a rejection for empty data.
     */
    private <T> ApiEnvelope<T> envelope(Map<String, Object> raw, TypeReference<T> dataType) {
        if (raw == null) {
            throw new TradingException(ErrorCodes.TRADE_STORE_EMPTY_RESPONSE,
                    "Trades service returned an empty body");
        }
        boolean ok = Boolean.TRUE.equals(raw.get("ok"));
        if (!ok) {
            Object err = raw.get("error");
            ErrorCodes code = ErrorCodes.TRADE_STORE_REJECTED;
            String message = "Trades service reported failure";
            if (err instanceof Map<?, ?> errorMap) {
                if (errorMap.get("code") != null) message = errorMap.get("code") + ": " + message;
                if (errorMap.get("message") != null) message = String.valueOf(errorMap.get("message"));
            }
            throw new TradingException(code, message);
        }

        T data = null;
        Object rawData = raw.get("data");
        if (rawData != null) {
            data = objectMapper.convertValue(rawData, dataType);
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> meta = (Map<String, Object>) raw.get("meta");
        Object ts = raw.get("timestamp");

        return new ApiEnvelope<>(true, data, meta, null, ts == null ? null : String.valueOf(ts));
    }

    /** Applies the optional query parameters shared by list and count. */
    private UriComponentsBuilder applyQuery(UriComponentsBuilder b, TradeQuery q) {
        if (q == null) return b;
        if (q.page() != null) b.queryParam("page", q.page());
        if (q.pageSize() != null) b.queryParam("page_size", q.pageSize());
        if (q.symbol() != null) b.queryParam("symbol", q.symbol());
        if (q.status() != null) b.queryParam("status", q.status());
        if (q.direction() != null) b.queryParam("direction", q.direction());
        if (q.sortBy() != null) b.queryParam("sort_by", q.sortBy());
        if (q.sortDir() != null) b.queryParam("sort_dir", q.sortDir());
        // opened_from / opened_to: the names trades_controller.py actually
        // reads. This sent opened_after / opened_before, which Flask never
        // looked at, so date filtering through the Java service did nothing --
        // silently, since an unknown query parameter is simply ignored.
        if (q.openedAfter() != null) b.queryParam("opened_from", q.openedAfter());
        if (q.openedBefore() != null) b.queryParam("opened_to", q.openedBefore());
        if (q.includeDeleted() != null) b.queryParam("include_deleted", q.includeDeleted());
        return b;
    }

    private static final TypeReference<List<Trade>> TRADE_LIST = new TypeReference<>() {
    };
    private static final TypeReference<Trade> TRADE = new TypeReference<>() {
    };
    private static final TypeReference<Map<String, Object>> MAP = new TypeReference<>() {
    };
    private static final TypeReference<List<Map<String, Object>>> MAP_LIST = new TypeReference<>() {
    };
    private static final TypeReference<List<Object>> OBJECT_LIST = new TypeReference<>() {
    };

    // ============================================================
    // READ
    // ============================================================

    @Override
    public ApiEnvelope<List<Trade>> listTrades(TradeQuery query) {
        String url = applyQuery(UriComponentsBuilder.fromPath(BASE_URL), query)
                .build().toUriString();
        return envelope(exchange(HttpMethod.GET, url, null), TRADE_LIST);
    }

    @Override
    public ApiEnvelope<List<Trade>> queryTrades(Map<String, Object> body) {
        // Forwarded untouched. The Python side is the only validator: it
        // rejects unknown keys, and re-declaring the body as a typed record
        // here with ignoreUnknown=true would drop a mistyped filter silently --
        // turning a 400 the caller can fix into every trade, unfiltered.
        return envelope(exchange(HttpMethod.POST, BASE_URL + "/query",
                body == null ? Map.of() : body), TRADE_LIST);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> filterCatalog() {
        return envelope(exchange(HttpMethod.GET, BASE_URL + "/filters", null), MAP);
    }

    @Override
    public ApiEnvelope<Trade> getTrade(String tradeId) {
        return envelope(exchange(HttpMethod.GET, BASE_URL + "/" + tradeId, null), TRADE);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> exists(String tradeId) {
        return envelope(exchange(HttpMethod.GET, BASE_URL + "/" + tradeId + "/exists", null), MAP);
    }

    @Override
    public ApiEnvelope<List<Map<String, Object>>> getPriceEvolution(String tradeId, Integer page, Integer pageSize) {
        UriComponentsBuilder b = UriComponentsBuilder.fromPath(BASE_URL + "/" + tradeId + "/price-evolution");
        if (page != null) b.queryParam("page", page);
        if (pageSize != null) b.queryParam("page_size", pageSize);
        return envelope(exchange(HttpMethod.GET, b.build().toUriString(), null), MAP_LIST);
    }

    @Override
    public ApiEnvelope<List<Trade>> search(String q, Integer page, Integer pageSize) {
        UriComponentsBuilder b = UriComponentsBuilder.fromPath(BASE_URL + "/search").queryParam("q", q);
        if (page != null) b.queryParam("page", page);
        if (pageSize != null) b.queryParam("page_size", pageSize);
        return envelope(exchange(HttpMethod.GET, b.build().toUriString(), null), TRADE_LIST);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> count(TradeQuery query) {
        String url = applyQuery(UriComponentsBuilder.fromPath(BASE_URL + "/count"), query)
                .build().toUriString();
        return envelope(exchange(HttpMethod.GET, url, null), MAP);
    }

    @Override
    public ApiEnvelope<List<Object>> distinct(String field) {
        return envelope(exchange(HttpMethod.GET, BASE_URL + "/distinct/" + field, null), OBJECT_LIST);
    }

    // ============================================================
    // STATISTICS
    // ============================================================

    @Override
    public ApiEnvelope<Map<String, Object>> stats() {
        return envelope(exchange(HttpMethod.GET, BASE_URL + "/stats", null), MAP);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> performance(String from, String to, String symbol) {
        UriComponentsBuilder b = UriComponentsBuilder.fromPath(BASE_URL + "/stats/performance");
        if (from != null) b.queryParam("from", from);
        if (to != null) b.queryParam("to", to);
        if (symbol != null) b.queryParam("symbol", symbol);
        return envelope(exchange(HttpMethod.GET, b.build().toUriString(), null), MAP);
    }

    @Override
    public ApiEnvelope<List<Map<String, Object>>> statsBySymbol(String from, String to) {
        UriComponentsBuilder b = UriComponentsBuilder.fromPath(BASE_URL + "/stats/by-symbol");
        if (from != null) b.queryParam("from", from);
        if (to != null) b.queryParam("to", to);
        return envelope(exchange(HttpMethod.GET, b.build().toUriString(), null), MAP_LIST);
    }

    @Override
    public ApiEnvelope<List<Map<String, Object>>> statsTimeseries(String interval, String from, String to) {
        UriComponentsBuilder b = UriComponentsBuilder.fromPath(BASE_URL + "/stats/timeseries");
        if (interval != null) b.queryParam("interval", interval);
        if (from != null) b.queryParam("from", from);
        if (to != null) b.queryParam("to", to);
        return envelope(exchange(HttpMethod.GET, b.build().toUriString(), null), MAP_LIST);
    }

    // ============================================================
    // DIAGNOSTICS
    // ============================================================

    @Override
    public ApiEnvelope<Map<String, Object>> health() {
        return envelope(exchange(HttpMethod.GET, BASE_URL + "/health", null), MAP);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> diagnostics(Integer limit, Boolean onlyOpen, Integer sinceHours) {
        UriComponentsBuilder b = UriComponentsBuilder.fromPath(BASE_URL + "/diagnostics");
        if (limit != null) b.queryParam("limit", limit);
        if (onlyOpen != null) b.queryParam("only_open", onlyOpen);
        if (sinceHours != null) b.queryParam("since_hours", sinceHours);
        return envelope(exchange(HttpMethod.GET, b.build().toUriString(), null), MAP);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> selfCheck() {
        return envelope(exchange(HttpMethod.POST, BASE_URL + "/diagnostics/self-check", Map.of()), MAP);
    }

    // ============================================================
    // WRITE
    // ============================================================

    @Override
    public ApiEnvelope<Trade> upsertTrade(Map<String, Object> trade) {
        return envelope(exchange(HttpMethod.POST, BASE_URL, trade), TRADE);
    }

    @Override
    public ApiEnvelope<Trade> patchTrade(String tradeId, Map<String, Object> patch) {
        return envelope(exchange(HttpMethod.PATCH, BASE_URL + "/" + tradeId, patch), TRADE);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> appendPricePoint(String tradeId, PricePointRequest point) {
        return envelope(exchange(HttpMethod.POST, BASE_URL + "/" + tradeId + "/price-evolution", point), MAP);
    }

    @Override
    public ApiEnvelope<Trade> closeTrade(String tradeId, CloseTradeRequest request) {
        return envelope(exchange(HttpMethod.POST, BASE_URL + "/" + tradeId + "/close", request), TRADE);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> bulkUpsert(BulkRequest request) {
        return envelope(exchange(HttpMethod.POST, BASE_URL + "/bulk", request), MAP);
    }

    // ============================================================
    // DELETE
    // ============================================================

    @Override
    public ApiEnvelope<Map<String, Object>> deleteTrade(String tradeId, DeleteRequest request) {
        UriComponentsBuilder b = UriComponentsBuilder.fromPath(BASE_URL + "/" + tradeId);
        if (request != null) {
            if (request.mode() != null) b.queryParam("mode", request.mode());
            if (request.confirm() != null) b.queryParam("confirm", request.confirm());
            if (request.reason() != null) b.queryParam("reason", request.reason());
            if (request.allowOpen() != null) b.queryParam("allow_open", request.allowOpen());
        }
        return envelope(exchange(HttpMethod.DELETE, b.build().toUriString(), null), MAP);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> restoreTrade(String tradeId) {
        return envelope(exchange(HttpMethod.POST, BASE_URL + "/" + tradeId + "/restore", Map.of()), MAP);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> bulkDelete(BulkDeleteRequest request) {
        return envelope(exchange(HttpMethod.POST, BASE_URL + "/bulk-delete", request), MAP);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> purge(Integer olderThanDays, Boolean confirm) {
        UriComponentsBuilder b = UriComponentsBuilder.fromPath(BASE_URL + "/purge");
        if (olderThanDays != null) b.queryParam("older_than_days", olderThanDays);
        if (confirm != null) b.queryParam("confirm", confirm);
        return envelope(exchange(HttpMethod.POST, b.build().toUriString(), null), MAP);
    }
}
