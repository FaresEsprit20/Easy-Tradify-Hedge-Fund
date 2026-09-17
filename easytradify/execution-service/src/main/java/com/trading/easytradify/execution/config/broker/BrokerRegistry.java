package com.trading.easytradify.execution.config.broker;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Component
@Slf4j
public class BrokerRegistry {

    private final Map<String, BrokerConfig> brokers = new ConcurrentHashMap<>();
    private final String defaultBrokerName = "icmarkets";

    private static final List<String> ALL_BROKERS_KEYWORDS = List.of("all", "*", "every");

    @PostConstruct
    public void init() {
        registerBroker(BrokerConfig.icMarkets());
        registerBroker(BrokerConfig.vtMarkets());
        registerBroker(BrokerConfig.admirals());

        log.info("✅ BrokerRegistry initialized with {} brokers", brokers.size());
        log.info("   Default: {} (port {})", defaultBrokerName, getDefaultBroker().port());
        brokers.values().forEach(b ->
                log.info("   - {}: {} (active={})", b.name(), b.getBaseUrl(), b.active())
        );
    }

    public void registerBroker(BrokerConfig config) {
        brokers.put(config.name(), config);
    }

    public BrokerConfig getBroker(String name) {
        if (name == null || name.isBlank() || name.equalsIgnoreCase("default")) {
            return getDefaultBroker();
        }

        var broker = brokers.get(name.toLowerCase());
        if (broker == null) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.BROKER_NOT_FOUND)
                    .message("Broker not found: " + name + ". Available: " + brokers.keySet())
                    .build();
        }

        if (!broker.active()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.BROKER_INACTIVE)
                    .message("Broker is inactive: " + name)
                    .build();
        }

        return broker;
    }

    public List<BrokerConfig> resolveBrokers(List<String> requestedBrokers) {
        // If null or empty → use default
        if (requestedBrokers == null || requestedBrokers.isEmpty()) {
            return List.of(getDefaultBroker());
        }

        // If "all" → return all active brokers
        if (requestedBrokers.size() == 1 && isAllBrokersKeyword(requestedBrokers.get(0))) {
            return getActiveBrokers();
        }

        // Otherwise resolve each broker name
        var result = new ArrayList<BrokerConfig>();
        for (var name : requestedBrokers) {
            try {
                var broker = getBroker(name);
                result.add(broker);
            } catch (TradingException e) {
                log.warn("Broker {} not found, skipping", name);
            }
        }

        if (result.isEmpty()) {
            throw TradingException.builder()
                    .errorCode(ErrorCodes.NO_VALID_BROKER)
                    .message("No valid brokers found in request: " + requestedBrokers)
                    .build();
        }

        return result;
    }

    public BrokerConfig getDefaultBroker() {
        var broker = brokers.get(defaultBrokerName);
        if (broker == null || !broker.active()) {
            return brokers.values().stream()
                    .filter(BrokerConfig::active)
                    .findFirst()
                    .orElseThrow(() -> TradingException.builder()
                            .errorCode(ErrorCodes.NO_ACTIVE_BROKER)
                            .message("No active brokers available")
                            .build());
        }
        return broker;
    }

    public List<BrokerConfig> getActiveBrokers() {
        return brokers.values().stream()
                .filter(BrokerConfig::active)
                .toList();
    }

    public List<String> getActiveBrokerNames() {
        return getActiveBrokers().stream()
                .map(BrokerConfig::name)
                .toList();
    }

    public boolean isBrokerExists(String name) {
        return name != null && brokers.containsKey(name.toLowerCase());
    }

    private boolean isAllBrokersKeyword(String value) {
        return value != null && ALL_BROKERS_KEYWORDS.contains(value.toLowerCase());
    }


}