package com.trading.easytradify.execution.controllers;

import com.trading.easytradify.execution.controller.api.ExecutionApi;
import com.trading.easytradify.execution.models.*;
import com.trading.easytradify.execution.services.TradeExecutionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

/**
 * <h1>Trade Execution Controller</h1>
 * <p>
 * Concrete implementation of the {@link ExecutionApi} interface.
 * This controller handles all REST endpoints for trade execution and management.
 * </p>
 * <p>
 * <b>Design Principles:</b>
 * </p>
 * <ul>
 *   <li><b>Thin Controller:</b> All business logic is delegated to the service layer</li>
 *   <li><b>No Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Validation:</b> All requests are validated via {@code @Valid}</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see ExecutionApi
 * @see TradeExecutionService
 */
@RestController
@RequiredArgsConstructor
@Slf4j
public class ExecutionController implements ExecutionApi {

    private final TradeExecutionService tradeService;

    // ============================================================
    // 1. TRADE EXECUTION
    // ============================================================

    @Override
    public ResponseEntity<TradeExecutionResponse> executeTrade(ExecuteTradeRequest request) {
        log.info("Received trade execution request: {} {}", request.symbol(), request.orderType());
        var response = tradeService.executeTrade(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<AnalyseTradeResponse> analyseTrade(AnalyseTradeRequest request) {
        log.info("Received trade analysis request: {} {}", request.symbol(), request.orderType());
        var response = tradeService.analyseTrade(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<ProbabilityResponse> calculateProbability(ProbabilityRequest request) {
        log.info("Received probability calculation request: {}", request.symbol());
        var response = tradeService.calculateProbability(request);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // 2. POSITION MANAGEMENT
    // ============================================================

    @Override
    public ResponseEntity<ClosePositionResponse> closePosition(ClosePositionRequest request) {
        log.info("Received close position request: {}", request.ticket());
        var response = tradeService.closePosition(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<PartialCloseResponse> partialClosePosition(PartialCloseRequest request) {
        log.info("Received partial close request: {} volume: {}", request.ticket(), request.volumeToClose());
        var response = tradeService.partialClosePosition(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<CloseAllResponse> closeAllPositions(CloseAllPositionsRequest request) {
        log.info("Received close all positions request{}",
                request.symbol() != null ? " for " + request.symbol() : "");
        var response = tradeService.closeAllPositions(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<PositionsResponse> getPositions(String broker, String symbol, Integer magic) {
        log.info("Received get positions request: broker={}, symbol={}, magic={}", broker, symbol, magic);
        var response = tradeService.getPositions(broker, symbol, magic);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<PositionsResponse> getOpenPositions(String broker, String symbol, Integer magic) {
        log.info("Received get open positions request: broker={}, symbol={}, magic={}", broker, symbol, magic);
        var response = tradeService.getOpenPositions(broker, symbol, magic);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<PositionResponse> getPosition(String broker, int ticket) {
        log.info("Received get position request: broker={}, ticket={}", broker, ticket);
        var response = tradeService.getPosition(broker, ticket);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // 3. STOP LOSS & TAKE PROFIT
    // ============================================================

    @Override
    public ResponseEntity<ModifyStopLossResponse> modifyStopLoss(ModifyStopLossRequest request) {
        log.info("Received modify SL request: {} -> {}", request.ticket(), request.slPrice());
        var response = tradeService.modifyStopLoss(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<ModifyTakeProfitResponse> modifyTakeProfit(ModifyTakeProfitRequest request) {
        log.info("Received modify TP request: {} -> {}", request.ticket(), request.tpPrice());
        var response = tradeService.modifyTakeProfit(request);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // 4. TRAILING STOP
    // ============================================================

    @Override
    public ResponseEntity<TrailingStopResponse> enableTrailingStop(TrailingStopRequest request) {
        log.info("Received enable trailing request: {} ({} pips)", request.ticket(), request.trailingPips());
        var response = tradeService.enableTrailingStop(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<TrailingStopResponse> disableTrailingStop(DisableTrailingRequest request) {
        log.info("Received disable trailing request: {}", request.ticket());
        var response = tradeService.disableTrailingStop(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<TrailingStopResponse> updateTrailingStop(TrailingStopRequest request) {
        log.info("Received update trailing request: {} -> {} pips", request.ticket(), request.trailingPips());
        var response = tradeService.updateTrailingStop(request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<TrailingStatusResponse> getTrailingStatus(String broker) {
        log.info("Received get trailing status request: broker={}", broker);
        var response = tradeService.getTrailingStatus(broker);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<TrailingStatsResponse> getTrailingStats(String broker) {
        log.info("Received get trailing stats request: broker={}", broker);
        var response = tradeService.getTrailingStats(broker);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // 5. ACCOUNT & SYMBOL
    // ============================================================

    @Override
    public ResponseEntity<AccountResponse> getAccount(String broker) {
        log.info("Received get account request: broker={}", broker);
        var response = tradeService.getAccount(broker);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<SymbolInfoResponse> getSymbolInfo(String broker, String symbol) {
        log.info("Received get symbol info request: broker={}, symbol={}", broker, symbol);
        var response = tradeService.getSymbolInfo(broker, symbol);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<SymbolsResponse> getSymbols(String broker) {
        log.info("Received get symbols request: broker={}", broker);
        var response = tradeService.getSymbols(broker);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // 6. MARKET CONDITIONS
    // ============================================================

    @Override
    public ResponseEntity<MarketStatusResponse> getMarketStatus(String broker, String symbol) {
        log.info("Received get market status request: broker={}, symbol={}", broker, symbol);
        var response = tradeService.getMarketStatus(broker, symbol);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<VolatilityResponse> getMarketVolatility(String broker, String symbol, int lookback) {
        log.info("Received get volatility request: broker={}, symbol={}, lookback={}", broker, symbol, lookback);
        var response = tradeService.getMarketVolatility(broker, symbol, lookback);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<SpreadResponse> getMarketSpread(String broker, String symbol, double maxSpread) {
        log.info("Received get spread request: broker={}, symbol={}, maxSpread={}", broker, symbol, maxSpread);
        var response = tradeService.getMarketSpread(broker, symbol, maxSpread);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<MarketConditionsResponse> getMarketConditions(String broker, String symbol) {
        log.info("Received get market conditions request: broker={}, symbol={}", broker, symbol);
        var response = tradeService.getMarketConditions(broker, symbol);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // 7. MT5 CONNECTION
    // ============================================================

    @Override
    public ResponseEntity<Mt5ConnectionResponse> connectMt5(String broker, Mt5ConnectRequest request) {
        log.info("Received MT5 connect request: broker={}", broker);
        var response = tradeService.connectMt5(broker, request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<SingleBrokerResult> disconnectMt5(String broker) {
        log.info("Received MT5 disconnect request: broker={}", broker);
        var response = tradeService.disconnectMt5(broker);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // 8. HISTORY & CALCULATIONS
    // ============================================================

    @Override
    public ResponseEntity<TradeHistoryResponse> getTradeHistory(String broker, TradeHistoryRequest request) {
        log.info("Received get trade history request: broker={}", broker);
        var response = tradeService.getTradeHistory(broker, request);
        return ResponseEntity.ok(response);
    }

    @Override
    public ResponseEntity<LotCalculationResponse> calculateLot(String broker, LotCalculationRequest request) {
        log.info("Received calculate lot request: broker={}", broker);
        var response = tradeService.calculateLot(broker, request);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // 9. HEALTH
    // ============================================================

    @Override
    public ResponseEntity<HealthResponse> healthCheck(String broker) {
        log.info("Received health check request: broker={}", broker);
        var response = tradeService.healthCheck(broker);
        return ResponseEntity.ok(response);
    }


}