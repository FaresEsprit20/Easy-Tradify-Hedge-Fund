package com.trading.easytradify.portfolio.unit;

import com.trading.easytradify.portfolio.controllers.PortfolioRiskController;
import com.trading.easytradify.portfolio.services.PortfolioRiskService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("Portfolio Risk Controller Unit Tests")
class PortfolioRiskControllerTest {

    @Mock
    private PortfolioRiskService portfolioRiskService;

    @InjectMocks
    private PortfolioRiskController controller;

    // ============================================================
    // PORTFOLIO STATUS TESTS
    // ============================================================

    @Nested
    @DisplayName("Portfolio Status Controller Tests")
    class PortfolioStatusControllerTests {

        @Test
        @DisplayName("Should get portfolio status successfully")
        void shouldGetPortfolioStatusSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioStatusResponse();
            when(portfolioRiskService.getPortfolioStatus(anyBoolean(), anyBoolean()))
                    .thenReturn(expectedResponse);

            var response = controller.getPortfolioStatus(false, false);

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());

            verify(portfolioRiskService, times(1))
                    .getPortfolioStatus(false, false);
        }

        @Test
        @DisplayName("Should get portfolio summary successfully")
        void shouldGetPortfolioSummarySuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioSummaryResponse();
            when(portfolioRiskService.getPortfolioSummary())
                    .thenReturn(expectedResponse);

            var response = controller.getPortfolioSummary();

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());

            verify(portfolioRiskService, times(1))
                    .getPortfolioSummary();
        }
    }

    // ============================================================
    // CONFIGURATION CONTROLLER TESTS
    // ============================================================

    @Nested
    @DisplayName("Configuration Controller Tests")
    class ConfigurationControllerTests {

        @Test
        @DisplayName("Should get portfolio config successfully")
        void shouldGetPortfolioConfigSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioConfigResponse();
            when(portfolioRiskService.getPortfolioConfig())
                    .thenReturn(expectedResponse);

            var response = controller.getPortfolioConfig();

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());

            verify(portfolioRiskService, times(1))
                    .getPortfolioConfig();
        }

        @Test
        @DisplayName("Should get portfolio config field successfully")
        void shouldGetPortfolioConfigFieldSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioConfigFieldResponse(
                    "max_daily_loss_percent",
                    5.0
            );
            when(portfolioRiskService.getPortfolioConfigField(anyString()))
                    .thenReturn(expectedResponse);

            var response = controller.getPortfolioConfigField("max_daily_loss_percent");

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());
            assertEquals("max_daily_loss_percent", response.getBody().field());

            verify(portfolioRiskService, times(1))
                    .getPortfolioConfigField("max_daily_loss_percent");
        }

        @Test
        @DisplayName("Should update portfolio config successfully")
        void shouldUpdatePortfolioConfigSuccessfully() {
            var request = PortfolioRiskTestDataFactory.validPortfolioConfigUpdateRequest();
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioConfigResponse();
            when(portfolioRiskService.updatePortfolioConfig(any()))
                    .thenReturn(expectedResponse);

            var response = controller.updatePortfolioConfig(request);

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());

            verify(portfolioRiskService, times(1))
                    .updatePortfolioConfig(request);
        }

        @Test
        @DisplayName("Should update portfolio config field successfully")
        void shouldUpdatePortfolioConfigFieldSuccessfully() {
            var request = PortfolioRiskTestDataFactory.validFieldUpdateRequest(3.0);
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioConfigFieldResponse(
                    "max_daily_loss_percent",
                    3.0
            );
            when(portfolioRiskService.updatePortfolioConfigField(anyString(), any()))
                    .thenReturn(expectedResponse);

            var response = controller.updatePortfolioConfigField("max_daily_loss_percent", request);

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());

            verify(portfolioRiskService, times(1))
                    .updatePortfolioConfigField("max_daily_loss_percent", request);
        }
    }

    // ============================================================
    // TRADING PERMISSION CONTROLLER TESTS
    // ============================================================

    @Nested
    @DisplayName("Trading Permission Controller Tests")
    class TradingPermissionControllerTests {

        @Test
        @DisplayName("Should check trading allowed successfully")
        void shouldCheckTradingAllowedSuccessfully() {
            var request = PortfolioRiskTestDataFactory.validCheckTradingAllowedRequest();
            var expectedResponse = PortfolioRiskTestDataFactory.validCheckTradingAllowedResponse();
            when(portfolioRiskService.checkTradingAllowed(any()))
                    .thenReturn(expectedResponse);

            var response = controller.checkTradingAllowed(request);

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());

            verify(portfolioRiskService, times(1))
                    .checkTradingAllowed(request);
        }

        @Test
        @DisplayName("Should get max risk for trade successfully")
        void shouldGetMaxRiskForTradeSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validMaxRiskForTradeResponse();
            when(portfolioRiskService.getMaxRiskForTrade())
                    .thenReturn(expectedResponse);

            var response = controller.getMaxRiskForTrade();

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());
            assertEquals(5.0, response.getBody().maxRiskPerTradePercent());

            verify(portfolioRiskService, times(1))
                    .getMaxRiskForTrade();
        }
    }

    // ============================================================
    // STATISTICS CONTROLLER TESTS
    // ============================================================

    @Nested
    @DisplayName("Statistics Controller Tests")
    class StatisticsControllerTests {

        @Test
        @DisplayName("Should get portfolio stats successfully")
        void shouldGetPortfolioStatsSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validDailyStatsResponse();
            when(portfolioRiskService.getPortfolioStats(anyString(), any()))
                    .thenReturn(expectedResponse);

            var response = controller.getPortfolioStats("daily", "2024-01-15");

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());
            assertEquals("daily", response.getBody().period());

            verify(portfolioRiskService, times(1))
                    .getPortfolioStats("daily", "2024-01-15");
        }
    }

    // ============================================================
    // DRAWDOWN CONTROLLER TESTS
    // ============================================================

    @Nested
    @DisplayName("Drawdown Controller Tests")
    class DrawdownControllerTests {

        @Test
        @DisplayName("Should get drawdown info successfully")
        void shouldGetDrawdownInfoSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validDrawdownResponse();
            when(portfolioRiskService.getDrawdownInfo())
                    .thenReturn(expectedResponse);

            var response = controller.getDrawdownInfo();

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());
            assertEquals(2.0, response.getBody().currentPercent());

            verify(portfolioRiskService, times(1))
                    .getDrawdownInfo();
        }
    }

    // ============================================================
    // FUNDED COMPLIANCE CONTROLLER TESTS
    // ============================================================

    @Nested
    @DisplayName("Funded Compliance Controller Tests")
    class FundedComplianceControllerTests {

        @Test
        @DisplayName("Should get funded compliance successfully")
        void shouldGetFundedComplianceSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validFundedComplianceResponse();
            when(portfolioRiskService.getFundedCompliance())
                    .thenReturn(expectedResponse);

            var response = controller.getFundedCompliance();

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());
            assertEquals("FTMO", response.getBody().accountType());

            verify(portfolioRiskService, times(1))
                    .getFundedCompliance();
        }
    }

    // ============================================================
    // REFRESH CONTROLLER TESTS
    // ============================================================

    @Nested
    @DisplayName("Refresh Controller Tests")
    class RefreshControllerTests {

        @Test
        @DisplayName("Should refresh portfolio stats successfully")
        void shouldRefreshPortfolioStatsSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validRefreshResponse();
            when(portfolioRiskService.refreshPortfolioStats())
                    .thenReturn(expectedResponse);

            var response = controller.refreshPortfolioStats();

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertTrue(response.getBody().success());

            verify(portfolioRiskService, times(1))
                    .refreshPortfolioStats();
        }
    }

    // ============================================================
    // HEALTH CONTROLLER TESTS
    // ============================================================

    @Nested
    @DisplayName("Health Controller Tests")
    class HealthControllerTests {

        @Test
        @DisplayName("Should get health successfully")
        void shouldGetHealthSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validHealthResponse();
            when(portfolioRiskService.healthCheck())
                    .thenReturn(expectedResponse);

            var response = controller.healthCheck();

            assertNotNull(response);
            assertEquals(HttpStatus.OK, response.getStatusCode());
            assertEquals("operational", response.getBody().status());

            verify(portfolioRiskService, times(1))
                    .healthCheck();
        }
    }
}