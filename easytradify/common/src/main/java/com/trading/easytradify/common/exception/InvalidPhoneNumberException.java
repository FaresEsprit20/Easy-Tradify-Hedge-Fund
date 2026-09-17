package com.trading.easytradify.common.exception;

public class InvalidPhoneNumberException extends SmsServiceException {

    public InvalidPhoneNumberException(String phoneNumber) {
        super("The phone number " + phoneNumber + " is invalid.");
    }

}
