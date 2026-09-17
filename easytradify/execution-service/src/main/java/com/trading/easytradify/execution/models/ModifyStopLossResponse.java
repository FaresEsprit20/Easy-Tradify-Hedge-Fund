package com.trading.easytradify.execution.models;

public record ModifyStopLossResponse(
        boolean success,
        ModifyStopLossData data,
        String error
) {
    public static ModifyStopLossResponse success(Integer ticket, Double newSl) {
        return new ModifyStopLossResponse(true, new ModifyStopLossData(ticket, newSl), null);
    }

    public static ModifyStopLossResponse error(String error) {
        return new ModifyStopLossResponse(false, null, error);
    }
}