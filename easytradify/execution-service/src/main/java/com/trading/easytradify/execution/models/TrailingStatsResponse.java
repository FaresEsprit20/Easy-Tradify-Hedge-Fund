package com.trading.easytradify.execution.models;

import java.util.Map;

public record TrailingStatsResponse(
        boolean success,
        Map<String, Object> data,
        String error
) {
    public static TrailingStatsResponse success(Map<String, Object> data) {
        return new TrailingStatsResponse(true, data, null);
    }

    public static TrailingStatsResponse error(String error) {
        return new TrailingStatsResponse(false, null, error);
    }
}