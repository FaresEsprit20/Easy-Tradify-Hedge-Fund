package com.trading.easytradify.common.dto.auth;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * The answer to "is this caller signed in?".
 *
 * <p>
 * Deliberately thin. It reports whether the session is live and who it belongs
 * to, and nothing else — roles and profile data are fetched from their own
 * endpoints. A check-auth response that carries authorisation data invites the
 * client to make access decisions from a cached copy of it.
 * </p>
 */
@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AuthCheckResponse {

    /**
     * Explicitly named "isAuthenticated" on the wire.
     *
     * <p>
     * Without {@code @JsonProperty}, Jackson's bean naming turns the getter
     * {@code getIsAuthenticated()} into the field {@code authenticated}, and the
     * client checking {@code isAuthenticated} reads undefined — which is falsy,
     * so a signed-in user is silently treated as signed out.
     * </p>
     */
    @JsonProperty("isAuthenticated")
    private boolean isAuthenticated;

    private String email;

    private Integer userId;
}
