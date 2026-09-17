package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;

import java.util.Map;

/**
 * <h1>Portfolio Config Update Request</h1>
 * <p>
 * Request to update multiple portfolio configuration fields.
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
 * @param updates Map of field names to new values
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PortfolioConfigUpdateRequest(
        Map<String, Object> updates
) {
    public PortfolioConfigUpdateRequest {
        if (updates == null || updates.isEmpty()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Updates cannot be null or empty")
                    .build();
        }
    }
}