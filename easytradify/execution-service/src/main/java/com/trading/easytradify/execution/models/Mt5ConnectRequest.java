package com.trading.easytradify.execution.models;

import jakarta.validation.constraints.NotBlank;

public record Mt5ConnectRequest(

        @NotBlank(message = "Login is required")
        String login,

        @NotBlank(message = "Password is required")
        String password,

        @NotBlank(message = "Server is required")
        String server,

        String path

) {}