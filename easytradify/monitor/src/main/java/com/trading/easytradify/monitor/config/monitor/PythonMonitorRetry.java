package com.trading.easytradify.monitor.config.monitor;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.util.retry.Retry;

import java.time.Duration;

/**
 * <h1>Python Monitor Retry</h1>
 * <p>
 * Retry logic for the Python monitor client. Provides exponential backoff
 * retry with configurable max attempts and delay.
 * </p>
 *
 * <h2>Retryable Errors</h2>
 * <ul>
 *   <li>5xx Server Errors (500, 502, 503, 504)</li>
 *   <li>Rate Limiting (429)</li>
 *   <li>Timeout (408)</li>
 *   <li>Network Errors</li>
 * </ul>
 *
 * <h2>Configuration</h2>
 * <ul>
 *   <li><b>max-retries:</b> Maximum number of retry attempts (default: 3)</li>
 *   <li><b>retry-delay:</b> Initial delay in milliseconds (default: 1000)</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
@Component
@Slf4j
public class PythonMonitorRetry {

    private final int maxRetries;
    private final long retryDelay;

    public PythonMonitorRetry(
            @Value("${monitor.max-retries:3}") int maxRetries,
            @Value("${monitor.retry-delay:1000}") long retryDelay) {
        this.maxRetries = maxRetries;
        this.retryDelay = retryDelay;
    }

    /**
     * <h3>Get Retry Specification</h3>
     * <p>
     * Returns a Reactor Retry specification with exponential backoff.
     * </p>
     *
     * @return The Retry specification
     */
    public Retry getRetrySpec() {
        return Retry.backoff(maxRetries, Duration.ofMillis(retryDelay))
                .filter(this::isRetryableError)
                .doBeforeRetry(retrySignal -> {
                    log.warn("[Monitor] Retrying call (attempt {}/{})...",
                            retrySignal.totalRetries() + 1, maxRetries);
                })
                .onRetryExhaustedThrow((retryBackoffSpec, retrySignal) -> {
                    log.error("[Monitor] All retries exhausted");
                    Throwable failure = retrySignal.failure();
                    if (failure instanceof WebClientResponseException wcre) {
                        throw TradingException.builder()
                                .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                                .message("Monitor service unavailable after " + maxRetries + " retries: " +
                                        wcre.getStatusCode() + " - " + wcre.getResponseBodyAsString())
                                .mt5RetCode(wcre.getStatusCode().value())
                                .build();
                    }
                    throw TradingException.builder()
                            .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                            .message("Monitor service unavailable after " + maxRetries + " retries")
                            .build();
                });
    }

    /**
     * <h3>Check if Error is Retryable</h3>
     * <p>
     * Determines if an error should trigger a retry.
     * </p>
     *
     * @param throwable The error to check
     * @return {@code true} if the error is retryable, {@code false} otherwise
     */
    private boolean isRetryableError(Throwable throwable) {
        if (throwable instanceof WebClientResponseException wcre) {
            int statusCode = wcre.getStatusCode().value();
            // Retry on 5xx errors, rate limiting, and timeouts
            return statusCode >= 500 ||
                    statusCode == 429 ||
                    statusCode == 408 ||
                    statusCode == 503 ||
                    statusCode == 504;
        }
        // Retry on network errors
        return true;
    }
}