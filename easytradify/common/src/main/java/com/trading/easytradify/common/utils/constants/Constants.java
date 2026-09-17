package com.trading.easytradify.common.utils.constants;

import java.util.LinkedHashMap;
import java.util.Map;

public interface Constants {

    // ========================
    // ENDPOINT ROOTS
    // ========================
    // Every auth-module controller builds its @RequestMapping from these rather
    // than writing a literal path, so the whole surface moves together if the
    // root ever changes. That is not hypothetical: these were ported from a
    // codebase rooted at "/tunindex/market/tool/v1", and the two places that
    // had hardcoded the literal instead of using the constant were exactly the
    // two that had to be found by hand.
    String APP_ROOT = "easytradify/trading/tool/v1";
    String USER_ENDPOINT = APP_ROOT + "/users";
    String AUTHENTICATION_ENDPOINT = APP_ROOT + "/auth";
    String ACCOUNTS_ENDPOINT = APP_ROOT + "/accounts/management";

    String ALLOWED_ORIGINS = "http://localhost:4200";

    // ========================
    // ENVIRONMENT
    // ========================
    // Gates the `Secure` flag on the auth cookies. False here means the cookies
    // are sent over plain http, which is required for local development and
    // WRONG anywhere else: a Secure-less session cookie is readable by any
    // network observer. This must be true before this module is deployed, and
    // it is a constant rather than a property so that flipping it is a
    // deliberate, reviewable code change instead of an env var someone forgets.
    Boolean PRODUCTION_ENVIRONMENT = false;


    // ========================
    // WEB CLIENT CONSTANTS
    // ========================
    String USER_AGENT_HEADER = "User-Agent";
    String ACCEPT_HEADER = "Accept";
    String ACCEPT_LANGUAGE_HEADER = "Accept-Language";
    String ACCEPT_ENCODING_HEADER = "Accept-Encoding";
    String CONNECTION_HEADER = "Connection";

    String DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36";
    String DEFAULT_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7";
    String DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9";
    String DEFAULT_ACCEPT_ENCODING = "gzip, deflate, br";
    String DEFAULT_CONNECTION = "keep-alive";




}