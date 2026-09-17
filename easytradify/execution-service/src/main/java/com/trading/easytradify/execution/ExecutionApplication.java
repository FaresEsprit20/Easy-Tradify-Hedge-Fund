package com.trading.easytradify.execution;

import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.domain.EntityScan;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.data.jpa.repository.config.EnableJpaAuditing;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;

@SpringBootApplication(scanBasePackages = {
        // The module's OWN package must be listed. scanBasePackages
        // REPLACES the default (the application class's package), so
        // naming only "common" meant com.trading.easytradify.execution.**
        // was never scanned: no controller, no service, no client and no
        // WebClient bean were registered, and the service started serving
        // nothing. Compiling proved the classes were valid, not wired.
        "com.trading.easytradify.execution",
        "com.trading.easytradify.common"
})
@Slf4j
@EnableJpaAuditing
@EnableDiscoveryClient
public class ExecutionApplication {

    public static void main(String[] args) {
        SpringApplication.run(ExecutionApplication.class, args);

        log.info("=".repeat(60));
        log.info("🚀 Execution SERVICE STARTED");
        log.info("📡 Web server running on http://localhost:8081");
        log.info("📖 Swagger UI: http://localhost:8082/swagger-ui.html");
        log.info("=".repeat(60));
    }

}