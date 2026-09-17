package com.trading.easytradify.execution.models;

import java.util.List;
import java.util.Map;

public record TrailingStatusResponse(

        boolean success,
        List<Map<String, Object>> activeTrails,
        Integer count,
        String error
) {
    public static TrailingStatusResponse success(List<Map<String, Object>> activeTrails) {
        return new TrailingStatusResponse(true, activeTrails, activeTrails.size(), null);
    }

    public static TrailingStatusResponse error(String error) {
        return new TrailingStatusResponse(false, null, null, error);
    }


}