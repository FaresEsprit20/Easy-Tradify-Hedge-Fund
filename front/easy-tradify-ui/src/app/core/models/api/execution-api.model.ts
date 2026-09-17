// Typed 1:1 from execution_controller.py / execute_copy_trade.py's /trade/execute
// and /position/* endpoints, so wiring real HttpClient calls later is a drop-in.

export interface ExecuteTradeRequest {
  symbol: string;
  orderType: 'BUY' | 'SELL';
  strategyMagic: number;
  fixedTradeSizeUsd: number;
  riskPerTrade: number;
  maxSpread: number;
  tradeDeviation?: number;
  maxTradesPerSymbol?: number;
  maxSimultaneousTrades?: number;
  comment?: string;
  stopLossPrice?: number;
  takeProfitPrice?: number;
  takeProfit2Price?: number;
  takeProfit3Price?: number;
  minStopPipsOverride?: number;
  enableBreakEven?: boolean;
  breakEvenPipsDistance?: number;
  breakEvenUsdDistance?: number;
  enableTrailingStop?: boolean;
  trailingPips?: number;
  trailingUsdDistance?: number;
}

export interface TakeProfitSplitLevel {
  label: string;
  price: number;
  percent: number;
}

export interface ExecuteTradeResponse {
  success: boolean;
  ticket: number | null;
  symbol: string;
  orderType: 'BUY' | 'SELL';
  volume: number;
  price: number;
  stopLoss: number;
  takeProfit: number | null;
  takeProfit2: number | null;
  takeProfit3: number | null;
  takeProfitSplit: TakeProfitSplitLevel[] | null;
  actualMargin: number;
  actualRiskUsd: number;
  riskPercentUsed: number;
  magic: number;
  comment: string;
  timestamp: number;
  breakEven: { enabled: boolean; pipsDistance: number | null; usdDistance: number | null };
  trailingStop: { enabled: boolean; pipsDistance: number | null; usdDistance: number | null };
  probabilityOfHitPercent: number | null;
  error?: string;
}

export interface ClosePositionResponse {
  success: boolean;
  ticket: number;
  symbol: string;
  profit: number;
  closePrice: number;
  volume: number;
}

export interface PartialCloseResponse {
  success: boolean;
  ticket: number;
  closedVolume: number;
  remainingVolume: number;
}

export interface CloseAllResponse {
  success: boolean;
  closedCount: number;
  failedCount: number;
  totalProfit: number;
}

export interface ModifyStopLossResponse {
  success: boolean;
  ticket: number;
  newSl: number;
  oldSl: number;
}

export interface ModifyTakeProfitResponse {
  success: boolean;
  ticket: number;
  newTp: number;
  oldTp: number;
}

export type DistanceUnit = 'pips' | 'usd';

export interface BreakEvenEnableRequest {
  pipsDistance?: number;
  usdDistance?: number;
}

export interface BreakEvenStatus {
  ticket: number;
  hasBreakEven: boolean;
  breakEvenApplied: boolean;
  breakEvenTrigger: number | null;
  breakEvenTriggerType: 'pips_distance' | 'usd_distance' | null;
  breakEvenPrice: number | null;
}

export interface TrailingEnableRequest {
  trailingPips?: number;
  trailingUsdDistance?: number;
}

export interface ActiveTrail {
  ticket: number;
  symbol: string;
  distanceType: DistanceUnit;
  usdDistance: number | null;
  pipsDistance: number | null;
  breakEvenEnabled: boolean;
  lastSl: number | null;
  ageSeconds: number;
}

export interface TrailStats {
  totalUpdates: number;
  breakevenApplied: number;
  trailingUpdates: number;
  lastUpdateTime: number;
  activeTrails?: number;
}

export interface TrailingStatusResponse {
  activeTrails: ActiveTrail[];
  count: number;
  stats: TrailStats;
}

export interface CalculateLotRequest {
  symbol: string;
  fixedTradeSizeUsd: number;
  riskPerTrade: number;
  minStopPipsOverride?: number;
}

export interface CalculateLotResponse {
  lot: number;
  actualRisk: number;
  marginRequired: number;
  pipValue: number;
  stopLossPrice: number;
  stopLossPips: number;
  takeProfitPrice: number;
  targetRisk: number;
  targetMargin: number;
  riskPercent: number;
  marginPercent: number;
  currentPrice: number;
  warnings: string[];
}

export interface AccountInfo {
  login: number;
  balance: number;
  equity: number;
  margin: number;
  freeMargin: number;
  marginLevel: number;
  currency: string;
  profit: number;
  leverage: number;
}

export interface TradeHistoryDeal {
  ticket: number;
  symbol: string;
  type: 'BUY' | 'SELL';
  entry: 'entry' | 'exit' | 'reverse' | 'close_by';
  volume: number;
  price: number;
  netProfit: number;
  time: number;
}

export interface GroupedTrade {
  positionId: number;
  symbol: string;
  type: 'BUY' | 'SELL';
  entryTicket: number;
  volume: number;
  entryPrice: number;
  exitPrice: number | null;
  entryTime: number;
  exitTime: number | null;
  netProfit: number;
  isClosed: boolean;
  hasBreakEven: boolean;
}

export interface TradeHistorySummary {
  totalDeals: number;
  closedTrades: number;
  winningTrades: number;
  losingTrades: number;
  totalProfit: number;
  winRate: number;
  avgWin: number;
  avgLoss: number;
  profitFactor: number | null;
  expectancy: number;
}

export interface TradeHistoryResponse {
  deals: TradeHistoryDeal[];
  trades: GroupedTrade[];
  summary: TradeHistorySummary;
}

export interface TradeHistoryQuery {
  symbol?: string;
  magic?: number;
  lastNDays?: number;
}

export interface Mt5ConnectRequest {
  login: number;
  password: string;
  server: string;
  path?: string;
}

export interface Mt5ConnectResponse {
  success: boolean;
  message: string;
  account?: { login: number; balance: number; equity: number; currency: string };
  error?: string;
}
