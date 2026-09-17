package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Response containing a symbol's ranking information.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record SymbolRankResponse(
        String symbol,
        Double confidence,
        Boolean isActive,
        Boolean inPosition,
        Integer ticket,
        String exchange,
        String reason,
        Double entryPrice,
        String lastCheckTime,
        String stabilityStatus
) {
    public static SymbolRankResponse active(String symbol, Double confidence, String reason) {
        return new SymbolRankResponse(symbol, confidence, true, false, null,
                null, reason, null, null, "UNKNOWN");
    }

    public static SymbolRankResponse inactive(String symbol, String reason) {
        return new SymbolRankResponse(symbol, 0.0, false, false, null,
                null, reason, null, null, "UNKNOWN");
    }

}