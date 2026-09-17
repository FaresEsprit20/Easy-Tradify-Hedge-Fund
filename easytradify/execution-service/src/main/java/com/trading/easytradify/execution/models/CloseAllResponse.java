package com.trading.easytradify.execution.models;

public record CloseAllResponse(
        boolean success,
        CloseAllData data,
        String error
) {
    public static CloseAllResponse success(Integer closed, Double totalProfit) {
        return new CloseAllResponse(true, new CloseAllData(true, closed, totalProfit), null);
    }

    public static CloseAllResponse error(String error) {
        return new CloseAllResponse(false, null, error);
    }
}