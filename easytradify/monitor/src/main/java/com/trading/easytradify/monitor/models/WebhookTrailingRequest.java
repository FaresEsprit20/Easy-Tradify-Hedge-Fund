package com.trading.easytradify.monitor.models;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

/**
 * Webhook request for trailing stop updates from MT5.
 */
public record WebhookTrailingRequest(
        @NotNull(message = "Ticket is required")
        @Positive(message = "Ticket must be positive")
        Integer ticket,

        String symbol,

        String action,

        @Positive(message = "Stop loss price must be positive")
        Double slPrice,

        @Positive(message = "Profit pips must be positive")
        Double profitPips,

        @Positive(message = "Step pips must be positive")
        Double stepPips,

        @Positive(message = "Price must be positive")
        Double price,

        @Positive(message = "Entry price must be positive")
        Double entryPrice,

        String timestamp
) {
    public WebhookTrailingRequest {
        action = action != null ? action : "ENABLE";
        profitPips = profitPips != null ? profitPips : 0.0;
        stepPips = stepPips != null ? stepPips : 5.0;
        price = price != null ? price : 0.0;
        entryPrice = entryPrice != null ? entryPrice : 0.0;
        timestamp = timestamp != null ? timestamp : java.time.Instant.now().toString();

        // Validation for negative values
        if (slPrice != null && slPrice <= 0) {
            throw new IllegalArgumentException("sl_price must be positive: " + slPrice);
        }
        if (stepPips != null && stepPips <= 0) {
            throw new IllegalArgumentException("step_pips must be positive: " + stepPips);
        }
    }

}