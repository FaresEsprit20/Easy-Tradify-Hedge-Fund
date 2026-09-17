package com.trading.easytradify.execution.models;

import java.time.Instant;

public record TradeHistoryRequest(
        String symbol,
        Integer magic,
        Integer lastNDays,
        Instant fromDate,
        Instant toDate
) {}