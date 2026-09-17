package com.trading.easytradify.auth.dto.two_factor;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TwoFactorSetupResponse {

    private boolean success;
    private String qrCodeUrl; // For authenticator app
    private String secretKey; // For manual entry
    private String message;

}