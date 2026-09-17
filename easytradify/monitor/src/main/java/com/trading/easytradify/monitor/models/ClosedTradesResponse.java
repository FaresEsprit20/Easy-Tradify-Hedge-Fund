package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.Map;

/**
 * Response containing closed trades.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ClosedTradesResponse(
        boolean success,
        Integer count,
        List<Map<String, Object>> closedTrades,
        String error
) {
    public static ClosedTradesResponse success(Integer count, List<Map<String, Object>> closedTrades) {
        return new ClosedTradesResponse(true, count, closedTrades, null);
    }

    public static ClosedTradesResponse error(String error) {
        return new ClosedTradesResponse(false, null, null, error);
    }

}