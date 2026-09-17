package com.trading.easytradify.monitor.services;

import com.trading.easytradify.monitor.models.*;

import java.util.List;

/**
 * <h1>Monitor Service</h1>
 * <p>
 * Service for monitoring market conditions, discovering symbols,
 * and ranking them by confidence. Also handles webhook processing
 * for trade closures and trailing stops.
 * </p>
 *
 * <h2>Architecture Overview</h2>
 * <p>
 * The service follows the <b>Orchestration Pattern</b> where each method
 * represents a distinct monitoring operation. All operations are stateless
 * and thread-safe, making them suitable for concurrent execution.
 * </p>
 *
 * <h2>Key Features</h2>
 * <ul>
 *   <li><b>Symbol Discovery:</b> Scans all available symbols</li>
 *   <li><b>Ranking:</b> Ranks symbols by confidence score</li>
 *   <li><b>Filtering:</b> Filters out low-confidence or excluded symbols</li>
 *   <li><b>Reanalysis:</b> Periodic re-analysis of top symbols</li>
 *   <li><b>Webhook Support:</b> Handles trade closures and trailing stops</li>
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
 * @see MonitorServiceImpl
 * @see com.trading.easytradify.common.exception.TradingException
 */
public interface MonitorService {

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
    /** Recent veto/gate decisions plus a per-gate summary. */
    Object getGateEvents(int limit, String symbol, boolean vetoedOnly);

    /** Live quotes for the tracked symbols. */
    Object getWatchlist(int limit);

    /** Worker pool capacity, live threads and queue depth. */
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
     * <h4>Validation Rules</h4>
     * <ul>
     *   <li>Symbol cannot be {@code null} or empty</li>
     *   <li>Ticket must be positive</li>
     *   <li>Price values must be positive</li>
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

    // ============================================================
    // 4. HEALTH
    // ============================================================

    /**
     * <h3>Health Check</h3>
     * <p>
     * Performs a health check on the monitor service.
     * </p>
     *
     * @return {@link HealthResponse} containing the service health status
     */
    HealthResponse healthCheck();

}