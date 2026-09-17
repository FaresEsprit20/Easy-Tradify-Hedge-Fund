package com.trading.easytradify.execution.models;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.util.List;

public record ModifyStopLossRequest(
        int ticket,
        @NotNull(message = "Stop loss price is required")
        @Positive(message = "Stop loss price must be positive")
        double slPrice,
        List<String> brokers
) {
    public ModifyStopLossRequest {
        brokers = brokers != null && !brokers.isEmpty() ? brokers : List.of("default");
    }
}