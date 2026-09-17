package com.trading.easytradify.trades.models;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * <h1>Trade Models</h1>
 * <p>
 * Immutable contracts for the Python trades service ({@code api/trades_controller.py},
 * port 5011), which is the REST face of the MongoDB {@code easytradify.trades}
 * collection.
 * </p>
 *
 * <h2>Why these are lenient</h2>
 * <p>
 * Every record is annotated {@link JsonIgnoreProperties} with
 * {@code ignoreUnknown = true}. A stored trade carries a large, evolving
 * {@code analysis_at_open} payload — on a live document it holds 60+ top-level
 * keys — and new measurement channels are added there deliberately
 * ({@code microstructure_at_entry}, {@code strategy_family_scores},
 * {@code component_reads}). A strict binding would turn every such addition on
 * the Python side into a deserialization failure here, which is exactly the
 * kind of coupling that left this layer deprecated in the first place.
 * </p>
 *
 * <h2>The shape is a contract</h2>
 * <p>
 * {@code entry}, {@code direction} and {@code openedAt} are load-bearing on the
 * Python side: every model reads {@code entry.price} / {@code entry.stop_loss},
 * and a document without them scores {@code R = null} and is silently dropped
 * from analysis. They are modelled explicitly here rather than left inside a
 * loose map so that a missing one is visible to a Java caller too.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
public final class TradeModels {

    private TradeModels() {
    }

    // ============================================================
    // RESPONSE ENVELOPE
    // ============================================================

    /**
     * The envelope every Python trades endpoint returns, on success and failure
     * alike. {@code ok} is the discriminator; {@code error} is populated only
     * when {@code ok} is false.
     *
     * @param <T> the payload type carried in {@code data}
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ApiEnvelope<T>(
            /*
             * trades_controller.py writes this flag as "success", not "ok".
             * Without the alias Jackson found no "ok" key, defaulted the
             * primitive to false, and re-serialised EVERY successful response
             * to Angular as {"ok": false} -- which TradesApiService.unwrap()
             * correctly treats as a failure. Every trades call through the
             * full stack failed while each layer looked healthy in isolation.
             */
            @JsonAlias("success") boolean ok,
            T data,
            Map<String, Object> meta,
            ApiError error,
            String timestamp
    ) {
    }

    /**
     * The error half of the envelope. {@code code} is a stable machine-readable
     * string; {@code message} is for humans; {@code details} is free-form.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ApiError(
            String code,
            String message,
            Object details
    ) {
    }

    /**
     * Pagination metadata returned alongside a page of trades.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PageMeta(
            Integer page,
            @JsonProperty("page_size") Integer pageSize,
            Integer total,
            @JsonProperty("total_pages") Integer totalPages,
            @JsonProperty("has_next") Boolean hasNext
    ) {
    }

    // ============================================================
    // THE TRADE
    // ============================================================

    /**
     * One stored trade, in the canonical shape defined by
     * {@code ai/mt5_history.to_trade()}.
     *
     * <p>
     * {@code analysisAtOpen}, {@code analysisAtClose} and each price-evolution
     * point are intentionally {@code Map} rather than typed records: they carry
     * the full analysis payload, whose shape is owned by the Python decision
     * engine and changes as components are added. Java's job here is transport
     * and querying, not re-implementing that schema.
     * </p>
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Trade(
            @JsonProperty("trade_id") String tradeId,
            Long ticket,
            String symbol,

            /** "BUY" or "SELL" — never inferred from the price move. */
            String direction,

            /** Kept in step with {@code direction}; older rows may carry only this. */
            @JsonProperty("order_type") String orderType,

            /** "OPEN" or "CLOSED". */
            String status,

            /** The chronological key: default sort, own index, orders every walk-forward split. */
            @JsonProperty("opened_at") String openedAt,
            @JsonProperty("closed_at") String closedAt,
            @JsonProperty("created_at") String createdAt,
            @JsonProperty("updated_at") String updatedAt,
            @JsonProperty("deleted_at") String deletedAt,

            TradeEntry entry,
            @JsonProperty("close_data") TradeClose closeData,

            @JsonProperty("analysis_at_open") Map<String, Object> analysisAtOpen,
            @JsonProperty("analysis_at_close") Map<String, Object> analysisAtClose,

            @JsonProperty("price_evolution") List<Map<String, Object>> priceEvolution,
            @JsonProperty("price_evolution_count") Integer priceEvolutionCount,

            Double price,
            Double volume,
            @JsonProperty("stop_loss") Double stopLoss,
            @JsonProperty("take_profit") Double takeProfit,
            @JsonProperty("actual_risk_usd") Double actualRiskUsd,
            @JsonProperty("actual_margin") Double actualMargin,
            @JsonProperty("risk_percent_used") Double riskPercentUsed,
            Long magic,
            String comment,
            String source,

            /*
             * Every field below is declared EXPLICITLY, and that is the whole
             * point. These records are @JsonIgnoreProperties(ignoreUnknown =
             * true), so a field the Python side writes but this record does not
             * name is dropped on the way through without an error -- it simply
             * never reaches Angular. That is how leverage and the cost fields
             * would have gone missing even after the store started writing them.
             */

            /** Account leverage (200, 300, 500). Trades come from three accounts. */
            Integer leverage,

            /** The MT5 account the trade was placed on. */
            TradeAccount account,

            /** Spread at entry, in pips. */
            @JsonProperty("spread_at_entry") Double spreadAtEntry,

            /** order_tick | live_tick | tick_history | analysis -- how exact it is. */
            @JsonProperty("spread_at_entry_source") String spreadAtEntrySource,

            /** Reward / risk from the EXECUTED entry, stop and target. */
            @JsonProperty("risk_reward_ratio") Double riskRewardRatio
    ) {
    }

    /**
     * What was known at entry. Every AI model reads {@code price} and
     * {@code stopLoss} from here to compute R — a trade missing either is
     * dropped from analysis without an error.
     */
    /**
     * The MT5 account a trade was placed on, captured live at open.
     * Recorded on trades opened after this field was introduced; older trades
     * carry {@code leverage} only.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record TradeAccount(
            Long login,
            String server,
            Integer leverage,
            String currency,
            String company
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record TradeEntry(
            Double price,
            Double volume,
            @JsonProperty("stop_loss") Double stopLoss,
            @JsonProperty("take_profit") Double takeProfit
    ) {
    }

    /**
     * The outcome. {@code profitUsd} is the broker's realised P/L for the round
     * trip — including swap and commission on both legs — not a figure derived
     * from prices.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record TradeClose(
            @JsonProperty("close_price") Double closePrice,
            @JsonProperty("close_reason") String closeReason,
            @JsonProperty("profit_usd") Double profitUsd,
            @JsonProperty("profit_percent") Double profitPercent,
            @JsonProperty("is_winning") Boolean isWinning,
            @JsonProperty("duration_seconds") Long durationSeconds,
            @JsonProperty("order_type") String orderType,
            Double sl,
            Double tp,
            Double volume,
            @JsonProperty("price_open") Double priceOpen,

            /** Spread at the close, in pips. Null when no tick existed near the close. */
            @JsonProperty("exit_spread") Double exitSpread,

            /** tick_at_deal | tick_at_detection | tick_history. */
            @JsonProperty("exit_spread_source") String exitSpreadSource,

            /**
             * Fill versus the stop/target that triggered the close, in pips.
             * Positive is worse than the level. Null for manual or EA closes,
             * which had no requested level -- not 0.0, which would claim a
             * perfect fill.
             */
            @JsonProperty("exit_slippage") Double exitSlippage
    ) {
    }

    // ============================================================
    // REQUESTS
    // ============================================================

    /**
     * Query parameters for listing trades. All fields are optional; the Python
     * side bounds and whitelists every one of them, so an out-of-range page size
     * is clamped rather than rejected.
     */
    public record TradeQuery(
            Integer page,
            Integer pageSize,
            String symbol,
            String status,
            String direction,
            String sortBy,
            String sortDir,
            String openedAfter,
            String openedBefore,
            Boolean includeDeleted
    ) {
        /** A query with every filter unset. */
        public static TradeQuery empty() {
            return new TradeQuery(null, null, null, null, null, null, null, null, null, null);
        }
    }

    /**
     * A price-evolution point appended to an open trade.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PricePointRequest(
            Double price,
            @JsonProperty("profit_usd") Double profitUsd,
            @JsonProperty("profit_percent") Double profitPercent,
            @JsonProperty("distance_from_entry_pips") Double distanceFromEntryPips,
            Map<String, Object> analysis,
            @JsonProperty("risk_state") Map<String, Object> riskState,
            Map<String, Object> microstructure
    ) {
    }

    /**
     * Closing payload. Mirrors {@link TradeClose}; the Python side fills
     * anything omitted from the broker's own deal record where it can, and
     * leaves the trade unsaved rather than fabricating a close it cannot
     * reconstruct.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record CloseTradeRequest(
            @JsonProperty("close_price") Double closePrice,
            @JsonProperty("close_reason") String closeReason,
            @JsonProperty("profit_usd") Double profitUsd,
            Double volume,
            @JsonProperty("analysis_at_close") Map<String, Object> analysisAtClose
    ) {
    }

    /**
     * Delete request. {@code mode} is one of {@code soft} (default),
     * {@code archive} or {@code hard}; {@code hard} additionally requires
     * {@code confirm = true} on the Python side, because it destroys the only
     * record of a real trade.
     */
    public record DeleteRequest(
            String mode,
            Boolean confirm,
            String reason,
            Boolean allowOpen
    ) {
    }

    /**
     * Bulk write. The Python endpoint applies these as upserts keyed on
     * {@code trade_id}, so a retry converges on one record per trade.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record BulkRequest(
            List<Map<String, Object>> trades
    ) {
    }

    /**
     * Bulk delete by trade id.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record BulkDeleteRequest(
            @JsonProperty("trade_ids") List<String> tradeIds,
            String mode,
            Boolean confirm
    ) {
    }
}
