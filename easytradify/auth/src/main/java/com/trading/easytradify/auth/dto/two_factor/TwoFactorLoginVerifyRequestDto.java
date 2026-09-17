package com.trading.easytradify.auth.dto.two_factor;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/** Second step of login when the account has TOTP enabled. */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class TwoFactorLoginVerifyRequestDto {
    private String mfaToken;
    private String code;
}
