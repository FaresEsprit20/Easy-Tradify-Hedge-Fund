package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;
import java.util.Map;

/**
 * <h1>GNN Correlation Changes Response</h1>
 * <p>
 * Response containing significant changes in correlations (regime shifts).
 * </p>
 *
 * @param success Whether the request was successful
 * @param symbol  The trading symbol
 * @param changes List of correlation changes (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnCorrelationChangesResponse(
        boolean success,
        String symbol,
        List<Map<String, Object>> changes,
        String error
) {
    public static GnnCorrelationChangesResponse success(String symbol, List<Map<String, Object>> changes) {
        return new GnnCorrelationChangesResponse(true, symbol, changes, null);
    }

    public static GnnCorrelationChangesResponse error(String error) {
        return new GnnCorrelationChangesResponse(false, null, null, error);
    }
}