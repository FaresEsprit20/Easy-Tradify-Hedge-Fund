package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Response for webhook health check.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WebhookHealthResponse(
        String status,
        Integer openPositions,
        Boolean running,
        Integer webhookClosedTickets,
        String timestamp
) {
    public static WebhookHealthResponse healthy(Integer openPositions, Boolean running,
                                                Integer webhookClosedTickets) {
        return new WebhookHealthResponse(
                "healthy",
                openPositions,
                running,
                webhookClosedTickets,
                java.time.Instant.now().toString()
        );
    }

    public static WebhookHealthResponse unhealthy() {
        return new WebhookHealthResponse(
                "unhealthy",
                null,
                false,
                null,
                java.time.Instant.now().toString()
        );
    }
}