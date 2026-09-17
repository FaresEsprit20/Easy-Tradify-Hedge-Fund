import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { MockStreamService } from '../mock-stream.service';
import { ApiClient } from '../../http/api-client.service';
import { ApiError } from '../../http/api-error';
import { DataOrigin } from '../../http/backend-health.service';
import { SERVICE } from '../../http/services';
import { environment } from '../../../../environments/environment';
import {
  PortfolioStatusEnvelope,
  PortfolioStatusWire,
  PortfolioConfigEnvelope,
  PeriodStatsWire,
  CheckTradingAllowedWire,
  DrawdownWire,
  FundedComplianceWire,
  MaxRiskWire,
} from '../../models/api/portfolio-api.model';
import {
  PortfolioStatusSummary,
  PortfolioConfig,
  TradingAllowedCheck,
  StatsPeriod,
  PeriodStats,
  DrawdownInfo,
  FundedCompliance,
  RiskLevel,
} from '../../models/portfolio.model';

function round(value: number, decimals: number): number {
  const f = Math.pow(10, decimals);
  return Math.round(value * f) / f;
}

/**
 * Risk limits and portfolio state, from /api/v1/portfolio/** via the gateway.
 *
 * The Python controller behind this (port 5010) is the authority on what the
 * bot is ALLOWED to do — daily loss caps, drawdown, consecutive losses. That
 * makes the fallback behaviour here more delicate than elsewhere: a seeded
 * "trading allowed: yes" shown while the risk service is unreachable is an
 * invitation to trade past a limit that is actually breached. So
 * `checkTradingAllowed()` fails CLOSED — if it cannot reach the service it
 * reports not-allowed with the reason, regardless of `allowMockFallback`.
 */
@Injectable({ providedIn: 'root' })
export class PortfolioApiService {
  private readonly stream = inject(MockStreamService);
  private readonly api = inject(ApiClient);

  readonly origin = signal<DataOrigin>(environment.allowMockFallback ? 'mock' : 'stale');
  readonly lastError = signal<string | null>(null);

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  readonly config = signal<PortfolioConfig>({
    tradeSizeInUsd: 200,
    maxDailyLossPercent: 5,
    maxDailyTrades: 12,
    maxDailyWinTargetPercent: 8,
    maxMonthlyLossPercent: 12,
    maxMonthlyTrades: 150,
    maxMonthlyWinTargetPercent: 25,
    maxYtdLossPercent: 20,
    maxRiskPerTradePercent: 5,
    maxDrawdownPercent: 10,
    maxConsecutiveLosses: 5,
    maxDailyConsecutiveLosses: 3,
    fundedAccountType: 'FTMO Swing',
    fundedAccountRules: 'STANDARD',
    tradingStartHour: 7,
    tradingEndHour: 20,
    maxSimultaneousTrades: 5,
    maxTradesPerSymbol: 1,
    maxSpread: 30,
    tradeDeviation: 20,
    autoMaxSimultaneousTrades: 5,
    autoMaxTradesPerSymbol: 1,
    autoMaxSpread: 30,
    autoTradeDeviation: 20,
    enableBreakeven: true,
    autoBreakevenUsd: 15,
    enableAutoTrailingStop: true,
    autoTrailingStopUsd: 10,
  });

  // Signals rather than constants: these were fixed sample figures, and the
  // live status response overwrites all three in one call. Their seeded values
  // remain the offline fallback.
  private readonly daily = signal<PeriodStats>({ netProfitUsd: 313.43, netProfitPercent: 1.4, trades: 6, winRate: 66.7, remainingLossPercent: 3.6, consecutiveLosses: 0 });
  private readonly monthly = signal<PeriodStats>({ netProfitUsd: 2841.2, netProfitPercent: 12.7, trades: 84, winRate: 61.9, remainingLossPercent: 6.8 });
  private readonly ytd = signal<PeriodStats>({ netProfitUsd: 9120.5, netProfitPercent: 40.7, trades: 612, winRate: 59.3, remainingLossPercent: 12.4 });

  /** Live drawdown, once the service has answered. Null means "not yet read". */
  private readonly liveDrawdown = signal<DrawdownInfo | null>(null);

  /** Live account block from /status; falls back to the mock stream. */
  private readonly liveAccount = signal<PortfolioStatusWire['account'] | null>(null);

  private readonly liveTrading = signal<PortfolioStatusWire['trading'] | null>(null);

  private delay<T>(value: T, ms = 260): Promise<T> {
    return new Promise((resolve) => setTimeout(() => resolve(value), ms));
  }

  private riskLevel(): RiskLevel {
    const dd = this.getDrawdown().currentPercent;
    if (dd >= 8) return 'CRITICAL';
    if (dd >= 6) return 'HIGH';
    if (dd >= 4) return 'ELEVATED';
    if (dd >= 2) return 'MODERATE';
    return 'LOW';
  }

  // ------------------------------------------------------------------
  // GET /portfolio/status?summary=true
  // ------------------------------------------------------------------
  getStatus(): PortfolioStatusSummary {
    const live = this.liveAccount();
    const mockAccount = this.stream.accountSummary();
    const account = {
      balance: live?.balance ?? mockAccount.balance,
      equity: live?.equity ?? mockAccount.equity,
      leverage: live?.leverage ?? 200,
      currency: live?.currency ?? 'USD',
    };

    // Prefer the service's own verdict. It applies rules this client does not
    // model (funded-account conditions, per-symbol caps, trading hours), so
    // recomputing it locally would quietly disagree with the bot.
    const remote = this.liveTrading();
    const riskLevel = (remote?.riskLevel ?? remote?.risk_level ?? this.riskLevel()) as RiskLevel;

    const blocked: string[] = remote
      ? (remote.blockedReasons ?? remote.blocked_reasons ?? [])
      : [];

    if (!remote) {
      if (this.daily().remainingLossPercent <= 0) blocked.push('Daily loss limit reached');
      if (riskLevel === 'CRITICAL') blocked.push('Portfolio drawdown at critical threshold');
    }

    const isAllowed = remote
      ? (remote.isAllowed ?? remote.is_allowed ?? false)
      : blocked.length === 0;

    return {
      timestamp: Date.now(),
      account,
      trading: { isAllowed, riskLevel, blockedReasons: blocked },
      tradeSizeInUsd: this.config().tradeSizeInUsd,
      maxRiskPerTradePercent: this.config().maxRiskPerTradePercent,
      daily: this.daily(),
      monthly: this.monthly(),
      ytd: this.ytd(),
      drawdown: this.getDrawdown(),
    };
  }

  // ------------------------------------------------------------------
  // GET/PUT /portfolio/config, GET/PUT /portfolio/config/<field>
  // ------------------------------------------------------------------
  getConfig(): PortfolioConfig {
    return this.config();
  }

  async updateConfig(updates: Partial<PortfolioConfig>): Promise<PortfolioConfig> {
    const next = { ...this.config(), ...updates };

    try {
      // The controller validates the fields and accepts or rejects the request
      // as a unit, so the local signal is only updated after it succeeds --
      // showing limits as applied when the service refused them would put the
      // UI out of step with what the bot is actually enforcing.
      const response = await firstValueFrom(
        this.api.put<PortfolioConfigEnvelope>(SERVICE.portfolio, '/config', toWireConfig(updates)),
      );
      if (response?.success === false) throw new Error(response.error ?? 'Config rejected');

      this.config.set(
        response?.config ? { ...next, ...fromWireConfig(response.config) } : next,
      );
      this.lastError.set(null);
      this.origin.set('live');
    } catch (error) {
      const message = error instanceof ApiError ? error.message : String(error);
      this.lastError.set(message);

      if (!(environment.allowMockFallback && error instanceof ApiError && error.isPlatformFailure)) {
        this.logActivity(`Config update FAILED: ${message}`);
        throw error;
      }
      this.config.set(next);
      this.origin.set('mock');
    }

    this.logActivity(`Config updated: ${Object.keys(updates).join(', ')}`);
    return this.config();
  }

  private logActivity(message: string): void {
    this.stream.activityLog.update((list) => [
      ...list.slice(-79),
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        timestamp: Date.now(),
        level: 'info',
        message: `[Risk] ${message}`,
      },
    ]);
  }

  // ------------------------------------------------------------------
  // POST /portfolio/check_trading_allowed, GET /portfolio/max_risk_for_trade
  // ------------------------------------------------------------------
  /**
   * Ask the risk service whether a trade may be placed.
   *
   * FAILS CLOSED. Every other read in this file degrades to sample data when
   * the backend is unreachable; this one must not. The answer gates real orders
   * against limits that exist to stop an account being blown, and "the service
   * was down, so we assumed yes" is exactly the wrong default. On failure it
   * returns not-allowed, with the transport error as the stated reason.
   */
  async checkTradingAllowed(tradeRiskPercent?: number): Promise<TradingAllowedCheck> {
    const maxRisk = this.config().maxRiskPerTradePercent;

    try {
      const wire = await firstValueFrom(
        this.api.post<CheckTradingAllowedWire>(SERVICE.portfolio, '/check_trading_allowed', {
          trade_risk_percent: tradeRiskPercent ?? null,
        }),
      );

      this.lastError.set(null);
      this.origin.set('live');

      return {
        isTradingAllowed: wire.isTradingAllowed ?? wire.is_trading_allowed ?? false,
        riskLevel: (wire.risk_level ?? 'LOW') as RiskLevel,
        reasons: wire.reasons ?? [],
        requestedRiskPercent: wire.requested_risk_percent ?? tradeRiskPercent ?? null,
        maxRiskPerTradePercent: wire.max_risk_per_trade_percent ?? maxRisk,
      };
    } catch (error) {
      const message = error instanceof ApiError ? error.message : String(error);
      this.lastError.set(message);
      this.logActivity(`Trading-allowed check failed, refusing: ${message}`);

      return {
        isTradingAllowed: false,
        riskLevel: 'CRITICAL',
        reasons: [`Risk service unreachable - refusing to confirm (${message})`],
        requestedRiskPercent: tradeRiskPercent ?? null,
        maxRiskPerTradePercent: maxRisk,
      };
    }
  }

  getMaxRiskForTrade(): number {
    return this.config().maxRiskPerTradePercent;
  }

  // ------------------------------------------------------------------
  // GET /portfolio/stats?period=
  // ------------------------------------------------------------------
  getStats(period: StatsPeriod): PeriodStats {
    return period === 'daily' ? this.daily() : period === 'monthly' ? this.monthly() : this.ytd();
  }

  // ------------------------------------------------------------------
  // GET /portfolio/drawdown
  // ------------------------------------------------------------------
  getDrawdown(): DrawdownInfo {
    const live = this.liveDrawdown();
    if (live) return live;

    // Only reached before the first successful read, or while offline. The
    // jitter is what made the seeded value look live; it is kept so the gauge
    // still animates in mock mode rather than sitting frozen.
    return { currentPercent: round(2.4 + Math.random() * 0.6, 2), maxPercent: this.config().maxDrawdownPercent };
  }

  // ------------------------------------------------------------------
  // GET /portfolio/funded_compliance
  // ------------------------------------------------------------------
  getFundedCompliance(): FundedCompliance {
    const status = this.getStatus();
    const violations: string[] = [];
    if (status.daily.netProfitPercent <= -this.config().maxDailyLossPercent) violations.push('Daily loss limit breached');
    if (status.drawdown.currentPercent >= status.drawdown.maxPercent) violations.push('Max drawdown breached');
    return { accountType: this.config().fundedAccountType, compliant: violations.length === 0, violations };
  }

  // ------------------------------------------------------------------
  // POST /portfolio/refresh
  // ------------------------------------------------------------------
  async refresh(): Promise<{ success: boolean }> {
    try {
      await firstValueFrom(this.api.post<unknown>(SERVICE.portfolio, '/refresh'));
      await this.refreshAll();
      return { success: true };
    } catch (error) {
      this.lastError.set(error instanceof ApiError ? error.message : String(error));
      return { success: environment.allowMockFallback };
    }
  }

  // ==================================================================
  // LIVE READS
  // ==================================================================

  startPolling(): void {
    if (this.pollTimer !== null) return;
    void this.refreshAll();
    this.pollTimer = setInterval(() => void this.refreshAll(), environment.pollIntervalMs.portfolio);
  }

  stopPolling(): void {
    if (this.pollTimer === null) return;
    clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  async refreshAll(): Promise<void> {
    await Promise.allSettled([this.refreshStatus(), this.refreshConfig(), this.refreshDrawdown()]);
  }

  /** /status carries account, the trading verdict, all three periods and drawdown. */
  async refreshStatus(): Promise<void> {
    try {
      const envelope = await firstValueFrom(
        this.api.get<PortfolioStatusEnvelope>(SERVICE.portfolio, '/status', { summary: true }),
      );

      if (envelope?.success === false || !envelope?.status) {
        this.markStale(envelope?.error ?? 'Portfolio status unavailable');
        return;
      }

      const wire = envelope.status;
      this.liveAccount.set(wire.account ?? null);
      this.liveTrading.set(wire.trading ?? null);

      if (wire.daily) this.daily.set(toPeriodStats(wire.daily));
      if (wire.monthly) this.monthly.set(toPeriodStats(wire.monthly));
      if (wire.ytd) this.ytd.set(toPeriodStats(wire.ytd));

      if (wire.drawdown) {
        this.liveDrawdown.set({
          currentPercent: wire.drawdown.current_percent ?? 0,
          maxPercent: wire.drawdown.max_percent ?? this.config().maxDrawdownPercent,
        });
      }

      this.markLive();
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  async refreshConfig(): Promise<void> {
    try {
      const envelope = await firstValueFrom(
        this.api.get<PortfolioConfigEnvelope>(SERVICE.portfolio, '/config'),
      );
      const config = envelope?.config;
      if (config) {
        this.config.update((current) => ({ ...current, ...fromWireConfig(config) }));
        this.markLive();
      }
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  async refreshDrawdown(): Promise<void> {
    try {
      const wire = await firstValueFrom(this.api.get<DrawdownWire>(SERVICE.portfolio, '/drawdown'));
      const block = wire.drawdown ?? wire;
      if (block.current_percent !== undefined) {
        this.liveDrawdown.set({
          currentPercent: block.current_percent ?? 0,
          maxPercent: block.max_percent ?? this.config().maxDrawdownPercent,
        });
        this.markLive();
      }
    } catch (error) {
      this.handleReadFailure(error);
    }
  }

  async fetchFundedCompliance(): Promise<FundedCompliance> {
    try {
      const wire = await firstValueFrom(
        this.api.get<FundedComplianceWire>(SERVICE.portfolio, '/funded_compliance'),
      );
      this.markLive();
      return {
        accountType: wire.account_type ?? this.config().fundedAccountType,
        compliant: wire.compliant ?? false,
        violations: wire.violations ?? [],
      };
    } catch (error) {
      this.handleReadFailure(error);
      return this.getFundedCompliance();
    }
  }

  async fetchMaxRiskForTrade(): Promise<number> {
    try {
      const wire = await firstValueFrom(
        this.api.get<MaxRiskWire>(SERVICE.portfolio, '/max_risk_for_trade'),
      );
      this.markLive();
      return wire.max_risk_for_trade ?? wire.max_risk_per_trade_percent ?? this.getMaxRiskForTrade();
    } catch (error) {
      this.handleReadFailure(error);
      return this.getMaxRiskForTrade();
    }
  }

  // ------------------------------------------------------------------

  private markLive(): void {
    this.origin.set('live');
    this.lastError.set(null);
  }

  private markStale(message: string): void {
    this.lastError.set(message);
    if (this.origin() === 'live') this.origin.set('stale');
  }

  private handleReadFailure(error: unknown): void {
    const message = error instanceof ApiError ? error.message : String(error);
    if (environment.allowMockFallback && error instanceof ApiError && error.isPlatformFailure) {
      this.origin.set('mock');
      this.lastError.set(message);
      return;
    }
    this.markStale(message);
  }
}

// ====================================================================
// WIRE <-> VIEW MAPPERS
// ====================================================================

function toPeriodStats(wire: PeriodStatsWire): PeriodStats {
  return {
    netProfitUsd: wire.net_profit_usd ?? 0,
    netProfitPercent: wire.net_profit_percent ?? 0,
    trades: wire.trades ?? 0,
    winRate: wire.win_rate ?? 0,
    remainingLossPercent: wire.remaining_loss_percent ?? 0,
    consecutiveLosses: wire.consecutive_losses,
  };
}

/**
 * camelCase view keys -> the controller's snake_case field names.
 *
 * Transformed rather than kept as a lookup table: the config carries 28 fields,
 * and a table would need an edit every time one is added -- the kind of
 * maintenance that gets skipped and then silently drops a field from the PUT.
 */
function toWireConfig(updates: Partial<PortfolioConfig>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(updates)) {
    if (value === undefined) continue;
    out[toSnakeCase(key)] = value;
  }
  return out;
}

function fromWireConfig(config: Record<string, unknown>): Partial<PortfolioConfig> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(config)) {
    out[toCamelCase(key)] = value;
  }
  return out as Partial<PortfolioConfig>;
}

function toSnakeCase(key: string): string {
  // maxDailyLossPercent -> max_daily_loss_percent
  return key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
}

function toCamelCase(key: string): string {
  return key.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
}
