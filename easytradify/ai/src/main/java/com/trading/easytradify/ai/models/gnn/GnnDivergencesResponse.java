package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>GNN Divergences Response</h1>
 * <p>
 * Response containing divergence detection between GNN and price direction.
 * </p>
 *
 * <h4>Divergence Types</h4>
 * <ul>
 *   <li><b>BULLISH:</b> Price making lower lows, GNN making higher lows</li>
 *   <li><b>BEARISH:</b> Price making higher highs, GNN making lower highs</li>
 * </ul>
 *
 * @param success    Whether the request was successful
 * @param symbol     The trading symbol
 * @param divergence The divergence data (success case)
 * @param error      Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnDivergencesResponse(
        boolean success,
        String symbol,
        Map<String, Object> divergence,
        String error
) {
    public static GnnDivergencesResponse success(String symbol, Map<String, Object> divergence) {
        return new GnnDivergencesResponse(true, symbol, divergence, null);
    }

    public static GnnDivergencesResponse error(String error) {
        return new GnnDivergencesResponse(false, null, null, error);
    }
}