package com.trading.easytradify.execution.models;

public record VolatilityResponse(
        boolean success,
        Double volatility,
        String level,
        String error
) {
    public static VolatilityResponse success(double volatility, String level) {
        return new VolatilityResponse(true, volatility, level, null);
    }

    public static VolatilityResponse error(String error) {
        return new VolatilityResponse(false, null, null, error);
    }
}