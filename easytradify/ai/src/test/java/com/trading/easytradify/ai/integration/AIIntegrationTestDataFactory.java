package com.trading.easytradify.ai.integration;

import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.AdversarialIntensityRequest;
import com.trading.easytradify.ai.models.adverserial.AdversarialEnableRequest;
import com.trading.easytradify.ai.models.adverserial.AdversarialGenerateRequest;
import com.trading.easytradify.ai.models.adverserial.AdversarialTrainRequest;
import com.trading.easytradify.ai.models.gnn.*;

import java.util.List;
import java.util.Map;

/**
 * Factory for creating AI integration test data.
 */
public final class AIIntegrationTestDataFactory {

    private AIIntegrationTestDataFactory() {
        // Private constructor
    }

    // ============================================================
    // GNN REQUEST FIXTURES
    // ============================================================

    public static GnnTrackResultRequest validGnnTrackResultRequest() {
        return new GnnTrackResultRequest(123456789, 50.0, 1, true);
    }

    public static GnnTrackResultRequest gnnTrackResultRequestWithNullTradeId() {
        return new GnnTrackResultRequest(null, 50.0, 1, true);
    }

    public static GnnTrackResultRequest gnnTrackResultRequestWithZeroTradeId() {
        return new GnnTrackResultRequest(0, 50.0, 1, true);
    }

    public static GnnRolloutRequest validGnnRolloutRequest() {
        return new GnnRolloutRequest(0.5);
    }

    public static GnnRolloutRequest invalidGnnRolloutRequest() {
        return new GnnRolloutRequest(1.5);
    }

    // ============================================================
    // ADVERSARIAL REQUEST FIXTURES
    // ============================================================

    public static AdversarialGenerateRequest validAdversarialGenerateRequest() {
        var trade = Map.<String, Object>of(
                "symbol", "EURUSD",
                "entry", 1.12345,
                "stop_loss", 1.12245,
                "take_profit", 1.12545,
                "volume", 0.01
        );
        return new AdversarialGenerateRequest(trade, 1, 5);
    }

    public static AdversarialGenerateRequest adversarialGenerateRequestWithNullTrade() {
        return new AdversarialGenerateRequest(null, 1, 5);
    }

    public static AdversarialGenerateRequest adversarialGenerateRequestWithNullOutcome() {
        var trade = Map.<String, Object>of("symbol", "EURUSD");
        return new AdversarialGenerateRequest(trade, null, 5);
    }

    public static AdversarialTrainRequest validAdversarialTrainRequest() {
        var trades = List.<Map<String, Object>>of(
                Map.of("symbol", "EURUSD", "entry", 1.12345),
                Map.of("symbol", "GBPUSD", "entry", 1.23456)
        );
        var outcomes = List.of(1, 0);
        return new AdversarialTrainRequest(trades, outcomes, "EURUSD", "component1", true);
    }

    public static AdversarialTrainRequest adversarialTrainRequestWithNullTrades() {
        return new AdversarialTrainRequest(null, List.of(1, 0), "EURUSD", "component1", true);
    }

    public static AdversarialTrainRequest adversarialTrainRequestWithNullOutcomes() {
        var trades = List.<Map<String, Object>>of(Map.of("symbol", "EURUSD"));
        return new AdversarialTrainRequest(trades, null, "EURUSD", "component1", true);
    }

    public static AdversarialTrainRequest adversarialTrainRequestWithMismatchedLengths() {
        var trades = List.<Map<String, Object>>of(
                Map.of("symbol", "EURUSD"),
                Map.of("symbol", "GBPUSD")
        );
        var outcomes = List.of(1);
        return new AdversarialTrainRequest(trades, outcomes, "EURUSD", "component1", true);
    }

    public static AdversarialIntensityRequest validAdversarialIntensityRequest() {
        return new AdversarialIntensityRequest(0.5);
    }

    public static AdversarialIntensityRequest invalidAdversarialIntensityRequest() {
        return new AdversarialIntensityRequest(1.5);
    }

    public static AdversarialEnableRequest validAdversarialEnableRequest() {
        return new AdversarialEnableRequest(true);
    }

    public static AdversarialEnableRequest validAdversarialDisableRequest() {
        return new AdversarialEnableRequest(false);
    }
}