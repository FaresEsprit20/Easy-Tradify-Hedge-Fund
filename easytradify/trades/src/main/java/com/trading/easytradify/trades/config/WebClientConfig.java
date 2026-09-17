package com.trading.easytradify.trades.config;

import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.handler.timeout.WriteTimeoutHandler;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.util.concurrent.TimeUnit;

/**
 * <h1>WebClient Configuration</h1>
 * <p>
 * The HTTP client used to reach the Python trades service.
 * </p>
 *
 * <h2>Why the buffer is enlarged</h2>
 * <p>
 * Spring's default in-memory limit for a single response body is 256 KB. That
 * is far too small here: a stored trade carries its whole
 * {@code price_evolution} forward walk, which is precisely the payload that
 * made Firestore's 1 MiB document cap unusable and forced the move to MongoDB.
 * A page of such trades comfortably exceeds the default and would fail with
 * {@code DataBufferLimitException} — so the limit is raised to 32 MB, above
 * MongoDB's own 16 MB per-document ceiling.
 * </p>
 *
 * <h2>Why timeouts are generous</h2>
 * <p>
 * Some endpoints do real work rather than a lookup: {@code /diagnostics} scans
 * stored trades and {@code /stats/timeseries} aggregates across the collection.
 * A short read timeout turns a slow-but-correct answer into a spurious error.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
@Configuration
public class WebClientConfig {

    @Value("${trades.connect-timeout:30000}")
    private int connectTimeoutMs;

    @Value("${trades.read-timeout:60000}")
    private int readTimeoutMs;

    @Value("${trades.write-timeout:60000}")
    private int writeTimeoutMs;

    /** Response bodies up to 32 MB — above MongoDB's 16 MB document ceiling. */
    private static final int MAX_IN_MEMORY_BYTES = 32 * 1024 * 1024;

    @Bean
    public WebClient pythonWebClient() {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, connectTimeoutMs)
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(readTimeoutMs, TimeUnit.MILLISECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(writeTimeoutMs, TimeUnit.MILLISECONDS)));

        return WebClient.builder()
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .codecs(c -> c.defaultCodecs().maxInMemorySize(MAX_IN_MEMORY_BYTES))
                .build();
    }
}
