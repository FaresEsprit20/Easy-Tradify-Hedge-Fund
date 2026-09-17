// execution-service/src/main/java/.../execution/domain/model/OrderSide.java
package com.trading.easytradify.execution.models;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;

public enum OrderSide {
    BUY, SELL;

    public static OrderSide fromString(String value) {
        if (value == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.TRADE_INVALID_ORDER_SIDE)
                    .message("Order side cannot be null")
                    .build();
        }
        try {
            return valueOf(value.toUpperCase());
        } catch (IllegalArgumentException e) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.TRADE_INVALID_ORDER_SIDE)
                    .message("Invalid order side: " + value + ". Must be BUY or SELL")
                    .build();
        }
    }
}