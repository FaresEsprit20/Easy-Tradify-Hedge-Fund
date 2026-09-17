export type MarketRegime = 'trend' | 'range' | 'volatile';

export interface AccountSummary {
  equity: number;
  balance: number;
  margin: number;
  marginLevelPct: number;
  dayPnl: number;
  dayPnlPct: number;
  openPositions: number;
  updatedAt: number;
}

export interface WatchlistItem {
  symbol: string;
  last: number;
  changePct: number;
  bid: number;
  ask: number;
  regime: MarketRegime;
  conviction: number;
  series: number[];
  updatedAt: number;
}

export interface MarketDepthLevel {
  price: number;
  size: number;
}

export interface MarketDepth {
  symbol: string;
  bids: MarketDepthLevel[];
  asks: MarketDepthLevel[];
  updatedAt: number;
}
