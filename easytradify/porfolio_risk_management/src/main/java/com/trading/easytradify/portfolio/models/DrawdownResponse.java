package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>Drawdown Response</h1>
 * <p>
 * Response containing drawdown information.
 * </p>
 *
 * @param success           Whether the request was successful
 * @param currentPercent    Current drawdown as percentage
 * @param maxPercent        Maximum historical drawdown as percentage
 * @param error             Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record DrawdownResponse(
        boolean success,
        Double currentPercent,
        Double maxPercent,
        String error
) {
    public static DrawdownResponse success(Double currentPercent, Double maxPercent) {
        return new DrawdownResponse(true, currentPercent, maxPercent, null);
    }

    public static DrawdownResponse error(String error) {
        return new DrawdownResponse(false, null, null, error);
    }
}