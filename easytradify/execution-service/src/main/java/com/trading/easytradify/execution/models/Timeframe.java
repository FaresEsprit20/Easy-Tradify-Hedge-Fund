package com.trading.easytradify.execution.models;

import lombok.Getter;

@Getter
public enum Timeframe {
    M1("M1", 1),
    M5("M5", 5),
    M15("M15", 15),
    M30("M30", 30),
    H1("H1", 60),
    H4("H4", 240),
    D1("D1", 1440);

    private final String value;
    private final int minutes;

    Timeframe(String value, int minutes) {
        this.value = value;
        this.minutes = minutes;
    }

    public static Timeframe fromString(String value) {
        if (value == null) {
            return M1;
        }
        try {
            return valueOf(value.toUpperCase());
        } catch (IllegalArgumentException e) {
            return M1;
        }
    }

}