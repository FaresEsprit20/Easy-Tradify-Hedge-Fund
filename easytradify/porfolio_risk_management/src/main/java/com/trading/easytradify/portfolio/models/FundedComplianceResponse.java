package com.trading.easytradify.portfolio.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;

/**
 * <h1>Funded Compliance Response</h1>
 * <p>
 * Response containing funded account compliance information.
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
 * @param success        Whether the request was successful
 * @param accountType    The funded account type
 * @param compliant      Whether the portfolio is compliant with the account rules
 * @param violations     List of compliance violations (empty if compliant)
 * @param error          Error message (failure case)
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record FundedComplianceResponse(
        boolean success,
        String accountType,
        Boolean compliant,
        List<String> violations,
        String error
) {
    public static FundedComplianceResponse success(String accountType, Boolean compliant, List<String> violations) {
        return new FundedComplianceResponse(true, accountType, compliant, violations, null);
    }

    public static FundedComplianceResponse error(String error) {
        return new FundedComplianceResponse(false, null, null, null, error);
    }
}