package com.trading.easytradify.ai.models.gnn;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>GNN A/B Test Response</h1>
 * <p>
 * Response containing GNN A/B test results and statistics.
 * </p>
 *
 * <h4>Statistics Include</h4>
 * <ul>
 *   <li>Total trades with GNN</li>
 *   <li>Total trades without GNN</li>
 *   <li>Win rates for both groups</li>
 *   <li>Profit/loss comparison</li>
 *   <li>Statistical significance</li>
 * </ul>
 *
 * @param success Whether the request was successful
 * @param results The A/B test results (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record GnnAbTestResponse(
        boolean success,
        Map<String, Object> results,
        String error
) {
    public static GnnAbTestResponse success(Map<String, Object> results) {
        return new GnnAbTestResponse(true, results, null);
    }

    public static GnnAbTestResponse error(String error) {
        return new GnnAbTestResponse(false, null, error);
    }

}