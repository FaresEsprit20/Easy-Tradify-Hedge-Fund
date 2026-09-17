package com.trading.easytradify.portfolio.services;

import com.trading.easytradify.portfolio.client.PythonPortfolioRiskClient;
import com.trading.easytradify.portfolio.models.*;

/**
 * <h1>Portfolio Risk Management Service</h1>
 * <p>
 * Core service for managing portfolio risk, tracking performance,
 * and enforcing trading limits based on risk configuration.
 * </p>
 *
 * <h2>Architecture Overview</h2>
 * <p>
 * This service acts as a bridge between the application layer and the
 * Python portfolio risk service. It provides:
 * </p>
 * <ul>
 *   <li><b>Risk Configuration:</b> Get and update portfolio risk limits</li>
 *   <li><b>Portfolio Status:</b> Real-time P&amp;L, drawdown, and risk metrics</li>
 *   <li><b>Trading Permissions:</b> Check if trading is allowed based on risk limits</li>
 *   <li><b>Statistics:</b> Daily/Monthly/YTD performance tracking</li>
 *   <li><b>Compliance:</b> Funded account rule validation (FTMO, MFF, TFT)</li>
 * </ul>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Thin Service:</b> All business logic is delegated to the Python client</li>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Declarative Validation:</b> Input validation is explicit and throws domain exceptions</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * <h2>Error Handling Strategy</h2>
 * <ol>
 *   <li>Validate inputs → throws {@link com.trading.easytradify.common.exception.TradingException} if invalid</li>
 *   <li>Delegate to client → returns a response object</li>
 *   <li>Check response success flag → throws {@link com.trading.easytradify.common.exception.TradingException} if {@code false}</li>
 *   <li>Return successful response to caller</li>
 * </ol>
 * <p>
 * All exceptions are propagated to {@code GlobalExceptionHandler}
 * for consistent error response formatting.
 * </p>
 *
 * <h2>Usage Example</h2>
 * <pre>
 * {@code
 * @Autowired
 * private PortfolioRiskService portfolioRiskService;
 *
 * public void checkTrading() {
 *     var request = new CheckTradingAllowedRequest(1.5);
 *     var response = portfolioRiskService.checkTradingAllowed(request);
 *     if (response.isTradingAllowed()) {
 *         // Execute trade
 *     }
 * }
 * }
 * </pre>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see PythonPortfolioRiskClient
 * @see com.trading.easytradify.common.exception.TradingException
 * @see com.trading.easytradify.common.exception.ErrorCodes
 */
public interface PortfolioRiskService {

    // ============================================================
    // PORTFOLIO STATUS
    // ============================================================

    /**
     * <h3>Get Portfolio Status</h3>
     * <p>
     * Retrieves the current portfolio status including account information,
     * daily/monthly/YTD performance, and risk metrics.
     * </p>
     *
     * <h4>Status Information Includes</h4>
     * <ul>
     *   <li><b>Account:</b> Balance, equity, leverage, currency</li>
     *   <li><b>Daily:</b> Profit/Loss in USD and %, trades, win rate, drawdown</li>
     *   <li><b>Monthly:</b> Profit/Loss in USD and %, trades, win rate, drawdown</li>
     *   <li><b>YTD:</b> Profit/Loss in USD and %, trades, win rate, drawdown</li>
     *   <li><b>Risk:</b> Current risk level, remaining loss limits, consecutive losses</li>
     * </ul>
     *
     * @param refresh Whether to force refresh from Firebase
     * @param summary Whether to return only a lightweight summary
     * @return {@link PortfolioStatusResponse} containing the portfolio status
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails
     */
    PortfolioStatusResponse getPortfolioStatus(boolean refresh, boolean summary);

    /**
     * <h3>Get Portfolio Summary</h3>
     * <p>
     * Retrieves a lightweight summary of the portfolio status.
     * </p>
     * <p>
     * This is a convenience method that calls {@link #getPortfolioStatus}
     * with summary=true and refresh=false.
     * </p>
     *
     * @return {@link PortfolioStatusResponse} containing the portfolio summary
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails
     */
    PortfolioStatusResponse getPortfolioSummary();

    // ============================================================
    // CONFIGURATION
    // ============================================================

    /**
     * <h3>Get Portfolio Configuration</h3>
     * <p>
     * Retrieves the current portfolio risk configuration.
     * </p>
     *
     * <h4>Configuration Fields</h4>
     * <ul>
     *   <li><b>trade_size_in_usd:</b> Default trade size in USD</li>
     *   <li><b>max_daily_loss_percent:</b> Max daily loss as percentage</li>
     *   <li><b>max_daily_trades:</b> Max trades per day</li>
     *   <li><b>max_daily_win_target_percent:</b> Daily profit target</li>
     *   <li><b>max_monthly_loss_percent:</b> Max monthly loss as percentage</li>
     *   <li><b>max_monthly_trades:</b> Max trades per month</li>
     *   <li><b>max_monthly_win_target_percent:</b> Monthly profit target</li>
     *   <li><b>max_ytd_loss_percent:</b> Max YTD loss as percentage</li>
     *   <li><b>max_risk_per_trade_percent:</b> Max risk per trade</li>
     *   <li><b>max_drawdown_percent:</b> Max drawdown as percentage</li>
     *   <li><b>max_consecutive_losses:</b> Max consecutive losses</li>
     *   <li><b>max_daily_consecutive_losses:</b> Max daily consecutive losses</li>
     *   <li><b>funded_account_type:</b> STANDARD, FTMO, MFF, TFT</li>
     *   <li><b>trading_start_hour:</b> Trading start hour (0-23)</li>
     *   <li><b>trading_end_hour:</b> Trading end hour (0-23)</li>
     * </ul>
     *
     * @return {@link PortfolioConfigResponse} containing the current configuration
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails
     */
    PortfolioConfigResponse getPortfolioConfig();

    /**
     * <h3>Get Configuration Field</h3>
     * <p>
     * Retrieves a specific configuration field value.
     * </p>
     *
     * @param field The configuration field name (e.g., "max_daily_loss_percent")
     *              Must not be {@code null} or empty
     * @return {@link PortfolioConfigFieldResponse} containing the field value
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized, the field is not found,
     *         or the request fails
     */
    PortfolioConfigFieldResponse getPortfolioConfigField(String field);

    /**
     * <h3>Update Portfolio Configuration</h3>
     * <p>
     * Updates multiple portfolio configuration fields.
     * </p>
     *
     * <h4>Validation Rules</h4>
     * <ul>
     *   <li>All percentage fields must be between 0 and 100</li>
     *   <li>Trade size must be positive</li>
     *   <li>Max trades must be positive integers</li>
     *   <li>Consecutive losses must be positive integers</li>
     *   <li>Trading hours must be between 0 and 23</li>
     *   <li>Funded account type must be valid (STANDARD, FTMO, MFF, TFT)</li>
     * </ul>
     *
     * @param request The configuration update request containing the fields to update
     *                Must not be {@code null}
     * @return {@link PortfolioConfigResponse} containing the updated configuration
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized, the request is invalid,
     *         or the update fails
     */
    PortfolioConfigResponse updatePortfolioConfig(PortfolioConfigUpdateRequest request);

    /**
     * <h3>Update Configuration Field</h3>
     * <p>
     * Updates a specific configuration field.
     * </p>
     *
     * @param field   The configuration field name
     *                Must not be {@code null} or empty
     * @param request The field update request containing the new value
     *                Must not be {@code null}
     * @return {@link PortfolioConfigFieldResponse} containing the updated field value
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized, the field is not found,
     *         or the update fails
     */
    PortfolioConfigFieldResponse updatePortfolioConfigField(
            String field,
            PortfolioConfigFieldUpdateRequest request
    );

    // ============================================================
    // TRADING PERMISSION CHECKS
    // ============================================================

    /**
     * <h3>Check if Trading is Allowed</h3>
     * <p>
     * Checks if trading is allowed based on current portfolio risk limits.
     * Optionally validates the trade against per-trade risk limits.
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
     * <h4>Risk Levels</h4>
     * <ul>
     *   <li><b>SAFE:</b> No violations, trading allowed</li>
     *   <li><b>CAUTION:</b> Minor violations approaching, trading allowed</li>
     *   <li><b>WARNING:</b> Multiple violations approaching, trading allowed</li>
     *   <li><b>CRITICAL:</b> Severe violations, trading blocked</li>
     *   <li><b>MAX_EXCEEDED:</b> Hard limit exceeded, trading blocked</li>
     * </ul>
     *
     * @param request The check request containing optional trade risk percentage
     *                Must not be {@code null}
     * @return {@link CheckTradingAllowedResponse} containing the check result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails
     */
    CheckTradingAllowedResponse checkTradingAllowed(CheckTradingAllowedRequest request);

    /**
     * <h3>Get Maximum Risk Per Trade</h3>
     * <p>
     * Retrieves the maximum risk percentage allowed for a trade.
     * </p>
     *
     * @return {@link MaxRiskForTradeResponse} containing the maximum risk percentage
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails
     */
    MaxRiskForTradeResponse getMaxRiskForTrade();

    // ============================================================
    // STATISTICS
    // ============================================================

    /**
     * <h3>Get Portfolio Statistics</h3>
     * <p>
     * Retrieves portfolio statistics for a specified period.
     * </p>
     *
     * <h4>Periods</h4>
     * <ul>
     *   <li><b>daily:</b> Statistics for a specific day (date: YYYY-MM-DD)</li>
     *   <li><b>monthly:</b> Statistics for a specific month (date: YYYY-MM)</li>
     *   <li><b>ytd:</b> Statistics for a specific year (date: YYYY)</li>
     * </ul>
     *
     * <h4>Statistics Include</h4>
     * <ul>
     *   <li>Total profit/loss in USD and %</li>
     *   <li>Win rate</li>
     *   <li>Trade count</li>
     *   <li>Max drawdown</li>
     *   <li>Starting and ending balance</li>
     * </ul>
     *
     * @param period The statistics period: daily, monthly, or ytd
     *               Must not be {@code null}
     * @param date   The date for the statistics period.
     *               If {@code null}, uses the current date
     * @return {@link PortfolioStatsResponse} containing the statistics
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized, the period is invalid,
     *         or no data is found
     */
    PortfolioStatsResponse getPortfolioStats(String period, String date);

    /**
     * <h3>Get Daily Statistics</h3>
     * <p>
     * Retrieves statistics for today or a specific date.
     * </p>
     * <p>
     * This is a convenience method that calls {@link #getPortfolioStats}
     * with period="daily".
     * </p>
     *
     * @param date The date in YYYY-MM-DD format.
     *             If {@code null}, uses today
     * @return {@link PortfolioStatsResponse} containing the daily statistics
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or no data is found
     */
    PortfolioStatsResponse getDailyStats(String date);

    /**
     * <h3>Get Monthly Statistics</h3>
     * <p>
     * Retrieves statistics for the current month or a specific month.
     * </p>
     * <p>
     * This is a convenience method that calls {@link #getPortfolioStats}
     * with period="monthly".
     * </p>
     *
     * @param month The month in YYYY-MM format.
     *              If {@code null}, uses the current month
     * @return {@link PortfolioStatsResponse} containing the monthly statistics
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or no data is found
     */
    PortfolioStatsResponse getMonthlyStats(String month);

    /**
     * <h3>Get YTD Statistics</h3>
     * <p>
     * Retrieves statistics for the current year or a specific year.
     * </p>
     * <p>
     * This is a convenience method that calls {@link #getPortfolioStats}
     * with period="ytd".
     * </p>
     *
     * @param year The year in YYYY format.
     *             If {@code null}, uses the current year
     * @return {@link PortfolioStatsResponse} containing the YTD statistics
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or no data is found
     */
    PortfolioStatsResponse getYtdStats(Integer year);

    // ============================================================
    // DRAWDOWN
    // ============================================================

    /**
     * <h3>Get Drawdown Information</h3>
     * <p>
     * Retrieves current and maximum drawdown information.
     * </p>
     *
     * <h4>Drawdown Metrics</h4>
     * <ul>
     *   <li><b>current_percent:</b> Current drawdown from peak as percentage</li>
     *   <li><b>max_percent:</b> Maximum historical drawdown as percentage</li>
     * </ul>
     *
     * @return {@link DrawdownResponse} containing drawdown information
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails
     */
    DrawdownResponse getDrawdownInfo();

    // ============================================================
    // FUNDED ACCOUNT COMPLIANCE
    // ============================================================

    /**
     * <h3>Get Funded Account Compliance</h3>
     * <p>
     * Retrieves funded account compliance information.
     * </p>
     *
     * <h4>Supported Account Types</h4>
     * <ul>
     *   <li><b>STANDARD:</b> No specific rules, always compliant</li>
     *   <li><b>FTMO:</b> Max daily loss 5%, max monthly loss 10%, max drawdown 10%</li>
     *   <li><b>MFF:</b> Max daily loss 5%, max monthly loss 12%, max drawdown 12%</li>
     *   <li><b>TFT:</b> Max daily loss 5%, max monthly loss 8%, max drawdown 8%</li>
     * </ul>
     *
     * <h4>Compliance Check</h4>
     * <p>
     * The service validates that the current portfolio risk limits
     * do not exceed the funded account's maximum allowed limits.
     * </p>
     *
     * @return {@link FundedComplianceResponse} containing compliance information
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the request fails
     */
    FundedComplianceResponse getFundedCompliance();

    // ============================================================
    // REFRESH
    // ============================================================

    /**
     * <h3>Refresh Portfolio Statistics</h3>
     * <p>
     * Forces a refresh of statistics from Firebase.
     * </p>
     * <p>
     * This is useful when you want to ensure the latest trade data
     * is reflected in the portfolio statistics.
     * </p>
     *
     * @return {@link RefreshResponse} indicating the refresh result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the portfolio service is not initialized or the refresh fails
     */
    RefreshResponse refreshPortfolioStats();

    // ============================================================
    // HEALTH
    // ============================================================

    /**
     * <h3>Health Check</h3>
     * <p>
     * Performs a health check on the Python portfolio risk service.
     * </p>
     *
     * @return {@link HealthResponse} containing the service health status
     */
    HealthResponse healthCheck();
}