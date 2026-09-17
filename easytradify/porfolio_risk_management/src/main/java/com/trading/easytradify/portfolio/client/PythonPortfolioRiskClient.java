package com.trading.easytradify.portfolio.client;

import com.trading.easytradify.portfolio.models.*;

/**
 * <h1>Python Portfolio Risk Service Client</h1>
 * <p>
 * Complete abstraction for the Python-based portfolio risk management service.
 * This interface provides a comprehensive set of methods that map directly
 * to the REST endpoints exposed by the Python portfolio risk controller on port 5010.
 * </p>
 * <p>
 * Each method corresponds to a specific Python endpoint and handles the
 * communication with the underlying Python service.
 * The client abstracts away the HTTP communication details and provides
 * a clean, type-safe API for the calling service layer.
 * </p>
 *
 * <h2>Architecture Overview</h2>
 * <ul>
 *   <li><b>Single Responsibility:</b> Each method maps to exactly one Python endpoint</li>
 *   <li><b>Immutable Contracts:</b> All requests and responses are defined as immutable records</li>
 *   <li><b>Error Propagation:</b> Exceptions are propagated to the caller for centralized handling</li>
 *   <li><b>Standalone:</b> No broker dependency - pure portfolio risk management</li>
 * </ul>
 *
 * <h2>Base URL</h2>
 * <p>
 * All endpoints are prefixed with {@code /api/v1/portfolio}
 * </p>
 *
 * <h2>Port</h2>
 * <p>
 * The Python service runs on port 5010
 * </p>
 *
 * <h2>Error Handling</h2>
 * <p>
 * All errors are returned in a standardized format via
 * {@link com.trading.easytradify.common.exception.TradingException}.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see DefaultPythonPortfolioRiskClient
 */
public interface PythonPortfolioRiskClient {

    // ============================================================
    // PORTFOLIO STATUS
    // ============================================================

    /**
     * <h3>GET /api/v1/portfolio/status</h3>
     * <p>
     * Retrieves the current portfolio status including account information,
     * daily/monthly/YTD performance, and risk metrics.
     * </p>
     *
     * <h4>Query Parameters</h4>
     * <ul>
     *   <li><b>refresh:</b> Force refresh from Firebase (default: false)</li>
     *   <li><b>summary:</b> Return lightweight summary (default: false)</li>
     * </ul>
     *
     * @param refresh Whether to force refresh from Firebase.
     * @param summary Whether to return only a summary.
     * @return A {@link PortfolioStatusResponse} containing the portfolio status.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails.
     * @see PortfolioStatusResponse
     */
    PortfolioStatusResponse getPortfolioStatus(boolean refresh, boolean summary);

    /**
     * <h3>GET /api/v1/portfolio/status/summary</h3>
     * <p>
     * Retrieves a lightweight summary of the portfolio status.
     * This is a convenience method that calls {@link #getPortfolioStatus} with summary=true.
     * </p>
     *
     * @return A {@link PortfolioStatusResponse} containing the portfolio summary.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails.
     * @see PortfolioStatusResponse
     */
    PortfolioStatusResponse getPortfolioSummary();

    // ============================================================
    // CONFIGURATION
    // ============================================================

    /**
     * <h3>GET /api/v1/portfolio/config</h3>
     * <p>
     * Retrieves the current portfolio risk configuration.
     * </p>
     *
     * @return A {@link PortfolioConfigResponse} containing the current configuration.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails.
     * @see PortfolioConfigResponse
     */
    PortfolioConfigResponse getPortfolioConfig();

    /**
     * <h3>GET /api/v1/portfolio/config/{field}</h3>
     * <p>
     * Retrieves a specific configuration field.
     * </p>
     *
     * @param field The configuration field name.
     *              Must not be {@code null} or empty.
     * @return A {@link PortfolioConfigFieldResponse} containing the field value.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized, the field is not found,
     *         or the request fails.
     * @see PortfolioConfigFieldResponse
     */
    PortfolioConfigFieldResponse getPortfolioConfigField(String field);

    /**
     * <h3>PUT /api/v1/portfolio/config</h3>
     * <p>
     * Updates multiple portfolio configuration fields.
     * </p>
     *
     * <h4>Valid Fields</h4>
     * <ul>
     *   <li><b>trade_size_in_usd:</b> double</li>
     *   <li><b>max_daily_loss_percent:</b> double</li>
     *   <li><b>max_daily_trades:</b> int</li>
     *   <li><b>max_daily_win_target_percent:</b> double</li>
     *   <li><b>max_monthly_loss_percent:</b> double</li>
     *   <li><b>max_monthly_trades:</b> int</li>
     *   <li><b>max_monthly_win_target_percent:</b> double</li>
     *   <li><b>max_ytd_loss_percent:</b> double</li>
     *   <li><b>max_risk_per_trade_percent:</b> double</li>
     *   <li><b>max_drawdown_percent:</b> double</li>
     *   <li><b>max_consecutive_losses:</b> int</li>
     *   <li><b>max_daily_consecutive_losses:</b> int</li>
     *   <li><b>funded_account_type:</b> string</li>
     *   <li><b>funded_account_rules:</b> object</li>
     *   <li><b>trading_start_hour:</b> int</li>
     *   <li><b>trading_end_hour:</b> int</li>
     * </ul>
     *
     * @param request The configuration update request containing the fields to update.
     *                Must not be {@code null}.
     * @return A {@link PortfolioConfigResponse} containing the updated configuration.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized, the request is invalid,
     *         or the update fails.
     * @see PortfolioConfigUpdateRequest
     * @see PortfolioConfigResponse
     */
    PortfolioConfigResponse updatePortfolioConfig(PortfolioConfigUpdateRequest request);

    /**
     * <h3>PUT /api/v1/portfolio/config/{field}</h3>
     * <p>
     * Updates a specific configuration field.
     * </p>
     *
     * @param field   The configuration field name.
     *                Must not be {@code null} or empty.
     * @param request The configuration field update request containing the new value.
     *                Must not be {@code null}.
     * @return A {@link PortfolioConfigFieldResponse} containing the updated field value.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized, the field is not found,
     *         or the update fails.
     * @see PortfolioConfigFieldUpdateRequest
     * @see PortfolioConfigFieldResponse
     */
    PortfolioConfigFieldResponse updatePortfolioConfigField(
            String field,
            PortfolioConfigFieldUpdateRequest request
    );

    // ============================================================
    // TRADING PERMISSION CHECKS
    // ============================================================

    /**
     * <h3>POST /api/v1/portfolio/check_trading_allowed</h3>
     * <p>
     * Checks if trading is allowed based on current portfolio risk limits.
     * </p>
     *
     * <h4>Risk Checks Performed</h4>
     * <ul>
     *   <li>Account balance is positive</li>
     *   <li>Trading hours are within configured limits</li>
     *   <li>Daily loss limit not exceeded</li>
     *   <li>Daily win target not reached</li>
     *   <li>Daily trade count not exceeded</li>
     *   <li>Monthly loss limit not exceeded</li>
     *   <li>Monthly win target not reached</li>
     *   <li>Monthly trade count not exceeded</li>
     *   <li>YTD loss limit not exceeded</li>
     *   <li>Drawdown limit not exceeded</li>
     *   <li>Consecutive loss limits not exceeded</li>
     *   <li>Per-trade risk limit not exceeded (if provided)</li>
     * </ul>
     *
     * @param request The check trading allowed request containing optional trade risk.
     *                Must not be {@code null}.
     * @return A {@link CheckTradingAllowedResponse} containing the check result.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails.
     * @see CheckTradingAllowedRequest
     * @see CheckTradingAllowedResponse
     */
    CheckTradingAllowedResponse checkTradingAllowed(CheckTradingAllowedRequest request);

    /**
     * <h3>GET /api/v1/portfolio/max_risk_for_trade</h3>
     * <p>
     * Retrieves the maximum risk percentage allowed for a trade.
     * </p>
     *
     * @return A {@link MaxRiskForTradeResponse} containing the maximum risk percentage.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails.
     * @see MaxRiskForTradeResponse
     */
    MaxRiskForTradeResponse getMaxRiskForTrade();

    // ============================================================
    // STATISTICS
    // ============================================================

    /**
     * <h3>GET /api/v1/portfolio/stats</h3>
     * <p>
     * Retrieves portfolio statistics for a specified period.
     * </p>
     *
     * <h4>Query Parameters</h4>
     * <ul>
     *   <li><b>period:</b> daily, monthly, or ytd (default: daily)</li>
     *   <li><b>date:</b> YYYY-MM-DD for daily, YYYY-MM for monthly, YYYY for ytd</li>
     * </ul>
     *
     * @param period The statistics period: daily, monthly, or ytd.
     *               Must not be {@code null}.
     * @param date   The date for the statistics period.
     *               If {@code null}, uses the current date.
     * @return A {@link PortfolioStatsResponse} containing the statistics.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized, the period is invalid,
     *         or no data is found.
     * @see PortfolioStatsResponse
     */
    PortfolioStatsResponse getPortfolioStats(String period, String date);

    // ============================================================
    // DRAWDOWN
    // ============================================================

    /**
     * <h3>GET /api/v1/portfolio/drawdown</h3>
     * <p>
     * Retrieves drawdown information including current and maximum drawdown.
     * </p>
     *
     * @return A {@link DrawdownResponse} containing drawdown information.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails.
     * @see DrawdownResponse
     */
    DrawdownResponse getDrawdownInfo();

    // ============================================================
    // FUNDED ACCOUNT COMPLIANCE
    // ============================================================

    /**
     * <h3>GET /api/v1/portfolio/funded_compliance</h3>
     * <p>
     * Retrieves funded account compliance information.
     * </p>
     *
     * <h4>Supported Account Types</h4>
     * <ul>
     *   <li><b>STANDARD:</b> No specific rules</li>
     *   <li><b>FTMO:</b> Max daily loss 5%, max monthly loss 10%, max drawdown 10%</li>
     *   <li><b>MFF:</b> Max daily loss 5%, max monthly loss 12%, max drawdown 12%</li>
     *   <li><b>TFT:</b> Max daily loss 5%, max monthly loss 8%, max drawdown 8%</li>
     * </ul>
     *
     * @return A {@link FundedComplianceResponse} containing compliance information.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails.
     * @see FundedComplianceResponse
     */
    FundedComplianceResponse getFundedCompliance();

    // ============================================================
    // REFRESH
    // ============================================================

    /**
     * <h3>POST /api/v1/portfolio/refresh</h3>
     * <p>
     * Forces a refresh of statistics from Firebase.
     * </p>
     *
     * @return A {@link RefreshResponse} indicating the refresh result.
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the refresh fails.
     * @see RefreshResponse
     */
    RefreshResponse refreshPortfolioStats();

    // ============================================================
    // HEALTH
    // ============================================================

    /**
     * <h3>GET /health</h3>
     * <p>
     * Performs a health check on the Python portfolio risk service.
     * </p>
     *
     * @return A {@link HealthResponse} containing the service health status.
     */
    HealthResponse healthCheck();
}