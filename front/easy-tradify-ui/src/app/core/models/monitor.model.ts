// Typed from hybrid_monitor.py's /monitor/* endpoints. Fields for get_status()
// and get_restart_status() weren't fully specified in the source snippet — those
// two are reasonable-shape approximations, flagged below.

export interface MonitorStatus {
  running: boolean;
  /** Approximated — Python source didn't show get_status()'s full shape. */
  uptimeSeconds: number;
  symbolsTracked: number;
  openPositions: number;
  lastRefreshAt: number;
}

export interface RestartStatus {
  /** Approximated — Python source didn't show get_restart_status()'s full shape. */
  enabled: boolean;
  intervalSeconds: number;
  lastRestartAt: number | null;
  nextRestartAt: number | null;
  restartInProgress: boolean;
}

export type TopSymbolStability = 'STABLE' | 'WATCH' | 'UNSTABLE' | 'UNKNOWN';

export interface TopSymbol {
  symbol: string;
  confidence: number;
  isActive: boolean;
  inPosition: boolean;
  ticket: number | null;
  exchange: string;
  reason: string;
  entryPrice: number | null;
  lastCheckTime: number;
  stabilityStatus: TopSymbolStability;
}

export interface FilteredSymbolsResponse {
  symbols: string[];
  permanentlyExcluded: string[];
  longTermExcluded: string[];
}

export interface MonitorExecutionEntry {
  timestamp: number;
  symbol: string;
  success: boolean;
  ticket: number | null;
  orderType: string;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number | null;
  volume: number;
}

export interface MonitorClosedTrade {
  timestamp: number;
  symbol: string;
  ticket: number;
  closeReason: string;
  profit: number;
  isWinning: boolean;
}

export interface FirebaseStatus {
  connected: boolean;
  queueSize: number;
  errors: number;
  lastWriteAt: number | null;
}

export interface NewsStatus {
  cacheHealthy: boolean;
  highImpactEventsToday: number;
  nextEvent: string | null;
  lastRefreshAt: number | null;
}

export interface SessionStatus {
  activeSessions: string[];
  isMarketOpen: boolean;
  minutesToClose: number | null;
  lastRefreshAt: number | null;
}
