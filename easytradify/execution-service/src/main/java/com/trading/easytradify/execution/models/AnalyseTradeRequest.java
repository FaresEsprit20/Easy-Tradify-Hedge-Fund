package com.trading.easytradify.execution.models;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

public record AnalyseTradeRequest(

        @NotBlank(message = "Symbol is required")
        String symbol,

        @NotNull(message = "Order type is required")
        OrderSide orderType,

        @NotNull(message = "Trade size is required")
        @Positive(message = "Trade size must be positive")
        Double fixedTradeSizeUsd,

        @NotNull(message = "Risk per trade is required")
        @Positive(message = "Risk per trade must be positive")
        Double riskPerTrade,

        Timeframe timeframe,

        @Positive(message = "Stop loss pips must be positive")
        Double stopLossPips,

        @Positive(message = "Take profit pips must be positive")
        Double takeProfitPips
) {
    public AnalyseTradeRequest {
        timeframe = timeframe != null ? timeframe : Timeframe.M1;
    }
}