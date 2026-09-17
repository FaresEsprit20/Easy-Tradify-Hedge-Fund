package com.trading.easytradify.portfolio.integration;

import com.trading.easytradify.portfolio.models.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("Portfolio Risk Integration Tests")
class PortfolioRiskIntegrationTest extends BasePortfolioRiskIntegrationTest {

    @BeforeEach
    void setUp() {
        System.out.println(">>> Portfolio Risk Base URL: " + portfolioBaseUrl);
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
                    .toEntity(HealthResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("healthy", body.status());
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
                    .toEntity(HealthResponse.class)
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
    // 2. PORTFOLIO STATUS TESTS
    // ============================================================

    @Nested
    @DisplayName("Portfolio Status Tests")
    class PortfolioStatusTests {

        @Test
        @DisplayName("Should get portfolio status successfully")
        void shouldGetPortfolioStatusSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/status";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PortfolioStatusResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.status());
        }

        @Test
        @DisplayName("Should get portfolio status with refresh")
        void shouldGetPortfolioStatusWithRefresh() {
            // Given
            var url = portfolioBaseUrl + "/status?refresh=true";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PortfolioStatusResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should get portfolio status with summary")
        void shouldGetPortfolioStatusWithSummary() {
            // Given
            var url = portfolioBaseUrl + "/status?summary=true";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PortfolioStatusResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should get portfolio summary")
        void shouldGetPortfolioSummary() {
            // Given
            var url = portfolioBaseUrl + "/summary";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PortfolioStatusResponse.class)
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
    // 3. CONFIGURATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Configuration Tests")
    class ConfigurationTests {

        @Test
        @DisplayName("Should get portfolio config successfully")
        void shouldGetPortfolioConfigSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.config());
        }

        @Test
        @DisplayName("Should get portfolio config field successfully")
        void shouldGetPortfolioConfigFieldSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config/max_daily_loss_percent";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PortfolioConfigFieldResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("max_daily_loss_percent", body.field());
        }

        @Test
        @DisplayName("Should fail when config field not found")
        void shouldFailWhenConfigFieldNotFound() {
            // Given
            var url = portfolioBaseUrl + "/config/invalid_field";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .retrieve()
                        .toEntity(PortfolioConfigFieldResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should update portfolio config successfully")
        void shouldUpdatePortfolioConfigSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var request = PortfolioRiskIntegrationTestDataFactory.validConfigUpdateRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should update portfolio config field successfully")
        void shouldUpdatePortfolioConfigFieldSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config/max_daily_loss_percent";
            var request = PortfolioRiskIntegrationTestDataFactory.fieldUpdateRequest(3.0);

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigFieldResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("max_daily_loss_percent", body.field());
            assertEquals(3.0, body.value());
        }

        @Test
        @DisplayName("Should update daily limits successfully")
        void shouldUpdateDailyLimitsSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var request = PortfolioRiskIntegrationTestDataFactory.dailyLimitsUpdateRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should update monthly limits successfully")
        void shouldUpdateMonthlyLimitsSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var request = PortfolioRiskIntegrationTestDataFactory.monthlyLimitsUpdateRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should update YTD limits successfully")
        void shouldUpdateYtdLimitsSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var request = PortfolioRiskIntegrationTestDataFactory.ytdLimitsUpdateRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should update risk per trade successfully")
        void shouldUpdateRiskPerTradeSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var request = PortfolioRiskIntegrationTestDataFactory.riskPerTradeUpdateRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should update drawdown successfully")
        void shouldUpdateDrawdownSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var request = PortfolioRiskIntegrationTestDataFactory.drawdownUpdateRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should update consecutive losses successfully")
        void shouldUpdateConsecutiveLossesSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var request = PortfolioRiskIntegrationTestDataFactory.consecutiveLossesUpdateRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should update funded account successfully")
        void shouldUpdateFundedAccountSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var request = PortfolioRiskIntegrationTestDataFactory.fundedAccountUpdateRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should update trading hours successfully")
        void shouldUpdateTradingHoursSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var request = PortfolioRiskIntegrationTestDataFactory.tradingHoursUpdateRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(PortfolioConfigResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should fail when updating with invalid percentage")
        void shouldFailWhenUpdatingWithInvalidPercentage() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var updates = Map.<String, Object>of("max_daily_loss_percent", 105.0);
            var request = new PortfolioConfigUpdateRequest(updates);

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .put()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(PortfolioConfigResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when updating with negative trade size")
        void shouldFailWhenUpdatingWithNegativeTradeSize() {
            // Given
            var url = portfolioBaseUrl + "/config";
            var updates = Map.<String, Object>of("trade_size_in_usd", -100.0);
            var request = new PortfolioConfigUpdateRequest(updates);

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .put()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(PortfolioConfigResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 4. TRADING PERMISSION TESTS
    // ============================================================

    @Nested
    @DisplayName("Trading Permission Tests")
    class TradingPermissionTests {

        @Test
        @DisplayName("Should check trading allowed successfully")
        void shouldCheckTradingAllowedSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/check-trading-allowed";
            var request = PortfolioRiskIntegrationTestDataFactory.checkTradingAllowedRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(CheckTradingAllowedResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.isTradingAllowed());
        }

        @Test
        @DisplayName("Should check trading allowed with no risk")
        void shouldCheckTradingAllowedWithNoRisk() {
            // Given
            var url = portfolioBaseUrl + "/check-trading-allowed";
            var request = PortfolioRiskIntegrationTestDataFactory.checkTradingAllowedRequestWithNoRisk();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(CheckTradingAllowedResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should check trading allowed with high risk (may be blocked)")
        void shouldCheckTradingAllowedWithHighRisk() {
            // Given
            var url = portfolioBaseUrl + "/check-trading-allowed";
            var request = PortfolioRiskIntegrationTestDataFactory.checkTradingAllowedRequestWithHighRisk();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(CheckTradingAllowedResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should fail when check request is null")
        void shouldFailWhenCheckRequestIsNull() {
            // Given
            var url = portfolioBaseUrl + "/check-trading-allowed";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(null)
                        .retrieve()
                        .toEntity(CheckTradingAllowedResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should get max risk for trade successfully")
        void shouldGetMaxRiskForTradeSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/max-risk-per-trade";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(MaxRiskForTradeResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.maxRiskPerTradePercent());
        }
    }

    // ============================================================
    // 5. STATISTICS TESTS
    // ============================================================

    @Nested
    @DisplayName("Statistics Tests")
    class StatisticsTests {

        @Test
        @DisplayName("Should get daily stats successfully")
        void shouldGetDailyStatsSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/stats?period=daily&date=" +
                    PortfolioRiskIntegrationTestDataFactory.dailyStatsDate();

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PortfolioStatsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("daily", body.period());
        }

        @Test
        @DisplayName("Should get monthly stats successfully")
        void shouldGetMonthlyStatsSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/stats?period=monthly&date=" +
                    PortfolioRiskIntegrationTestDataFactory.monthlyStatsMonth();

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PortfolioStatsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("monthly", body.period());
        }

        @Test
        @DisplayName("Should get YTD stats successfully")
        void shouldGetYtdStatsSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/stats?period=ytd&date=" +
                    PortfolioRiskIntegrationTestDataFactory.ytdStatsYear();

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PortfolioStatsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertEquals("ytd", body.period());
        }

        @Test
        @DisplayName("Should fail with invalid period")
        void shouldFailWithInvalidPeriod() {
            // Given
            var url = portfolioBaseUrl + "/stats?period=invalid";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .retrieve()
                        .toEntity(PortfolioStatsResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail with missing period")
        void shouldFailWithMissingPeriod() {
            // Given
            var url = portfolioBaseUrl + "/stats";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .retrieve()
                        .toEntity(PortfolioStatsResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 6. DRAWDOWN TESTS
    // ============================================================

    @Nested
    @DisplayName("Drawdown Tests")
    class DrawdownTests {

        @Test
        @DisplayName("Should get drawdown info successfully")
        void shouldGetDrawdownInfoSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/drawdown";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(DrawdownResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.currentPercent());
            assertNotNull(body.maxPercent());
        }
    }

    // ============================================================
    // 7. FUNDED COMPLIANCE TESTS
    // ============================================================

    @Nested
    @DisplayName("Funded Compliance Tests")
    class FundedComplianceTests {

        @Test
        @DisplayName("Should get funded compliance successfully")
        void shouldGetFundedComplianceSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/funded-compliance";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(FundedComplianceResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
            assertNotNull(body.accountType());
            assertNotNull(body.compliant());
        }
    }

    // ============================================================
    // 8. REFRESH TESTS
    // ============================================================

    @Nested
    @DisplayName("Refresh Tests")
    class RefreshTests {

        @Test
        @DisplayName("Should refresh portfolio stats successfully")
        void shouldRefreshPortfolioStatsSuccessfully() {
            // Given
            var url = portfolioBaseUrl + "/refresh";

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(RefreshResponse.class)
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
    // 9. AUTHENTICATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Authentication Tests")
    class AuthenticationTests {

        @Test
        @DisplayName("Should fail when API key is missing")
        void shouldFailWhenApiKeyIsMissing() {
            // Given
            var url = portfolioBaseUrl + "/status";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .retrieve()
                        .toEntity(PortfolioStatusResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when API key is invalid")
        void shouldFailWhenApiKeyIsInvalid() {
            // Given
            var url = portfolioBaseUrl + "/status";

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .get()
                        .uri(url)
                        .header("X-API-Key", "invalid-key")
                        .retrieve()
                        .toEntity(PortfolioStatusResponse.class)
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
                    .toEntity(HealthResponse.class)
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