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
import org.springframework.web.util.UriComponentsBuilder;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Component
@RequiredArgsConstructor
@Slf4j
public class DefaultPythonExecutionClient implements PythonExecutionClient {

    private final WebClient pythonWebClient;
    private final PythonClientRetry retry;

    @Value("${internal.api.key:}")
    private String internalApiKey;

    private static final String API_KEY_HEADER = "X-API-Key";

    // ============================================================
    // PRIVATE HELPERS
    // ============================================================

    @SuppressWarnings("unchecked")
    private Map<String, Object> executeRequest(String method, String url, Object body) {
        try {
            log.debug("[{}] Calling Python: {}", method, url);

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
                    .retryWhen(retry.getRetrySpec())
                    .block();

            if (response == null) {
                throw TradingException.builder()
                        .errorCode(ErrorCodes.PYTHON_SERVICE_INVALID_RESPONSE)
                        .message("Empty response from Python service")
                        .build();
            }

            return response;

        } catch (WebClientResponseException e) {
            // Extract actual error message from Python response
            String errorMessage = extractErrorMessage(e);
            log.error("[{}] HTTP error: {} - {}", method, e.getStatusCode(), errorMessage);

            throw TradingException.builder()
                    .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                    .message("Python service error (" + e.getStatusCode() + "): " + errorMessage)
                    .mt5RetCode(e.getStatusCode().value())
                    .build();

        } catch (TradingException e) {
            throw e;
        } catch (Exception e) {
            log.error("[{}] Request failed: {}", method, e.getMessage());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                    .message("Python service error: " + e.getMessage())
                    .build();
        }
    }

    /**
     * Extract the actual error message from Python's response body.
     * Python returns: {"success": false, "error": "Actual error message"}
     * or {"error": "Actual error message"}
     */
    @SuppressWarnings("unchecked")
    private String extractErrorMessage(WebClientResponseException e) {
        try {
            String responseBody = e.getResponseBodyAsString();
            if (responseBody == null || responseBody.isEmpty()) {
                return e.getMessage();
            }

            // Try to parse JSON error response
            var objectMapper = new com.fasterxml.jackson.databind.ObjectMapper();
            var json = objectMapper.readValue(responseBody, Map.class);

            // Check for "error" field
            if (json.containsKey("error")) {
                return json.get("error").toString();
            }

            // Check for "error_message" field
            if (json.containsKey("error_message")) {
                return json.get("error_message").toString();
            }

            // Check for "message" field
            if (json.containsKey("message")) {
                return json.get("message").toString();
            }

            // Check for "details" field
            if (json.containsKey("details")) {
                return json.get("details").toString();
            }

            // If no error field, return the status text
            return e.getStatusText();

        } catch (Exception parseError) {
            // If we can't parse JSON, return the raw response body or status text
            String responseBody = e.getResponseBodyAsString();
            if (responseBody != null && !responseBody.isEmpty()) {
                return responseBody;
            }
            return e.getStatusText();
        }
    }

    /**
     * Extract error from Python response (for non-exception cases)
     */
    private String extractErrorFromResponse(Map<String, Object> response) {
        if (response == null) {
            return "Unknown error: Empty response";
        }

        // Check for "error" field
        if (response.containsKey("error")) {
            return response.get("error").toString();
        }

        // Check for "error_message" field
        if (response.containsKey("error_message")) {
            return response.get("error_message").toString();
        }

        // Check for "message" field
        if (response.containsKey("message")) {
            return response.get("message").toString();
        }

        // Check for "details" field
        if (response.containsKey("details")) {
            return response.get("details").toString();
        }

        return "Unknown error";
    }

    private Map<String, Object> buildTradePayload(ExecuteTradeRequest request) {
        var payload = new HashMap<String, Object>();
        payload.put("symbol", request.symbol());
        payload.put("order_type", request.orderType().name());
        payload.put("strategy_magic", request.strategyMagic());
        payload.put("fixed_trade_size_usd", request.fixedTradeSizeUsd());
        payload.put("risk_per_trade", request.riskPerTrade());
        payload.put("max_spread", request.maxSpread());
        payload.put("trade_deviation", request.tradeDeviation());
        payload.put("enable_trailing_stop", request.enableTrailingStop());
        payload.put("trailing_pips", request.trailingPips());
        payload.put("comment", request.comment());

        if (request.stopLossPrice() != null) {
            payload.put("stop_loss_price", request.stopLossPrice());
        }
        if (request.takeProfitPrice() != null) {
            payload.put("take_profit_price", request.takeProfitPrice());
        }
        return payload;
    }

    private String buildUrl(BrokerConfig broker, String path) {
        return broker.getBaseUrl() + "/api/v1" + path;
    }

    // ============================================================
    // 1. TRADE EXECUTION
    // ============================================================

    @Override
    public TradeExecutionResponse executeTrade(BrokerConfig broker, ExecuteTradeRequest request) {
        var url = buildUrl(broker, "/trade/execute");
        var payload = buildTradePayload(request);

        log.info("[{}] Executing trade: {} {}", broker.name(), request.symbol(), request.orderType());

        try {
            var response = executeRequest("POST", url, payload);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return TradeExecutionResponse.success(new TradeExecutionData(
                        (Integer) data.get("ticket"),
                        (Double) data.get("price"),
                        (Double) data.get("stop_loss"),
                        (Double) data.get("take_profit"),
                        (Double) data.get("volume"),
                        (Double) data.get("actual_margin"),
                        (Double) data.get("actual_risk_usd"),
                        (Double) data.get("take_profit_2_reference"),
                        (Double) data.get("take_profit_3_reference"),
                        (String) data.get("note")
                ));
            }

            // Extract actual error from response
            String error = extractErrorFromResponse(response);
            return TradeExecutionResponse.error(error);

        } catch (TradingException e) {
            // Re-throw with actual error message already extracted
            throw e;
        }
    }

    @Override
    public AnalyseTradeResponse analyseTrade(BrokerConfig broker, AnalyseTradeRequest request) {
        var url = buildUrl(broker, "/trade/analyse");

        log.info("[{}] Analysing trade: {}", broker.name(), request.symbol());

        try {
            var response = executeRequest("POST", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                @SuppressWarnings("unchecked")
                var result = (Map<String, Object>) response.get("result");
                return AnalyseTradeResponse.success(result);
            }

            String error = extractErrorFromResponse(response);
            return AnalyseTradeResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public ProbabilityResponse calculateProbability(BrokerConfig broker, ProbabilityRequest request) {
        var url = buildUrl(broker, "/trade/probability");

        log.info("[{}] Calculating probability: {}", broker.name(), request.symbol());

        try {
            var response = executeRequest("POST", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return ProbabilityResponse.success(
                        (Double) response.get("probability_decimal"),
                        (String) response.get("symbol")
                );
            }

            String error = extractErrorFromResponse(response);
            return ProbabilityResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // 2. POSITION MANAGEMENT
    // ============================================================

    @Override
    public ClosePositionResponse closePosition(BrokerConfig broker, ClosePositionRequest request) {
        var url = buildUrl(broker, "/position/close/" + request.ticket());
        var payload = Map.of("deviation", request.deviation());

        log.info("[{}] Closing position: {}", broker.name(), request.ticket());

        try {
            var response = executeRequest("POST", url, payload);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return ClosePositionResponse.success(
                        (Integer) data.get("ticket"),
                        (Double) data.get("profit")
                );
            }

            String error = extractErrorFromResponse(response);
            return ClosePositionResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public PartialCloseResponse partialClosePosition(BrokerConfig broker, PartialCloseRequest request) {
        var url = buildUrl(broker, "/position/partial-close/" + request.ticket());
        var payload = Map.of(
                "volume_to_close", request.volumeToClose(),
                "deviation", request.deviation()
        );

        log.info("[{}] Partial closing: {} (volume: {})", broker.name(), request.ticket(), request.volumeToClose());

        try {
            var response = executeRequest("PUT", url, payload);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return PartialCloseResponse.success(
                        (Integer) data.get("ticket"),
                        (Double) data.get("remaining_volume"),
                        (Double) data.get("closed_volume"),
                        (Double) data.get("profit")
                );
            }

            String error = extractErrorFromResponse(response);
            return PartialCloseResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public CloseAllResponse closeAllPositions(BrokerConfig broker, CloseAllPositionsRequest request) {
        var url = buildUrl(broker, "/positions/close/all");
        var payload = new HashMap<String, Object>();
        if (request.symbol() != null) payload.put("symbol", request.symbol());
        payload.put("deviation", request.deviation());

        log.info("[{}] Closing all positions{}", broker.name(),
                request.symbol() != null ? " for " + request.symbol() : "");

        try {
            var response = executeRequest("POST", url, payload);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return CloseAllResponse.success(
                        (Integer) data.get("closed"),
                        (Double) data.get("total_profit")
                );
            }

            String error = extractErrorFromResponse(response);
            return CloseAllResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public PositionsResponse getPositions(BrokerConfig broker, String symbol, Integer magic) {
        var url = buildUrl(broker, "/positions");
        var uriBuilder = UriComponentsBuilder.fromUriString(url);
        if (symbol != null) uriBuilder.queryParam("symbol", symbol);
        if (magic != null) uriBuilder.queryParam("magic", magic);

        log.info("[{}] Getting positions", broker.name());

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var positions = (java.util.List<Map<String, Object>>) response.get("positions");
                var summaryMap = (Map<String, Object>) response.get("summary");
                var summary = new PositionSummary(
                        (Double) summaryMap.get("total_risk_usd"),
                        (Double) summaryMap.get("total_potential_reward_usd"),
                        (Double) summaryMap.get("total_profit_usd"),
                        (Double) summaryMap.get("avg_probability_percent"),
                        (Double) summaryMap.get("total_expected_value")
                );
                return PositionsResponse.success((Integer) response.get("count"), positions, summary);
            }

            String error = extractErrorFromResponse(response);
            return PositionsResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public PositionsResponse getOpenPositions(BrokerConfig broker, String symbol, Integer magic) {
        var url = buildUrl(broker, "/positions/open");
        var uriBuilder = UriComponentsBuilder.fromUriString(url);
        if (symbol != null) uriBuilder.queryParam("symbol", symbol);
        if (magic != null) uriBuilder.queryParam("magic", magic);

        log.info("[{}] Getting open positions", broker.name());

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var positions = (java.util.List<Map<String, Object>>) response.get("positions");
                var summaryMap = (Map<String, Object>) response.get("summary");
                var summary = new PositionSummary(
                        (Double) summaryMap.get("total_risk_usd"),
                        (Double) summaryMap.get("total_potential_reward_usd"),
                        (Double) summaryMap.get("total_profit_usd"),
                        (Double) summaryMap.get("avg_probability_percent"),
                        (Double) summaryMap.get("total_expected_value")
                );
                return PositionsResponse.success((Integer) response.get("count"), positions, summary);
            }

            String error = extractErrorFromResponse(response);
            return PositionsResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public PositionResponse getPosition(BrokerConfig broker, int ticket) {
        var url = buildUrl(broker, "/position/" + ticket);

        log.info("[{}] Getting position: {}", broker.name(), ticket);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var position = (Map<String, Object>) response.get("position");
                return PositionResponse.success(position);
            }

            String error = extractErrorFromResponse(response);
            return PositionResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // 3. STOP LOSS & TAKE PROFIT
    // ============================================================

    @Override
    public ModifyStopLossResponse modifyStopLoss(BrokerConfig broker, ModifyStopLossRequest request) {
        var url = buildUrl(broker, "/position/" + request.ticket() + "/stop-loss");
        var payload = Map.of("sl_price", request.slPrice());

        log.info("[{}] Modifying SL: {} -> {}", broker.name(), request.ticket(), request.slPrice());

        try {
            var response = executeRequest("PUT", url, payload);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return ModifyStopLossResponse.success(
                        (Integer) data.get("ticket"),
                        (Double) data.get("new_sl")
                );
            }

            String error = extractErrorFromResponse(response);
            return ModifyStopLossResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public ModifyTakeProfitResponse modifyTakeProfit(BrokerConfig broker, ModifyTakeProfitRequest request) {
        var url = buildUrl(broker, "/position/" + request.ticket() + "/take-profit");
        var payload = Map.of("tp_price", request.tpPrice());

        log.info("[{}] Modifying TP: {} -> {}", broker.name(), request.ticket(), request.tpPrice());

        try {
            var response = executeRequest("PUT", url, payload);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return ModifyTakeProfitResponse.success(
                        (Integer) data.get("ticket"),
                        (Double) data.get("new_tp")
                );
            }

            String error = extractErrorFromResponse(response);
            return ModifyTakeProfitResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // 4. TRAILING STOP
    // ============================================================

    @Override
    public TrailingStopResponse enableTrailingStop(BrokerConfig broker, TrailingStopRequest request) {
        var url = buildUrl(broker, "/position/trailing/enable/" + request.ticket());
        var payload = Map.of("trailing_pips", request.trailingPips());

        log.info("[{}] Enabling trailing: {} ({} pips)", broker.name(), request.ticket(), request.trailingPips());

        try {
            var response = executeRequest("PUT", url, payload);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return TrailingStopResponse.success(
                        (Integer) data.get("ticket"),
                        (String) data.get("symbol"),
                        (Double) data.get("trailing_pips"),
                        (String) response.get("message")
                );
            }

            String error = extractErrorFromResponse(response);
            return TrailingStopResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public TrailingStopResponse disableTrailingStop(BrokerConfig broker, DisableTrailingRequest request) {
        var url = buildUrl(broker, "/position/trailing/disable/" + request.ticket());

        log.info("[{}] Disabling trailing: {}", broker.name(), request.ticket());

        try {
            var response = executeRequest("PUT", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return TrailingStopResponse.success(
                        (Integer) data.get("ticket"),
                        (String) data.get("symbol"),
                        (Double) data.get("trailing_pips"),
                        (String) response.get("message")
                );
            }

            String error = extractErrorFromResponse(response);
            return TrailingStopResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public TrailingStopResponse updateTrailingStop(BrokerConfig broker, TrailingStopRequest request) {
        var url = buildUrl(broker, "/position/trailing/update/" + request.ticket());
        var payload = Map.of("trailing_pips", request.trailingPips());

        log.info("[{}] Updating trailing: {} -> {} pips", broker.name(), request.ticket(), request.trailingPips());

        try {
            var response = executeRequest("PUT", url, payload);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return TrailingStopResponse.success(
                        (Integer) data.get("ticket"),
                        (String) data.get("symbol"),
                        (Double) data.get("trailing_pips"),
                        (String) response.get("message")
                );
            }

            String error = extractErrorFromResponse(response);
            return TrailingStopResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public TrailingStatusResponse getTrailingStatus(BrokerConfig broker) {
        var url = buildUrl(broker, "/position/trailing/status");

        log.info("[{}] Getting trailing status", broker.name());

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var activeTrails = (java.util.List<Map<String, Object>>) response.get("active_trails");
                return TrailingStatusResponse.success(activeTrails);
            }

            String error = extractErrorFromResponse(response);
            return TrailingStatusResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public TrailingStatsResponse getTrailingStats(BrokerConfig broker) {
        var url = buildUrl(broker, "/trailing-stop/stats");

        log.info("[{}] Getting trailing stats", broker.name());

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return TrailingStatsResponse.success(data);
            }

            String error = extractErrorFromResponse(response);
            return TrailingStatsResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // 5. ACCOUNT & SYMBOL
    // ============================================================

    @Override
    public AccountResponse getAccount(BrokerConfig broker) {
        var url = buildUrl(broker, "/account");

        log.info("[{}] Getting account info", broker.name());

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return AccountResponse.success(data);
            }

            String error = extractErrorFromResponse(response);
            return AccountResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public SymbolInfoResponse getSymbolInfo(BrokerConfig broker, String symbol) {
        var url = buildUrl(broker, "/symbol/" + symbol);

        log.info("[{}] Getting symbol info: {}", broker.name(), symbol);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var symbolData = (Map<String, Object>) response.get("symbol");
                return SymbolInfoResponse.success(symbolData);
            }

            String error = extractErrorFromResponse(response);
            return SymbolInfoResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public SymbolsResponse getSymbols(BrokerConfig broker) {
        var url = buildUrl(broker, "/symbols");

        log.info("[{}] Getting all symbols", broker.name());

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> rawSymbols = (List<Map<String, Object>>) response.get("symbols");
                List<SymbolInfoResponse> symbols = new ArrayList<>();

                if (rawSymbols != null) {
                    for (Map<String, Object> raw : rawSymbols) {
                        symbols.add(SymbolInfoResponse.fromPythonResponse(raw));
                    }
                }

                return SymbolsResponse.success((Integer) response.get("count"), symbols);
            }

            return SymbolsResponse.error((String) response.getOrDefault("error", "Unknown error"));

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // 6. MARKET CONDITIONS
    // ============================================================

    @Override
    public MarketStatusResponse getMarketStatus(BrokerConfig broker, String symbol) {
        var url = buildUrl(broker, "/market/status/" + symbol);

        log.info("[{}] Getting market status: {}", broker.name(), symbol);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return MarketStatusResponse.success(
                        (Boolean) response.get("is_closed"),
                        (String) response.get("reason")
                );
            }

            String error = extractErrorFromResponse(response);
            return MarketStatusResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public VolatilityResponse getMarketVolatility(BrokerConfig broker, String symbol, int lookback) {
        var url = buildUrl(broker, "/market/volatility/" + symbol + "?lookback=" + lookback);

        log.info("[{}] Getting volatility: {}", broker.name(), symbol);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return VolatilityResponse.success(
                        (Double) response.get("volatility"),
                        (String) response.get("level")
                );
            }

            String error = extractErrorFromResponse(response);
            return VolatilityResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public SpreadResponse getMarketSpread(BrokerConfig broker, String symbol, double maxSpread) {
        var url = buildUrl(broker, "/market/spread/" + symbol + "?max_spread=" + maxSpread);

        log.info("[{}] Getting spread: {}", broker.name(), symbol);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return SpreadResponse.success(
                        (Double) response.get("spread_pips"),
                        (Boolean) response.get("is_valid")
                );
            }

            String error = extractErrorFromResponse(response);
            return SpreadResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public MarketConditionsResponse getMarketConditions(BrokerConfig broker, String symbol) {
        var url = buildUrl(broker, "/market/conditions/" + symbol);

        log.info("[{}] Getting market conditions: {}", broker.name(), symbol);

        try {
            var response = executeRequest("GET", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var metrics = (Map<String, Object>) response.get("metrics");
                var recommendation = (Map<String, Object>) response.get("trading_recommendation");
                return MarketConditionsResponse.success(
                        (String) response.get("symbol"),
                        (Double) response.get("current_price"),
                        metrics,
                        recommendation
                );
            }

            String error = extractErrorFromResponse(response);
            return MarketConditionsResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // 7. MT5 CONNECTION
    // ============================================================

    @Override
    public Mt5ConnectionResponse connectMt5(BrokerConfig broker, Mt5ConnectRequest request) {
        var url = buildUrl(broker, "/mt5/connect");

        log.info("[{}] Connecting to MT5", broker.name());

        try {
            var response = executeRequest("POST", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var account = (Map<String, Object>) response.get("account");
                return Mt5ConnectionResponse.success(
                        (String) response.get("message"),
                        account
                );
            }

            String error = extractErrorFromResponse(response);
            return Mt5ConnectionResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public SingleBrokerResult disconnectMt5(BrokerConfig broker) {
        var url = buildUrl(broker, "/mt5/disconnect");

        log.info("[{}] Disconnecting from MT5", broker.name());

        try {
            var response = executeRequest("POST", url, null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                return SingleBrokerResult.success(broker.name(), null);
            }

            String error = extractErrorFromResponse(response);
            return SingleBrokerResult.error(broker.name(), error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // 8. HISTORY & CALCULATIONS
    // ============================================================

    @Override
    public TradeHistoryResponse getTradeHistory(BrokerConfig broker, TradeHistoryRequest request) {
        var url = buildUrl(broker, "/trades/history");
        var uriBuilder = UriComponentsBuilder.fromUriString(url);

        if (request.symbol() != null) uriBuilder.queryParam("symbol", request.symbol());
        if (request.magic() != null) uriBuilder.queryParam("magic", request.magic());
        if (request.lastNDays() != null) uriBuilder.queryParam("last_n_days", request.lastNDays());
        if (request.fromDate() != null) uriBuilder.queryParam("from_date", request.fromDate());
        if (request.toDate() != null) uriBuilder.queryParam("to_date", request.toDate());

        log.info("[{}] Getting trade history", broker.name());

        try {
            var response = executeRequest("GET", uriBuilder.build().toUriString(), null);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var deals = (java.util.List<Map<String, Object>>) response.get("deals");
                var trades = (java.util.List<Map<String, Object>>) response.get("trades");
                var summary = (Map<String, Object>) response.get("summary");
                return TradeHistoryResponse.success(
                        (Integer) response.get("count"),
                        deals,
                        trades,
                        summary
                );
            }

            String error = extractErrorFromResponse(response);
            return TradeHistoryResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    @Override
    public LotCalculationResponse calculateLot(BrokerConfig broker, LotCalculationRequest request) {
        var url = buildUrl(broker, "/calculate-lot");

        log.info("[{}] Calculating lot", broker.name());

        try {
            var response = executeRequest("POST", url, request);

            boolean success = (boolean) response.getOrDefault("success", false);
            if (success) {
                var data = (Map<String, Object>) response.get("data");
                return LotCalculationResponse.success(data);
            }

            String error = extractErrorFromResponse(response);
            return LotCalculationResponse.error(error);

        } catch (TradingException e) {
            throw e;
        }
    }

    // ============================================================
    // 9. HEALTH
    // ============================================================

    @Override
    public HealthResponse healthCheck(BrokerConfig broker) {
        var url = buildUrl(broker, "/health");

        log.info("[{}] Health check", broker.name());

        try {
            var response = executeRequest("GET", url, null);
            return HealthResponse.operational((Boolean) response.get("mt5_connected"));
        } catch (TradingException e) {
            log.warn("[{}] Health check failed: {}", broker.name(), e.getMessage());
            return HealthResponse.error();
        }
    }
}