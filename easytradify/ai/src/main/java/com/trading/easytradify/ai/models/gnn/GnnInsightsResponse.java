package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>GNN Insights Response</h1>
 * <p>
 * Response containing complete trading insights for a symbol.
 * Includes correlations, divergences, suggestions, and risk warnings.
 * </p>
 *
 * @param success  Whether the request was successful
 * @param symbol   The trading symbol
 * @param insights The complete insights data (success case)
 * @param error    Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnInsightsResponse(
        boolean success,
        String symbol,
        Map<String, Object> insights,
        String error
) {
    public static GnnInsightsResponse success(String symbol, Map<String, Object> insights) {
        return new GnnInsightsResponse(true, symbol, insights, null);
    }

    public static GnnInsightsResponse error(String error) {
        return new GnnInsightsResponse(false, null, null, error);
    }
}