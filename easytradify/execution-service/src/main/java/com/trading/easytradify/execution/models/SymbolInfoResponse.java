package com.trading.easytradify.execution.models;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record SymbolInfoResponse(
        boolean success,
        String name,
        String description,
        String currencyBase,
        String currencyProfit,
        Integer digits,
        Double volumeMin,
        Double volumeMax,
        Double bid,
        Double ask,
        Double spreadPips,
        String error
) {
    // ============================================================
    // PUBLIC FACTORY METHODS
    // ============================================================

    public static SymbolInfoResponse fromPythonResponse(Map<String, Object> data) {
        if (data == null) {
            return error("Empty symbol data");
        }

        return new SymbolInfoResponse(
                true,
                (String) data.get("name"),
                (String) data.get("description"),
                (String) data.get("currency_base"),
                (String) data.get("currency_profit"),
                (Integer) data.get("digits"),
                (Double) data.get("volume_min"),
                (Double) data.get("volume_max"),
                (Double) data.get("bid"),
                (Double) data.get("ask"),
                (Double) data.get("spread_pips"),
                null
        );
    }

    public static SymbolInfoResponse success(
            String name,
            String description,
            String currencyBase,
            String currencyProfit,
            Integer digits,
            Double volumeMin,
            Double volumeMax,
            Double bid,
            Double ask,
            Double spreadPips) {
        return new SymbolInfoResponse(
                true,
                name,
                description,
                currencyBase,
                currencyProfit,
                digits,
                volumeMin,
                volumeMax,
                bid,
                ask,
                spreadPips,
                null
        );
    }

    // ============================================================
    // OVERLOAD: Accept Map<String, Object> directly
    // ============================================================

    public static SymbolInfoResponse success(Map<String, Object> symbolData) {
        return fromPythonResponse(symbolData);
    }

    public static SymbolInfoResponse error(String error) {
        return new SymbolInfoResponse(false, null, null, null, null, null, null, null, null, null, null, error);
    }
}