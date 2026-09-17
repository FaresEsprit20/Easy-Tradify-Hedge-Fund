package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>GNN Reset Response</h1>
 * <p>
 * Response indicating the result of a GNN reset.
 * </p>
 *
 * @param success Whether the reset was successful
 * @param message Success message (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnResetResponse(
        boolean success,
        String message,
        String error
) {
    public static GnnResetResponse success(String message) {
        return new GnnResetResponse(true, message, null);
    }

    public static GnnResetResponse error(String error) {
        return new GnnResetResponse(false, null, error);
    }
}