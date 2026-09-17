package com.trading.easytradify.unit.execution;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.execution.models.WebhookTrailingRequest;
import com.trading.easytradify.execution.services.CopyTradeServiceImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("Copy Trade Service Unit Tests")
class CopyTradeServiceTest {

    private PythonCopyTradeClientMock clientMock;
    private CopyTradeServiceImpl service;

    @BeforeEach
    void setUp() {
        clientMock = new PythonCopyTradeClientMock();
        service = new CopyTradeServiceImpl(clientMock);
    }

    // ============================================================
    // EXECUTE COPY TRADE TESTS
    // ============================================================

    @Nested
    @DisplayName("Execute Copy Trade Tests")
    class ExecuteCopyTradeTests {

        @Test
        @DisplayName("Should execute copy trade successfully")
        void shouldExecuteCopyTradeSuccessfully() {
            clientMock.withSuccess();
            var request = CopyTradeTestDataFactory.validCopyTradeRequest();

            var response = service.executeCopyTrade(request);

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("EURUSD", response.symbol());
            assertEquals(123456789, response.ticket());
        }

        @Test
        @DisplayName("Should throw TradingException when symbol is empty")
        void shouldThrowExceptionWhenSymbolIsEmpty() {
            var request = CopyTradeTestDataFactory.emptySymbolCopyTradeRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.executeCopyTrade(request)
            );

            assertEquals(ErrorCodes.TRADE_INVALID_SYMBOL, exception.getErrorCode());
        }

        @Test
        @DisplayName("Should throw TradingException when symbol is null")
        void shouldThrowExceptionWhenSymbolIsNull() {
            var request = CopyTradeTestDataFactory.nullSymbolCopyTradeRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.executeCopyTrade(request)
            );

            assertEquals(ErrorCodes.TRADE_INVALID_SYMBOL, exception.getErrorCode());
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure")
        void shouldThrowExceptionWhenClientReturnsFailure() {
            clientMock.withFailure("Client execution failed");
            var request = CopyTradeTestDataFactory.validCopyTradeRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.executeCopyTrade(request)
            );

            assertEquals(ErrorCodes.TRADE_EXECUTION_FAILED, exception.getErrorCode());
        }
    }

    // ============================================================
    // WEBHOOK TRADE TESTS
    // ============================================================

    @Nested
    @DisplayName("Webhook Trade Tests")
    class WebhookTradeTests {

        @Test
        @DisplayName("Should handle webhook trade successfully")
        void shouldHandleWebhookTradeSuccessfully() {
            clientMock.withSuccess();
            var request = CopyTradeTestDataFactory.validWebhookTradeRequest();

            var response = service.handleWebhookTrade(request);

            assertNotNull(response);
            assertEquals("success", response.status());
        }

        @Test
        @DisplayName("Should throw TradingException when symbol is null")
        void shouldThrowExceptionWhenSymbolIsNull() {
            var request = CopyTradeTestDataFactory.nullSymbolWebhookTradeRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.handleWebhookTrade(request)
            );

            assertEquals(ErrorCodes.TRADE_INVALID_SYMBOL, exception.getErrorCode());
        }

        @Test
        @DisplayName("Should throw TradingException when ticket is null")
        void shouldThrowExceptionWhenTicketIsNull() {
            var request = CopyTradeTestDataFactory.nullTicketWebhookTradeRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.handleWebhookTrade(request)
            );

            assertEquals(ErrorCodes.POSITION_NOT_FOUND, exception.getErrorCode());
        }

        @Test
        @DisplayName("Should throw TradingException when ticket is zero")
        void shouldThrowExceptionWhenTicketIsZero() {
            var request = CopyTradeTestDataFactory.zeroTicketWebhookTradeRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.handleWebhookTrade(request)
            );

            assertEquals(ErrorCodes.POSITION_NOT_FOUND, exception.getErrorCode());
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure")
        void shouldThrowExceptionWhenClientReturnsFailure() {
            clientMock.withFailure("Webhook processing failed");
            var request = CopyTradeTestDataFactory.validWebhookTradeRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.handleWebhookTrade(request)
            );

            assertEquals(ErrorCodes.WEBHOOK_PROCESSING_FAILED, exception.getErrorCode());
        }
    }

    // ============================================================
    // WEBHOOK TRAILING TESTS
    // ============================================================

    @Nested
    @DisplayName("Webhook Trailing Tests")
    class WebhookTrailingTests {

        @Test
        @DisplayName("Should handle webhook trailing successfully")
        void shouldHandleWebhookTrailingSuccessfully() {
            clientMock.withSuccess();
            var request = CopyTradeTestDataFactory.validWebhookTrailingRequest();

            var response = service.handleWebhookTrailing(request);

            assertNotNull(response);
            assertEquals("success", response.status());
        }

        @Test
        @DisplayName("Should throw TradingException when ticket is null")
        void shouldThrowExceptionWhenTicketIsNull() {
            var request = CopyTradeTestDataFactory.nullTicketWebhookTrailingRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.handleWebhookTrailing(request)
            );

            assertEquals(ErrorCodes.POSITION_NOT_FOUND, exception.getErrorCode());
        }

        @Test
        @DisplayName("Should throw TradingException when ticket is zero")
        void shouldThrowExceptionWhenTicketIsZero() {
            var request = CopyTradeTestDataFactory.zeroTicketWebhookTrailingRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.handleWebhookTrailing(request)
            );

            assertEquals(ErrorCodes.POSITION_NOT_FOUND, exception.getErrorCode());
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure")
        void shouldThrowExceptionWhenClientReturnsFailure() {
            clientMock.withFailure("Webhook processing failed");
            var request = CopyTradeTestDataFactory.validWebhookTrailingRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.handleWebhookTrailing(request)
            );

            assertEquals(ErrorCodes.WEBHOOK_PROCESSING_FAILED, exception.getErrorCode());
        }

        // ============================================================
        // ✅ FIXED: Test record validation directly, not through service
        // ============================================================

        @Test
        @DisplayName("WebhookTrailingRequest should throw IllegalArgumentException when SL price is negative")
        void shouldThrowIllegalArgumentExceptionWhenSlPriceIsNegative() {
            // When & Then - the exception is thrown by the record constructor
            assertThrows(
                    IllegalArgumentException.class,
                    () -> new WebhookTrailingRequest(
                            123456789,
                            "EURUSD",
                            "ENABLE",
                            -1.12400,  // negative SL price
                            5.0,
                            5.0,
                            1.12450,
                            1.12345,
                            Instant.now().toString()
                    )
            );
        }

        @Test
        @DisplayName("WebhookTrailingRequest should throw IllegalArgumentException when step pips is zero")
        void shouldThrowIllegalArgumentExceptionWhenStepPipsIsZero() {
            // When & Then - the exception is thrown by the record constructor
            assertThrows(
                    IllegalArgumentException.class,
                    () -> new WebhookTrailingRequest(
                            123456789,
                            "EURUSD",
                            "ENABLE",
                            1.12400,
                            5.0,
                            0.0,  // zero step pips
                            1.12450,
                            1.12345,
                            Instant.now().toString()
                    )
            );
        }
    }

    // ============================================================
    // WEBHOOK TEST TESTS
    // ============================================================

    @Nested
    @DisplayName("Webhook Test Tests")
    class WebhookTestTests {

        @Test
        @DisplayName("Should handle webhook test successfully")
        void shouldHandleWebhookTestSuccessfully() {
            clientMock.withSuccess();
            var payload = Map.of("test", "data");

            var response = service.webhookTest(payload);

            assertNotNull(response);
            assertEquals("success", response.status());
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure")
        void shouldThrowExceptionWhenClientReturnsFailure() {
            clientMock.withFailure("Test failed");
            var payload = Map.of("test", "data");

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.webhookTest(payload)
            );

            assertEquals(ErrorCodes.WEBHOOK_PROCESSING_FAILED, exception.getErrorCode());
        }
    }

    // ============================================================
    // STATUS & HEALTH TESTS
    // ============================================================

    @Nested
    @DisplayName("Status & Health Tests")
    class StatusHealthTests {

        @Test
        @DisplayName("Should get webhook health successfully")
        void shouldGetWebhookHealthSuccessfully() {
            var response = service.getWebhookHealth();

            assertNotNull(response);
            assertEquals("healthy", response.get("status"));
        }

        @Test
        @DisplayName("Should get status successfully")
        void shouldGetStatusSuccessfully() {
            var response = service.getStatus();

            assertNotNull(response);
            assertTrue((Boolean) response.get("running"));
        }

        @Test
        @DisplayName("Should perform health check successfully")
        void shouldPerformHealthCheckSuccessfully() {
            clientMock.withSuccess();

            var response = service.healthCheck();

            assertNotNull(response);
            assertEquals("operational", response.status());
        }
    }
}