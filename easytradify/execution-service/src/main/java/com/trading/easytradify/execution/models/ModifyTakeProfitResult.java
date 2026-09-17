// execution-service/src/main/java/.../execution/domain/model/ModifyTakeProfitResult.java
package com.trading.easytradify.execution.models;

import java.util.Map;

public record ModifyTakeProfitResult(
        boolean success,
        Integer ticket,
        Double newTp,
        String error
) {
    public static ModifyTakeProfitResult fromPythonResponse(Map<String, Object> response) {
        if (response == null) {
            return error("Empty response from Python");
        }
        boolean success = (boolean) response.getOrDefault("success", false);
        if (success) {
            @SuppressWarnings("unchecked")
            Map<String, Object> data = (Map<String, Object>) response.get("data");
            return new ModifyTakeProfitResult(
                    true,
                    (Integer) data.get("ticket"),
                    (Double) data.get("new_tp"),
                    null
            );
        }
        return error((String) response.getOrDefault("error", "Unknown error"));
    }

    public static ModifyTakeProfitResult error(String error) {
        return new ModifyTakeProfitResult(false, null, null, error);
    }
}