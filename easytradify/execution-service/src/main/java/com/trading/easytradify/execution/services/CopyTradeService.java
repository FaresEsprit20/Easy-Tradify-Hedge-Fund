package com.trading.easytradify.execution.services;

import com.trading.easytradify.execution.models.*;

import java.util.Map;

/**
 * <h1>Copy Trade Service</h1>
 * <p>
 * Service for executing copy trades and handling webhook notifications
 * from MetaTrader 5 terminals. This service acts as a bridge between
 * the copy trade signal source and the MT5 execution engine.
 * </p>
 *
 * <h2>Architecture Overview</h2>
 * <p>
 * The service follows the <b>Execute-and-Save</b> pattern:
 * </p>
 * <ol>
 *   <li>Receives a trade signal with analysis results</li>
 *   <li>Executes the trade via the Python execution service</li>
 *   <li>Saves the trade to Firebase for tracking</li>
 *   <li>Handles webhook notifications for trade closures and trailing stops</li>
 * </ol>
 *
 * <h2>Key Features</h2>
 * <ul>
 *   <li><b>Zero Gating:</b> No symbol discovery, filtering, or confidence gating</li>
 *   <li><b>Trust the Caller:</b> Executes exactly what it receives</li>
 *   <li><b>Webhook Support:</b> Handles MT5 trade closure and trailing stop webhooks</li>
 *   <li><b>Firebase Persistence:</b> Saves all trades to the "trades" collection</li>
 * </ul>
 *
 * <h2>Error Handling Strategy</h2>
 * <p>
 * This service uses a <b>fail-fast</b> approach:
 * </p>
 * <ol>
 *   <li>Input validation is performed before any operation</li>
 *   <li>Validation failures throw {@link com.trading.easytradify.common.exception.TradingException}</li>
 *   <li>Business errors throw {@link com.trading.easytradify.common.exception.TradingException}</li>
 *   <li>All exceptions are propagated to {@code GlobalExceptionHandler}</li>
 * </ol>
 *
 * <h2>Thread Safety</h2>
 * <p>
 * All implementations of this interface must be thread-safe.
 * The service is designed to handle concurrent requests without
 * synchronization overhead.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see CopyTradeServiceImpl
 * @see com.trading.easytradify.common.exception.TradingException
 */
public interface CopyTradeService {

    /**
     * <h3>Execute a Copy Trade</h3>
     * <p>
     * Executes a copy trade based on the provided analysis result.
     * The trade is executed via the Python copy trade executor and
     * saved to Firebase.
     * </p>
     *
     * <h4>Request Requirements</h4>
     * <ul>
     *   <li><b>symbol:</b> Must be a valid trading symbol (e.g., "EURUSD")</li>
     *   <li><b>analysis_result:</b> Must contain {@code final_verdict} with {@code stop_loss} and {@code take_profit_1}</li>
     *   <li><b>analysis_result.config:</b> Must contain {@code executed_direction} (BUY/SELL)</li>
     * </ul>
     *
     * <h4>Validation Rules</h4>
     * <ul>
     *   <li>Symbol cannot be {@code null} or empty</li>
     *   <li>Analysis result cannot be {@code null} or empty</li>
     *   <li>Stop loss and take profit must be positive</li>
     *   <li>Broker must be active and available</li>
     * </ul>
     *
     * <h4>Example</h4>
     * <pre>{@code
     * var request = new CopyTradeRequest("EURUSD", analysisResult);
     * CopyTradeResponse response = copyTradeService.executeCopyTrade(request);
     * if (response.success()) {
     *     System.out.println("Trade executed: " + response.ticket());
     * }
     * }</pre>
     *
     * @param request The copy trade request containing symbol and analysis result
     * @return {@link CopyTradeResponse} containing the execution result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If validation fails, execution fails, or analysis result is invalid
     * @throws IllegalArgumentException If request is {@code null}
     * @see CopyTradeRequest
     * @see CopyTradeResponse
     */
    CopyTradeResponse executeCopyTrade(CopyTradeRequest request);

    /**
     * <h3>Handle Trade Closure Webhook</h3>
     * <p>
     * Processes a trade closure webhook from MT5/TradingView. This is called
     * when a trade is closed by SL/TP hit, manual intervention, or trailing stop.
     * </p>
     *
     * <h4>Webhook Payload Requirements</h4>
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
     * <h4>Validation Rules</h4>
     * <ul>
     *   <li>Symbol and ticket cannot be {@code null}</li>
     *   <li>Ticket must be positive</li>
     *   <li>Price values must be positive</li>
     * </ul>
     *
     * @param request The webhook trade request
     * @return {@link WebhookResponse} indicating processing status
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the webhook payload is invalid or processing fails
     * @see WebhookTradeRequest
     * @see WebhookResponse
     */
    WebhookResponse handleWebhookTrade(WebhookTradeRequest request);

    /**
     * <h3>Handle Trailing Stop Webhook</h3>
     * <p>
     * Processes a trailing stop webhook from MT5. This is called when the
     * trailing stop is updated or triggered.
     * </p>
     *
     * <h4>Validation Rules</h4>
     * <ul>
     *   <li>Ticket must be positive</li>
     *   <li>Stop loss price must be positive</li>
     *   <li>Step pips must be positive</li>
     * </ul>
     *
     * @param request The trailing stop webhook request
     * @return {@link WebhookResponse} indicating processing status
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the webhook payload is invalid or processing fails
     * @see WebhookTrailingRequest
     * @see WebhookResponse
     */
    WebhookResponse handleWebhookTrailing(WebhookTrailingRequest request);

    /**
     * <h3>Test Webhook Endpoint</h3>
     * <p>
     * Sends a test payload to the webhook endpoint to verify connectivity
     * and payload format. This is useful for debugging webhook integration.
     * </p>
     *
     * @param payload The test payload (can be any object)
     * @return {@link WebhookResponse} indicating test result
     */
    WebhookResponse webhookTest(Object payload);

    /**
     * <h3>Get Webhook Health</h3>
     * <p>
     * Checks the health of the webhook service. Returns the status of the
     * webhook endpoint and any recent errors.
     * </p>
     *
     * @return Health status map containing:
     *         <ul>
     *           <li>{@code status}: "healthy" or "unhealthy"</li>
     *           <li>{@code timestamp}: Current timestamp</li>
     *           <li>{@code errors}: List of recent errors (if any)</li>
     *         </ul>
     */
    Map<String, Object> getWebhookHealth();

    /**
     * <h3>Get Webhook Debug Info</h3>
     * <p>
     * Retrieves debug information from the webhook service. This includes
     * configuration details, recent requests, and performance metrics.
     * </p>
     *
     * <h4>Debug Information</h4>
     * <ul>
     *   <li>Webhook URL configuration</li>
     *   <li>Recent webhook requests</li>
     *   <li>Success/failure counts</li>
     *   <li>Average processing time</li>
     * </ul>
     *
     * @return Debug information map
     */
    Map<String, Object> getWebhookDebug();

    /**
     * <h3>Get Executor Status</h3>
     * <p>
     * Retrieves the status of the copy trade executor including open positions
     * and performance statistics.
     * </p>
     *
     * <h4>Status Information</h4>
     * <ul>
     *   <li>{@code running}: Whether the executor is running</li>
     *   <li>{@code open_positions}: List of open positions</li>
     *   <li>{@code stats}: Execution statistics</li>
     * </ul>
     *
     * @return Status information map
     */
    Map<String, Object> getStatus();

    /**
     * <h3>Health Check</h3>
     * <p>
     * Performs a health check on the Python copy trade service.
     * Verifies that the service is running and can accept requests.
     * </p>
     *
     * <h4>Health Check Results</h4>
     * <ul>
     *   <li>{@code status}: "operational" or "error"</li>
     *   <li>{@code running}: Whether the executor is running</li>
     *   <li>{@code timestamp}: Check timestamp</li>
     * </ul>
     *
     * @return {@link HealthResponse} containing the service health status
     */
    HealthResponse healthCheck();

}