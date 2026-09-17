package com.trading.easytradify.execution.models;

public record WebhookResponse(
        String status,
        String message
) {
    public static WebhookResponse success(String message) {
        return new WebhookResponse("success", message);
    }

    public static WebhookResponse error(String message) {
        return new WebhookResponse("error", message);
    }

    public static WebhookResponse ignored(String message) {
        return new WebhookResponse("ignored", message);
    }
}