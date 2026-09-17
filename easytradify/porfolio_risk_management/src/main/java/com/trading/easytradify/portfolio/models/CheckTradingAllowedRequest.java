package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>Check Trading Allowed Request</h1>
 * <p>
 * Request to check if trading is allowed based on portfolio risk limits.
 * </p>
 *
 * @param tradeRiskPercent Optional risk percentage for the trade being checked
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record CheckTradingAllowedRequest(
        Double tradeRiskPercent
) {
    public static CheckTradingAllowedRequest empty() {
        return new CheckTradingAllowedRequest(null);
    }

    public static CheckTradingAllowedRequest withRisk(Double tradeRiskPercent) {
        return new CheckTradingAllowedRequest(tradeRiskPercent);
    }
}