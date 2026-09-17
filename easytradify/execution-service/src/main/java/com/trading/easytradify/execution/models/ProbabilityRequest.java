package com.trading.easytradify.execution.models;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

public record ProbabilityRequest(

        @NotBlank(message = "Symbol is required")
        String symbol,

        @NotNull(message = "Entry price is required")
        @Positive(message = "Entry price must be positive")
        Double entryPrice,

        @NotNull(message = "Stop loss is required")
        @Positive(message = "Stop loss must be positive")
        Double stopLoss,

        @NotNull(message = "Take profit is required")
        @Positive(message = "Take profit must be positive")
        Double takeProfit,

        @NotNull(message = "Order type is required")
        OrderSide orderType

) {}