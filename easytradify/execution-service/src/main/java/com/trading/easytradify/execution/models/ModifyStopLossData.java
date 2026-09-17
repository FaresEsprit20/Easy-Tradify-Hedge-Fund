package com.trading.easytradify.execution.models;

public record ModifyStopLossData(
        Integer ticket,
        Double newSl
) {}