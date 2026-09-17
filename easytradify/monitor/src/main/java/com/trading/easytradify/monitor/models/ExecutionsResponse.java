package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.List;
import java.util.Map;

/**
 * Response containing executed trades.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ExecutionsResponse(
        boolean success,
        Integer count,
        List<Map<String, Object>> executions,
        String error
) {
    public static ExecutionsResponse success(Integer count, List<Map<String, Object>> executions) {
        return new ExecutionsResponse(true, count, executions, null);
    }

    public static ExecutionsResponse error(String error) {
        return new ExecutionsResponse(false, null, null, error);
    }

}