package com.trading.easytradify.ai.models.adverserial;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>Adversarial Intensity Response</h1>
 * <p>
 * Response indicating the result of setting attack intensity.
 * </p>
 *
 * <h4>Intensity Levels</h4>
 * <ul>
 *   <li><b>0.0 - 0.3:</b> Low intensity - minimal perturbations</li>
 *   <li><b>0.3 - 0.7:</b> Medium intensity - moderate perturbations</li>
 *   <li><b>0.7 - 1.0:</b> High intensity - aggressive perturbations</li>
 * </ul>
 *
 * @param success   Whether the intensity update was successful
 * @param message   Success message (success case)
 * @param intensity The intensity value (0.0 - 1.0)
 * @param error     Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialIntensityResponse(
        boolean success,
        String message,
        Double intensity,
        String error
) {
    public static AdversarialIntensityResponse success(String message, Double intensity) {
        return new AdversarialIntensityResponse(true, message, intensity, null);
    }

    public static AdversarialIntensityResponse error(String error) {
        return new AdversarialIntensityResponse(false, null, null, error);
    }
}