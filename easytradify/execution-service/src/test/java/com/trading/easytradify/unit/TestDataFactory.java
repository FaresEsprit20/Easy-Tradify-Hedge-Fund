package com.trading.easytradify.unit;

import com.trading.easytradify.execution.config.broker.BrokerConfig;
import com.trading.easytradify.execution.models.*;
import com.trading.easytradify.execution.models.OrderSide;

import java.util.List;
import java.util.Map;

/**
 * Factory class for creating test data.
 * Centralizes test fixture creation to avoid duplication.
 */
public class TestDataFactory {

    // ============================================================
    // BROKERS
    // ============================================================

    public static BrokerConfig defaultBroker() {
        return BrokerConfig.icMarkets();
    }

    public static BrokerConfig vtBroker() {
        return BrokerConfig.vtMarkets();
    }

    public static BrokerConfig admiralsBroker() {
        return BrokerConfig.admirals();
    }

    public static List<BrokerConfig> allBrokers() {
        return List.of(defaultBroker(), vtBroker(), admiralsBroker());
    }

    // ============================================================
    // EXECUTE TRADE REQUEST
    // ============================================================

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

    // ============================================================
    // TRADE EXECUTION RESPONSE
    // ============================================================

    public static TradeExecutionData validTradeExecutionData() {
        return new TradeExecutionData(
                123456789,
                1.12345,
                1.12245,
                1.12545,
                0.01,
                100.0,
                10.0,
                null,
                null,
                null
        );
    }

    public static TradeExecutionResponse successTradeExecutionResponse() {
        return TradeExecutionResponse.success(validTradeExecutionData());
    }

    public static TradeExecutionResponse failureTradeExecutionResponse(String error) {
        return TradeExecutionResponse.error(error);
    }

    // ============================================================
    // CLOSE POSITION
    // ============================================================

    public static ClosePositionRequest validClosePositionRequest() {
        return new ClosePositionRequest(123456789, 20, List.of("icmarkets"));
    }

    public static ClosePositionResponse successClosePositionResponse() {
        return ClosePositionResponse.success(123456789, 10.5);
    }

    public static ClosePositionResponse failureClosePositionResponse(String error) {
        return ClosePositionResponse.error(error);
    }

    // ============================================================
    // PARTIAL CLOSE
    // ============================================================

    public static PartialCloseRequest validPartialCloseRequest() {
        return new PartialCloseRequest(123456789, 0.05, 20, List.of("icmarkets"));
    }

    public static PartialCloseResponse successPartialCloseResponse() {
        return PartialCloseResponse.success(123456789, 0.05, 0.05, 5.25);
    }

    // ============================================================
    // MODIFY STOP LOSS
    // ============================================================

    public static ModifyStopLossRequest validModifyStopLossRequest() {
        return new ModifyStopLossRequest(123456789, 1.12200, List.of("icmarkets"));
    }

    public static ModifyStopLossResponse successModifyStopLossResponse() {
        return ModifyStopLossResponse.success(123456789, 1.12200);
    }

    // ============================================================
    // MODIFY TAKE PROFIT
    // ============================================================

    public static ModifyTakeProfitRequest validModifyTakeProfitRequest() {
        return new ModifyTakeProfitRequest(123456789, 1.12600, List.of("icmarkets"));
    }

    public static ModifyTakeProfitResponse successModifyTakeProfitResponse() {
        return ModifyTakeProfitResponse.success(123456789, 1.12600);
    }

    // ============================================================
    // TRAILING STOP
    // ============================================================

    public static TrailingStopRequest validTrailingStopRequest() {
        return new TrailingStopRequest(123456789, 5.0, List.of("icmarkets"));
    }

    public static TrailingStopResponse successTrailingStopResponse() {
        return TrailingStopResponse.success(123456789, "icmarkets", 5.0, "Trailing stop enabled");
    }

    // ============================================================
    // POSITIONS
    // ============================================================

    public static PositionsResponse validPositionsResponse() {
        var positions = List.<Map<String, Object>>of(
                Map.of(
                        "ticket", 123456789,
                        "symbol", "EURUSD",
                        "type", "BUY",
                        "volume", 0.01,
                        "price_open", 1.12345,
                        "price_current", 1.12450,
                        "stop_loss", 1.12245,
                        "take_profit", 1.12545,
                        "profit_usd", 5.25
                )
        );
        var summary = new PositionSummary(10.0, 20.0, 5.25, 75.0, 10.0);
        return PositionsResponse.success(1, positions, summary);
    }

    // ============================================================
    // ACCOUNT
    // ============================================================

    public static AccountResponse validAccountResponse() {
        var data = Map.<String, Object>of(
                "login", 123456,
                "balance", 10000.0,
                "equity", 10500.0,
                "currency", "USD",
                "leverage", 200
        );
        return AccountResponse.success(data);
    }

    // ============================================================
    // SYMBOLS
    // ============================================================

    public static SymbolInfoResponse validSymbolInfoResponse() {
        return SymbolInfoResponse.success(
                "EURUSD",
                "Euro vs US Dollar",
                "EUR",
                "USD",
                5,
                0.01,
                100.0,
                1.12345,
                1.12355,
                1.0
        );
    }

    // ============================================================
    // MARKET CONDITIONS
    // ============================================================

    public static MarketConditionsResponse validMarketConditionsResponse() {
        var metrics = Map.<String, Object>of(
                "spread_pips", Map.of(
                        "value", 6.0,
                        "interpretation", "Excellent"
                ),
                "atr_pips", Map.of(
                        "value", 12.5,
                        "interpretation", "Price moves approximately 12.5 pips on average per bar"
                )
        );
        var recommendation = Map.<String, Object>of(
                "action", "NORMAL",
                "minimum_required_rr", "1:2",
                "minimum_required_probability", "75%"
        );
        return MarketConditionsResponse.success("EURUSD", 1.12345, metrics, recommendation);
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

    public static TradeHistoryRequest validTradeHistoryRequest() {
        return new TradeHistoryRequest(
                "EURUSD",
                123456,
                7,
                null,
                null
        );
    }

    public static LotCalculationRequest validLotCalculationRequest() {
        return new LotCalculationRequest(
                "EURUSD",
                200.0,
                0.05,
                null
        );
    }

    public static Mt5ConnectRequest validMt5ConnectRequest() {
        return new Mt5ConnectRequest(
                "12345",
                "password",
                "ICMarkets-Demo",
                ""
        );
    }

    public static DisableTrailingRequest validDisableTrailingRequest() {
        return new DisableTrailingRequest(123456789, List.of("icmarkets"));
    }

    // ============================================================
    // HEALTH
    // ============================================================

    public static HealthResponse validHealthResponse() {
        return HealthResponse.operational(true);
    }
}