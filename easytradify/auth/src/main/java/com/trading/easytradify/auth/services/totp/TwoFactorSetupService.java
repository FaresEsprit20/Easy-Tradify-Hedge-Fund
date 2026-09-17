package com.trading.easytradify.auth.services.totp;

import com.trading.easytradify.auth.dto.two_factor.TotpSetupResponseDto;
import com.trading.easytradify.auth.dto.two_factor.TotpStatusResponseDto;
import com.trading.easytradify.auth.dto.two_factor.TwoFactorMethodChangeResponseDto;
import com.trading.easytradify.common.entities.enums.TwoFactorMethod;
import org.springframework.security.core.Authentication;

public interface TwoFactorSetupService {

    TotpSetupResponseDto beginSetup(Authentication authentication);

    void confirmSetup(Authentication authentication, String code);

    void disable(Authentication authentication, String code);

    /**
     * Begins moving the second factor to another method.
     *
     * <p>Changes nothing yet: it records the intent and sends or generates a
     * code through the new channel. The switch completes only in
     * {@link #confirmMethodChange}.
     */
    TwoFactorMethodChangeResponseDto startMethodChange(Authentication authentication, TwoFactorMethod method);

    /** Completes a pending switch, given a code delivered by the new method. */
    void confirmMethodChange(Authentication authentication, String code);

    TotpStatusResponseDto getStatus(Authentication authentication);
}
