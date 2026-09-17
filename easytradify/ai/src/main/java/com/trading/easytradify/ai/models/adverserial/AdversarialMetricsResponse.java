package com.trading.easytradify.ai.models.adverserial;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>Adversarial Metrics Response</h1>
 * <p>
 * Response containing adversarial attack metrics and statistics.
 * </p>
 *
 * <h4>Metrics Include</h4>
 * <ul>
 *   <li>Total attacks generated</li>
 *   <li>Attacks applied</li>
 *   <li>Attack success rate</li>
 *   <li>Diversity score</li>
 *   <li>Components attacked</li>
 *   <li>Attack types used</li>
 * </ul>
 *
 * @param success Whether the request was successful
 * @param metrics The attack metrics (success case)
 * @param error   Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialMetricsResponse(
        boolean success,
        Map<String, Object> metrics,
        String error
) {
    public static AdversarialMetricsResponse success(Map<String, Object> metrics) {
        return new AdversarialMetricsResponse(true, metrics, null);
    }

    public static AdversarialMetricsResponse error(String error) {
        return new AdversarialMetricsResponse(false, null, error);
    }
}