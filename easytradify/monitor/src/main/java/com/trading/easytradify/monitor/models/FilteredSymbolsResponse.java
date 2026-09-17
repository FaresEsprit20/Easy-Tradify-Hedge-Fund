package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.List;

/**
 * Response containing filtered symbols.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record FilteredSymbolsResponse(
        boolean success,
        Integer count,
        List<String> symbols,
        List<String> permanentlyExcluded,
        List<String> longTermExcluded,
        String error
) {
    public static FilteredSymbolsResponse success(Integer count, List<String> symbols,
                                                  List<String> permanentlyExcluded,
                                                  List<String> longTermExcluded) {
        return new FilteredSymbolsResponse(true, count, symbols, permanentlyExcluded,
                longTermExcluded, null);
    }

    public static FilteredSymbolsResponse error(String error) {
        return new FilteredSymbolsResponse(false, null, null, null, null, error);
    }
}