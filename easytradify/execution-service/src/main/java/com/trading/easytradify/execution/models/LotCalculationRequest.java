package com.trading.easytradify.execution.models;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

public record LotCalculationRequest(

        @NotBlank(message = "Symbol is required")
        String symbol,

        @NotNull(message = "Trade size is required")
        @Positive(message = "Trade size must be positive")
        Double fixedTradeSizeUsd,

        @NotNull(message = "Risk per trade is required")
        @Positive(message = "Risk per trade must be positive")
        Double riskPerTrade,

        Double minStopPipsOverride
) {}