package com.trading.easytradify.auth.dto.two_factor;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/** Used for both confirming enrollment and disabling — a fresh code either way. */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class TotpCodeRequestDto {
    private String code;
}
