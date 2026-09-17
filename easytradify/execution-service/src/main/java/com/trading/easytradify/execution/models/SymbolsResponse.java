// execution-service/src/main/java/.../execution/models/SymbolsResponse.java
package com.trading.easytradify.execution.models;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record SymbolsResponse(
        boolean success,
        Integer count,
        List<SymbolInfoResponse> symbols,
        String error
) {
    public static SymbolsResponse fromPythonResponse(Map<String, Object> response) {
        if (response == null) {
            return error("Empty response from Python");
        }

        boolean success = (boolean) response.getOrDefault("success", false);
        if (success) {
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rawSymbols = (List<Map<String, Object>>) response.get("symbols");
            List<SymbolInfoResponse> symbolInfos = new ArrayList<>();

            if (rawSymbols != null) {
                for (Map<String, Object> raw : rawSymbols) {
                    symbolInfos.add(SymbolInfoResponse.fromPythonResponse(raw));
                }
            }

            Integer count = (Integer) response.get("count");
            if (count == null) {
                count = symbolInfos.size();
            }

            return new SymbolsResponse(true, count, symbolInfos, null);
        }

        return error((String) response.getOrDefault("error", "Unknown error"));
    }

    public static SymbolsResponse success(Integer count, List<SymbolInfoResponse> symbols) {
        return new SymbolsResponse(true, count, symbols, null);
    }

    public static SymbolsResponse error(String error) {
        return new SymbolsResponse(false, null, null, error);
    }
}