package com.trading.easytradify.auth.dto.two_factor;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TotpStatusResponseDto {
    private boolean enabled;

    /** Which delivery method is in force: TOTP or EMAIL. */
    private String method;

    /**
     * A method awaiting confirmation, if a switch is part-way through.
     *
     * <p>Surfaced so the UI can resume the flow instead of stranding the user
     * between two methods with no visible way back.
     */
    private String pendingMethod;
}
