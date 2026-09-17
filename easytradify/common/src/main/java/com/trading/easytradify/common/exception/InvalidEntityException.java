package com.trading.easytradify.common.exception;

import java.util.List;

public class InvalidEntityException extends RuntimeException {

    private ErrorCodes errorCode;
    private final List<String> errors;


    public InvalidEntityException(String message, List<String> errors) {
        super(message);
        this.errors = errors;
    }
    public InvalidEntityException(String message, ErrorCodes errorCode, List<String> errors) {
        super(message);
        this.errorCode = errorCode;
        this.errors = errors;
    }

    public InvalidEntityException(String message, Throwable cause, List<String> errors) {
        super(message, cause);
        this.errors = errors;
    }

    public InvalidEntityException(String message, Throwable cause, ErrorCodes errorCode, List<String> errors) {
        super(message, cause);
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

