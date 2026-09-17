package com.trading.easytradify.execution.models;

import java.util.List;

public record DisableTrailingRequest(
        int ticket,
        List<String> brokers
) {
    public DisableTrailingRequest {
        brokers = brokers != null && !brokers.isEmpty() ? brokers : List.of("default");
    }
}