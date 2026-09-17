package com.trading.easytradify.execution.models;

import java.util.Map;

public record Mt5ConnectionResponse(
        boolean success,
        String message,
        Map<String, Object> account,
        String error
) {
    public static Mt5ConnectionResponse success(String message, Map<String, Object> account) {
        return new Mt5ConnectionResponse(true, message, account, null);
    }

    public static Mt5ConnectionResponse error(String error) {
        return new Mt5ConnectionResponse(false, null, null, error);
    }
}