package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>Portfolio Stats Response</h1>
 * <p>
 * Response containing portfolio statistics for a specified period.
 * </p>
 *
 * @param success Whether the request was successful
 * @param period  The statistics period: daily, monthly, or ytd
 * @param data    The statistics data (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PortfolioStatsResponse(
        boolean success,
        String period,
        Map<String, Object> data,
        String error
) {
    public static PortfolioStatsResponse success(Map<String, Object> data) {
        String period = (String) data.getOrDefault("period", "daily");
        return new PortfolioStatsResponse(true, period, data, null);
    }

    public static PortfolioStatsResponse error(String error) {
        return new PortfolioStatsResponse(false, null, null, error);
    }


}