package com.trading.easytradify.auth.dto.email;


import lombok.Data;

@Data
public class SendToAllNewsletterDto {

    private String subject;
    private String content;
    private String label;

}