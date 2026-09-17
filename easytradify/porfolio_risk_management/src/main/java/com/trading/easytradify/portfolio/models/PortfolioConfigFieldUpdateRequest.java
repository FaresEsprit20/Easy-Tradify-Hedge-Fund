package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;

/**
 * <h1>Portfolio Config Field Update Request</h1>
 * <p>
 * Request to update a specific configuration field.
 * </p>
 *
 * @param value The new value for the field
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PortfolioConfigFieldUpdateRequest(
        Object value
) {
    public PortfolioConfigFieldUpdateRequest {
        if (value == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Value cannot be null")
                    .build();
        }
    }
}