package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Health check response.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record HealthResponse(
        String status,
        Boolean running,
        Integer port,
        String webhookPort,
        Boolean gnnInitialized,
        String timestamp
) {
    public static HealthResponse operational(boolean running) {
        return new HealthResponse(
                "operational",
                running,
                8082,
                "8082",
                false,
                java.time.Instant.now().toString()
        );
    }

    public static HealthResponse error() {
        return new HealthResponse(
                "error",
                false,
                null,
                null,
                null,
                java.time.Instant.now().toString()
        );
    }
}