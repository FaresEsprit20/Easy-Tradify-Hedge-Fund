package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

/**
 * <h1>GNN Rollout Request</h1>
 * <p>
 * Request to set the A/B test rollout percentage for GNN.
 * </p>
 *
 * @param rollout The rollout percentage (0.0 - 1.0)
 *                - 0.0 = 0% of trades use GNN
 *                - 0.5 = 50% of trades use GNN
 *                - 1.0 = 100% of trades use GNN
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnRolloutRequest(
        @NotNull(message = "Rollout is required")
        @Min(value = 0, message = "Rollout must be between 0.0 and 1.0")
        @Max(value = 1, message = "Rollout must be between 0.0 and 1.0")
        Double rollout
) {
    // No validation in constructor - handled by jakarta validation
}