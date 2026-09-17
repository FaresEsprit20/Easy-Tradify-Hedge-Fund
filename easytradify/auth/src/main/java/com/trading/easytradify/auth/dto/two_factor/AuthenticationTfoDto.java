package com.trading.easytradify.auth.dto.two_factor;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AuthenticationTfoDto {

    private String accessToken;
    private String refreshToken;
    private String twoFactorDeliveryMethod;
    private String twoFactorVerificationToken;
    private String twoFactorCode;
    private Long otpValidForSeconds; // Time until OTP expires
    private Long resendAllowedInSeconds; // Time until next resend allowed


}

