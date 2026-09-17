package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>GNN Track Result Request</h1>
 * <p>
 * Request to track a trade outcome for A/B testing.
 * </p>
 *
 * @param tradeId  The trade ID/ticket number
 * @param profit   The profit in USD
 * @param outcome  The outcome: 1 = WIN, 0 = LOSS
 * @param gnnUsed  Whether GNN was used for the trade
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnTrackResultRequest(
        Integer tradeId,
        Double profit,
        Integer outcome,
        Boolean gnnUsed
) {
    // No validation in constructor - handled by service
}