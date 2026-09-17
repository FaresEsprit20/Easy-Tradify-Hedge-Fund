package com.trading.easytradify.execution.models;

public record SpreadResponse(
        boolean success,
        Double spreadPips,
        Boolean isValid,
        String error
) {
    public static SpreadResponse success(double spreadPips, boolean isValid) {
        return new SpreadResponse(true, spreadPips, isValid, null);
    }

    public static SpreadResponse error(String error) {
        return new SpreadResponse(false, null, null, error);
    }
}