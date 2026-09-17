package com.trading.easytradify.portfolio.unit;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.portfolio.client.PythonPortfolioRiskClient;
import com.trading.easytradify.portfolio.models.*;
import com.trading.easytradify.portfolio.services.PortfolioRiskService;
import com.trading.easytradify.portfolio.services.PortfolioRiskServiceImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("Portfolio Risk Service Unit Tests")
class PortfolioRiskServiceTest {

    @Mock
    private PythonPortfolioRiskClient clientMock;

    @InjectMocks
    private PortfolioRiskServiceImpl service;

    // ============================================================
    // PORTFOLIO STATUS TESTS
    // ============================================================

    @Nested
    @DisplayName("Portfolio Status Tests")
    class PortfolioStatusTests {

        @Test
        @DisplayName("Should get portfolio status successfully")
        void shouldGetPortfolioStatusSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioStatusResponse();
            when(clientMock.getPortfolioStatus(anyBoolean(), anyBoolean()))
                    .thenReturn(expectedResponse);

            var response = service.getPortfolioStatus(false, false);

            assertNotNull(response);
            assertTrue(response.success());
            assertNotNull(response.status());

            verify(clientMock, times(1)).getPortfolioStatus(false, false);
        }

        @Test
        @DisplayName("Should get portfolio status with refresh successfully")
        void shouldGetPortfolioStatusWithRefreshSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioStatusResponse();
            when(clientMock.getPortfolioStatus(anyBoolean(), anyBoolean()))
                    .thenReturn(expectedResponse);

            var response = service.getPortfolioStatus(true, false);

            assertNotNull(response);
            assertTrue(response.success());

            verify(clientMock, times(1)).getPortfolioStatus(true, false);
        }

        @Test
        @DisplayName("Should get portfolio summary successfully")
        void shouldGetPortfolioSummarySuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioSummaryResponse();
            when(clientMock.getPortfolioSummary())
                    .thenReturn(expectedResponse);

            var response = service.getPortfolioSummary();

            assertNotNull(response);
            assertTrue(response.success());

            verify(clientMock, times(1)).getPortfolioSummary();
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure for status")
        void shouldThrowExceptionWhenClientReturnsFailureForStatus() {
            var errorResponse = PortfolioRiskTestDataFactory.errorPortfolioStatusResponse("Service unavailable");
            when(clientMock.getPortfolioStatus(anyBoolean(), anyBoolean()))
                    .thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getPortfolioStatus(false, false)
            );

            assertEquals(ErrorCodes.PORTFOLIO_STATUS_FETCH_FAILED, exception.getErrorCode());

            verify(clientMock, times(1)).getPortfolioStatus(false, false);
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure for summary")
        void shouldThrowExceptionWhenClientReturnsFailureForSummary() {
            var errorResponse = PortfolioRiskTestDataFactory.errorPortfolioStatusResponse("Service unavailable");
            when(clientMock.getPortfolioSummary())
                    .thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getPortfolioSummary()
            );

            assertEquals(ErrorCodes.PORTFOLIO_STATUS_FETCH_FAILED, exception.getErrorCode());

            verify(clientMock, times(1)).getPortfolioSummary();
        }
    }

    // ============================================================
    // CONFIGURATION TESTS
    // ============================================================

    @Nested
    @DisplayName("Configuration Tests")
    class ConfigurationTests {

        @Test
        @DisplayName("Should get portfolio config successfully")
        void shouldGetPortfolioConfigSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioConfigResponse();
            when(clientMock.getPortfolioConfig())
                    .thenReturn(expectedResponse);

            var response = service.getPortfolioConfig();

            assertNotNull(response);
            assertTrue(response.success());
            assertNotNull(response.config());

            verify(clientMock, times(1)).getPortfolioConfig();
        }

        @Test
        @DisplayName("Should get portfolio config field successfully")
        void shouldGetPortfolioConfigFieldSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioConfigFieldResponse(
                    "max_daily_loss_percent", 5.0
            );
            when(clientMock.getPortfolioConfigField(anyString()))
                    .thenReturn(expectedResponse);

            var response = service.getPortfolioConfigField("max_daily_loss_percent");

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("max_daily_loss_percent", response.field());

            verify(clientMock, times(1)).getPortfolioConfigField("max_daily_loss_percent");
        }

        @Test
        @DisplayName("Should throw TradingException when field name is empty")
        void shouldThrowExceptionWhenFieldNameIsEmpty() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getPortfolioConfigField("")
            );

            assertEquals(ErrorCodes.PORTFOLIO_CONFIG_FIELD_NOT_FOUND, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when field name is null")
        void shouldThrowExceptionWhenFieldNameIsNull() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getPortfolioConfigField(null)
            );

            assertEquals(ErrorCodes.PORTFOLIO_CONFIG_FIELD_NOT_FOUND, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should update portfolio config successfully")
        void shouldUpdatePortfolioConfigSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioConfigResponse();
            var request = PortfolioRiskTestDataFactory.validPortfolioConfigUpdateRequest();

            when(clientMock.updatePortfolioConfig(any()))
                    .thenReturn(expectedResponse);

            var response = service.updatePortfolioConfig(request);

            assertNotNull(response);
            assertTrue(response.success());

            verify(clientMock, times(1)).updatePortfolioConfig(request);
        }

        @Test
        @DisplayName("Should throw TradingException when config update request is null")
        void shouldThrowExceptionWhenConfigUpdateRequestIsNull() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.updatePortfolioConfig(null)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when config update has no updates")
        void shouldThrowExceptionWhenConfigUpdateHasNoUpdates() {
            // This will throw TradingException from the record constructor
            var exception = assertThrows(
                    TradingException.class,
                    () -> new PortfolioConfigUpdateRequest(null)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when config update has empty updates")
        void shouldThrowExceptionWhenConfigUpdateHasEmptyUpdates() {
            // This will throw TradingException from the record constructor
            var exception = assertThrows(
                    TradingException.class,
                    () -> new PortfolioConfigUpdateRequest(Map.of())
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when percentage is out of range")
        void shouldThrowExceptionWhenPercentageIsOutOfRange() {
            var request = PortfolioRiskTestDataFactory.invalidPercentageUpdateRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.updatePortfolioConfig(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when trade size is negative")
        void shouldThrowExceptionWhenTradeSizeIsNegative() {
            var request = PortfolioRiskTestDataFactory.invalidTradeSizeUpdateRequest();

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.updatePortfolioConfig(request)
            );

            assertEquals(ErrorCodes.FIELD_OUT_OF_RANGE, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should update portfolio config field successfully")
        void shouldUpdatePortfolioConfigFieldSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validPortfolioConfigFieldResponse(
                    "max_daily_loss_percent", 3.0
            );
            var request = PortfolioRiskTestDataFactory.validFieldUpdateRequest(3.0);

            when(clientMock.updatePortfolioConfigField(anyString(), any()))
                    .thenReturn(expectedResponse);

            var response = service.updatePortfolioConfigField("max_daily_loss_percent", request);

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("max_daily_loss_percent", response.field());
            assertEquals(3.0, response.value());

            verify(clientMock, times(1)).updatePortfolioConfigField("max_daily_loss_percent", request);
        }

        @Test
        @DisplayName("Should throw TradingException when field update request is null")
        void shouldThrowExceptionWhenFieldUpdateRequestIsNull() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.updatePortfolioConfigField("max_daily_loss_percent", null)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when field update value is null")
        void shouldThrowExceptionWhenFieldUpdateValueIsNull() {
            // This will throw TradingException from the record constructor
            var exception = assertThrows(
                    TradingException.class,
                    () -> new PortfolioConfigFieldUpdateRequest(null)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }
    }

    // ============================================================
    // TRADING PERMISSION TESTS
    // ============================================================

    @Nested
    @DisplayName("Trading Permission Tests")
    class TradingPermissionTests {

        @Test
        @DisplayName("Should check trading allowed successfully")
        void shouldCheckTradingAllowedSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validCheckTradingAllowedResponse();
            var request = PortfolioRiskTestDataFactory.validCheckTradingAllowedRequest();

            when(clientMock.checkTradingAllowed(any()))
                    .thenReturn(expectedResponse);

            var response = service.checkTradingAllowed(request);

            assertNotNull(response);
            assertTrue(response.success());
            assertTrue(response.isTradingAllowed());

            verify(clientMock, times(1)).checkTradingAllowed(request);
        }

        @Test
        @DisplayName("Should check trading allowed with no risk successfully")
        void shouldCheckTradingAllowedWithNoRiskSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validCheckTradingAllowedResponse();
            var request = PortfolioRiskTestDataFactory.checkTradingAllowedRequestWithNoRisk();

            when(clientMock.checkTradingAllowed(any()))
                    .thenReturn(expectedResponse);

            var response = service.checkTradingAllowed(request);

            assertNotNull(response);
            assertTrue(response.success());

            verify(clientMock, times(1)).checkTradingAllowed(request);
        }

        @Test
        @DisplayName("Should throw TradingException when check request is null")
        void shouldThrowExceptionWhenCheckRequestIsNull() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.checkTradingAllowed(null)
            );

            assertEquals(ErrorCodes.MISSING_REQUIRED_FIELD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should get max risk for trade successfully")
        void shouldGetMaxRiskForTradeSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validMaxRiskForTradeResponse();

            when(clientMock.getMaxRiskForTrade())
                    .thenReturn(expectedResponse);

            var response = service.getMaxRiskForTrade();

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(5.0, response.maxRiskPerTradePercent());

            verify(clientMock, times(1)).getMaxRiskForTrade();
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure for max risk")
        void shouldThrowExceptionWhenClientReturnsFailureForMaxRisk() {
            var errorResponse = PortfolioRiskTestDataFactory.errorMaxRiskForTradeResponse("Service unavailable");

            when(clientMock.getMaxRiskForTrade())
                    .thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getMaxRiskForTrade()
            );

            assertEquals(ErrorCodes.RISK_CHECK_FAILED, exception.getErrorCode());

            verify(clientMock, times(1)).getMaxRiskForTrade();
        }
    }

    // ============================================================
    // STATISTICS TESTS
    // ============================================================

    @Nested
    @DisplayName("Statistics Tests")
    class StatisticsTests {

        @Test
        @DisplayName("Should get daily stats successfully")
        void shouldGetDailyStatsSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validDailyStatsResponse();

            when(clientMock.getPortfolioStats(anyString(), any()))
                    .thenReturn(expectedResponse);

            var response = service.getDailyStats("2024-01-15");

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("daily", response.period());

            verify(clientMock, times(1)).getPortfolioStats("daily", "2024-01-15");
        }

        @Test
        @DisplayName("Should get monthly stats successfully")
        void shouldGetMonthlyStatsSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validMonthlyStatsResponse();

            when(clientMock.getPortfolioStats(anyString(), any()))
                    .thenReturn(expectedResponse);

            var response = service.getMonthlyStats("2024-01");

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("monthly", response.period());

            verify(clientMock, times(1)).getPortfolioStats("monthly", "2024-01");
        }

        @Test
        @DisplayName("Should get YTD stats successfully")
        void shouldGetYtdStatsSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validYtdStatsResponse();

            when(clientMock.getPortfolioStats(anyString(), any()))
                    .thenReturn(expectedResponse);

            var response = service.getYtdStats(2024);

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("ytd", response.period());

            verify(clientMock, times(1)).getPortfolioStats("ytd", "2024");
        }

        @Test
        @DisplayName("Should get portfolio stats with invalid period throws exception")
        void shouldGetPortfolioStatsWithInvalidPeriodThrowsException() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getPortfolioStats("invalid", null)
            );

            assertEquals(ErrorCodes.STATS_INVALID_PERIOD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should get portfolio stats with null period throws exception")
        void shouldGetPortfolioStatsWithNullPeriodThrowsException() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getPortfolioStats(null, null)
            );

            assertEquals(ErrorCodes.STATS_INVALID_PERIOD, exception.getErrorCode());
            verifyNoInteractions(clientMock);
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure for stats")
        void shouldThrowExceptionWhenClientReturnsFailureForStats() {
            var errorResponse = PortfolioRiskTestDataFactory.errorPortfolioStatsResponse("No data found");

            when(clientMock.getPortfolioStats(anyString(), any()))
                    .thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getDailyStats("2024-01-15")
            );

            assertEquals(ErrorCodes.STATS_CALCULATION_FAILED, exception.getErrorCode());

            verify(clientMock, times(1)).getPortfolioStats("daily", "2024-01-15");
        }
    }

    // ============================================================
    // DRAWDOWN TESTS
    // ============================================================

    @Nested
    @DisplayName("Drawdown Tests")
    class DrawdownTests {

        @Test
        @DisplayName("Should get drawdown info successfully")
        void shouldGetDrawdownInfoSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validDrawdownResponse();

            when(clientMock.getDrawdownInfo())
                    .thenReturn(expectedResponse);

            var response = service.getDrawdownInfo();

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals(2.0, response.currentPercent());
            assertEquals(5.0, response.maxPercent());

            verify(clientMock, times(1)).getDrawdownInfo();
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure for drawdown")
        void shouldThrowExceptionWhenClientReturnsFailureForDrawdown() {
            var errorResponse = PortfolioRiskTestDataFactory.errorDrawdownResponse("Service unavailable");

            when(clientMock.getDrawdownInfo())
                    .thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getDrawdownInfo()
            );

            assertEquals(ErrorCodes.DRAWDOWN_CALCULATION_FAILED, exception.getErrorCode());

            verify(clientMock, times(1)).getDrawdownInfo();
        }
    }

    // ============================================================
    // FUNDED COMPLIANCE TESTS
    // ============================================================

    @Nested
    @DisplayName("Funded Compliance Tests")
    class FundedComplianceTests {

        @Test
        @DisplayName("Should get funded compliance successfully")
        void shouldGetFundedComplianceSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validFundedComplianceResponse();

            when(clientMock.getFundedCompliance())
                    .thenReturn(expectedResponse);

            var response = service.getFundedCompliance();

            assertNotNull(response);
            assertTrue(response.success());
            assertEquals("FTMO", response.accountType());
            assertTrue(response.compliant());

            verify(clientMock, times(1)).getFundedCompliance();
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure for funded compliance")
        void shouldThrowExceptionWhenClientReturnsFailureForFundedCompliance() {
            var errorResponse = PortfolioRiskTestDataFactory.errorFundedComplianceResponse("Service unavailable");

            when(clientMock.getFundedCompliance())
                    .thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.getFundedCompliance()
            );

            assertEquals(ErrorCodes.FUNDED_ACCOUNT_COMPLIANCE_FAILED, exception.getErrorCode());

            verify(clientMock, times(1)).getFundedCompliance();
        }
    }

    // ============================================================
    // REFRESH TESTS
    // ============================================================

    @Nested
    @DisplayName("Refresh Tests")
    class RefreshTests {

        @Test
        @DisplayName("Should refresh portfolio stats successfully")
        void shouldRefreshPortfolioStatsSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validRefreshResponse();

            when(clientMock.refreshPortfolioStats())
                    .thenReturn(expectedResponse);

            var response = service.refreshPortfolioStats();

            assertNotNull(response);
            assertTrue(response.success());

            verify(clientMock, times(1)).refreshPortfolioStats();
        }

        @Test
        @DisplayName("Should throw TradingException when client returns failure for refresh")
        void shouldThrowExceptionWhenClientReturnsFailureForRefresh() {
            var errorResponse = PortfolioRiskTestDataFactory.errorRefreshResponse("Service unavailable");

            when(clientMock.refreshPortfolioStats())
                    .thenReturn(errorResponse);

            var exception = assertThrows(
                    TradingException.class,
                    () -> service.refreshPortfolioStats()
            );

            assertEquals(ErrorCodes.REFRESH_STATS_FAILED, exception.getErrorCode());

            verify(clientMock, times(1)).refreshPortfolioStats();
        }
    }

    // ============================================================
    // HEALTH TESTS
    // ============================================================

    @Nested
    @DisplayName("Health Tests")
    class HealthTests {

        @Test
        @DisplayName("Should get health successfully")
        void shouldGetHealthSuccessfully() {
            var expectedResponse = PortfolioRiskTestDataFactory.validHealthResponse();

            when(clientMock.healthCheck())
                    .thenReturn(expectedResponse);

            var response = service.healthCheck();

            assertNotNull(response);
            assertEquals("operational", response.status());

            verify(clientMock, times(1)).healthCheck();
        }

        @Test
        @DisplayName("Should return error health when client throws exception")
        void shouldReturnErrorHealthWhenClientThrowsException() {
            when(clientMock.healthCheck())
                    .thenThrow(new RuntimeException("Service unavailable"));

            var response = service.healthCheck();

            assertNotNull(response);
            assertEquals("error", response.status());
            assertFalse(response.serviceInitialized());

            verify(clientMock, times(1)).healthCheck();
        }
    }
}