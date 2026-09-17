package com.trading.easytradify.monitor.models;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

/**
 * Webhook request for trade closure from MT5.
 */
public record WebhookTradeRequest(

        @NotBlank(message = "Symbol is required")
        String symbol,

        @NotNull(message = "Ticket is required")
        @Positive(message = "Ticket must be positive")
        Integer ticket,

        String closeReason,

        Double profit,

        @Positive(message = "Price open must be positive")
        Double priceOpen,

        @Positive(message = "Price close must be positive")
        Double priceClose,

        @Positive(message = "Volume must be positive")
        Double volume,

        @Positive(message = "Stop loss must be positive")
        Double sl,

        @Positive(message = "Take profit must be positive")
        Double tp,

        String time
) {
    public WebhookTradeRequest {
        closeReason = closeReason != null ? closeReason : "SL_TP_HIT";
        profit = profit != null ? profit : 0.0;
        volume = volume != null ? volume : 0.0;
        sl = sl != null ? sl : 0.0;
        tp = tp != null ? tp : 0.0;
        priceOpen = priceOpen != null ? priceOpen : 0.0;
        priceClose = priceClose != null ? priceClose : 0.0;
        time = time != null ? time : java.time.Instant.now().toString();
    }
}