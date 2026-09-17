package com.trading.easytradify.trades.services;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.TradingException;
import com.trading.easytradify.trades.client.PythonTradesClient;
import com.trading.easytradify.trades.models.TradeModels.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * <h1>Trades Service Implementation</h1>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see TradesService
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class TradesServiceImpl implements TradesService {

    private final PythonTradesClient client;

    /** Cap on {@link #verifyShape} sampling, so a diagnostic cannot pull the collection. */
    private static final int MAX_SHAPE_SAMPLE = 500;

    // ============================================================
    // READ
    // ============================================================

    @Override
    public ApiEnvelope<List<Trade>> list(TradeQuery query) {
        return client.listTrades(query == null ? TradeQuery.empty() : query);
    }

    @Override
    public ApiEnvelope<List<Trade>> query(Map<String, Object> body) {
        return client.queryTrades(body);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> filters() {
        return client.filterCatalog();
    }

    @Override
    public ApiEnvelope<Trade> get(String tradeId) {
        requireTradeId(tradeId);
        return client.getTrade(tradeId);
    }

    @Override
    public boolean exists(String tradeId) {
        requireTradeId(tradeId);
        Map<String, Object> data = client.exists(tradeId).data();
        return data != null && Boolean.TRUE.equals(data.get("exists"));
    }

    @Override
    public ApiEnvelope<List<Map<String, Object>>> priceEvolution(String tradeId, Integer page, Integer pageSize) {
        requireTradeId(tradeId);
        return client.getPriceEvolution(tradeId, page, pageSize);
    }

    @Override
    public ApiEnvelope<List<Trade>> search(String q, Integer page, Integer pageSize) {
        if (q == null || q.isBlank()) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER,
                    "search requires a non-empty query");
        }
        return client.search(q, page, pageSize);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> count(TradeQuery query) {
        return client.count(query == null ? TradeQuery.empty() : query);
    }

    @Override
    public ApiEnvelope<List<Object>> distinct(String field) {
        if (field == null || field.isBlank()) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER,
                    "distinct requires a field name");
        }
        return client.distinct(field);
    }

    // ============================================================
    // STATISTICS
    // ============================================================

    @Override
    public ApiEnvelope<Map<String, Object>> stats() {
        return client.stats();
    }

    @Override
    public ApiEnvelope<Map<String, Object>> performance(String from, String to, String symbol) {
        return client.performance(from, to, symbol);
    }

    @Override
    public ApiEnvelope<List<Map<String, Object>>> statsBySymbol(String from, String to) {
        return client.statsBySymbol(from, to);
    }

    @Override
    public ApiEnvelope<List<Map<String, Object>>> statsTimeseries(String interval, String from, String to) {
        return client.statsTimeseries(interval, from, to);
    }

    // ============================================================
    // DIAGNOSTICS
    // ============================================================

    @Override
    public ApiEnvelope<Map<String, Object>> health() {
        return client.health();
    }

    @Override
    public ApiEnvelope<Map<String, Object>> diagnostics(Integer limit, Boolean onlyOpen, Integer sinceHours) {
        return client.diagnostics(limit, onlyOpen, sinceHours);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> selfCheck() {
        return client.selfCheck();
    }

    @Override
    public Map<String, Object> verifyShape(int sampleSize) {
        int size = Math.min(Math.max(sampleSize, 1), MAX_SHAPE_SAMPLE);
        TradeQuery q = new TradeQuery(1, size, null, null, null, "opened_at", "desc", null, null, null);

        List<Trade> trades = list(q).data();
        if (trades == null) trades = List.of();

        int withEntryPrice = 0, withEntryStop = 0, withDirection = 0, withOpenedAt = 0, scoreable = 0;
        List<String> unusable = new ArrayList<>();

        for (Trade t : trades) {
            boolean hasPrice = t.entry() != null && t.entry().price() != null;
            boolean hasStop = t.entry() != null && t.entry().stopLoss() != null;
            boolean hasDir = t.direction() != null && !t.direction().isBlank();
            boolean hasOpened = t.openedAt() != null && !t.openedAt().isBlank();

            if (hasPrice) withEntryPrice++;
            if (hasStop) withEntryStop++;
            if (hasDir) withDirection++;
            if (hasOpened) withOpenedAt++;

            // An R can only be computed with an entry, a stop and a direction.
            // A closed trade additionally needs a close price.
            boolean closed = "CLOSED".equalsIgnoreCase(String.valueOf(t.status()));
            boolean hasClose = t.closeData() != null && t.closeData().closePrice() != null;
            if (hasPrice && hasStop && hasDir && (!closed || hasClose)) {
                scoreable++;
            } else {
                unusable.add(t.tradeId());
            }
        }

        Map<String, Object> report = new LinkedHashMap<>();
        report.put("sampled", trades.size());
        report.put("with_entry_price", withEntryPrice);
        report.put("with_entry_stop_loss", withEntryStop);
        report.put("with_direction", withDirection);
        report.put("with_opened_at", withOpenedAt);
        report.put("scoreable_by_ai_layer", scoreable);
        report.put("unusable_trade_ids", unusable);
        report.put("ok", !trades.isEmpty() && unusable.isEmpty());
        report.put("note", "A trade missing entry.price, entry.stop_loss or direction is "
                + "skipped silently by every AI model — rows accumulating is not evidence "
                + "that collection is working.");

        if (!unusable.isEmpty()) {
            log.warn("Shape check: {} of {} sampled trades are unusable by the AI layer",
                    unusable.size(), trades.size());
        }
        return report;
    }

    // ============================================================
    // WRITE
    // ============================================================

    @Override
    public ApiEnvelope<Trade> upsert(Map<String, Object> trade) {
        if (trade == null || trade.isEmpty()) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER, "trade body is required");
        }
        if (trade.get("ticket") == null && trade.get("trade_id") == null) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER,
                    "trade requires a ticket or trade_id — it is the upsert key, and without "
                            + "it a retry would create a second record for one position");
        }
        return client.upsertTrade(trade);
    }

    @Override
    public ApiEnvelope<Trade> patch(String tradeId, Map<String, Object> patch) {
        requireTradeId(tradeId);
        if (patch == null || patch.isEmpty()) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER, "patch body is required");
        }
        return client.patchTrade(tradeId, patch);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> appendPricePoint(String tradeId, PricePointRequest point) {
        requireTradeId(tradeId);
        if (point == null || point.price() == null) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER,
                    "a price-evolution point requires a price");
        }
        return client.appendPricePoint(tradeId, point);
    }

    @Override
    public ApiEnvelope<Trade> close(String tradeId, CloseTradeRequest request) {
        requireTradeId(tradeId);
        if (request == null) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER, "close body is required");
        }
        return client.closeTrade(tradeId, request);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> bulkUpsert(BulkRequest request) {
        if (request == null || request.trades() == null || request.trades().isEmpty()) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER, "bulk requires at least one trade");
        }
        return client.bulkUpsert(request);
    }

    // ============================================================
    // DELETE
    // ============================================================

    @Override
    public ApiEnvelope<Map<String, Object>> delete(String tradeId, DeleteRequest request) {
        requireTradeId(tradeId);
        DeleteRequest req = request == null
                ? new DeleteRequest("soft", null, null, null)
                : request;
        requireConfirmedIfHard(req.mode(), req.confirm());
        return client.deleteTrade(tradeId, req);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> restore(String tradeId) {
        requireTradeId(tradeId);
        return client.restoreTrade(tradeId);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> bulkDelete(BulkDeleteRequest request) {
        if (request == null || request.tradeIds() == null || request.tradeIds().isEmpty()) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER,
                    "bulk-delete requires at least one trade id");
        }
        requireConfirmedIfHard(request.mode(), request.confirm());
        return client.bulkDelete(request);
    }

    @Override
    public ApiEnvelope<Map<String, Object>> purge(Integer olderThanDays, Boolean confirm) {
        if (!Boolean.TRUE.equals(confirm)) {
            throw new TradingException(ErrorCodes.TRADE_DELETE_NOT_CONFIRMED,
                    "purge permanently removes soft-deleted trades and requires confirm=true");
        }
        return client.purge(olderThanDays, true);
    }

    // ============================================================
    // GUARDS
    // ============================================================

    private void requireTradeId(String tradeId) {
        if (tradeId == null || tradeId.isBlank()) {
            throw new TradingException(ErrorCodes.INVALID_PARAMETER, "tradeId is required");
        }
    }

    /**
     * A hard delete destroys the only record of a real trade and cannot be
     * undone. The Python side gates it too; this refuses locally so an
     * accidental call never leaves the process.
     */
    private void requireConfirmedIfHard(String mode, Boolean confirm) {
        if ("hard".equalsIgnoreCase(String.valueOf(mode)) && !Boolean.TRUE.equals(confirm)) {
            throw new TradingException(ErrorCodes.TRADE_DELETE_NOT_CONFIRMED,
                    "hard delete destroys the only record of a real trade and requires confirm=true; "
                            + "use mode=soft or mode=archive instead");
        }
    }
}
