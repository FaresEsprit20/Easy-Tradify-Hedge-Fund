package com.trading.easytradify.execution.models;

public record ClosePositionData(
        Integer ticket,
        Double profit
) {}