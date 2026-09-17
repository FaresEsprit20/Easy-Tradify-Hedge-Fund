package com.trading.easytradify.execution.models;

import java.util.List;

public record TrailingStopRequest(
        int ticket,
        double trailingPips,
        List<String> brokers
) {
    public TrailingStopRequest {
        trailingPips = trailingPips > 0 ? trailingPips : 5.0;
        brokers = brokers != null && !brokers.isEmpty() ? brokers : List.of("default");
    }
}