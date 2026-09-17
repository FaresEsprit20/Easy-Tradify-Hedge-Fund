package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>GNN Heatmap Response</h1>
 * <p>
 * Response containing a correlation heatmap for symbols.
 * </p>
 *
 * @param success Whether the request was successful
 * @param heatmap The correlation heatmap data (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnHeatmapResponse(
        boolean success,
        Map<String, Object> heatmap,
        String error
) {
    public static GnnHeatmapResponse success(Map<String, Object> heatmap) {
        return new GnnHeatmapResponse(true, heatmap, null);
    }

    public static GnnHeatmapResponse error(String error) {
        return new GnnHeatmapResponse(false, null, error);
    }
}