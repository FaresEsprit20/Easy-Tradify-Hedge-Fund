package com.trading.easytradify.unit.execution;

import com.trading.easytradify.execution.models.*;

import java.time.Instant;
import java.util.Map;

/**
 * Factory for creating copy trade test data.
 */
public final class CopyTradeTestDataFactory {

    private CopyTradeTestDataFactory() {
        // Private constructor
    }

    // ============================================================
    // COPY TRADE REQUEST FIXTURES
    // ============================================================

    public static CopyTradeRequest validCopyTradeRequest() {
        return new CopyTradeRequest("EURUSD", createValidAnalysisResult());
    }

    public static CopyTradeRequest validCopyTradeRequestForGBPUSD() {
        return new CopyTradeRequest("GBPUSD", createValidAnalysisResult());
    }

    public static CopyTradeRequest emptySymbolCopyTradeRequest() {
        return new CopyTradeRequest("", createValidAnalysisResult());
    }

    public static CopyTradeRequest nullSymbolCopyTradeRequest() {
        return new CopyTradeRequest(null, createValidAnalysisResult());
    }

    public static CopyTradeRequest nullAnalysisCopyTradeRequest() {
        return new CopyTradeRequest("EURUSD", null);
    }

    public static CopyTradeRequest emptyAnalysisCopyTradeRequest() {
        return new CopyTradeRequest("EURUSD", Map.of());
    }

    public static CopyTradeRequest missingFinalVerdictCopyTradeRequest() {
        return new CopyTradeRequest("EURUSD", Map.of("config", Map.of("executed_direction", "BUY")));
    }

    public static CopyTradeRequest missingConfigCopyTradeRequest() {
        var finalVerdict = Map.of(
                "stop_loss", 1.12245,
                "take_profit_1", 1.12545
        );
        return new CopyTradeRequest("EURUSD", Map.of("final_verdict", finalVerdict));
    }

    public static CopyTradeRequest missingStopLossCopyTradeRequest() {
        var finalVerdict = Map.of("take_profit_1", 1.12545);
        var config = Map.of("executed_direction", "BUY");
        return new CopyTradeRequest("EURUSD", Map.of("final_verdict", finalVerdict, "config", config));
    }

    public static CopyTradeRequest missingTakeProfitCopyTradeRequest() {
        var finalVerdict = Map.of("stop_loss", 1.12245);
        var config = Map.of("executed_direction", "BUY");
        return new CopyTradeRequest("EURUSD", Map.of("final_verdict", finalVerdict, "config", config));
    }

    // ============================================================
    // COPY TRADE RESPONSE FIXTURES
    // ============================================================

    public static CopyTradeResponse successCopyTradeResponse() {
        return CopyTradeResponse.success(
                "EURUSD",
                123456789,
                1.12345,
                1.12245,
                1.12545,
                0.01
        );
    }

    public static CopyTradeResponse failureCopyTradeResponse(String error) {
        return CopyTradeResponse.error("EURUSD", error);
    }

    // ============================================================
    // WEBHOOK REQUEST FIXTURES
    // ============================================================

    public static WebhookTradeRequest validWebhookTradeRequest() {
        return new WebhookTradeRequest(
                "EURUSD",
                123456789,
                "SL_TP_HIT",
                10.5,
                1.12345,
                1.12545,
                0.01,
                1.12245,
                1.12545,
                Instant.now().toString()
        );
    }

    public static WebhookTradeRequest nullSymbolWebhookTradeRequest() {
        return new WebhookTradeRequest(
                null,
                123456789,
                "SL_TP_HIT",
                10.5,
                1.12345,
                1.12545,
                0.01,
                1.12245,
                1.12545,
                Instant.now().toString()
        );
    }

    public static WebhookTradeRequest nullTicketWebhookTradeRequest() {
        return new WebhookTradeRequest(
                "EURUSD",
                null,
                "SL_TP_HIT",
                10.5,
                1.12345,
                1.12545,
                0.01,
                1.12245,
                1.12545,
                Instant.now().toString()
        );
    }

    public static WebhookTradeRequest zeroTicketWebhookTradeRequest() {
        return new WebhookTradeRequest(
                "EURUSD",
                0,
                "SL_TP_HIT",
                10.5,
                1.12345,
                1.12545,
                0.01,
                1.12245,
                1.12545,
                Instant.now().toString()
        );
    }

    public static WebhookTradeRequest negativePriceWebhookTradeRequest() {
        return new WebhookTradeRequest(
                "EURUSD",
                123456789,
                "SL_TP_HIT",
                -10.5,
                -1.12345,
                1.12545,
                0.01,
                1.12245,
                1.12545,
                Instant.now().toString()
        );
    }

    // ============================================================
    // WEBHOOK TRAILING REQUEST FIXTURES
    // ============================================================

    public static WebhookTrailingRequest validWebhookTrailingRequest() {
        return new WebhookTrailingRequest(
                123456789,
                "EURUSD",
                "ENABLE",
                1.12400,
                5.0,
                5.0,
                1.12450,
                1.12345,
                Instant.now().toString()
        );
    }

    public static WebhookTrailingRequest nullTicketWebhookTrailingRequest() {
        return new WebhookTrailingRequest(
                null,
                "EURUSD",
                "ENABLE",
                1.12400,
                5.0,
                5.0,
                1.12450,
                1.12345,
                Instant.now().toString()
        );
    }

    public static WebhookTrailingRequest zeroTicketWebhookTrailingRequest() {
        return new WebhookTrailingRequest(
                0,
                "EURUSD",
                "ENABLE",
                1.12400,
                5.0,
                5.0,
                1.12450,
                1.12345,
                Instant.now().toString()
        );
    }

    public static WebhookTrailingRequest negativeSlPriceWebhookTrailingRequest() {
        return new WebhookTrailingRequest(
                123456789,
                "EURUSD",
                "ENABLE",
                -1.12400,
                5.0,
                5.0,
                1.12450,
                1.12345,
                Instant.now().toString()
        );
    }

    public static WebhookTrailingRequest zeroStepPipsWebhookTrailingRequest() {
        // ✅ FIXED: This will now throw IllegalArgumentException from the record constructor
        return new WebhookTrailingRequest(
                123456789,
                "EURUSD",
                "ENABLE",
                1.12400,
                5.0,
                0.0,  // zero step pips - will throw validation
                1.12450,
                1.12345,
                Instant.now().toString()
        );
    }

    // ============================================================
    // WEBHOOK RESPONSE FIXTURES
    // ============================================================

    public static WebhookResponse successWebhookResponse() {
        return WebhookResponse.success("Webhook processed successfully");
    }

    public static WebhookResponse failureWebhookResponse(String message) {
        return WebhookResponse.error(message);
    }

    public static WebhookResponse ignoredWebhookResponse() {
        return WebhookResponse.ignored("Webhook ignored");
    }

    // ============================================================
    // HEALTH RESPONSE FIXTURES
    // ============================================================

    public static HealthResponse validHealthResponse() {
        return HealthResponse.operational(true);
    }

    public static HealthResponse errorHealthResponse() {
        return HealthResponse.error();
    }

    // ============================================================
    // STATUS & HEALTH MAP FIXTURES
    // ============================================================

    public static Map<String, Object> statusMap() {
        return Map.of(
                "running", true,
                "open_positions", Map.of("EURUSD", 123456789),
                "stats", Map.of(
                        "trades_executed", 10,
                        "trades_closed", 5,
                        "webhook_closes", 3
                ),
                "timestamp", Instant.now().toString()
        );
    }

    public static Map<String, Object> webhookHealthMap() {
        return Map.of(
                "status", "healthy",
                "open_positions", 2,
                "running", true,
                "webhook_closed_tickets", 3,
                "timestamp", Instant.now().toString()
        );
    }

    public static Map<String, Object> webhookDebugMap() {
        return Map.of(
                "executor_initialized", true,
                "executor_running", true,
                "webhook_closed_tickets", 3,
                "open_positions", 2,
                "webhook_url", "http://localhost:5003/webhook/trade",
                "trailing_url", "http://localhost:5003/webhook/trailing",
                "timestamp", Instant.now().toString()
        );
    }

    // ============================================================
    // PRIVATE HELPERS
    // ============================================================

    @SuppressWarnings("unchecked")
    private static Map<String, Object> createValidAnalysisResult() {
        var finalVerdict = Map.of(
                "stop_loss", 1.12245,
                "take_profit_1", 1.12545,
                "probability_percent", 83.1,
                "verdict", "BUY NOW"
        );

        var config = Map.of(
                "executed_direction", "BUY"
        );

        return Map.of(
                "final_verdict", finalVerdict,
                "config", config
        );
    }
}