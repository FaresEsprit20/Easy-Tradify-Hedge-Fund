package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>Refresh Response</h1>
 * <p>
 * Response indicating the result of a portfolio statistics refresh.
 * </p>
 *
 * @param success Whether the refresh was successful
 * @param message Success message (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record RefreshResponse(
        boolean success,
        String message,
        String error
) {
    public static RefreshResponse success(String message) {
        return new RefreshResponse(true, message, null);
    }

    public static RefreshResponse error(String error) {
        return new RefreshResponse(false, null, error);
    }
}