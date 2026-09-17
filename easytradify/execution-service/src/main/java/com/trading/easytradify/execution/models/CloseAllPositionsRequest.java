package com.trading.easytradify.execution.models;

public record CloseAllPositionsRequest(
        String symbol,
        int deviation
) {
    public CloseAllPositionsRequest {
        deviation = deviation > 0 ? deviation : 20;
    }

}