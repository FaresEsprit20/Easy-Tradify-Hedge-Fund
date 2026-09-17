package com.trading.easytradify.portfolio.controllers;

import com.trading.easytradify.portfolio.models.*;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * <h1>Portfolio Risk Management API</h1>
 * <p>
 * REST API for managing portfolio risk, tracking performance,
 * and enforcing trading limits based on risk configuration.
 * </p>
 *
 * <h2>Base Path</h2>
 * <p>
 * All endpoints are prefixed with {@code /api/v1/portfolio}
 * </p>
 *
 * <h2>Authentication</h2>
 * <p>
 * All endpoints require a valid API key in the {@code X-API-Key} header.
 * </p>
 *
 * <h2>Risk Management Features</h2>
 * <ul>
 *   <li><b>Portfolio Status:</b> Real-time P&amp;L, drawdown, and risk metrics</li>
 *   <li><b>Risk Configuration:</b> Get and update portfolio risk limits</li>
 *   <li><b>Trading Permissions:</b> Check if trading is allowed based on risk limits</li>
 *   <li><b>Statistics:</b> Daily/Monthly/YTD performance tracking</li>
 *   <li><b>Compliance:</b> Funded account rule validation (FTMO, MFF, TFT)</li>
 * </ul>
 *
 * <h2>Error Handling</h2>
 * <p>
 * All errors are returned in a standardized format via
 * {@link com.trading.easytradify.common.exception.CustomErrorMsg}.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 */
@Tag(name = "Portfolio Risk", description = "Portfolio risk management and performance tracking")
@RequestMapping("/api/v1/portfolio")
public interface PortfolioRiskApi {

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
     * @param refresh Whether to force refresh from Firebase (default: false)
     * @param summary Whether to return only a lightweight summary (default: false)
     * @return {@link PortfolioStatusResponse} containing the portfolio status
     */
    @Operation(
            summary = "Get portfolio status",
            description = """
                    Retrieves the current portfolio status including account information,
                    daily/monthly/YTD performance, and risk metrics.
                    
                    **Status Information Includes:**
                    - Account: Balance, equity, leverage, currency
                    - Daily: Profit/Loss in USD and %, trades, win rate, drawdown
                    - Monthly: Profit/Loss in USD and %, trades, win rate, drawdown
                    - YTD: Profit/Loss in USD and %, trades, win rate, drawdown
                    - Risk: Current risk level, remaining loss limits, consecutive losses
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Portfolio status retrieved successfully",
                    content = @Content(schema = @Schema(implementation = PortfolioStatusResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/status")
    ResponseEntity<PortfolioStatusResponse> getPortfolioStatus(
            @Parameter(description = "Force refresh from Firebase (default: false)")
            @RequestParam(defaultValue = "false") boolean refresh,

            @Parameter(description = "Return only a lightweight summary (default: false)")
            @RequestParam(defaultValue = "false") boolean summary
    );

    /**
     * <h3>Get Portfolio Summary</h3>
     * <p>
     * Retrieves a lightweight summary of the portfolio status.
     * </p>
     *
     * @return {@link PortfolioStatusResponse} containing the portfolio summary
     */
    @Operation(
            summary = "Get portfolio summary",
            description = "Retrieves a lightweight summary of the portfolio status."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Portfolio summary retrieved successfully",
                    content = @Content(schema = @Schema(implementation = PortfolioStatusResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/summary")
    ResponseEntity<PortfolioStatusResponse> getPortfolioSummary();

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
     */
    @Operation(
            summary = "Get portfolio configuration",
            description = "Retrieves the current portfolio risk configuration."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Configuration retrieved successfully",
                    content = @Content(schema = @Schema(implementation = PortfolioConfigResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/config")
    ResponseEntity<PortfolioConfigResponse> getPortfolioConfig();

    /**
     * <h3>Get Configuration Field</h3>
     * <p>
     * Retrieves a specific configuration field value.
     * </p>
     *
     * @param field The configuration field name (e.g., "max_daily_loss_percent")
     * @return {@link PortfolioConfigFieldResponse} containing the field value
     */
    @Operation(
            summary = "Get configuration field",
            description = "Retrieves a specific configuration field value."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Field retrieved successfully",
                    content = @Content(schema = @Schema(implementation = PortfolioConfigFieldResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid field name"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Field not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/config/{field}")
    ResponseEntity<PortfolioConfigFieldResponse> getPortfolioConfigField(
            @Parameter(description = "Configuration field name", required = true)
            @PathVariable String field
    );

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
     * @return {@link PortfolioConfigResponse} containing the updated configuration
     */
    @Operation(
            summary = "Update portfolio configuration",
            description = """
                    Updates multiple portfolio configuration fields.
                    
                    **Validation Rules:**
                    - All percentage fields must be between 0 and 100
                    - Trade size must be positive
                    - Max trades must be positive integers
                    - Consecutive losses must be positive integers
                    - Trading hours must be between 0 and 23
                    - Funded account type must be valid (STANDARD, FTMO, MFF, TFT)
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Configuration updated successfully",
                    content = @Content(schema = @Schema(implementation = PortfolioConfigResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid request parameters",
                    content = @Content(schema = @Schema(implementation = PortfolioConfigResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PutMapping("/config")
    ResponseEntity<PortfolioConfigResponse> updatePortfolioConfig(
            @Parameter(description = "Configuration update request", required = true)
            @Valid @RequestBody PortfolioConfigUpdateRequest request
    );

    /**
     * <h3>Update Configuration Field</h3>
     * <p>
     * Updates a specific configuration field.
     * </p>
     *
     * @param field   The configuration field name
     * @param request The field update request containing the new value
     * @return {@link PortfolioConfigFieldResponse} containing the updated field value
     */
    @Operation(
            summary = "Update configuration field",
            description = "Updates a specific configuration field."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Field updated successfully",
                    content = @Content(schema = @Schema(implementation = PortfolioConfigFieldResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid request parameters",
                    content = @Content(schema = @Schema(implementation = PortfolioConfigFieldResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "Field not found"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PutMapping("/config/{field}")
    ResponseEntity<PortfolioConfigFieldResponse> updatePortfolioConfigField(
            @Parameter(description = "Configuration field name", required = true)
            @PathVariable String field,

            @Parameter(description = "Field update request", required = true)
            @Valid @RequestBody PortfolioConfigFieldUpdateRequest request
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
     * @return {@link CheckTradingAllowedResponse} containing the check result
     */
    @Operation(
            summary = "Check if trading is allowed",
            description = """
                    Checks if trading is allowed based on current portfolio risk limits.
                    
                    **Risk Checks Performed:**
                    - Account balance is positive
                    - Trading hours are within configured limits
                    - Daily loss limit not exceeded
                    - Daily win target not reached
                    - Daily trade count not exceeded
                    - Monthly loss limit not exceeded
                    - Monthly win target not reached
                    - Monthly trade count not exceeded
                    - YTD loss limit not exceeded
                    - Drawdown limit not exceeded
                    - Consecutive loss limits not exceeded
                    - Per-trade risk limit not exceeded (if provided)
                    
                    **Risk Levels:**
                    - SAFE: No violations, trading allowed
                    - CAUTION: Minor violations approaching, trading allowed
                    - WARNING: Multiple violations approaching, trading allowed
                    - CRITICAL: Severe violations, trading blocked
                    - MAX_EXCEEDED: Hard limit exceeded, trading blocked
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Check completed successfully",
                    content = @Content(schema = @Schema(implementation = CheckTradingAllowedResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid request parameters",
                    content = @Content(schema = @Schema(implementation = CheckTradingAllowedResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/check-trading-allowed")
    ResponseEntity<CheckTradingAllowedResponse> checkTradingAllowed(
            @Parameter(description = "Check trading allowed request", required = true)
            @Valid @RequestBody CheckTradingAllowedRequest request
    );

    /**
     * <h3>Get Maximum Risk Per Trade</h3>
     * <p>
     * Retrieves the maximum risk percentage allowed for a trade.
     * </p>
     *
     * @return {@link MaxRiskForTradeResponse} containing the maximum risk percentage
     */
    @Operation(
            summary = "Get maximum risk per trade",
            description = "Retrieves the maximum risk percentage allowed for a trade."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Max risk retrieved successfully",
                    content = @Content(schema = @Schema(implementation = MaxRiskForTradeResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/max-risk-per-trade")
    ResponseEntity<MaxRiskForTradeResponse> getMaxRiskForTrade();

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
     * @param period The statistics period: daily, monthly, or ytd
     * @param date   The date for the statistics period (optional)
     * @return {@link PortfolioStatsResponse} containing the statistics
     */
    @Operation(
            summary = "Get portfolio statistics",
            description = """
                    Retrieves portfolio statistics for a specified period.
                    
                    **Periods:**
                    - daily: Statistics for a specific day (date: YYYY-MM-DD)
                    - monthly: Statistics for a specific month (date: YYYY-MM)
                    - ytd: Statistics for a specific year (date: YYYY)
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Statistics retrieved successfully",
                    content = @Content(schema = @Schema(implementation = PortfolioStatsResponse.class))
            ),
            @ApiResponse(
                    responseCode = "400",
                    description = "Invalid period or date format"
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "404",
                    description = "No data found for the specified period"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/stats")
    ResponseEntity<PortfolioStatsResponse> getPortfolioStats(
            @Parameter(description = "Statistics period: daily, monthly, or ytd", required = true)
            @RequestParam String period,

            @Parameter(description = "Date for the statistics period (optional)")
            @RequestParam(required = false) String date
    );

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
     */
    @Operation(
            summary = "Get drawdown information",
            description = """
                    Retrieves current and maximum drawdown information.
                    
                    **Drawdown Metrics:**
                    - current_percent: Current drawdown from peak as percentage
                    - max_percent: Maximum historical drawdown as percentage
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Drawdown information retrieved successfully",
                    content = @Content(schema = @Schema(implementation = DrawdownResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/drawdown")
    ResponseEntity<DrawdownResponse> getDrawdownInfo();

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
     * @return {@link FundedComplianceResponse} containing compliance information
     */
    @Operation(
            summary = "Get funded account compliance",
            description = """
                    Retrieves funded account compliance information.
                    
                    **Supported Account Types:**
                    - STANDARD: No specific rules, always compliant
                    - FTMO: Max daily loss 5%, max monthly loss 10%, max drawdown 10%
                    - MFF: Max daily loss 5%, max monthly loss 12%, max drawdown 12%
                    - TFT: Max daily loss 5%, max monthly loss 8%, max drawdown 8%
                    """
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Compliance information retrieved successfully",
                    content = @Content(schema = @Schema(implementation = FundedComplianceResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @GetMapping("/funded-compliance")
    ResponseEntity<FundedComplianceResponse> getFundedCompliance();

    // ============================================================
    // REFRESH
    // ============================================================

    /**
     * <h3>Refresh Portfolio Statistics</h3>
     * <p>
     * Forces a refresh of statistics from Firebase.
     * </p>
     *
     * @return {@link RefreshResponse} indicating the refresh result
     */
    @Operation(
            summary = "Refresh portfolio statistics",
            description = "Forces a refresh of statistics from Firebase."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Statistics refreshed successfully",
                    content = @Content(schema = @Schema(implementation = RefreshResponse.class))
            ),
            @ApiResponse(
                    responseCode = "401",
                    description = "Missing or invalid API key"
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Internal server error"
            )
    })
    @PostMapping("/refresh")
    ResponseEntity<RefreshResponse> refreshPortfolioStats();

    // ============================================================
    // HEALTH
    // ============================================================

    /**
     * <h3>Health Check</h3>
     * <p>
     * Performs a health check on the portfolio risk service.
     * </p>
     *
     * @return {@link HealthResponse} containing the service health status
     */
    @Operation(
            summary = "Health check",
            description = "Performs a health check on the portfolio risk service."
    )
    @ApiResponses(value = {
            @ApiResponse(
                    responseCode = "200",
                    description = "Service is healthy",
                    content = @Content(schema = @Schema(implementation = HealthResponse.class))
            ),
            @ApiResponse(
                    responseCode = "500",
                    description = "Service is unhealthy",
                    content = @Content(schema = @Schema(implementation = HealthResponse.class))
            )
    })
    @GetMapping("/health")
    ResponseEntity<HealthResponse> healthCheck();
}