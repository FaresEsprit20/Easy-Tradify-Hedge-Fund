package com.trading.easytradify.execution.models;

public record TradeExecutionResponse(
        boolean success,
        TradeExecutionData data,
        String error
) {
    public static TradeExecutionResponse success(TradeExecutionData data) {
        return new TradeExecutionResponse(true, data, null);
    }

    public static TradeExecutionResponse error(String error) {
        return new TradeExecutionResponse(false, null, error);
    }
}