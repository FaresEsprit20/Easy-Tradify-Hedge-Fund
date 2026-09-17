// execution-service/src/main/java/.../execution/domain/model/ModifyStopLossResult.java
package com.trading.easytradify.execution.models;

import java.util.Map;

public record ModifyStopLossResult(
        boolean success,
        Integer ticket,
        Double newSl,
        String error
) {
    public static ModifyStopLossResult fromPythonResponse(Map<String, Object> response) {
        if (response == null) {
            return error("Empty response from Python");
        }
        boolean success = (boolean) response.getOrDefault("success", false);
        if (success) {
            @SuppressWarnings("unchecked")
            Map<String, Object> data = (Map<String, Object>) response.get("data");
            return new ModifyStopLossResult(
                    true,
                    (Integer) data.get("ticket"),
                    (Double) data.get("new_sl"),
                    null
            );
        }
        return error((String) response.getOrDefault("error", "Unknown error"));
    }

    public static ModifyStopLossResult error(String error) {
        return new ModifyStopLossResult(false, null, null, error);
    }
}