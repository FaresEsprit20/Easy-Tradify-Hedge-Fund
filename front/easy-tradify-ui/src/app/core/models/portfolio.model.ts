// Typed 1:1 from portfolio_risk_controller.py's /portfolio/* endpoints.

export type RiskLevel = 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH' | 'CRITICAL';

export interface PeriodStats {
  netProfitUsd: number;
  netProfitPercent: number;
  trades: number;
  winRate: number;
  remainingLossPercent: number;
  consecutiveLosses?: number;
}

export interface PortfolioStatusSummary {
  timestamp: number;
  account: { balance: number; equity: number; leverage: number; currency: string };
  trading: { isAllowed: boolean; riskLevel: RiskLevel; blockedReasons: string[] };
  tradeSizeInUsd: number;
  maxRiskPerTradePercent: number;
  daily: PeriodStats;
  monthly: PeriodStats;
  ytd: PeriodStats;
  drawdown: { currentPercent: number; maxPercent: number };
}

// Every entry in portfolio_risk_controller.py's `valid_fields` list, PUT /portfolio/config.
export interface PortfolioConfig {
  tradeSizeInUsd: number;

  maxDailyLossPercent: number;
  maxDailyTrades: number;
  maxDailyWinTargetPercent: number;

  maxMonthlyLossPercent: number;
  maxMonthlyTrades: number;
  maxMonthlyWinTargetPercent: number;

  maxYtdLossPercent: number;

  maxRiskPerTradePercent: number;
  maxDrawdownPercent: number;

  maxConsecutiveLosses: number;
  maxDailyConsecutiveLosses: number;

  fundedAccountType: string;
  fundedAccountRules: string;

  tradingStartHour: number;
  tradingEndHour: number;

  maxSimultaneousTrades: number;
  maxTradesPerSymbol: number;
  maxSpread: number;
  tradeDeviation: number;

  autoMaxSimultaneousTrades: number;
  autoMaxTradesPerSymbol: number;
  autoMaxSpread: number;
  autoTradeDeviation: number;

  enableBreakeven: boolean;
  autoBreakevenUsd: number;

  enableAutoTrailingStop: boolean;
  autoTrailingStopUsd: number;
}

export interface TradingAllowedCheck {
  isTradingAllowed: boolean;
  riskLevel: RiskLevel;
  reasons: string[];
  requestedRiskPercent: number | null;
  maxRiskPerTradePercent: number;
}

export type StatsPeriod = 'daily' | 'monthly' | 'ytd';

export interface DrawdownInfo {
  currentPercent: number;
  maxPercent: number;
}

export interface FundedCompliance {
  accountType: string | null;
  compliant: boolean;
  violations: string[];
}
