package com.trading.easytradify.gateway;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * What the gateway answers when a circuit is open or a call times out.
 *
 * <h2>The whole point is to say the right thing, not just to say something</h2>
 * <p>
 * A generic "service unavailable" is adequate for a dashboard panel and
 * actively dangerous for an order. These handlers differ because the correct
 * response to each failure differs, and a client that retries the wrong one
 * causes real damage.
 * </p>
 *
 * <h2>Why every body carries {@code retryable} and {@code stateUnknown}</h2>
 * <p>
 * Those two flags are the only things a client genuinely needs to decide what
 * to do: whether repeating the call is safe, and whether the request may
 * already have taken effect. Every other field is for the human reading the
 * screen.
 * </p>
 */
@RestController
@RequestMapping("/fallback")
public class FallbackController {

    /**
     * Execution and copy-trade.
     *
     * <p>
     * <b>This one must never say the trade did not happen.</b> The gateway
     * times out on the REQUEST, not on the broker: a POST to
     * {@code /execution/trade} that exceeds the limit may already have reached
     * MT5 and filled. Reporting it as failed invites the obvious next action —
     * place it again — and that is how one intended position becomes two.
     * </p>
     *
     * <p>
     * So the answer is explicitly "unknown", with the instruction to reconcile
     * against open positions rather than retry. {@code retryable} is false for
     * exactly this reason, even though the transport error itself looks
     * retryable.
     * </p>
     */
    @RequestMapping("/execution")
    public Mono<ResponseEntity<Map<String, Object>>> execution() {
        Map<String, Object> body = base("execution-service");
        body.put("message",
                "The execution service did not respond in time. Any order in this "
                        + "request may or may not have reached the broker.");
        body.put("action",
                "Do NOT resend. Check open positions and recent trades to see whether it filled.");
        body.put("retryable", false);
        body.put("stateUnknown", true);
        return answer(body);
    }

    /**
     * The trade store.
     *
     * <p>
     * Returns no {@code trades} key at all rather than an empty array. An empty
     * list is a claim — "there are no trades" — and here it would be false;
     * anything computing a win rate or a daily total from it would produce a
     * confident, wrong number. The absence of the key forces the caller to
     * handle the failure.
     * </p>
     */
    @RequestMapping("/trades")
    public Mono<ResponseEntity<Map<String, Object>>> trades() {
        Map<String, Object> body = base("trades-service");
        body.put("message", "The trade store is unreachable.");
        body.put("action", "Stored trades could not be read. This is not an empty result set.");
        body.put("retryable", true);
        body.put("stateUnknown", false);
        return answer(body);
    }

    /**
     * Risk and portfolio limits.
     *
     * <p>
     * Carries {@code tradingAllowed: false}. The risk service is what decides
     * whether an order may be placed at all, and the safe reading of "I could
     * not ask" is no. Defaulting to allowed during an outage would open every
     * limit precisely when nothing is checking them.
     * </p>
     */
    @RequestMapping("/portfolio")
    public Mono<ResponseEntity<Map<String, Object>>> portfolio() {
        Map<String, Object> body = base("portfolio-service");
        body.put("message", "The risk service is unreachable.");
        body.put("action", "Trading is treated as not permitted until limits can be read.");
        body.put("tradingAllowed", false);
        body.put("retryable", true);
        body.put("stateUnknown", false);
        return answer(body);
    }

    /**
     * The monitor.
     *
     * <p>
     * The gentlest case: this feeds dashboard panels, and a failed poll simply
     * means the last values go stale. {@code running} is deliberately absent —
     * reporting false would say the monitor has stopped, which is a different
     * and much more alarming claim than "I cannot reach it".
     * </p>
     */
    @RequestMapping("/monitor")
    public Mono<ResponseEntity<Map<String, Object>>> monitor() {
        Map<String, Object> body = base("monitor-service");
        body.put("message", "The monitor service is unreachable.");
        body.put("action", "Displayed values are the last known ones and are stale.");
        body.put("retryable", true);
        body.put("stateUnknown", false);
        return answer(body);
    }

    /**
     * The AI layer.
     *
     * <p>
     * Note the AI circuit allows 180 seconds before it trips, because folds and
     * a permutation null legitimately take minutes. Reaching this handler
     * therefore means something is genuinely wrong, not merely slow — which is
     * why the message says so rather than suggesting patience.
     * </p>
     */
    @RequestMapping("/ai")
    public Mono<ResponseEntity<Map<String, Object>>> ai() {
        Map<String, Object> body = base("ai-service");
        body.put("message", "The AI service did not respond within 180 seconds.");
        body.put("action", "No result was produced. Nothing partial was computed or stored.");
        body.put("retryable", true);
        body.put("stateUnknown", false);
        return answer(body);
    }

    /**
     * Auth.
     *
     * <p>
     * Fails closed, like everything else about authentication here: an
     * unreachable auth service means "not signed in", never "assume signed
     * in". The client should send the user to sign in again rather than
     * proceeding on a session it could not confirm.
     * </p>
     */
    @RequestMapping("/auth")
    public Mono<ResponseEntity<Map<String, Object>>> auth() {
        Map<String, Object> body = base("auth-service");
        body.put("message", "The auth service is unreachable.");
        body.put("action", "Treat the session as unauthenticated.");
        body.put("isAuthenticated", false);
        body.put("retryable", true);
        body.put("stateUnknown", false);
        return answer(body);
    }

    // ----------------------------------------------------------------

    private Map<String, Object> base(String service) {
        // LinkedHashMap so the JSON field order is stable and readable in a log
        // or a terminal, rather than shuffling between responses.
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("success", false);
        body.put("error", "SERVICE_UNAVAILABLE");
        body.put("service", service);
        body.put("timestamp", Instant.now().toString());
        return body;
    }

    /**
     * 503 with a {@code Retry-After}.
     *
     * <p>
     * 503 rather than 500: it states that the failure is the gateway's inability
     * to reach a dependency, not a fault in the request, so a client knows not
     * to "fix" a payload that was fine. The header matches the breakers' 10s
     * open state — probing sooner only burns calls against an open circuit.
     * </p>
     */
    private Mono<ResponseEntity<Map<String, Object>>> answer(Map<String, Object> body) {
        return Mono.just(ResponseEntity
                .status(HttpStatus.SERVICE_UNAVAILABLE)
                .header("Retry-After", "10")
                .body(body));
    }
}
