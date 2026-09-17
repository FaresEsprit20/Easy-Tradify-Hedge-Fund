package com.trading.easytradify.execution.models;

import java.util.Map;

public record CopyTradeRequest(
        String symbol,
        Map<String, Object> analysisResult
) {}