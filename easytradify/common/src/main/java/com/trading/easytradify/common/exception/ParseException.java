package com.trading.easytradify.common.exception;

import lombok.Getter;

import java.util.List;

@Getter
public class ParseException extends InvalidEntityException {

    private final String dataType;
    private final String contentPreview;

    public ParseException(String dataType, String message) {
        super(message, (List<String>) null);
        this.dataType = dataType;
        this.contentPreview = null;
    }

    public ParseException(ErrorCodes errorCode, String dataType, String message, List<String> errors) {
        super(message, errorCode, errors);
        this.dataType = dataType;
        this.contentPreview = null;
    }

    public ParseException(String dataType, String message, String contentPreview) {
        super(message, (List<String>) null);
        this.dataType = dataType;
        this.contentPreview = contentPreview != null && contentPreview.length() > 100 ?
                contentPreview.substring(0, 100) + "..." : contentPreview;
    }
}