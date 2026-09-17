package com.trading.easytradify.execution.client;

import lombok.Getter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;

@Configuration
@Getter
public class PythonClientConfig {

    @Value("${python.host:localhost}")
    private String host;

    @Value("${python.connect-timeout:30000}")
    private int connectTimeout;

    @Value("${python.read-timeout:30000}")
    private int readTimeout;

    @Value("${python.write-timeout:30000}")
    private int writeTimeout;

    @Value("${python.max-retries:3}")
    private int maxRetries;

    @Value("${python.retry-delay:1000}")
    private int retryDelay;
}