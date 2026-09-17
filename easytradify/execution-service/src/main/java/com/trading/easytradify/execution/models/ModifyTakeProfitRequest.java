package com.trading.easytradify.execution.models;

import java.util.List;

public record ModifyTakeProfitRequest(
        int ticket,
        double tpPrice,
        List<String> brokers
) {
    public ModifyTakeProfitRequest {
        brokers = brokers != null && !brokers.isEmpty() ? brokers : List.of("default");
    }
}