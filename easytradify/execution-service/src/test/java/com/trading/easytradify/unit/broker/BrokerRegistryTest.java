package com.trading.easytradify.unit.broker;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.execution.config.broker.BrokerConfig;
import com.trading.easytradify.execution.config.broker.BrokerRegistry;
import com.trading.easytradify.unit.TestDataFactory;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("Broker Registry Unit Tests")
class BrokerRegistryTest {

    private BrokerRegistry brokerRegistry;

    @BeforeEach
    void setUp() {
        brokerRegistry = new BrokerRegistry();
        brokerRegistry.init();
    }

    @Nested
    @DisplayName("Initialization Tests")
    class InitTests {

        @Test
        @DisplayName("Should initialize with 3 active brokers")
        void shouldInitializeWithThreeBrokers() {
            var brokers = brokerRegistry.getActiveBrokers();

            assertEquals(3, brokers.size());
            assertTrue(brokerRegistry.isBrokerExists("icmarkets"));
            assertTrue(brokerRegistry.isBrokerExists("vtmarkets"));
            assertTrue(brokerRegistry.isBrokerExists("admirals"));
        }

        @Test
        @DisplayName("Should have IC Markets as default broker")
        void shouldHaveIcMarketsAsDefault() {
            var defaultBroker = brokerRegistry.getDefaultBroker();

            assertNotNull(defaultBroker);
            assertEquals("icmarkets", defaultBroker.name());
            // 5000 is api/execution_controller.py. It was 5002, which is
            // ai/ai_controller.py -- a live server that 404s /api/v1/trade/execute,
            // so every execution failed in a way that looked like a trade error.
            assertEquals(5000, defaultBroker.port());
            assertTrue(defaultBroker.defaultBroker());
        }

        @Test
        @DisplayName("All brokers should be active")
        void allBrokersShouldBeActive() {
            var brokers = brokerRegistry.getActiveBrokers();

            assertTrue(brokers.stream().allMatch(BrokerConfig::active));
        }
    }

    @Nested
    @DisplayName("Broker Resolution Tests")
    class BrokerResolutionTests {

        @Test
        @DisplayName("Should return default broker when name is null")
        void shouldReturnDefaultBrokerWhenNameIsNull() {
            var broker = brokerRegistry.getBroker(null);

            assertNotNull(broker);
            assertEquals("icmarkets", broker.name());
        }

        @Test
        @DisplayName("Should return default broker when name is empty")
        void shouldReturnDefaultBrokerWhenNameIsEmpty() {
            var broker = brokerRegistry.getBroker("");

            assertNotNull(broker);
            assertEquals("icmarkets", broker.name());
        }

        @Test
        @DisplayName("Should return default broker when name is 'default'")
        void shouldReturnDefaultBrokerWhenNameIsDefault() {
            var broker = brokerRegistry.getBroker("default");

            assertNotNull(broker);
            assertEquals("icmarkets", broker.name());
        }

        @Test
        @DisplayName("Should find broker by name (case-insensitive)")
        void shouldFindBrokerByNameCaseInsensitive() {
            var broker = brokerRegistry.getBroker("ICMARKETS");

            assertNotNull(broker);
            assertEquals("icmarkets", broker.name());

            var broker2 = brokerRegistry.getBroker("VtMaRkEtS");
            assertNotNull(broker2);
            assertEquals("vtmarkets", broker2.name());
        }

        @Test
        @DisplayName("Should throw TradingException when broker not found")
        void shouldThrowExceptionWhenBrokerNotFound() {
            var exception = assertThrows(
                    TradingException.class,
                    () -> brokerRegistry.getBroker("unknown")
            );

            assertEquals(ErrorCodes.BROKER_NOT_FOUND, exception.getErrorCode());
            assertTrue(exception.getMessage().contains("Broker not found: unknown"));
            assertTrue(exception.getMessage().contains("icmarkets"));
            assertTrue(exception.getMessage().contains("vtmarkets"));
            assertTrue(exception.getMessage().contains("admirals"));
        }
    }

    @Nested
    @DisplayName("Multi-Broker Resolution Tests")
    class MultiBrokerResolutionTests {

        @Test
        @DisplayName("Should resolve single broker from list")
        void shouldResolveSingleBrokerFromList() {
            var requested = List.of("icmarkets");
            var resolved = brokerRegistry.resolveBrokers(requested);

            assertEquals(1, resolved.size());
            assertEquals("icmarkets", resolved.get(0).name());
        }

        @Test
        @DisplayName("Should resolve multiple brokers from list")
        void shouldResolveMultipleBrokersFromList() {
            var requested = List.of("icmarkets", "vtmarkets");
            var resolved = brokerRegistry.resolveBrokers(requested);

            assertEquals(2, resolved.size());
            assertEquals("icmarkets", resolved.get(0).name());
            assertEquals("vtmarkets", resolved.get(1).name());
        }

        @Test
        @DisplayName("Should resolve all brokers when 'all' is requested")
        void shouldResolveAllBrokersWhenAllRequested() {
            var requested = List.of("all");
            var resolved = brokerRegistry.resolveBrokers(requested);

            assertEquals(3, resolved.size());
            assertTrue(resolved.stream().anyMatch(b -> b.name().equals("icmarkets")));
            assertTrue(resolved.stream().anyMatch(b -> b.name().equals("vtmarkets")));
            assertTrue(resolved.stream().anyMatch(b -> b.name().equals("admirals")));
        }

        @Test
        @DisplayName("Should resolve all brokers when '*' is requested")
        void shouldResolveAllBrokersWhenStarRequested() {
            var requested = List.of("*");
            var resolved = brokerRegistry.resolveBrokers(requested);

            assertEquals(3, resolved.size());
        }

        @Test
        @DisplayName("Should skip invalid brokers and return valid ones")
        void shouldSkipInvalidBrokers() {
            var requested = List.of("icmarkets", "unknown", "vtmarkets");
            var resolved = brokerRegistry.resolveBrokers(requested);

            assertEquals(2, resolved.size());
            assertEquals("icmarkets", resolved.get(0).name());
            assertEquals("vtmarkets", resolved.get(1).name());
        }

        @Test
        @DisplayName("Should throw TradingException when no valid brokers found")
        void shouldThrowExceptionWhenNoValidBrokersFound() {
            var requested = List.of("unknown1", "unknown2");

            var exception = assertThrows(
                    TradingException.class,
                    () -> brokerRegistry.resolveBrokers(requested)
            );

            assertEquals(ErrorCodes.NO_VALID_BROKER, exception.getErrorCode());
        }

        @Test
        @DisplayName("Should use default broker when requested list is null")
        void shouldUseDefaultBrokerWhenRequestedListIsNull() {
            var resolved = brokerRegistry.resolveBrokers(null);

            assertEquals(1, resolved.size());
            assertEquals("icmarkets", resolved.get(0).name());
        }

        @Test
        @DisplayName("Should use default broker when requested list is empty")
        void shouldUseDefaultBrokerWhenRequestedListIsEmpty() {
            var resolved = brokerRegistry.resolveBrokers(List.of());

            assertEquals(1, resolved.size());
            assertEquals("icmarkets", resolved.get(0).name());
        }
    }

    @Nested
    @DisplayName("Utility Methods Tests")
    class UtilityMethodTests {

        @Test
        @DisplayName("Should get active broker names")
        void shouldGetActiveBrokerNames() {
            var names = brokerRegistry.getActiveBrokerNames();

            // Derived from getActiveBrokers() now, rather than a second
            // hardcoded literal that could drift away from it.
            assertEquals(3, names.size());
            assertTrue(names.contains("icmarkets"));
            assertTrue(names.contains("vtmarkets"));
            assertTrue(names.contains("admirals"));
        }

        @Test
        @DisplayName("Should check if broker exists")
        void shouldCheckIfBrokerExists() {
            assertTrue(brokerRegistry.isBrokerExists("icmarkets"));
            assertTrue(brokerRegistry.isBrokerExists("vtmarkets"));
            assertTrue(brokerRegistry.isBrokerExists("admirals"));
            assertFalse(brokerRegistry.isBrokerExists("unknown"));
            assertFalse(brokerRegistry.isBrokerExists(null));
        }

        @Test
        @DisplayName("Should check if broker exists (case-insensitive)")
        void shouldCheckIfBrokerExistsCaseInsensitive() {
            assertTrue(brokerRegistry.isBrokerExists("ICMARKETS"));
            assertTrue(brokerRegistry.isBrokerExists("VtMaRkEtS"));
        }

        @Test
        @DisplayName("Broker should return correct base URL")
        void brokerShouldReturnCorrectBaseUrl() {
            var broker = TestDataFactory.defaultBroker();

            assertEquals("http://localhost:5000", broker.getBaseUrl());
        }
    }
}