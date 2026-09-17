package com.trading.easytradify.execution.models;

public record CloseAllData(
        Boolean success,
        Integer closed,
        Double totalProfit
) {}