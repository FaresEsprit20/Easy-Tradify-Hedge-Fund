package com.trading.easytradify.auth.dto.sms;

import lombok.Data;

@Data
public class SendToUserSmsDto {

    private String phoneNumber;
    private String message;

}