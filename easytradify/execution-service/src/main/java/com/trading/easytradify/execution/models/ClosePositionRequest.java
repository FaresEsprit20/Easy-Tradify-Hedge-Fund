package com.trading.easytradify.execution.models;

import java.util.List;

public record ClosePositionRequest(
        int ticket,
        int deviation,
        List<String> brokers
) {
    public ClosePositionRequest {
        deviation = deviation > 0 ? deviation : 20;
        brokers = brokers != null && !brokers.isEmpty() ? brokers : List.of("default");
    }
}