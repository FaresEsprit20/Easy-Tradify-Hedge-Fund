package com.trading.easytradify.ai.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

/**
 * <h1>Adversarial Intensity Request</h1>
 * <p>
 * Request to set the adversarial attack intensity level.
 * </p>
 *
 * <h4>Intensity Levels</h4>
 * <ul>
 *   <li><b>0.0 - 0.3:</b> Low intensity - minimal perturbations</li>
 *   <li><b>0.3 - 0.7:</b> Medium intensity - moderate perturbations</li>
 *   <li><b>0.7 - 1.0:</b> High intensity - aggressive perturbations</li>
 * </ul>
 *
 * @param intensity The intensity value (0.0 - 1.0)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialIntensityRequest(
        @NotNull(message = "Intensity is required")
        @Min(value = 0, message = "Intensity must be between 0.0 and 1.0")
        @Max(value = 1, message = "Intensity must be between 0.0 and 1.0")
        Double intensity
) {
    // No validation in constructor - handled by jakarta validation
}