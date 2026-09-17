package com.trading.easytradify.ai.models.adverserial;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;
import java.util.Map;

/**
 * <h1>Adversarial Generate Response</h1>
 * <p>
 * Response containing generated attacked trades.
 * </p>
 *
 * @param success         Whether the request was successful
 * @param attackedTrades  List of attacked trade variations (success case)
 * @param count           Number of attacks generated
 * @param gnnUsed         Whether GNN context was used
 * @param error           Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialGenerateResponse(
        boolean success,
        List<Map<String, Object>> attackedTrades,
        Integer count,
        Boolean gnnUsed,
        String error
) {
    public static AdversarialGenerateResponse success(
            List<Map<String, Object>> attackedTrades,
            Integer count,
            Boolean gnnUsed) {
        return new AdversarialGenerateResponse(true, attackedTrades, count, gnnUsed, null);
    }

    public static AdversarialGenerateResponse error(String error) {
        return new AdversarialGenerateResponse(false, null, null, null, error);
    }
}