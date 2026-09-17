/**
 * Wire shapes for /api/v1/monitor/**, typed from the Java records in
 * monitor/models/ rather than from the Angular view models.
 *
 * They are kept separate from `monitor.model.ts` on purpose. The backend speaks
 * in `lastScan` (an ISO string) and `activePositions`; the UI thinks in
 * `lastRefreshAt` (an epoch) and `openPositions`. Mapping in one place means a
 * field rename on either side is a compile error here instead of an
 * `undefined` rendered as "NaN" three components away.
 */

export interface MonitorStatusWire {
  success: boolean;
  running: boolean;
  /** ISO-8601, or null before the first scan completes. */
  lastScan?: string | null;
  totalSymbols?: number | null;
  activePositions?: number | null;
  stats?: Record<string, unknown> | null;
  error?: string | null;
}

export interface SymbolRankWire {
  symbol: string;
  confidence?: number | null;
  isActive?: boolean | null;
  inPosition?: boolean | null;
  ticket?: number | null;
  exchange?: string | null;
  reason?: string | null;
  entryPrice?: number | null;
  lastCheckTime?: string | null;
  stabilityStatus?: string | null;
}

/**
 * /logs, /executions and /closed-trades are declared `ResponseEntity<Object>`
 * on the Java side — they forward whatever the Python monitor returns. The
 * shape below is what hybrid_monitor.py actually sends; `unknown` on the
 * container is the honest type, so the service validates before trusting it.
 */
export interface MonitorExecutionWire {
  timestamp?: number | string;
  symbol?: string;
  success?: boolean;
  ticket?: number | null;
  order_type?: string;
  orderType?: string;
  entry_price?: number;
  entryPrice?: number;
  stop_loss?: number;
  stopLoss?: number;
  take_profit?: number | null;
  takeProfit?: number | null;
  volume?: number;
}

export interface MonitorClosedTradeWire {
  timestamp?: number | string;
  symbol?: string;
  ticket?: number;
  close_reason?: string;
  closeReason?: string;
  profit?: number;
}
