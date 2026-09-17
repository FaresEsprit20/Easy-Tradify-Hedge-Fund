package com.trading.easytradify.ai.controllers;

import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.AdversarialIntensityRequest;
import com.trading.easytradify.ai.models.adverserial.*;
import com.trading.easytradify.ai.models.gnn.*;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * <h1>AI Service API</h1>
 * <p>
 * REST API for AI-powered trading intelligence including GNN (Graph Neural Network)
 * and Adversarial Training capabilities.
 * </p>
 *
 * <h2>Base Path</h2>
 * <p>
 * All endpoints are prefixed with {@code /api/v1/ai}
 * </p>
 *
 * <h2>Authentication</h2>
 * <p>
 * All endpoints require a valid API key in the {@code X-API-Key} header.
 * </p>
 *
 * <h2>GNN Features (14 endpoints)</h2>
 * <ul>
 *   <li>GET  /gnn/status - Get GNN status</li>
 *   <li>GET  /gnn/context/{symbol} - Get GNN context</li>
 *   <li>GET  /gnn/insights/{symbol} - Get GNN insights</li>
 *   <li>GET  /gnn/correlations/{symbol} - Get GNN correlations</li>
 *   <li>GET  /gnn/divergences/{symbol} - Get GNN divergences</li>
 *   <li>GET  /gnn/suggestions/{symbol} - Get GNN suggestions</li>
 *   <li>GET  /gnn/conflict/{symbol} - Get GNN conflict</li>
 *   <li>GET  /gnn/ab-test - Get GNN A/B test results</li>
 *   <li>GET  /gnn/heatmap - Get GNN heatmap</li>
 *   <li>GET  /gnn/correlation-changes/{symbol} - Get correlation changes</li>
 *   <li>POST /gnn/refresh - Refresh GNN</li>
 *   <li>POST /gnn/reset - Reset GNN</li>
 *   <li>POST /gnn/ab-test/rollout - Set GNN A/B test rollout</li>
 *   <li>POST /gnn/track-result - Track GNN result</li>
 * </ul>
 *
 * <h2>Adversarial Features (6 endpoints)</h2>
 * <ul>
 *   <li>GET  /adversarial/status - Get adversarial status</li>
 *   <li>POST /adversarial/generate - Generate adversarial attacks</li>
 *   <li>POST /adversarial/train - Train adversarial</li>
 *   <li>GET  /adversarial/metrics - Get adversarial metrics</li>
 *   <li>POST /adversarial/intensity - Set adversarial intensity</li>
 *   <li>POST /adversarial/enable - Enable/disable adversarial</li>
 * </ul>
 *
 * <h2>Health (1 endpoint)</h2>
 * <ul>
 *   <li>GET /health - Health check</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 */
@Tag(name = "AI Service", description = "AI-powered trading intelligence including GNN and Adversarial Training")
@RequestMapping("/api/v1/ai")
public interface AIApi {

    // ============================================================
    // HEALTH
    // ============================================================

    @Operation(
            summary = "Health check",
            description = "Performs a health check on the AI service."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Service is healthy",
                    content = @Content(schema = @Schema(implementation = AIHealthResponse.class))
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Service is unhealthy",
                    content = @Content(schema = @Schema(implementation = AIHealthResponse.class))
            )
    })
    @GetMapping("/health")
    ResponseEntity<AIHealthResponse> healthCheck();

    // ============================================================
    // GNN ENDPOINTS (14)
    // ============================================================

    @Operation(
            summary = "Get GNN status",
            description = "Retrieves the current status of the GNN."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "GNN status retrieved successfully",
                    content = @Content(schema = @Schema(implementation = GnnStatusResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/status")
    ResponseEntity<GnnStatusResponse> getGnnStatus();

    @Operation(
            summary = "Get GNN context",
            description = "Retrieves GNN context for a symbol used in AI Asset Analyzer feature extraction."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "GNN context retrieved successfully",
                    content = @Content(schema = @Schema(implementation = GnnContextResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid symbol"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Symbol not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/context/{symbol}")
    ResponseEntity<GnnContextResponse> getGnnContext(
            @Parameter(description = "Trading symbol (e.g., EURUSD)", required = true)
            @PathVariable String symbol,

            @Parameter(description = "Optional trade ID for tracking")
            @RequestParam(required = false) Integer tradeId
    );

    @Operation(
            summary = "Get GNN insights",
            description = "Retrieves complete trading insights for a symbol."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "GNN insights retrieved successfully",
                    content = @Content(schema = @Schema(implementation = GnnInsightsResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid symbol or direction"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Symbol not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/insights/{symbol}")
    ResponseEntity<GnnInsightsResponse> getGnnInsights(
            @Parameter(description = "Trading symbol (e.g., EURUSD)", required = true)
            @PathVariable String symbol,

            @Parameter(description = "Analysis direction: BUY, SELL, or HOLD")
            @RequestParam(required = false) String analysisDirection
    );

    @Operation(
            summary = "Get GNN correlations",
            description = "Retrieves correlation information for a symbol."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "GNN correlations retrieved successfully",
                    content = @Content(schema = @Schema(implementation = GnnCorrelationsResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid symbol"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Symbol not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/correlations/{symbol}")
    ResponseEntity<GnnCorrelationsResponse> getGnnCorrelations(
            @Parameter(description = "Trading symbol (e.g., EURUSD)", required = true)
            @PathVariable String symbol
    );

    @Operation(
            summary = "Get GNN divergences",
            description = "Checks for divergences between GNN and price direction."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "GNN divergences retrieved successfully",
                    content = @Content(schema = @Schema(implementation = GnnDivergencesResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid symbol"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Symbol not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/divergences/{symbol}")
    ResponseEntity<GnnDivergencesResponse> getGnnDivergences(
            @Parameter(description = "Trading symbol (e.g., EURUSD)", required = true)
            @PathVariable String symbol
    );

    @Operation(
            summary = "Get GNN suggestions",
            description = "Retrieves trade suggestions for correlated symbols."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "GNN suggestions retrieved successfully",
                    content = @Content(schema = @Schema(implementation = GnnSuggestionsResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid symbol"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Symbol not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/suggestions/{symbol}")
    ResponseEntity<GnnSuggestionsResponse> getGnnSuggestions(
            @Parameter(description = "Trading symbol (e.g., EURUSD)", required = true)
            @PathVariable String symbol
    );

    @Operation(
            summary = "Get GNN conflict",
            description = "Detects contradiction between your analysis and GNN predictions."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "GNN conflict detected successfully",
                    content = @Content(schema = @Schema(implementation = GnnConflictResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid symbol or direction"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Symbol not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/conflict/{symbol}")
    ResponseEntity<GnnConflictResponse> getGnnConflict(
            @Parameter(description = "Trading symbol (e.g., EURUSD)", required = true)
            @PathVariable String symbol,

            @Parameter(description = "Your analysis direction: BUY or SELL", required = true)
            @RequestParam String analysisDirection
    );

    @Operation(
            summary = "Get GNN A/B test results",
            description = "Retrieves GNN A/B test results and statistics."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "A/B test results retrieved successfully",
                    content = @Content(schema = @Schema(implementation = GnnAbTestResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/ab-test")
    ResponseEntity<GnnAbTestResponse> getGnnAbTest();

    @Operation(
            summary = "Get GNN heatmap",
            description = "Retrieves a correlation heatmap for symbols."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Heatmap retrieved successfully",
                    content = @Content(schema = @Schema(implementation = GnnHeatmapResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/heatmap")
    ResponseEntity<GnnHeatmapResponse> getGnnHeatmap(
            @Parameter(description = "Comma-separated list of symbols (optional)")
            @RequestParam(required = false) String symbols
    );

    @Operation(
            summary = "Get GNN correlation changes",
            description = "Detects significant changes in correlations (regime shifts)."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Correlation changes retrieved successfully",
                    content = @Content(schema = @Schema(implementation = GnnCorrelationChangesResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid symbol or lookback"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Symbol not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/gnn/correlation-changes/{symbol}")
    ResponseEntity<GnnCorrelationChangesResponse> getGnnCorrelationChanges(
            @Parameter(description = "Trading symbol (e.g., EURUSD)", required = true)
            @PathVariable String symbol,

            @Parameter(description = "Lookback period in bars (default: 10)")
            @RequestParam(defaultValue = "10") int lookback
    );

    @Operation(
            summary = "Refresh GNN",
            description = "Forces a refresh of the GNN cache."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "GNN refreshed successfully",
                    content = @Content(schema = @Schema(implementation = GnnRefreshResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/gnn/refresh")
    ResponseEntity<GnnRefreshResponse> refreshGnn();

    @Operation(
            summary = "Reset GNN",
            description = "Resets the GNN state."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "GNN reset successfully",
                    content = @Content(schema = @Schema(implementation = GnnResetResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/gnn/reset")
    ResponseEntity<GnnResetResponse> resetGnn();

    @Operation(
            summary = "Set GNN A/B test rollout",
            description = "Sets the A/B test rollout percentage."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Rollout updated successfully",
                    content = @Content(schema = @Schema(implementation = GnnRolloutResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid rollout value"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/gnn/ab-test/rollout")
    ResponseEntity<GnnRolloutResponse> setGnnAbTestRollout(
            @Parameter(description = "Rollout request", required = true)
            @Valid @RequestBody GnnRolloutRequest request
    );

    @Operation(
            summary = "Track GNN result",
            description = "Tracks a trade outcome for A/B testing."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Result tracked successfully",
                    content = @Content(schema = @Schema(implementation = GnnTrackResultResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid request"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/gnn/track-result")
    ResponseEntity<GnnTrackResultResponse> trackGnnResult(
            @Parameter(description = "Track result request", required = true)
            @Valid @RequestBody GnnTrackResultRequest request
    );

    // ============================================================
    // ADVERSARIAL ENDPOINTS (6)
    // ============================================================

    @Operation(
            summary = "Get adversarial status",
            description = "Retrieves the current status of adversarial training."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Adversarial status retrieved successfully",
                    content = @Content(schema = @Schema(implementation = AdversarialStatusResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/adversarial/status")
    ResponseEntity<AdversarialStatusResponse> getAdversarialStatus();

    @Operation(
            summary = "Generate adversarial attacks",
            description = "Generates attacked trade variations for adversarial training."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Attacks generated successfully",
                    content = @Content(schema = @Schema(implementation = AdversarialGenerateResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid request"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/adversarial/generate")
    ResponseEntity<AdversarialGenerateResponse> generateAdversarialAttacks(
            @Parameter(description = "Adversarial generate request", required = true)
            @Valid @RequestBody AdversarialGenerateRequest request
    );

    @Operation(
            summary = "Train adversarial",
            description = "Applies adversarial attacks to training data."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Training completed successfully",
                    content = @Content(schema = @Schema(implementation = AdversarialTrainResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid request"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/adversarial/train")
    ResponseEntity<AdversarialTrainResponse> trainAdversarial(
            @Parameter(description = "Adversarial train request", required = true)
            @Valid @RequestBody AdversarialTrainRequest request
    );

    @Operation(
            summary = "Get adversarial metrics",
            description = "Retrieves adversarial attack metrics and statistics."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Metrics retrieved successfully",
                    content = @Content(schema = @Schema(implementation = AdversarialMetricsResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/adversarial/metrics")
    ResponseEntity<AdversarialMetricsResponse> getAdversarialMetrics();

    @Operation(
            summary = "Set adversarial intensity",
            description = "Sets the attack intensity level."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Intensity updated successfully",
                    content = @Content(schema = @Schema(implementation = AdversarialIntensityResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid intensity value"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/adversarial/intensity")
    ResponseEntity<AdversarialIntensityResponse> setAdversarialIntensity(
            @Parameter(description = "Intensity request", required = true)
            @Valid @RequestBody AdversarialIntensityRequest request
    );

    @Operation(
            summary = "Enable/Disable adversarial",
            description = "Enables or disables adversarial training."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Adversarial training enabled/disabled successfully",
                    content = @Content(schema = @Schema(implementation = AdversarialEnableResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid request"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/adversarial/enable")
    ResponseEntity<AdversarialEnableResponse> enableAdversarial(
            @Parameter(description = "Enable request", required = true)
            @Valid @RequestBody AdversarialEnableRequest request
    );
}