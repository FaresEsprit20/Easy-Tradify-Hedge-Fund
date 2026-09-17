package com.trading.easytradify.execution.models;

import java.util.Map;

public record MarketConditionsResponse(
        boolean success,
        String symbol,
        Double currentPrice,
        Map<String, Object> metrics,
        Map<String, Object> tradingRecommendation,
        String error
) {
    public static MarketConditionsResponse success(String symbol, Double currentPrice,
                                                   Map<String, Object> metrics,
                                                   Map<String, Object> tradingRecommendation) {
        return new MarketConditionsResponse(true, symbol, currentPrice, metrics, tradingRecommendation, null);
    }

    public static MarketConditionsResponse error(String error) {
        return new MarketConditionsResponse(false, null, null, null, null, error);
    }
}