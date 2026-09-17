package com.trading.easytradify.ai.unit;

import com.trading.easytradify.ai.client.PythonAIServiceClient;
import com.trading.easytradify.ai.models.adverserial.AdversarialGenerateRequest;
import com.trading.easytradify.ai.models.adverserial.AdversarialTrainRequest;
import com.trading.easytradify.ai.models.gnn.*;
import com.trading.easytradify.ai.services.AIServiceImpl;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
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
@DisplayName("AI Service Unit Tests")
class AIServiceTest {

    @Mock
    private PythonAIServiceClient clientMock;

    @InjectMocks
    private AIServiceImpl service;

    // ============================================================
    // HEALTH TESTS
    // ============================================================

    @Nested
    @DisplayName("Health Tests")
    class HealthTests {

        @Test
        @DisplayName("Should get health successfully")
        void shouldGetHealthSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validHealthResponse();
            when(clientMock.healthCheck()).thenReturn(expectedResponse);

            var response = service.healthCheck();

            assertNotNull(response);
            assertEquals("healthy", response.status());
            assertTrue(response.initialized());

            verify(clientMock, times(1)).healthCheck();
        }

        @Test
        @DisplayName("Should return error health when client throws exception")
        void shouldReturnErrorHealthWhenClientThrowsException() {
            when(clientMock.healthCheck()).thenThrow(new RuntimeException("Service unavailable"));

            var response = service.healthCheck();

            assertNotNull(response);
            assertEquals("error", response.status());
            assertFalse(response.initialized());

            verify(clientMock, times(1)).healthCheck();
        }
    }

    // ============================================================
    // GNN STATUS TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Status Tests")
    class GnnStatusTests {

        @Test
        @DisplayName("Should get GNN status successfully")
        void shouldGetGnnStatusSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validGnnStatusResponse();
            when(clientMock.getGnnStatus()).thenReturn(expectedResponse);

            var response = service.getGnnStatus();

            assertNotNull(response);
            assertTrue(response.success());
            assertNotNull(response.status());

            verify(clientMock, times(1)).getGnnStatus();
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure")
        void shouldThrowExceptionWhenClientReturnsFailure() {
            var errorResponse = AIServiceTestDataFactory.errorGnnStatusResponse("GNN not initialized");
            when(clientMock.getGnnStatus()).thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getGnnStatus()
            );

            assertEquals(ErrorCodes.GNN_NOT_INITIALIZED, exception.getErrorCode());

            verify(clientMock, times(1)).getGnnStatus();
        }
    }

    // ============================================================
    // GNN CONTEXT TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Context Tests")
    class GnnContextTests {

        @Test
        @DisplayName("Should get GNN context successfully")
        void shouldGetGnnContextSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validGnnContextResponse();
            when(clientMock.getGnnContext(anyString(), any())).thenReturn(expectedResponse);

            var response = service.getGnnContext("EURUSD", null);

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("EURUSD", response.symbol());
            assertNotNull(response.context());

            verify(clientMock, times(1)).getGnnContext("EURUSD", null);
        }

        @Test
        @DisplayName("Should throw TradingException when symbol is empty")
        void shouldThrowExceptionWhenSymbolIsEmpty() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getGnnContext("", null)
            );

            assertEquals(ErrorCodes.GNN_INVALID_SYMBOL, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when symbol is null")
        void shouldThrowExceptionWhenSymbolIsNull() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getGnnContext(null, null)
            );

            assertEquals(ErrorCodes.GNN_INVALID_SYMBOL, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure")
        void shouldThrowExceptionWhenClientReturnsFailure() {
            var errorResponse = AIServiceTestDataFactory.errorGnnContextResponse("Symbol not found");
            when(clientMock.getGnnContext(anyString(), any())).thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getGnnContext("EURUSD", null)
            );

            assertEquals(ErrorCodes.GNN_CONTEXT_FETCH_FAILED, exception.getErrorCode());

            verify(clientMock, times(1)).getGnnContext("EURUSD", null);
        }
    }

    // ============================================================
    // GNN INSIGHTS TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Insights Tests")
    class GnnInsightsTests {

        @Test
        @DisplayName("Should get GNN insights successfully")
        void shouldGetGnnInsightsSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validGnnInsightsResponse();
            when(clientMock.getGnnInsights(anyString(), anyString())).thenReturn(expectedResponse);

            var response = service.getGnnInsights("EURUSD", "BUY");

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("EURUSD", response.symbol());
            assertNotNull(response.insights());

            verify(clientMock, times(1)).getGnnInsights("EURUSD", "BUY");
        }

        @Test
        @DisplayName("Should throw TradingException when analysis direction is invalid")
        void shouldThrowExceptionWhenAnalysisDirectionIsInvalid() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getGnnInsights("EURUSD", "INVALID")
            );

            assertEquals(ErrorCodes.GNN_INVALID_SYMBOL, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }
    }

    // ============================================================
    // GNN CONFLICT TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Conflict Tests")
    class GnnConflictTests {

        @Test
        @DisplayName("Should get GNN conflict successfully")
        void shouldGetGnnConflictSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validGnnConflictResponse();
            when(clientMock.getGnnConflict(anyString(), anyString())).thenReturn(expectedResponse);

            var response = service.getGnnConflict("EURUSD", "BUY");

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("EURUSD", response.symbol());
            assertEquals("BUY", response.yourAnalysis());

            verify(clientMock, times(1)).getGnnConflict("EURUSD", "BUY");
        }

        @Test
        @DisplayName("Should throw TradingException when analysis direction is missing")
        void shouldThrowExceptionWhenAnalysisDirectionIsMissing() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getGnnConflict("EURUSD", null)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when analysis direction is invalid")
        void shouldThrowExceptionWhenAnalysisDirectionIsInvalid() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getGnnConflict("EURUSD", "INVALID")
            );

            assertEquals(ErrorCodes.GNN_INVALID_SYMBOL, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }
    }

    // ============================================================
    // GNN A/B TEST TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN A/B Test Tests")
    class GnnAbTestTests {

        @Test
        @DisplayName("Should get GNN A/B test results successfully")
        void shouldGetGnnAbTestSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validGnnAbTestResponse();
            when(clientMock.getGnnAbTest()).thenReturn(expectedResponse);

            var response = service.getGnnAbTest();

            assertNotNull(response);
            assertTrue(response.success());
            assertNotNull(response.results());

            verify(clientMock, times(1)).getGnnAbTest();
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure")
        void shouldThrowExceptionWhenClientReturnsFailure() {
            var errorResponse = AIServiceTestDataFactory.errorGnnAbTestResponse("No data found");
            when(clientMock.getGnnAbTest()).thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getGnnAbTest()
            );

            assertEquals(ErrorCodes.GNN_AB_TEST_FETCH_FAILED, exception.getErrorCode());

            verify(clientMock, times(1)).getGnnAbTest();
        }
    }

    // ============================================================
    // GNN ROLLOUT TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Rollout Tests")
    class GnnRolloutTests {

        @Test
        @DisplayName("Should set GNN rollout successfully")
        void shouldSetGnnRolloutSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validGnnRolloutResponse();
            when(clientMock.setGnnAbTestRollout(anyDouble())).thenReturn(expectedResponse);

            var response = service.setGnnAbTestRollout(0.5);

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(0.5, response.rollout());

            verify(clientMock, times(1)).setGnnAbTestRollout(0.5);
        }

        @Test
        @DisplayName("Should throw TradingException when rollout is negative")
        void shouldThrowExceptionWhenRolloutIsNegative() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.setGnnAbTestRollout(-0.5)
            );

            assertEquals(ErrorCodes.GNN_ROLLOUT_UPDATE_FAILED, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when rollout is greater than 1")
        void shouldThrowExceptionWhenRolloutIsGreaterThanOne() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.setGnnAbTestRollout(1.5)
            );

            assertEquals(ErrorCodes.GNN_ROLLOUT_UPDATE_FAILED, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }
    }

    // ============================================================
    // GNN TRACK RESULT TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Track Result Tests")
    class GnnTrackResultTests {

        @Test
        @DisplayName("Should track GNN result successfully")
        void shouldTrackGnnResultSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validGnnTrackResultResponse();
            var request = AIServiceTestDataFactory.validGnnTrackResultRequest();

            when(clientMock.trackGnnResult(any())).thenReturn(expectedResponse);

            var response = service.trackGnnResult(request);

            assertNotNull(response);
            assertTrue(response.success());

            verify(clientMock, times(1)).trackGnnResult(request);
        }

        @Test
        @DisplayName("Should throw TradingException when request is null")
        void shouldThrowExceptionWhenRequestIsNull() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.trackGnnResult(null)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when trade ID is null")
        void shouldThrowExceptionWhenTradeIdIsNull() {
            var request = new GnnTrackResultRequest(null, 50.0, 1, true);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.trackGnnResult(request)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when trade ID is zero or negative")
        void shouldThrowExceptionWhenTradeIdIsZeroOrNegative() {
            var request = new GnnTrackResultRequest(0, 50.0, 1, true);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.trackGnnResult(request)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }
    }

    // ============================================================
    // ADVERSARIAL GENERATE TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Generate Tests")
    class AdversarialGenerateTests {

        @Test
        @DisplayName("Should generate adversarial attacks successfully")
        void shouldGenerateAdversarialAttacksSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validAdversarialGenerateResponse();
            var request = AIServiceTestDataFactory.validAdversarialGenerateRequest();

            when(clientMock.generateAdversarialAttacks(any())).thenReturn(expectedResponse);

            var response = service.generateAdversarialAttacks(request);

            assertNotNull(response);
            assertTrue(response.success());
            assertNotNull(response.attackedTrades());

            verify(clientMock, times(1)).generateAdversarialAttacks(request);
        }

        @Test
        @DisplayName("Should throw TradingException when request is null")
        void shouldThrowExceptionWhenRequestIsNull() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.generateAdversarialAttacks(null)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when trade data is missing")
        void shouldThrowExceptionWhenTradeDataIsMissing() {
            var request = new AdversarialGenerateRequest(null, 1, 5);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.generateAdversarialAttacks(request)
            );

            assertEquals(ErrorCodes.ADVERSARIAL_NO_TRADES_PROVIDED, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when outcome is null")
        void shouldThrowExceptionWhenOutcomeIsNull() {
            var trade = Map.<String, Object>of("symbol", "EURUSD");
            var request = new AdversarialGenerateRequest(trade, null, 5);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.generateAdversarialAttacks(request)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }
    }

    // ============================================================
    // ADVERSARIAL TRAIN TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Train Tests")
    class AdversarialTrainTests {

        @Test
        @DisplayName("Should train adversarial successfully")
        void shouldTrainAdversarialSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validAdversarialTrainResponse();
            var request = AIServiceTestDataFactory.validAdversarialTrainRequest();

            when(clientMock.trainAdversarial(any())).thenReturn(expectedResponse);

            var response = service.trainAdversarial(request);

            assertNotNull(response);
            assertTrue(response.success());
            assertNotNull(response.result());

            verify(clientMock, times(1)).trainAdversarial(request);
        }

        @Test
        @DisplayName("Should throw TradingException when request is null")
        void shouldThrowExceptionWhenRequestIsNull() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.trainAdversarial(null)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when trades are missing")
        void shouldThrowExceptionWhenTradesAreMissing() {
            var request = new AdversarialTrainRequest(null, List.of(1), "EURUSD", null, true);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.trainAdversarial(request)
            );

            assertEquals(ErrorCodes.ADVERSARIAL_NO_TRADES_PROVIDED, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when outcomes are missing")
        void shouldThrowExceptionWhenOutcomesAreMissing() {
            var trades = List.<Map<String, Object>>of(Map.of("symbol", "EURUSD"));
            var request = new AdversarialTrainRequest(trades, null, "EURUSD", null, true);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.trainAdversarial(request)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when trades and outcomes length mismatch")
        void shouldThrowExceptionWhenTradesAndOutcomesLengthMismatch() {
            var trades = List.<Map<String, Object>>of(
                    Map.of("symbol", "EURUSD"),
                    Map.of("symbol", "GBPUSD")
            );
            var outcomes = List.of(1);
            var request = new AdversarialTrainRequest(trades, outcomes, "EURUSD", null, true);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.trainAdversarial(request)
            );

            assertEquals(ErrorCodes.ADVERSARIAL_OUTCOMES_MISMATCH, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }
    }

    // ============================================================
    // ADVERSARIAL INTENSITY TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Intensity Tests")
    class AdversarialIntensityTests {

        @Test
        @DisplayName("Should set adversarial intensity successfully")
        void shouldSetAdversarialIntensitySuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validAdversarialIntensityResponse();
            when(clientMock.setAdversarialIntensity(anyDouble())).thenReturn(expectedResponse);

            var response = service.setAdversarialIntensity(0.5);

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(0.5, response.intensity());

            verify(clientMock, times(1)).setAdversarialIntensity(0.5);
        }

        @Test
        @DisplayName("Should throw TradingException when intensity is negative")
        void shouldThrowExceptionWhenIntensityIsNegative() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.setAdversarialIntensity(-0.5)
            );

            assertEquals(ErrorCodes.ADVERSARIAL_INVALID_INTENSITY, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when intensity is greater than 1")
        void shouldThrowExceptionWhenIntensityIsGreaterThanOne() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.setAdversarialIntensity(1.5)
            );

            assertEquals(ErrorCodes.ADVERSARIAL_INVALID_INTENSITY, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }
    }

    // ============================================================
    // ADVERSARIAL ENABLE TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Enable Tests")
    class AdversarialEnableTests {

        @Test
        @DisplayName("Should enable adversarial successfully")
        void shouldEnableAdversarialSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validAdversarialEnableResponse();
            when(clientMock.enableAdversarial(anyBoolean())).thenReturn(expectedResponse);

            var response = service.enableAdversarial(true);

            assertNotNull(response);
            assertTrue(response.success());
            assertTrue(response.enabled());

            verify(clientMock, times(1)).enableAdversarial(true);
        }

        @Test
        @DisplayName("Should disable adversarial successfully")
        void shouldDisableAdversarialSuccessfully() {
            var expectedResponse = AIServiceTestDataFactory.validAdversarialEnableResponse();
            when(clientMock.enableAdversarial(anyBoolean())).thenReturn(expectedResponse);

            var response = service.enableAdversarial(false);

            assertNotNull(response);
            assertTrue(response.success());
            assertTrue(response.enabled());

            verify(clientMock, times(1)).enableAdversarial(false);
        }
    }
}