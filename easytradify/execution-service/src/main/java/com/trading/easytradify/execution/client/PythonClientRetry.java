package com.trading.easytradify.execution.client;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.util.retry.Retry;

import java.time.Duration;

@Component
@Slf4j
public class PythonClientRetry {

    private final int maxRetries;
    private final long retryDelay;

    public PythonClientRetry(
            @Value("${python.max-retries:3}") int maxRetries,
            @Value("${python.retry-delay:1000}") long retryDelay) {
        this.maxRetries = maxRetries;
        this.retryDelay = retryDelay;
    }

    public Retry getRetrySpec() {
        return Retry.backoff(maxRetries, Duration.ofMillis(retryDelay))
                .filter(this::isRetryableError)
                .doBeforeRetry(retrySignal -> {
                    log.warn("Retrying Python call (attempt {}/{})...",
                            retrySignal.totalRetries() + 1, maxRetries);
                })
                .onRetryExhaustedThrow((retryBackoffSpec, retrySignal) -> {
                    log.error("All retries exhausted for Python call");
                    Throwable failure = retrySignal.failure();
                    if (failure instanceof WebClientResponseException wcre) {
                        throw TradingException.builder()
                                .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                                .message("Python service unavailable after " + maxRetries + " retries: " +
                                        wcre.getStatusCode() + " - " + wcre.getResponseBodyAsString())
                                .mt5RetCode(wcre.getStatusCode().value())
                                .build();
                    }
                    throw TradingException.builder()
                            .errorCode(ErrorCodes.PYTHON_SERVICE_UNREACHABLE)
                            .message("Python service unavailable after " + maxRetries + " retries")
                            .build();
                });
    }

    private boolean isRetryableError(Throwable throwable) {
        if (throwable instanceof WebClientResponseException wcre) {
            int statusCode = wcre.getStatusCode().value();
            return statusCode >= 500 || statusCode == 429 || statusCode == 408 ||
                    statusCode == 503 || statusCode == 504;
        }
        return true;
    }
}