package com.trading.easytradify.auth.dto.two_factor;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/** Shown once, at enrollment time — the client renders the QR code from otpAuthUri itself. */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TotpSetupResponseDto {
    private String secret;
    private String otpAuthUri;
}
