package com.trading.easytradify.common.exception;

import java.util.List;

public class RecaptchaException extends RuntimeException {

    private final ErrorCodes errorCode;
    private final List<String> errors;

    public RecaptchaException(String message, ErrorCodes errorCode) {
        super(message);
        this.errorCode = errorCode;
        this.errors = List.of(message);
    }

    public RecaptchaException(String message, ErrorCodes errorCode, List<String> errors) {
        super(message);
        this.errorCode = errorCode;
        this.errors = errors;
    }

    public List<String> getErrors() {
        return errors;
    }

    public ErrorCodes getErrorCode() {
        return errorCode;
    }


}