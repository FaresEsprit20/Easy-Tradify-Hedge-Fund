package com.trading.easytradify.auth.dto.two_factor;

import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TwoFactorVerificationRequest {

    @NotBlank(message = "Verification token cannot be blank")
    private String verificationToken;

    @NotBlank(message = "Verification code cannot be blank")
    private String code;

}
