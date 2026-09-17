package com.trading.easytradify.integration;

import com.trading.easytradify.execution.ExecutionApplication;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpMethod;
import org.springframework.test.context.junit.jupiter.SpringExtension;
import org.springframework.web.reactive.function.client.WebClient;

@ExtendWith(SpringExtension.class)
@SpringBootTest(
        classes = ExecutionApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT
)
public abstract class BaseIntegrationTest {

    @LocalServerPort
    protected int port;

    protected WebClient webClient;

    protected String baseUrl;
    protected String apiKey;

    @BeforeEach
    void setUpBase() {
        baseUrl = "http://localhost:" + port;
        apiKey = "easy-tradify-internal-secret-key-2026";

        webClient = WebClient.builder()
                .baseUrl(baseUrl)
                .codecs(configurer ->
                        configurer.defaultCodecs().maxInMemorySize(10 * 1024 * 1024))
                .build();
    }

    protected WebClient.RequestHeadersSpec<?> getRequest(String uri) {
        return webClient
                .method(HttpMethod.GET)
                .uri(uri)
                .header("X-API-Key", apiKey);
    }

    protected WebClient.RequestBodySpec postRequest(String uri) {
        return webClient
                .method(HttpMethod.POST)
                .uri(uri)
                .header("X-API-Key", apiKey);
    }

    protected WebClient.RequestBodySpec putRequest(String uri) {
        return webClient
                .method(HttpMethod.PUT)
                .uri(uri)
                .header("X-API-Key", apiKey);
    }

    protected WebClient.RequestHeadersSpec<?> deleteRequest(String uri) {
        return webClient
                .method(HttpMethod.DELETE)
                .uri(uri)
                .header("X-API-Key", apiKey);
    }
}