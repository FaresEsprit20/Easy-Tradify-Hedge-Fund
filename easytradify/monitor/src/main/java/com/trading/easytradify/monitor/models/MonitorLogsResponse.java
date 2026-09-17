package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.List;
import java.util.Map;

/**
 * Response containing monitor logs.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record MonitorLogsResponse(
        boolean success,
        Integer count,
        List<Map<String, Object>> executions,
        List<Map<String, Object>> positions,
        Map<String, Object> summary,
        String error
) {
    public static MonitorLogsResponse success(Integer count, List<Map<String, Object>> executions,
                                              List<Map<String, Object>> positions,
                                              Map<String, Object> summary) {
        return new MonitorLogsResponse(true, count, executions, positions, summary, null);
    }

    public static MonitorLogsResponse error(String error) {
        return new MonitorLogsResponse(false, null, null, null, null, error);
    }

}