// execution-service/src/main/java/.../execution/domain/model/TradeExecutionResult.java
package com.trading.easytradify.execution.models;

import java.util.Map;

public record TradeExecutionResult(
        boolean success,
        Integer ticket,
        Double price,
        Double stopLoss,
        Double takeProfit,
        Double volume,
        Double actualMargin,
        Double actualRiskUsd,
        String error
) {
    public static TradeExecutionResult fromPythonResponse(Map<String, Object> response) {
        if (response == null) {
            return error("Empty response from Python");
        }
        boolean success = (boolean) response.getOrDefault("success", false);
        if (success) {
            @SuppressWarnings("unchecked")
            Map<String, Object> data = (Map<String, Object>) response.get("data");
            return new TradeExecutionResult(
                    true,
                    (Integer)data.get("ticket"),
                    (Double) data.get("price"),
                    (Double) data.get("stop_loss"),
                    (Double) data.get("take_profit"),
                    (Double) data.get("volume"),
                    (Double) data.get("actual_margin"),
                    (Double) data.get("actual_risk_usd"),
                    null
            );
        }
        return error((String) response.getOrDefault("error", "Unknown error"));
    }

    public static TradeExecutionResult error(String error) {
        return new TradeExecutionResult(false, null, null, null, null, null, null, null, error);
    }
}