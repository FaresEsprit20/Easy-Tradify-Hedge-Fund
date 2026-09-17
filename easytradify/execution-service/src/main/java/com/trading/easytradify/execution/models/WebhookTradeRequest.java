package com.trading.easytradify.execution.models;

public record WebhookTradeRequest(
        String symbol,
        Integer ticket,
        String closeReason,
        Double profit,
        Double priceOpen,
        Double priceClose,
        Double volume,
        Double sl,
        Double tp,
        String time
) {
    public WebhookTradeRequest {
        closeReason = closeReason != null ? closeReason : "SL_TP_HIT";
    }
}