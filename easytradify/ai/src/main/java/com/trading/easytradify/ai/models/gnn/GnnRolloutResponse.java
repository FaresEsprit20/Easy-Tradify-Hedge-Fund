package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>GNN Rollout Response</h1>
 * <p>
 * Response indicating the result of setting A/B test rollout percentage.
 * </p>
 *
 * @param success Whether the rollout update was successful
 * @param message Success message (success case)
 * @param rollout The rollout percentage (0.0 - 1.0)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnRolloutResponse(
        boolean success,
        String message,
        Double rollout,
        String error
) {
    public static GnnRolloutResponse success(String message, Double rollout) {
        return new GnnRolloutResponse(true, message, rollout, null);
    }

    public static GnnRolloutResponse error(String error) {
        return new GnnRolloutResponse(false, null, null, error);
    }
}