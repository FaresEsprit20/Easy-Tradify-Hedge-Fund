package com.trading.easytradify.execution.models;

public record PositionSummary(
        Double totalRiskUsd,
        Double totalPotentialRewardUsd,
        Double totalProfitUsd,
        Double avgProbabilityPercent,
        Double totalExpectedValue
) {
    public static PositionSummary empty() {
        return new PositionSummary(0.0, 0.0, 0.0, 0.0, 0.0);
    }
}