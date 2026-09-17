package com.trading.easytradify.auth.dto.password_reset;

import lombok.Data;
import lombok.RequiredArgsConstructor;

@Data
@RequiredArgsConstructor
public class ResetPasswordRequestDto {

    private String token;
    private String newPassword;

}