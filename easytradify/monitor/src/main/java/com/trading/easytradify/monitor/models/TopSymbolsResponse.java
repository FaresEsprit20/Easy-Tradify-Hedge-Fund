package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Response containing top ranked symbols.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
// ignoreUnknown: hybrid_monitor.py also sends `timestamp`, and adds fields as
// the monitor grows. A strict binding turns every such addition into a
// deserialization failure here -- which this client then reports as
// "service unavailable", pointing debugging at the network instead of the
// contract.
@JsonIgnoreProperties(ignoreUnknown = true)
public record TopSymbolsResponse(
        boolean success,
        Integer count,
        // Python's key is `top_symbols`. Without this the list bound to null
        // and the endpoint silently returned an empty ranking.
        @JsonProperty("top_symbols") List<SymbolRankResponse> symbols,
        String error
) {
    public static TopSymbolsResponse success(Integer count, List<SymbolRankResponse> symbols) {
        return new TopSymbolsResponse(true, count, symbols, null);
    }

    public static TopSymbolsResponse error(String error) {
        return new TopSymbolsResponse(false, null, null, error);
    }
}