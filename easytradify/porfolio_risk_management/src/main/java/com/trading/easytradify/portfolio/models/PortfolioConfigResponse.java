package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>Portfolio Config Response</h1>
 * <p>
 * Response containing the portfolio risk configuration.
 * </p>
 *
 * @param success Whether the request was successful
 * @param config  The configuration data (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PortfolioConfigResponse(
        boolean success,
        Map<String, Object> config,
        String error
) {
    public static PortfolioConfigResponse success(Map<String, Object> config) {
        return new PortfolioConfigResponse(true, config, null);
    }

    public static PortfolioConfigResponse error(String error) {
        return new PortfolioConfigResponse(false, null, error);
    }
}