package com.trading.easytradify.trades.services;

import com.trading.easytradify.trades.models.TradeModels.*;

import java.util.List;
import java.util.Map;

/**
 * <h1>Trades Service</h1>
 * <p>
 * The Java platform's view of the trade store. Wraps
 * {@link com.trading.easytradify.trades.client.PythonTradesClient} and adds the
 * validation that belongs on this side of the boundary.
 * </p>
 *
 * <h2>What this layer adds over the client</h2>
 * <ul>
 *   <li><b>Destructive-operation gating.</b> A hard delete or a purge destroys
 *       the only record of a real trade. The Python side requires explicit
 *       confirmation; this layer refuses to forward an unconfirmed one at all,
 *       so an accidental call fails locally instead of relying on the remote
 *       check.</li>
 *   <li><b>Shape verification.</b> {@link #verifyShape} answers the question
 *       that actually matters about this collection: are the stored trades in
 *       a form the AI layer can read? A trade missing {@code entry.price},
 *       {@code entry.stop_loss} or {@code direction} is dropped silently by
 *       every model, so "rows are accumulating" is not evidence that
 *       collection is working.</li>
 * </ul>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see TradesServiceImpl
 */
public interface TradesService {

    // ---------- read ----------

    /** A page of trades. */
    ApiEnvelope<List<Trade>> list(TradeQuery query);

    /**
     * Filter trades with a JSON body. The response {@code meta} carries
     * pagination, the applied filters and a win/loss summary over the WHOLE
     * filtered set, broken down by leverage.
     */
    ApiEnvelope<List<Trade>> query(Map<String, Object> body);

    /** Every filter {@link #query} accepts, with the values present in the store. */
    ApiEnvelope<Map<String, Object>> filters();

    /** One trade by id. */
    ApiEnvelope<Trade> get(String tradeId);

    /** Whether a trade exists, without transferring the document. */
    boolean exists(String tradeId);

    /** The forward walk for one trade. */
    ApiEnvelope<List<Map<String, Object>>> priceEvolution(String tradeId, Integer page, Integer pageSize);

    /** Free-text search over the whitelisted searchable fields. */
    ApiEnvelope<List<Trade>> search(String q, Integer page, Integer pageSize);

    /** Matching document count. */
    ApiEnvelope<Map<String, Object>> count(TradeQuery query);

    /** Distinct values of one whitelisted field. */
    ApiEnvelope<List<Object>> distinct(String field);

    // ---------- statistics ----------

    ApiEnvelope<Map<String, Object>> stats();

    ApiEnvelope<Map<String, Object>> performance(String from, String to, String symbol);

    ApiEnvelope<List<Map<String, Object>>> statsBySymbol(String from, String to);

    ApiEnvelope<List<Map<String, Object>>> statsTimeseries(String interval, String from, String to);

    // ---------- diagnostics ----------

    /** Whether the Mongo server answered. */
    ApiEnvelope<Map<String, Object>> health();

    ApiEnvelope<Map<String, Object>> diagnostics(Integer limit, Boolean onlyOpen, Integer sinceHours);

    ApiEnvelope<Map<String, Object>> selfCheck();

    /**
     * Samples stored trades and reports how many carry the fields the AI layer
     * requires: {@code entry.price}, {@code entry.stop_loss}, {@code direction}
     * and {@code opened_at}.
     *
     * <p>
     * This exists because the failure it detects is invisible everywhere else.
     * The live writer once emitted only flat {@code price} / {@code stop_loss}
     * and no {@code entry} sub-document; every trade it recorded returned
     * {@code R = null} and was skipped by every model, while counts rose and
     * the pipeline looked healthy. Measured at the time: R computable on
     * 220/250 trades read from MT5 history and 0/2 written live.
     * </p>
     *
     * @param sampleSize how many recent trades to inspect
     * @return per-field counts plus the ids of any unusable trades
     */
    Map<String, Object> verifyShape(int sampleSize);

    // ---------- write ----------

    ApiEnvelope<Trade> upsert(Map<String, Object> trade);

    ApiEnvelope<Trade> patch(String tradeId, Map<String, Object> patch);

    ApiEnvelope<Map<String, Object>> appendPricePoint(String tradeId, PricePointRequest point);

    ApiEnvelope<Trade> close(String tradeId, CloseTradeRequest request);

    ApiEnvelope<Map<String, Object>> bulkUpsert(BulkRequest request);

    // ---------- delete ----------

    /**
     * Deletes a trade. Soft by default.
     *
     * @throws com.trading.easytradify.common.exception.TradingException
     *         if {@code mode} is {@code hard} without {@code confirm = true}
     */
    ApiEnvelope<Map<String, Object>> delete(String tradeId, DeleteRequest request);

    ApiEnvelope<Map<String, Object>> restore(String tradeId);

    ApiEnvelope<Map<String, Object>> bulkDelete(BulkDeleteRequest request);

    /**
     * Purges soft-deleted trades older than a cutoff.
     *
     * @throws com.trading.easytradify.common.exception.TradingException
     *         unless {@code confirm} is true
     */
    ApiEnvelope<Map<String, Object>> purge(Integer olderThanDays, Boolean confirm);
}
