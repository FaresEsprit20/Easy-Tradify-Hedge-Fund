package com.trading.easytradify.monitor.models;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Response for webhook processing.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WebhookResponse(
        String status,
        String message,
        String error
) {
    public static WebhookResponse success(String message) {
        return new WebhookResponse("success", message, null);
    }

    public static WebhookResponse error(String message) {
        return new WebhookResponse("error", null, message);
    }

    public static WebhookResponse ignored(String message) {
        return new WebhookResponse("ignored", message, null);
    }
}