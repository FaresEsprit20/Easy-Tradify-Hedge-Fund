package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Response for webhook debug information.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WebhookDebugResponse(
        Boolean executorInitialized,
        Boolean executorRunning,
        Integer webhookClosedTickets,
        Integer openPositions,
        String webhookUrl,
        String trailingUrl,
        String timestamp
) {
    public static WebhookDebugResponse success(Boolean executorInitialized, Boolean executorRunning,
                                               Integer webhookClosedTickets, Integer openPositions,
                                               String webhookUrl, String trailingUrl) {
        return new WebhookDebugResponse(
                executorInitialized,
                executorRunning,
                webhookClosedTickets,
                openPositions,
                webhookUrl,
                trailingUrl,
                java.time.Instant.now().toString()
        );
    }

    public static WebhookDebugResponse defaultDebug() {
        return new WebhookDebugResponse(
                true,
                true,
                0,
                0,
                "/webhook/trade",
                "/webhook/trailing",
                java.time.Instant.now().toString()
        );
    }
}