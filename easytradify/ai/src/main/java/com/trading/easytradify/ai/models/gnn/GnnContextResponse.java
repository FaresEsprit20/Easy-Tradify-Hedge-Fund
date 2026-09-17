package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>GNN Context Response</h1>
 * <p>
 * Response containing GNN context for a symbol.
 * Used in AI Asset Analyzer for feature extraction.
 * </p>
 *
 * <h4>Context Fields</h4>
 * <ul>
 *   <li><b>dxy_strength:</b> Dollar index strength (-1.0 to 1.0)</li>
 *   <li><b>risk_sentiment:</b> Risk-on/risk-off sentiment (-1.0 to 1.0)</li>
 *   <li><b>commodity_impact:</b> Commodity price impact (-1.0 to 1.0)</li>
 *   <li><b>sector_sentiment:</b> Sector sentiment (-1.0 to 1.0)</li>
 *   <li><b>global_confidence:</b> Global market confidence (0.0 to 1.0)</li>
 *   <li><b>trend_alignment:</b> Trend alignment score (0.0 to 1.0)</li>
 *   <li><b>market_regime:</b> Current market regime (TRENDING/RANGING/VOLATILE)</li>
 *   <li><b>correlation_shift:</b> Correlation changes (0.0 to 1.0)</li>
 *   <li><b>gnn_influence:</b> GNN influence score (0.0 to 1.0)</li>
 *   <li><b>gnn_connections:</b> Connected assets and weights</li>
 * </ul>
 *
 * @param success Whether the request was successful
 * @param symbol  The trading symbol
 * @param context The GNN context data (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnContextResponse(
        boolean success,
        String symbol,
        Map<String, Object> context,
        String error
) {
    public static GnnContextResponse success(String symbol, Map<String, Object> context) {
        return new GnnContextResponse(true, symbol, context, null);
    }

    public static GnnContextResponse error(String error) {
        return new GnnContextResponse(false, null, null, error);
    }
}