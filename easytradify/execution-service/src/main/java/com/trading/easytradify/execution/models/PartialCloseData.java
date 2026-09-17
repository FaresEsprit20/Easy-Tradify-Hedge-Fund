// execution-service/src/main/java/.../execution/models/PartialCloseData.java
package com.trading.easytradify.execution.models;

public record PartialCloseData(
        Integer ticket,
        Double remainingVolume,
        Double closedVolume,
        Double profit
) {}