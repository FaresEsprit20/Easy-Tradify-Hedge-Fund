package com.trading.easytradify.ai.models.adverserial;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>Adversarial Generate Request</h1>
 * <p>
 * Request to generate attacked trade variations for adversarial training.
 * </p>
 *
 * <h4>Attack Types</h4>
 * <ul>
 *   <li><b>PRICE_SHIFT:</b> Shift entry/stop/take profit levels</li>
 *   <li><b>VOLUME_SPIKE:</b> Add fake volume spikes</li>
 *   <li><b>MOMENTUM_FLIP:</b> Reverse momentum indicators</li>
 *   <li><b>STRUCTURE_BREAK:</b> Break structural levels</li>
 *   <li><b>COMBINED:</b> Combine multiple attack types</li>
 * </ul>
 *
 * @param trade          The trade data to attack
 * @param outcome        The outcome: 1 = WIN, 0 = LOSS
 * @param numVariations  Number of variations to generate (optional)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdversarialGenerateRequest(
        Map<String, Object> trade,
        Integer outcome,
        Integer numVariations
) {
    // No validation in constructor - handled by service
}