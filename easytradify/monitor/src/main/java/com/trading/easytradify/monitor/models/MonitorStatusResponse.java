package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.Map;

/**
 * Response containing monitor status information.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record MonitorStatusResponse(
        boolean success,
        boolean running,
        String lastScan,
        Integer totalSymbols,
        Integer activePositions,
        Map<String, Object> stats,
        String error
) {
    public static MonitorStatusResponse success(boolean running, String lastScan,
                                                Integer totalSymbols, Integer activePositions,
                                                Map<String, Object> stats) {
        return new MonitorStatusResponse(true, running, lastScan, totalSymbols,
                activePositions, stats, null);
    }

    public static MonitorStatusResponse error(String error) {
        return new MonitorStatusResponse(false, false, null, null, null, null, error);
    }
}