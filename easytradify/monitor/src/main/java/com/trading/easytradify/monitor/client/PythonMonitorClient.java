package com.trading.easytradify.monitor.client;


import com.trading.easytradify.monitor.models.*;

import java.util.List;
import java.util.Map;

/**
 * <h1>Python Monitor Client</h1>
 * <p>
 * Client interface for communicating with the Python-based monitor service
 * running on port 5001. This client provides a clean abstraction for all
 * monitor operations including symbol discovery, scanning, ranking, and
 * webhook processing.
 * </p>
 *
 * <h2>Python Service Endpoints (Port 5001)</h2>
 * <table>
 *   <caption>Monitor Service Endpoints</caption>
 *   <tr><th>Method</th><th>Endpoint</th><th>Description</th></tr>
 *   <tr><td>POST</td><td>/monitor/start</td><td>Start the monitor</td></tr>
 *   <tr><td>POST</td><td>/monitor/stop</td><td>Stop the monitor</td></tr>
 *   <tr><td>POST</td><td>/monitor/refresh</td><td>Force refresh</td></tr>
 *   <tr><td>GET</td><td>/monitor/status</td><td>Get monitor status</td></tr>
 *   <tr><td>GET</td><td>/monitor/top_symbols</td><td>Get top symbols</td></tr>
 *   <tr><td>GET</td><td>/monitor/filtered_symbols</td><td>Get filtered symbols</td></tr>
 *   <tr><td>GET</td><td>/monitor/logs</td><td>Get monitor logs</td></tr>
 *   <tr><td>GET</td><td>/monitor/executions</td><td>Get executions</td></tr>
 *   <tr><td>GET</td><td>/monitor/closed_trades</td><td>Get closed trades</td></tr>
 *   <tr><td>POST</td><td>/webhook/trade</td><td>Trade closure webhook</td></tr>
 *   <tr><td>POST</td><td>/webhook/trailing</td><td>Trailing stop webhook</td></tr>
 *   <tr><td>GET</td><td>/webhook/health</td><td>Webhook health check</td></tr>
 *   <tr><td>GET</td><td>/health</td><td>Service health</td></tr>
 * </table>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Fail-Fast:</b> Validation failures throw {@link com.trading.easytradify.common.exception.TradingException}</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 *   <li><b>Thread-Safe:</b> All implementations must be thread-safe</li>
 * </ul>
 *
 * <h2>Error Handling</h2>
 * <p>
 * All errors are wrapped in {@link com.trading.easytradify.common.exception.TradingException}
 * with appropriate error codes from {@link com.trading.easytradify.common.exception.ErrorCodes}.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see DefaultPythonMonitorClient
 * @see com.trading.easytradify.common.exception.TradingException
 */
public interface PythonMonitorClient {

    // ============================================================
    // 1. MONITOR CONTROL
    // ============================================================

    /**
     * <h3>Start the Monitor</h3>
     * <p>
     * Starts the market monitoring service. This initiates symbol discovery,
     * scanning, and ranking processes.
     * </p>
     *
     * <h4>Expected Behavior</h4>
     * <ul>
     *   <li>If monitor is already running, this is a no-op</li>
     *   <li>If monitor is stopped, it starts the scanning loop</li>
     *   <li>Logs the start event</li>
     * </ul>
     *
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable or the start operation fails
     */
    void startMonitor();

    /**
     * <h3>Stop the Monitor</h3>
     * <p>
     * Stops the market monitoring service. This halts all scanning and
     * ranking processes.
     * </p>
     *
     * <h4>Expected Behavior</h4>
     * <ul>
     *   <li>If monitor is already stopped, this is a no-op</li>
     *   <li>If monitor is running, it stops gracefully</li>
     *   <li>Logs the stop event</li>
     * </ul>
     *
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable or the stop operation fails
     */
    void stopMonitor();

    /**
     * <h3>Force a Monitor Refresh</h3>
     * <p>
     * Triggers an immediate refresh of the monitor's data. This bypasses
     * the normal scan interval and forces a new scan immediately.
     * </p>
     *
     * <h4>Expected Behavior</h4>
     * <ul>
     *   <li>Clears the current cache</li>
     *   <li>Performs a full scan immediately</li>
     *   <li>Updates top symbols and rankings</li>
     * </ul>
     *
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable or the refresh operation fails
     */
    void refreshMonitor();

    // ============================================================
    // 2. MONITOR STATUS
    // ============================================================

    /**
     * <h3>Get Monitor Status</h3>
     * <p>
     * Retrieves the current status of the monitor including running state,
     * last scan time, and statistics.
     * </p>
     *
     * <h4>Response Details</h4>
     * <ul>
     *   <li>{@code running}: Whether the monitor is running</li>
     *   <li>{@code last_scan}: Timestamp of the last scan</li>
     *   <li>{@code total_symbols}: Number of symbols scanned</li>
     *   <li>{@code active_positions}: Number of open positions</li>
     *   <li>{@code stats}: Execution statistics</li>
     * </ul>
     *
     * @return {@link MonitorStatusResponse} containing the monitor status
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable
     */
    MonitorStatusResponse getStatus();

    /**
     * <h3>Get Top Symbols</h3>
     * <p>
     * Retrieves the top-ranked symbols based on confidence scores from
     * the latest scan.
     * </p>
     *
     * <h4>Ranking Criteria</h4>
     * <ul>
     *   <li>Confidence score (primary)</li>
     *   <li>Trend strength</li>
     *   <li>Volume profile</li>
     *   <li>Zone proximity</li>
     * </ul>
     *
     * @return List of {@link SymbolRankResponse} containing symbol rankings
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable
     */
    List<SymbolRankResponse> getTopSymbols();

    /**
     * <h3>Get Filtered Symbols</h3>
     * <p>
     * Retrieves the list of symbols that have been filtered out from
     * the top rankings due to low confidence or exclusion criteria.
     * </p>
     *
     * <h4>Filtering Criteria</h4>
     * <ul>
     *   <li>Low confidence score</li>
     *   <li>Permanently excluded symbols</li>
     *   <li>Long-term excluded symbols</li>
     *   <li>Market closed</li>
     * </ul>
     *
     * @return List of filtered symbol names
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable
     */
    List<String> getFilteredSymbols();

    /**
     * <h3>Get Monitor Logs</h3>
     * <p>
     * Retrieves the monitor execution logs with optional filtering by symbol.
     * </p>
     *
     * @param limit  Maximum number of log entries to return
     * @param symbol Optional symbol filter
     * @return Log entries as an Object (structure may vary)
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable
     */
    /** GET /monitor/gate-events on the Python monitor. */
    Object getGateEvents(int limit, String symbol, boolean vetoedOnly);

    /** GET /monitor/watchlist on the Python monitor. */
    Object getWatchlist(int limit);

    /** GET /monitor/threads on the Python monitor. */
    Object getThreads();

    Object getLogs(int limit, String symbol);

    /**
     * <h3>Get Executions</h3>
     * <p>
     * Retrieves the list of executed trades from the monitor's log.
     * </p>
     *
     * @param limit  Maximum number of executions to return
     * @param symbol Optional symbol filter
     * @return Execution entries as an Object (structure may vary)
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable
     */
    Object getExecutions(int limit, String symbol);

    /**
     * <h3>Get Closed Trades</h3>
     * <p>
     * Retrieves the list of closed trades from the monitor's log.
     * </p>
     *
     * @param limit  Maximum number of closed trades to return
     * @param symbol Optional symbol filter
     * @return Closed trade entries as an Object (structure may vary)
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable
     */
    Object getClosedTrades(int limit, String symbol);

    // ============================================================
    // 3. WEBHOOKS
    // ============================================================

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
     * @param request The webhook trade request
     * @return {@link WebhookResponse} indicating processing status
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If validation fails or processing fails
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
     *         If validation fails or processing fails
     */
    WebhookResponse handleWebhookTrailing(WebhookTrailingRequest request);

    /**
     * <h3>Get Webhook Health</h3>
     * <p>
     * Checks the health of the webhook service.
     * </p>
     *
     * @return Health status map containing:
     *         <ul>
     *           <li>{@code status}: "healthy" or "unhealthy"</li>
     *           <li>{@code open_positions}: Number of open positions</li>
     *           <li>{@code running}: Whether the monitor is running</li>
     *           <li>{@code webhook_closed_tickets}: Number of closed tickets</li>
     *           <li>{@code timestamp}: Current timestamp</li>
     *         </ul>
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable
     */
    Map<String, Object> getWebhookHealth();

    /**
     * <h3>Get Webhook Debug</h3>
     * <p>
     * Retrieves debug information from the webhook service.
     * </p>
     *
     * <h4>Debug Information</h4>
     * <ul>
     *   <li>Executor initialized status</li>
     *   <li>Executor running status</li>
     *   <li>Webhook closed tickets count</li>
     *   <li>Open positions count</li>
     *   <li>Webhook URLs</li>
     * </ul>
     *
     * @return Debug information map
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the Python service is unreachable
     */
    Map<String, Object> getWebhookDebug();

    // ============================================================
    // 4. HEALTH
    // ============================================================

    /**
     * <h3>Health Check</h3>
     * <p>
     * Performs a health check on the Python monitor service.
     * Verifies that the service is running and can accept requests.
     * </p>
     *
     * <h4>Health Check Results</h4>
     * <ul>
     *   <li>{@code status}: "operational" or "error"</li>
     *   <li>{@code running}: Whether the executor is running</li>
     *   <li>{@code port}: Service port</li>
     *   <li>{@code timestamp}: Check timestamp</li>
     * </ul>
     *
     * @return {@link HealthResponse} containing the service health status
     */
    HealthResponse healthCheck();
}