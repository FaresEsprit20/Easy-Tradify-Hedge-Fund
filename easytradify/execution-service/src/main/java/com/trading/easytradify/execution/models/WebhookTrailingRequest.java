package com.trading.easytradify.execution.models;

public record WebhookTrailingRequest(
        Integer ticket,
        String symbol,
        String action,
        Double slPrice,
        Double profitPips,
        Double stepPips,
        Double price,
        Double entryPrice,
        String timestamp
) {
    public WebhookTrailingRequest {
        // ✅ FIXED: Add validation for stepPips
        if (stepPips != null && stepPips <= 0) {
            throw new IllegalArgumentException("step_pips must be positive: " + stepPips);
        }
        if (slPrice != null && slPrice <= 0) {
            throw new IllegalArgumentException("sl_price must be positive: " + slPrice);
        }
    }
}