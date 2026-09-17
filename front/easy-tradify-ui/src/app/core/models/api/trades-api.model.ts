/**
 * The stored trade, as `easytradify.trades` holds it.
 *
 * Typed from the documents actually in the collection, not from a schema: the
 * previous version of this file declared close fields as `price` / `profit` /
 * `reason`, while the store writes `close_price` / `profit_usd` /
 * `close_reason`. Every close column would have rendered empty. Field names are
 * the Mongo ones, kept snake_case on the way in — this is the shape the AI
 * layer reads, and two spellings for one document is how a field ends up
 * written under one name and read under the other.
 */

/**
 * Every response from the trades service is wrapped in this.
 *
 * `ok` is what the Java layer emits. The Python service underneath writes the
 * same flag as `success`; both are declared so a direct call cannot read a
 * successful response as a failure.
 */
export interface TradesEnvelope<T> {
  ok?: boolean;
  success?: boolean;
  data: T | null;
  meta?: TradesMeta | null;
  error?: TradesApiError | null;
  timestamp?: string;
}

export interface TradesApiError {
  /** Stable, machine-readable. Switch on this, not on `message`. */
  code: string;
  message: string;
  details?: unknown;
}

export interface TradesMeta {
  pagination?: TradesPagination;
  sort?: { sortField: TradeSortField; sortDirection: 'ASC' | 'DESC' };
  appliedFilters?: Partial<TradeQueryRequest>;
  summary?: TradeQuerySummary | null;
  [key: string]: unknown;
}

export interface TradesPagination {
  page: number;
  size: number;
  total: number;
  pages: number;
  hasNext: boolean;
  hasPrevious: boolean;
}

// ====================================================================
// THE DOCUMENT
// ====================================================================

/**
 * What was known at entry.
 *
 * `price` and `stop_loss` here are what every R calculation is built on — a
 * trade missing either cannot be scored and is dropped from research samples
 * rather than defaulted, because a zero stop produces an infinite R.
 */
export interface TradeEntryWire {
  price?: number | null;
  volume?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
}

/** The MT5 account the trade was placed on, captured live at open. */
export interface TradeAccountWire {
  login?: number | null;
  server?: string | null;
  leverage?: number | null;
  currency?: string | null;
  company?: string | null;
}

export type SpreadSource = 'order_tick' | 'live_tick' | 'tick_history' | 'analysis';
export type ExitSpreadSource = 'tick_at_deal' | 'tick_at_detection' | 'tick_history';

export interface TradeCloseWire {
  close_price?: number | null;
  close_reason?: string | null;
  /** The measured close profit. Outcome (win/loss) is derived from this. */
  profit_usd?: number | null;
  profit_percent?: number | null;
  duration_seconds?: number | null;
  order_type?: string | null;
  price_open?: number | null;
  sl?: number | null;
  tp?: number | null;
  volume?: number | null;

  /** Spread at the close, in pips. Null when no tick existed near the close. */
  exit_spread?: number | null;
  exit_spread_source?: ExitSpreadSource | null;

  /**
   * Fill versus the stop or target that triggered the close, in pips.
   * Positive = worse than the level. Null for a manual or EA close: there was
   * no requested level to slip from, and 0 would claim a perfect fill.
   */
  exit_slippage?: number | null;
}

export interface TradeWire {
  trade_id: string;
  ticket?: number | null;
  symbol?: string | null;

  /**
   * "BUY" or "SELL", as recorded at entry. Never derive this from whether price
   * moved up or down — that inference mislabelled trades everywhere it
   * appeared; direction is a fact about the order, not about the outcome.
   */
  direction?: string | null;
  order_type?: string | null;

  status?: 'OPEN' | 'CLOSED' | string | null;

  /** Naive UTC ISO string, e.g. "2026-09-10T02:11:50.362594". */
  opened_at?: string | null;
  closed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  deleted_at?: string | null;

  /**
   * Account leverage: 200, 300 or 500. Trades come from three MT5 accounts,
   * and at a fixed margin a higher leverage means a larger lot and a tighter
   * stop for the same dollar risk.
   */
  leverage?: number | null;
  account?: TradeAccountWire | null;

  /** Spread paid at entry, in pips. */
  spread_at_entry?: number | null;
  /** How exact `spread_at_entry` is — order_tick is exact, analysis is seconds early. */
  spread_at_entry_source?: SpreadSource | null;

  /** Reward / risk from the EXECUTED entry, stop and target — not the analysis estimate. */
  risk_reward_ratio?: number | null;

  entry?: TradeEntryWire | null;
  close_data?: TradeCloseWire | null;

  analysis_at_open?: Record<string, unknown> | null;
  analysis_at_close?: Record<string, unknown> | null;

  price_evolution?: Record<string, unknown>[] | null;
  price_evolution_count?: number | null;

  price?: number | null;
  volume?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;

  /**
   * The dollar risk recorded at entry.
   *
   * Read with care on older rows. For a long stretch this was written as
   * `target_risk * lot` rather than measured — 4.00 x 0.34 stored as 1.34 on a
   * EURUSD position whose real risk was 4.08 — because the sizer discarded
   * MT5's answer whenever it came back negative, which for a stop-loss is
   * always. Rows written before that fix carry the arithmetic, not the risk.
   */
  actual_risk_usd?: number | null;
  actual_margin?: number | null;
  risk_percent_used?: number | null;

  magic?: number | null;
  comment?: string | null;
  source?: string | null;
}

// ====================================================================
// THE QUERY BODY  (POST /api/v1/trades/query)
// ====================================================================

export type TradeOutcome = 'WIN' | 'LOSS' | 'BREAKEVEN' | 'UNSCORED';

export type TradeSortField =
  | 'openedAt'
  | 'closedAt'
  | 'symbol'
  | 'status'
  | 'direction'
  | 'profitUsd'
  | 'volume'
  | 'durationSeconds'
  | 'leverage';

export interface NumberRange {
  min?: number;
  max?: number;
}

/** A single value or a list; a list means "any of". */
type OneOrMany<T> = T | T[];

/**
 * Filters for POST /query, named to match the platform's
 * PaginationAndFilteringDto so every layer passes it through unchanged.
 *
 * The server REJECTS unknown keys with a 400. That is deliberate — a mistyped
 * filter that was silently dropped would return every trade and look like a
 * working filter — so this interface is the place to add a field, not a cast.
 */
export interface TradeQueryRequest {
  page?: number;
  size?: number;
  sortField?: TradeSortField;
  sortDirection?: 'ASC' | 'DESC';

  status?: OneOrMany<'OPEN' | 'CLOSED'>;
  /** Scored from the measured close profit. UNSCORED = closed with no profit recorded. */
  outcome?: OneOrMany<TradeOutcome>;
  leverage?: OneOrMany<number>;
  symbol?: OneOrMany<string>;
  direction?: OneOrMany<'BUY' | 'SELL'>;
  closeReason?: OneOrMany<string>;
  ticket?: OneOrMany<number>;
  tradeId?: OneOrMany<string>;

  profitUsd?: NumberRange;
  profitPercent?: NumberRange;
  volume?: NumberRange;
  durationSeconds?: NumberRange;
  exitSlippage?: NumberRange;
  exitSpread?: NumberRange;

  /** ISO-8601. */
  openedFrom?: string;
  openedTo?: string;
  closedFrom?: string;
  closedTo?: string;

  search?: string;
  includeDeleted?: boolean;
  includeHeavy?: boolean;
  /** Summary over the whole filtered set. Defaults to true server-side. */
  withSummary?: boolean;
  fields?: string[];
}

// ====================================================================
// SUMMARY
// ====================================================================

export interface TradeSummaryBucket {
  trades: number;
  open: number;
  closed: number;
  /** Closed trades WITH a recorded profit — the denominator of the win rate. */
  scored: number;
  unscored: number;
  wins: number;
  losses: number;
  breakeven: number;
  /** wins / scored, as a percentage. Null when nothing is scored. */
  winRate: number | null;
  netProfit: number;
  avgProfit: number | null;
  avgWin: number | null;
  avgLoss: number | null;
  /** Null when there are no losses — never infinity. */
  profitFactor: number | null;
  /**
   * Fewer than 30 scored trades. Render the flag next to the win rate: a 0%
   * win rate on three trades is a small sample, not a verdict on leverage.
   */
  smallSample: boolean;
}

export interface TradeQuerySummary {
  available: boolean;
  overall?: TradeSummaryBucket;
  byLeverage?: (TradeSummaryBucket & { leverage: number | null })[];
  error?: string;
}

// ====================================================================
// FILTER CATALOG  (GET /api/v1/trades/filters)
// ====================================================================

export interface FilterValueCount<T = string | number> {
  value: T;
  count: number;
}

export interface EnumFilter<T = string | number> {
  type: 'enum';
  values: FilterValueCount<T>[];
  note?: string;
}

export interface RangeFilter {
  type: 'range';
  min?: number | null;
  max?: number | null;
}

export interface DateFilter {
  type: 'datetime';
  earliest?: string | null;
  latest?: string | null;
}

export interface TradeFilterCatalog {
  filters: {
    status: EnumFilter<string>;
    outcome: EnumFilter<TradeOutcome>;
    leverage: EnumFilter<number>;
    symbol: EnumFilter<string>;
    direction: EnumFilter<string>;
    closeReason: EnumFilter<string>;
    profitUsd: RangeFilter;
    volume: RangeFilter;
    durationSeconds: RangeFilter;
    profitPercent: RangeFilter;
    exitSlippage: RangeFilter;
    exitSpread: RangeFilter;
    openedFrom: DateFilter;
    openedTo: DateFilter;
    closedFrom: DateFilter;
    closedTo: DateFilter;
    ticket: { type: 'list' };
    tradeId: { type: 'list' };
    search: { type: 'text'; note?: string };
  };
  sortFields: TradeSortField[];
  sortDirections: ('ASC' | 'DESC')[];
  maxPageSize: number;
}

/** @deprecated GET query parameters. Prefer TradeQueryRequest via POST /query. */
export interface TradesQuery {
  symbol?: string;
  status?: string;
  direction?: string;
  limit?: number;
  offset?: number;
  since?: string;
  until?: string;
}

export interface TradeStats {
  total?: number;
  open?: number;
  closed?: number;
  win_rate?: number;
  net_profit?: number;
  [key: string]: unknown;
}
