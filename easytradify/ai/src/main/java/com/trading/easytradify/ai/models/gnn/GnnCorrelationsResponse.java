package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;
import java.util.Map;

/**
 * <h1>GNN Correlations Response</h1>
 * <p>
 * Response containing correlation information for a symbol.
 * Returns dynamic correlation matrix with confidence scores.
 * </p>
 *
 * @param success      Whether the request was successful
 * @param symbol       The trading symbol
 * @param correlations List of correlation entries (success case)
 * @param error        Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnCorrelationsResponse(
        boolean success,
        String symbol,
        List<Map<String, Object>> correlations,
        String error
) {
    public static GnnCorrelationsResponse success(String symbol, List<Map<String, Object>> correlations) {
        return new GnnCorrelationsResponse(true, symbol, correlations, null);
    }

    public static GnnCorrelationsResponse error(String error) {
        return new GnnCorrelationsResponse(false, null, null, error);
    }
}