export type PositionSide = 'long' | 'short';

export interface Position {
  id: string;
  /** MT5 position ticket — what every execution_controller.py /position/* endpoint keys on. */
  ticket: number;
  symbol: string;
  side: PositionSide;
  qty: number;
  entry: number;
  mark: number;
  pnl: number;
  pnlPct: number;
  stop: number;
  /** TP1 — the broker-level MT5 take profit. */
  target: number;
  /** TP2/TP3 — soft partial-exit levels tracked by the EA (execute_copy_trade.py's take_profit_split), not native MT5 fields. */
  target2: number | null;
  target3: number | null;
  openedAt: number;
  updatedAt: number;
}
