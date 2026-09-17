package com.trading.easytradify.execution.models;

import java.util.Map;

public record PositionResponse(
        boolean success,
        Map<String, Object> position,
        String error
) {
    public static PositionResponse success(Map<String, Object> position) {
        return new PositionResponse(true, position, null);
    }

    public static PositionResponse error(String error) {
        return new PositionResponse(false, null, error);
    }
}