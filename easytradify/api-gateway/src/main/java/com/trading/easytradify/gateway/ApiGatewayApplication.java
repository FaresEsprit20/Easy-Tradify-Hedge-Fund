package com.trading.easytradify.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;

/**
 * <h1>API Gateway</h1>
 * <p>
 * The single entry point to the platform. The Angular app and any external
 * caller talk to this on port <b>8080</b>; nothing else needs to be reachable
 * from outside.
 * </p>
 *
 * <h2>Why routes resolve by service name</h2>
 * <p>
 * Every route targets {@code lb://service-name} rather than a host and port.
 * The services already register with Eureka, and hardcoding ports here would
 * duplicate a fact that is guaranteed to drift — {@code ai-service} and the
 * trades service were both configured on 8084 at one point, and a gateway
 * holding its own copy of that mapping would have turned the clash into
 * intermittent routing rather than a startup failure.
 * </p>
 *
 * <h2>Reactive, not servlet</h2>
 * <p>
 * Spring Cloud Gateway runs on Netty/WebFlux. Adding
 * {@code spring-boot-starter-web} to this module puts a servlet container on
 * the classpath, Boot starts that instead, and the gateway silently routes
 * nothing while appearing to come up healthy.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
@SpringBootApplication
@EnableDiscoveryClient
public class ApiGatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(ApiGatewayApplication.class, args);
    }
}
