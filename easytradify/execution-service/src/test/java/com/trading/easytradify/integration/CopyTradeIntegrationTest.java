package com.trading.easytradify.integration;

import com.trading.easytradify.execution.models.CopyTradeResponse;
import com.trading.easytradify.execution.models.HealthResponse;
import com.trading.easytradify.execution.models.WebhookResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("Copy Trade Integration Tests")
class CopyTradeIntegrationTest extends BaseIntegrationTest {

    private String copyTradeBaseUrl;

    @BeforeEach
    void setUp() {
        copyTradeBaseUrl = baseUrl + "/api/v1/copy-trade";
        System.out.println(">>> Copy Trade Base URL: " + copyTradeBaseUrl);
    }

    // ============================================================
    // 1. COPY TRADE EXECUTION TESTS
    // ============================================================

    @Nested
    @DisplayName("Copy Trade Execution Tests")
    class CopyTradeExecutionTests {

        @Test
        @DisplayName("Should execute copy trade successfully")
        void shouldExecuteCopyTradeSuccessfully() {
            // Given
            var url = copyTradeBaseUrl + "/execute";
            var request = CopyTradeIntegrationTestDataFactory.validCopyTradeRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(CopyTradeResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("EURUSD", body.symbol());
            assertNotNull(body.ticket());
        }

        @Test
        @DisplayName("Should fail when symbol is empty")
        void shouldFailWhenSymbolIsEmpty() {
            // Given
            var url = copyTradeBaseUrl + "/execute";
            var request = CopyTradeIntegrationTestDataFactory.copyTradeRequestWithEmptySymbol();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(CopyTradeResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when analysis result is null")
        void shouldFailWhenAnalysisResultIsNull() {
            // Given
            var url = copyTradeBaseUrl + "/execute";
            var request = CopyTradeIntegrationTestDataFactory.copyTradeRequestWithNullAnalysis();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(CopyTradeResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when final_verdict is missing")
        void shouldFailWhenFinalVerdictIsMissing() {
            // Given
            var url = copyTradeBaseUrl + "/execute";
            var request = CopyTradeIntegrationTestDataFactory.copyTradeRequestWithMissingFinalVerdict();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(CopyTradeResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 2. WEBHOOK TRADE TESTS
    // ============================================================

    @Nested
    @DisplayName("Webhook Trade Tests")
    class WebhookTradeTests {

        @Test
        @DisplayName("Should handle webhook trade successfully")
        void shouldHandleWebhookTradeSuccessfully() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/trade";
            var request = CopyTradeIntegrationTestDataFactory.validWebhookTradeRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(WebhookResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("success", body.status());
        }

        @Test
        @DisplayName("Should fail when symbol is null")
        void shouldFailWhenSymbolIsNull() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/trade";
            var request = CopyTradeIntegrationTestDataFactory.webhookTradeRequestWithNullSymbol();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(WebhookResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when ticket is null")
        void shouldFailWhenTicketIsNull() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/trade";
            var request = CopyTradeIntegrationTestDataFactory.webhookTradeRequestWithNullTicket();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(WebhookResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when ticket is zero")
        void shouldFailWhenTicketIsZero() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/trade";
            var request = CopyTradeIntegrationTestDataFactory.webhookTradeRequestWithZeroTicket();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(WebhookResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 3. WEBHOOK TRAILING TESTS
    // ============================================================

    @Nested
    @DisplayName("Webhook Trailing Tests")
    class WebhookTrailingTests {

        @Test
        @DisplayName("Should handle webhook trailing successfully")
        void shouldHandleWebhookTrailingSuccessfully() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/trailing";
            var request = CopyTradeIntegrationTestDataFactory.validWebhookTrailingRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(WebhookResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("success", body.status());
        }

        @Test
        @DisplayName("Should fail when ticket is null")
        void shouldFailWhenTicketIsNull() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/trailing";
            var request = CopyTradeIntegrationTestDataFactory.webhookTrailingRequestWithNullTicket();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(WebhookResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when ticket is zero")
        void shouldFailWhenTicketIsZero() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/trailing";
            var request = CopyTradeIntegrationTestDataFactory.webhookTrailingRequestWithZeroTicket();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(WebhookResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 4. WEBHOOK TEST TESTS
    // ============================================================

    @Nested
    @DisplayName("Webhook Test Tests")
    class WebhookTestTests {

        @Test
        @DisplayName("Should handle webhook test successfully")
        void shouldHandleWebhookTestSuccessfully() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/test";
            var payload = CopyTradeIntegrationTestDataFactory.webhookTestPayload();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(payload)
                    .retrieve()
                    .toEntity(WebhookResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("success", body.status());
        }
    }

    // ============================================================
    // 5. STATUS & HEALTH TESTS
    // ============================================================

    @Nested
    @DisplayName("Status & Health Tests")
    class StatusHealthTests {

        @Test
        @DisplayName("Should get webhook health")
        void shouldGetWebhookHealth() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/health";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(Map.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("healthy", body.get("status"));
        }

        @Test
        @DisplayName("Should get webhook debug")
        void shouldGetWebhookDebug() {
            // Given
            var url = copyTradeBaseUrl + "/webhook/debug";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(Map.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue((Boolean) body.get("executor_initialized"));
            assertTrue((Boolean) body.get("executor_running"));
        }

        @Test
        @DisplayName("Should get executor status")
        void shouldGetExecutorStatus() {
            // Given
            var url = copyTradeBaseUrl + "/status";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(Map.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue((Boolean) body.get("running"));
            assertTrue(body.containsKey("stats"));
        }

        @Test
        @DisplayName("Should get health")
        void shouldGetHealth() {
            // Given
            var url = copyTradeBaseUrl + "/health";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(HealthResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("operational", body.status());
        }

        @Test
        @DisplayName("Should get health without API key (public endpoint)")
        void shouldGetHealthWithoutApiKey() {
            // Given
            var url = copyTradeBaseUrl + "/health";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .retrieve()
                    .toEntity(HealthResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("operational", body.status());
        }
    }

    // ============================================================
    // 6. AUTHENTICATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Authentication Tests")
    class AuthenticationTests {

        @Test
        @DisplayName("Should fail when API key is missing")
        void shouldFailWhenApiKeyIsMissing() {
            // Given
            var url = copyTradeBaseUrl + "/execute";
            var request = CopyTradeIntegrationTestDataFactory.validCopyTradeRequest();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(CopyTradeResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when API key is invalid")
        void shouldFailWhenApiKeyIsInvalid() {
            // Given
            var url = copyTradeBaseUrl + "/execute";
            var request = CopyTradeIntegrationTestDataFactory.validCopyTradeRequest();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", "invalid-key")
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(CopyTradeResponse.class)
                        .block();
            });
        }
    }
}