package com.trading.easytradify.execution.models;

public record MarketStatusResponse(
        boolean success,
        Boolean isClosed,
        String reason,
        String error
) {
    public static MarketStatusResponse success(boolean isClosed, String reason) {
        return new MarketStatusResponse(true, isClosed, reason, null);
    }

    public static MarketStatusResponse error(String error) {
        return new MarketStatusResponse(false, null, null, error);
    }
}