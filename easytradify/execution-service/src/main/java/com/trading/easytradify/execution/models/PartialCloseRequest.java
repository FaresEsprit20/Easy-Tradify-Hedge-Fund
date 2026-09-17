package com.trading.easytradify.execution.models;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.util.List;

public record PartialCloseRequest(
        int ticket,
        @NotNull(message = "Volume to close is required")
        @Positive(message = "Volume must be positive")
        double volumeToClose,
        int deviation,
        List<String> brokers
) {
    public PartialCloseRequest {
        deviation = deviation > 0 ? deviation : 20;
        brokers = brokers != null && !brokers.isEmpty() ? brokers : List.of("default");
    }

}