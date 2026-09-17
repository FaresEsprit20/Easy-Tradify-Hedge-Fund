package com.trading.easytradify.monitor.models;

import java.time.Instant;
import java.util.Map;

/**
 * Domain model for monitor status.
 */
public record MonitorStatus(
        boolean running,
        Instant lastScanTime,
        int totalSymbols,
        int activePositions,
        Map<String, Object> stats
) {
    public static MonitorStatusBuilder builder() {
        return new MonitorStatusBuilder();
    }

    public static class MonitorStatusBuilder {
        private boolean running = false;
        private Instant lastScanTime;
        private int totalSymbols = 0;
        private int activePositions = 0;
        private Map<String, Object> stats = Map.of();

        public MonitorStatusBuilder running(boolean running) {
            this.running = running;
            return this;
        }

        public MonitorStatusBuilder lastScanTime(Instant lastScanTime) {
            this.lastScanTime = lastScanTime;
            return this;
        }

        public MonitorStatusBuilder totalSymbols(int totalSymbols) {
            this.totalSymbols = totalSymbols;
            return this;
        }

        public MonitorStatusBuilder activePositions(int activePositions) {
            this.activePositions = activePositions;
            return this;
        }

        public MonitorStatusBuilder stats(Map<String, Object> stats) {
            this.stats = stats;
            return this;
        }

        public MonitorStatus build() {
            return new MonitorStatus(running, lastScanTime, totalSymbols,
                    activePositions, stats);
        }
    }
}