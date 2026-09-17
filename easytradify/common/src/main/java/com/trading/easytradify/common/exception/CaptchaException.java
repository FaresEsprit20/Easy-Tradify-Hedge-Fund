package com.trading.easytradify.common.exception;

import lombok.Getter;

import java.util.List;

@Getter
public class CaptchaException extends InvalidOperationException {

    private final String providerName;
    private final String captchaType;

    public CaptchaException(String providerName, String captchaType, String message) {
        super(message, ErrorCodes.CAPTCHA_DETECTED, null);
        this.providerName = providerName;
        this.captchaType = captchaType;
    }

    public CaptchaException(ErrorCodes errorCode, String providerName, String captchaType, String message, List<String> errors) {
        super(message, errorCode, errors);
        this.providerName = providerName;
        this.captchaType = captchaType;
    }

    public CaptchaException(String providerName, String captchaType, String message, Throwable cause, List<String> errors) {
        super(message, cause, ErrorCodes.CAPTCHA_DETECTED, errors);
        this.providerName = providerName;
        this.captchaType = captchaType;
    }
}