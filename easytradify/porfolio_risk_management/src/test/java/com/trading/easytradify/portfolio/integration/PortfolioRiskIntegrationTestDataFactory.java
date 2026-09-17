package com.trading.easytradify.portfolio.integration;

import com.trading.easytradify.portfolio.models.*;

import java.util.List;
import java.util.Map;

/**
 * Factory for creating portfolio risk integration test data.
 */
public final class PortfolioRiskIntegrationTestDataFactory {

    private PortfolioRiskIntegrationTestDataFactory() {
        // Private constructor
    }

    // ============================================================
    // CONFIGURATION UPDATE REQUESTS
    // ============================================================

    public static PortfolioConfigUpdateRequest validConfigUpdateRequest() {
        var updates = Map.<String, Object>of(
                "trade_size_in_usd", 300.0,
                "max_daily_loss_percent", 4.0,
                "max_daily_trades", 8,
                "max_risk_per_trade_percent", 3.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest dailyLimitsUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_daily_loss_percent", 3.0,
                "max_daily_trades", 8,
                "max_daily_win_target_percent", 8.0,
                "max_daily_consecutive_losses", 2
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest monthlyLimitsUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_monthly_loss_percent", 8.0,
                "max_monthly_trades", 80,
                "max_monthly_win_target_percent", 20.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest ytdLimitsUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_ytd_loss_percent", 12.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest riskPerTradeUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_risk_per_trade_percent", 2.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest drawdownUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_drawdown_percent", 8.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest consecutiveLossesUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_consecutive_losses", 4,
                "max_daily_consecutive_losses", 2
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest fundedAccountUpdateRequest() {
        var updates = Map.<String, Object>of(
                "funded_account_type", "FTMO",
                "funded_account_rules", Map.of(
                        "max_daily_loss", 5.0,
                        "max_monthly_loss", 10.0,
                        "max_drawdown", 10.0
                )
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest tradingHoursUpdateRequest() {
        var updates = Map.<String, Object>of(
                "trading_start_hour", 8,
                "trading_end_hour", 22
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigFieldUpdateRequest fieldUpdateRequest(Object value) {
        return new PortfolioConfigFieldUpdateRequest(value);
    }

    // ============================================================
    // CHECK TRADING ALLOWED REQUESTS
    // ============================================================

    public static CheckTradingAllowedRequest checkTradingAllowedRequest() {
        return new CheckTradingAllowedRequest(2.0);
    }

    public static CheckTradingAllowedRequest checkTradingAllowedRequestWithNoRisk() {
        return new CheckTradingAllowedRequest(null);
    }

    public static CheckTradingAllowedRequest checkTradingAllowedRequestWithHighRisk() {
        return new CheckTradingAllowedRequest(10.0);
    }

    // ============================================================
    // STATS REQUESTS
    // ============================================================

    public static String dailyStatsDate() {
        return "2024-01-15";
    }

    public static String monthlyStatsMonth() {
        return "2024-01";
    }

    public static Integer ytdStatsYear() {
        return 2024;
    }
}