package com.trading.easytradify.auth.dto.two_factor;

import com.trading.easytradify.common.entities.enums.TwoFactorMethod;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/** Which method the user wants their second factor delivered by. */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TwoFactorMethodRequestDto {
    private TwoFactorMethod method;
}
