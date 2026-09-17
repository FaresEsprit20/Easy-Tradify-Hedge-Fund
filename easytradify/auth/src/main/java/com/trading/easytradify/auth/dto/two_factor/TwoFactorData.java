package com.trading.easytradify.auth.dto.two_factor;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TwoFactorData {

    private String verificationToken;  // Long-lived token (UUID)
    private String otpCode;           // 6-digit code
    private Long otpValidForSeconds;
    private Long resendAllowedInSeconds;

}