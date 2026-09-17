package com.trading.easytradify.integration;

import com.trading.easytradify.execution.models.CopyTradeRequest;
import com.trading.easytradify.execution.models.WebhookTradeRequest;
import com.trading.easytradify.execution.models.WebhookTrailingRequest;

import java.time.Instant;
import java.util.Map;

/**
 * Factory for creating copy trade integration test data.
 */
public final class CopyTradeIntegrationTestDataFactory {

    private CopyTradeIntegrationTestDataFactory() {
        // Private constructor
    }

    public static CopyTradeRequest validCopyTradeRequest() {
        return new CopyTradeRequest("EURUSD", createValidAnalysisResult());
    }

    public static CopyTradeRequest validCopyTradeRequestForGBPUSD() {
        return new CopyTradeRequest("GBPUSD", createValidAnalysisResult());
    }

    public static CopyTradeRequest copyTradeRequestWithEmptySymbol() {
        return new CopyTradeRequest("", createValidAnalysisResult());
    }

    public static CopyTradeRequest copyTradeRequestWithNullAnalysis() {
        return new CopyTradeRequest("EURUSD", null);
    }

    public static CopyTradeRequest copyTradeRequestWithEmptyAnalysis() {
        return new CopyTradeRequest("EURUSD", Map.of());
    }

    public static CopyTradeRequest copyTradeRequestWithMissingFinalVerdict() {
        return new CopyTradeRequest("EURUSD", Map.of("config", Map.of("executed_direction", "BUY")));
    }

    public static CopyTradeRequest copyTradeRequestWithMissingStopLoss() {
        var finalVerdict = Map.of("take_profit_1", 1.12545);
        var config = Map.of("executed_direction", "BUY");
        return new CopyTradeRequest("EURUSD", Map.of("final_verdict", finalVerdict, "config", config));
    }

    public static CopyTradeRequest copyTradeRequestWithMissingTakeProfit() {
        var finalVerdict = Map.of("stop_loss", 1.12245);
        var config = Map.of("executed_direction", "BUY");
        return new CopyTradeRequest("EURUSD", Map.of("final_verdict", finalVerdict, "config", config));
    }

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

    public static WebhookTradeRequest webhookTradeRequestWithNullSymbol() {
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

    public static WebhookTradeRequest webhookTradeRequestWithNullTicket() {
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

    public static WebhookTradeRequest webhookTradeRequestWithZeroTicket() {
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

    public static WebhookTrailingRequest webhookTrailingRequestWithNullTicket() {
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

    public static WebhookTrailingRequest webhookTrailingRequestWithZeroTicket() {
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

    public static Object webhookTestPayload() {
        return Map.of(
                "test", "data",
                "timestamp", Instant.now().toString()
        );
    }

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