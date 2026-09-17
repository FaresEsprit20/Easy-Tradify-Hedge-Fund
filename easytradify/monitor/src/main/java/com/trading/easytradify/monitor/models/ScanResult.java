package com.trading.easytradify.monitor.models;

import java.time.Instant;
import java.util.List;

/**
 * Domain model for scan results.
 */
public record ScanResult(
        Instant scanTime,
        int totalSymbolsScanned,
        int activeSymbols,
        int filteredSymbols,
        List<SymbolRank> topRanks,
        String summary
) {
    public static ScanResultBuilder builder() {
        return new ScanResultBuilder();
    }

    public static class ScanResultBuilder {
        private Instant scanTime = Instant.now();
        private int totalSymbolsScanned = 0;
        private int activeSymbols = 0;
        private int filteredSymbols = 0;
        private List<SymbolRank> topRanks = List.of();
        private String summary = "";

        public ScanResultBuilder scanTime(Instant scanTime) {
            this.scanTime = scanTime;
            return this;
        }

        public ScanResultBuilder totalSymbolsScanned(int totalSymbolsScanned) {
            this.totalSymbolsScanned = totalSymbolsScanned;
            return this;
        }

        public ScanResultBuilder activeSymbols(int activeSymbols) {
            this.activeSymbols = activeSymbols;
            return this;
        }

        public ScanResultBuilder filteredSymbols(int filteredSymbols) {
            this.filteredSymbols = filteredSymbols;
            return this;
        }

        public ScanResultBuilder topRanks(List<SymbolRank> topRanks) {
            this.topRanks = topRanks;
            return this;
        }

        public ScanResultBuilder summary(String summary) {
            this.summary = summary;
            return this;
        }

        public ScanResult build() {
            return new ScanResult(scanTime, totalSymbolsScanned, activeSymbols,
                    filteredSymbols, topRanks, summary);
        }
    }
}