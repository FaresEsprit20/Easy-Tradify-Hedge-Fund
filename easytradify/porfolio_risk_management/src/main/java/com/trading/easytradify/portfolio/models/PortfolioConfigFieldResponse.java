package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>Portfolio Config Field Response</h1>
 * <p>
 * Response containing a specific configuration field value.
 * </p>
 *
 * @param success Whether the request was successful
 * @param field   The field name
 * @param value   The field value (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PortfolioConfigFieldResponse(
        boolean success,
        String field,
        Object value,
        String error
) {
    public static PortfolioConfigFieldResponse success(String field, Object value) {
        return new PortfolioConfigFieldResponse(true, field, value, null);
    }

    public static PortfolioConfigFieldResponse error(String error) {
        return new PortfolioConfigFieldResponse(false, null, null, error);
    }
}