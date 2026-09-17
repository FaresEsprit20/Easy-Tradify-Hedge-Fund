package com.trading.easytradify.monitor.config.monitor;

import lombok.Getter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;

/**
 * <h1>Monitor Configuration</h1>
 * <p>
 * Configuration properties for the monitor service.
 * </p>
 *
 * <h2>Configuration Properties</h2>
 * <table>
 *   <caption>Monitor Configuration Properties</caption>
 *   <tr><th>Property</th><th>Description</th><th>Default</th></tr>
 *   <tr><td>{@code monitor.python.url}</td><td>Python service URL</td><td>http://localhost:5001</td></tr>
 *   <tr><td>{@code monitor.connect-timeout}</td><td>Connection timeout (ms)</td><td>30000</td></tr>
 *   <tr><td>{@code monitor.read-timeout}</td><td>Read timeout (ms)</td><td>30000</td></tr>
 *   <tr><td>{@code monitor.write-timeout}</td><td>Write timeout (ms)</td><td>30000</td></tr>
 *   <tr><td>{@code monitor.max-retries}</td><td>Maximum retry attempts</td><td>3</td></tr>
 *   <tr><td>{@code monitor.retry-delay}</td><td>Initial retry delay (ms)</td><td>1000</td></tr>
 *   <tr><td>{@code monitor.scan-interval}</td><td>Scan interval (ms)</td><td>60000</td></tr>
 *   <tr><td>{@code monitor.max-top-symbols}</td><td>Maximum top symbols</td><td>10</td></tr>
 *   <tr><td>{@code monitor.min-confidence}</td><td>Minimum confidence threshold</td><td>60</td></tr>
 * </table>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
@Configuration
@Getter
public class MonitorConfig {

    @Value("${monitor.python.url:http://localhost:5001}")
    private String pythonServiceUrl;

    @Value("${monitor.connect-timeout:30000}")
    private int connectTimeout;

    @Value("${monitor.read-timeout:30000}")
    private int readTimeout;

    @Value("${monitor.write-timeout:30000}")
    private int writeTimeout;

    @Value("${monitor.max-retries:3}")
    private int maxRetries;

    @Value("${monitor.retry-delay:1000}")
    private int retryDelay;

    @Value("${monitor.scan-interval:60000}")
    private long scanInterval;

    @Value("${monitor.max-top-symbols:10}")
    private int maxTopSymbols;

    @Value("${monitor.min-confidence:60}")
    private int minConfidence;

    /**
     * Validates the configuration values.
     *
     * @throws IllegalArgumentException if any configuration value is invalid
     */
    public void validate() {
        if (connectTimeout <= 0) {
            throw new IllegalArgumentException("connect-timeout must be positive: " + connectTimeout);
        }
        if (readTimeout <= 0) {
            throw new IllegalArgumentException("read-timeout must be positive: " + readTimeout);
        }
        if (writeTimeout <= 0) {
            throw new IllegalArgumentException("write-timeout must be positive: " + writeTimeout);
        }
        if (maxRetries <= 0) {
            throw new IllegalArgumentException("max-retries must be positive: " + maxRetries);
        }
        if (retryDelay <= 0) {
            throw new IllegalArgumentException("retry-delay must be positive: " + retryDelay);
        }
        if (scanInterval <= 0) {
            throw new IllegalArgumentException("scan-interval must be positive: " + scanInterval);
        }
        if (maxTopSymbols <= 0) {
            throw new IllegalArgumentException("max-top-symbols must be positive: " + maxTopSymbols);
        }
        if (minConfidence < 0 || minConfidence > 100) {
            throw new IllegalArgumentException("min-confidence must be between 0 and 100: " + minConfidence);
        }
    }

}