package com.trading.easytradify.trades.client;

import com.trading.easytradify.trades.models.TradeModels.*;

import java.util.List;
import java.util.Map;

/**
 * <h1>Python Trades Service Client</h1>
 * <p>
 * Abstraction over the Python trades service ({@code api/trades_controller.py},
 * port <b>5011</b>), which is the REST face of the MongoDB
 * {@code easytradify.trades} collection. Each method maps to exactly one Python
 * endpoint under {@code /api/v1/trades}.
 * </p>
 *
 * <h2>Why this exists</h2>
 * <p>
 * Trades moved from Firestore to MongoDB: a Firestore document is capped at
 * 1 MiB and a trade carrying a full minute-by-minute forward walk is several
 * megabytes, so {@code price_evolution} stopped accepting points after two.
 * MongoDB holds a whole trade as one document. The Python service owns the
 * collection outright — {@code core/mongo/trades_service.py} is the only module
 * that touches it — and this client is the Java platform's sole route in.
 * </p>
 *
 * <h2>What this client must not do</h2>
 * <p>
 * It must not connect to MongoDB directly. Every guarantee the collection
 * relies on lives on the Python side: the unique {@code trade_id} index that
 * keeps a retry from producing two contradictory records, the idempotent
 * upsert, the {@code $push} that grows {@code price_evolution} without ever
 * blanking it, and the delete gating that makes a hard delete require explicit
 * confirmation. A second writer would bypass all of it.
 * </p>
 *
 * <h2>Base URL and port</h2>
 * <p>
 * All endpoints are prefixed with {@code /api/v1/trades}; the Python service
 * listens on port 5011.
 * </p>
 *
 * <h2>Error handling</h2>
 * <p>
 * Errors are extracted from the Python envelope and wrapped in
 * {@link com.trading.easytradify.common.exception.TradingException}.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see DefaultPythonTradesClient
 */
public interface PythonTradesClient {

    // ============================================================
    // READ
    // ============================================================

    /**
     * <h3>GET /api/v1/trades</h3>
     * A bounded, sorted page of trades. Every filter and sort key is whitelisted
     * server-side, so an unknown field is rejected rather than silently ignored.
     *
     * @param query filters, paging and sort; {@link TradeQuery#empty()} for defaults
     * @return the page, with pagination in the envelope's {@code meta}
     */
    ApiEnvelope<List<Trade>> listTrades(TradeQuery query);

    /** POST /api/v1/trades/query -- filters in a JSON body, forwarded as-is. */
    ApiEnvelope<List<Trade>> queryTrades(Map<String, Object> body);

    /** GET /api/v1/trades/filters -- every accepted filter with live values. */
    ApiEnvelope<Map<String, Object>> filterCatalog();

    /**
     * <h3>GET /api/v1/trades/{tradeId}</h3>
     * One trade by id ({@code "trade_{ticket}"}).
     */
    ApiEnvelope<Trade> getTrade(String tradeId);

    /**
     * <h3>GET /api/v1/trades/{tradeId}/exists</h3>
     * Whether the trade exists, without transferring the document — a stored
     * trade can be megabytes, so this is the cheap check.
     */
    ApiEnvelope<Map<String, Object>> exists(String tradeId);

    /**
     * <h3>GET /api/v1/trades/{tradeId}/price-evolution</h3>
     * The forward walk for one trade. Paged, because this is the array that made
     * Firestore unusable.
     */
    ApiEnvelope<List<Map<String, Object>>> getPriceEvolution(String tradeId, Integer page, Integer pageSize);

    /**
     * <h3>GET /api/v1/trades/search</h3>
     * Free-text search across the whitelisted searchable fields
     * ({@code symbol}, {@code close_reason}, {@code comment}, {@code trade_id}).
     */
    ApiEnvelope<List<Trade>> search(String q, Integer page, Integer pageSize);

    /**
     * <h3>GET /api/v1/trades/count</h3>
     * Matching document count for the supplied filters.
     */
    ApiEnvelope<Map<String, Object>> count(TradeQuery query);

    /**
     * <h3>GET /api/v1/trades/distinct/{field}</h3>
     * Distinct values of one whitelisted field — the honest way to populate a
     * symbol or status filter without scanning the collection client-side.
     */
    ApiEnvelope<List<Object>> distinct(String field);

    // ============================================================
    // STATISTICS
    // ============================================================

    /**
     * <h3>GET /api/v1/trades/stats</h3>
     * Headline counts: open, closed, by status.
     */
    ApiEnvelope<Map<String, Object>> stats();

    /**
     * <h3>GET /api/v1/trades/stats/performance</h3>
     * Win rate, expectancy and realised P/L.
     *
     * <p>
     * Read these with the collection's provenance in mind. Profit is the
     * broker's realised figure, but trades collected under the loosened
     * data-collection gates do not represent the strategy, and a risk unit of
     * one or two pips makes R enormously noisy — a mean R can sit above +9
     * while the median is negative.
     * </p>
     */
    ApiEnvelope<Map<String, Object>> performance(String from, String to, String symbol);

    /**
     * <h3>GET /api/v1/trades/stats/by-symbol</h3>
     * The same performance breakdown, grouped by symbol. An edge carried by one
     * instrument is that instrument's, not the strategy's.
     */
    ApiEnvelope<List<Map<String, Object>>> statsBySymbol(String from, String to);

    /**
     * <h3>GET /api/v1/trades/stats/timeseries</h3>
     * Performance bucketed over time, for drift and regime inspection.
     */
    ApiEnvelope<List<Map<String, Object>>> statsTimeseries(String interval, String from, String to);

    // ============================================================
    // DIAGNOSTICS
    // ============================================================

    /**
     * <h3>GET /api/v1/trades/health</h3>
     * Whether the Mongo <em>server</em> answered — not merely whether a client
     * object exists. Holding a {@code MongoClient} proves nothing; pymongo
     * builds one without contacting anything.
     */
    ApiEnvelope<Map<String, Object>> health();

    /**
     * <h3>GET /api/v1/trades/diagnostics</h3>
     * Scans stored trades for shape defects — the failure mode that matters
     * here is a trade recorded perfectly and then silently skipped by every
     * model because {@code entry} or {@code opened_at} is missing.
     */
    ApiEnvelope<Map<String, Object>> diagnostics(Integer limit, Boolean onlyOpen, Integer sinceHours);

    /**
     * <h3>POST /api/v1/trades/diagnostics/self-check</h3>
     * Runs the service's own self-check, which plants a known answer and
     * requires recovery — including the negative case, because a check that
     * cannot fail is indistinguishable from a stub returning success.
     */
    ApiEnvelope<Map<String, Object>> selfCheck();

    // ============================================================
    // WRITE
    // ============================================================

    /**
     * <h3>POST /api/v1/trades</h3>
     * Upsert one trade, keyed on {@code trade_id}. Idempotent: a network timeout
     * followed by a retry converges on one record.
     */
    ApiEnvelope<Trade> upsertTrade(Map<String, Object> trade);

    /**
     * <h3>PATCH /api/v1/trades/{tradeId}</h3>
     * Merge fields into an existing trade. {@code price_evolution} is excluded
     * server-side so an update can never blank an existing forward walk.
     */
    ApiEnvelope<Trade> patchTrade(String tradeId, Map<String, Object> patch);

    /**
     * <h3>POST /api/v1/trades/{tradeId}/price-evolution</h3>
     * Append one point to the forward walk. {@code $push}, so this is O(1) and
     * atomic however many points the trade already holds.
     */
    ApiEnvelope<Map<String, Object>> appendPricePoint(String tradeId, PricePointRequest point);

    /**
     * <h3>POST /api/v1/trades/{tradeId}/close</h3>
     * Record the close.
     */
    ApiEnvelope<Trade> closeTrade(String tradeId, CloseTradeRequest request);

    /**
     * <h3>POST /api/v1/trades/bulk</h3>
     * Upsert many trades in one call.
     */
    ApiEnvelope<Map<String, Object>> bulkUpsert(BulkRequest request);

    // ============================================================
    // DELETE
    // ============================================================

    /**
     * <h3>DELETE /api/v1/trades/{tradeId}</h3>
     * Soft by default. {@code archive} copies to the archive collection before
     * removing from the hot one — in that order, because the reverse loses the
     * trade if the second step fails. {@code hard} destroys the only record of a
     * real trade and requires {@code confirm = true}.
     */
    ApiEnvelope<Map<String, Object>> deleteTrade(String tradeId, DeleteRequest request);

    /**
     * <h3>POST /api/v1/trades/{tradeId}/restore</h3>
     * Undo a soft delete.
     */
    ApiEnvelope<Map<String, Object>> restoreTrade(String tradeId);

    /**
     * <h3>POST /api/v1/trades/bulk-delete</h3>
     * Delete many trades under one mode.
     */
    ApiEnvelope<Map<String, Object>> bulkDelete(BulkDeleteRequest request);

    /**
     * <h3>POST /api/v1/trades/purge</h3>
     * Permanently removes soft-deleted trades older than a cutoff. Bounded per
     * call: an unbounded purge is a long-running write that blocks the
     * collection.
     */
    ApiEnvelope<Map<String, Object>> purge(Integer olderThanDays, Boolean confirm);
}
