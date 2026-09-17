package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>GNN Refresh Response</h1>
 * <p>
 * Response indicating the result of a GNN refresh.
 * </p>
 *
 * @param success Whether the refresh was successful
 * @param message Success message (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnRefreshResponse(
        boolean success,
        String message,
        String error
) {
    public static GnnRefreshResponse success(String message) {
        return new GnnRefreshResponse(true, message, null);
    }

    public static GnnRefreshResponse error(String error) {
        return new GnnRefreshResponse(false, null, error);
    }
}