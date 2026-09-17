// Typed from execute_copy_trade.py's CopyTradeManager.get_status().

export interface CopyTradeStats {
  startTime: number | null;
  tradesRegistered: number;
  tradesClosed: number;
  firebaseSaves: number;
  firebaseErrors: number;
  webhookCloses: number;
  trailingUpdates: number;
  priceUpdates: number;
  monitorErrors: number;
}

export interface CopyTradeStatus {
  running: boolean;
  openTrackedPositions: number;
  openPositions: Record<string, number>;
  stats: CopyTradeStats;
  webhookClosedTickets: number;
  positionCacheSize: number;
  priceUpdateInterval: number;
  firebaseConnected: boolean;
}
