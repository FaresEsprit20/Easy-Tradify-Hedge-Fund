package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>GNN Status Response</h1>
 * <p>
 * Response containing the GNN status and configuration.
 * </p>
 *
 * @param success Whether the request was successful
 * @param status  The GNN status data (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnStatusResponse(
        boolean success,
        Map<String, Object> status,
        String error
) {
    public static GnnStatusResponse success(Map<String, Object> status) {
        return new GnnStatusResponse(true, status, null);
    }

    public static GnnStatusResponse error(String error) {
        return new GnnStatusResponse(false, null, error);
    }
}