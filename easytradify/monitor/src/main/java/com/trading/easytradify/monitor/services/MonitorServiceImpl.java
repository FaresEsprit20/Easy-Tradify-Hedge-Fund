package com.trading.easytradify.monitor.services;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.monitor.client.PythonMonitorClient;
import com.trading.easytradify.monitor.models.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * <h1>Monitor Service Implementation</h1>
 * <p>
 * Default implementation of {@link MonitorService}.
 * Delegates all operations to the {@link PythonMonitorClient}.
 * </p>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Thin Service:</b> All business logic is delegated to the client</li>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Declarative Validation:</b> Input validation is explicit and throws domain exceptions</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * <h2>Error Handling Strategy</h2>
 * <ol>
 *   <li>Validate inputs → throws {@link TradingException} if invalid</li>
 *   <li>Delegate to client → returns a response object</li>
 *   <li>Check response success flag → throws {@link TradingException} if {@code false}</li>
 *   <li>Return successful response to caller</li>
 * </ol>
 * <p>
 * All exceptions are propagated to {@code GlobalExceptionHandler}
 * for consistent error response formatting.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see MonitorService
 * @see PythonMonitorClient
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class MonitorServiceImpl implements MonitorService {

    private final PythonMonitorClient monitorClient;

    // ============================================================
    // VALIDATION HELPERS
    // ============================================================

    /**
     * Validates that a symbol is not {@code null} or empty.
     *
     * @param symbol The symbol to validate
     * @throws TradingException If the symbol is {@code null} or empty
     */
    private void validateSymbol(String symbol) {
        if (!StringUtils.hasText(symbol)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.TRADE_INVALID_SYMBOL)
                    .message("Symbol cannot be null or empty")
                    .build();
        }
    }

    /**
     * Validates that a ticket number is positive.
     *
     * @param ticket The ticket number to validate
     * @throws TradingException If the ticket number is not positive
     */
    private void validateTicket(Integer ticket) {
        if (ticket == null || ticket <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.POSITION_NOT_FOUND)
                    .message("Invalid ticket number: " + ticket)
                    .build();
        }
    }

    /**
     * Validates that a webhook trade request is complete and valid.
     *
     * @param request The webhook trade request to validate
     * @throws TradingException If the request is invalid
     */
    private void validateWebhookTrade(WebhookTradeRequest request) {
        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Webhook trade request cannot be null")
                    .build();
        }

        validateSymbol(request.symbol());
        validateTicket(request.ticket());
    }

    /**
     * Validates that a webhook trailing request is complete and valid.
     *
     * @param request The webhook trailing request to validate
     * @throws TradingException If the request is invalid
     */
    private void validateWebhookTrailing(WebhookTrailingRequest request) {
        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Webhook trailing request cannot be null")
                    .build();
        }

        validateTicket(request.ticket());
    }

    // ============================================================
    // SERVICE METHODS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public void startMonitor() {
        log.info("[Monitor] Starting monitor");
        monitorClient.startMonitor();
        log.info("[Monitor] Monitor started successfully");
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public void stopMonitor() {
        log.info("[Monitor] Stopping monitor");
        monitorClient.stopMonitor();
        log.info("[Monitor] Monitor stopped successfully");
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public void refreshMonitor() {
        log.info("[Monitor] Refreshing monitor");
        monitorClient.refreshMonitor();
        log.info("[Monitor] Monitor refreshed successfully");
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public MonitorStatusResponse getStatus() {
        log.debug("[Monitor] Getting status");
        return monitorClient.getStatus();
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public List<SymbolRankResponse> getTopSymbols() {
        log.debug("[Monitor] Getting top symbols");
        return monitorClient.getTopSymbols();
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public List<String> getFilteredSymbols() {
        log.debug("[Monitor] Getting filtered symbols");
        return monitorClient.getFilteredSymbols();
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public Object getGateEvents(int limit, String symbol, boolean vetoedOnly) {
        log.debug("[Monitor] Getting gate events");
        return monitorClient.getGateEvents(limit, symbol, vetoedOnly);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public Object getWatchlist(int limit) {
        log.debug("[Monitor] Getting watchlist");
        return monitorClient.getWatchlist(limit);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public Object getThreads() {
        log.debug("[Monitor] Getting thread pool state");
        return monitorClient.getThreads();
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public Object getLogs(int limit, String symbol) {
        log.debug("[Monitor] Getting logs");
        return monitorClient.getLogs(limit, symbol);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public Object getExecutions(int limit, String symbol) {
        log.debug("[Monitor] Getting executions");
        return monitorClient.getExecutions(limit, symbol);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public Object getClosedTrades(int limit, String symbol) {
        log.debug("[Monitor] Getting closed trades");
        return monitorClient.getClosedTrades(limit, symbol);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public WebhookResponse handleWebhookTrade(WebhookTradeRequest request) {
        log.info("[Monitor] Handling webhook trade: {} (Ticket: {})", request.symbol(), request.ticket());

        // 1. Validate input
        validateWebhookTrade(request);

        // 2. Delegate to client
        var response = monitorClient.handleWebhookTrade(request);

        // 3. Check response success
        if (!"success".equals(response.status())) {
            log.error("[Monitor] Webhook trade failed: {}", response.message());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.WEBHOOK_PROCESSING_FAILED)
                    .message("Webhook trade processing failed: " + response.message())
                    .ticket(request.ticket())
                    .build();
        }

        log.info("[Monitor] Webhook trade processed successfully: Ticket {}", request.ticket());
        return response;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public WebhookResponse handleWebhookTrailing(WebhookTrailingRequest request) {
        log.info("[Monitor] Handling webhook trailing: Ticket {}", request.ticket());

        // 1. Validate input
        validateWebhookTrailing(request);

        // 2. Delegate to client
        var response = monitorClient.handleWebhookTrailing(request);

        // 3. Check response success
        if (!"success".equals(response.status())) {
            log.error("[Monitor] Webhook trailing failed: {}", response.message());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.WEBHOOK_PROCESSING_FAILED)
                    .message("Webhook trailing processing failed: " + response.message())
                    .ticket(request.ticket())
                    .build();
        }

        log.info("[Monitor] Webhook trailing processed successfully: Ticket {}", request.ticket());
        return response;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public HealthResponse healthCheck() {
        log.debug("[Monitor] Health check");
        return monitorClient.healthCheck();
    }
}