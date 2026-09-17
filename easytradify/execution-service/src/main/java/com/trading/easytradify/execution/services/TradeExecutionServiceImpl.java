package com.trading.easytradify.execution.services;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.execution.client.PythonExecutionClient;
import com.trading.easytradify.execution.config.broker.BrokerConfig;
import com.trading.easytradify.execution.config.broker.BrokerRegistry;
import com.trading.easytradify.execution.models.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.lang.reflect.Method;
import java.util.List;
import java.util.function.BiFunction;
import java.util.function.Function;

/**
 * <h1>Trade Execution Service Implementation</h1>
 * <p>
 * Concrete implementation of the {@link TradeExecutionService} interface.
 * This service acts as a facade between the application layer and the
 * Python execution service, handling broker resolution, request validation,
 * and response processing.
 * </p>
 * <p>
 * <b>Key Design Principles:</b>
 * </p>
 * <ul>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to the global exception handler</li>
 *   <li><b>Declarative Validation:</b> Input validation is explicit and throws domain exceptions</li>
 *   <li><b>Reflection-Based Success Detection:</b> Responses are checked for success flag via reflection</li>
 *   <li><b>Multi-Broker Support:</b> Operations can be executed on single or multiple brokers</li>
 * </ul>
 *
 * <h2>Error Handling Strategy</h2>
 * <p>
 * This service uses a <b>fail-fast</b> approach:
 * </p>
 * <ol>
 *   <li>Validate inputs → throws {@link TradingException} if invalid</li>
 *   <li>Execute operation → returns a response object</li>
 *   <li>Check response success flag → throws {@link TradingException} if {@code false}</li>
 *   <li>Return successful response to caller</li>
 * </ol>
 * <p>
 * All exceptions are propagated to the {@code GlobalExceptionHandler}
 * for consistent error response formatting.
 * </p>
 *
 * <h2>Usage Example</h2>
 * <pre>
 * {@code
 * @Autowired
 * private TradeExecutionService tradeService;
 *
 * public void placeTrade() {
 *     var request = ExecuteTradeRequest.builder()
 *         .symbol("EURUSD")
 *         .orderType(OrderType.BUY)
 *         .fixedTradeSizeUsd(200.0)
 *         .riskPerTrade(0.05)
 *         .build();
 *
 *     var response = tradeService.executeTrade(request);
 *     // response.success() == true
 * }
 * }
 * </pre>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see TradeExecutionService
 * @see PythonExecutionClient
 * @see BrokerRegistry
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class TradeExecutionServiceImpl implements TradeExecutionService {

    private final PythonExecutionClient pythonClient;
    private final BrokerRegistry brokerRegistry;

    // ============================================================
    // VALIDATION HELPERS
    // ============================================================

    /**
     * Resolves a broker configuration from a broker name.
     * If the name is {@code null} or empty, returns the default broker.
     *
     * @param brokerName The broker name (optional)
     * @return The resolved {@link BrokerConfig}
     * @throws TradingException If the broker name is invalid
     */
    private BrokerConfig resolveBroker(String brokerName) {
        if (!StringUtils.hasText(brokerName)) {
            return brokerRegistry.getDefaultBroker();
        }
        return brokerRegistry.getBroker(brokerName);
    }

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
     * Validates that a numeric value is positive.
     *
     * @param value     The value to validate
     * @param fieldName The name of the field (used in error message)
     * @throws TradingException If the value is not positive
     */
    private void validatePositive(double value, String fieldName) {
        if (value <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message(fieldName + " must be positive: " + value)
                    .build();
        }
    }

    /**
     * Validates that a ticket number is positive.
     *
     * @param ticket The ticket number to validate
     * @throws TradingException If the ticket number is not positive
     */
    private void validateTicket(int ticket) {
        if (ticket <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.POSITION_NOT_FOUND)
                    .message("Invalid ticket number: " + ticket)
                    .build();
        }
    }

    /**
     * Validates that all requested brokers exist and are active.
     *
     * @param requestedBrokers The list of broker names to validate
     * @throws TradingException If any broker is not found
     */
    private void validateBrokers(List<String> requestedBrokers) {
        if (requestedBrokers == null || requestedBrokers.isEmpty()) {
            return;
        }
        for (var brokerName : requestedBrokers) {
            if (!brokerRegistry.isBrokerExists(brokerName) && !brokerName.equalsIgnoreCase("all")) {
                throw TradingException.builder()
                        .errorCode(ErrorCodes.BROKER_NOT_FOUND)
                        .message("Broker not found: " + brokerName)
                        .build();
            }
        }
    }

    // ============================================================
    // EXECUTION HELPERS
    // ============================================================

    /**
     * Executes an operation on a single broker with a request parameter.
     * <p>
     * <b>No try-catch:</b> Exceptions bubble up to the caller.
     * </p>
     *
     * @param brokerName    The broker name (optional, uses default if null)
     * @param executor      The operation executor function
     * @param request       The request object (may be null if not needed)
     * @param operationName The name of the operation (for logging)
     * @param <T>           The request type
     * @param <R>           The response type
     * @return The operation result
     */
    private <T, R> R executeOnBroker(
            String brokerName,
            BiFunction<BrokerConfig, T, R> executor,
            T request,
            String operationName) {

        var broker = resolveBroker(brokerName);
        log.info("[{}] Executing {}: {}", broker.name(), operationName, request);

        return executor.apply(broker, request);
    }

    /**
     * Executes an operation on a single broker without a request parameter.
     * <p>
     * <b>No try-catch:</b> Exceptions bubble up to the caller.
     * </p>
     *
     * @param brokerName    The broker name (optional, uses default if null)
     * @param executor      The operation executor function
     * @param operationName The name of the operation (for logging)
     * @param <R>           The response type
     * @return The operation result
     */
    private <R> R executeOnBroker(
            String brokerName,
            Function<BrokerConfig, R> executor,
            String operationName) {

        var broker = resolveBroker(brokerName);
        log.info("[{}] Executing {}:", broker.name(), operationName);

        return executor.apply(broker);
    }

    /**
     * Executes an operation on multiple brokers with a request parameter.
     * <p>
     * Iterates through all requested brokers until a successful response is found.
     * If all brokers fail, throws a {@link TradingException}.
     * </p>
     * <p>
     * <b>No try-catch:</b> Exceptions bubble up to the caller.
     * </p>
     *
     * @param requestedBrokers The list of broker names
     * @param executor         The operation executor function
     * @param request          The request object
     * @param operationName    The name of the operation (for logging)
     * @param <T>              The request type
     * @param <R>              The response type (must have a {@code success()} method)
     * @return The first successful response
     * @throws TradingException If all brokers fail or no brokers are available
     */
    @SuppressWarnings("unchecked")
    private <T, R> R executeOnBrokersWithFirstSuccess(
            List<String> requestedBrokers,
            BiFunction<BrokerConfig, T, R> executor,
            T request,
            String operationName) {

        var resolvedBrokers = brokerRegistry.resolveBrokers(requestedBrokers);

        for (var broker : resolvedBrokers) {
            log.info("[{}] Executing {}: {}", broker.name(), operationName, request);
            var result = executor.apply(broker, request);

            if (isSuccess(result)) {
                return result;
            }

            log.warn("[{}] {} failed: {}", broker.name(), operationName, getError(result));
        }

        throw TradingException.builder()
                .errorCode(ErrorCodes.TRADE_EXECUTION_FAILED)
                .message(operationName + " failed on all brokers")
                .build();
    }

    /**
     * Executes an operation on multiple brokers without a request parameter.
     * <p>
     * Iterates through all requested brokers until a successful response is found.
     * If all brokers fail, throws a {@link TradingException}.
     * </p>
     * <p>
     * <b>No try-catch:</b> Exceptions bubble up to the caller.
     * </p>
     *
     * @param requestedBrokers The list of broker names
     * @param executor         The operation executor function
     * @param operationName    The name of the operation (for logging)
     * @param <R>              The response type (must have a {@code success()} method)
     * @return The first successful response
     * @throws TradingException If all brokers fail or no brokers are available
     */
    @SuppressWarnings("unchecked")
    private <R> R executeOnBrokersWithFirstSuccess(
            List<String> requestedBrokers,
            Function<BrokerConfig, R> executor,
            String operationName) {

        var resolvedBrokers = brokerRegistry.resolveBrokers(requestedBrokers);

        for (var broker : resolvedBrokers) {
            log.info("[{}] Executing {}:", broker.name(), operationName);
            var result = executor.apply(broker);

            if (isSuccess(result)) {
                return result;
            }

            log.warn("[{}] {} failed: {}", broker.name(), operationName, getError(result));
        }

        throw TradingException.builder()
                .errorCode(ErrorCodes.TRADE_EXECUTION_FAILED)
                .message(operationName + " failed on all brokers")
                .build();
    }

    /**
     * Determines if a response object indicates success.
     * <p>
     * Uses reflection to invoke the {@code success()} method on the response object.
     * If the method does not exist, assumes success ({@code true}).
     * </p>
     *
     * @param response The response object to check
     * @return {@code true} if the response indicates success, {@code false} otherwise
     */
    private boolean isSuccess(Object response) {
        try {
            Method method = response.getClass().getMethod("success");
            return (Boolean) method.invoke(response);
        } catch (Exception e) {
            return true;
        }
    }

    /**
     * Extracts an error message from a failed response object.
     * <p>
     * Uses reflection to invoke the {@code error()} method on the response object.
     * If the method does not exist, returns a generic error message.
     * </p>
     *
     * @param response The failed response object
     * @return The error message
     */
    private String getError(Object response) {
        try {
            Method method = response.getClass().getMethod("error");
            return (String) method.invoke(response);
        } catch (Exception e) {
            return "Unknown error";
        }
    }

    // ============================================================
    // 1. TRADE EXECUTION
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public TradeExecutionResponse executeTrade(ExecuteTradeRequest request) {
        log.info("Executing trade: {} {} on brokers: {}",
                request.symbol(), request.orderType(), request.brokers());

        validateSymbol(request.symbol());
        validatePositive(request.fixedTradeSizeUsd(), "Trade size");
        validatePositive(request.riskPerTrade(), "Risk per trade");
        validatePositive(request.maxSpread(), "Max spread");
        validateBrokers(request.brokers());

        return executeOnBrokersWithFirstSuccess(
                request.brokers(),
                pythonClient::executeTrade,
                request,
                "executeTrade"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public AnalyseTradeResponse analyseTrade(AnalyseTradeRequest request) {
        log.info("Analysing trade: {} {}", request.symbol(), request.orderType());

        validateSymbol(request.symbol());
        validatePositive(request.fixedTradeSizeUsd(), "Trade size");
        validatePositive(request.riskPerTrade(), "Risk per trade");

        return executeOnBroker(
                null,
                pythonClient::analyseTrade,
                request,
                "analyseTrade"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ProbabilityResponse calculateProbability(ProbabilityRequest request) {
        log.info("Calculating probability for: {}", request.symbol());

        validateSymbol(request.symbol());
        validatePositive(request.entryPrice(), "Entry price");
        validatePositive(request.stopLoss(), "Stop loss");
        validatePositive(request.takeProfit(), "Take profit");

        return executeOnBroker(
                null,
                pythonClient::calculateProbability,
                request,
                "calculateProbability"
        );
    }

    // ============================================================
    // 2. POSITION MANAGEMENT
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ClosePositionResponse closePosition(ClosePositionRequest request) {
        log.info("Closing position: {} on brokers: {}", request.ticket(), request.brokers());

        validateTicket(request.ticket());
        validateBrokers(request.brokers());

        return executeOnBrokersWithFirstSuccess(
                request.brokers(),
                pythonClient::closePosition,
                request,
                "closePosition"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public PartialCloseResponse partialClosePosition(PartialCloseRequest request) {
        log.info("Partial closing position: {} (volume: {}) on brokers: {}",
                request.ticket(), request.volumeToClose(), request.brokers());

        validateTicket(request.ticket());
        validatePositive(request.volumeToClose(), "Volume to close");
        validateBrokers(request.brokers());

        return executeOnBrokersWithFirstSuccess(
                request.brokers(),
                pythonClient::partialClosePosition,
                request,
                "partialClosePosition"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public CloseAllResponse closeAllPositions(CloseAllPositionsRequest request) {
        log.info("Closing all positions{}",
                request.symbol() != null ? " for " + request.symbol() : "");

        return executeOnBroker(
                null,
                pythonClient::closeAllPositions,
                request,
                "closeAllPositions"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public PositionsResponse getPositions(String brokerName, String symbol, Integer magic) {
        log.info("Getting positions for broker: {}, symbol: {}, magic: {}", brokerName, symbol, magic);

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.getPositions(broker, symbol, magic),
                null,
                "getPositions"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public PositionsResponse getOpenPositions(String brokerName, String symbol, Integer magic) {
        log.info("Getting open positions for broker: {}, symbol: {}, magic: {}", brokerName, symbol, magic);

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.getOpenPositions(broker, symbol, magic),
                null,
                "getOpenPositions"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public PositionResponse getPosition(String brokerName, int ticket) {
        log.info("Getting position: {} for broker: {}", ticket, brokerName);

        validateTicket(ticket);

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.getPosition(broker, ticket),
                null,
                "getPosition"
        );
    }

    // ============================================================
    // 3. STOP LOSS & TAKE PROFIT
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ModifyStopLossResponse modifyStopLoss(ModifyStopLossRequest request) {
        log.info("Modifying SL: {} -> {} on brokers: {}",
                request.ticket(), request.slPrice(), request.brokers());

        validateTicket(request.ticket());
        validatePositive(request.slPrice(), "Stop loss price");
        validateBrokers(request.brokers());

        return executeOnBrokersWithFirstSuccess(
                request.brokers(),
                pythonClient::modifyStopLoss,
                request,
                "modifyStopLoss"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ModifyTakeProfitResponse modifyTakeProfit(ModifyTakeProfitRequest request) {
        log.info("Modifying TP: {} -> {} on brokers: {}",
                request.ticket(), request.tpPrice(), request.brokers());

        validateTicket(request.ticket());
        validatePositive(request.tpPrice(), "Take profit price");
        validateBrokers(request.brokers());

        return executeOnBrokersWithFirstSuccess(
                request.brokers(),
                pythonClient::modifyTakeProfit,
                request,
                "modifyTakeProfit"
        );
    }

    // ============================================================
    // 4. TRAILING STOP
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public TrailingStopResponse enableTrailingStop(TrailingStopRequest request) {
        log.info("Enabling trailing stop: {} ({} pips) on brokers: {}",
                request.ticket(), request.trailingPips(), request.brokers());

        validateTicket(request.ticket());
        validatePositive(request.trailingPips(), "Trailing pips");
        validateBrokers(request.brokers());

        return executeOnBrokersWithFirstSuccess(
                request.brokers(),
                pythonClient::enableTrailingStop,
                request,
                "enableTrailingStop"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public TrailingStopResponse disableTrailingStop(DisableTrailingRequest request) {
        log.info("Disabling trailing stop: {} on brokers: {}", request.ticket(), request.brokers());

        validateTicket(request.ticket());
        validateBrokers(request.brokers());

        return executeOnBrokersWithFirstSuccess(
                request.brokers(),
                pythonClient::disableTrailingStop,
                request,
                "disableTrailingStop"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public TrailingStopResponse updateTrailingStop(TrailingStopRequest request) {
        log.info("Updating trailing stop: {} -> {} pips on brokers: {}",
                request.ticket(), request.trailingPips(), request.brokers());

        validateTicket(request.ticket());
        validatePositive(request.trailingPips(), "Trailing pips");
        validateBrokers(request.brokers());

        return executeOnBrokersWithFirstSuccess(
                request.brokers(),
                pythonClient::updateTrailingStop,
                request,
                "updateTrailingStop"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public TrailingStatusResponse getTrailingStatus(String brokerName) {
        log.info("Getting trailing status for broker: {}", brokerName);

        return executeOnBroker(
                brokerName,
                pythonClient::getTrailingStatus,
                "getTrailingStatus"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public TrailingStatsResponse getTrailingStats(String brokerName) {
        log.info("Getting trailing stats for broker: {}", brokerName);

        return executeOnBroker(
                brokerName,
                pythonClient::getTrailingStats,
                "getTrailingStats"
        );
    }

    // ============================================================
    // 5. ACCOUNT & SYMBOL
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public AccountResponse getAccount(String brokerName) {
        log.info("Getting account info for broker: {}", brokerName);

        return executeOnBroker(
                brokerName,
                pythonClient::getAccount,
                "getAccount"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public SymbolInfoResponse getSymbolInfo(String brokerName, String symbol) {
        log.info("Getting symbol info: {} for broker: {}", symbol, brokerName);

        validateSymbol(symbol);

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.getSymbolInfo(broker, symbol),
                null,
                "getSymbolInfo"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public SymbolsResponse getSymbols(String brokerName) {
        log.info("Getting all symbols for broker: {}", brokerName);

        return executeOnBroker(
                brokerName,
                pythonClient::getSymbols,
                "getSymbols"
        );
    }

    // ============================================================
    // 6. MARKET CONDITIONS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public MarketStatusResponse getMarketStatus(String brokerName, String symbol) {
        log.info("Getting market status: {} for broker: {}", symbol, brokerName);

        validateSymbol(symbol);

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.getMarketStatus(broker, symbol),
                null,
                "getMarketStatus"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public VolatilityResponse getMarketVolatility(String brokerName, String symbol, int lookback) {
        log.info("Getting volatility: {} (lookback: {}) for broker: {}", symbol, lookback, brokerName);

        validateSymbol(symbol);
        if (lookback <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message("Lookback period must be positive: " + lookback)
                    .build();
        }

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.getMarketVolatility(broker, symbol, lookback),
                null,
                "getMarketVolatility"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public SpreadResponse getMarketSpread(String brokerName, String symbol, double maxSpread) {
        log.info("Getting spread: {} (max: {}) for broker: {}", symbol, maxSpread, brokerName);

        validateSymbol(symbol);
        if (maxSpread <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message("Max spread must be positive: " + maxSpread)
                    .build();
        }

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.getMarketSpread(broker, symbol, maxSpread),
                null,
                "getMarketSpread"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public MarketConditionsResponse getMarketConditions(String brokerName, String symbol) {
        log.info("Getting market conditions: {} for broker: {}", symbol, brokerName);

        validateSymbol(symbol);

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.getMarketConditions(broker, symbol),
                null,
                "getMarketConditions"
        );
    }

    // ============================================================
    // 7. MT5 CONNECTION
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public Mt5ConnectionResponse connectMt5(String brokerName, Mt5ConnectRequest request) {
        log.info("Connecting MT5 for broker: {}", brokerName);

        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Connection request cannot be null")
                    .build();
        }

        if (!StringUtils.hasText(request.login())) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Login is required for MT5 connection")
                    .build();
        }

        if (!StringUtils.hasText(request.password())) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Password is required for MT5 connection")
                    .build();
        }

        if (!StringUtils.hasText(request.server())) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Server is required for MT5 connection")
                    .build();
        }

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.connectMt5(broker, req),
                request,
                "connectMt5"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public SingleBrokerResult disconnectMt5(String brokerName) {
        log.info("Disconnecting MT5 for broker: {}", brokerName);

        return executeOnBroker(
                brokerName,
                pythonClient::disconnectMt5,
                "disconnectMt5"
        );
    }

    // ============================================================
    // 8. HISTORY & CALCULATIONS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public TradeHistoryResponse getTradeHistory(String brokerName, TradeHistoryRequest request) {
        log.info("Getting trade history for broker: {}", brokerName);

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.getTradeHistory(broker, req),
                request,
                "getTradeHistory"
        );
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public LotCalculationResponse calculateLot(String brokerName, LotCalculationRequest request) {
        log.info("Calculating lot for broker: {}", brokerName);

        validatePositive(request.fixedTradeSizeUsd(), "Trade size");
        validatePositive(request.riskPerTrade(), "Risk per trade");

        return executeOnBroker(
                brokerName,
                (broker, req) -> pythonClient.calculateLot(broker, req),
                request,
                "calculateLot"
        );
    }

    // ============================================================
    // 9. HEALTH
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public HealthResponse healthCheck(String brokerName) {
        log.info("Health check for broker: {}", brokerName);

        return executeOnBroker(
                brokerName,
                pythonClient::healthCheck,
                "healthCheck"
        );
    }


}