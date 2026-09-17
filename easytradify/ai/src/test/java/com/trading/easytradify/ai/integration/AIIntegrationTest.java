package com.trading.easytradify.ai.integration;

import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.adverserial.*;
import com.trading.easytradify.ai.models.gnn.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.util.Objects;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("AI Service Integration Tests")
class AIIntegrationTest extends BaseAIIntegrationTest {

    @BeforeEach
    void setUp() {
        System.out.println(">>> AI Service Base URL: " + aiBaseUrl);
    }

    // ============================================================
    // 1. HEALTH CHECK TESTS
    // ============================================================

    @Nested
    @DisplayName("Health Check Tests")
    class HealthCheckTests {

        @Test
        @DisplayName("Should get health successfully")
        void shouldGetHealthSuccessfully() {
            // Given
            var url = baseUrl + "/health";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .retrieve()
                    .toEntity(AIHealthResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("healthy", body.status());
            assertEquals("ai_controller", body.service());
            assertEquals(5002, body.port());
        }

        @Test
        @DisplayName("Should get health without API key (public endpoint)")
        void shouldGetHealthWithoutApiKey() {
            // Given
            var url = baseUrl + "/health";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .retrieve()
                    .toEntity(AIHealthResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("healthy", body.status());
        }
    }

    // ============================================================
    // 2. GNN STATUS TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Status Tests")
    class GnnStatusTests {

        @Test
        @DisplayName("Should get GNN status successfully")
        void shouldGetGnnStatusSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/status";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnStatusResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.status());
        }
    }

    // ============================================================
    // 3. GNN CONTEXT TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Context Tests")
    class GnnContextTests {

        @Test
        @DisplayName("Should get GNN context successfully")
        void shouldGetGnnContextSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/context/EURUSD";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnContextResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("EURUSD", body.symbol());
            assertNotNull(body.context());
        }

        @Test
        @DisplayName("Should get GNN context with trade ID")
        void shouldGetGnnContextWithTradeId() {
            // Given
            var url = aiBaseUrl + "/gnn/context/EURUSD?tradeId=123456789";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnContextResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should fail when symbol is invalid")
        void shouldFailWhenSymbolIsInvalid() {
            // Given
            var url = aiBaseUrl + "/gnn/context/INVALID";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .retrieve()
                        .toEntity(GnnContextResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 4. GNN INSIGHTS TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Insights Tests")
    class GnnInsightsTests {

        @Test
        @DisplayName("Should get GNN insights successfully")
        void shouldGetGnnInsightsSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/insights/EURUSD";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnInsightsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("EURUSD", body.symbol());
            assertNotNull(body.insights());
        }

        @Test
        @DisplayName("Should get GNN insights with analysis direction")
        void shouldGetGnnInsightsWithAnalysisDirection() {
            // Given
            var url = aiBaseUrl + "/gnn/insights/EURUSD?analysisDirection=BUY";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnInsightsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should fail when symbol is invalid")
        void shouldFailWhenSymbolIsInvalid() {
            // Given
            var url = aiBaseUrl + "/gnn/insights/INVALID";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .retrieve()
                        .toEntity(GnnInsightsResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 5. GNN CORRELATIONS TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Correlations Tests")
    class GnnCorrelationsTests {

        @Test
        @DisplayName("Should get GNN correlations successfully")
        void shouldGetGnnCorrelationsSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/correlations/EURUSD";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnCorrelationsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("EURUSD", body.symbol());
            assertNotNull(body.correlations());
        }
    }

    // ============================================================
    // 6. GNN DIVERGENCES TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Divergences Tests")
    class GnnDivergencesTests {

        @Test
        @DisplayName("Should get GNN divergences successfully")
        void shouldGetGnnDivergencesSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/divergences/EURUSD";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnDivergencesResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("EURUSD", body.symbol());
            assertNotNull(body.divergence());
        }
    }

    // ============================================================
    // 7. GNN SUGGESTIONS TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Suggestions Tests")
    class GnnSuggestionsTests {

        @Test
        @DisplayName("Should get GNN suggestions successfully")
        void shouldGetGnnSuggestionsSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/suggestions/EURUSD";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnSuggestionsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("EURUSD", body.symbol());
            assertNotNull(body.suggestions());
        }
    }

    // ============================================================
    // 8. GNN CONFLICT TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Conflict Tests")
    class GnnConflictTests {

        @Test
        @DisplayName("Should get GNN conflict successfully")
        void shouldGetGnnConflictSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/conflict/EURUSD?analysisDirection=BUY";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnConflictResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("EURUSD", body.symbol());
            assertEquals("BUY", body.yourAnalysis());
            assertNotNull(body.conflict());
        }

        @Test
        @DisplayName("Should fail when analysis direction is missing")
        void shouldFailWhenAnalysisDirectionIsMissing() {
            // Given
            var url = aiBaseUrl + "/gnn/conflict/EURUSD";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .retrieve()
                        .toEntity(GnnConflictResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when analysis direction is invalid")
        void shouldFailWhenAnalysisDirectionIsInvalid() {
            // Given
            var url = aiBaseUrl + "/gnn/conflict/EURUSD?analysisDirection=INVALID";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .retrieve()
                        .toEntity(GnnConflictResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 9. GNN A/B TEST TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN A/B Test Tests")
    class GnnAbTestTests {

        @Test
        @DisplayName("Should get GNN A/B test results successfully")
        void shouldGetGnnAbTestResultsSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/ab-test";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnAbTestResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.results());
        }
    }

    // ============================================================
    // 10. GNN HEATMAP TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Heatmap Tests")
    class GnnHeatmapTests {

        @Test
        @DisplayName("Should get GNN heatmap successfully")
        void shouldGetGnnHeatmapSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/heatmap";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnHeatmapResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.heatmap());
        }

        @Test
        @DisplayName("Should get GNN heatmap with specific symbols")
        void shouldGetGnnHeatmapWithSpecificSymbols() {
            // Given
            var url = aiBaseUrl + "/gnn/heatmap?symbols=EURUSD,GBPUSD,USDCHF";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnHeatmapResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }
    }

    // ============================================================
    // 11. GNN CORRELATION CHANGES TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Correlation Changes Tests")
    class GnnCorrelationChangesTests {

        @Test
        @DisplayName("Should get GNN correlation changes successfully")
        void shouldGetGnnCorrelationChangesSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/correlation-changes/EURUSD";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnCorrelationChangesResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("EURUSD", body.symbol());
            assertNotNull(body.changes());
        }

        @Test
        @DisplayName("Should get GNN correlation changes with lookback")
        void shouldGetGnnCorrelationChangesWithLookback() {
            // Given
            var url = aiBaseUrl + "/gnn/correlation-changes/EURUSD?lookback=20";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnCorrelationChangesResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }
    }

    // ============================================================
    // 12. GNN REFRESH TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Refresh Tests")
    class GnnRefreshTests {

        @Test
        @DisplayName("Should refresh GNN successfully")
        void shouldRefreshGnnSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/refresh";

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnRefreshResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }
    }

    // ============================================================
    // 13. GNN RESET TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Reset Tests")
    class GnnResetTests {

        @Test
        @DisplayName("Should reset GNN successfully")
        void shouldResetGnnSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/reset";

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(GnnResetResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }
    }

    // ============================================================
    // 14. GNN ROLLOUT TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Rollout Tests")
    class GnnRolloutTests {

        @Test
        @DisplayName("Should set GNN rollout successfully")
        void shouldSetGnnRolloutSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/ab-test/rollout";
            var request = AIIntegrationTestDataFactory.validGnnRolloutRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(GnnRolloutResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals(0.5, body.rollout());
        }

        @Test
        @DisplayName("Should fail when rollout is invalid")
        void shouldFailWhenRolloutIsInvalid() {
            // Given
            var url = aiBaseUrl + "/gnn/ab-test/rollout";
            var request = AIIntegrationTestDataFactory.invalidGnnRolloutRequest();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(GnnRolloutResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 15. GNN TRACK RESULT TESTS
    // ============================================================

    @Nested
    @DisplayName("GNN Track Result Tests")
    class GnnTrackResultTests {

        @Test
        @DisplayName("Should track GNN result successfully")
        void shouldTrackGnnResultSuccessfully() {
            // Given
            var url = aiBaseUrl + "/gnn/track-result";
            var request = AIIntegrationTestDataFactory.validGnnTrackResultRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(GnnTrackResultResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should fail when trade ID is null")
        void shouldFailWhenTradeIdIsNull() {
            // Given
            var url = aiBaseUrl + "/gnn/track-result";
            var request = AIIntegrationTestDataFactory.gnnTrackResultRequestWithNullTradeId();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(GnnTrackResultResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when trade ID is zero")
        void shouldFailWhenTradeIdIsZero() {
            // Given
            var url = aiBaseUrl + "/gnn/track-result";
            var request = AIIntegrationTestDataFactory.gnnTrackResultRequestWithZeroTradeId();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(GnnTrackResultResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 16. ADVERSARIAL STATUS TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Status Tests")
    class AdversarialStatusTests {

        @Test
        @DisplayName("Should get adversarial status successfully")
        void shouldGetAdversarialStatusSuccessfully() {
            // Given
            var url = aiBaseUrl + "/adversarial/status";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(AdversarialStatusResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.status());
        }
    }

    // ============================================================
    // 17. ADVERSARIAL GENERATE TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Generate Tests")
    class AdversarialGenerateTests {

        @Test
        @DisplayName("Should generate adversarial attacks successfully")
        void shouldGenerateAdversarialAttacksSuccessfully() {
            // Given
            var url = aiBaseUrl + "/adversarial/generate";
            var request = AIIntegrationTestDataFactory.validAdversarialGenerateRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(AdversarialGenerateResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.attackedTrades());
        }

        @Test
        @DisplayName("Should fail when trade is null")
        void shouldFailWhenTradeIsNull() {
            // Given
            var url = aiBaseUrl + "/adversarial/generate";
            var request = AIIntegrationTestDataFactory.adversarialGenerateRequestWithNullTrade();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(AdversarialGenerateResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when outcome is null")
        void shouldFailWhenOutcomeIsNull() {
            // Given
            var url = aiBaseUrl + "/adversarial/generate";
            var request = AIIntegrationTestDataFactory.adversarialGenerateRequestWithNullOutcome();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(AdversarialGenerateResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 18. ADVERSARIAL TRAIN TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Train Tests")
    class AdversarialTrainTests {

        @Test
        @DisplayName("Should train adversarial successfully")
        void shouldTrainAdversarialSuccessfully() {
            // Given
            var url = aiBaseUrl + "/adversarial/train";
            var request = AIIntegrationTestDataFactory.validAdversarialTrainRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(AdversarialTrainResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.result());
        }

        @Test
        @DisplayName("Should fail when trades are null")
        void shouldFailWhenTradesAreNull() {
            // Given
            var url = aiBaseUrl + "/adversarial/train";
            var request = AIIntegrationTestDataFactory.adversarialTrainRequestWithNullTrades();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(AdversarialTrainResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when outcomes are null")
        void shouldFailWhenOutcomesAreNull() {
            // Given
            var url = aiBaseUrl + "/adversarial/train";
            var request = AIIntegrationTestDataFactory.adversarialTrainRequestWithNullOutcomes();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(AdversarialTrainResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when trades and outcomes length mismatch")
        void shouldFailWhenTradesAndOutcomesLengthMismatch() {
            // Given
            var url = aiBaseUrl + "/adversarial/train";
            var request = AIIntegrationTestDataFactory.adversarialTrainRequestWithMismatchedLengths();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(AdversarialTrainResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 19. ADVERSARIAL METRICS TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Metrics Tests")
    class AdversarialMetricsTests {

        @Test
        @DisplayName("Should get adversarial metrics successfully")
        void shouldGetAdversarialMetricsSuccessfully() {
            // Given
            var url = aiBaseUrl + "/adversarial/metrics";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(AdversarialMetricsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.metrics());
        }
    }

    // ============================================================
    // 20. ADVERSARIAL INTENSITY TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Intensity Tests")
    class AdversarialIntensityTests {

        @Test
        @DisplayName("Should set adversarial intensity successfully")
        void shouldSetAdversarialIntensitySuccessfully() {
            // Given
            var url = aiBaseUrl + "/adversarial/intensity";
            var request = AIIntegrationTestDataFactory.validAdversarialIntensityRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(AdversarialIntensityResponse.class)
                    .block();

            // Then            assertNotNull(response);
            var body = Objects.requireNonNull(response).getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals(0.5, body.intensity());
        }

        @Test
        @DisplayName("Should fail when intensity is invalid")
        void shouldFailWhenIntensityIsInvalid() {
            // Given
            var url = aiBaseUrl + "/adversarial/intensity";
            var request = AIIntegrationTestDataFactory.invalidAdversarialIntensityRequest();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(AdversarialIntensityResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 21. ADVERSARIAL ENABLE TESTS
    // ============================================================

    @Nested
    @DisplayName("Adversarial Enable Tests")
    class AdversarialEnableTests {

        @Test
        @DisplayName("Should enable adversarial successfully")
        void shouldEnableAdversarialSuccessfully() {
            // Given
            var url = aiBaseUrl + "/adversarial/enable";
            var request = AIIntegrationTestDataFactory.validAdversarialEnableRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(AdversarialEnableResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertTrue(body.enabled());
        }

        @Test
        @DisplayName("Should disable adversarial successfully")
        void shouldDisableAdversarialSuccessfully() {
            // Given
            var url = aiBaseUrl + "/adversarial/enable";
            var request = AIIntegrationTestDataFactory.validAdversarialDisableRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(AdversarialEnableResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertFalse(body.enabled());
        }
    }

    // ============================================================
    // 22. AUTHENTICATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Authentication Tests")
    class AuthenticationTests {

        @Test
        @DisplayName("Should fail when API key is missing")
        void shouldFailWhenApiKeyIsMissing() {
            // Given
            var url = aiBaseUrl + "/gnn/status";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .retrieve()
                        .toEntity(GnnStatusResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when API key is invalid")
        void shouldFailWhenApiKeyIsInvalid() {
            // Given
            var url = aiBaseUrl + "/gnn/status";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .header("X-API-Key", "invalid-key")
                        .retrieve()
                        .toEntity(GnnStatusResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Health endpoint should work without API key")
        void healthEndpointShouldWorkWithoutApiKey() {
            // Given
            var url = baseUrl + "/health";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .retrieve()
                    .toEntity(AIHealthResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("healthy", body.status());
        }
    }
}