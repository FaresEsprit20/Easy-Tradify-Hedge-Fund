package com.trading.easytradify.ai.models.adverserial;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>Adversarial Enable Response</h1>
 * <p>
 * Response indicating the result of enabling/disabling adversarial training.
 * </p>
 *
 * @param success Whether the enable/disable operation was successful
 * @param message Success message (success case)
 * @param enabled Whether adversarial training is enabled
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialEnableResponse(
        boolean success,
        String message,
        Boolean enabled,
        String error
) {
    public static AdversarialEnableResponse success(String message, Boolean enabled) {
        return new AdversarialEnableResponse(true, message, enabled, null);
    }

    public static AdversarialEnableResponse error(String error) {
        return new AdversarialEnableResponse(false, null, null, error);
    }
}