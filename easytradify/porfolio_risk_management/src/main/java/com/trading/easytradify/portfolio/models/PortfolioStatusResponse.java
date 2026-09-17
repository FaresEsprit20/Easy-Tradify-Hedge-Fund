package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;
import java.util.Map;

/**
 * <h1>Portfolio Status Response</h1>
 * <p>
 * Response containing the complete portfolio status including account information,
 * daily/monthly/YTD performance, and risk metrics.
 * </p>
 *
 * @param success Whether the request was successful
 * @param status  The portfolio status data (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PortfolioStatusResponse(
        boolean success,
        Map<String, Object> status,
        String error
) {
    public static PortfolioStatusResponse success(Map<String, Object> status) {
        return new PortfolioStatusResponse(true, status, null);
    }

    public static PortfolioStatusResponse error(String error) {
        return new PortfolioStatusResponse(false, null, error);
    }
}