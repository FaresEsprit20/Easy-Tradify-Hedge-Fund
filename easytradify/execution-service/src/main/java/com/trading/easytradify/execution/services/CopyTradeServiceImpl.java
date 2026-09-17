package com.trading.easytradify.execution.services;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.execution.client.PythonCopyTradeClient;
import com.trading.easytradify.execution.models.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.Map;

/**
 * <h1>Copy Trade Service Implementation</h1>
 * <p>
 * Default implementation of {@link CopyTradeService}.
 * Delegates all operations to the {@link PythonCopyTradeClient}.
 * </p>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Thin Service:</b> All business logic is delegated to the client</li>
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
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see CopyTradeService
 * @see PythonCopyTradeClient
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class CopyTradeServiceImpl implements CopyTradeService {

    private final PythonCopyTradeClient copyTradeClient;

    // ============================================================
    // VALIDATION HELPERS
    // ============================================================

    /**
     * Validates that a symbol is not {@code null} or empty.
     *
     * @param symbol The symbol to validate
     * @throws TradingException If the symbol is {@code null} or empty
     */
    private void validateSymbol(String symbol) {
        if (!StringUtils.hasText(symbol)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.TRADE_INVALID_SYMBOL)
                    .message("Symbol cannot be null or empty")
                    .build();
        }
    }

    /**
     * Validates that a numeric value is positive.
     *
     * @param value     The value to validate
     * @param fieldName The name of the field (used in error message)
     * @throws TradingException If the value is not positive
     */
    private void validatePositive(Double value, String fieldName) {
        if (value == null || value <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message(fieldName + " must be positive: " + value)
                    .build();
        }
    }

    /**
     * Validates that a ticket number is positive.
     *
     * @param ticket The ticket number to validate
     * @throws TradingException If the ticket number is not positive
     */
    private void validateTicket(Integer ticket) {
        if (ticket == null || ticket <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.POSITION_NOT_FOUND)
                    .message("Invalid ticket number: " + ticket)
                    .build();
        }
    }

    /**
     * Validates that an analysis result contains required fields.
     *
     * @param analysisResult The analysis result to validate
     * @throws TradingException If the analysis result is invalid
     */
    @SuppressWarnings("unchecked")
    private void validateAnalysisResult(Map<String, Object> analysisResult) {
        if (analysisResult == null || analysisResult.isEmpty()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Analysis result cannot be null or empty")
                    .build();
        }

        var finalVerdict = (Map<String, Object>) analysisResult.get("final_verdict");
        if (finalVerdict == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("final_verdict is required in analysis result")
                    .build();
        }

        var stopLoss = (Double) finalVerdict.get("stop_loss");
        if (stopLoss == null || stopLoss <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("stop_loss is required in final_verdict")
                    .build();
        }

        var takeProfit = (Double) finalVerdict.get("take_profit_1");
        if (takeProfit == null || takeProfit <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("take_profit_1 is required in final_verdict")
                    .build();
        }

        var config = (Map<String, Object>) analysisResult.get("config");
        if (config == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("config is required in analysis result")
                    .build();
        }

        var orderType = (String) config.get("executed_direction");
        if (!StringUtils.hasText(orderType)) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("executed_direction is required in config")
                    .build();
        }
    }

    /**
     * Validates a webhook trade request.
     *
     * @param request The webhook trade request to validate
     * @throws TradingException If the request is invalid
     */
    private void validateWebhookTrade(WebhookTradeRequest request) {
        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Webhook trade request cannot be null")
                    .build();
        }

        validateSymbol(request.symbol());
        validateTicket(request.ticket());

        if (request.priceOpen() != null && request.priceOpen() <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message("price_open must be positive: " + request.priceOpen())
                    .build();
        }

        if (request.priceClose() != null && request.priceClose() <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message("price_close must be positive: " + request.priceClose())
                    .build();
        }
    }

    /**
     * Validates a webhook trailing request.
     *
     * @param request The webhook trailing request to validate
     * @throws TradingException If the request is invalid
     */
    private void validateWebhookTrailing(WebhookTrailingRequest request) {
        if (request == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.MISSING_REQUIRED_FIELD)
                    .message("Webhook trailing request cannot be null")
                    .build();
        }

        validateTicket(request.ticket());

        if (request.slPrice() != null && request.slPrice() <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message("sl_price must be positive: " + request.slPrice())
                    .build();
        }

        if (request.stepPips() != null && request.stepPips() <= 0) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.FIELD_OUT_OF_RANGE)
                    .message("step_pips must be positive: " + request.stepPips())
                    .build();
        }
    }

    // ============================================================
    // SERVICE METHODS
    // ============================================================

    /**
     * {@inheritDoc}
     */
    @Override
    public CopyTradeResponse executeCopyTrade(CopyTradeRequest request) {
        log.info("[CopyTrade] Executing copy trade for: {}", request.symbol());

        // 1. Validate input
        validateSymbol(request.symbol());
        validateAnalysisResult(request.analysisResult());

        // 2. Delegate to client
        var response = copyTradeClient.executeCopyTrade(request);

        // 3. Check response success
        if (!response.success()) {
            log.error("[CopyTrade] Copy trade failed: {}", response.error());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.TRADE_EXECUTION_FAILED)
                    .message("Copy trade execution failed: " + response.error())
                    .symbol(request.symbol())
                    .build();
        }

        log.info("[CopyTrade] Copy trade executed successfully: {} (Ticket: {})",
                request.symbol(), response.ticket());

        return response;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public WebhookResponse handleWebhookTrade(WebhookTradeRequest request) {
        log.info("[CopyTrade] Handling webhook trade: {} (Ticket: {})", request.symbol(), request.ticket());

        // 1. Validate input
        validateWebhookTrade(request);

        // 2. Delegate to client
        var response = copyTradeClient.handleWebhookTrade(request);

        // 3. Check response success
        if (!"success".equals(response.status())) {
            log.error("[CopyTrade] Webhook trade failed: {}", response.message());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.WEBHOOK_PROCESSING_FAILED)
                    .message("Webhook trade processing failed: " + response.message())
                    .ticket(request.ticket())
                    .build();
        }

        log.info("[CopyTrade] Webhook trade processed successfully: Ticket {}", request.ticket());

        return response;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public WebhookResponse handleWebhookTrailing(WebhookTrailingRequest request) {
        log.info("[CopyTrade] Handling webhook trailing: Ticket {}", request.ticket());

        // 1. Validate input
        validateWebhookTrailing(request);

        // 2. Delegate to client
        var response = copyTradeClient.handleWebhookTrailing(request);

        // 3. Check response success
        if (!"success".equals(response.status())) {
            log.error("[CopyTrade] Webhook trailing failed: {}", response.message());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.WEBHOOK_PROCESSING_FAILED)
                    .message("Webhook trailing processing failed: " + response.message())
                    .ticket(request.ticket())
                    .build();
        }

        log.info("[CopyTrade] Webhook trailing processed successfully: Ticket {}", request.ticket());

        return response;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public WebhookResponse webhookTest(Object payload) {
        log.info("[CopyTrade] Webhook test");

        // 1. Delegate to client
        var response = copyTradeClient.webhookTest(payload);

        // 2. Check response success
        if (!"success".equals(response.status())) {
            log.error("[CopyTrade] Webhook test failed: {}", response.message());
            throw TradingException.builder()
                    .errorCode(ErrorCodes.WEBHOOK_PROCESSING_FAILED)
                    .message("Webhook test failed: " + response.message())
                    .build();
        }

        log.info("[CopyTrade] Webhook test successful");

        return response;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public Map<String, Object> getWebhookHealth() {
        log.debug("[CopyTrade] Getting webhook health");

        // Delegate to client
        var response = copyTradeClient.getWebhookHealth();

        // Add timestamp if not present
        if (!response.containsKey("timestamp")) {
            response.put("timestamp", java.time.Instant.now().toString());
        }

        return response;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public Map<String, Object> getWebhookDebug() {
        log.debug("[CopyTrade] Getting webhook debug info");

        // Delegate to client
        var response = copyTradeClient.getWebhookDebug();

        // Add timestamp if not present
        if (!response.containsKey("timestamp")) {
            response.put("timestamp", java.time.Instant.now().toString());
        }

        return response;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public Map<String, Object> getStatus() {
        log.debug("[CopyTrade] Getting executor status");

        // Delegate to client
        var response = copyTradeClient.getStatus();

        // Add timestamp if not present
        if (!response.containsKey("timestamp")) {
            response.put("timestamp", java.time.Instant.now().toString());
        }

        return response;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public HealthResponse healthCheck() {
        log.debug("[CopyTrade] Health check");

        // Delegate to client
        var response = copyTradeClient.healthCheck(null);

        log.info("[CopyTrade] Health check: {}", response.status());

        return response;
    }
}