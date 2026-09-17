package com.trading.easytradify.auth.dto.recpatcha;

import lombok.AllArgsConstructor;

@AllArgsConstructor
public class RecaptchaRequestDto {

    String secret;
    String response;

}