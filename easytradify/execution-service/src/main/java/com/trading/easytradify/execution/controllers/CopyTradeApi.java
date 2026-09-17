package com.trading.easytradify.execution.controllers;

import com.trading.easytradify.execution.models.*;
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

import java.util.Map;

/**
 * <h1>Copy Trade API</h1>
 * <p>
 * REST API for executing copy trades and handling webhook notifications.
 * This interface defines all endpoints with comprehensive Swagger/OpenAPI documentation.
 * </p>
 *
 * <h2>Base Path</h2>
 * <p>
 * All endpoints are prefixed with {@code /api/v1/copy-trade}
 * </p>
 *
 * <h2>Authentication</h2>
 * <p>
 * All endpoints require a valid API key in the {@code X-API-Key} header.
 * </p>
 *
 * <h2>Webhook Integration</h2>
 * <p>
 * The webhook endpoints are designed to receive notifications from MT5
 * terminals when trades are closed or trailing stops are updated.
 * </p>
 *
 * <h2>Error Handling</h2>
 * <p>
 * All errors are returned in a standardized format via
 * {@link com.trading.easytradify.common.exception.CustomErrorMsg}.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 */
@Tag(name = "Copy Trade", description = "Copy trade execution and webhook handling")
@RequestMapping("/api/v1/copy-trade")
public interface CopyTradeApi {

    // ============================================================
    // COPY TRADE EXECUTION
    // ============================================================

    /**
     * <h3>Execute a Copy Trade</h3>
     * <p>
     * Executes a copy trade based on the provided analysis result.
     * The trade is executed via the Python copy trade executor and saved to Firebase.
     * </p>
     *
     * <h4>Request Requirements</h4>
     * <ul>
     *   <li><b>symbol:</b> Must be a valid trading symbol (e.g., "EURUSD")</li>
     *   <li><b>analysis_result:</b> Must contain {@code final_verdict} with {@code stop_loss} and {@code take_profit_1}</li>
     *   <li><b>analysis_result.config:</b> Must contain {@code executed_direction} (BUY/SELL)</li>
     * </ul>
     *
     * <h4>Response</h4>
     * <p>
     * Returns the execution result including ticket number, entry price,
     * stop loss, take profit, and volume.
     * </p>
     *
     * @param request The copy trade request containing symbol and analysis result
     * @return {@link CopyTradeResponse} containing the execution result
     */
    @Operation(
            summary = "Execute a copy trade",
            description = """
                    Executes a copy trade based on the provided analysis result.
                    
                    **Request Requirements:**
                    - `symbol`: Must be a valid trading symbol (e.g., "EURUSD")
                    - `analysis_result`: Must contain `final_verdict` with `stop_loss` and `take_profit_1`
                    - `analysis_result.config`: Must contain `executed_direction` (BUY/SELL)
                    
                    **Execution Behavior:**
                    - The trade is executed via the Python copy trade executor
                    - The trade is saved to Firebase with full analysis data
                    - No gating or filtering is applied (trust the caller)
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Copy trade executed successfully",
                    content = @Content(schema = @Schema(implementation = CopyTradeResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid request or analysis result",
                    content = @Content(schema = @Schema(implementation = CopyTradeResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Broker not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/execute")
    ResponseEntity<CopyTradeResponse> executeCopyTrade(
            @Parameter(
                    description = "Copy trade request containing symbol and analysis result",
                    required = true
            )
            @Valid @RequestBody CopyTradeRequest request
    );

    // ============================================================
    // WEBHOOK ENDPOINTS
    // ============================================================

    /**
     * <h3>Trade Closure Webhook</h3>
     * <p>
     * Handles trade closure notifications from MT5 terminals.
     * This endpoint is called when a trade is closed by SL/TP hit or manual intervention.
     * </p>
     *
     * <h4>Webhook Payload</h4>
     * <ul>
     *   <li><b>symbol:</b> Trading symbol (required)</li>
     *   <li><b>ticket:</b> MT5 ticket number (required)</li>
     *   <li><b>close_reason:</b> Reason for closure (default: SL_TP_HIT)</li>
     *   <li><b>profit:</b> Profit in USD</li>
     *   <li><b>price_open:</b> Entry price</li>
     *   <li><b>price_close:</b> Exit price</li>
     *   <li><b>volume:</b> Trade volume</li>
     * </ul>
     *
     * @param request The webhook trade request
     * @return {@link WebhookResponse} indicating processing status
     */
    @Operation(
            summary = "Trade closure webhook",
            description = """
                    Handles trade closure notifications from MT5 terminals.
                    
                    **When Called:**
                    - Trade hits stop loss (SL)
                    - Trade hits take profit (TP)
                    - Trade is manually closed
                    - Trailing stop closes the trade
                    
                    **Processing:**
                    - Validates the webhook payload
                    - Saves the trade closure to Firebase
                    - Triggers analysis capture at close
                    - Returns processing status
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Webhook processed successfully",
                    content = @Content(schema = @Schema(implementation = WebhookResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid webhook payload",
                    content = @Content(schema = @Schema(implementation = WebhookResponse.class))
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
    @PostMapping("/webhook/trade")
    ResponseEntity<WebhookResponse> webhookTrade(
            @Parameter(
                    description = "Trade closure webhook payload",
                    required = true
            )
            @RequestBody WebhookTradeRequest request
    );

    /**
     * <h3>Trailing Stop Webhook</h3>
     * <p>
     * Handles trailing stop notifications from MT5 terminals.
     * This endpoint is called when trailing stops are updated or triggered.
     * </p>
     *
     * @param request The trailing stop webhook request
     * @return {@link WebhookResponse} indicating processing status
     */
    @Operation(
            summary = "Trailing stop webhook",
            description = """
                    Handles trailing stop notifications from MT5 terminals.
                    
                    **When Called:**
                    - Trailing stop is enabled
                    - Trailing stop step is updated
                    - Trailing stop is disabled
                    - Trailing stop is triggered
                    
                    **Processing:**
                    - Validates the webhook payload
                    - Saves the trailing stop update to Firebase
                    - Returns processing status
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Webhook processed successfully",
                    content = @Content(schema = @Schema(implementation = WebhookResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid webhook payload",
                    content = @Content(schema = @Schema(implementation = WebhookResponse.class))
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
    @PostMapping("/webhook/trailing")
    ResponseEntity<WebhookResponse> webhookTrailing(
            @Parameter(
                    description = "Trailing stop webhook payload",
                    required = true
            )
            @RequestBody WebhookTrailingRequest request
    );

    /**
     * <h3>Test Webhook Endpoint</h3>
     * <p>
     * Test endpoint for verifying webhook connectivity and payload format.
     * This is useful for debugging webhook integration.
     * </p>
     *
     * @param payload The test payload
     * @return {@link WebhookResponse} indicating test result
     */
    @Operation(
            summary = "Test webhook endpoint",
            description = """
                    Test endpoint for verifying webhook connectivity and payload format.
                    
                    **Usage:**
                    Send any JSON payload to test the webhook integration.
                    The response will indicate whether the payload was received and processed.
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Test successful",
                    content = @Content(schema = @Schema(implementation = WebhookResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid test payload",
                    content = @Content(schema = @Schema(implementation = WebhookResponse.class))
            )
    })
    @PostMapping("/webhook/test")
    ResponseEntity<WebhookResponse> webhookTest(
            @Parameter(
                    description = "Test payload (any JSON object)",
                    required = true
            )
            @RequestBody Object payload
    );

    // ============================================================
    // STATUS & HEALTH ENDPOINTS
    // ============================================================

    /**
     * <h3>Webhook Health Check</h3>
     * <p>
     * Checks the health of the webhook service.
     * </p>
     *
     * @return Health status map containing:
     *         <ul>
     *           <li>{@code status}: "healthy" or "unhealthy"</li>
     *           <li>{@code timestamp}: Current timestamp</li>
     *           <li>{@code errors}: List of recent errors (if any)</li>
     *         </ul>
     */
    @Operation(
            summary = "Webhook health check",
            description = "Checks the health of the webhook service."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Service is healthy",
                    content = @Content(schema = @Schema(implementation = Map.class))
            )
    })
    @GetMapping("/webhook/health")
    ResponseEntity<Map<String, Object>> webhookHealth();

    /**
     * <h3>Webhook Debug Info</h3>
     * <p>
     * Retrieves debug information from the webhook service.
     * </p>
     *
     * @return Debug information map containing:
     *         <ul>
     *           <li>Webhook URL configuration</li>
     *           <li>Recent webhook requests</li>
     *           <li>Success/failure counts</li>
     *           <li>Average processing time</li>
     *         </ul>
     */
    @Operation(
            summary = "Webhook debug info",
            description = "Retrieves debug information from the webhook service."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Debug information retrieved",
                    content = @Content(schema = @Schema(implementation = Map.class))
            )
    })
    @GetMapping("/webhook/debug")
    ResponseEntity<Map<String, Object>> webhookDebug();

    /**
     * <h3>Get Executor Status</h3>
     * <p>
     * Retrieves the status of the copy trade executor including open positions
     * and performance statistics.
     * </p>
     *
     * @return Status information map containing:
     *         <ul>
     *           <li>{@code running}: Whether the executor is running</li>
     *           <li>{@code open_positions}: List of open positions</li>
     *           <li>{@code stats}: Execution statistics</li>
     *         </ul>
     */
    @Operation(
            summary = "Get executor status",
            description = "Retrieves the status of the copy trade executor."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Status retrieved",
                    content = @Content(schema = @Schema(implementation = Map.class))
            )
    })
    @GetMapping("/status")
    ResponseEntity<Map<String, Object>> getStatus();

    /**
     * <h3>Service Health Check</h3>
     * <p>
     * Performs a health check on the copy trade service.
     * </p>
     *
     * @return {@link HealthResponse}
     *         containing the service health status
     */
    @Operation(
            summary = "Service health check",
            description = "Performs a health check on the copy trade service."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Service is healthy",
                    content = @Content(schema = @Schema(implementation = HealthResponse.class))
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Service is unhealthy",
                    content = @Content(schema = @Schema(implementation = HealthResponse.class))
            )
    })
    @GetMapping("/health")
    ResponseEntity<HealthResponse> healthCheck();
}