package com.trading.easytradify.auth.dto.email;

import lombok.Data;

@Data
public class SendToUserNewsletterDto {

    private String email;
    private String subject;
    private String content;
    private String label;

}
