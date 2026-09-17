package com.trading.easytradify.integration;

import com.trading.easytradify.execution.models.*;
import com.trading.easytradify.unit.TestDataFactory;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("Trade Execution Integration Tests")
class TradeExecutionIntegrationTest extends BaseIntegrationTest {

    private String executionBaseUrl;

    @BeforeEach
    void setUp() {
        executionBaseUrl = baseUrl + "/api/v1/execution";
    }

    // ============================================================
    // 1. TRADE EXECUTION TESTS
    // ============================================================

    @Nested
    @DisplayName("Execute Trade Tests")
    class ExecuteTradeTests {

        @Test
        @DisplayName("Should execute trade successfully on default broker")
        void shouldExecuteTradeSuccessfullyOnDefaultBroker() {
            // Given
            var url = executionBaseUrl + "/trade";
            var request = TestDataFactory.validExecuteTradeRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(TradeExecutionResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should execute trade on multiple brokers")
        void shouldExecuteTradeOnMultipleBrokers() {
            // Given
            var url = executionBaseUrl + "/trade";
            var request = TestDataFactory.validExecuteTradeRequestWithMultipleBrokers();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(TradeExecutionResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should execute trade on all brokers when 'all' is specified")
        void shouldExecuteTradeOnAllBrokersWhenAllSpecified() {
            // Given
            var url = executionBaseUrl + "/trade";
            var request = TestDataFactory.validExecuteTradeRequestWithAllBrokers();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(TradeExecutionResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should fail when symbol is empty")
        void shouldFailWhenSymbolIsEmpty() {
            // Given
            var url = executionBaseUrl + "/trade";
            var request = ExecuteTradeRequest.builder()
                    .symbol("")
                    .orderType(OrderSide.BUY)
                    .strategyMagic(123456)
                    .fixedTradeSizeUsd(200.0)
                    .riskPerTrade(0.05)
                    .maxSpread(30.0)
                    .brokers(List.of("icmarkets"))
                    .build();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(TradeExecutionResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 2. TRADE ANALYSIS TESTS
    // ============================================================

    @Nested
    @DisplayName("Trade Analysis Tests")
    class AnalyseTradeTests {

        @Test
        @DisplayName("Should analyse trade successfully")
        void shouldAnalyseTradeSuccessfully() {
            // Given
            var url = executionBaseUrl + "/analyse";
            var request = TestDataFactory.validAnalyseTradeRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(AnalyseTradeResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(body.success());
        }

        @Test
        @DisplayName("Should fail when symbol is empty")
        void shouldFailWhenSymbolIsEmpty() {
            // Given
            var url = executionBaseUrl + "/analyse";
            var request = new AnalyseTradeRequest("", OrderSide.BUY, 200.0, 0.05, null, null, null);

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(AnalyseTradeResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 3. PROBABILITY CALCULATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Probability Calculation Tests")
    class ProbabilityCalculationTests {

        @Test
        @DisplayName("Should calculate probability successfully")
        void shouldCalculateProbabilitySuccessfully() {
            // Given
            var url = executionBaseUrl + "/probability";
            var request = TestDataFactory.validProbabilityRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(ProbabilityResponse.class)
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
    // 4. POSITION MANAGEMENT TESTS
    // ============================================================

    @Nested
    @DisplayName("Position Management Tests")
    class PositionManagementTests {

        @Test
        @DisplayName("Should get all positions")
        void shouldGetAllPositions() {
            // Given
            var url = executionBaseUrl + "/positions?broker=icmarkets";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PositionsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }

        @Test
        @DisplayName("Should get open positions")
        void shouldGetOpenPositions() {
            // Given
            var url = executionBaseUrl + "/positions/open?broker=icmarkets";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(PositionsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }
    }

    // ============================================================
    // 5. TRAILING STOP TESTS
    // ============================================================

    @Nested
    @DisplayName("Trailing Stop Tests")
    class TrailingStopTests {

        @Test
        @DisplayName("Should enable trailing stop")
        void shouldEnableTrailingStop() {
            // Given
            var url = executionBaseUrl + "/position/trailing/enable";
            var request = new TrailingStopRequest(123456789, 5.0, List.of("icmarkets"));

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(TrailingStopResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertTrue(response.getStatusCode().is2xxSuccessful() ||
                    response.getStatusCode() == HttpStatus.BAD_REQUEST);
        }

        @Test
        @DisplayName("Should disable trailing stop")
        void shouldDisableTrailingStop() {
            // Given
            var url = executionBaseUrl + "/position/trailing/disable";
            var request = TestDataFactory.validDisableTrailingRequest();

            // When
            var response = webClient
                    .put()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(TrailingStopResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertTrue(response.getStatusCode().is2xxSuccessful() ||
                    response.getStatusCode() == HttpStatus.BAD_REQUEST);
        }

        @Test
        @DisplayName("Should get trailing status")
        void shouldGetTrailingStatus() {
            // Given
            var url = executionBaseUrl + "/trailing/status?broker=icmarkets";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(TrailingStatusResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }
    }

    // ============================================================
    // 6. ACCOUNT & SYMBOL TESTS
    // ============================================================

    @Nested
    @DisplayName("Account & Symbol Tests")
    class AccountSymbolTests {

        @Test
        @DisplayName("Should get account info")
        void shouldGetAccountInfo() {
            // Given
            var url = executionBaseUrl + "/account?broker=icmarkets";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(AccountResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }

        @Test
        @DisplayName("Should get symbol info")
        void shouldGetSymbolInfo() {
            // Given
            var url = executionBaseUrl + "/symbol/EURUSD?broker=icmarkets";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(SymbolInfoResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }

        @Test
        @DisplayName("Should get all symbols")
        void shouldGetAllSymbols() {
            // Given
            var url = executionBaseUrl + "/symbols?broker=icmarkets";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(SymbolsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }
    }

    // ============================================================
    // 7. MARKET CONDITIONS TESTS
    // ============================================================

    @Nested
    @DisplayName("Market Conditions Tests")
    class MarketConditionsTests {

        @Test
        @DisplayName("Should get market status")
        void shouldGetMarketStatus() {
            // Given
            var url = executionBaseUrl + "/market/status/EURUSD?broker=icmarkets";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(MarketStatusResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }

        @Test
        @DisplayName("Should get market volatility")
        void shouldGetMarketVolatility() {
            // Given
            var url = executionBaseUrl + "/market/volatility/EURUSD?broker=icmarkets&lookback=20";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(VolatilityResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }

        @Test
        @DisplayName("Should get market spread")
        void shouldGetMarketSpread() {
            // Given
            var url = executionBaseUrl + "/market/spread/EURUSD?broker=icmarkets&maxSpread=30";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(SpreadResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }

        @Test
        @DisplayName("Should get market conditions")
        void shouldGetMarketConditions() {
            // Given
            var url = executionBaseUrl + "/market/conditions/EURUSD?broker=icmarkets";

            // When
            var response = webClient
                    .get()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .retrieve()
                    .toEntity(MarketConditionsResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }
    }

    // ============================================================
    // 8. MT5 CONNECTION TESTS
    // ============================================================

    @Nested
    @DisplayName("MT5 Connection Tests")
    class Mt5ConnectionTests {

        @Test
        @DisplayName("Should connect to MT5")
        void shouldConnectToMt5() {
            // Given
            var url = executionBaseUrl + "/mt5/connect?broker=icmarkets";
            var request = TestDataFactory.validMt5ConnectRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(Mt5ConnectionResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertNotNull(body.success());
        }

        @Test
        @DisplayName("Should fail when login is empty")
        void shouldFailWhenLoginIsEmpty() {
            // Given
            var url = executionBaseUrl + "/mt5/connect?broker=icmarkets";
            var request = new Mt5ConnectRequest("", "password", "ICMarkets-Demo", "");

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", apiKey)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(Mt5ConnectionResponse.class)
                        .block();
            });
        }
    }

    // ============================================================
    // 9. HISTORY & CALCULATIONS TESTS
    // ============================================================

    @Nested
    @DisplayName("History & Calculations Tests")
    class HistoryCalculationsTests {

        @Test
        @DisplayName("Should get trade history")
        void shouldGetTradeHistory() {
            // Given
            var url = executionBaseUrl + "/trades/history?broker=icmarkets";
            var request = TestDataFactory.validTradeHistoryRequest();

            // When — use method with body for GET requests
            var response = webClient
                    .method(HttpMethod.GET)
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(TradeHistoryResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }

        @Test
        @DisplayName("Should calculate lot")
        void shouldCalculateLot() {
            // Given
            var url = executionBaseUrl + "/calculate-lot?broker=icmarkets";
            var request = TestDataFactory.validLotCalculationRequest();

            // When
            var response = webClient
                    .post()
                    .uri(url)
                    .header("X-API-Key", apiKey)
                    .bodyValue(request)
                    .retrieve()
                    .toEntity(LotCalculationResponse.class)
                    .block();

            // Then
            assertNotNull(response);
            var body = response.getBody();
            assertNotNull(body);
            assertEquals(HttpStatus.OK, response.getStatusCode());
        }
    }

    // ============================================================
    // 10. HEALTH TEST
    // ============================================================

    @Nested
    @DisplayName("Health Tests")
    class HealthTests {

        @Test
        @DisplayName("Should return health status")
        void shouldReturnHealthStatus() {
            // Given
            var url = executionBaseUrl + "/health?broker=icmarkets";

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
            assertNotNull(body.status());
        }

        @Test
        @DisplayName("Should return health status without API key")
        void shouldReturnHealthStatusWithoutApiKey() {
            // Given
            var url = executionBaseUrl + "/health";

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
        }
    }

    // ============================================================
    // 11. AUTHENTICATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Authentication Tests")
    class AuthenticationTests {

        @Test
        @DisplayName("Should fail when API key is missing")
        void shouldFailWhenApiKeyIsMissing() {
            // Given
            var url = executionBaseUrl + "/trade";
            var request = TestDataFactory.validExecuteTradeRequest();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(TradeExecutionResponse.class)
                        .block();
            });
        }

        @Test
        @DisplayName("Should fail when API key is invalid")
        void shouldFailWhenApiKeyIsInvalid() {
            // Given
            var url = executionBaseUrl + "/trade";
            var request = TestDataFactory.validExecuteTradeRequest();

            // When & Then
            assertThrows(WebClientResponseException.class, () -> {
                webClient
                        .post()
                        .uri(url)
                        .header("X-API-Key", "invalid-key")
                        .bodyValue(request)
                        .retrieve()
                        .toEntity(TradeExecutionResponse.class)
                        .block();
            });
        }
    }
}