package com.trading.easytradify.execution.models;

public record HealthResponse(
        String status,
        Boolean mt5Connected,
        String timestamp
) {
    public static HealthResponse operational(boolean mt5Connected) {
        return new HealthResponse("operational", mt5Connected, java.time.Instant.now().toString());
    }

    public static HealthResponse error() {
        return new HealthResponse("error", false, java.time.Instant.now().toString());
    }
}