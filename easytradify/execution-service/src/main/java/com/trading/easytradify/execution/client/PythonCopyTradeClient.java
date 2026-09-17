package com.trading.easytradify.execution.client;

import com.trading.easytradify.execution.config.broker.BrokerConfig;
import com.trading.easytradify.execution.models.*;


/**
 * <h1>Python Copy Trade Client</h1>
 * <p>
 * Client interface for communicating with the Python-based copy trade executor
 * service running on port 5003. This client provides a clean abstraction for
 * executing copy trades and handling webhook notifications.
 * </p>
 *
 * <h2>Python Service Endpoints</h2>
 * <ul>
 *   <li><b>POST /execute</b> - Execute a copy trade</li>
 *   <li><b>POST /webhook/trade</b> - Trade closure webhook</li>
 *   <li><b>POST /webhook/trailing</b> - Trailing stop webhook</li>
 *   <li><b>POST /webhook/test</b> - Test webhook endpoint</li>
 *   <li><b>GET /webhook/health</b> - Health check</li>
 *   <li><b>GET /webhook/debug</b> - Debug information</li>
 *   <li><b>GET /status</b> - Executor status</li>
 *   <li><b>GET /health</b> - Service health</li>
 * </ul>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Zero Gating:</b> No symbol discovery, filtering, or confidence gating</li>
 *   <li><b>Trust the Caller:</b> Executes exactly what it receives</li>
 *   <li><b>Firebase Persistence:</b> Saves all trades to the "trades" collection</li>
 *   <li><b>Webhook Support:</b> Handles MT5 trade closure and trailing stop webhooks</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see DefaultPythonCopyTradeClient
 */
public interface PythonCopyTradeClient {

    /**
     * <h3>Execute a Copy Trade</h3>
     * <p>
     * Executes a copy trade based on the provided analysis result.
     * The trade is executed via the Python copy trade executor and
     * saved to Firebase.
     * </p>
     *
     * <h4>Request Format</h4>
     * <p>
     * The request must contain:
     * </p>
     * <ul>
     *   <li><b>symbol:</b> Trading symbol (e.g., "EURUSD")</li>
     *   <li><b>analysis_result:</b> Full analysis result from {@code analyze_institutional_signal()}</li>
     * </ul>
     *
     * <h4>Example</h4>
     * <pre>{@code
     * var request = new CopyTradeRequest("EURUSD", analysisResult);
     * CopyTradeResponse response = client.executeCopyTrade(request);
     * }</pre>
     *
     * @param request The copy trade request containing symbol and analysis result
     * @return {@link CopyTradeResponse} containing the execution result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the execution fails or the analysis result is invalid
     * @see CopyTradeRequest
     * @see CopyTradeResponse
     */
    CopyTradeResponse executeCopyTrade(CopyTradeRequest request);

    /**
     * <h3>Handle Trade Closure Webhook</h3>
     * <p>
     * Processes a trade closure webhook from MT5/TradingView. This is called
     * when a trade is closed by SL/TP hit or manual intervention.
     * </p>
     *
     * <h4>Webhook Payload</h4>
     * <ul>
     *   <li><b>symbol:</b> Trading symbol</li>
     *   <li><b>ticket:</b> MT5 ticket number</li>
     *   <li><b>close_reason:</b> Reason for closure (SL_TP_HIT, etc.)</li>
     *   <li><b>profit:</b> Profit in USD</li>
     *   <li><b>price_open:</b> Entry price</li>
     *   <li><b>price_close:</b> Exit price</li>
     *   <li><b>volume:</b> Trade volume</li>
     *   <li><b>sl:</b> Stop loss price</li>
     *   <li><b>tp:</b> Take profit price</li>
     * </ul>
     *
     * @param request The webhook trade request
     * @return {@link WebhookResponse} indicating processing status
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the webhook processing fails
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
     * @param request The trailing stop webhook request
     * @return {@link WebhookResponse} indicating processing status
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the webhook processing fails
     * @see WebhookTrailingRequest
     * @see WebhookResponse
     */
    WebhookResponse handleWebhookTrailing(WebhookTrailingRequest request);

    /**
     * <h3>Test Webhook Endpoint</h3>
     * <p>
     * Sends a test payload to the webhook endpoint to verify connectivity
     * and payload format.
     * </p>
     *
     * @param payload The test payload
     * @return {@link WebhookResponse} indicating test result
     */
    WebhookResponse webhookTest(Object payload);

    /**
     * <h3>Get Webhook Health</h3>
     * <p>
     * Checks the health of the webhook service.
     * </p>
     *
     * @return Health status map
     */
    java.util.Map<String, Object> getWebhookHealth();

    /**
     * <h3>Get Webhook Debug Info</h3>
     * <p>
     * Retrieves debug information from the webhook service.
     * </p>
     *
     * @return Debug information map
     */
    java.util.Map<String, Object> getWebhookDebug();

    /**
     * <h3>Get Executor Status</h3>
     * <p>
     * Retrieves the status of the copy trade executor including
     * open positions and statistics.
     * </p>
     *
     * @return Status information map
     */
    java.util.Map<String, Object> getStatus();

    /**
     * <h3>Health Check</h3>
     * <p>
     * Performs a health check on the Python copy trade service.
     * </p>
     *
     * @param broker The broker configuration (optional)
     * @return Health response
     */
    HealthResponse healthCheck(BrokerConfig broker);
}