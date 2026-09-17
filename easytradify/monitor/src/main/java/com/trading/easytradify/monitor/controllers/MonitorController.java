package com.trading.easytradify.monitor.controllers;

import com.trading.easytradify.monitor.models.MonitorStatusResponse;
import com.trading.easytradify.monitor.models.SymbolRankResponse;
import com.trading.easytradify.monitor.services.MonitorService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * <h1>Monitor Controller</h1>
 * <p>
 * Concrete implementation of the {@link MonitorApi} interface.
 * This controller handles all REST endpoints for market monitoring
 * and symbol discovery.
 * </p>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Thin Controller:</b> All business logic is delegated to the service layer</li>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * <h2>Error Handling</h2>
 * <p>
 * This controller relies on the {@code GlobalExceptionHandler} for consistent
 * error responses. All exceptions propagate through the call stack without
 * being caught locally.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see MonitorApi
 * @see MonitorService
 */
@RestController
@RequiredArgsConstructor
@Slf4j
public class MonitorController implements MonitorApi {

    private final MonitorService monitorService;

    // ============================================================
    // 1. MONITOR CONTROL
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<Void> startMonitor() {
        log.info("[Monitor] Received start request");
        monitorService.startMonitor();
        return ResponseEntity.ok().build();
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<Void> stopMonitor() {
        log.info("[Monitor] Received stop request");
        monitorService.stopMonitor();
        return ResponseEntity.ok().build();
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<Void> refreshMonitor() {
        log.info("[Monitor] Received refresh request");
        monitorService.refreshMonitor();
        return ResponseEntity.ok().build();
    }

    // ============================================================
    // 2. MONITOR STATUS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<MonitorStatusResponse> getStatus() {
        log.debug("[Monitor] Received status request");
        var response = monitorService.getStatus();
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<List<SymbolRankResponse>> getTopSymbols() {
        log.debug("[Monitor] Received top symbols request");
        var response = monitorService.getTopSymbols();
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<List<String>> getFilteredSymbols() {
        log.debug("[Monitor] Received filtered symbols request");
        var response = monitorService.getFilteredSymbols();
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<Object> getGateEvents(int limit, String symbol, boolean vetoedOnly) {
        log.debug("[Monitor] Gate events: limit={}, symbol={}, vetoedOnly={}", limit, symbol, vetoedOnly);
        return ResponseEntity.ok(monitorService.getGateEvents(limit, symbol, vetoedOnly));
    }

    @Override
    public ResponseEntity<Object> getWatchlist(int limit) {
        log.debug("[Monitor] Watchlist: limit={}", limit);
        return ResponseEntity.ok(monitorService.getWatchlist(limit));
    }

    @Override
    public ResponseEntity<Object> getThreads() {
        log.debug("[Monitor] Thread pool state");
        return ResponseEntity.ok(monitorService.getThreads());
    }

    @Override
    public ResponseEntity<Object> getLogs(int limit, String symbol) {
        log.debug("[Monitor] Received logs request: limit={}, symbol={}", limit, symbol);
        var response = monitorService.getLogs(limit, symbol);
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<Object> getExecutions(int limit, String symbol) {
        log.debug("[Monitor] Received executions request: limit={}, symbol={}", limit, symbol);
        var response = monitorService.getExecutions(limit, symbol);
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<Object> getClosedTrades(int limit, String symbol) {
        log.debug("[Monitor] Received closed trades request: limit={}, symbol={}", limit, symbol);
        var response = monitorService.getClosedTrades(limit, symbol);
        return ResponseEntity.ok(response);
    }

}