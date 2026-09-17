package com.trading.easytradify.ai.models.adverserial;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>Adversarial Train Response</h1>
 * <p>
 * Response containing adversarial training results.
 * </p>
 *
 * @param success Whether the request was successful
 * @param result  The training result (success case)
 * @param gnnUsed Whether GNN context was used
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialTrainResponse(
        boolean success,
        Map<String, Object> result,
        Boolean gnnUsed,
        String error
) {
    public static AdversarialTrainResponse success(Map<String, Object> result, Boolean gnnUsed) {
        return new AdversarialTrainResponse(true, result, gnnUsed, null);
    }

    public static AdversarialTrainResponse error(String error) {
        return new AdversarialTrainResponse(false, null, null, error);
    }
}