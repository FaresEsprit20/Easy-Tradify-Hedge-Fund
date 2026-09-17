package com.trading.easytradify.execution.models;

import java.time.Instant;
import java.util.List;

public record MultiBrokerTradeResponse(
        String requestId,
        String symbol,
        String orderType,
        List<String> requestedBrokers,
        List<String> executedBrokers,
        int totalRequested,
        int successfulCount,
        int failedCount,
        List<SingleBrokerResult> results,
        String summary,
        String timestamp
) {
    public static MultiBrokerTradeResponse fromResults(
            List<String> requestedBrokers,
            String symbol,
            String orderType,
            List<SingleBrokerResult> results
    ) {
        var executed = results.stream().map(SingleBrokerResult::broker).toList();
        var successCount = results.stream().filter(SingleBrokerResult::success).count();
        var failCount = results.size() - successCount;

        String summary;
        if (results.isEmpty()) {
            summary = "❌ No brokers executed";
        } else if (successCount == results.size()) {
            summary = String.format("✅ Successfully executed on all %d brokers", results.size());
        } else if (successCount > 0) {
            summary = String.format("⚠️ Executed on %d/%d brokers (Success: %d, Failed: %d)",
                    successCount, results.size(), successCount, failCount);
        } else {
            summary = String.format("❌ All %d brokers failed", results.size());
        }

        return new MultiBrokerTradeResponse(
                java.util.UUID.randomUUID().toString(),
                symbol != null ? symbol : "N/A",
                orderType != null ? orderType : "N/A",
                requestedBrokers,
                executed,
                requestedBrokers.size(),
                (int) successCount,
                (int) failCount,
                results,
                summary,
                Instant.now().toString()
        );
    }
}