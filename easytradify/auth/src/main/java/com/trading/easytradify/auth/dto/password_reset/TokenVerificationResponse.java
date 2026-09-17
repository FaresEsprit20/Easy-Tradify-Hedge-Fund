package com.trading.easytradify.auth.dto.password_reset;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;

@Builder
@Data
@AllArgsConstructor
public class TokenVerificationResponse {

    private String message;
    private boolean valid;
    private Integer userId;
    private long remainingTimeSeconds;

}