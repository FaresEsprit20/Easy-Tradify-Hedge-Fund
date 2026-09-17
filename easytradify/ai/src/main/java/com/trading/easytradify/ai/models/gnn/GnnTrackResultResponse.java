package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>GNN Track Result Response</h1>
 * <p>
 * Response indicating the result of tracking a GNN outcome.
 * </p>
 *
 * @param success Whether the tracking was successful
 * @param message Success message (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnTrackResultResponse(
        boolean success,
        String message,
        String error
) {
    public static GnnTrackResultResponse success(String message) {
        return new GnnTrackResultResponse(true, message, null);
    }

    public static GnnTrackResultResponse error(String error) {
        return new GnnTrackResultResponse(false, null, error);
    }
}