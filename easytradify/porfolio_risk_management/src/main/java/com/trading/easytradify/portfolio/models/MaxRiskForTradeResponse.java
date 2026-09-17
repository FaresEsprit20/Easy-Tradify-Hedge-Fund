package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>Max Risk For Trade Response</h1>
 * <p>
 * Response containing the maximum risk percentage allowed for a trade.
 * </p>
 *
 * @param success                 Whether the request was successful
 * @param maxRiskPerTradePercent  The maximum risk percentage allowed
 * @param error                   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record MaxRiskForTradeResponse(
        boolean success,
        Double maxRiskPerTradePercent,
        String error
) {
    public static MaxRiskForTradeResponse success(Double maxRiskPerTradePercent) {
        return new MaxRiskForTradeResponse(true, maxRiskPerTradePercent, null);
    }

    public static MaxRiskForTradeResponse error(String error) {
        return new MaxRiskForTradeResponse(false, null, error);
    }
}