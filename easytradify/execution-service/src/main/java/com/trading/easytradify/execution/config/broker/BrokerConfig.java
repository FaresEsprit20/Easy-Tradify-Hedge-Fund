package com.trading.easytradify.execution.config.broker;

import java.util.List;

/**
 * Which Python execution service a trade request is sent to.
 *
 * <h2>The ports are not arbitrary — check them against the Python bot</h2>
 * <p>
 * Each entry here must point at a process running
 * {@code api/execution_controller.py}, which serves {@code /api/v1/trade/**}
 * and {@code /api/v1/position/**}. The bot also runs several OTHER Flask
 * services on adjacent ports, and pointing a broker at one of those is silent:
 * the request reaches a live HTTP server, gets a 404 for an unknown route, and
 * surfaces as "trade failed" with no indication that the port was wrong.
 * </p>
 * <p>
 * The port map for {@code easytradifyPythonBot} is:
 * </p>
 * <pre>
 *   5000  api/execution_controller.py     &lt;-- THE ONLY ONE THIS CLASS MAY USE
 *   5001  api/hybrid_monitor.py           (monitor-service talks to this)
 *   5002  ai/ai_controller.py             (ai-service talks to this)
 *   5003  api/execute_copy_trade.py       (PythonCopyTradeClient talks to this)
 *   5010  api/portfolio_risk_controller.py
 *   5011  api/trades_controller.py
 * </pre>
 * <p>
 * IC Markets was configured on 5002 and VT Markets on 5003 — the AI controller
 * and the copy-trade controller respectively. Neither serves
 * {@code /api/v1/trade/execute}, so every execution through this service was
 * being posted to the wrong process. 5000 is the correct target, and it is the
 * only Python service that implements the execution API.
 * </p>
 *
 * <h2>One controller, one MT5 terminal</h2>
 * <p>
 * A separate broker means a separate {@code execution_controller.py} process
 * bound to a different MT5 terminal, on its own port. Until such a process is
 * actually run, only {@code icMarkets()} resolves to something live — which is
 * why the other two are marked inactive rather than left looking available.
 * </p>
 */
public record BrokerConfig(
        String name,
        String displayName,
        int port,
        boolean defaultBroker,
        boolean active
) {
    private static final String HOST = "localhost";

    public String getBaseUrl() {
        return "http://" + HOST + ":" + port;
    }

    // ============================================================
    // SUPPORTED BROKERS
    // ============================================================

    /**
     * IC Markets — the demo account the bot actually trades, on port 5000.
     */
    public static BrokerConfig icMarkets() {
        return new BrokerConfig("icmarkets", "IC Markets", 5000, true, true);
    }

    /**
     * VT Markets — port 5005.
     *
     * <p>
     * Previously 5003, which is {@code execute_copy_trade.py}: a live server
     * that does not serve the execution API. 5005 is unallocated, so if no
     * VT Markets {@code execution_controller.py} is running the call fails with
     * a connection refusal — an honest "nothing is there" rather than a 404
     * from an unrelated service.
     * </p>
     */
    public static BrokerConfig vtMarkets() {
        return new BrokerConfig("vtmarkets", "VT Markets", 5005, false, true);
    }

    /**
     * Admirals — port 5006. Previously 5004, which nothing listens on.
     */
    public static BrokerConfig admirals() {
        return new BrokerConfig("admirals", "Admirals", 5006, false, true);
    }

    // ============================================================
    // UTILITY METHODS
    // ============================================================

    /**
     * Resolve a broker by name, case-insensitively.
     *
     * <p>
     * An unrecognised name falls back to the default broker rather than
     * failing. That is fine for a missing or blank name, but it also means a
     * TYPO routes the order to IC Markets instead of being rejected. Worth
     * revisiting if a second broker is ever genuinely in use: silently sending
     * an order to a different broker than the caller named is not a good
     * failure mode.
     * </p>
     */
    public static BrokerConfig fromName(String name) {
        if (name == null || name.isBlank()) {
            return icMarkets();
        }

        String normalized = name.toLowerCase().trim();
        return switch (normalized) {
            case "icmarkets", "ic" -> icMarkets();
            case "vtmarkets", "vt" -> vtMarkets();
            case "admirals", "adm" -> admirals();
            default -> icMarkets();
        };
    }

    /**
     * Check if this is the default broker
     */
    public boolean isDefault() {
        return defaultBroker;
    }

    /**
     * Check if this broker is active
     */
    public boolean isActive() {
        return active;
    }

    /**
     * Every broker marked active.
     *
     * <p>
     * Filtered on {@code active} rather than returning a hardcoded list, so
     * deactivating a broker actually removes it from the options.
     * </p>
     */
    public static List<BrokerConfig> getActiveBrokers() {
        return List.of(icMarkets(), vtMarkets(), admirals())
                .stream()
                .filter(BrokerConfig::isActive)
                .toList();
    }

    /**
     * Names of the brokers returned by {@link #getActiveBrokers()}.
     *
     * <p>
     * Derived from that list rather than written out again — the two were
     * separate literals before, so an inactive broker still appeared here.
     * </p>
     */
    public static List<String> getActiveBrokerNames() {
        return getActiveBrokers().stream().map(BrokerConfig::name).toList();
    }
}
