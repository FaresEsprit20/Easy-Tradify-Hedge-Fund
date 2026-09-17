package com.trading.easytradify.execution.client;

import com.trading.easytradify.execution.config.broker.BrokerConfig;
import com.trading.easytradify.execution.models.*;

/**
 * <h1>Python Execution Service Client</h1>
 * <p>
 * Complete abstraction for the Python-based trading execution service.
 * This interface provides a comprehensive set of methods that map directly
 * to the REST endpoints exposed by the Python execution controller.
 * </p>
 * <p>
 * Each method corresponds to a specific Python endpoint and handles the
 * communication with the underlying Python service for a given broker.
 * The client abstracts away the HTTP communication details and provides
 * a clean, type-safe API for the calling service layer.
 * </p>
 *
 * <h2>Architecture Overview</h2>
 * <ul>
 *   <li><b>Single Responsibility:</b> Each method maps to exactly one Python endpoint</li>
 *   <li><b>Broker Awareness:</b> All operations require a {@link BrokerConfig} to route to the correct Python instance</li>
 *   <li><b>Immutable Contracts:</b> All requests and responses are defined as immutable records</li>
 *   <li><b>Error Propagation:</b> Exceptions are propagated to the caller for centralized handling</li>
 * </ul>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Interface Segregation:</b> Methods are logically grouped by functional domain</li>
 *   <li><b>Dependency Inversion:</b> High-level modules depend on this abstraction, not concrete implementations</li>
 *   <li><b>Open/Closed:</b> New Python endpoints can be added without modifying existing methods</li>
 * </ul>
 *
 * <h2>Usage Example</h2>
 * <pre>
 * {@code
 * var client = new DefaultPythonExecutionClient(webClient, retry);
 * var broker = BrokerConfig.icMarkets();
 * var request = new ExecuteTradeRequest(...);
 * TradeExecutionResponse response = client.executeTrade(broker, request);
 * }
 * </pre>
 *
 * @see DefaultPythonExecutionClient
 * @see BrokerConfig
 * @see TradeExecutionResponse
 * @author Trading Platform Team
 * @version 1.0
 */
public interface PythonExecutionClient {

    // ============================================================
    // 1. TRADE EXECUTION
    // ============================================================

    /**
     * <h3>POST /trade/execute</h3>
     * <p>
     * Executes a market trade on the specified broker with optional stop loss,
     * take profit, and trailing stop configurations.
     * </p>
     * <p>
     * <b>Note:</b> MT5 only supports a single take profit per position.
     * TP2 and TP3 are stored as references only and are not applied to the actual order.
     * </p>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The trade execution request containing order details.
     *                Must not be {@code null}.
     * @return A {@link TradeExecutionResponse} containing the execution result
     *         including ticket number, price, stop loss, take profit, volume,
     *         margin, and risk information.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the execution fails due to invalid parameters,
     *         broker unavailability, or MT5 errors.
     * @throws IllegalArgumentException If the request or broker is {@code null}.
     * @see ExecuteTradeRequest
     * @see TradeExecutionResponse
     * @see TradeExecutionData
     */
    TradeExecutionResponse executeTrade(BrokerConfig broker, ExecuteTradeRequest request);

    /**
     * <h3>POST /trade/analyse</h3>
     * <p>
     * Performs a comprehensive trading signal analysis for the specified symbol
     * and order type. This is a non-executing analysis that returns the same
     * detailed 17-component analysis as the hedge fund signal endpoint.
     * </p>
     * <p>
     * <b>Analysis Components:</b>
     * </p>
     * <ul>
     *   <li>Trend analysis with divergence impact</li>
     *   <li>Technical indicators (RSI, MACD, Bollinger Bands, Stochastic)</li>
     *   <li>Supply/demand zones</li>
     *   <li>ICT/FVG concepts</li>
     *   <li>Wyckoff phase detection</li>
     *   <li>Volume profile and POC analysis</li>
     *   <li>Support and resistance levels</li>
     *   <li>Candlestick pattern recognition</li>
     *   <li>Entry timing with 5-star hedge fund rating</li>
     * </ul>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The analysis request containing symbol, order type,
     *                trade size, risk, and optional timeframe overrides.
     *                Must not be {@code null}.
     * @return An {@link AnalyseTradeResponse} containing the complete
     *         analysis result with all components, verdict, and execution timing.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the analysis fails or the symbol is invalid.
     * @see AnalyseTradeRequest
     * @see AnalyseTradeResponse
     */
    AnalyseTradeResponse analyseTrade(BrokerConfig broker, AnalyseTradeRequest request);

    /**
     * <h3>POST /trade/probability</h3>
     * <p>
     * Calculates the probability of hitting the take profit level before
     * the stop loss level for a given trade setup. This is a statistical
     * calculation based on historical price behavior and volatility.
     * </p>
     * <p>
     * <b>Interpretation:</b>
     * </p>
     * <ul>
     *   <li><b>&gt; 65%:</b> HIGH_PROBABILITY — Favorable setup</li>
     *   <li><b>45% - 65%:</b> MEDIUM_PROBABILITY — Average setup</li>
     *   <li><b>&lt; 45%:</b> LOW_PROBABILITY — Unfavorable setup</li>
     * </ul>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The probability request containing symbol, entry price,
     *                stop loss, take profit, and order type.
     *                Must not be {@code null}.
     * @return A {@link ProbabilityResponse} containing the calculated
     *         probability percentage and a textual recommendation.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the calculation fails or the parameters are invalid.
     * @see ProbabilityRequest
     * @see ProbabilityResponse
     */
    ProbabilityResponse calculateProbability(BrokerConfig broker, ProbabilityRequest request);

    // ============================================================
    // 2. POSITION MANAGEMENT
    // ============================================================

    /**
     * <h3>POST /position/close/{ticket}</h3>
     * <p>
     * Closes an existing position identified by its ticket number.
     * The position is closed at the current market price with the
     * specified deviation tolerance.
     * </p>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The close position request containing the ticket number
     *                and allowed deviation.
     *                Must not be {@code null}.
     * @return A {@link ClosePositionResponse} containing the closure result
     *         including the ticket number and realized profit.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the position is not found, already closed, or the close operation fails.
     * @see ClosePositionRequest
     * @see ClosePositionResponse
     */
    ClosePositionResponse closePosition(BrokerConfig broker, ClosePositionRequest request);

    /**
     * <h3>PUT /position/partial-close/{ticket}</h3>
     * <p>
     * Partially closes a position by reducing its volume by the specified amount.
     * The remaining position stays open with the original stop loss and take profit levels.
     * </p>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The partial close request containing the ticket number,
     *                volume to close, and allowed deviation.
     *                Must not be {@code null}.
     * @return A {@link PartialCloseResponse} containing the partial closure result
     *         including remaining volume, closed volume, and realized profit.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the position is not found, the volume is invalid, or the operation fails.
     * @see PartialCloseRequest
     * @see PartialCloseResponse
     */
    PartialCloseResponse partialClosePosition(BrokerConfig broker, PartialCloseRequest request);

    /**
     * <h3>POST /positions/close/all</h3>
     * <p>
     * Closes all open positions. Optionally filters by symbol to close
     * positions for a specific instrument only.
     * </p>
     * <p>
     * <b>Caution:</b> This operation is irreversible and will close all
     * positions matching the filter criteria.
     * </p>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The close all positions request containing optional
     *                symbol filter and deviation.
     *                Must not be {@code null}.
     * @return A {@link CloseAllResponse} containing the number of closed
     *         positions and total realized profit.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the operation fails.
     * @see CloseAllPositionsRequest
     * @see CloseAllResponse
     */
    CloseAllResponse closeAllPositions(BrokerConfig broker, CloseAllPositionsRequest request);

    /**
     * <h3>GET /positions</h3>
     * <p>
     * Retrieves all positions for the specified broker, optionally filtered
     * by symbol and/or magic number.
     * </p>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @param symbol Optional symbol filter. If {@code null}, returns positions
     *               for all symbols.
     * @param magic  Optional magic number filter. If {@code null}, returns
     *               positions for all magic numbers.
     * @return A {@link PositionsResponse} containing the list of positions
     *         and a summary with total risk, reward, and profit.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the broker is unreachable or the request fails.
     * @see PositionsResponse
     * @see PositionSummary
     */
    PositionsResponse getPositions(BrokerConfig broker, String symbol, Integer magic);

    /**
     * <h3>GET /positions/open</h3>
     * <p>
     * Retrieves only open (non-closed) positions for the specified broker,
     * optionally filtered by symbol and/or magic number.
     * </p>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @param symbol Optional symbol filter. If {@code null}, returns open
     *               positions for all symbols.
     * @param magic  Optional magic number filter. If {@code null}, returns
     *               open positions for all magic numbers.
     * @return A {@link PositionsResponse} containing the list of open positions
     *         and a summary with total risk, reward, and profit.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the broker is unreachable or the request fails.
     * @see PositionsResponse
     */
    PositionsResponse getOpenPositions(BrokerConfig broker, String symbol, Integer magic);

    /**
     * <h3>GET /position/{ticket}</h3>
     * <p>
     * Retrieves detailed information about a single position identified by
     * its ticket number.
     * </p>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @param ticket The position ticket number.
     *               Must be positive.
     * @return A {@link PositionResponse} containing the position details
     *         including entry price, current price, stop loss, take profit,
     *         volume, profit, and trailing stop status.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the position is not found or the request fails.
     * @see PositionResponse
     */
    PositionResponse getPosition(BrokerConfig broker, int ticket);

    // ============================================================
    // 3. STOP LOSS & TAKE PROFIT
    // ============================================================

    /**
     * <h3>PUT /position/{ticket}/stop-loss</h3>
     * <p>
     * Modifies the stop loss price of an existing position.
     * The new stop loss must be at a valid distance from the current market price
     * as determined by the broker's minimum stop distance rules.
     * </p>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The modify stop loss request containing the ticket number
     *                and new stop loss price.
     *                Must not be {@code null}.
     * @return A {@link ModifyStopLossResponse} containing the ticket number
     *         and the new stop loss price.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the position is not found, the stop loss price is invalid,
     *         or the modification fails.
     * @see ModifyStopLossRequest
     * @see ModifyStopLossResponse
     */
    ModifyStopLossResponse modifyStopLoss(BrokerConfig broker, ModifyStopLossRequest request);

    /**
     * <h3>PUT /position/{ticket}/take-profit</h3>
     * <p>
     * Modifies the take profit price of an existing position.
     * The new take profit must be at a valid distance from the current market price.
     * </p>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The modify take profit request containing the ticket number
     *                and new take profit price.
     *                Must not be {@code null}.
     * @return A {@link ModifyTakeProfitResponse} containing the ticket number
     *         and the new take profit price.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the position is not found, the take profit price is invalid,
     *         or the modification fails.
     * @see ModifyTakeProfitRequest
     * @see ModifyTakeProfitResponse
     */
    ModifyTakeProfitResponse modifyTakeProfit(BrokerConfig broker, ModifyTakeProfitRequest request);

    // ============================================================
    // 4. TRAILING STOP
    // ============================================================

    /**
     * <h3>PUT /position/trailing/enable/{ticket}</h3>
     * <p>
     * Enables a trailing stop for the specified position.
     * The trailing stop automatically adjusts the stop loss level as the price
     * moves in favor of the position, locking in profits while allowing for
     * continued upside.
     * </p>
     * <p>
     * <b>Behavior:</b>
     * </p>
     * <ul>
     *   <li>Activates after the position reaches a certain profit threshold (typically +10 pips)</li>
     *   <li>Moves the stop loss to breakeven initially</li>
     *   <li>Then trails the price by the specified number of pips</li>
     * </ul>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The trailing stop request containing the ticket number
     *                and the trailing step in pips.
     *                Must not be {@code null}.
     * @return A {@link TrailingStopResponse} containing the ticket number,
     *         symbol, and trailing pips.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the position is not found or the trailing stop activation fails.
     * @see TrailingStopRequest
     * @see TrailingStopResponse
     */
    TrailingStopResponse enableTrailingStop(BrokerConfig broker, TrailingStopRequest request);

    /**
     * <h3>PUT /position/trailing/disable/{ticket}</h3>
     * <p>
     * Disables the trailing stop for the specified position.
     * The stop loss remains at its current level and will not be adjusted further.
     * </p>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The disable trailing request containing the ticket number.
     *                Must not be {@code null}.
     * @return A {@link TrailingStopResponse} containing the ticket number
     *         and a success message.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the position is not found or no active trailing stop exists.
     * @see DisableTrailingRequest
     * @see TrailingStopResponse
     */
    TrailingStopResponse disableTrailingStop(BrokerConfig broker, DisableTrailingRequest request);

    /**
     * <h3>PUT /position/trailing/update/{ticket}</h3>
     * <p>
     * Updates the trailing stop step size for the specified position.
     * The step size determines how many pips the price must move before the
     * stop loss is adjusted.
     * </p>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The trailing stop request containing the ticket number
     *                and the new trailing step in pips.
     *                Must not be {@code null}.
     * @return A {@link TrailingStopResponse} containing the ticket number,
     *         symbol, and updated trailing pips.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the position is not found, no active trailing stop exists,
     *         or the update fails.
     * @see TrailingStopRequest
     * @see TrailingStopResponse
     */
    TrailingStopResponse updateTrailingStop(BrokerConfig broker, TrailingStopRequest request);

    /**
     * <h3>GET /position/trailing/status</h3>
     * <p>
     * Retrieves the trailing stop status for all positions on the specified broker.
     * Returns a list of all positions with active trailing stops and their current
     * trailing pips settings.
     * </p>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @return A {@link TrailingStatusResponse} containing a list of active
     *         trailing stops with ticket numbers, symbols, step pips, and last
     *         adjusted stop loss levels.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the broker is unreachable or the request fails.
     * @see TrailingStatusResponse
     */
    TrailingStatusResponse getTrailingStatus(BrokerConfig broker);

    /**
     * <h3>GET /trailing-stop/stats</h3>
     * <p>
     * Retrieves trailing stop statistics for the specified broker.
     * Provides aggregated metrics about trailing stop usage and performance.
     * </p>
     * <p>
     * <b>Available Statistics:</b>
     * </p>
     * <ul>
     *   <li>Total number of trailing stops enabled</li>
     *   <li>Active trailing stops</li>
     *   <li>Average trailing pips</li>
     *   <li>Total profit locked by trailing stops</li>
     *   <li>Total loss prevented by trailing stops</li>
     *   <li>Success rate (profit locked vs loss prevented)</li>
     *   <li>Breakdown by symbol</li>
     * </ul>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @return A {@link TrailingStatsResponse} containing the trailing stop
     *         statistics.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the broker is unreachable or the request fails.
     * @see TrailingStatsResponse
     */
    TrailingStatsResponse getTrailingStats(BrokerConfig broker);

    // ============================================================
    // 5. ACCOUNT & SYMBOL
    // ============================================================

    /**
     * <h3>GET /account</h3>
     * <p>
     * Retrieves account information for the specified broker.
     * </p>
     * <p>
     * <b>Account Details:</b>
     * </p>
     * <ul>
     *   <li>Login number</li>
     *   <li>Account balance</li>
     *   <li>Current equity</li>
     *   <li>Account currency</li>
     *   <li>Leverage</li>
     * </ul>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @return An {@link AccountResponse} containing the account information.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the broker is unreachable or the request fails.
     * @see AccountResponse
     */
    AccountResponse getAccount(BrokerConfig broker);

    /**
     * <h3>GET /symbol/{symbol}</h3>
     * <p>
     * Retrieves detailed information about a specific trading symbol
     * from the specified broker.
     * </p>
     * <p>
     * <b>Symbol Details:</b>
     * </p>
     * <ul>
     *   <li>Name and description</li>
     *   <li>Base and profit currencies</li>
     *   <li>Digits (decimal places)</li>
     *   <li>Minimum and maximum volume</li>
     *   <li>Current bid and ask prices</li>
     *   <li>Current spread in pips</li>
     * </ul>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @param symbol The trading symbol name (e.g., "EURUSD", "XAUUSD").
     *               Must not be {@code null} or empty.
     * @return A {@link SymbolInfoResponse} containing the symbol information.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the symbol is not found or the request fails.
     * @see SymbolInfoResponse
     */
    SymbolInfoResponse getSymbolInfo(BrokerConfig broker, String symbol);

    /**
     * <h3>GET /symbols</h3>
     * <p>
     * Retrieves information for all available trading symbols from the
     * specified broker.
     * </p>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @return A {@link SymbolsResponse} containing a list of all available
     *         symbols with their details.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the broker is unreachable or the request fails.
     * @see SymbolsResponse
     * @see SymbolInfoResponse
     */
    SymbolsResponse getSymbols(BrokerConfig broker);

    // ============================================================
    // 6. MARKET CONDITIONS
    // ============================================================

    /**
     * <h3>GET /market/status/{symbol}</h3>
     * <p>
     * Checks whether the market is closed for the specified symbol.
     * </p>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @param symbol The trading symbol name (e.g., "EURUSD", "XAUUSD").
     *               Must not be {@code null} or empty.
     * @return A {@link MarketStatusResponse} indicating whether the market is
     *         closed and the reason if applicable.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the symbol is not found or the request fails.
     * @see MarketStatusResponse
     */
    MarketStatusResponse getMarketStatus(BrokerConfig broker, String symbol);

    /**
     * <h3>GET /market/volatility/{symbol}</h3>
     * <p>
     * Calculates the market volatility for the specified symbol.
     * Volatility is measured as a percentage of price movement.
     * </p>
     * <p>
     * <b>Interpretation:</b>
     * </p>
     * <ul>
     *   <li><b>&lt; 0.5%:</b> Low Volatility</li>
     *   <li><b>0.5% - 1.5%:</b> Normal Volatility</li>
     *   <li><b>&gt; 1.5%:</b> High Volatility</li>
     * </ul>
     *
     * @param broker   The broker configuration for routing the request.
     *                 Must not be {@code null}.
     * @param symbol   The trading symbol name (e.g., "EURUSD", "XAUUSD").
     *                 Must not be {@code null} or empty.
     * @param lookback The number of bars to calculate volatility over.
     *                 Must be positive.
     * @return A {@link VolatilityResponse} containing the volatility percentage
     *         and an interpretation level (LOW, NORMAL, HIGH).
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the symbol is not found or the request fails.
     * @see VolatilityResponse
     */
    VolatilityResponse getMarketVolatility(BrokerConfig broker, String symbol, int lookback);

    /**
     * <h3>GET /market/spread/{symbol}</h3>
     * <p>
     * Checks the current spread for the specified symbol and validates it
     * against a maximum allowed spread.
     * </p>
     * <p>
     * <b>Spread Interpretation:</b>
     * </p>
     * <ul>
     *   <li><b>&lt;= 8 pips:</b> Excellent — Low cost, ideal for trading</li>
     *   <li><b>8-15 pips:</b> Normal — Acceptable for most strategies</li>
     *   <li><b>&gt; 15 pips:</b> High — May cause trade avoidance</li>
     * </ul>
     *
     * @param broker    The broker configuration for routing the request.
     *                  Must not be {@code null}.
     * @param symbol    The trading symbol name (e.g., "EURUSD", "XAUUSD").
     *                  Must not be {@code null} or empty.
     * @param maxSpread The maximum allowed spread in pips.
     *                  Must be positive.
     * @return A {@link SpreadResponse} containing the current spread in pips
     *         and a boolean indicating if it is within the acceptable range.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the symbol is not found or the request fails.
     * @see SpreadResponse
     */
    SpreadResponse getMarketSpread(BrokerConfig broker, String symbol, double maxSpread);

    /**
     * <h3>GET /market/conditions/{symbol}</h3>
     * <p>
     * Retrieves comprehensive market conditions for the specified symbol.
     * This is a combined view of multiple market metrics with explanations
     * and trading recommendations.
     * </p>
     * <p>
     * <b>Provided Metrics:</b>
     * </p>
     * <ul>
     *   <li><b>Spread:</b> Current spread with interpretation</li>
     *   <li><b>ATR:</b> Average True Range in pips</li>
     *   <li><b>Trend Strength:</b> 0-1 scale (0.3 = ranging, 0.6 = strong trend)</li>
     *   <li><b>Volatility:</b> Price movement percentage with interpretation</li>
     * </ul>
     * <p>
     * <b>Trading Recommendations:</b>
     * </p>
     * <ul>
     *   <li>Action: CAUTIOUS (spread > 15) or NORMAL</li>
     *   <li>Minimum required risk-reward: 1:2</li>
     *   <li>Minimum required probability: 75%</li>
     *   <li>Suggested stop loss and take profit levels</li>
     *   <li>Suggested trailing stop step</li>
     * </ul>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @param symbol The trading symbol name (e.g., "EURUSD", "XAUUSD").
     *               Must not be {@code null} or empty.
     * @return A {@link MarketConditionsResponse} containing all market metrics
     *         and trading recommendations.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the symbol is not found or the request fails.
     * @see MarketConditionsResponse
     */
    MarketConditionsResponse getMarketConditions(BrokerConfig broker, String symbol);

    // ============================================================
    // 7. MT5 CONNECTION
    // ============================================================

    /**
     * <h3>POST /mt5/connect</h3>
     * <p>
     * Establishes a connection to the MetaTrader 5 terminal for the
     * specified broker.
     * </p>
     * <p>
     * <b>Note:</b> This method is typically called once at application startup
     * or when re-establishing a connection after a disconnect.
     * </p>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The MT5 connection request containing login credentials,
     *                server name, and optional terminal path.
     *                Must not be {@code null}.
     * @return An {@link Mt5ConnectionResponse} indicating the connection status
     *         and containing account information if successful.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the connection fails due to invalid credentials, server
     *         unavailability, or MT5 initialization errors.
     * @see Mt5ConnectRequest
     * @see Mt5ConnectionResponse
     */
    Mt5ConnectionResponse connectMt5(BrokerConfig broker, Mt5ConnectRequest request);

    /**
     * <h3>POST /mt5/disconnect</h3>
     * <p>
     * Disconnects from the MetaTrader 5 terminal for the specified broker.
     * This releases all resources and terminates the connection to the terminal.
     * </p>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @return A {@link SingleBrokerResult} indicating the disconnection status.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the disconnect operation fails.
     */
    SingleBrokerResult disconnectMt5(BrokerConfig broker);

    // ============================================================
    // 8. HISTORY & CALCULATIONS
    // ============================================================

    /**
     * <h3>GET /trades/history</h3>
     * <p>
     * Retrieves trade history for the specified broker with optional
     * filtering and date range constraints.
     * </p>
     * <p>
     * <b>Available Filters:</b>
     * </p>
     * <ul>
     *   <li><b>Symbol:</b> Filter by trading symbol</li>
     *   <li><b>Magic Number:</b> Filter by strategy identifier</li>
     *   <li><b>Date Range:</b> Filter by from/to dates</li>
     *   <li><b>Last N Days:</b> Quick filter for recent history</li>
     * </ul>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The trade history request containing optional
     *                filters and date range.
     *                Must not be {@code null}.
     * @return A {@link TradeHistoryResponse} containing the list of deals
     *         and trades with a summary of performance metrics.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the broker is unreachable or the request fails.
     * @see TradeHistoryRequest
     * @see TradeHistoryResponse
     */
    TradeHistoryResponse getTradeHistory(BrokerConfig broker, TradeHistoryRequest request);

    /**
     * <h3>POST /calculate-lot</h3>
     * <p>
     * Calculates the optimal lot size for a trade based on the specified
     * trade size in USD and risk per trade percentage.
     * </p>
     * <p>
     * <b>Calculation Logic:</b>
     * </p>
     * <ul>
     *   <li>Uses the current account balance and leverage</li>
     *   <li>Calculates the maximum lot size based on margin requirements</li>
     *   <li>Adjusts lot size to keep risk within the target risk budget</li>
     *   <li>Applies instrument-specific pip values and contract sizes</li>
     * </ul>
     *
     * @param broker  The broker configuration for routing the request.
     *                Must not be {@code null}.
     * @param request The lot calculation request containing symbol,
     *                trade size in USD, and risk per trade percentage.
     *                Must not be {@code null}.
     * @return A {@link LotCalculationResponse} containing the calculated
     *         lot size and associated risk and margin information.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the calculation fails or the parameters are invalid.
     * @see LotCalculationRequest
     * @see LotCalculationResponse
     */
    LotCalculationResponse calculateLot(BrokerConfig broker, LotCalculationRequest request);

    // ============================================================
    // 9. HEALTH
    // ============================================================

    /**
     * <h3>GET /health</h3>
     * <p>
     * Performs a health check on the Python execution service for the
     * specified broker. This is a lightweight endpoint that verifies
     * the service is operational and connected to MT5.
     * </p>
     * <p>
     * <b>Usage:</b> This method is typically used for monitoring and
     * circuit breaker patterns. It should be called periodically to
     * ensure the service is healthy before sending production requests.
     * </p>
     *
     * @param broker The broker configuration for routing the request.
     *               Must not be {@code null}.
     * @return A {@link HealthResponse} containing the service status
     *         ("operational" or "error") and MT5 connection status.
     */
    HealthResponse healthCheck(BrokerConfig broker);

}