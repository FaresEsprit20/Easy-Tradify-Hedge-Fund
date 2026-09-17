package com.trading.easytradify.portfolio.unit;

import com.trading.easytradify.portfolio.client.PythonPortfolioRiskClient;
import com.trading.easytradify.portfolio.models.*;

import java.util.Map;

/**
 * Mock implementation of PythonPortfolioRiskClient for unit testing.
 * Provides configurable success/failure responses.
 */
public class PythonPortfolioRiskClientMock implements PythonPortfolioRiskClient {

    private boolean shouldSucceed = true;
    private String errorMessage = "Mock error";
    private boolean shouldThrowException = false;

    public PythonPortfolioRiskClientMock withSuccess() {
        this.shouldSucceed = true;
        this.shouldThrowException = false;
        return this;
    }

    public PythonPortfolioRiskClientMock withFailure(String errorMessage) {
        this.shouldSucceed = false;
        this.errorMessage = errorMessage;
        this.shouldThrowException = false;
        return this;
    }

    public PythonPortfolioRiskClientMock withException() {
        this.shouldThrowException = true;
        return this;
    }

    @Override
    public PortfolioStatusResponse getPortfolioStatus(boolean refresh, boolean summary) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            if (summary) {
                return PortfolioRiskTestDataFactory.validPortfolioSummaryResponse();
            }
            return PortfolioRiskTestDataFactory.validPortfolioStatusResponse();
        }
        return PortfolioRiskTestDataFactory.errorPortfolioStatusResponse(errorMessage);
    }

    @Override
    public PortfolioStatusResponse getPortfolioSummary() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validPortfolioSummaryResponse();
        }
        return PortfolioRiskTestDataFactory.errorPortfolioStatusResponse(errorMessage);
    }

    @Override
    public PortfolioConfigResponse getPortfolioConfig() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validPortfolioConfigResponse();
        }
        return PortfolioRiskTestDataFactory.errorPortfolioConfigResponse(errorMessage);
    }

    @Override
    public PortfolioConfigFieldResponse getPortfolioConfigField(String field) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validPortfolioConfigFieldResponse(
                    field,
                    field.equals("max_daily_loss_percent") ? 5.0 : "some_value"
            );
        }
        return PortfolioRiskTestDataFactory.errorPortfolioConfigFieldResponse(errorMessage);
    }

    @Override
    public PortfolioConfigResponse updatePortfolioConfig(PortfolioConfigUpdateRequest request) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validPortfolioConfigResponse();
        }
        return PortfolioRiskTestDataFactory.errorPortfolioConfigResponse(errorMessage);
    }

    @Override
    public PortfolioConfigFieldResponse updatePortfolioConfigField(String field, PortfolioConfigFieldUpdateRequest request) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validPortfolioConfigFieldResponse(field, request.value());
        }
        return PortfolioRiskTestDataFactory.errorPortfolioConfigFieldResponse(errorMessage);
    }

    @Override
    public CheckTradingAllowedResponse checkTradingAllowed(CheckTradingAllowedRequest request) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validCheckTradingAllowedResponse();
        }
        return PortfolioRiskTestDataFactory.errorCheckTradingAllowedResponse(errorMessage);
    }

    @Override
    public MaxRiskForTradeResponse getMaxRiskForTrade() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validMaxRiskForTradeResponse();
        }
        return PortfolioRiskTestDataFactory.errorMaxRiskForTradeResponse(errorMessage);
    }

    @Override
    public PortfolioStatsResponse getPortfolioStats(String period, String date) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            if ("daily".equals(period)) {
                return PortfolioRiskTestDataFactory.validDailyStatsResponse();
            } else if ("monthly".equals(period)) {
                return PortfolioRiskTestDataFactory.validMonthlyStatsResponse();
            } else {
                return PortfolioRiskTestDataFactory.validYtdStatsResponse();
            }
        }
        return PortfolioRiskTestDataFactory.errorPortfolioStatsResponse(errorMessage);
    }

    @Override
    public DrawdownResponse getDrawdownInfo() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validDrawdownResponse();
        }
        return PortfolioRiskTestDataFactory.errorDrawdownResponse(errorMessage);
    }

    @Override
    public FundedComplianceResponse getFundedCompliance() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validFundedComplianceResponse();
        }
        return PortfolioRiskTestDataFactory.errorFundedComplianceResponse(errorMessage);
    }

    @Override
    public RefreshResponse refreshPortfolioStats() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validRefreshResponse();
        }
        return PortfolioRiskTestDataFactory.errorRefreshResponse(errorMessage);
    }

    @Override
    public HealthResponse healthCheck() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return PortfolioRiskTestDataFactory.validHealthResponse();
        }
        return PortfolioRiskTestDataFactory.errorHealthResponse();
    }
}