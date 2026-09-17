package com.trading.easytradify.execution.controller.api;

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

/**
 * <h1>Trade Execution API</h1>
 * <p>
 * REST API for executing and managing trades across multiple brokers.
 * This interface defines all endpoints with comprehensive Swagger/OpenAPI documentation.
 * </p>
 *
 * <h2>Authentication</h2>
 * <p>
 * All endpoints require a valid API key in the {@code X-API-Key} header.
 * </p>
 *
 * <h2>Base Path</h2>
 * <p>
 * All endpoints are prefixed with {@code /api/v1/execution}
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
@Tag(name = "Trade Execution", description = "Execute and manage trades across multiple brokers")
@RequestMapping("/api/v1/execution")
public interface ExecutionApi {

    // ============================================================
    // 1. TRADE EXECUTION
    // ============================================================

    @Operation(
            summary = "Execute a market trade",
            description = """
                    Executes a market trade with optional stop loss, take profit, and trailing stop.
                    
                    **Broker Selection:**
                    - `brokers: ["icmarkets"]` → Execute on IC Markets only
                    - `brokers: ["icmarkets", "vtmarkets"]` → Execute on multiple brokers
                    - `brokers: ["all"]` → Execute on ALL active brokers
                    - `brokers: null` or empty → Execute on default broker (IC Markets)
                    
                    **Note:** MT5 only supports one take profit per position. TP2 and TP3 are stored as references only.
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Trade executed successfully",
                    content = @Content(schema = @Schema(implementation = TradeExecutionResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "429", description = "Rate limit exceeded"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/trade")
    ResponseEntity<TradeExecutionResponse> executeTrade(
            @Parameter(description = "Trade execution request", required = true)
            @Valid @RequestBody ExecuteTradeRequest request
    );

    @Operation(
            summary = "Analyze a trade signal",
            description = """
                    Performs a comprehensive 17-component analysis of a trade signal without executing.
                    
                    **Analysis Components:**
                    - Trend analysis with divergence impact
                    - Technical indicators (RSI, MACD, Bollinger Bands, Stochastic)
                    - Supply/demand zones
                    - ICT/FVG concepts
                    - Wyckoff phase detection
                    - Volume profile and POC analysis
                    - Support and resistance levels
                    - Candlestick pattern recognition
                    - Entry timing with 5-star hedge fund rating
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Analysis completed successfully",
                    content = @Content(schema = @Schema(implementation = AnalyseTradeResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Symbol or broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/analyse")
    ResponseEntity<AnalyseTradeResponse> analyseTrade(
            @Parameter(description = "Trade analysis request", required = true)
            @Valid @RequestBody AnalyseTradeRequest request
    );

    @Operation(
            summary = "Calculate probability of hit",
            description = """
                    Calculates the statistical probability of hitting the take profit level before the stop loss level.
                    
                    **Interpretation:**
                    - > 65%: HIGH_PROBABILITY — Favorable setup
                    - 45% - 65%: MEDIUM_PROBABILITY — Average setup
                    - < 45%: LOW_PROBABILITY — Unfavorable setup
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Probability calculated successfully",
                    content = @Content(schema = @Schema(implementation = ProbabilityResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/probability")
    ResponseEntity<ProbabilityResponse> calculateProbability(
            @Parameter(description = "Probability calculation request", required = true)
            @Valid @RequestBody ProbabilityRequest request
    );

    // ============================================================
    // 2. POSITION MANAGEMENT
    // ============================================================

    @Operation(
            summary = "Close a position",
            description = "Closes an existing position identified by its ticket number."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Position closed successfully",
                    content = @Content(schema = @Schema(implementation = ClosePositionResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Position not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/position/close")
    ResponseEntity<ClosePositionResponse> closePosition(
            @Parameter(description = "Close position request", required = true)
            @Valid @RequestBody ClosePositionRequest request
    );

    @Operation(
            summary = "Partially close a position",
            description = "Partially closes a position by reducing its volume. The remaining position stays open."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Position partially closed successfully",
                    content = @Content(schema = @Schema(implementation = PartialCloseResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Position not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PutMapping("/position/partial-close")
    ResponseEntity<PartialCloseResponse> partialClosePosition(
            @Parameter(description = "Partial close request", required = true)
            @Valid @RequestBody PartialCloseRequest request
    );

    @Operation(
            summary = "Close all positions",
            description = "Closes all open positions. Optionally filters by symbol."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "All positions closed successfully",
                    content = @Content(schema = @Schema(implementation = CloseAllResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/positions/close/all")
    ResponseEntity<CloseAllResponse> closeAllPositions(
            @Parameter(description = "Close all positions request", required = true)
            @Valid @RequestBody CloseAllPositionsRequest request
    );

    @Operation(
            summary = "Get all positions",
            description = "Retrieves all positions for the specified broker."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Positions retrieved successfully",
                    content = @Content(schema = @Schema(implementation = PositionsResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/positions")
    ResponseEntity<PositionsResponse> getPositions(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Symbol filter (optional)")
            @RequestParam(required = false) String symbol,

            @Parameter(description = "Magic number filter (optional)")
            @RequestParam(required = false) Integer magic
    );

    @Operation(
            summary = "Get open positions",
            description = "Retrieves only open (non-closed) positions for the specified broker."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Open positions retrieved successfully",
                    content = @Content(schema = @Schema(implementation = PositionsResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/positions/open")
    ResponseEntity<PositionsResponse> getOpenPositions(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Symbol filter (optional)")
            @RequestParam(required = false) String symbol,

            @Parameter(description = "Magic number filter (optional)")
            @RequestParam(required = false) Integer magic
    );

    @Operation(
            summary = "Get position by ticket",
            description = "Retrieves detailed information about a single position by its ticket number."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Position retrieved successfully",
                    content = @Content(schema = @Schema(implementation = PositionResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Position not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/position/{ticket}")
    ResponseEntity<PositionResponse> getPosition(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Position ticket number", required = true)
            @PathVariable int ticket
    );

    // ============================================================
    // 3. STOP LOSS & TAKE PROFIT
    // ============================================================

    @Operation(
            summary = "Modify stop loss",
            description = "Modifies the stop loss price of an existing position."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Stop loss modified successfully",
                    content = @Content(schema = @Schema(implementation = ModifyStopLossResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Position not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PutMapping("/position/stop-loss")
    ResponseEntity<ModifyStopLossResponse> modifyStopLoss(
            @Parameter(description = "Modify stop loss request", required = true)
            @Valid @RequestBody ModifyStopLossRequest request
    );

    @Operation(
            summary = "Modify take profit",
            description = "Modifies the take profit price of an existing position."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Take profit modified successfully",
                    content = @Content(schema = @Schema(implementation = ModifyTakeProfitResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Position not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PutMapping("/position/take-profit")
    ResponseEntity<ModifyTakeProfitResponse> modifyTakeProfit(
            @Parameter(description = "Modify take profit request", required = true)
            @Valid @RequestBody ModifyTakeProfitRequest request
    );

    // ============================================================
    // 4. TRAILING STOP
    // ============================================================

    @Operation(
            summary = "Enable trailing stop",
            description = """
                    Enables a trailing stop for the specified position.
                    
                    **Behavior:**
                    - Activates after +10 pips profit (breakeven)
                    - Then trails the price by the specified number of pips
                    - Automatically adjusts stop loss as price moves in favor
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Trailing stop enabled successfully",
                    content = @Content(schema = @Schema(implementation = TrailingStopResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Position not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PutMapping("/position/trailing/enable")
    ResponseEntity<TrailingStopResponse> enableTrailingStop(
            @Parameter(description = "Enable trailing stop request", required = true)
            @Valid @RequestBody TrailingStopRequest request
    );

    @Operation(
            summary = "Disable trailing stop",
            description = "Disables the trailing stop for the specified position. The stop loss remains at its current level."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Trailing stop disabled successfully",
                    content = @Content(schema = @Schema(implementation = TrailingStopResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Position not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PutMapping("/position/trailing/disable")
    ResponseEntity<TrailingStopResponse> disableTrailingStop(
            @Parameter(description = "Disable trailing stop request", required = true)
            @Valid @RequestBody DisableTrailingRequest request
    );

    @Operation(
            summary = "Update trailing stop",
            description = "Updates the trailing stop step size for the specified position."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Trailing stop updated successfully",
                    content = @Content(schema = @Schema(implementation = TrailingStopResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Position not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PutMapping("/position/trailing/update")
    ResponseEntity<TrailingStopResponse> updateTrailingStop(
            @Parameter(description = "Update trailing stop request", required = true)
            @Valid @RequestBody TrailingStopRequest request
    );

    @Operation(
            summary = "Get trailing stop status",
            description = "Retrieves the trailing stop status for all positions on the specified broker."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Trailing status retrieved successfully",
                    content = @Content(schema = @Schema(implementation = TrailingStatusResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/trailing/status")
    ResponseEntity<TrailingStatusResponse> getTrailingStatus(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker
    );

    @Operation(
            summary = "Get trailing stop statistics",
            description = "Retrieves trailing stop statistics for the specified broker."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Trailing statistics retrieved successfully",
                    content = @Content(schema = @Schema(implementation = TrailingStatsResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/trailing/stats")
    ResponseEntity<TrailingStatsResponse> getTrailingStats(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker
    );

    // ============================================================
    // 5. ACCOUNT & SYMBOL
    // ============================================================

    @Operation(
            summary = "Get account information",
            description = "Retrieves account information for the specified broker."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Account info retrieved successfully",
                    content = @Content(schema = @Schema(implementation = AccountResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/account")
    ResponseEntity<AccountResponse> getAccount(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker
    );

    @Operation(
            summary = "Get symbol information",
            description = "Retrieves detailed information about a specific trading symbol."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Symbol info retrieved successfully",
                    content = @Content(schema = @Schema(implementation = SymbolInfoResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Symbol or broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/symbol/{symbol}")
    ResponseEntity<SymbolInfoResponse> getSymbolInfo(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Trading symbol (e.g., EURUSD, XAUUSD)", required = true)
            @PathVariable String symbol
    );

    @Operation(
            summary = "Get all symbols",
            description = "Retrieves information for all available trading symbols."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Symbols retrieved successfully",
                    content = @Content(schema = @Schema(implementation = SymbolsResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/symbols")
    ResponseEntity<SymbolsResponse> getSymbols(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker
    );

    // ============================================================
    // 6. MARKET CONDITIONS
    // ============================================================

    @Operation(
            summary = "Check market status",
            description = "Checks whether the market is closed for the specified symbol."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Market status retrieved successfully",
                    content = @Content(schema = @Schema(implementation = MarketStatusResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Symbol not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/market/status/{symbol}")
    ResponseEntity<MarketStatusResponse> getMarketStatus(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Trading symbol", required = true)
            @PathVariable String symbol
    );

    @Operation(
            summary = "Get market volatility",
            description = """
                    Calculates the market volatility for the specified symbol.
                    
                    **Interpretation:**
                    - < 0.5%: Low Volatility
                    - 0.5% - 1.5%: Normal Volatility
                    - > 1.5%: High Volatility
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Volatility retrieved successfully",
                    content = @Content(schema = @Schema(implementation = VolatilityResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Symbol not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/market/volatility/{symbol}")
    ResponseEntity<VolatilityResponse> getMarketVolatility(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Trading symbol", required = true)
            @PathVariable String symbol,

            @Parameter(description = "Lookback period in bars (default: 20)")
            @RequestParam(defaultValue = "20") int lookback
    );

    @Operation(
            summary = "Get market spread",
            description = """
                    Checks the current spread for the specified symbol.
                    
                    **Interpretation:**
                    - <= 8 pips: Excellent
                    - 8-15 pips: Normal
                    - > 15 pips: High
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Spread retrieved successfully",
                    content = @Content(schema = @Schema(implementation = SpreadResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Symbol not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/market/spread/{symbol}")
    ResponseEntity<SpreadResponse> getMarketSpread(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Trading symbol", required = true)
            @PathVariable String symbol,

            @Parameter(description = "Maximum allowed spread in pips (default: 30)")
            @RequestParam(defaultValue = "30") double maxSpread
    );

    @Operation(
            summary = "Get full market conditions",
            description = """
                    Retrieves comprehensive market conditions including spread, ATR, trend strength, and volatility.
                    Also provides trading recommendations.
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Market conditions retrieved successfully",
                    content = @Content(schema = @Schema(implementation = MarketConditionsResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Symbol not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/market/conditions/{symbol}")
    ResponseEntity<MarketConditionsResponse> getMarketConditions(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Trading symbol", required = true)
            @PathVariable String symbol
    );

    // ============================================================
    // 7. MT5 CONNECTION
    // ============================================================

    @Operation(
            summary = "Connect to MT5",
            description = "Establishes a connection to the MetaTrader 5 terminal for the specified broker."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "MT5 connected successfully",
                    content = @Content(schema = @Schema(implementation = Mt5ConnectionResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/mt5/connect")
    ResponseEntity<Mt5ConnectionResponse> connectMt5(
            @Parameter(description = "Broker name (required)")
            @RequestParam String broker,

            @Parameter(description = "MT5 connection request", required = true)
            @Valid @RequestBody Mt5ConnectRequest request
    );

    @Operation(
            summary = "Disconnect from MT5",
            description = "Disconnects from the MetaTrader 5 terminal for the specified broker."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "MT5 disconnected successfully",
                    content = @Content(schema = @Schema(implementation = SingleBrokerResult.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/mt5/disconnect")
    ResponseEntity<SingleBrokerResult> disconnectMt5(
            @Parameter(description = "Broker name (required)")
            @RequestParam String broker
    );

    // ============================================================
    // 8. HISTORY & CALCULATIONS
    // ============================================================

    @Operation(
            summary = "Get trade history",
            description = "Retrieves trade history with optional filters and date range."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Trade history retrieved successfully",
                    content = @Content(schema = @Schema(implementation = TradeHistoryResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @GetMapping("/trades/history")
    ResponseEntity<TradeHistoryResponse> getTradeHistory(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Trade history request", required = true)
            @Valid @RequestBody TradeHistoryRequest request
    );

    @Operation(
            summary = "Calculate lot size",
            description = "Calculates the optimal lot size based on trade size and risk percentage."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Lot calculated successfully",
                    content = @Content(schema = @Schema(implementation = LotCalculationResponse.class))),
            @ApiResponse(responseCode = "400", description = "Invalid request parameters"),
            @ApiResponse(responseCode = "401", description = "Missing or invalid API key"),
            @ApiResponse(responseCode = "404", description = "Broker not found"),
            @ApiResponse(responseCode = "500", description = "Internal server error")
    })
    @PostMapping("/calculate-lot")
    ResponseEntity<LotCalculationResponse> calculateLot(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker,

            @Parameter(description = "Lot calculation request", required = true)
            @Valid @RequestBody LotCalculationRequest request
    );

    // ============================================================
    // 9. HEALTH
    // ============================================================

    @Operation(
            summary = "Health check",
            description = "Performs a health check on the Python execution service."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Service is healthy",
                    content = @Content(schema = @Schema(implementation = HealthResponse.class))),
            @ApiResponse(responseCode = "500", description = "Service is unhealthy")
    })
    @GetMapping("/health")
    ResponseEntity<HealthResponse> healthCheck(
            @Parameter(description = "Broker name (optional, uses default if not provided)")
            @RequestParam(required = false) String broker
    );
}