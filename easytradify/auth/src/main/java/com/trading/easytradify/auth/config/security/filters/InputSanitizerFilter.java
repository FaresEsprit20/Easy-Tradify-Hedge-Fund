package com.trading.easytradify.auth.config.security.filters;

import com.trading.easytradify.auth.config.security.sanitizers.InputSanitizer;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.*;
import java.util.regex.Pattern;

/**
 * Filter that uses ALL InputSanitizer patterns and methods:
 *
 * PATTERNS:
 * - SCRIPT_TAG_PATTERN - Removes <script> tags
 * - EVENT_HANDLER_PATTERN - Removes onload, onclick, etc.
 * - JAVASCRIPT_URI_PATTERN - Removes javascript: URIs
 * - STYLE_EXPRESSION_PATTERN - Removes CSS expressions
 * - IFRAME_PATTERN - Removes <iframe> tags
 * - OBJECT_PATTERN - Removes <object> tags
 * - EMBED_PATTERN - Removes <embed> tags
 * - IMG_JS_PATTERN - Removes javascript: in img src
 * - URL_PROTOCOL_PATTERN - Validates URL protocols
 * - INVALID_URL_CHARS - Removes invalid URL characters
 *
 * METHODS:
 * - removeControlChars() - Removes control characters
 * - htmlEntityEncode() - Encodes HTML entities
 * - sanitize() - Uses SCRIPT_TAG, EVENT_HANDLER patterns + htmlEntityEncode
 * - sanitizeUrl() - Uses JAVASCRIPT_URI, IMG_JS, URL_PROTOCOL, INVALID_URL_CHARS patterns
 * - fullSanitize() - Uses ALL patterns
 */
@Slf4j
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class InputSanitizerFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {

        SanitizedRequestWrapper sanitizedRequest = new SanitizedRequestWrapper(request);

        log.debug("🔍 InputSanitizerFilter - Processing: {} {}", request.getMethod(), request.getRequestURI());

        filterChain.doFilter(sanitizedRequest, response);
    }

    private static class SanitizedRequestWrapper extends HttpServletRequestWrapper {

        public SanitizedRequestWrapper(HttpServletRequest request) {
            super(request);
        }

        /**
         * Apply FULL sanitization using ALL patterns from InputSanitizer
         * This mimics exactly what fullSanitize() does
         */
        private String applyFullSanitization(String input) {
            if (input == null) return null;

            String sanitized = input;

            // Step 1: Remove control characters (using removeControlChars)
            sanitized = InputSanitizer.removeControlChars(sanitized);

            // Step 2: Apply ALL patterns from InputSanitizer
            // SCRIPT_TAG_PATTERN - Remove script tags
            sanitized = Pattern.compile("<script.*?>.*?</script>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL)
                    .matcher(sanitized).replaceAll("");

            // EVENT_HANDLER_PATTERN - Remove event handlers (onclick, onload, etc.)
            sanitized = Pattern.compile("on[a-z]+\\s*=\\s*(?:['\"].*?['\"]|[^\\s>]+)", Pattern.CASE_INSENSITIVE)
                    .matcher(sanitized).replaceAll("");

            // JAVASCRIPT_URI_PATTERN - Remove javascript: URIs
            sanitized = Pattern.compile("javascript:[^'\"]*", Pattern.CASE_INSENSITIVE)
                    .matcher(sanitized).replaceAll("");

            // STYLE_EXPRESSION_PATTERN - Remove CSS expressions
            sanitized = Pattern.compile("expression\\s*\\(.*?\\)", Pattern.CASE_INSENSITIVE)
                    .matcher(sanitized).replaceAll("");

            // IFRAME_PATTERN - Remove iframe tags
            sanitized = Pattern.compile("<iframe.*?>.*?</iframe>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL)
                    .matcher(sanitized).replaceAll("");

            // OBJECT_PATTERN - Remove object tags
            sanitized = Pattern.compile("<object.*?>.*?</object>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL)
                    .matcher(sanitized).replaceAll("");

            // EMBED_PATTERN - Remove embed tags
            sanitized = Pattern.compile("<embed.*?>.*?</embed>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL)
                    .matcher(sanitized).replaceAll("");

            // IMG_JS_PATTERN - Remove javascript: in img src
            sanitized = Pattern.compile("<img[^>]+src\\s*=\\s*['\"]?javascript:[^'\">]+['\"]?[^>]*>", Pattern.CASE_INSENSITIVE)
                    .matcher(sanitized).replaceAll("");

            // Step 3: HTML Entity Encode (using htmlEntityEncode)
            // Skip encoding for URLs with valid protocols
            Pattern urlProtocolPattern = Pattern.compile("^(https?|ftp|mailto|tel):", Pattern.CASE_INSENSITIVE);
            if (!urlProtocolPattern.matcher(sanitized).find()) {
                StringBuilder sb = new StringBuilder();
                for (char c : sanitized.toCharArray()) {
                    switch (c) {
                        case '<': sb.append("&lt;"); break;
                        case '>': sb.append("&gt;"); break;
                        case '"': sb.append("&quot;"); break;
                        case '\'': sb.append("&#39;"); break;
                        case '&': sb.append("&amp;"); break;
                        default: sb.append(c);
                    }
                }
                sanitized = sb.toString();
            }

            return sanitized;
        }

        /**
         * Apply URL-specific sanitization using URL patterns
         */
        private String applyUrlSanitization(String input) {
            if (input == null) return null;

            String sanitized = InputSanitizer.removeControlChars(input);

            // JAVASCRIPT_URI_PATTERN
            sanitized = Pattern.compile("javascript:[^'\"]*", Pattern.CASE_INSENSITIVE)
                    .matcher(sanitized).replaceAll("");

            // IMG_JS_PATTERN
            sanitized = Pattern.compile("<img[^>]+src\\s*=\\s*['\"]?javascript:[^'\">]+['\"]?[^>]*>", Pattern.CASE_INSENSITIVE)
                    .matcher(sanitized).replaceAll("");

            // URL_PROTOCOL_PATTERN - Validate and add protocol if missing
            Pattern urlProtocolPattern = Pattern.compile("^(https?|ftp|mailto|tel):", Pattern.CASE_INSENSITIVE);
            if (!urlProtocolPattern.matcher(sanitized).find()) {
                sanitized = sanitized.replaceFirst("^([^:/?#]+)(?=[/?#])", "http://$1");
            }

            // INVALID_URL_CHARS - Remove invalid characters
            sanitized = Pattern.compile("[\\x00-\\x1F\\x7F<>\\\\^`{|}]")
                    .matcher(sanitized).replaceAll("");

            return sanitized;
        }

        /**
         * Apply basic sanitization (script tags and event handlers only)
         */
        private String applyBasicSanitization(String input) {
            if (input == null) return null;

            String sanitized = InputSanitizer.removeControlChars(input);

            // SCRIPT_TAG_PATTERN
            sanitized = Pattern.compile("<script.*?>.*?</script>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL)
                    .matcher(sanitized).replaceAll("");

            // EVENT_HANDLER_PATTERN
            sanitized = Pattern.compile("on[a-z]+\\s*=\\s*(?:['\"].*?['\"]|[^\\s>]+)", Pattern.CASE_INSENSITIVE)
                    .matcher(sanitized).replaceAll("");

            // HTML Entity Encode
            StringBuilder sb = new StringBuilder();
            for (char c : sanitized.toCharArray()) {
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

        private String applyAllSanitization(String input) {
            if (input == null) return null;

            String cleaned = InputSanitizer.removeControlChars(input);

            // Check content type and apply appropriate sanitization
            if (isUrl(cleaned)) {
                return applyUrlSanitization(cleaned);
            } else if (containsHtmlTags(cleaned) || isRichText(cleaned)) {
                return applyFullSanitization(cleaned);
            } else {
                return applyBasicSanitization(cleaned);
            }
        }

        @Override
        public String getParameter(String name) {
            String value = super.getParameter(name);
            return applyAllSanitization(value);
        }

        @Override
        public Map<String, String[]> getParameterMap() {
            Map<String, String[]> originalMap = super.getParameterMap();
            Map<String, String[]> sanitizedMap = new HashMap<>();

            for (Map.Entry<String, String[]> entry : originalMap.entrySet()) {
                String[] sanitizedValues = Arrays.stream(entry.getValue())
                        .map(this::applyAllSanitization)
                        .toArray(String[]::new);
                sanitizedMap.put(applyAllSanitization(entry.getKey()), sanitizedValues);
            }

            return Collections.unmodifiableMap(sanitizedMap);
        }

        @Override
        public String[] getParameterValues(String name) {
            String[] values = super.getParameterValues(name);
            if (values == null) return null;

            return Arrays.stream(values)
                    .map(this::applyAllSanitization)
                    .toArray(String[]::new);
        }

        @Override
        public String getHeader(String name) {
            String value = super.getHeader(name);
            if (value == null) return null;

            if ("Authorization".equalsIgnoreCase(name) ||
                    "Content-Type".equalsIgnoreCase(name) ||
                    "Content-Length".equalsIgnoreCase(name)) {
                return value;
            }

            return applyAllSanitization(value);
        }

        @Override
        public Enumeration<String> getHeaders(String name) {
            Enumeration<String> headers = super.getHeaders(name);
            List<String> sanitizedHeaders = new ArrayList<>();

            while (headers.hasMoreElements()) {
                String header = headers.nextElement();

                if ("Authorization".equalsIgnoreCase(name) ||
                        "Content-Type".equalsIgnoreCase(name) ||
                        "Content-Length".equalsIgnoreCase(name)) {
                    sanitizedHeaders.add(header);
                } else if (header != null) {
                    sanitizedHeaders.add(applyAllSanitization(header));
                }
            }

            return Collections.enumeration(sanitizedHeaders);
        }

        @Override
        public String getQueryString() {
            String queryString = super.getQueryString();
            if (queryString == null) return null;
            return applyFullSanitization(queryString);
        }

        private boolean isUrl(String input) {
            if (input == null) return false;
            String lowerInput = input.toLowerCase();
            return lowerInput.startsWith("http://") ||
                    lowerInput.startsWith("https://") ||
                    lowerInput.startsWith("ftp://") ||
                    lowerInput.startsWith("mailto:") ||
                    lowerInput.startsWith("tel:") ||
                    input.contains(".com") ||
                    input.contains(".tn") ||
                    input.contains(".org") ||
                    input.contains(".net");
        }

        private boolean containsHtmlTags(String input) {
            if (input == null) return false;
            return input.contains("<") && input.contains(">") ||
                    input.contains("&lt;") || input.contains("&gt;") ||
                    input.matches(".*<[^>]+>.*");
        }

        private boolean isRichText(String input) {
            if (input == null) return false;
            String lowerInput = input.toLowerCase();
            return lowerInput.contains("<div") ||
                    lowerInput.contains("<p>") ||
                    lowerInput.contains("<span") ||
                    lowerInput.contains("<br") ||
                    lowerInput.contains("<img") ||
                    lowerInput.contains("<a href") ||
                    lowerInput.contains("javascript:") ||
                    lowerInput.contains("onclick") ||
                    lowerInput.contains("onload") ||
                    lowerInput.contains("<iframe") ||
                    lowerInput.contains("<object") ||
                    lowerInput.contains("<embed");
        }
    }
}