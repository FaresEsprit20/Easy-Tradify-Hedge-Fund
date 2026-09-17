package com.trading.easytradify.common.exception;


import java.util.List;

public class EntityNotFoundException extends RuntimeException {


    private ErrorCodes errorCode;
    private final List<String> errors;


    public EntityNotFoundException(String message, List<String> errors) {
        super(message);
        this.errors = errors;
    }

    public EntityNotFoundException(String message, Throwable cause, List<String> errors) {
        super(message, cause);
        this.errors = errors;
    }

    public EntityNotFoundException(String message, Throwable cause, ErrorCodes errorCode, List<String> errors) {
        super(message, cause);
        this.errorCode = errorCode;
        this.errors = errors;
    }

    public EntityNotFoundException(String message, ErrorCodes errorCode, List<String> errors) {
        super(message);
        this.errorCode = errorCode;
        this.errors = errors;
    }

    public ErrorCodes getErrorCode() {
        return errorCode;
    }

    public List<String> getErrors() {
        return errors;
    }

}
