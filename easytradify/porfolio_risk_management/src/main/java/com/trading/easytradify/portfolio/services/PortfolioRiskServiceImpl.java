package com.trading.easytradify.portfolio.services;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.portfolio.client.PythonPortfolioRiskClient;
import com.trading.easytradify.portfolio.models.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.Set;

/**
 * <h1>Portfolio Risk Service Implementation</h1>
 * <p>
 * Default implementation of the {@link PortfolioRiskService} interface.
 * This service acts as a facade between the application layer and the
 * Python portfolio risk service.
 * </p>
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
 *   <li>Validate inputs → throws {@link TradingException} if invalid</li>
 *   <li>Delegate to client → returns a response object</li>
 *   <li>Check response success flag → throws {@link TradingException} if {@code false}</li>
 *   <li>Return successful response to caller</li>
 * </ol>
 * <p>
 * All exceptions are propagated to {@code GlobalExceptionHandler}
 * for consistent error response formatting.
 * </p>
 *
 * <h2>Validation Rules</h2>
 * <ul>
 *   <li>All percentage fields must be between 0 and 100</li>
 *   <li>Trade size must be positive</li>
 *   <li>Max trades must be positive integers</li>
 *   <li>Consecutive losses must be positive integers</li>
 *   <li>Trading hours must be between 0 and 23</li>
 *   <li>Period must be: daily, monthly, or ytd</li>
 *   <li>Date formats must match the period</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see PortfolioRiskService
 * @see PythonPortfolioRiskClient
 * @see TradingException
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class PortfolioRiskServiceImpl implements PortfolioRiskService {

    private final PythonPortfolioRiskClient portfolioRiskClient;

    // ============================================================
    // VALIDATION HELPERS
    // ============================================================

    /**
     * Validates that a field name is not {@code null} or empty.
     *
     * @param field The field name to validate
     * @throws TradingException If the field name is {@code null} or empty
     */
    private void validateField(String field) {
        if (!StringUtils.hasText(field)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PORTFOLIO_CONFIG_FIELD_NOT_FOUND)
                    .message("Field name cannot be null or empty")
                    .build();
        }
    }

    /**
     * Validates that a percentage value is within valid range (0-100).
     *
     * @param value The percentage value to validate
     * @param fieldName The name of the field (used in error message)
     * @throws TradingException If the percentage is outside valid range
     */
    private void validatePercentage(Double value, String fieldName) {
        if (value != null && (value < 0 || value > 100)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message(fieldName + " must be between 0 and 100: " + value)
                    .build();
        }
    }

    /**
     * Validates that a positive integer is valid.
     *
     * @param value The integer value to validate
     * @param fieldName The name of the field (used in error message)
     * @throws TradingException If the value is not positive
     */
    private void validatePositiveInteger(Integer value, String fieldName) {
        if (value != null && value <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message(fieldName + " must be positive: " + value)
                    .build();
        }
    }

    /**
     * Validates that a positive double is valid.
     *
     * @param value The double value to validate
     * @param fieldName The name of the field (used in error message)
     * @throws TradingException If the value is not positive
     */
    private void validatePositiveDouble(Double value, String fieldName) {
        if (value != null && value <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message(fieldName + " must be positive: " + value)
                    .build();
        }
    }

    /**
     * Validates that a trading hour is within valid range (0-23).
     *
     * @param hour The hour to validate
     * @param fieldName The name of the field (used in error message)
     * @throws TradingException If the hour is outside valid range
     */
    private void validateHour(Integer hour, String fieldName) {
        if (hour != null && (hour < 0 || hour > 23)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message(fieldName + " must be between 0 and 23: " + hour)
                    .build();
        }
    }

    /**
     * Validates that a funded account type is valid.
     *
     * @param type The account type to validate
     * @throws TradingException If the account type is invalid
     */
    private void validateFundedAccountType(String type) {
        if (type != null) {
            var validTypes = Set.of("STANDARD", "FTMO", "MFF", "TFT");
            if (!validTypes.contains(type.toUpperCase())) {
                throw TradingException.builder()
                        .errorCode(ErrorCodes.FUNDED_ACCOUNT_INVALID_TYPE)
                        .message("Invalid funded account type: " + type +
                                ". Valid types: STANDARD, FTMO, MFF, TFT")
                        .build();
            }
        }
    }

    /**
     * Validates that a period string is valid.
     *
     * @param period The period to validate
     * @throws TradingException If the period is invalid
     */
    private void validatePeriod(String period) {
        if (!StringUtils.hasText(period)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.STATS_INVALID_PERIOD)
                    .message("Period cannot be null or empty")
                    .build();
        }
        var validPeriods = Set.of("daily", "monthly", "ytd");
        if (!validPeriods.contains(period.toLowerCase())) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.STATS_INVALID_PERIOD)
                    .message("Invalid period: " + period + ". Valid periods: daily, monthly, ytd")
                    .build();
        }
    }

    /**
     * Validates a portfolio config update request.
     *
     * @param request The request to validate
     * @throws TradingException If any field is invalid
     */
    private void validateConfigUpdate(PortfolioConfigUpdateRequest request) {
        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Config update request cannot be null")
                    .build();
        }

        var updates = request.updates();
        if (updates == null || updates.isEmpty()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Updates cannot be null or empty")
                    .build();
        }

        // Validate each field
        for (var entry : updates.entrySet()) {
            var field = entry.getKey();
            var value = entry.getValue();

            switch (field) {
                case "trade_size_in_usd":
                    if (value instanceof Double d) validatePositiveDouble(d, field);
                    else if (value instanceof Number n) validatePositiveDouble(n.doubleValue(), field);
                    break;
                case "max_daily_loss_percent":
                case "max_daily_win_target_percent":
                case "max_monthly_loss_percent":
                case "max_monthly_win_target_percent":
                case "max_ytd_loss_percent":
                case "max_risk_per_trade_percent":
                case "max_drawdown_percent":
                    if (value instanceof Double d) validatePercentage(d, field);
                    else if (value instanceof Number n) validatePercentage(n.doubleValue(), field);
                    break;
                case "max_daily_trades":
                case "max_monthly_trades":
                case "max_consecutive_losses":
                case "max_daily_consecutive_losses":
                    if (value instanceof Integer i) validatePositiveInteger(i, field);
                    else if (value instanceof Number n) validatePositiveInteger(n.intValue(), field);
                    break;
                case "funded_account_type":
                    if (value instanceof String s) validateFundedAccountType(s);
                    break;
                case "trading_start_hour":
                case "trading_end_hour":
                    if (value instanceof Integer i) validateHour(i, field);
                    else if (value instanceof Number n) validateHour(n.intValue(), field);
                    break;
                case "funded_account_rules":
                    // No validation needed - any object is valid
                    break;
                default:
                    // Unknown field - let the Python service handle it
                    break;
            }
        }
    }

    /**
     * Validates a field update request.
     *
     * @param field The field name
     * @param request The field update request
     * @throws TradingException If any field is invalid
     */
    private void validateFieldUpdate(String field, PortfolioConfigFieldUpdateRequest request) {
        validateField(field);
        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Field update request cannot be null")
                    .build();
        }
        if (request.value() == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Value cannot be null")
                    .build();
        }

        // Validate the value based on the field
        var value = request.value();
        switch (field) {
            case "trade_size_in_usd":
                if (value instanceof Double d) validatePositiveDouble(d, field);
                else if (value instanceof Number n) validatePositiveDouble(n.doubleValue(), field);
                break;
            case "max_daily_loss_percent":
            case "max_daily_win_target_percent":
            case "max_monthly_loss_percent":
            case "max_monthly_win_target_percent":
            case "max_ytd_loss_percent":
            case "max_risk_per_trade_percent":
            case "max_drawdown_percent":
                if (value instanceof Double d) validatePercentage(d, field);
                else if (value instanceof Number n) validatePercentage(n.doubleValue(), field);
                break;
            case "max_daily_trades":
            case "max_monthly_trades":
            case "max_consecutive_losses":
            case "max_daily_consecutive_losses":
                if (value instanceof Integer i) validatePositiveInteger(i, field);
                else if (value instanceof Number n) validatePositiveInteger(n.intValue(), field);
                break;
            case "funded_account_type":
                if (value instanceof String s) validateFundedAccountType(s);
                break;
            case "trading_start_hour":
            case "trading_end_hour":
                if (value instanceof Integer i) validateHour(i, field);
                else if (value instanceof Number n) validateHour(n.intValue(), field);
                break;
            default:
                // Unknown field - let the Python service handle it
                break;
        }
    }

    /**
     * Checks if a response was successful and throws an exception if not.
     *
     * @param success The response to check
     * @param errorCode The error code to use if the response failed
     * @param errorMessage The error message to use if the response failed
     * @throws TradingException If the response indicates failure
     */
    private void checkResponse(boolean success, String error, ErrorCodes errorCode, String errorMessage) {
        if (!success) {
            throw TradingException.builder()
                    .errorCode(errorCode)
                    .message(errorMessage + ": " + (error != null ? error : "Unknown error"))
                    .build();
        }
    }

    // ============================================================
    // PORTFOLIO STATUS
    // ============================================================

    @Override
    public PortfolioStatusResponse getPortfolioStatus(boolean refresh, boolean summary) {
        log.info("[PortfolioRisk] Getting portfolio status - refresh: {}, summary: {}", refresh, summary);

        var response = portfolioRiskClient.getPortfolioStatus(refresh, summary);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PORTFOLIO_STATUS_FETCH_FAILED)
                    .message("Failed to get portfolio status: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public PortfolioStatusResponse getPortfolioSummary() {
        log.info("[PortfolioRisk] Getting portfolio summary");

        var response = portfolioRiskClient.getPortfolioSummary();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PORTFOLIO_STATUS_FETCH_FAILED)
                    .message("Failed to get portfolio summary: " + response.error())
                    .build();
        }

        return response;
    }

    // ============================================================
    // CONFIGURATION
    // ============================================================

    @Override
    public PortfolioConfigResponse getPortfolioConfig() {
        log.info("[PortfolioRisk] Getting portfolio config");

        var response = portfolioRiskClient.getPortfolioConfig();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PORTFOLIO_CONFIG_NOT_FOUND)
                    .message("Failed to get portfolio config: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public PortfolioConfigFieldResponse getPortfolioConfigField(String field) {
        log.info("[PortfolioRisk] Getting portfolio config field: {}", field);

        validateField(field);

        var response = portfolioRiskClient.getPortfolioConfigField(field);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PORTFOLIO_CONFIG_FIELD_NOT_FOUND)
                    .message("Failed to get field '" + field + "': " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public PortfolioConfigResponse updatePortfolioConfig(PortfolioConfigUpdateRequest request) {
        log.info("[PortfolioRisk] Updating portfolio config");

        validateConfigUpdate(request);

        var response = portfolioRiskClient.updatePortfolioConfig(request);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PORTFOLIO_CONFIG_UPDATE_FAILED)
                    .message("Failed to update portfolio config: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public PortfolioConfigFieldResponse updatePortfolioConfigField(
            String field,
            PortfolioConfigFieldUpdateRequest request) {
        log.info("[PortfolioRisk] Updating portfolio config field: {}", field);

        validateFieldUpdate(field, request);

        var response = portfolioRiskClient.updatePortfolioConfigField(field, request);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.PORTFOLIO_CONFIG_UPDATE_FAILED)
                    .message("Failed to update field '" + field + "': " + response.error())
                    .build();
        }

        return response;
    }

    // ============================================================
    // TRADING PERMISSION CHECKS
    // ============================================================

    @Override
    public CheckTradingAllowedResponse checkTradingAllowed(CheckTradingAllowedRequest request) {
        log.info("[PortfolioRisk] Checking trading allowed");

        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Check trading allowed request cannot be null")
                    .build();
        }

        var response = portfolioRiskClient.checkTradingAllowed(request);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.RISK_CHECK_FAILED)
                    .message("Failed to check trading allowed: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public MaxRiskForTradeResponse getMaxRiskForTrade() {
        log.info("[PortfolioRisk] Getting max risk for trade");

        var response = portfolioRiskClient.getMaxRiskForTrade();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.RISK_CHECK_FAILED)
                    .message("Failed to get max risk for trade: " + response.error())
                    .build();
        }

        return response;
    }

    // ============================================================
    // STATISTICS
    // ============================================================

    @Override
    public PortfolioStatsResponse getPortfolioStats(String period, String date) {
        log.info("[PortfolioRisk] Getting portfolio stats - period: {}, date: {}", period, date);

        validatePeriod(period);

        var response = portfolioRiskClient.getPortfolioStats(period, date);

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.STATS_CALCULATION_FAILED)
                    .message("Failed to get portfolio stats: " + response.error())
                    .build();
        }

        return response;
    }

    @Override
    public PortfolioStatsResponse getDailyStats(String date) {
        log.info("[PortfolioRisk] Getting daily stats - date: {}", date);
        return getPortfolioStats("daily", date);
    }

    @Override
    public PortfolioStatsResponse getMonthlyStats(String month) {
        log.info("[PortfolioRisk] Getting monthly stats - month: {}", month);
        return getPortfolioStats("monthly", month);
    }

    @Override
    public PortfolioStatsResponse getYtdStats(Integer year) {
        log.info("[PortfolioRisk] Getting YTD stats - year: {}", year);
        String date = year != null ? String.valueOf(year) : null;
        return getPortfolioStats("ytd", date);
    }

    // ============================================================
    // DRAWDOWN
    // ============================================================

    @Override
    public DrawdownResponse getDrawdownInfo() {
        log.info("[PortfolioRisk] Getting drawdown info");

        var response = portfolioRiskClient.getDrawdownInfo();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.DRAWDOWN_CALCULATION_FAILED)
                    .message("Failed to get drawdown info: " + response.error())
                    .build();
        }

        return response;
    }

    // ============================================================
    // FUNDED ACCOUNT COMPLIANCE
    // ============================================================

    @Override
    public FundedComplianceResponse getFundedCompliance() {
        log.info("[PortfolioRisk] Getting funded compliance");

        var response = portfolioRiskClient.getFundedCompliance();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FUNDED_ACCOUNT_COMPLIANCE_FAILED)
                    .message("Failed to get funded compliance: " + response.error())
                    .build();
        }

        return response;
    }

    // ============================================================
    // REFRESH
    // ============================================================

    @Override
    public RefreshResponse refreshPortfolioStats() {
        log.info("[PortfolioRisk] Refreshing portfolio stats");

        var response = portfolioRiskClient.refreshPortfolioStats();

        if (!response.success()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.REFRESH_STATS_FAILED)
                    .message("Failed to refresh portfolio stats: " + response.error())
                    .build();
        }

        return response;
    }

    // ============================================================
    // HEALTH
    // ============================================================

    @Override
    public HealthResponse healthCheck() {
        log.info("[PortfolioRisk] Health check");

        try {
            return portfolioRiskClient.healthCheck();
        } catch (Exception e) {
            log.warn("[PortfolioRisk] Health check failed: {}", e.getMessage());
            return HealthResponse.error(e.getMessage());
        }
    }
}