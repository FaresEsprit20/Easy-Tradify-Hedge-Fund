package com.trading.easytradify.auth.config.security.filters;

import lombok.Getter;

import java.util.concurrent.atomic.AtomicInteger;

public class IpRateTracker {

    private final int maxPerSecond;
    private final int maxPerMinute;
    private final AtomicInteger secondCount = new AtomicInteger(0);
    private final AtomicInteger minuteCount = new AtomicInteger(0);
    @Getter
    private volatile long lastAccessTime = System.currentTimeMillis();
    private volatile long secondWindow = System.currentTimeMillis() / 1000;
    private volatile long minuteWindow = System.currentTimeMillis() / 60_000;

    public IpRateTracker(int maxPerSecond, int maxPerMinute) {
        this.maxPerSecond = maxPerSecond;
        this.maxPerMinute = maxPerMinute;
    }

    public synchronized boolean allowRequest() {
        lastAccessTime = System.currentTimeMillis();
        long currentSecond = System.currentTimeMillis() / 1000;
        long currentMinute = System.currentTimeMillis() / 60_000;

        if (currentSecond != secondWindow) {
            secondCount.set(0);
            secondWindow = currentSecond;
        }
        if (currentMinute != minuteWindow) {
            minuteCount.set(0);
            minuteWindow = currentMinute;
        }

        return secondCount.incrementAndGet() <= maxPerSecond
                && minuteCount.incrementAndGet() <= maxPerMinute;
    }

    public int getRemainingSecond() {
        return maxPerSecond - secondCount.get();
    }

    public int getRemainingMinute() {
        return maxPerMinute - minuteCount.get();
    }


}