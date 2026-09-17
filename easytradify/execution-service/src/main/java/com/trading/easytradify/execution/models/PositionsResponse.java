package com.trading.easytradify.execution.models;

import java.util.List;
import java.util.Map;

public record PositionsResponse(
        boolean success,
        Integer count,
        List<Map<String, Object>> positions,
        PositionSummary summary,
        String error
) {
    public static PositionsResponse success(Integer count, List<Map<String, Object>> positions, PositionSummary summary) {
        return new PositionsResponse(true, count, positions, summary, null);
    }

    public static PositionsResponse error(String error) {
        return new PositionsResponse(false, null, null, null, error);
    }
}