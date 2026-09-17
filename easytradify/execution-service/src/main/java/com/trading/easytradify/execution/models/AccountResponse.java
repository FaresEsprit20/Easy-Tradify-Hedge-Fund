package com.trading.easytradify.execution.models;

import java.util.Map;

public record AccountResponse(
        boolean success,
        Map<String, Object> data,
        String error
) {
    public static AccountResponse success(Map<String, Object> data) {
        return new AccountResponse(true, data, null);
    }

    public static AccountResponse error(String error) {
        return new AccountResponse(false, null, error);
    }
}