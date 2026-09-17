package com.trading.easytradify.execution.models;

public record TrailingEnableData(
        Integer ticket,
        Double trailingPips,
        String symbol
) {}