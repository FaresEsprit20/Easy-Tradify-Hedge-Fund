package com.trading.easytradify.ai.models.adverserial;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>Adversarial Status Response</h1>
 * <p>
 * Response containing the adversarial training status.
 * </p>
 *
 * @param success Whether the request was successful
 * @param status  The adversarial status data (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialStatusResponse(
        boolean success,
        Map<String, Object> status,
        String error
) {
    public static AdversarialStatusResponse success(Map<String, Object> status) {
        return new AdversarialStatusResponse(true, status, null);
    }

    public static AdversarialStatusResponse error(String error) {
        return new AdversarialStatusResponse(false, null, error);
    }
}