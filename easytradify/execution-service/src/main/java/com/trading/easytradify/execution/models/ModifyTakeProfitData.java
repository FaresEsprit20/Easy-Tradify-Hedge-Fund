package com.trading.easytradify.execution.models;

public record ModifyTakeProfitData(
        Integer ticket,
        Double newTp
) {}