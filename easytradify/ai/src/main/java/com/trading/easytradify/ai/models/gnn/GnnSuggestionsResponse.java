package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;
import java.util.Map;

/**
 * <h1>GNN Suggestions Response</h1>
 * <p>
 * Response containing trade suggestions for correlated symbols.
 * Returns BUY/SELL actions with confidence scores.
 * </p>
 *
 * @param success     Whether the request was successful
 * @param symbol      The trading symbol
 * @param suggestions List of trade suggestions (success case)
 * @param error       Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnSuggestionsResponse(
        boolean success,
        String symbol,
        List<Map<String, Object>> suggestions,
        String error
) {
    public static GnnSuggestionsResponse success(String symbol, List<Map<String, Object>> suggestions) {
        return new GnnSuggestionsResponse(true, symbol, suggestions, null);
    }

    public static GnnSuggestionsResponse error(String error) {
        return new GnnSuggestionsResponse(false, null, null, error);
    }
}