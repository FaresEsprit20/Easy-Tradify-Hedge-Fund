package com.trading.easytradify.execution.models;

import java.util.List;
import java.util.Map;

public record TradeHistoryResponse(
        boolean success,
        Integer count,
        List<Map<String, Object>> deals,
        List<Map<String, Object>> trades,
        Map<String, Object> summary,
        String error
) {
    public static TradeHistoryResponse success(Integer count, List<Map<String, Object>> deals,
                                               List<Map<String, Object>> trades,
                                               Map<String, Object> summary) {
        return new TradeHistoryResponse(true, count, deals, trades, summary, null);
    }

    public static TradeHistoryResponse error(String error) {
        return new TradeHistoryResponse(false, null, null, null, null, error);
    }
}