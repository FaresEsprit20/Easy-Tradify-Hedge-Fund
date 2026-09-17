package com.trading.easytradify.auth.dto.sms;

import com.trading.easytradify.auth.entities.enums.UserRole;
import lombok.Data;

@Data
public class SendToRoleSmsDto {

    private UserRole role;
    private String message;

}
