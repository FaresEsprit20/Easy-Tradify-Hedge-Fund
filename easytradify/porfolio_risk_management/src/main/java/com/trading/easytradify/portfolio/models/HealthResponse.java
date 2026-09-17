package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * <h1>Health Response</h1>
 * <p>
 * Response containing the service health status.
 * </p>
 *
 * @param status              The service status: "operational" or "error"
 * @param serviceInitialized  Whether the portfolio service is initialized
 * @param error               Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record HealthResponse(
        String status,
        Boolean serviceInitialized,
        String error
) {
    // Static factory methods - these are allowed in records
    // The error might be from your IDE/lombok config, but these are valid Java
    public static HealthResponse operational(Boolean serviceInitialized) {
        return new HealthResponse("operational", serviceInitialized, null);
    }

    public static HealthResponse error(String error) {
        return new HealthResponse("error", false, error);
    }

}