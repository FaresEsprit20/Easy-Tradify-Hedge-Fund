package com.trading.easytradify.unit.execution;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.execution.client.PythonExecutionClient;
import com.trading.easytradify.execution.config.broker.BrokerConfig;
import com.trading.easytradify.execution.config.broker.BrokerRegistry;
import com.trading.easytradify.execution.models.*;
import com.trading.easytradify.execution.services.TradeExecutionServiceImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("Trade Execution Service - Validation Tests")
class TradeExecutionServiceValidationTest {

    @Mock
    private PythonExecutionClient pythonClient;

    @Mock
    private BrokerRegistry brokerRegistry;

    @InjectMocks
    private TradeExecutionServiceImpl tradeService;

    @BeforeEach
    void setUp() {
        BrokerConfig defaultBroker = BrokerConfig.icMarkets();

        lenient().when(brokerRegistry.resolveBrokers(anyList())).thenReturn(List.of(defaultBroker));
        lenient().when(brokerRegistry.isBrokerExists("icmarkets")).thenReturn(true);
        lenient().when(brokerRegistry.isBrokerExists("vtmarkets")).thenReturn(true);
        lenient().when(brokerRegistry.isBrokerExists("admirals")).thenReturn(true);
    }

    // ============================================================
    // EXECUTE TRADE VALIDATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Execute Trade Validation Tests")
    class ExecuteTradeValidationTests {

        @Test
        @DisplayName("Should throw TradingException when symbol is null")
        void shouldThrowExceptionWhenSymbolIsNull() {
            var request = ExecuteTradeRequest.builder()
                    .symbol(null)
                    .orderType(OrderSide.BUY)
                    .strategyMagic(123456)
                    .fixedTradeSizeUsd(200.0)
                    .riskPerTrade(0.05)
                    .maxSpread(30.0)
                    .brokers(List.of("icmarkets"))
                    .build();

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.executeTrade(request)
            );

            assertEquals(ErrorCodes.TRADE_INVALID_SYMBOL, exception.getErrorCode());
            assertEquals("Symbol cannot be null or empty", exception.getMessage());
            verifyNoInteractions(pythonClient);
        }

        @Test
        @DisplayName("Should throw TradingException when symbol is empty")
        void shouldThrowExceptionWhenSymbolIsEmpty() {
            var request = ExecuteTradeRequest.builder()
                    .symbol("")
                    .orderType(OrderSide.BUY)
                    .strategyMagic(123456)
                    .fixedTradeSizeUsd(200.0)
                    .riskPerTrade(0.05)
                    .maxSpread(30.0)
                    .brokers(List.of("icmarkets"))
                    .build();

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.executeTrade(request)
            );

            assertEquals(ErrorCodes.TRADE_INVALID_SYMBOL, exception.getErrorCode());
            verifyNoInteractions(pythonClient);
        }

        @Test
        @DisplayName("Should throw TradingException when trade size is negative")
        void shouldThrowExceptionWhenTradeSizeIsNegative() {
            var request = ExecuteTradeRequest.builder()
                    .symbol("EURUSD")
                    .orderType(OrderSide.BUY)
                    .strategyMagic(123456)
                    .fixedTradeSizeUsd(-100.0)
                    .riskPerTrade(0.05)
                    .maxSpread(30.0)
                    .brokers(List.of("icmarkets"))
                    .build();

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.executeTrade(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Trade size must be positive"));
            verifyNoInteractions(pythonClient);
        }

        @Test
        @DisplayName("Should throw TradingException when trade size is zero")
        void shouldThrowExceptionWhenTradeSizeIsZero() {
            var request = ExecuteTradeRequest.builder()
                    .symbol("EURUSD")
                    .orderType(OrderSide.BUY)
                    .strategyMagic(123456)
                    .fixedTradeSizeUsd(0.0)
                    .riskPerTrade(0.05)
                    .maxSpread(30.0)
                    .brokers(List.of("icmarkets"))
                    .build();

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.executeTrade(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
        }

        @Test
        @DisplayName("Should throw TradingException when risk per trade is negative")
        void shouldThrowExceptionWhenRiskPerTradeIsNegative() {
            var request = ExecuteTradeRequest.builder()
                    .symbol("EURUSD")
                    .orderType(OrderSide.BUY)
                    .strategyMagic(123456)
                    .fixedTradeSizeUsd(200.0)
                    .riskPerTrade(-0.05)
                    .maxSpread(30.0)
                    .brokers(List.of("icmarkets"))
                    .build();

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.executeTrade(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Risk per trade must be positive"));
        }

        @Test
        @DisplayName("Should throw TradingException when max spread is negative")
        void shouldThrowExceptionWhenMaxSpreadIsNegative() {
            var request = ExecuteTradeRequest.builder()
                    .symbol("EURUSD")
                    .orderType(OrderSide.BUY)
                    .strategyMagic(123456)
                    .fixedTradeSizeUsd(200.0)
                    .riskPerTrade(0.05)
                    .maxSpread(-10.0)
                    .brokers(List.of("icmarkets"))
                    .build();

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.executeTrade(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Max spread must be positive"));
        }

        @Test
        @DisplayName("Should throw TradingException when broker not found")
        void shouldThrowExceptionWhenBrokerNotFound() {
            when(brokerRegistry.isBrokerExists("unknown")).thenReturn(false);

            var request = ExecuteTradeRequest.builder()
                    .symbol("EURUSD")
                    .orderType(OrderSide.BUY)
                    .strategyMagic(123456)
                    .fixedTradeSizeUsd(200.0)
                    .riskPerTrade(0.05)
                    .maxSpread(30.0)
                    .brokers(List.of("unknown"))
                    .build();

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.executeTrade(request)
            );

            assertEquals(ErrorCodes.BROKER_NOT_FOUND, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Broker not found: unknown"));
            verifyNoInteractions(pythonClient);
        }
    }

    // ============================================================
    // CLOSE POSITION VALIDATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Close Position Validation Tests")
    class ClosePositionValidationTests {

        @Test
        @DisplayName("Should throw TradingException when ticket is zero")
        void shouldThrowExceptionWhenTicketIsZero() {
            var request = new ClosePositionRequest(0, 20, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.closePosition(request)
            );

            assertEquals(ErrorCodes.POSITION_NOT_FOUND, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Invalid ticket number: 0"));
            verifyNoInteractions(pythonClient);
        }

        @Test
        @DisplayName("Should throw TradingException when ticket is negative")
        void shouldThrowExceptionWhenTicketIsNegative() {
            var request = new ClosePositionRequest(-123, 20, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.closePosition(request)
            );

            assertEquals(ErrorCodes.POSITION_NOT_FOUND, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Invalid ticket number: -123"));
        }
    }

    // ============================================================
    // PARTIAL CLOSE VALIDATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Partial Close Validation Tests")
    class PartialCloseValidationTests {

        @Test
        @DisplayName("Should throw TradingException when volume to close is zero")
        void shouldThrowExceptionWhenVolumeToCloseIsZero() {
            var request = new PartialCloseRequest(123456789, 0.0, 20, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.partialClosePosition(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Volume to close must be positive"));
        }

        @Test
        @DisplayName("Should throw TradingException when volume to close is negative")
        void shouldThrowExceptionWhenVolumeToCloseIsNegative() {
            var request = new PartialCloseRequest(123456789, -0.05, 20, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.partialClosePosition(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
        }
    }

    // ============================================================
    // MODIFY STOP LOSS VALIDATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Modify Stop Loss Validation Tests")
    class ModifyStopLossValidationTests {

        @Test
        @DisplayName("Should throw TradingException when SL price is zero")
        void shouldThrowExceptionWhenSlPriceIsZero() {
            var request = new ModifyStopLossRequest(123456789, 0.0, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.modifyStopLoss(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Stop loss price must be positive"));
        }

        @Test
        @DisplayName("Should throw TradingException when SL price is negative")
        void shouldThrowExceptionWhenSlPriceIsNegative() {
            var request = new ModifyStopLossRequest(123456789, -1.0, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.modifyStopLoss(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
        }
    }

    // ============================================================
    // MODIFY TAKE PROFIT VALIDATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Modify Take Profit Validation Tests")
    class ModifyTakeProfitValidationTests {

        @Test
        @DisplayName("Should throw TradingException when TP price is zero")
        void shouldThrowExceptionWhenTpPriceIsZero() {
            var request = new ModifyTakeProfitRequest(123456789, 0.0, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.modifyTakeProfit(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Take profit price must be positive"));
        }

        @Test
        @DisplayName("Should throw TradingException when TP price is negative")
        void shouldThrowExceptionWhenTpPriceIsNegative() {
            var request = new ModifyTakeProfitRequest(123456789, -1.0, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.modifyTakeProfit(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
        }
    }

    // ============================================================
    // TRAILING STOP VALIDATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Trailing Stop Validation Tests")
    class TrailingStopValidationTests {

        @Test
        @DisplayName("Should throw TradingException when ticket is zero")
        void shouldThrowExceptionWhenTicketIsZero() {
            var request = new TrailingStopRequest(0, 5.0, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.enableTrailingStop(request)
            );

            assertEquals(ErrorCodes.POSITION_NOT_FOUND, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Invalid ticket number: 0"));
        }

        @Test
        @DisplayName("Should throw TradingException when ticket is negative")
        void shouldThrowExceptionWhenTicketIsNegative() {
            var request = new TrailingStopRequest(-123, 5.0, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.enableTrailingStop(request)
            );

            assertEquals(ErrorCodes.POSITION_NOT_FOUND, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Invalid ticket number: -123"));
        }

        @Test
        @DisplayName("Should throw TradingException when disabling trailing with invalid ticket")
        void shouldThrowExceptionWhenDisablingTrailingWithInvalidTicket() {
            var request = new DisableTrailingRequest(0, List.of("icmarkets"));

            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.disableTrailingStop(request)
            );

            assertEquals(ErrorCodes.POSITION_NOT_FOUND, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Invalid ticket number: 0"));
        }
    }

    // ============================================================
    // SYMBOL INFO VALIDATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Symbol Info Validation Tests")
    class SymbolInfoValidationTests {

        @Test
        @DisplayName("Should throw TradingException when symbol is null")
        void shouldThrowExceptionWhenSymbolIsNull() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.getSymbolInfo("icmarkets", null)
            );

            assertEquals(ErrorCodes.TRADE_INVALID_SYMBOL, exception.getErrorCode());
            assertEquals("Symbol cannot be null or empty", exception.getMessage());
            verifyNoInteractions(pythonClient);
        }

        @Test
        @DisplayName("Should throw TradingException when symbol is empty")
        void shouldThrowExceptionWhenSymbolIsEmpty() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.getSymbolInfo("icmarkets", "")
            );

            assertEquals(ErrorCodes.TRADE_INVALID_SYMBOL, exception.getErrorCode());
        }
    }

    // ============================================================
    // MARKET VOLATILITY VALIDATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Market Volatility Validation Tests")
    class MarketVolatilityValidationTests {

        @Test
        @DisplayName("Should throw TradingException when lookback period is zero")
        void shouldThrowExceptionWhenLookbackPeriodIsZero() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.getMarketVolatility("icmarkets", "EURUSD", 0)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Lookback period must be positive"));
        }

        @Test
        @DisplayName("Should throw TradingException when lookback period is negative")
        void shouldThrowExceptionWhenLookbackPeriodIsNegative() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.getMarketVolatility("icmarkets", "EURUSD", -5)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Lookback period must be positive"));
        }
    }

    // ============================================================
    // MARKET SPREAD VALIDATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Market Spread Validation Tests")
    class MarketSpreadValidationTests {

        @Test
        @DisplayName("Should throw TradingException when max spread is zero")
        void shouldThrowExceptionWhenMaxSpreadIsZero() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.getMarketSpread("icmarkets", "EURUSD", 0)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Max spread must be positive"));
        }

        @Test
        @DisplayName("Should throw TradingException when max spread is negative")
        void shouldThrowExceptionWhenMaxSpreadIsNegative() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> tradeService.getMarketSpread("icmarkets", "EURUSD", -10)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Max spread must be positive"));
        }
    }
}