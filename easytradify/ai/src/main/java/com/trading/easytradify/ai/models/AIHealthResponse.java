package com.trading.easytradify.ai.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.Map;

/**
 * <h1>AI Health Response</h1>
 * <p>
 * Response containing the AI service health status.
 * </p>
 *
 * @param status          The service status: "healthy" or "initializing"
 * @param service         The service name
 * @param port            The service port
 * @param initialized     Whether the service is initialized
 * @param gnn             GNN status information
 * @param adversarial     Adversarial training status
 * @param timestamp       Current timestamp
 * @param error           Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AIHealthResponse(
        String status,
        String service,
        Integer port,
        Boolean initialized,
        Map<String, Object> gnn,
        Map<String, Object> adversarial,
        String timestamp,
        String error
) {
    public static AIHealthResponse success(
            String status,
            String service,
            Integer port,
            Boolean initialized,
            Map<String, Object> gnn,
            Map<String, Object> adversarial,
            String timestamp) {
        return new AIHealthResponse(status, service, port, initialized, gnn, adversarial, timestamp, null);
    }

    public static AIHealthResponse error(String error) {
        return new AIHealthResponse("error", null, null, false, null, null, null, error);
    }
}