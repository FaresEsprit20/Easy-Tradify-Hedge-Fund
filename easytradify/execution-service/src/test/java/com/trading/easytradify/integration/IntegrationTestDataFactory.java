package com.trading.easytradify.integration;

import com.trading.easytradify.execution.models.*;
import java.util.List;

/**
 * Factory for creating test data used in integration tests.
 */
public class IntegrationTestDataFactory {

    public static ExecuteTradeRequest validExecuteTradeRequest() {
        return ExecuteTradeRequest.builder()
                .symbol("EURUSD")
                .orderType(OrderSide.BUY)
                .strategyMagic(123456)
                .fixedTradeSizeUsd(200.0)
                .riskPerTrade(0.05)
                .maxSpread(30.0)
                .tradeDeviation(20)
                .enableTrailingStop(true)
                .trailingPips(5.0)
                .comment("AI Trade")
                .brokers(List.of("icmarkets"))
                .build();
    }

    public static ExecuteTradeRequest validExecuteTradeRequestWithMultipleBrokers() {
        return ExecuteTradeRequest.builder()
                .symbol("EURUSD")
                .orderType(OrderSide.BUY)
                .strategyMagic(123456)
                .fixedTradeSizeUsd(200.0)
                .riskPerTrade(0.05)
                .maxSpread(30.0)
                .enableTrailingStop(true)
                .trailingPips(5.0)
                .comment("AI Trade")
                .brokers(List.of("icmarkets", "vtmarkets"))
                .build();
    }

    public static ExecuteTradeRequest validExecuteTradeRequestWithAllBrokers() {
        return ExecuteTradeRequest.builder()
                .symbol("EURUSD")
                .orderType(OrderSide.BUY)
                .strategyMagic(123456)
                .fixedTradeSizeUsd(200.0)
                .riskPerTrade(0.05)
                .maxSpread(30.0)
                .enableTrailingStop(true)
                .trailingPips(5.0)
                .comment("AI Trade")
                .brokers(List.of("all"))
                .build();
    }

    public static AnalyseTradeRequest validAnalyseTradeRequest() {
        return new AnalyseTradeRequest(
                "EURUSD",
                OrderSide.BUY,
                200.0,
                0.05,
                Timeframe.M1,
                null,
                null
        );
    }

    public static ProbabilityRequest validProbabilityRequest() {
        return new ProbabilityRequest(
                "EURUSD",
                1.12345,
                1.12245,
                1.12545,
                OrderSide.BUY
        );
    }
}