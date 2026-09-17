package com.trading.easytradify.monitor.controllers;

import com.trading.easytradify.monitor.models.MonitorStatusResponse;
import com.trading.easytradify.monitor.models.SymbolRankResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * <h1>Monitor API</h1>
 * <p>
 * REST API for market monitoring and symbol discovery.
 * This interface defines all endpoints with comprehensive Swagger/OpenAPI documentation.
 * </p>
 *
 * <h2>Base Path</h2>
 * <p>
 * All endpoints are prefixed with {@code /api/v1/monitor}
 * </p>
 *
 * <h2>Authentication</h2>
 * <p>
 * All endpoints require a valid API key in the {@code X-API-Key} header.
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
@Tag(name = "Monitor", description = "Market monitoring and symbol discovery")
@RequestMapping("/api/v1/monitor")
public interface MonitorApi {

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
     * @return Empty response with 200 OK on success
     */
    @Operation(
            summary = "Start the monitor",
            description = """
                    Starts the market monitoring service.
                    
                    **What happens:**
                    - Symbol discovery is initiated
                    - Scanning loop starts
                    - Ranking process begins
                    
                    **If monitor is already running:**
                    - This is a no-op (idempotent)
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Monitor started successfully"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/start")
    ResponseEntity<Void> startMonitor();

    /**
     * <h3>Stop the Monitor</h3>
     * <p>
     * Stops the market monitoring service. This halts all scanning and
     * ranking processes.
     * </p>
     *
     * @return Empty response with 200 OK on success
     */
    @Operation(
            summary = "Stop the monitor",
            description = """
                    Stops the market monitoring service.
                    
                    **What happens:**
                    - Scanning loop stops
                    - Ranking process halts
                    - All active scans are cancelled
                    
                    **If monitor is already stopped:**
                    - This is a no-op (idempotent)
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Monitor stopped successfully"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/stop")
    ResponseEntity<Void> stopMonitor();

    /**
     * <h3>Force a Monitor Refresh</h3>
     * <p>
     * Triggers an immediate refresh of the monitor's data. This bypasses
     * the normal scan interval and forces a new scan immediately.
     * </p>
     *
     * @return Empty response with 200 OK on success
     */
    @Operation(
            summary = "Force a monitor refresh",
            description = """
                    Triggers an immediate refresh of the monitor's data.
                    
                    **What happens:**
                    - Current cache is cleared
                    - Full scan is performed immediately
                    - Top symbols and rankings are updated
                    - Bypasses normal scan interval
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Monitor refreshed successfully"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/refresh")
    ResponseEntity<Void> refreshMonitor();

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
     * @return {@link MonitorStatusResponse} containing the monitor status
     */
    @Operation(
            summary = "Get monitor status",
            description = """
                    Retrieves the current status of the monitor.
                    
                    **Response includes:**
                    - Running state
                    - Last scan timestamp
                    - Total symbols scanned
                    - Active positions count
                    - Execution statistics
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Status retrieved successfully",
                    content = @Content(schema = @Schema(implementation = MonitorStatusResponse.class))),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/status")
    ResponseEntity<MonitorStatusResponse> getStatus();

    /**
     * <h3>Get Top Symbols</h3>
     * <p>
     * Retrieves the top-ranked symbols based on confidence scores from
     * the latest scan.
     * </p>
     *
     * @return List of {@link SymbolRankResponse} containing symbol rankings
     */
    @Operation(
            summary = "Get top symbols",
            description = """
                    Retrieves the top-ranked symbols.
                    
                    **Ranking Criteria:**
                    - Confidence score (primary)
                    - Trend strength
                    - Volume profile
                    - Zone proximity
                    - Current position status
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Top symbols retrieved successfully",
                    content = @Content(schema = @Schema(implementation = SymbolRankResponse.class))),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/top-symbols")
    ResponseEntity<List<SymbolRankResponse>> getTopSymbols();

    /**
     * <h3>Get Filtered Symbols</h3>
     * <p>
     * Retrieves the list of symbols that have been filtered out from
     * the top rankings due to low confidence or exclusion criteria.
     * </p>
     *
     * @return List of filtered symbol names
     */
    @Operation(
            summary = "Get filtered symbols",
            description = """
                    Retrieves symbols that were filtered out.
                    
                    **Filtering Criteria:**
                    - Low confidence score
                    - Permanently excluded
                    - Long-term excluded
                    - Market closed
                    - Insufficient data
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Filtered symbols retrieved successfully",
                    content = @Content(schema = @Schema(implementation = List.class))),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/filtered-symbols")
    ResponseEntity<List<String>> getFilteredSymbols();

    /**
     * <h3>Get Monitor Logs</h3>
     * <p>
     * Retrieves the monitor execution logs with optional filtering by symbol.
     * </p>
     *
     * @param limit  Maximum number of log entries to return
     * @param symbol Optional symbol filter
     * @return Log entries
     */
    @Operation(
            summary = "Get monitor logs",
            description = "Retrieves the monitor execution logs with optional filtering by symbol."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Logs retrieved successfully"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/logs")
    ResponseEntity<Object> getLogs(
            @Parameter(description = "Maximum number of log entries to return", example = "100")
            @RequestParam(defaultValue = "100") int limit,

            @Parameter(description = "Optional symbol filter", example = "EURUSD")
            @RequestParam(required = false) String symbol
    );

    /**
     * Recent veto/gate decisions, newest first.
     *
     * <p>
     * The fastest answer to "why is nothing trading?". Each entry is one check
     * as the decision path actually evaluated it — a check missing from a
     * decision did not run (the engine short-circuits on the first veto) and is
     * not reported as a pass, because those are different facts.
     * </p>
     *
     * <p>
     * The response also carries a per-gate tally over the last ten minutes,
     * which is what makes a dominant blocker visible; a flat feed hides it as
     * soon as it is longer than a screen.
     * </p>
     */
    @Operation(summary = "Recent gate/veto decisions",
            description = "Chronological veto-engine decisions with a per-gate summary")
    @GetMapping("/gate-events")
    ResponseEntity<Object> getGateEvents(
            @Parameter(description = "Maximum events to return", example = "100")
            @RequestParam(defaultValue = "100") int limit,

            @Parameter(description = "Optional symbol filter", example = "EURUSD")
            @RequestParam(required = false) String symbol,

            @Parameter(description = "Return only checks that blocked", example = "false")
            @RequestParam(name = "vetoed_only", defaultValue = "false") boolean vetoedOnly
    );

    /**
     * Live quotes for the symbols currently being tracked.
     *
     * <p>
     * Read straight from MT5 on each call. A symbol MT5 will not quote is
     * omitted rather than returned with zeros — a 0.00000 bid renders as a
     * real price and is worse than an absent row.
     * </p>
     */
    @Operation(summary = "Tracked symbol quotes",
            description = "Bid/ask, session change and a short close series per tracked symbol")
    @GetMapping("/watchlist")
    ResponseEntity<Object> getWatchlist(
            @Parameter(description = "Maximum symbols to return", example = "24")
            @RequestParam(defaultValue = "24") int limit
    );

    /**
     * The monitor's worker pools, as configured and as running.
     *
     * <p>
     * Reports capacity, live thread counts and queue depth. It deliberately
     * does not claim which symbol each worker holds — nothing records that
     * mapping, and inventing it would be fabrication dressed as telemetry.
     * </p>
     */
    @Operation(summary = "Worker pool state",
            description = "Filter/Monitor pool capacity, live threads and queue depth")
    @GetMapping("/threads")
    ResponseEntity<Object> getThreads();


    /**
     * <h3>Get Executions</h3>
     * <p>
     * Retrieves the list of executed trades from the monitor's log.
     * </p>
     *
     * @param limit  Maximum number of executions to return
     * @param symbol Optional symbol filter
     * @return Execution entries
     */
    @Operation(
            summary = "Get executions",
            description = "Retrieves the list of executed trades from the monitor's log."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Executions retrieved successfully"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/executions")
    ResponseEntity<Object> getExecutions(
            @Parameter(description = "Maximum number of executions to return", example = "100")
            @RequestParam(defaultValue = "100") int limit,

            @Parameter(description = "Optional symbol filter", example = "EURUSD")
            @RequestParam(required = false) String symbol
    );

    /**
     * <h3>Get Closed Trades</h3>
     * <p>
     * Retrieves the list of closed trades from the monitor's log.
     * </p>
     *
     * @param limit  Maximum number of closed trades to return
     * @param symbol Optional symbol filter
     * @return Closed trade entries
     */
    @Operation(
            summary = "Get closed trades",
            description = "Retrieves the list of closed trades from the monitor's log."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Closed trades retrieved successfully"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/closed-trades")
    ResponseEntity<Object> getClosedTrades(
            @Parameter(description = "Maximum number of closed trades to return", example = "100")
            @RequestParam(defaultValue = "100") int limit,

            @Parameter(description = "Optional symbol filter", example = "EURUSD")
            @RequestParam(required = false) String symbol
    );


}