package com.trading.easytradify.auth.config.security.sanitizers;

import java.util.regex.Pattern;

/**
 * Enhanced input sanitizer with safe URL handling and XSS protection
 */
public class InputSanitizer {

    // Patterns for dangerous content
    private static final Pattern SCRIPT_TAG_PATTERN =
            Pattern.compile("<script.*?>.*?</script>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
    private static final Pattern EVENT_HANDLER_PATTERN =
            Pattern.compile("on[a-z]+\\s*=\\s*(?:['\"].*?['\"]|[^\\s>]+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern JAVASCRIPT_URI_PATTERN =
            Pattern.compile("javascript:[^'\"]*", Pattern.CASE_INSENSITIVE);
    private static final Pattern STYLE_EXPRESSION_PATTERN =
            Pattern.compile("expression\\s*\\(.*?\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern IFRAME_PATTERN =
            Pattern.compile("<iframe.*?>.*?</iframe>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
    private static final Pattern OBJECT_PATTERN =
            Pattern.compile("<object.*?>.*?</object>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
    private static final Pattern EMBED_PATTERN =
            Pattern.compile("<embed.*?>.*?</embed>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
    private static final Pattern IMG_JS_PATTERN =
            Pattern.compile("<img[^>]+src\\s*=\\s*['\"]?javascript:[^'\">]+['\"]?[^>]*>", Pattern.CASE_INSENSITIVE);
    private static final Pattern URL_PROTOCOL_PATTERN =
            Pattern.compile("^(https?|ftp|mailto|tel):", Pattern.CASE_INSENSITIVE);
    private static final Pattern INVALID_URL_CHARS =
            Pattern.compile("[\\x00-\\x1F\\x7F<>\\\\^`{|}]");

    /**
     * Sanitize general input (text content)
     */
    public static String sanitize(String input) {
        if (input == null) return null;

        String sanitized = input;
        sanitized = removeControlChars(sanitized);
        sanitized = SCRIPT_TAG_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = EVENT_HANDLER_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = htmlEntityEncode(sanitized);

        return sanitized;
    }

    /**
     * Sanitize URLs while preserving their structure
     */
    public static String sanitizeUrl(String url) {
        if (url == null) return null;

        // Remove control chars and dangerous patterns
        String sanitized = removeControlChars(url);
        sanitized = JAVASCRIPT_URI_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = IMG_JS_PATTERN.matcher(sanitized).replaceAll("");

        // Validate URL structure
        if (!URL_PROTOCOL_PATTERN.matcher(sanitized).find()) {
            sanitized = sanitized.replaceFirst("^([^:/?#]+)(?=[/?#])", "http://$1");
        }

        // Remove remaining invalid characters
        sanitized = INVALID_URL_CHARS.matcher(sanitized).replaceAll("");

        return sanitized;
    }

    /**
     * Safe HTML entity encoding (skips URLs)
     */
    public static String htmlEntityEncode(String input) {
        if (input == null) return null;

        // Skip encoding for URLs
        if (URL_PROTOCOL_PATTERN.matcher(input).find()) {
            return input;
        }

        StringBuilder sb = new StringBuilder();
        for (char c : input.toCharArray()) {
            switch (c) {
                case '<': sb.append("&lt;"); break;
                case '>': sb.append("&gt;"); break;
                case '"': sb.append("&quot;"); break;
                case '\'': sb.append("&#39;"); break;
                case '&': sb.append("&amp;"); break;
                default: sb.append(c);
            }
        }
        return sb.toString();
    }

    /**
     * Remove control characters (except newlines and tabs)
     */
    public static String removeControlChars(String input) {
        if (input == null) return null;
        return input.replaceAll("[\\p{Cntrl}&&[^\n\t]]", "");
    }

    /**
     * Full sanitization for rich text content
     */
    public static String fullSanitize(String input) {
        if (input == null) return null;

        String sanitized = input;
        sanitized = removeControlChars(sanitized);
        sanitized = SCRIPT_TAG_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = EVENT_HANDLER_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = JAVASCRIPT_URI_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = STYLE_EXPRESSION_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = IFRAME_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = OBJECT_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = EMBED_PATTERN.matcher(sanitized).replaceAll("");
        sanitized = IMG_JS_PATTERN.matcher(sanitized).replaceAll("");

        return htmlEntityEncode(sanitized);
    }
}