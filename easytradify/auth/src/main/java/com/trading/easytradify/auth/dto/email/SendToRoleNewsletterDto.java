package com.trading.easytradify.auth.dto.email;

import com.trading.easytradify.auth.entities.enums.UserRole;
import lombok.Data;

@Data
public class SendToRoleNewsletterDto {

    private UserRole role;
    private String subject;
    private String content;
    private String label;

}