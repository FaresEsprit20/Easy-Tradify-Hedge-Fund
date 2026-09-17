package com.trading.easytradify.portfolio.controllers;

import com.trading.easytradify.portfolio.models.*;
import com.trading.easytradify.portfolio.services.PortfolioRiskService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

/**
 * <h1>Portfolio Risk Controller</h1>
 * <p>
 * Concrete implementation of the {@link PortfolioRiskApi} interface.
 * This controller handles all REST endpoints for portfolio risk management.
 * </p>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Thin Controller:</b> All business logic is delegated to the service layer</li>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Validation:</b> All requests are validated via {@code @Valid}</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * <h2>Error Handling</h2>
 * <p>
 * This controller relies on the {@code GlobalExceptionHandler} for consistent
 * error responses. All exceptions propagate through the call stack without
 * being caught locally.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see PortfolioRiskApi
 * @see PortfolioRiskService
 */
@RestController
@RequiredArgsConstructor
@Slf4j
public class PortfolioRiskController implements PortfolioRiskApi {

    private final PortfolioRiskService portfolioRiskService;

    // ============================================================
    // PORTFOLIO STATUS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<PortfolioStatusResponse> getPortfolioStatus(boolean refresh, boolean summary) {
        log.info("[PortfolioRisk] Received get portfolio status request - refresh: {}, summary: {}", refresh, summary);
        var response = portfolioRiskService.getPortfolioStatus(refresh, summary);
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<PortfolioStatusResponse> getPortfolioSummary() {
        log.info("[PortfolioRisk] Received get portfolio summary request");
        var response = portfolioRiskService.getPortfolioSummary();
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // CONFIGURATION
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<PortfolioConfigResponse> getPortfolioConfig() {
        log.info("[PortfolioRisk] Received get portfolio config request");
        var response = portfolioRiskService.getPortfolioConfig();
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<PortfolioConfigFieldResponse> getPortfolioConfigField(String field) {
        log.info("[PortfolioRisk] Received get portfolio config field request: {}", field);
        var response = portfolioRiskService.getPortfolioConfigField(field);
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<PortfolioConfigResponse> updatePortfolioConfig(PortfolioConfigUpdateRequest request) {
        log.info("[PortfolioRisk] Received update portfolio config request");
        var response = portfolioRiskService.updatePortfolioConfig(request);
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<PortfolioConfigFieldResponse> updatePortfolioConfigField(
            String field,
            PortfolioConfigFieldUpdateRequest request) {
        log.info("[PortfolioRisk] Received update portfolio config field request: {}", field);
        var response = portfolioRiskService.updatePortfolioConfigField(field, request);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // TRADING PERMISSION CHECKS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<CheckTradingAllowedResponse> checkTradingAllowed(CheckTradingAllowedRequest request) {
        log.info("[PortfolioRisk] Received check trading allowed request");
        var response = portfolioRiskService.checkTradingAllowed(request);
        return ResponseEntity.ok(response);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<MaxRiskForTradeResponse> getMaxRiskForTrade() {
        log.info("[PortfolioRisk] Received get max risk for trade request");
        var response = portfolioRiskService.getMaxRiskForTrade();
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // STATISTICS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<PortfolioStatsResponse> getPortfolioStats(String period, String date) {
        log.info("[PortfolioRisk] Received get portfolio stats request - period: {}, date: {}", period, date);
        var response = portfolioRiskService.getPortfolioStats(period, date);
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // DRAWDOWN
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<DrawdownResponse> getDrawdownInfo() {
        log.info("[PortfolioRisk] Received get drawdown info request");
        var response = portfolioRiskService.getDrawdownInfo();
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // FUNDED ACCOUNT COMPLIANCE
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<FundedComplianceResponse> getFundedCompliance() {
        log.info("[PortfolioRisk] Received get funded compliance request");
        var response = portfolioRiskService.getFundedCompliance();
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // REFRESH
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<RefreshResponse> refreshPortfolioStats() {
        log.info("[PortfolioRisk] Received refresh portfolio stats request");
        var response = portfolioRiskService.refreshPortfolioStats();
        return ResponseEntity.ok(response);
    }

    // ============================================================
    // HEALTH
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public ResponseEntity<HealthResponse> healthCheck() {
        log.debug("[PortfolioRisk] Received health check request");
        var response = portfolioRiskService.healthCheck();
        return ResponseEntity.ok(response);
    }
}