package com.trading.easytradify.execution.models;

public record ClosePositionResponse(
        boolean success,
        ClosePositionData data,
        String error
) {
    public static ClosePositionResponse success(Integer ticket, Double profit) {
        return new ClosePositionResponse(true, new ClosePositionData(ticket, profit), null);
    }

    public static ClosePositionResponse error(String error) {
        return new ClosePositionResponse(false, null, error);
    }
}