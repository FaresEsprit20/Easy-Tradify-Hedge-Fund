package com.trading.easytradify.auth.dto.two_factor;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TwoFactorVerificationResponse {

    private boolean success;
    private String message;

}