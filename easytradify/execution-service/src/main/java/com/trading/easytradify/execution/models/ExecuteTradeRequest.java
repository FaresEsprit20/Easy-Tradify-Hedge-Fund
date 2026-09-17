package com.trading.easytradify.execution.models;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import lombok.Builder;

import java.util.List;

@Builder
public record ExecuteTradeRequest(
        @NotBlank(message = "Symbol is required")
        String symbol,

        @NotNull(message = "Order type is required")
        OrderSide orderType,

        @NotNull(message = "Strategy magic number is required")
        Integer strategyMagic,

        @NotNull(message = "Trade size is required")
        @Positive(message = "Trade size must be positive")
        Double fixedTradeSizeUsd,

        @NotNull(message = "Risk per trade is required")
        @Positive(message = "Risk per trade must be positive")
        Double riskPerTrade,

        @NotNull(message = "Max spread is required")
        @Positive(message = "Max spread must be positive")
        Double maxSpread,

        Integer tradeDeviation,

        // ⚠️ OPTIONAL - Python checks if present
        @Positive(message = "Stop loss price must be positive")
        Double stopLossPrice,

        // ⚠️ OPTIONAL - Python checks if present
        @Positive(message = "Take profit price must be positive")
        Double takeProfitPrice,

        Boolean enableTrailingStop,

        @Positive(message = "Trailing pips must be positive")
        Double trailingPips,

        String comment,

        List<String> brokers
) {
    public ExecuteTradeRequest {
        tradeDeviation = tradeDeviation != null ? tradeDeviation : 20;
        enableTrailingStop = enableTrailingStop != null && enableTrailingStop;
        trailingPips = trailingPips != null ? trailingPips : 5.0;
        comment = comment != null ? comment : "AI Trade";
        brokers = brokers != null && !brokers.isEmpty() ? brokers : List.of("default");

        // stopLossPrice and takeProfitPrice are allowed to be null (optional)
    }
}