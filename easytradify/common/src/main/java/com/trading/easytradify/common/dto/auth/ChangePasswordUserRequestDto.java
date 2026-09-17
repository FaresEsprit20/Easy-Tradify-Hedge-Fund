package com.trading.easytradify.common.dto.auth;

import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * A password change, whether initiated by a reset link or by an admin.
 *
 * <p>
 * Note this is the RESET path: it does not carry the old password, because the
 * caller has already proved control of the account with the reset token. The
 * self-service "change my password while signed in" path is a different DTO
 * ({@code ChangePasswordUserDto}) and does verify the current password.
 * </p>
 */
@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class ChangePasswordUserRequestDto {

    private Integer id;

    /**
     * The reset token that authorises this change.
     *
     * <p>
     * {@code @JsonIgnore} on the getter side would be wrong — it must be
     * readable from the request body — but it must never be echoed back in a
     * response, which is why every response type here is a different class
     * rather than this one reused.
     * </p>
     */
    private String token;

    private String password;

    private String confirmPassword;

    /** True only when both supplied passwords match and are non-blank. */
    @JsonIgnore
    public boolean isConsistent() {
        return password != null && !password.isBlank() && password.equals(confirmPassword);
    }
}
