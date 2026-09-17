package com.trading.easytradify.execution.models;

public record TradeExecutionData(
        Integer ticket,
        Double price,
        Double stopLoss,
        Double takeProfit,
        Double volume,
        Double actualMargin,
        Double actualRiskUsd,
        Double takeProfit2Reference,
        Double takeProfit3Reference,
        String note
) {}