package com.trading.easytradify.portfolio.unit;

import com.trading.easytradify.portfolio.models.*;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * Factory for creating portfolio risk test data.
 * Centralizes test fixture creation to avoid duplication.
 */
public final class PortfolioRiskTestDataFactory {

    private PortfolioRiskTestDataFactory() {
        // Private constructor
    }

    // ============================================================
    // PORTFOLIO STATUS RESPONSE FIXTURES
    // ============================================================

    public static PortfolioStatusResponse validPortfolioStatusResponse() {
        var status = Map.<String, Object>ofEntries(
                Map.entry("timestamp", Instant.now().toString()),
                Map.entry("account_balance", 10000.0),
                Map.entry("account_equity", 10500.0),
                Map.entry("account_leverage", 200),
                Map.entry("account_currency", "USD"),
                Map.entry("trade_size_in_usd", 200.0),
                Map.entry("daily_profit_usd", 500.0),
                Map.entry("daily_profit_percent", 5.0),
                Map.entry("daily_loss_usd", 100.0),
                Map.entry("daily_loss_percent", 1.0),
                Map.entry("daily_net_profit_usd", 400.0),
                Map.entry("daily_net_profit_percent", 4.0),
                Map.entry("daily_trades", 5),
                Map.entry("daily_wins", 4),
                Map.entry("daily_losses", 1),
                Map.entry("daily_win_rate", 80.0),
                Map.entry("daily_drawdown_percent", 2.0),
                Map.entry("daily_remaining_loss_percent", 4.0),
                Map.entry("daily_remaining_win_target_percent", 6.0),
                Map.entry("daily_consecutive_losses", 0),
                Map.entry("monthly_profit_usd", 1500.0),
                Map.entry("monthly_profit_percent", 15.0),
                Map.entry("monthly_loss_usd", 300.0),
                Map.entry("monthly_loss_percent", 3.0),
                Map.entry("monthly_net_profit_usd", 1200.0),
                Map.entry("monthly_net_profit_percent", 12.0),
                Map.entry("monthly_trades", 20),
                Map.entry("monthly_wins", 15),
                Map.entry("monthly_losses", 5),
                Map.entry("monthly_win_rate", 75.0),
                Map.entry("monthly_drawdown_percent", 3.0),
                Map.entry("monthly_remaining_loss_percent", 7.0),
                Map.entry("monthly_remaining_win_target_percent", 10.0),
                Map.entry("ytd_profit_usd", 5000.0),
                Map.entry("ytd_profit_percent", 50.0),
                Map.entry("ytd_loss_usd", 1000.0),
                Map.entry("ytd_loss_percent", 10.0),
                Map.entry("ytd_net_profit_usd", 4000.0),
                Map.entry("ytd_net_profit_percent", 40.0),
                Map.entry("ytd_trades", 100),
                Map.entry("ytd_wins", 70),
                Map.entry("ytd_losses", 30),
                Map.entry("ytd_win_rate", 70.0),
                Map.entry("ytd_drawdown_percent", 5.0),
                Map.entry("ytd_remaining_loss_percent", 5.0),
                Map.entry("overall_risk_level", "SAFE"),
                Map.entry("max_drawdown_percent", 5.0),
                Map.entry("current_drawdown_percent", 2.0),
                Map.entry("consecutive_losses", 0),
                Map.entry("is_trading_allowed", true),
                Map.entry("trading_blocked_reasons", List.of()),
                Map.entry("funded_account_compliance", Map.of(
                        "type", "STANDARD",
                        "compliant", true,
                        "violations", List.of()
                )),
                Map.entry("max_risk_per_trade_percent", 5.0)
        );
        return new PortfolioStatusResponse(true, status, null);
    }

    public static PortfolioStatusResponse validPortfolioSummaryResponse() {
        var summary = Map.<String, Object>ofEntries(
                Map.entry("timestamp", Instant.now().toString()),
                Map.entry("account", Map.of(
                        "balance", 10000.0,
                        "equity", 10500.0,
                        "leverage", 200,
                        "currency", "USD"
                )),
                Map.entry("trading", Map.of(
                        "is_allowed", true,
                        "risk_level", "SAFE",
                        "blocked_reasons", List.of()
                )),
                Map.entry("trade_size_in_usd", 200.0),
                Map.entry("max_risk_per_trade_percent", 5.0),
                Map.entry("daily", Map.of(
                        "net_profit_usd", 400.0,
                        "net_profit_percent", 4.0,
                        "trades", 5,
                        "win_rate", 80.0,
                        "remaining_loss_percent", 4.0,
                        "consecutive_losses", 0
                )),
                Map.entry("monthly", Map.of(
                        "net_profit_usd", 1200.0,
                        "net_profit_percent", 12.0,
                        "trades", 20,
                        "win_rate", 75.0,
                        "remaining_loss_percent", 7.0
                )),
                Map.entry("ytd", Map.of(
                        "net_profit_usd", 4000.0,
                        "net_profit_percent", 40.0,
                        "trades", 100,
                        "win_rate", 70.0,
                        "remaining_loss_percent", 5.0
                )),
                Map.entry("drawdown", Map.of(
                        "current_percent", 2.0,
                        "max_percent", 5.0
                ))
        );
        return new PortfolioStatusResponse(true, summary, null);
    }

    public static PortfolioStatusResponse errorPortfolioStatusResponse(String error) {
        return new PortfolioStatusResponse(false, null, error);
    }

    // ============================================================
    // PORTFOLIO CONFIG RESPONSE FIXTURES
    // ============================================================

    public static PortfolioConfigResponse validPortfolioConfigResponse() {
        var config = Map.<String, Object>ofEntries(
                Map.entry("trade_size_in_usd", 200.0),
                Map.entry("max_daily_loss_percent", 5.0),
                Map.entry("max_daily_trades", 10),
                Map.entry("max_daily_win_target_percent", 10.0),
                Map.entry("max_monthly_loss_percent", 10.0),
                Map.entry("max_monthly_trades", 100),
                Map.entry("max_monthly_win_target_percent", 25.0),
                Map.entry("max_ytd_loss_percent", 15.0),
                Map.entry("max_risk_per_trade_percent", 5.0),
                Map.entry("max_drawdown_percent", 10.0),
                Map.entry("max_consecutive_losses", 5),
                Map.entry("max_daily_consecutive_losses", 3),
                Map.entry("funded_account_type", "STANDARD"),
                Map.entry("funded_account_rules", Map.of()),
                Map.entry("trading_start_hour", 0),
                Map.entry("trading_end_hour", 23)
        );
        return new PortfolioConfigResponse(true, config, null);
    }

    public static PortfolioConfigResponse errorPortfolioConfigResponse(String error) {
        return new PortfolioConfigResponse(false, null, error);
    }

    // ============================================================
    // PORTFOLIO CONFIG FIELD RESPONSE FIXTURES
    // ============================================================

    public static PortfolioConfigFieldResponse validPortfolioConfigFieldResponse(String field, Object value) {
        return new PortfolioConfigFieldResponse(true, field, value, null);
    }

    public static PortfolioConfigFieldResponse errorPortfolioConfigFieldResponse(String error) {
        return new PortfolioConfigFieldResponse(false, null, null, error);
    }

    // ============================================================
    // PORTFOLIO CONFIG UPDATE REQUEST FIXTURES
    // ============================================================

    public static PortfolioConfigUpdateRequest validPortfolioConfigUpdateRequest() {
        var updates = Map.<String, Object>ofEntries(
                Map.entry("trade_size_in_usd", 300.0),
                Map.entry("max_daily_loss_percent", 4.0),
                Map.entry("max_daily_trades", 8),
                Map.entry("max_risk_per_trade_percent", 3.0)
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest validDailyLimitsUpdateRequest() {
        var updates = Map.<String, Object>ofEntries(
                Map.entry("max_daily_loss_percent", 3.0),
                Map.entry("max_daily_trades", 8),
                Map.entry("max_daily_win_target_percent", 8.0),
                Map.entry("max_daily_consecutive_losses", 2)
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest validMonthlyLimitsUpdateRequest() {
        var updates = Map.<String, Object>ofEntries(
                Map.entry("max_monthly_loss_percent", 8.0),
                Map.entry("max_monthly_trades", 80),
                Map.entry("max_monthly_win_target_percent", 20.0)
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest validYtdLimitsUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_ytd_loss_percent", 12.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest validRiskPerTradeUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_risk_per_trade_percent", 2.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest validDrawdownUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_drawdown_percent", 8.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest validConsecutiveLossesUpdateRequest() {
        var updates = Map.<String, Object>ofEntries(
                Map.entry("max_consecutive_losses", 4),
                Map.entry("max_daily_consecutive_losses", 2)
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest validFundedAccountUpdateRequest() {
        var updates = Map.<String, Object>ofEntries(
                Map.entry("funded_account_type", "FTMO"),
                Map.entry("funded_account_rules", Map.of(
                        "max_daily_loss", 5.0,
                        "max_monthly_loss", 10.0,
                        "max_drawdown", 10.0
                ))
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest validTradingHoursUpdateRequest() {
        var updates = Map.<String, Object>ofEntries(
                Map.entry("trading_start_hour", 8),
                Map.entry("trading_end_hour", 22)
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest invalidConfigUpdateRequest() {
        var updates = Map.<String, Object>of(
                "invalid_field", "some_value"
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest invalidPercentageUpdateRequest() {
        var updates = Map.<String, Object>of(
                "max_daily_loss_percent", 105.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    public static PortfolioConfigUpdateRequest invalidTradeSizeUpdateRequest() {
        var updates = Map.<String, Object>of(
                "trade_size_in_usd", -100.0
        );
        return new PortfolioConfigUpdateRequest(updates);
    }

    // ============================================================
    // PORTFOLIO CONFIG FIELD UPDATE REQUEST FIXTURES
    // ============================================================

    public static PortfolioConfigFieldUpdateRequest validFieldUpdateRequest(Object value) {
        return new PortfolioConfigFieldUpdateRequest(value);
    }

    public static PortfolioConfigFieldUpdateRequest invalidFieldUpdateRequest() {
        return new PortfolioConfigFieldUpdateRequest(null);
    }

    // ============================================================
    // CHECK TRADING ALLOWED REQUEST FIXTURES
    // ============================================================

    public static CheckTradingAllowedRequest validCheckTradingAllowedRequest() {
        return new CheckTradingAllowedRequest(2.0);
    }

    public static CheckTradingAllowedRequest checkTradingAllowedRequestWithNoRisk() {
        return new CheckTradingAllowedRequest(null);
    }

    public static CheckTradingAllowedRequest checkTradingAllowedRequestWithHighRisk() {
        return new CheckTradingAllowedRequest(10.0);
    }

    // ============================================================
    // CHECK TRADING ALLOWED RESPONSE FIXTURES
    // ============================================================

    public static CheckTradingAllowedResponse validCheckTradingAllowedResponse() {
        return new CheckTradingAllowedResponse(
                true,
                true,
                "SAFE",
                List.of(),
                null,
                5.0,
                null
        );
    }

    public static CheckTradingAllowedResponse blockedTradingAllowedResponse() {
        return new CheckTradingAllowedResponse(
                true,
                false,
                "CRITICAL",
                List.of("Daily loss limit reached: 6.0% >= 5.0%"),
                null,
                5.0,
                null
        );
    }

    public static CheckTradingAllowedResponse blockedWithRiskResponse() {
        return new CheckTradingAllowedResponse(
                true,
                false,
                "WARNING",
                List.of("Trade risk 10.0% exceeds max 5.0%"),
                10.0,
                5.0,
                null
        );
    }

    public static CheckTradingAllowedResponse errorCheckTradingAllowedResponse(String error) {
        return new CheckTradingAllowedResponse(false, null, null, null, null, null, error);
    }

    // ============================================================
    // MAX RISK FOR TRADE RESPONSE FIXTURES
    // ============================================================

    public static MaxRiskForTradeResponse validMaxRiskForTradeResponse() {
        return new MaxRiskForTradeResponse(true, 5.0, null);
    }

    public static MaxRiskForTradeResponse errorMaxRiskForTradeResponse(String error) {
        return new MaxRiskForTradeResponse(false, null, error);
    }

    // ============================================================
    // PORTFOLIO STATS RESPONSE FIXTURES
    // ============================================================

    public static PortfolioStatsResponse validDailyStatsResponse() {
        var data = Map.<String, Object>ofEntries(
                Map.entry("date", "2024-01-15"),
                Map.entry("total_profit_usd", 500.0),
                Map.entry("total_profit_percent", 5.0),
                Map.entry("total_loss_usd", 100.0),
                Map.entry("total_loss_percent", 1.0),
                Map.entry("net_profit_usd", 400.0),
                Map.entry("net_profit_percent", 4.0),
                Map.entry("trades_count", 5),
                Map.entry("winning_trades", 4),
                Map.entry("losing_trades", 1),
                Map.entry("win_rate", 80.0)
        );
        return new PortfolioStatsResponse(true, "daily", data, null);
    }

    public static PortfolioStatsResponse validMonthlyStatsResponse() {
        var data = Map.<String, Object>ofEntries(
                Map.entry("month", "2024-01"),
                Map.entry("total_profit_usd", 1500.0),
                Map.entry("total_profit_percent", 15.0),
                Map.entry("total_loss_usd", 300.0),
                Map.entry("total_loss_percent", 3.0),
                Map.entry("net_profit_usd", 1200.0),
                Map.entry("net_profit_percent", 12.0),
                Map.entry("trades_count", 20),
                Map.entry("winning_trades", 15),
                Map.entry("losing_trades", 5),
                Map.entry("win_rate", 75.0)
        );
        return new PortfolioStatsResponse(true, "monthly", data, null);
    }

    public static PortfolioStatsResponse validYtdStatsResponse() {
        var data = Map.<String, Object>ofEntries(
                Map.entry("year", 2024),
                Map.entry("total_profit_usd", 5000.0),
                Map.entry("total_profit_percent", 50.0),
                Map.entry("total_loss_usd", 1000.0),
                Map.entry("total_loss_percent", 10.0),
                Map.entry("net_profit_usd", 4000.0),
                Map.entry("net_profit_percent", 40.0),
                Map.entry("trades_count", 100),
                Map.entry("winning_trades", 70),
                Map.entry("losing_trades", 30),
                Map.entry("win_rate", 70.0)
        );
        return new PortfolioStatsResponse(true, "ytd", data, null);
    }

    public static PortfolioStatsResponse errorPortfolioStatsResponse(String error) {
        return new PortfolioStatsResponse(false, null, null, error);
    }

    // ============================================================
    // DRAWDOWN RESPONSE FIXTURES
    // ============================================================

    public static DrawdownResponse validDrawdownResponse() {
        return new DrawdownResponse(true, 2.0, 5.0, null);
    }

    public static DrawdownResponse errorDrawdownResponse(String error) {
        return new DrawdownResponse(false, null, null, error);
    }

    // ============================================================
    // FUNDED COMPLIANCE RESPONSE FIXTURES
    // ============================================================

    public static FundedComplianceResponse validFundedComplianceResponse() {
        return new FundedComplianceResponse(true, "FTMO", true, List.of(), null);
    }

    public static FundedComplianceResponse nonCompliantFundedComplianceResponse() {
        return new FundedComplianceResponse(
                true,
                "FTMO",
                false,
                List.of("Daily loss limit 6.0% exceeds FTMO max 5%"),
                null
        );
    }

    public static FundedComplianceResponse errorFundedComplianceResponse(String error) {
        return new FundedComplianceResponse(false, null, null, null, error);
    }

    // ============================================================
    // REFRESH RESPONSE FIXTURES
    // ============================================================

    public static RefreshResponse validRefreshResponse() {
        return new RefreshResponse(true, "Statistics refreshed successfully", null);
    }

    public static RefreshResponse errorRefreshResponse(String error) {
        return new RefreshResponse(false, null, error);
    }

    // ============================================================
    // HEALTH RESPONSE FIXTURES
    // ============================================================

    public static HealthResponse validHealthResponse() {
        return new HealthResponse("operational", true, null);
    }

    public static HealthResponse errorHealthResponse() {
        return new HealthResponse("error", false, "Service unavailable");
    }
}