package com.trading.easytradify.unit.execution;

import com.trading.easytradify.execution.client.PythonExecutionClient;
import com.trading.easytradify.execution.config.broker.BrokerConfig;
import com.trading.easytradify.execution.config.broker.BrokerRegistry;
import com.trading.easytradify.execution.models.*;
import com.trading.easytradify.execution.services.TradeExecutionServiceImpl;
import com.trading.easytradify.unit.TestDataFactory;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("Trade Execution Service - Happy Path Tests")
class TradeExecutionServiceHappyPathTest {

    @Mock
    private PythonExecutionClient pythonClient;

    @Mock
    private BrokerRegistry brokerRegistry;

    @InjectMocks
    private TradeExecutionServiceImpl tradeService;

    private BrokerConfig defaultBroker;
    private BrokerConfig vtBroker;
    private BrokerConfig admiralsBroker;

    @BeforeEach
    void setUp() {
        defaultBroker = TestDataFactory.defaultBroker();
        vtBroker = TestDataFactory.vtBroker();
        admiralsBroker = TestDataFactory.admiralsBroker();

        // Mock broker resolution
        lenient().when(brokerRegistry.getBroker("icmarkets")).thenReturn(defaultBroker);
        lenient().when(brokerRegistry.getBroker("vtmarkets")).thenReturn(vtBroker);
        lenient().when(brokerRegistry.getBroker("admirals")).thenReturn(admiralsBroker);
        lenient().when(brokerRegistry.getBroker(anyString())).thenReturn(defaultBroker);

        lenient().when(brokerRegistry.getDefaultBroker()).thenReturn(defaultBroker);
        lenient().when(brokerRegistry.isBrokerExists("icmarkets")).thenReturn(true);
        lenient().when(brokerRegistry.isBrokerExists("vtmarkets")).thenReturn(true);
        lenient().when(brokerRegistry.isBrokerExists("admirals")).thenReturn(true);
        lenient().when(brokerRegistry.resolveBrokers(anyList())).thenReturn(List.of(defaultBroker));
    }

    // ============================================================
    // TRADE EXECUTION HAPPY PATH TESTS
    // ============================================================

    @Nested
    @DisplayName("Execute Trade Happy Path Tests")
    class ExecuteTradeHappyPathTests {

        @Test
        @DisplayName("Should execute trade successfully on default broker")
        void shouldExecuteTradeSuccessfullyOnDefaultBroker() {
            // Given
            var request = TestDataFactory.validExecuteTradeRequest();
            var successResponse = TestDataFactory.successTradeExecutionResponse();

            when(brokerRegistry.resolveBrokers(anyList())).thenReturn(List.of(defaultBroker));
            when(pythonClient.executeTrade(eq(defaultBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.executeTrade(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(123456789, response.data().ticket());

            verify(pythonClient, times(1))
                    .executeTrade(eq(defaultBroker), any());
        }

        @Test
        @DisplayName("Should execute trade on multiple brokers - stops at first success")
        void shouldExecuteTradeOnMultipleBrokers() {
            // Given
            var request = TestDataFactory.validExecuteTradeRequestWithMultipleBrokers();
            var successResponse = TestDataFactory.successTradeExecutionResponse();

            // First broker succeeds, so second is NOT called
            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(List.of(defaultBroker, vtBroker));
            when(pythonClient.executeTrade(eq(defaultBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.executeTrade(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());

            // Only first broker is called because it succeeded
            verify(pythonClient, times(1))
                    .executeTrade(eq(defaultBroker), any());
            verify(pythonClient, never())
                    .executeTrade(eq(vtBroker), any());
        }

        @Test
        @DisplayName("Should continue to next broker when first broker fails")
        void shouldContinueToNextBrokerWhenFirstBrokerFails() {
            // Given
            var request = TestDataFactory.validExecuteTradeRequestWithMultipleBrokers();
            var successResponse = TestDataFactory.successTradeExecutionResponse();
            var failureResponse = TestDataFactory.failureTradeExecutionResponse("First broker failed");

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(List.of(defaultBroker, vtBroker));
            when(pythonClient.executeTrade(eq(defaultBroker), any()))
                    .thenReturn(failureResponse);
            when(pythonClient.executeTrade(eq(vtBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.executeTrade(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());

            verify(pythonClient, times(1))
                    .executeTrade(eq(defaultBroker), any());
            verify(pythonClient, times(1))
                    .executeTrade(eq(vtBroker), any());
        }

        @Test
        @DisplayName("Should execute trade on all brokers when first fails and second succeeds")
        void shouldExecuteTradeOnAllBrokersWhenFirstFailsAndSecondSucceeds() {
            // Given
            var request = TestDataFactory.validExecuteTradeRequestWithAllBrokers();
            var successResponse = TestDataFactory.successTradeExecutionResponse();
            var failureResponse = TestDataFactory.failureTradeExecutionResponse("Broker failed");
            var allBrokers = TestDataFactory.allBrokers();

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(allBrokers);
            // First broker fails, second succeeds -> stops at second
            when(pythonClient.executeTrade(eq(defaultBroker), any()))
                    .thenReturn(failureResponse);
            when(pythonClient.executeTrade(eq(vtBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.executeTrade(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());

            verify(pythonClient, times(1))
                    .executeTrade(eq(defaultBroker), any());
            verify(pythonClient, times(1))
                    .executeTrade(eq(vtBroker), any());
            verify(pythonClient, never())
                    .executeTrade(eq(admiralsBroker), any());
        }

        @Test
        @DisplayName("Should throw exception when all brokers fail")
        void shouldThrowExceptionWhenAllBrokersFail() {
            // Given
            var request = TestDataFactory.validExecuteTradeRequestWithAllBrokers();
            var failureResponse = TestDataFactory.failureTradeExecutionResponse("All brokers failed");
            var allBrokers = TestDataFactory.allBrokers();

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(allBrokers);
            when(pythonClient.executeTrade(any(BrokerConfig.class), any()))
                    .thenReturn(failureResponse);

            // When & Then
            var exception = assertThrows(
                    com.trading.easytradify.common.exception.TradingException.class,
                    () -> tradeService.executeTrade(request)
            );

            assertTrue(exception.getMessage().contains("failed on all brokers"));

            verify(pythonClient, times(3))
                    .executeTrade(any(BrokerConfig.class), any());
        }
    }

    // ============================================================
    // POSITION MANAGEMENT HAPPY PATH TESTS
    // ============================================================

    @Nested
    @DisplayName("Position Management Happy Path Tests")
    class PositionManagementHappyPathTests {

        @Test
        @DisplayName("Should close position successfully")
        void shouldClosePositionSuccessfully() {
            // Given
            var request = TestDataFactory.validClosePositionRequest();
            var successResponse = TestDataFactory.successClosePositionResponse();

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(List.of(defaultBroker));
            when(pythonClient.closePosition(eq(defaultBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.closePosition(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(123456789, response.data().ticket());
            assertEquals(10.5, response.data().profit());

            verify(pythonClient, times(1))
                    .closePosition(eq(defaultBroker), any());
        }

        @Test
        @DisplayName("Should partial close position successfully")
        void shouldPartialClosePositionSuccessfully() {
            // Given
            var request = TestDataFactory.validPartialCloseRequest();
            var successResponse = TestDataFactory.successPartialCloseResponse();

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(List.of(defaultBroker));
            when(pythonClient.partialClosePosition(eq(defaultBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.partialClosePosition(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(123456789, response.data().ticket());

            verify(pythonClient, times(1))
                    .partialClosePosition(eq(defaultBroker), any());
        }
    }

    // ============================================================
    // STOP LOSS & TAKE PROFIT HAPPY PATH TESTS
    // ============================================================

    @Nested
    @DisplayName("Stop Loss & Take Profit Happy Path Tests")
    class StopLossTakeProfitHappyPathTests {

        @Test
        @DisplayName("Should modify stop loss successfully")
        void shouldModifyStopLossSuccessfully() {
            // Given
            var request = TestDataFactory.validModifyStopLossRequest();
            var successResponse = TestDataFactory.successModifyStopLossResponse();

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(List.of(defaultBroker));
            when(pythonClient.modifyStopLoss(eq(defaultBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.modifyStopLoss(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(123456789, response.data().ticket());
            assertEquals(1.12200, response.data().newSl());

            verify(pythonClient, times(1))
                    .modifyStopLoss(eq(defaultBroker), any());
        }

        @Test
        @DisplayName("Should modify take profit successfully")
        void shouldModifyTakeProfitSuccessfully() {
            // Given
            var request = TestDataFactory.validModifyTakeProfitRequest();
            var successResponse = TestDataFactory.successModifyTakeProfitResponse();

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(List.of(defaultBroker));
            when(pythonClient.modifyTakeProfit(eq(defaultBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.modifyTakeProfit(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(123456789, response.data().ticket());
            assertEquals(1.12600, response.data().newTp());

            verify(pythonClient, times(1))
                    .modifyTakeProfit(eq(defaultBroker), any());
        }
    }

    // ============================================================
    // TRAILING STOP HAPPY PATH TESTS
    // ============================================================

    @Nested
    @DisplayName("Trailing Stop Happy Path Tests")
    class TrailingStopHappyPathTests {

        @Test
        @DisplayName("Should enable trailing stop successfully")
        void shouldEnableTrailingStopSuccessfully() {
            // Given
            var request = TestDataFactory.validTrailingStopRequest();
            var successResponse = TestDataFactory.successTrailingStopResponse();

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(List.of(defaultBroker));
            when(pythonClient.enableTrailingStop(eq(defaultBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.enableTrailingStop(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(123456789, response.data().ticket());
            assertEquals("icmarkets", response.data().symbol());
            assertEquals(5.0, response.data().trailingPips());

            verify(pythonClient, times(1))
                    .enableTrailingStop(eq(defaultBroker), any());
        }

        @Test
        @DisplayName("Should disable trailing stop successfully")
        void shouldDisableTrailingStopSuccessfully() {
            // Given
            var request = new DisableTrailingRequest(123456789, List.of("icmarkets"));
            var successResponse = TestDataFactory.successTrailingStopResponse();

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(List.of(defaultBroker));
            when(pythonClient.disableTrailingStop(eq(defaultBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.disableTrailingStop(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());

            verify(pythonClient, times(1))
                    .disableTrailingStop(eq(defaultBroker), any());
        }

        @Test
        @DisplayName("Should update trailing stop successfully")
        void shouldUpdateTrailingStopSuccessfully() {
            // Given
            var request = new TrailingStopRequest(123456789, 7.5, List.of("icmarkets"));
            var successResponse = TestDataFactory.successTrailingStopResponse();

            when(brokerRegistry.resolveBrokers(anyList()))
                    .thenReturn(List.of(defaultBroker));
            when(pythonClient.updateTrailingStop(eq(defaultBroker), any()))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.updateTrailingStop(request);

            // Then
            assertNotNull(response);
            assertTrue(response.success());

            verify(pythonClient, times(1))
                    .updateTrailingStop(eq(defaultBroker), any());
        }
    }

    // ============================================================
    // QUERY HAPPY PATH TESTS
    // ============================================================

    @Nested
    @DisplayName("Query Happy Path Tests")
    class QueryHappyPathTests {

        @Test
        @DisplayName("Should get positions successfully")
        void shouldGetPositionsSuccessfully() {
            // Given
            var successResponse = TestDataFactory.validPositionsResponse();

            when(brokerRegistry.getBroker("icmarkets")).thenReturn(defaultBroker);
            when(pythonClient.getPositions(eq(defaultBroker), eq("EURUSD"), eq(123456)))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.getPositions("icmarkets", "EURUSD", 123456);

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(1, response.count());

            verify(pythonClient, times(1))
                    .getPositions(eq(defaultBroker), eq("EURUSD"), eq(123456));
        }

        @Test
        @DisplayName("Should get account info successfully")
        void shouldGetAccountInfoSuccessfully() {
            // Given
            var successResponse = TestDataFactory.validAccountResponse();

            when(brokerRegistry.getBroker("icmarkets")).thenReturn(defaultBroker);
            when(pythonClient.getAccount(eq(defaultBroker)))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.getAccount("icmarkets");

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertNotNull(response.data());
            assertEquals(10000.0, response.data().get("balance"));

            verify(pythonClient, times(1))
                    .getAccount(eq(defaultBroker));
        }

        @Test
        @DisplayName("Should get symbol info successfully")
        void shouldGetSymbolInfoSuccessfully() {
            // Given
            var successResponse = TestDataFactory.validSymbolInfoResponse();

            when(brokerRegistry.getBroker("icmarkets")).thenReturn(defaultBroker);
            when(pythonClient.getSymbolInfo(eq(defaultBroker), eq("EURUSD")))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.getSymbolInfo("icmarkets", "EURUSD");

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("EURUSD", response.name());
            assertEquals("Euro vs US Dollar", response.description());

            verify(pythonClient, times(1))
                    .getSymbolInfo(eq(defaultBroker), eq("EURUSD"));
        }

        @Test
        @DisplayName("Should get all symbols successfully")
        void shouldGetAllSymbolsSuccessfully() {
            // Given
            var symbol = TestDataFactory.validSymbolInfoResponse();
            var successResponse = SymbolsResponse.success(1, List.of(symbol));

            when(brokerRegistry.getBroker("icmarkets")).thenReturn(defaultBroker);
            when(pythonClient.getSymbols(eq(defaultBroker)))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.getSymbols("icmarkets");

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(1, response.count());

            verify(pythonClient, times(1))
                    .getSymbols(eq(defaultBroker));
        }

        @Test
        @DisplayName("Should get trailing status successfully")
        void shouldGetTrailingStatusSuccessfully() {
            // Given
            var activeTrails = List.<Map<String, Object>>of(
                    Map.of("ticket", 123456789, "symbol", "EURUSD", "step_pips", 5.0)
            );
            var successResponse = TrailingStatusResponse.success(activeTrails);

            when(brokerRegistry.getBroker("icmarkets")).thenReturn(defaultBroker);
            when(pythonClient.getTrailingStatus(eq(defaultBroker)))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.getTrailingStatus("icmarkets");

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(1, response.count());

            verify(pythonClient, times(1))
                    .getTrailingStatus(eq(defaultBroker));
        }

        @Test
        @DisplayName("Should get market conditions successfully")
        void shouldGetMarketConditionsSuccessfully() {
            // Given
            var successResponse = TestDataFactory.validMarketConditionsResponse();

            when(brokerRegistry.getBroker("icmarkets")).thenReturn(defaultBroker);
            when(pythonClient.getMarketConditions(eq(defaultBroker), eq("EURUSD")))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.getMarketConditions("icmarkets", "EURUSD");

            // Then
            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("EURUSD", response.symbol());

            verify(pythonClient, times(1))
                    .getMarketConditions(eq(defaultBroker), eq("EURUSD"));
        }

        @Test
        @DisplayName("Should check health successfully")
        void shouldCheckHealthSuccessfully() {
            // Given
            var successResponse = TestDataFactory.validHealthResponse();

            when(brokerRegistry.getBroker("icmarkets")).thenReturn(defaultBroker);
            when(pythonClient.healthCheck(eq(defaultBroker)))
                    .thenReturn(successResponse);

            // When
            var response = tradeService.healthCheck("icmarkets");

            // Then
            assertNotNull(response);
            assertEquals("operational", response.status());
            assertTrue(response.mt5Connected());

            verify(pythonClient, times(1))
                    .healthCheck(eq(defaultBroker));
        }
    }
}