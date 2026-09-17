package com.trading.easytradify.execution.models;

public record ModifyTakeProfitResponse(
        boolean success,
        ModifyTakeProfitData data,
        String error
) {
    public static ModifyTakeProfitResponse success(Integer ticket, Double newTp) {
        return new ModifyTakeProfitResponse(true, new ModifyTakeProfitData(ticket, newTp), null);
    }

    public static ModifyTakeProfitResponse error(String error) {
        return new ModifyTakeProfitResponse(false, null, error);
    }
}