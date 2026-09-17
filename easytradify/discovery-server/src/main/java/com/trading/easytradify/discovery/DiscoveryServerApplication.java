package com.trading.easytradify.discovery;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.netflix.eureka.server.EnableEurekaServer;

@SpringBootApplication
@EnableEurekaServer
public class DiscoveryServerApplication {

    public static void main(String[] args) {
        SpringApplication.run(DiscoveryServerApplication.class, args);
        System.out.println("========================================");
        System.out.println("🔄 EUREKA DISCOVERY SERVER STARTED");
        System.out.println("📍 Dashboard: http://localhost:8761");
        System.out.println("========================================");
    }
}