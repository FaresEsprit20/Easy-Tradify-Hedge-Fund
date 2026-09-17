package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>GNN Conflict Response</h1>
 * <p>
 * Response containing contradiction detection between your analysis and GNN.
 * </p>
 *
 * <h4>Conflict Severity</h4>
 * <ul>
 *   <li><b>NONE:</b> Your analysis aligns with GNN</li>
 *   <li><b>LOW:</b> Minor disagreement</li>
 *   <li><b>MEDIUM:</b> Significant disagreement</li>
 *   <li><b>HIGH:</b> Strong contradiction</li>
 * </ul>
 *
 * @param success            Whether the request was successful
 * @param symbol             The trading symbol
 * @param yourAnalysis       Your analysis direction (BUY or SELL)
 * @param conflict           Conflict detection result (success case)
 * @param gnnInsights        GNN insights for context
 * @param error              Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnConflictResponse(
        boolean success,
        String symbol,
        String yourAnalysis,
        Object conflict,
        Map<String, Object> gnnInsights,
        String error
) {
    public static GnnConflictResponse success(
            String symbol,
            String yourAnalysis,
            Object conflict,
            Map<String, Object> gnnInsights) {
        return new GnnConflictResponse(true, symbol, yourAnalysis, conflict, gnnInsights, null);
    }

    public static GnnConflictResponse error(String error) {
        return new GnnConflictResponse(false, null, null, null, null, error);
    }
}