package com.trading.easytradify.common.exception;




import lombok.Builder;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

@Builder
public class CustomErrorMsg {

    private Integer httpCode;

    private ErrorCodes code;

    private String message;

    private List<String> errors = new ArrayList<>();

    public CustomErrorMsg() {}

    public CustomErrorMsg(Integer httpCode, ErrorCodes code, String message) {
        this.httpCode = httpCode;
        this.code = code;
        this.message = message;
    }

    public CustomErrorMsg(Integer httpCode, ErrorCodes code, List<String> errors) {
        this.httpCode = httpCode;
        this.code = code;
        this.errors = errors;
    }

    public CustomErrorMsg(Integer httpCode, ErrorCodes code, String message, List<String> errors) {
        this.httpCode = httpCode;
        this.code = code;
        this.message = message;
        this.errors = errors;
    }


    public Integer getHttpCode() {
        return httpCode;
    }

    public void setHttpCode(Integer httpCode) {
        this.httpCode = httpCode;
    }

    public ErrorCodes getCode() {
        return code;
    }

    public void setCode(ErrorCodes code) {
        this.code = code;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }

    public List<String> getErrors() {
        return errors;
    }

    public void setErrors(List<String> errors) {
        this.errors = errors;
    }

    @Override
    public boolean equals(Object o) {
        if (o == null || getClass() != o.getClass()) return false;
        CustomErrorMsg that = (CustomErrorMsg) o;
        return Objects.equals(httpCode, that.httpCode) && code == that.code && Objects.equals(message, that.message) && Objects.equals(errors, that.errors);
    }

    @Override
    public int hashCode() {
        return Objects.hash(httpCode, code, message, errors);
    }

    @Override
    public String toString() {
        return "CustomErrorMsg{" +
                "httpCode=" + httpCode +
                ", code=" + code +
                ", message='" + message + '\'' +
                ", errors=" + errors +
                '}';
    }


}
