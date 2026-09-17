package com.trading.easytradify.monitor.models;

import java.time.Instant;

/**
 * Domain model for symbol ranking.
 */
public record SymbolRank(
        String symbol,
        double confidence,
        boolean isActive,
        boolean inPosition,
        Integer ticket,
        String exchange,
        String reason,
        Double entryPrice,
        Instant lastCheckTime,
        StabilityStatus stabilityStatus
) {
    public enum StabilityStatus {
        UNKNOWN,
        STABLE,
        VOLATILE,
        EXCLUDED
    }

    public static SymbolRankBuilder builder() {
        return new SymbolRankBuilder();
    }

    public static class SymbolRankBuilder {
        private String symbol;
        private double confidence;
        private boolean isActive = true;
        private boolean inPosition = false;
        private Integer ticket;
        private String exchange;
        private String reason;
        private Double entryPrice;
        private Instant lastCheckTime;
        private StabilityStatus stabilityStatus = StabilityStatus.UNKNOWN;

        public SymbolRankBuilder symbol(String symbol) {
            this.symbol = symbol;
            return this;
        }

        public SymbolRankBuilder confidence(double confidence) {
            this.confidence = confidence;
            return this;
        }

        public SymbolRankBuilder isActive(boolean isActive) {
            this.isActive = isActive;
            return this;
        }

        public SymbolRankBuilder inPosition(boolean inPosition) {
            this.inPosition = inPosition;
            return this;
        }

        public SymbolRankBuilder ticket(Integer ticket) {
            this.ticket = ticket;
            return this;
        }

        public SymbolRankBuilder exchange(String exchange) {
            this.exchange = exchange;
            return this;
        }

        public SymbolRankBuilder reason(String reason) {
            this.reason = reason;
            return this;
        }

        public SymbolRankBuilder entryPrice(Double entryPrice) {
            this.entryPrice = entryPrice;
            return this;
        }

        public SymbolRankBuilder lastCheckTime(Instant lastCheckTime) {
            this.lastCheckTime = lastCheckTime;
            return this;
        }

        public SymbolRankBuilder stabilityStatus(StabilityStatus stabilityStatus) {
            this.stabilityStatus = stabilityStatus;
            return this;
        }

        public SymbolRank build() {
            return new SymbolRank(symbol, confidence, isActive, inPosition, ticket,
                    exchange, reason, entryPrice, lastCheckTime, stabilityStatus);
        }
    }
}