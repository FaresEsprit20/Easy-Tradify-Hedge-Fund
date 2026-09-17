package com.trading.easytradify.execution.models;

import com.fasterxml.jackson.annotation.JsonInclude;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record TrailingStopResponse(
        boolean success,
        String message,
        TrailingEnableData data,
        String error
) {
    public static TrailingStopResponse success(Integer ticket, String symbol, Double trailingPips, String message) {
        return new TrailingStopResponse(true, message, new TrailingEnableData(ticket, trailingPips, symbol), null);
    }

    public static TrailingStopResponse error(String error) {
        return new TrailingStopResponse(false, null, null, error);
    }
}