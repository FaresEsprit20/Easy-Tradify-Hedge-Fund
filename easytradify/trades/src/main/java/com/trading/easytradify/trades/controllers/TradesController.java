package com.trading.easytradify.trades.controllers;

import com.trading.easytradify.trades.models.TradeModels.*;
import com.trading.easytradify.trades.services.TradesService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * <h1>Trades Controller</h1>
 * <p>
 * The Java platform's REST face over the MongoDB trade store. Mirrors the
 * Python trades service ({@code api/trades_controller.py}, port 5011) so the
 * Angular frontend and the other Java services have a single, Eureka-discovered
 * entry point rather than each reaching into Python directly.
 * </p>
 *
 * <h2>Base path</h2>
 * <p>{@code /api/v1/trades}</p>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
@RestController
@RequestMapping("/api/v1/trades")
@RequiredArgsConstructor
@Slf4j
@Tag(name = "Trades", description = "Query and manage stored trades (MongoDB)")
public class TradesController {

    private final TradesService tradesService;

    // ============================================================
    // READ
    // ============================================================

    @GetMapping
    @Operation(summary = "List trades",
            description = "A bounded, sorted page. Filters and sort keys are whitelisted server-side.")
    public ResponseEntity<ApiEnvelope<List<Trade>>> list(
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false, name = "page_size") Integer pageSize,
            @RequestParam(required = false) String symbol,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String direction,
            @RequestParam(required = false, name = "sort_by") String sortBy,
            @RequestParam(required = false, name = "sort_dir") String sortDir,
            @RequestParam(required = false, name = "opened_after") String openedAfter,
            @RequestParam(required = false, name = "opened_before") String openedBefore,
            @RequestParam(required = false, name = "include_deleted") Boolean includeDeleted) {

        TradeQuery q = new TradeQuery(page, pageSize, symbol, status, direction,
                sortBy, sortDir, openedAfter, openedBefore, includeDeleted);
        return ResponseEntity.ok(tradesService.list(q));
    }

    @PostMapping("/query")
    @Operation(
            summary = "Filter trades with a JSON body",
            description = """
                    The preferred way to filter. Every field is optional; a list means "any of".

                    ```json
                    {
                      "page": 1, "size": 25,
                      "sortField": "closedAt", "sortDirection": "DESC",
                      "status": "CLOSED",
                      "outcome": ["WIN"],
                      "leverage": [300, 500],
                      "symbol": ["EURUSD", "GBPUSD"],
                      "direction": "SELL",
                      "closeReason": ["TAKE_PROFIT"],
                      "profitUsd": {"min": 0, "max": 50},
                      "volume": {"min": 0.1},
                      "durationSeconds": {"max": 3600},
                      "openedFrom": "2026-09-11T00:00:00Z",
                      "closedTo": "2026-09-14T23:59:59Z",
                      "search": "EUR",
                      "withSummary": true
                    }
                    ```

                    `outcome` is scored from the measured close profit: WIN, LOSS, BREAKEVEN,
                    or UNSCORED (closed with no profit recorded).

                    `meta.summary` reports win rate, net and average profit, profit factor and
                    a small-sample flag over the whole filtered set -- overall and per leverage.

                    Unknown fields are rejected with 400 rather than ignored, so a mistyped
                    filter cannot silently return every trade. `GET /filters` lists the
                    accepted fields and the values that exist.
                    """)
    public ResponseEntity<ApiEnvelope<List<Trade>>> query(
            @RequestBody(required = false) Map<String, Object> body) {
        // A Map, not a typed record, on purpose. See DefaultPythonTradesClient
        // .queryTrades: a record with ignoreUnknown would swallow a typo and
        // return unfiltered data, where the Python validator returns a 400.
        return ResponseEntity.ok(tradesService.query(body));
    }

    @GetMapping("/filters")
    @Operation(summary = "Every accepted filter, with the values present in the store",
            description = "Statuses, outcomes, leverages, symbols, directions and close reasons with "
                    + "their trade counts, plus the observed range of profit, volume, duration and dates.")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> filters() {
        return ResponseEntity.ok(tradesService.filters());
    }

    @GetMapping("/search")
    @Operation(summary = "Free-text search over whitelisted searchable fields")
    public ResponseEntity<ApiEnvelope<List<Trade>>> search(
            @RequestParam String q,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false, name = "page_size") Integer pageSize) {
        return ResponseEntity.ok(tradesService.search(q, page, pageSize));
    }

    @GetMapping("/count")
    @Operation(summary = "Count trades matching the filters")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> count(
            @RequestParam(required = false) String symbol,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String direction) {
        TradeQuery q = new TradeQuery(null, null, symbol, status, direction,
                null, null, null, null, null);
        return ResponseEntity.ok(tradesService.count(q));
    }

    @GetMapping("/distinct/{field}")
    @Operation(summary = "Distinct values of one whitelisted field")
    public ResponseEntity<ApiEnvelope<List<Object>>> distinct(@PathVariable String field) {
        return ResponseEntity.ok(tradesService.distinct(field));
    }

    // ============================================================
    // STATISTICS
    // ============================================================

    @GetMapping("/stats")
    @Operation(summary = "Headline counts")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> stats() {
        return ResponseEntity.ok(tradesService.stats());
    }

    @GetMapping("/stats/performance")
    @Operation(summary = "Win rate, expectancy and realised P/L",
            description = "Profit is the broker's realised figure. Read win rate and R with the "
                    + "collection's provenance in mind — trades gathered under loosened "
                    + "data-collection gates do not represent the strategy.")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> performance(
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to,
            @RequestParam(required = false) String symbol) {
        return ResponseEntity.ok(tradesService.performance(from, to, symbol));
    }

    @GetMapping("/stats/by-symbol")
    @Operation(summary = "Performance grouped by symbol",
            description = "An edge carried by one instrument is that instrument's, not the strategy's.")
    public ResponseEntity<ApiEnvelope<List<Map<String, Object>>>> statsBySymbol(
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to) {
        return ResponseEntity.ok(tradesService.statsBySymbol(from, to));
    }

    @GetMapping("/stats/timeseries")
    @Operation(summary = "Performance bucketed over time")
    public ResponseEntity<ApiEnvelope<List<Map<String, Object>>>> statsTimeseries(
            @RequestParam(required = false) String interval,
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to) {
        return ResponseEntity.ok(tradesService.statsTimeseries(interval, from, to));
    }

    // ============================================================
    // DIAGNOSTICS
    // ============================================================

    @GetMapping("/health")
    @Operation(summary = "Whether the Mongo server answered",
            description = "Not whether a client object exists — holding one proves nothing.")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> health() {
        return ResponseEntity.ok(tradesService.health());
    }

    @GetMapping("/diagnostics")
    @Operation(summary = "Scan stored trades for shape defects")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> diagnostics(
            @RequestParam(required = false) Integer limit,
            @RequestParam(required = false, name = "only_open") Boolean onlyOpen,
            @RequestParam(required = false, name = "since_hours") Integer sinceHours) {
        return ResponseEntity.ok(tradesService.diagnostics(limit, onlyOpen, sinceHours));
    }

    @PostMapping("/diagnostics/self-check")
    @Operation(summary = "Run the Python service's own self-check")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> selfCheck() {
        return ResponseEntity.ok(tradesService.selfCheck());
    }

    @GetMapping("/diagnostics/shape")
    @Operation(summary = "Are stored trades readable by the AI layer?",
            description = "Counts how many sampled trades carry entry.price, entry.stop_loss, "
                    + "direction and opened_at. A trade missing any of these is skipped "
                    + "silently by every model, so a rising trade count is not evidence "
                    + "that collection is working.")
    public ResponseEntity<Map<String, Object>> verifyShape(
            @RequestParam(required = false, defaultValue = "50") int sample) {
        return ResponseEntity.ok(tradesService.verifyShape(sample));
    }

    // ============================================================
    // WRITE
    // ============================================================

    @PostMapping
    @Operation(summary = "Upsert one trade, keyed on trade_id (idempotent)")
    public ResponseEntity<ApiEnvelope<Trade>> upsert(@RequestBody Map<String, Object> trade) {
        return ResponseEntity.ok(tradesService.upsert(trade));
    }

    @GetMapping("/{tradeId}")
    @Operation(summary = "One trade by id")
    public ResponseEntity<ApiEnvelope<Trade>> get(@PathVariable String tradeId) {
        return ResponseEntity.ok(tradesService.get(tradeId));
    }

    @GetMapping("/{tradeId}/exists")
    @Operation(summary = "Whether the trade exists, without transferring the document")
    public ResponseEntity<Map<String, Object>> exists(@PathVariable String tradeId) {
        return ResponseEntity.ok(Map.of("trade_id", tradeId, "exists", tradesService.exists(tradeId)));
    }

    @GetMapping("/{tradeId}/price-evolution")
    @Operation(summary = "The forward walk for one trade (paged)")
    public ResponseEntity<ApiEnvelope<List<Map<String, Object>>>> priceEvolution(
            @PathVariable String tradeId,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false, name = "page_size") Integer pageSize) {
        return ResponseEntity.ok(tradesService.priceEvolution(tradeId, page, pageSize));
    }

    @PatchMapping("/{tradeId}")
    @Operation(summary = "Merge fields into a trade",
            description = "price_evolution is excluded server-side so an update cannot blank an "
                    + "existing forward walk.")
    public ResponseEntity<ApiEnvelope<Trade>> patch(@PathVariable String tradeId,
                                                    @RequestBody Map<String, Object> patch) {
        return ResponseEntity.ok(tradesService.patch(tradeId, patch));
    }

    @PostMapping("/{tradeId}/price-evolution")
    @Operation(summary = "Append one point to the forward walk")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> appendPricePoint(
            @PathVariable String tradeId, @RequestBody PricePointRequest point) {
        return ResponseEntity.ok(tradesService.appendPricePoint(tradeId, point));
    }

    @PostMapping("/{tradeId}/close")
    @Operation(summary = "Record the close")
    public ResponseEntity<ApiEnvelope<Trade>> close(@PathVariable String tradeId,
                                                    @RequestBody CloseTradeRequest request) {
        return ResponseEntity.ok(tradesService.close(tradeId, request));
    }

    @PostMapping("/bulk")
    @Operation(summary = "Upsert many trades")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> bulkUpsert(@RequestBody BulkRequest request) {
        return ResponseEntity.ok(tradesService.bulkUpsert(request));
    }

    // ============================================================
    // DELETE
    // ============================================================

    @DeleteMapping("/{tradeId}")
    @Operation(summary = "Delete a trade (soft by default)",
            description = "mode=soft|archive|hard. hard destroys the only record of a real trade "
                    + "and requires confirm=true.")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> delete(
            @PathVariable String tradeId,
            @RequestParam(required = false, defaultValue = "soft") String mode,
            @RequestParam(required = false) Boolean confirm,
            @RequestParam(required = false) String reason,
            @RequestParam(required = false, name = "allow_open") Boolean allowOpen) {
        return ResponseEntity.ok(
                tradesService.delete(tradeId, new DeleteRequest(mode, confirm, reason, allowOpen)));
    }

    @PostMapping("/{tradeId}/restore")
    @Operation(summary = "Undo a soft delete")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> restore(@PathVariable String tradeId) {
        return ResponseEntity.ok(tradesService.restore(tradeId));
    }

    @PostMapping("/bulk-delete")
    @Operation(summary = "Delete many trades under one mode")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> bulkDelete(@RequestBody BulkDeleteRequest request) {
        return ResponseEntity.ok(tradesService.bulkDelete(request));
    }

    @PostMapping("/purge")
    @Operation(summary = "Permanently remove soft-deleted trades older than a cutoff",
            description = "Requires confirm=true. Bounded per call — an unbounded purge is a "
                    + "long-running write that blocks the collection.")
    public ResponseEntity<ApiEnvelope<Map<String, Object>>> purge(
            @RequestParam(required = false, name = "older_than_days") Integer olderThanDays,
            @RequestParam(required = false) Boolean confirm) {
        return ResponseEntity.ok(tradesService.purge(olderThanDays, confirm));
    }
}
