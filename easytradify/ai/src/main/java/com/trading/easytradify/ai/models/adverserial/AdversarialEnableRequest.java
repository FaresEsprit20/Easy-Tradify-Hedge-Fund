package com.trading.easytradify.ai.models.adverserial;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.NotNull;

/**
 * <h1>Adversarial Enable Request</h1>
 * <p>
 * Request to enable or disable adversarial training.
 * </p>
 *
 * @param enabled Whether adversarial training should be enabled
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialEnableRequest(
        @NotNull(message = "Enabled flag is required")
        Boolean enabled
) {
    // No validation in constructor - handled by jakarta validation
}