package com.trading.easytradify.common.exception;

import lombok.Getter;
import java.util.List;

@Getter
public class TradingException extends RuntimeException {

    private final ErrorCodes errorCode;
    private final List<String> errors;
    private final Integer mt5RetCode;
    private final String symbol;
    private final Integer ticket;

    public TradingException(ErrorCodes errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
        this.errors = null;
        this.mt5RetCode = null;
        this.symbol = null;
        this.ticket = null;
    }

    public TradingException(ErrorCodes errorCode, String message, List<String> errors) {
        super(message);
        this.errorCode = errorCode;
        this.errors = errors;
        this.mt5RetCode = null;
        this.symbol = null;
        this.ticket = null;
    }

    public TradingException(ErrorCodes errorCode, String message, Throwable cause) {
        super(message, cause);
        this.errorCode = errorCode;
        this.errors = null;
        this.mt5RetCode = null;
        this.symbol = null;
        this.ticket = null;
    }

    // Full constructor with all details
    public TradingException(ErrorCodes errorCode, String message, List<String> errors,
                            Integer mt5RetCode, String symbol, Integer ticket) {
        super(message);
        this.errorCode = errorCode;
        this.errors = errors;
        this.mt5RetCode = mt5RetCode;
        this.symbol = symbol;
        this.ticket = ticket;
    }

    // Builder pattern for convenience
    public static class Builder {
        private ErrorCodes errorCode;
        private String message;
        private List<String> errors;
        private Integer mt5RetCode;
        private String symbol;
        private Integer ticket;

        public Builder errorCode(ErrorCodes errorCode) {
            this.errorCode = errorCode;
            return this;
        }

        public Builder message(String message) {
            this.message = message;
            return this;
        }

        public Builder errors(List<String> errors) {
            this.errors = errors;
            return this;
        }

        public Builder mt5RetCode(Integer mt5RetCode) {
            this.mt5RetCode = mt5RetCode;
            return this;
        }

        public Builder symbol(String symbol) {
            this.symbol = symbol;
            return this;
        }

        public Builder ticket(Integer ticket) {
            this.ticket = ticket;
            return this;
        }

        public TradingException build() {
            return new TradingException(errorCode, message, errors, mt5RetCode, symbol, ticket);
        }
    }

    public static Builder builder() {
        return new Builder();
    }

}