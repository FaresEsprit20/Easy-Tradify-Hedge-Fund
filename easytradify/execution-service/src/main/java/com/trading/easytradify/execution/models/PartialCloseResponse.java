// execution-service/src/main/java/.../execution/models/PartialCloseResponse.java
package com.trading.easytradify.execution.models;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record PartialCloseResponse(
        boolean success,
        PartialCloseData data,
        String error
) {
    public static PartialCloseResponse fromPythonResponse(Map<String, Object> response) {
        if (response == null) {
            return error("Empty response from Python");
        }
        boolean success = (boolean) response.getOrDefault("success", false);
        if (success) {
            @SuppressWarnings("unchecked")
            Map<String, Object> data = (Map<String, Object>) response.get("data");
            return new PartialCloseResponse(
                    true,
                    new PartialCloseData(
                            (Integer) data.get("ticket"),
                            (Double) data.get("remaining_volume"),
                            (Double) data.get("closed_volume"),
                            (Double) data.get("profit")
                    ),
                    null
            );
        }
        return error((String) response.getOrDefault("error", "Unknown error"));
    }

    public static PartialCloseResponse success(Integer ticket, Double remainingVolume, Double closedVolume, Double profit) {
        return new PartialCloseResponse(true, new PartialCloseData(ticket, remainingVolume, closedVolume, profit), null);
    }

    public static PartialCloseResponse error(String error) {
        return new PartialCloseResponse(false, null, error);
    }
}