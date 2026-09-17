package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;

/**
 * <h1>Check Trading Allowed Response</h1>
 * <p>
 * Response containing the result of a trading permission check.
 * </p>
 *
 * @param success                 Whether the request was successful
 * @param isTradingAllowed        Whether trading is allowed
 * @param riskLevel               The risk level: SAFE, CAUTION, WARNING, CRITICAL, MAX_EXCEEDED
 * @param reasons                 List of reasons why trading is blocked (empty if allowed)
 * @param requestedRiskPercent    The requested risk percentage (if provided)
 * @param maxRiskPerTradePercent  The maximum allowed risk per trade
 * @param error                   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record CheckTradingAllowedResponse(
        boolean success,
        Boolean isTradingAllowed,
        String riskLevel,
        List<String> reasons,
        Double requestedRiskPercent,
        Double maxRiskPerTradePercent,
        String error
) {
    public static CheckTradingAllowedResponse allowed(Double maxRiskPerTradePercent) {
        return new CheckTradingAllowedResponse(
                true,
                true,
                "SAFE",
                List.of(),
                null,
                maxRiskPerTradePercent,
                null
        );
    }

    public static CheckTradingAllowedResponse blocked(
            String riskLevel,
            List<String> reasons,
            Double maxRiskPerTradePercent) {
        return new CheckTradingAllowedResponse(
                true,
                false,
                riskLevel,
                reasons,
                null,
                maxRiskPerTradePercent,
                null
        );
    }

    public static CheckTradingAllowedResponse blockedWithRisk(
            String riskLevel,
            List<String> reasons,
            Double requestedRiskPercent,
            Double maxRiskPerTradePercent) {
        return new CheckTradingAllowedResponse(
                true,
                false,
                riskLevel,
                reasons,
                requestedRiskPercent,
                maxRiskPerTradePercent,
                null
        );
    }

    public static CheckTradingAllowedResponse error(String error) {
        return new CheckTradingAllowedResponse(false, null, null, null, null, null, error);
    }
}