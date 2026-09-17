package com.trading.easytradify.trades.models;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.easytradify.trades.models.TradeModels.ApiEnvelope;
import com.trading.easytradify.trades.models.TradeModels.Trade;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Pins the JSON contract between trades_controller.py and these records.
 *
 * <h2>Why this test exists</h2>
 * <p>
 * Every record here is {@code @JsonIgnoreProperties(ignoreUnknown = true)}.
 * That is right for resilience and wrong for detection: a field the Python side
 * writes under a name these records do not declare is dropped without an error,
 * and a missing primitive quietly takes its default. Twice now that has broken
 * the platform while every layer looked healthy on its own:
 * </p>
 * <ul>
 *   <li>The envelope flag is {@code success} in Python and {@code ok} here, so
 *       every successful response re-serialised to Angular as
 *       {@code {"ok": false}} and was treated as a failure.</li>
 *   <li>Leverage and the spread / reward:risk fields would have been stripped
 *       in transit, reaching Angular as absent even once the store wrote them.</li>
 * </ul>
 * <p>
 * The payload below is the literal shape Python returns. If a rename on either
 * side breaks the mapping, this fails instead of the UI going quietly blank.
 * </p>
 */
class TradeModelsWireContractTest {

    private final ObjectMapper mapper = new ObjectMapper();

    private static final String PYTHON_RESPONSE = """
            {
              "success": true,
              "data": [{
                "trade_id": "trade_1931865685",
                "ticket": 1931865685,
                "symbol": "EURUSD",
                "direction": "SELL",
                "status": "CLOSED",
                "leverage": 300,
                "account": {"login": 53048860, "server": "ICMarketsSC-Demo",
                            "leverage": 300, "currency": "USD", "company": "Raw Trading Ltd"},
                "spread_at_entry": 0.2,
                "spread_at_entry_source": "tick_history",
                "risk_reward_ratio": 5.71,
                "close_data": {
                  "close_price": 1.16097, "close_reason": "STOP_LOSS", "profit_usd": -3.43,
                  "exit_spread": 0.3, "exit_spread_source": "tick_history", "exit_slippage": -0.2
                }
              }],
              "error": null,
              "request_id": "abc123",
              "timestamp": "2026-09-14T23:15:49+00:00",
              "meta": {"pagination": {"page": 1, "total": 1}}
            }
            """;

    @Test
    void envelopeSuccessIsReadAsOk() throws Exception {
        ApiEnvelope<List<Trade>> envelope =
                mapper.readValue(PYTHON_RESPONSE, new TypeReference<>() {});

        assertTrue(envelope.ok(),
                "Python's \"success\": true must map to ok=true; otherwise every "
                        + "successful call reaches Angular as a failure");
    }

    @Test
    void envelopeReSerialisesOkForAngular() throws Exception {
        ApiEnvelope<List<Trade>> envelope =
                mapper.readValue(PYTHON_RESPONSE, new TypeReference<>() {});

        String outbound = mapper.writeValueAsString(envelope);
        assertTrue(outbound.contains("\"ok\":true"),
                "Angular's TradesApiService.unwrap() reads \"ok\"; got: " + outbound);
    }

    @Test
    void leverageAccountAndCostFieldsSurviveTheRoundTrip() throws Exception {
        ApiEnvelope<List<Trade>> envelope =
                mapper.readValue(PYTHON_RESPONSE, new TypeReference<>() {});
        Trade trade = envelope.data().get(0);

        assertEquals(300, trade.leverage());
        assertNotNull(trade.account());
        assertEquals(53048860L, trade.account().login());
        assertEquals(0.2, trade.spreadAtEntry());
        assertEquals("tick_history", trade.spreadAtEntrySource());
        assertEquals(5.71, trade.riskRewardRatio());

        assertNotNull(trade.closeData());
        assertEquals(0.3, trade.closeData().exitSpread());
        assertEquals(-0.2, trade.closeData().exitSlippage());
    }
}
