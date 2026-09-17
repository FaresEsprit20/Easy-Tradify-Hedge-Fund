package com.trading.easytradify.common.dto.auth;

import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * A username/password sign-in attempt.
 *
 * <p>
 * {@code login} accepts either an email address or a username — the repository
 * resolves both — so that a user who registered with one is not locked out by
 * being asked for the other.
 * </p>
 */
@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class AuthenticationRequest {

    /** Email address or username. */
    @NotBlank(message = "Login is required")
    private String login;

    @NotBlank(message = "Password is required")
    private String password;
}
