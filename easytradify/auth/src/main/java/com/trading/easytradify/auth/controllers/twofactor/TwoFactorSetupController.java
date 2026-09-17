package com.trading.easytradify.auth.controllers.twofactor;

import com.trading.easytradify.auth.dto.two_factor.TotpCodeRequestDto;
import com.trading.easytradify.auth.dto.two_factor.TotpSetupResponseDto;
import com.trading.easytradify.auth.dto.two_factor.TotpStatusResponseDto;
import com.trading.easytradify.auth.services.totp.TwoFactorSetupService;
import com.trading.easytradify.auth.dto.two_factor.TwoFactorMethodChangeResponseDto;
import com.trading.easytradify.auth.dto.two_factor.TwoFactorMethodRequestDto;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class TwoFactorSetupController implements TwoFactorSetupApi {

    private final TwoFactorSetupService twoFactorSetupService;

    @Override
    public TotpStatusResponseDto getStatus(Authentication authentication) {
        return twoFactorSetupService.getStatus(authentication);
    }

    @Override
    public TotpSetupResponseDto beginSetup(Authentication authentication) {
        return twoFactorSetupService.beginSetup(authentication);
    }

    @Override
    public ResponseEntity<Void> confirmSetup(TotpCodeRequestDto request, Authentication authentication) {
        twoFactorSetupService.confirmSetup(authentication, request.getCode());
        return ResponseEntity.ok().build();
    }

    @Override
    public ResponseEntity<Void> disable(TotpCodeRequestDto request, Authentication authentication) {
        twoFactorSetupService.disable(authentication, request.getCode());
        return ResponseEntity.ok().build();
    }

    @Override
    public TwoFactorMethodChangeResponseDto startMethodChange(TwoFactorMethodRequestDto request,
                                                              Authentication authentication) {
        return twoFactorSetupService.startMethodChange(authentication, request.getMethod());
    }

    @Override
    public ResponseEntity<Void> confirmMethodChange(TotpCodeRequestDto request, Authentication authentication) {
        twoFactorSetupService.confirmMethodChange(authentication, request.getCode());
        return ResponseEntity.noContent().build();
    }
}
