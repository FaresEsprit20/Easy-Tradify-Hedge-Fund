package com.trading.easytradify.execution.services;


import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.execution.models.*;

/**
 * Service interface for trade execution operations.
 * This is the primary abstraction for all trading operations.
 */
public interface TradeExecutionService {

    // ============================================================
    // 1. TRADE EXECUTION
    // ============================================================

    /**
     * Execute a trade on one or multiple brokers.
     *
     * @param request The trade execution request
     * @return Response containing results from all executed brokers
     * @throws TradingException if validation fails or no valid brokers found
     */
    TradeExecutionResponse executeTrade(ExecuteTradeRequest request);

    /**
     * Analyze a trade signal without executing.
     *
     * @param request The analysis request
     * @return Analysis results
     * @throws TradingException if validation fails
     */
    AnalyseTradeResponse analyseTrade(AnalyseTradeRequest request);

    /**
     * Calculate probability of hitting take profit.
     *
     * @param request The probability calculation request
     * @return Probability calculation result
     * @throws TradingException if validation fails
     */
    ProbabilityResponse calculateProbability(ProbabilityRequest request);

    // ============================================================
    // 2. POSITION MANAGEMENT
    // ============================================================

    /**
     * Close a position on one or multiple brokers.
     *
     * @param request The close position request
     * @return Response containing close results
     * @throws TradingException if position not found or close fails
     */
    ClosePositionResponse closePosition(ClosePositionRequest request);

    /**
     * Partially close a position on one or multiple brokers.
     *
     * @param request The partial close request
     * @return Response containing partial close results
     * @throws TradingException if validation fails or position not found
     */
    PartialCloseResponse partialClosePosition(PartialCloseRequest request);

    /**
     * Close all positions on one or multiple brokers.
     *
     * @param request The close all positions request
     * @return Response containing results
     * @throws TradingException if operation fails
     */
    CloseAllResponse closeAllPositions(CloseAllPositionsRequest request);

    /**
     * Get all positions from one or multiple brokers.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param symbol The symbol filter (optional)
     * @param magic The magic number filter (optional)
     * @return Positions response
     * @throws TradingException if broker not found
     */
    PositionsResponse getPositions(String brokerName, String symbol, Integer magic);

    /**
     * Get all open positions from one or multiple brokers.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param symbol The symbol filter (optional)
     * @param magic The magic number filter (optional)
     * @return Open positions response
     * @throws TradingException if broker not found
     */
    PositionsResponse getOpenPositions(String brokerName, String symbol, Integer magic);

    /**
     * Get a single position by ticket.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param ticket The position ticket
     * @return Position response
     * @throws TradingException if position not found
     */
    PositionResponse getPosition(String brokerName, int ticket);

    // ============================================================
    // 3. STOP LOSS & TAKE PROFIT
    // ============================================================

    /**
     * Modify stop loss on one or multiple brokers.
     *
     * @param request The modify SL request
     * @return Response containing results
     * @throws TradingException if position not found or modification fails
     */
    ModifyStopLossResponse modifyStopLoss(ModifyStopLossRequest request);

    /**
     * Modify take profit on one or multiple brokers.
     *
     * @param request The modify TP request
     * @return Response containing results
     * @throws TradingException if position not found or modification fails
     */
    ModifyTakeProfitResponse modifyTakeProfit(ModifyTakeProfitRequest request);

    // ============================================================
    // 4. TRAILING STOP
    // ============================================================

    /**
     * Enable trailing stop on one or multiple brokers.
     *
     * @param request The enable trailing request
     * @return Response containing results
     * @throws TradingException if position not found
     */
    TrailingStopResponse enableTrailingStop(TrailingStopRequest request);

    /**
     * Disable trailing stop on one or multiple brokers.
     *
     * @param request The disable trailing request
     * @return Response containing results
     * @throws TradingException if position not found
     */
    TrailingStopResponse disableTrailingStop(DisableTrailingRequest request);

    /**
     * Update trailing stop on one or multiple brokers.
     *
     * @param request The update trailing request
     * @return Response containing results
     * @throws TradingException if position not found
     */
    TrailingStopResponse updateTrailingStop(TrailingStopRequest request);

    /**
     * Get trailing stop status.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @return Trailing status response
     * @throws TradingException if broker not found
     */
    TrailingStatusResponse getTrailingStatus(String brokerName);

    /**
     * Get trailing stop statistics.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @return Trailing statistics response
     * @throws TradingException if broker not found
     */
    TrailingStatsResponse getTrailingStats(String brokerName);

    // ============================================================
    // 5. ACCOUNT & SYMBOL
    // ============================================================

    /**
     * Get account information.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @return Account response
     * @throws TradingException if broker not found
     */
    AccountResponse getAccount(String brokerName);

    /**
     * Get symbol information.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param symbol The symbol name
     * @return Symbol info response
     * @throws TradingException if symbol not found
     */
    SymbolInfoResponse getSymbolInfo(String brokerName, String symbol);

    /**
     * Get all symbols.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @return Symbols response
     * @throws TradingException if broker not found
     */
    SymbolsResponse getSymbols(String brokerName);

    // ============================================================
    // 6. MARKET CONDITIONS
    // ============================================================

    /**
     * Get market status (open/closed).
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param symbol The symbol
     * @return Market status response
     * @throws TradingException if symbol not found
     */
    MarketStatusResponse getMarketStatus(String brokerName, String symbol);

    /**
     * Get market volatility.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param symbol The symbol
     * @param lookback The lookback period in bars
     * @return Volatility response
     * @throws TradingException if symbol not found
     */
    VolatilityResponse getMarketVolatility(String brokerName, String symbol, int lookback);

    /**
     * Get market spread.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param symbol The symbol
     * @param maxSpread The maximum allowed spread
     * @return Spread response
     * @throws TradingException if symbol not found
     */
    SpreadResponse getMarketSpread(String brokerName, String symbol, double maxSpread);

    /**
     * Get full market conditions.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param symbol The symbol
     * @return Market conditions response
     * @throws TradingException if symbol not found
     */
    MarketConditionsResponse getMarketConditions(String brokerName, String symbol);

    // ============================================================
    // 7. MT5 CONNECTION
    // ============================================================

    /**
     * Connect to MT5.
     *
     * @param brokerName The broker name
     * @param request The connection request
     * @return Connection response
     * @throws TradingException if connection fails
     */
    Mt5ConnectionResponse connectMt5(String brokerName, Mt5ConnectRequest request);

    /**
     * Disconnect from MT5.
     *
     * @param brokerName The broker name
     * @return Disconnect result
     * @throws TradingException if disconnect fails
     */
    SingleBrokerResult disconnectMt5(String brokerName);

    // ============================================================
    // 8. HISTORY & CALCULATIONS
    // ============================================================

    /**
     * Get trade history.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param request The history request
     * @return Trade history response
     * @throws TradingException if broker not found
     */
    TradeHistoryResponse getTradeHistory(String brokerName, TradeHistoryRequest request);

    /**
     * Calculate lot size.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @param request The lot calculation request
     * @return Lot calculation response
     * @throws TradingException if broker not found
     */
    LotCalculationResponse calculateLot(String brokerName, LotCalculationRequest request);

    // ============================================================
    // 9. HEALTH
    // ============================================================

    /**
     * Check broker health.
     *
     * @param brokerName The broker name (optional, uses default if null)
     * @return Health response
     */
    HealthResponse healthCheck(String brokerName);
}