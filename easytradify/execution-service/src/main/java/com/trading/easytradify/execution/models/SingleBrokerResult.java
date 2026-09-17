package com.trading.easytradify.execution.models;

public record SingleBrokerResult(
        String broker,
        boolean success,
        Integer ticket,
        Double price,
        Double stopLoss,
        Double takeProfit,
        Double volume,
        Double actualMargin,
        Double actualRiskUsd,
        String error
) {
    public static SingleBrokerResult success(String broker, Integer ticket, Double price, Double stopLoss,
                                             Double takeProfit, Double volume, Double actualMargin,
                                             Double actualRiskUsd) {
        return new SingleBrokerResult(broker, true, ticket, price, stopLoss, takeProfit,
                volume, actualMargin, actualRiskUsd, null);
    }

    public static SingleBrokerResult success(String broker, Integer ticket) {
        return new SingleBrokerResult(broker, true, ticket, null, null, null, null, null, null, null);
    }

    public static SingleBrokerResult error(String broker, String error) {
        return new SingleBrokerResult(broker, false, null, null, null, null, null, null, null, error);
    }
}