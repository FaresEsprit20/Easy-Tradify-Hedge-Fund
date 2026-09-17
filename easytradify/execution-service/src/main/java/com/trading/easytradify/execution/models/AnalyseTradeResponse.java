package com.trading.easytradify.execution.models;

import java.util.Map;

public record AnalyseTradeResponse(
        boolean success,
        Map<String, Object> result,
        String error
) {
    public static AnalyseTradeResponse success(Map<String, Object> result) {
        return new AnalyseTradeResponse(true, result, null);
    }

    public static AnalyseTradeResponse error(String error) {
        return new AnalyseTradeResponse(false, null, error);
    }
}