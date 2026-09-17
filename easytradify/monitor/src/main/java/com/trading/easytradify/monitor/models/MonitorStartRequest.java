package com.trading.easytradify.monitor.models;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Positive;

/**
 * Request to start or configure the monitor.
 */
public record MonitorStartRequest(
        @Positive(message = "Scan interval must be positive")
        @Min(value = 5000, message = "Scan interval must be at least 5000ms")
        Long scanInterval,

        @Positive(message = "Max top symbols must be positive")
        @Min(value = 1, message = "Max top symbols must be at least 1")
        Integer maxTopSymbols,

        @Positive(message = "Min confidence must be positive")
        @Min(value = 0, message = "Min confidence must be at least 0")
        @Max(value = 100, message = "Min confidence must be at most 100")
        Integer minConfidence
) {
    public MonitorStartRequest {
        // Use defaults if not provided
        scanInterval = scanInterval != null ? scanInterval : 60000L;
        maxTopSymbols = maxTopSymbols != null ? maxTopSymbols : 10;
        minConfidence = minConfidence != null ? minConfidence : 60;
    }

    public static MonitorStartRequest defaultConfig() {
        return new MonitorStartRequest(60000L, 10, 60);
    }
}