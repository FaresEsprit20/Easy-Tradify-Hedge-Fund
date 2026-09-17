// execution-service/src/main/java/.../execution/domain/model/ClosePositionResult.java
package com.trading.easytradify.execution.models;

import java.util.Map;

public record ClosePositionResult(
        boolean success,
        Integer ticket,
        Double profit,
        String error
)
{
    public static ClosePositionResult fromPythonResponse(Map<String, Object> response) {
        if (response == null) {
            return error("Empty response from Python");
        }
        boolean success = (boolean) response.getOrDefault("success", false);
        if (success) {
            @SuppressWarnings("unchecked")
            Map<String, Object> data = (Map<String, Object>) response.get("data");
            return new ClosePositionResult(
                    true,
                    (Integer) data.get("ticket"),
                    (Double) data.get("profit"),
                    null
            );
        }
        return error((String) response.getOrDefault("error", "Unknown error"));
    }

    public static ClosePositionResult error(String error) {
        return new ClosePositionResult(false, null, null, error);
    }

}