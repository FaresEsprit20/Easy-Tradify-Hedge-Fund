package com.trading.easytradify.ai.models.adverserial;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;
import java.util.Map;

/**
 * <h1>Adversarial Train Request</h1>
 * <p>
 * Request to apply adversarial attacks to training data.
 * </p>
 *
 * @param trades         List of trades to attack
 * @param outcomes       List of outcomes corresponding to trades
 * @param symbol         The trading symbol (optional)
 * @param componentName  The component name (optional)
 * @param saveModels     Whether to save trained models
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialTrainRequest(
        List<Map<String, Object>> trades,
        List<Integer> outcomes,
        String symbol,
        String componentName,
        Boolean saveModels
) {
    // No validation in constructor - handled by service
}