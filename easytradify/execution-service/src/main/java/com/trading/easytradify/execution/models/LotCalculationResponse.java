package com.trading.easytradify.execution.models;

import java.util.Map;

public record LotCalculationResponse(
        boolean success,
        Map<String, Object> data,
        String error
) {
    public static LotCalculationResponse success(Map<String, Object> data) {
        return new LotCalculationResponse(true, data, null);
    }

    public static LotCalculationResponse error(String error) {
        return new LotCalculationResponse(false, null, error);
    }
}