package com.trading.easytradify.unit.execution;

import com.trading.easytradify.execution.client.PythonCopyTradeClient;
import com.trading.easytradify.execution.config.broker.BrokerConfig;
import com.trading.easytradify.execution.models.*;

import java.util.Map;

/**
 * Mock implementation of PythonCopyTradeClient for unit testing.
 * Provides configurable success/failure responses.
 */
public class PythonCopyTradeClientMock implements PythonCopyTradeClient {

    private boolean shouldSucceed = true;
    private String errorMessage = "Mock error";
    private boolean shouldThrowException = false;

    public PythonCopyTradeClientMock withSuccess() {
        this.shouldSucceed = true;
        this.shouldThrowException = false;
        return this;
    }

    public PythonCopyTradeClientMock withFailure(String errorMessage) {
        this.shouldSucceed = false;
        this.errorMessage = errorMessage;
        this.shouldThrowException = false;
        return this;
    }

    public PythonCopyTradeClientMock withException() {
        this.shouldThrowException = true;
        return this;
    }

    @Override
    public CopyTradeResponse executeCopyTrade(CopyTradeRequest request) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return CopyTradeTestDataFactory.successCopyTradeResponse();
        }
        return CopyTradeTestDataFactory.failureCopyTradeResponse(errorMessage);
    }

    @Override
    public WebhookResponse handleWebhookTrade(WebhookTradeRequest request) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return CopyTradeTestDataFactory.successWebhookResponse();
        }
        return CopyTradeTestDataFactory.failureWebhookResponse(errorMessage);
    }

    @Override
    public WebhookResponse handleWebhookTrailing(WebhookTrailingRequest request) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return CopyTradeTestDataFactory.successWebhookResponse();
        }
        return CopyTradeTestDataFactory.failureWebhookResponse(errorMessage);
    }

    @Override
    public WebhookResponse webhookTest(Object payload) {
        // ✅ FIXED: Check shouldSucceed for webhookTest too
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return CopyTradeTestDataFactory.successWebhookResponse();
        }
        return CopyTradeTestDataFactory.failureWebhookResponse(errorMessage);
    }

    @Override
    public Map<String, Object> getWebhookHealth() {
        return CopyTradeTestDataFactory.webhookHealthMap();
    }

    @Override
    public Map<String, Object> getWebhookDebug() {
        return CopyTradeTestDataFactory.webhookDebugMap();
    }

    @Override
    public Map<String, Object> getStatus() {
        return CopyTradeTestDataFactory.statusMap();
    }

    @Override
    public HealthResponse healthCheck(BrokerConfig broker) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return CopyTradeTestDataFactory.validHealthResponse();
        }
        return CopyTradeTestDataFactory.errorHealthResponse();
    }
}