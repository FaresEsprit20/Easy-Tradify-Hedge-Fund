package com.trading.easytradify.trades;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;

/**
 * <h1>Trades Service</h1>
 * <p>
 * The Java platform's entry point to the MongoDB trade store. It owns no
 * database of its own: {@code core/mongo/trades_service.py} is the sole owner of
 * the {@code easytradify.trades} collection, and this service proxies to it over
 * HTTP so that the collection has exactly one writer.
 * </p>
 *
 * <h2>Port</h2>
 * <p>{@code 8085} (8084 belongs to ai-service). The Python service it fronts
 * listens on {@code 5011}.</p>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
@SpringBootApplication
@EnableDiscoveryClient
public class TradesApplication {

    public static void main(String[] args) {
        SpringApplication.run(TradesApplication.class, args);
    }
}
