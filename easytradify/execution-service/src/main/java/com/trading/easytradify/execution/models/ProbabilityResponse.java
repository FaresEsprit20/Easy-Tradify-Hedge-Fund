package com.trading.easytradify.execution.models;

public record ProbabilityResponse(
        boolean success,
        Double probabilityPercent,
        Double probabilityDecimal,
        String symbol,
        String recommendation,
        String error
) {

    public static ProbabilityResponse success(double probability, String symbol) {
        return new ProbabilityResponse(
                true,
                probability * 100,
                probability,
                symbol,
                probability > 0.65 ? "HIGH_PROBABILITY" :
                        probability > 0.45 ? "MEDIUM_PROBABILITY" : "LOW_PROBABILITY",
                null
        );
    }

    public static ProbabilityResponse error(String error) {
        return new ProbabilityResponse(false, null, null, null, null, error);
    }

}