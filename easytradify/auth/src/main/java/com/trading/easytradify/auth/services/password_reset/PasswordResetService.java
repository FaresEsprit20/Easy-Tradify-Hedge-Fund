package com.trading.easytradify.auth.services.password_reset;


import com.trading.easytradify.auth.dto.password_reset.TokenVerificationResponse;
import com.trading.easytradify.common.dto.auth.ChangePasswordUserRequestDto;

public interface PasswordResetService {

    void sendResetLink(String email, String recaptchaToken, String userIp, String action);
    boolean resetPassword(String token, ChangePasswordUserRequestDto newPassword);
    boolean resendResetLink(String email, String recaptchaToken, String userIp, String action);

    TokenVerificationResponse verifyToken(String token);
}
