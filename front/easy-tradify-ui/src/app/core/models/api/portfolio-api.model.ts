/**
 * Wire shapes for /api/v1/portfolio/**.
 *
 * The Java records here are `Map<String, Object>` envelopes — `{success,
 * status, error}` and `{success, config, error}` — because the Python
 * controller's payload is passed through untouched. So the useful typing has to
 * describe the PYTHON body, which is snake_case throughout, and the mapper is
 * what turns it into the camelCase view models.
 */

export type PortfolioStatusEnvelope = {
  success: boolean;
  status?: PortfolioStatusWire | null;
  error?: string | null;
};

export type PortfolioConfigEnvelope = {
  success: boolean;
  config?: Record<string, unknown> | null;
  error?: string | null;
};

/** portfolio_risk_controller.py's /portfolio/status body. */
export interface PortfolioStatusWire {
  timestamp?: number | string;
  account?: {
    balance?: number;
    equity?: number;
    leverage?: number;
    currency?: string;
  } | null;
  trading?: {
    is_allowed?: boolean;
    isAllowed?: boolean;
    risk_level?: string;
    riskLevel?: string;
    blocked_reasons?: string[];
    blockedReasons?: string[];
  } | null;
  trade_size_in_usd?: number;
  max_risk_per_trade_percent?: number;
  daily?: PeriodStatsWire | null;
  monthly?: PeriodStatsWire | null;
  ytd?: PeriodStatsWire | null;
  drawdown?: { current_percent?: number; max_percent?: number } | null;
}

export interface PeriodStatsWire {
  net_profit_usd?: number;
  net_profit_percent?: number;
  trades?: number;
  win_rate?: number;
  remaining_loss_percent?: number;
  consecutive_losses?: number;
}

export interface CheckTradingAllowedWire {
  success?: boolean;
  is_trading_allowed?: boolean;
  isTradingAllowed?: boolean;
  risk_level?: string;
  reasons?: string[];
  requested_risk_percent?: number | null;
  max_risk_per_trade_percent?: number;
  error?: string | null;
}

export interface DrawdownWire {
  success?: boolean;
  current_percent?: number;
  max_percent?: number;
  drawdown?: { current_percent?: number; max_percent?: number } | null;
  error?: string | null;
}

export interface FundedComplianceWire {
  success?: boolean;
  account_type?: string;
  compliant?: boolean;
  violations?: string[];
  error?: string | null;
}

export interface MaxRiskWire {
  success?: boolean;
  max_risk_for_trade?: number;
  max_risk_per_trade_percent?: number;
  error?: string | null;
}
