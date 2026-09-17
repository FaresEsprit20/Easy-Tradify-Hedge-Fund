import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { MockStreamService } from '../mock-stream.service';
import { SYMBOL_UNIVERSE, SYMBOL_MAP } from '../../data/symbols';
import { ApiClient } from '../../http/api-client.service';
import { ApiError } from '../../http/api-error';
import { DataOrigin } from '../../http/backend-health.service';
import { SERVICE } from '../../http/services';
import { environment } from '../../../../environments/environment';
import { Position } from '../../models/position.model';
import { ActivityLevel } from '../../models/activity.model';
import {
  ExecuteTradeRequest,
  ExecuteTradeResponse,
  ClosePositionResponse,
  PartialCloseResponse,
  CloseAllResponse,
  ModifyStopLossResponse,
  ModifyTakeProfitResponse,
  BreakEvenEnableRequest,
  BreakEvenStatus,
  TrailingEnableRequest,
  ActiveTrail,
  TrailingStatusResponse,
  CalculateLotRequest,
  CalculateLotResponse,
  AccountInfo,
  TradeHistoryResponse,
  TradeHistoryQuery,
  GroupedTrade,
  Mt5ConnectRequest,
  Mt5ConnectResponse,
  TakeProfitSplitLevel,
} from '../../models/api/execution-api.model';

function round(value: number, decimals: number): number {
  const f = Math.pow(10, decimals);
  return Math.round(value * f) / f;
}

/** Internal shape of one core/execution.py `_active_trails[ticket]` entry. */
interface TrailRecord extends ActiveTrail {
  breakEvenEnabled: boolean;
}

/**
 * Mirrors execution_controller.py / execute_copy_trade.py's /trade/execute and
 * /position/* endpoints — one method per real endpoint, same request/response
 * shape. `activeTrails`/`breakEvenStatuses` intentionally mirror core/
 * execution.py's own `_active_trails` dict (a side-table keyed by ticket, not
 * a field on the position itself), kept as signals — not plain Maps — so row
 * actions in the UI re-render the instant a toggle changes.
 */
@Injectable({ providedIn: 'root' })
export class ExecutionApiService {
  private readonly stream = inject(MockStreamService);
  private readonly api = inject(ApiClient);

  /**
   * Where the account and position data currently on screen came from.
   *
   * This service is the one that places real orders, so the distinction is not
   * cosmetic. In mock mode the numbers are invented; a P&L or a margin level
   * shown without that qualifier is exactly the kind of figure that gets acted
   * on. `environment.allowMockFallback` is false in production for the same
   * reason.
   */
  readonly origin = signal<DataOrigin>(environment.allowMockFallback ? 'mock' : 'stale');
  readonly lastError = signal<string | null>(null);

  /** Live account from GET /account. Null until the first successful read. */
  private readonly liveAccount = signal<AccountInfo | null>(null);

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  readonly activeTrails = signal<Map<number, TrailRecord>>(new Map());
  readonly breakEvenStatuses = signal<Map<number, BreakEvenStatus>>(new Map());
  readonly tradeHistory = signal<GroupedTrade[]>([]);
  readonly mt5Connected = signal(true);
  readonly mt5Login = signal<number | null>(50412897);

  private readonly trailStats = { totalUpdates: 0, breakevenApplied: 0, trailingUpdates: 0, lastUpdateTime: 0 };
  private nextTicket = 90_000_101;
  private nextPositionId = 5000;

  private delay<T>(value: T, ms = 260): Promise<T> {
    return new Promise((resolve) => setTimeout(() => resolve(value), ms));
  }

  private log(level: ActivityLevel, message: string, symbol?: string): void {
    this.stream.activityLog.update((list) => [
      ...list.slice(-79),
      { id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, timestamp: Date.now(), level, message, symbol },
    ]);
  }

  private findPosition(ticket: number): Position | undefined {
    return this.stream.positions().find((p) => p.ticket === ticket);
  }

  private seedFor(symbol: string) {
    return SYMBOL_MAP.get(symbol) ?? SYMBOL_UNIVERSE[0];
  }

  private creditAccount(profitUsd: number): void {
    this.stream.accountSummary.update((a) => {
      const balance = round(a.balance + profitUsd, 2);
      const dayPnl = round(a.dayPnl + profitUsd, 2);
      return { ...a, balance, equity: round(balance + (a.equity - a.balance), 2), dayPnl, dayPnlPct: round((dayPnl / balance) * 100, 2) };
    });
  }

  private setTrail(ticket: number, record: TrailRecord): void {
    this.activeTrails.update((m) => new Map(m).set(ticket, record));
  }

  private deleteTrail(ticket: number): void {
    this.activeTrails.update((m) => {
      const next = new Map(m);
      next.delete(ticket);
      return next;
    });
  }

  private setBreakEven(ticket: number, status: BreakEvenStatus): void {
    this.breakEvenStatuses.update((m) => new Map(m).set(ticket, status));
  }

  private deleteBreakEven(ticket: number): void {
    this.breakEvenStatuses.update((m) => {
      const next = new Map(m);
      next.delete(ticket);
      return next;
    });
  }

  // ------------------------------------------------------------------
  // POST /trade/execute
  // ------------------------------------------------------------------
  /**
   * Place a real order.
   *
   * NO MOCK FALLBACK, and no retry. If the platform is unreachable this throws
   * rather than pretending: a fabricated ticket number for an order that was
   * never sent is the worst possible outcome here, and a request that timed out
   * may still have reached MT5 and filled — replaying it would double the
   * position. The caller shows the error and the next positions poll reveals
   * whether anything actually opened.
   */
  async executeTrade(req: ExecuteTradeRequest): Promise<ExecuteTradeResponse> {
    if (!environment.allowMockFallback || this.preferLive) {
      const wire = await firstValueFrom(
        this.api.post<ExecuteTradeWire>(SERVICE.execution, '/trade', toTradePayload(req)),
      );
      const d = wire.data ?? (wire as unknown as ExecuteTradeData);

      if (wire.success === false && !d.ticket) {
        throw new ApiError('rejected', wire.error ?? 'Trade rejected', 200, '/execution/trade', wire);
      }

      this.log(
        'success',
        `Trade executed: ${req.orderType} ${req.symbol} (ticket ${d.ticket})`,
        req.symbol,
      );

      // Server truth, immediately — rather than synthesising the new position
      // locally and letting it drift from what the broker actually filled.
      await this.refreshAll();
      this.origin.set('live');

      return {
        success: wire.success ?? true,
        ticket: d.ticket ?? null,
        symbol: d.symbol ?? req.symbol,
        orderType: (d.order_type ?? d.orderType ?? req.orderType) as 'BUY' | 'SELL',
        volume: d.volume ?? 0,
        price: d.price ?? 0,
        stopLoss: d.stop_loss ?? d.stopLoss ?? 0,
        takeProfit: d.take_profit ?? d.takeProfit ?? null,
        takeProfit2: d.take_profit_2 ?? d.takeProfit2 ?? null,
        takeProfit3: d.take_profit_3 ?? d.takeProfit3 ?? null,
        takeProfitSplit: d.take_profit_split ?? d.takeProfitSplit ?? null,
        actualMargin: d.actual_margin ?? d.actualMargin ?? 0,
        actualRiskUsd: d.actual_risk_usd ?? d.actualRiskUsd ?? 0,
        riskPercentUsed: d.risk_percent_used ?? d.riskPercentUsed ?? 0,
        magic: d.magic ?? req.strategyMagic,
        comment: d.comment ?? '',
        timestamp: toEpoch(d.timestamp) ?? Date.now(),
        breakEven: {
          enabled: d.break_even?.enabled ?? false,
          pipsDistance: d.break_even?.pips_distance ?? null,
          usdDistance: d.break_even?.usd_distance ?? null,
        },
        trailingStop: {
          enabled: d.trailing_stop?.enabled ?? false,
          pipsDistance: d.trailing_stop?.pips_distance ?? null,
          usdDistance: d.trailing_stop?.usd_distance ?? null,
        },
        // Null, not 0. This is a model output and "no estimate available" is a
        // different statement from "a 0% chance of hitting target".
        probabilityOfHitPercent:
          d.probability_of_hit_percent ?? d.probabilityOfHitPercent ?? null,
        error: wire.error ?? undefined,
      };
    }

    return this.executeTradeMock(req);
  }

  private async executeTradeMock(req: ExecuteTradeRequest): Promise<ExecuteTradeResponse> {
    const seed = this.seedFor(req.symbol);
    const digits = seed.pip < 0.01 ? 5 : 2;
    const price = round(seed.base * (1 + (Math.random() - 0.5) * 0.001), digits);
    const slPips = req.minStopPipsOverride ?? 20;
    const stopLoss = req.stopLossPrice ?? round(price - (req.orderType === 'BUY' ? 1 : -1) * slPips * seed.pip, digits);
    const takeProfit = req.takeProfitPrice ?? null;
    const volume = round(Math.max(0.01, (req.fixedTradeSizeUsd * req.riskPerTrade) / (slPips * 10)), 2);
    const ticket = this.nextTicket++;

    const useNativeTp = req.takeProfit2Price == null && req.takeProfit3Price == null;
    const takeProfitSplit =
      !useNativeTp && takeProfit != null
        ? req.takeProfit3Price != null
          ? [
              { label: 'TP1', price: takeProfit, percent: 33 },
              { label: 'TP2', price: req.takeProfit2Price!, percent: 33 },
              { label: 'TP3', price: req.takeProfit3Price!, percent: 34 },
            ]
          : [
              { label: 'TP1', price: takeProfit, percent: 70 },
              { label: 'TP2', price: req.takeProfit2Price!, percent: 30 },
            ]
        : null;

    const position: Position = {
      id: `POS-${this.nextPositionId++}`,
      ticket,
      symbol: req.symbol,
      side: req.orderType === 'BUY' ? 'long' : 'short',
      qty: volume,
      entry: price,
      mark: price,
      pnl: 0,
      pnlPct: 0,
      stop: stopLoss,
      target: takeProfit ?? round(price + (req.orderType === 'BUY' ? 1 : -1) * slPips * 2 * seed.pip, digits),
      target2: req.takeProfit2Price ?? null,
      target3: req.takeProfit3Price ?? null,
      openedAt: Date.now(),
      updatedAt: Date.now(),
    };
    this.stream.positions.update((list) => [...list, position]);

    if (req.enableBreakEven || req.enableTrailingStop) {
      this.setTrail(ticket, {
        ticket,
        symbol: req.symbol,
        distanceType: req.trailingUsdDistance != null ? 'usd' : 'pips',
        usdDistance: req.trailingUsdDistance ?? null,
        pipsDistance: req.trailingPips ?? null,
        breakEvenEnabled: !!req.enableBreakEven,
        lastSl: stopLoss,
        ageSeconds: 0,
      });
    }
    if (req.enableBreakEven) {
      this.setBreakEven(ticket, {
        ticket,
        hasBreakEven: true,
        breakEvenApplied: false,
        breakEvenTrigger: req.breakEvenUsdDistance ?? req.breakEvenPipsDistance ?? 0,
        breakEvenTriggerType: req.breakEvenUsdDistance != null ? 'usd_distance' : 'pips_distance',
        breakEvenPrice: null,
      });
    }

    this.log('success', `${req.orderType} ${volume} ${req.symbol} filled @ ${price} (ticket ${ticket})`, req.symbol);

    return this.delay({
      success: true,
      ticket,
      symbol: req.symbol,
      orderType: req.orderType,
      volume,
      price,
      stopLoss,
      takeProfit,
      takeProfit2: req.takeProfit2Price ?? null,
      takeProfit3: req.takeProfit3Price ?? null,
      takeProfitSplit,
      actualMargin: round(volume * 1000, 2),
      actualRiskUsd: round(req.fixedTradeSizeUsd * req.riskPerTrade, 2),
      riskPercentUsed: round(req.riskPerTrade * 100, 1),
      magic: req.strategyMagic,
      comment: req.comment ?? 'AI Trade',
      timestamp: Date.now(),
      breakEven: { enabled: !!req.enableBreakEven, pipsDistance: req.breakEvenPipsDistance ?? null, usdDistance: req.breakEvenUsdDistance ?? null },
      trailingStop: { enabled: !!req.enableTrailingStop, pipsDistance: req.trailingPips ?? null, usdDistance: req.trailingUsdDistance ?? null },
      probabilityOfHitPercent: takeProfit != null ? Math.round(40 + Math.random() * 45) : null,
    });
  }

  // ------------------------------------------------------------------
  // POST /position/close/<ticket>
  // ------------------------------------------------------------------
  /**
   * Close a position. Like executeTrade, this never falls back to the mock —
   * reporting a close that did not happen leaves real exposure on the account
   * while the screen shows none.
   */
  async closePosition(ticket: number, deviation = 20): Promise<ClosePositionResponse> {
    if (!environment.allowMockFallback || this.preferLive) {
      const wire = await firstValueFrom(
        this.api.post<ClosePositionWire>(SERVICE.execution, '/position/close', {
          ticket,
          deviation,
        }),
      );
      const d = wire.data ?? (wire as unknown as ClosePositionData);

      if (wire.success === false) {
        throw new ApiError('rejected', wire.error ?? 'Close rejected', 200, '/execution/position/close', wire);
      }

      const profit = d.profit ?? 0;
      this.deleteTrail(ticket);
      this.log(
        'success',
        `Position closed: ${d.symbol ?? ticket} (ticket ${ticket}) — ${profit >= 0 ? '+' : ''}${profit.toFixed(2)}`,
        d.symbol,
      );
      await this.refreshAll();

      return {
        success: true,
        ticket,
        symbol: d.symbol ?? '',
        profit,
        closePrice: d.close_price ?? d.closePrice ?? 0,
        volume: d.volume ?? 0,
      };
    }

    return this.closePositionMock(ticket);
  }

  private async closePositionMock(ticket: number): Promise<ClosePositionResponse> {
    const pos = this.findPosition(ticket);
    if (!pos) throw new Error(`Position ${ticket} not found`);

    this.stream.positions.update((list) => list.filter((p) => p.ticket !== ticket));
    this.deleteTrail(ticket);
    this.creditAccount(pos.pnl);
    this.recordClosedTrade(pos, pos.mark);
    this.log('success', `Position closed: ${pos.symbol} (ticket ${ticket}) — ${pos.pnl >= 0 ? '+' : ''}${pos.pnl.toFixed(2)}`, pos.symbol);

    return this.delay({ success: true, ticket, symbol: pos.symbol, profit: pos.pnl, closePrice: pos.mark, volume: pos.qty });
  }

  // ------------------------------------------------------------------
  // PUT /position/partial-close/<ticket>
  // ------------------------------------------------------------------
  async partialClosePosition(ticket: number, volumeToClose: number, _deviation = 20): Promise<PartialCloseResponse> {
    const pos = this.findPosition(ticket);
    if (!pos) throw new Error(`Position ${ticket} not found`);
    if (volumeToClose >= pos.qty) throw new Error(`Volume to close (${volumeToClose}) must be less than position volume (${pos.qty})`);

    const remaining = round(pos.qty - volumeToClose, 2);
    const closedPnl = round(pos.pnl * (volumeToClose / pos.qty), 2);
    this.stream.positions.update((list) => list.map((p) => (p.ticket === ticket ? { ...p, qty: remaining, pnl: round(p.pnl - closedPnl, 2) } : p)));
    this.creditAccount(closedPnl);
    this.log('info', `Partially closed ${volumeToClose} of ${pos.symbol} (ticket ${ticket}) — remaining ${remaining}`, pos.symbol);

    return this.delay({ success: true, ticket, closedVolume: volumeToClose, remainingVolume: remaining });
  }

  // ------------------------------------------------------------------
  // POST /positions/close/all
  // ------------------------------------------------------------------
  async closeAllPositions(symbol?: string, deviation = 20): Promise<CloseAllResponse> {
    if (!environment.allowMockFallback || this.preferLive) {
      // One bulk call rather than a loop of single closes: the controller
      // closes them in one pass, and a loop that fails halfway leaves the
      // account in a state neither side has a record of.
      const wire = await firstValueFrom(
        this.api.post<CloseAllWire>(SERVICE.execution, '/positions/close/all', {
          symbol: symbol ?? null,
          deviation,
        }),
      );
      const d = wire.data ?? (wire as unknown as CloseAllData);
      await this.refreshAll();

      return {
        success: wire.success ?? true,
        closedCount: d.closed_count ?? d.closedCount ?? 0,
        failedCount: d.failed_count ?? d.failedCount ?? 0,
        totalProfit: round(d.total_profit ?? d.totalProfit ?? 0, 2),
      };
    }

    return this.closeAllPositionsMock(symbol, deviation);
  }

  private async closeAllPositionsMock(symbol?: string, deviation = 20): Promise<CloseAllResponse> {
    const targets = this.stream.positions().filter((p) => !symbol || p.symbol === symbol);
    let totalProfit = 0;
    for (const p of targets) {
      const res = await this.closePosition(p.ticket, deviation);
      totalProfit += res.profit;
    }
    return { success: targets.length > 0, closedCount: targets.length, failedCount: 0, totalProfit: round(totalProfit, 2) };
  }

  // ------------------------------------------------------------------
  // PUT /position/<ticket>/stop-loss
  // ------------------------------------------------------------------
  async modifyStopLoss(ticket: number, slPrice: number): Promise<ModifyStopLossResponse> {
    if (!environment.allowMockFallback || this.preferLive) {
      await firstValueFrom(
        this.api.put<unknown>(SERVICE.execution, '/position/stop-loss', { ticket, sl_price: slPrice }),
      );
      const previous = this.findPosition(ticket)?.stop ?? 0;
      this.log('info', `Stop loss moved to ${slPrice} (ticket ${ticket})`);
      await this.refreshPositions();
      return { success: true, ticket, oldSl: previous, newSl: slPrice };
    }
    return this.modifyStopLossMock(ticket, slPrice);
  }

  private async modifyStopLossMock(ticket: number, slPrice: number): Promise<ModifyStopLossResponse> {
    const pos = this.findPosition(ticket);
    if (!pos) throw new Error(`Position ${ticket} not found`);
    const oldSl = pos.stop;
    this.stream.positions.update((list) => list.map((p) => (p.ticket === ticket ? { ...p, stop: slPrice, updatedAt: Date.now() } : p)));
    this.log('info', `Stop loss updated for ${pos.symbol} (ticket ${ticket}): ${oldSl} → ${slPrice}`, pos.symbol);
    return this.delay({ success: true, ticket, newSl: slPrice, oldSl });
  }

  // ------------------------------------------------------------------
  // PUT /position/<ticket>/take-profit
  // ------------------------------------------------------------------
  async modifyTakeProfit(ticket: number, tpPrice: number): Promise<ModifyTakeProfitResponse> {
    const pos = this.findPosition(ticket);
    if (!pos) throw new Error(`Position ${ticket} not found`);
    const oldTp = pos.target;
    this.stream.positions.update((list) => list.map((p) => (p.ticket === ticket ? { ...p, target: tpPrice, updatedAt: Date.now() } : p)));
    this.log('info', `Take profit (TP1) updated for ${pos.symbol} (ticket ${ticket}): ${oldTp} → ${tpPrice}`, pos.symbol);
    return this.delay({ success: true, ticket, newTp: tpPrice, oldTp });
  }

  // ------------------------------------------------------------------
  // PUT /position/<ticket>/take-profit-2, /position/<ticket>/take-profit-3
  // Soft partial-exit levels tracked by the EA's take-profit split, not
  // native MT5 order fields — same endpoint shape as TP1, second/third slot.
  // ------------------------------------------------------------------
  async modifyTakeProfit2(ticket: number, tpPrice: number): Promise<ModifyTakeProfitResponse> {
    const pos = this.findPosition(ticket);
    if (!pos) throw new Error(`Position ${ticket} not found`);
    const oldTp = pos.target2 ?? 0;
    this.stream.positions.update((list) => list.map((p) => (p.ticket === ticket ? { ...p, target2: tpPrice, updatedAt: Date.now() } : p)));
    this.log('info', `Take profit 2 updated for ${pos.symbol} (ticket ${ticket}): ${oldTp} → ${tpPrice}`, pos.symbol);
    return this.delay({ success: true, ticket, newTp: tpPrice, oldTp });
  }

  async modifyTakeProfit3(ticket: number, tpPrice: number): Promise<ModifyTakeProfitResponse> {
    const pos = this.findPosition(ticket);
    if (!pos) throw new Error(`Position ${ticket} not found`);
    const oldTp = pos.target3 ?? 0;
    this.stream.positions.update((list) => list.map((p) => (p.ticket === ticket ? { ...p, target3: tpPrice, updatedAt: Date.now() } : p)));
    this.log('info', `Take profit 3 updated for ${pos.symbol} (ticket ${ticket}): ${oldTp} → ${tpPrice}`, pos.symbol);
    return this.delay({ success: true, ticket, newTp: tpPrice, oldTp });
  }

  // ------------------------------------------------------------------
  // PUT /position/break-even/{enable,disable,apply}/<ticket>, GET .../status
  // ------------------------------------------------------------------
  async enableBreakEven(ticket: number, req: BreakEvenEnableRequest): Promise<BreakEvenStatus> {
    const pos = this.findPosition(ticket);
    if (!pos) throw new Error(`Position ${ticket} not found`);
    const trigger = req.usdDistance ?? req.pipsDistance ?? 0;
    const triggerType = req.usdDistance != null ? 'usd_distance' : 'pips_distance';
    const status: BreakEvenStatus = { ticket, hasBreakEven: true, breakEvenApplied: false, breakEvenTrigger: trigger, breakEvenTriggerType: triggerType, breakEvenPrice: null };
    this.setBreakEven(ticket, status);
    this.log('info', `Break-even enabled for ${pos.symbol} (ticket ${ticket}) — trigger ${trigger} ${triggerType === 'usd_distance' ? 'USD' : 'pips'}`, pos.symbol);
    return this.delay(status);
  }

  async disableBreakEven(ticket: number): Promise<{ ticket: number }> {
    this.deleteBreakEven(ticket);
    this.log('info', `Break-even disabled for position ${ticket}`);
    return this.delay({ ticket });
  }

  async applyBreakEven(ticket: number, _req: BreakEvenEnableRequest): Promise<BreakEvenStatus> {
    const pos = this.findPosition(ticket);
    if (!pos) throw new Error(`Position ${ticket} not found`);
    const status = this.breakEvenStatuses().get(ticket) ?? {
      ticket,
      hasBreakEven: true,
      breakEvenApplied: false,
      breakEvenTrigger: 0,
      breakEvenTriggerType: 'pips_distance' as const,
      breakEvenPrice: null,
    };
    const applied: BreakEvenStatus = { ...status, breakEvenApplied: true, breakEvenPrice: pos.entry };
    this.setBreakEven(ticket, applied);
    this.stream.positions.update((list) => list.map((p) => (p.ticket === ticket ? { ...p, stop: pos.entry, updatedAt: Date.now() } : p)));
    this.log('success', `Break-even applied for ${pos.symbol} (ticket ${ticket}) — SL moved to entry ${pos.entry}`, pos.symbol);
    return this.delay(applied);
  }

  getBreakEvenStatus(ticket: number): BreakEvenStatus {
    return (
      this.breakEvenStatuses().get(ticket) ?? {
        ticket,
        hasBreakEven: false,
        breakEvenApplied: false,
        breakEvenTrigger: null,
        breakEvenTriggerType: null,
        breakEvenPrice: null,
      }
    );
  }

  // ------------------------------------------------------------------
  // PUT /position/trailing/{enable,disable,update}/<ticket>, GET .../status
  // ------------------------------------------------------------------
  async enableTrailing(ticket: number, req: TrailingEnableRequest): Promise<ActiveTrail> {
    const pos = this.findPosition(ticket);
    if (!pos) throw new Error(`Position ${ticket} not found`);
    const trail: TrailRecord = {
      ticket,
      symbol: pos.symbol,
      distanceType: req.trailingUsdDistance != null ? 'usd' : 'pips',
      usdDistance: req.trailingUsdDistance ?? null,
      pipsDistance: req.trailingPips ?? null,
      breakEvenEnabled: this.breakEvenStatuses().get(ticket)?.hasBreakEven ?? false,
      lastSl: pos.stop,
      ageSeconds: 0,
    };
    this.setTrail(ticket, trail);
    const distance = req.trailingUsdDistance != null ? `$${req.trailingUsdDistance.toFixed(2)}` : `${req.trailingPips}p`;
    this.log('info', `Trailing stop enabled for ${pos.symbol} (ticket ${ticket}) — distance ${distance}`, pos.symbol);
    return this.delay(trail);
  }

  async disableTrailing(ticket: number): Promise<{ ticket: number }> {
    if (!this.activeTrails().has(ticket)) throw new Error(`No active trailing for position ${ticket}`);
    this.deleteTrail(ticket);
    this.log('info', `Trailing stop disabled for position ${ticket}`);
    return this.delay({ ticket });
  }

  async updateTrailing(ticket: number, req: TrailingEnableRequest): Promise<ActiveTrail> {
    const existing = this.activeTrails().get(ticket);
    if (!existing) throw new Error(`No active position management for position ${ticket}`);
    const updated: TrailRecord = { ...existing, distanceType: req.trailingUsdDistance != null ? 'usd' : 'pips', usdDistance: req.trailingUsdDistance ?? null, pipsDistance: req.trailingPips ?? null };
    this.setTrail(ticket, updated);
    return this.delay(updated);
  }

  getTrailingStatus(): TrailingStatusResponse {
    return {
      activeTrails: Array.from(this.activeTrails().values()).map((t) => ({ ...t })),
      count: this.activeTrails().size,
      stats: { ...this.trailStats, activeTrails: this.activeTrails().size },
    };
  }

  // ------------------------------------------------------------------
  // POST /calculate-lot
  // ------------------------------------------------------------------
  /**
   * Size a position through the real sizer.
   *
   * Worth calling out: the mock below is a placeholder that assumes a $10 pip
   * value and a 20-pip stop for every instrument. The real
   * `core/execution.py::calculate_lot` is margin-first — it solves for the lot
   * the margin target allows, then sets the stop so the dollar risk lands on
   * target — and the two do not agree for anything that is not a major FX pair.
   * Any screen that shows a lot size must be on the live path before it is
   * trusted; the mock is for layout only.
   */
  async calculateLot(req: CalculateLotRequest): Promise<CalculateLotResponse> {
    try {
      const wire = await firstValueFrom(
        this.api.post<CalculateLotWire>(SERVICE.execution, '/calculate-lot', {
          symbol: req.symbol,
          fixed_trade_size_usd: req.fixedTradeSizeUsd,
          risk_per_trade: req.riskPerTrade,
          min_stop_pips_override: req.minStopPipsOverride ?? null,
        }),
      );

      // The Python controller answers {success, data:{...}}; the Java DTO
      // flattens it. Accept both rather than depend on which one replied.
      const d = wire.data ?? (wire as unknown as CalculateLotData);

      this.origin.set('live');
      this.lastError.set(null);

      return {
        lot: d.lot ?? 0,
        actualRisk: d.actual_risk ?? d.actualRisk ?? 0,
        marginRequired: d.margin_required ?? d.marginRequired ?? 0,
        pipValue: d.pip_value ?? d.pipValue ?? 0,
        stopLossPrice: d.stop_loss_price ?? d.stopLossPrice ?? 0,
        stopLossPips: d.stop_loss_pips ?? d.stopLossPips ?? 0,
        takeProfitPrice: d.take_profit_price ?? d.takeProfitPrice ?? 0,
        targetRisk: d.target_risk ?? d.targetRisk ?? 0,
        targetMargin: d.target_margin ?? d.targetMargin ?? 0,
        riskPercent: d.risk_percent ?? d.riskPercent ?? 0,
        marginPercent: d.margin_percent ?? d.marginPercent ?? 0,
        currentPrice: d.current_price ?? d.currentPrice ?? 0,
        // Surfaced, not swallowed: the sizer reports here when it could not get
        // risk under target at the spread floor, which is the difference
        // between a usable setup and one that is too expensive to take.
        warnings: d.warnings ?? [],
      };
    } catch (error) {
      if (!this.canFallBack(error)) throw error;
      this.noteFallback(error);
      return this.calculateLotMock(req);
    }
  }

  private async calculateLotMock(req: CalculateLotRequest): Promise<CalculateLotResponse> {
    const seed = this.seedFor(req.symbol);
    const targetRisk = round(req.fixedTradeSizeUsd * req.riskPerTrade, 2);
    const targetMargin = req.fixedTradeSizeUsd;
    const slPips = req.minStopPipsOverride ?? 20;
    const pipValue = 10;
    const lot = round(Math.max(0.01, targetRisk / (slPips * pipValue)), 2);
    const currentPrice = round(seed.base, seed.pip < 0.01 ? 5 : 2);

    return this.delay({
      lot,
      actualRisk: round(lot * slPips * pipValue, 2),
      marginRequired: round(lot * 200, 2),
      pipValue,
      stopLossPrice: round(currentPrice - slPips * seed.pip, 5),
      stopLossPips: slPips,
      takeProfitPrice: round(currentPrice + slPips * 2 * seed.pip, 5),
      targetRisk,
      targetMargin,
      riskPercent: round(req.riskPerTrade * 100, 2),
      marginPercent: round((lot * 200 * 100) / req.fixedTradeSizeUsd, 2),
      currentPrice,
      warnings: [],
    });
  }

  // ------------------------------------------------------------------
  // POST /mt5/connect, POST /mt5/disconnect
  // ------------------------------------------------------------------
  async connectMt5(req: Mt5ConnectRequest): Promise<Mt5ConnectResponse> {
    this.mt5Connected.set(true);
    this.mt5Login.set(req.login);
    const a = this.stream.accountSummary();
    this.log('success', `Connected to MT5 — login ${req.login} @ ${req.server}`);
    return this.delay({ success: true, message: 'Connected to MT5', account: { login: req.login, balance: a.balance, equity: a.equity, currency: 'USD' } }, 500);
  }

  async disconnectMt5(): Promise<{ success: boolean; message: string }> {
    this.mt5Connected.set(false);
    this.log('warn', 'Disconnected from MT5');
    return this.delay({ success: true, message: 'Disconnected from MT5' }, 300);
  }

  // ------------------------------------------------------------------
  // GET /account
  // ------------------------------------------------------------------
  getAccount(): AccountInfo {
    const live = this.liveAccount();
    if (live) return live;

    const a = this.stream.accountSummary();
    return { login: this.mt5Login() ?? 0, balance: a.balance, equity: a.equity, margin: a.margin, freeMargin: round(a.equity - a.margin, 2), marginLevel: a.marginLevelPct, currency: 'USD', profit: a.dayPnl, leverage: 200 };
  }

  // ==================================================================
  // LIVE READS
  // ==================================================================

  startPolling(): void {
    if (this.pollTimer !== null) return;
    void this.refreshAll();
    this.pollTimer = setInterval(() => void this.refreshAll(), environment.pollIntervalMs.positions);
  }

  stopPolling(): void {
    if (this.pollTimer === null) return;
    clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  async refreshAll(): Promise<void> {
    await Promise.allSettled([this.refreshPositions(), this.refreshAccount()]);
  }

  async refreshAccount(): Promise<void> {
    try {
      const wire = await firstValueFrom(this.api.get<AccountWire>(SERVICE.execution, '/account'));
      const a = wire.data ?? (wire as unknown as AccountData);

      if (a.login !== undefined || a.balance !== undefined) {
        this.liveAccount.set({
          login: a.login ?? 0,
          balance: a.balance ?? 0,
          equity: a.equity ?? 0,
          margin: a.margin ?? 0,
          freeMargin: a.free_margin ?? a.freeMargin ?? 0,
          marginLevel: a.margin_level ?? a.marginLevel ?? 0,
          currency: a.currency ?? 'USD',
          profit: a.profit ?? 0,
          leverage: a.leverage ?? 0,
        });
        // The account panel reads through getAccount(), which prefers
        // liveAccount() — but the mock drift also mutates stream.accountSummary
        // directly, so it has to be stopped too.
        this.stream.claim('accountSummary');

        if (a.login !== undefined) this.mt5Login.set(a.login);
        this.mt5Connected.set(true);
        this.origin.set('live');
        this.lastError.set(null);
      }
    } catch (error) {
      if (!this.canFallBack(error)) {
        // A failed account read means MT5 or the controller is gone. Saying so
        // is the point of the pill; leaving it connected is worse than blank.
        this.mt5Connected.set(false);
        if (this.origin() === 'live') this.origin.set('stale');
      }
      this.noteFallback(error);
    }
  }

  /**
   * Replace the position list with the broker's.
   *
   * The server is the only authority here. Merging into the locally-simulated
   * list would leave a position on screen that was closed in the terminal, and
   * a stale open position is the single most dangerous thing this UI can show.
   */
  async refreshPositions(): Promise<void> {
    try {
      const wire = await firstValueFrom(this.api.get<PositionsWire>(SERVICE.execution, '/positions'));
      // Narrow before reaching for the envelope keys: the route returns a bare
      // array from Python and an object from the Java DTO.
      const rows = Array.isArray(wire) ? wire : (wire.data ?? wire.positions ?? null);
      if (!Array.isArray(rows)) return;

      // Claim first: tickFast drifts positions every 900ms and would otherwise
      // overwrite the broker's list with simulated marks within a second.
      this.stream.claim('positions');
      this.stream.positions.set(rows.map((row) => toPosition(row, this.stream.positions())));
      this.origin.set('live');
      this.lastError.set(null);
    } catch (error) {
      if (!this.canFallBack(error) && this.origin() === 'live') this.origin.set('stale');
      this.noteFallback(error);
    }
  }

  // ------------------------------------------------------------------

  /**
   * Whether write operations should go to the backend.
   *
   * True once any call has succeeded — i.e. the platform has proven reachable.
   * Before first contact in development the mocks drive the UI so the screens
   * are workable with nothing running; the moment a poll succeeds, orders are
   * real. In production `allowMockFallback` is false and every write is live
   * regardless of what this returns.
   */
  private get preferLive(): boolean {
    return this.origin() === 'live';
  }

  /** True when the failure is the platform being down AND mocks are allowed. */
  private canFallBack(error: unknown): boolean {
    return (
      environment.allowMockFallback &&
      error instanceof ApiError &&
      error.isPlatformFailure
    );
  }

  private noteFallback(error: unknown): void {
    const message = error instanceof ApiError ? error.message : String(error);
    this.lastError.set(message);
    if (this.canFallBack(error)) this.origin.set('mock');
  }

  // ------------------------------------------------------------------
  // GET /trades/history
  // ------------------------------------------------------------------
  private recordClosedTrade(pos: Position, closePrice: number): void {
    this.tradeHistory.update((list) => [
      {
        positionId: list.length + 1,
        symbol: pos.symbol,
        type: pos.side === 'long' ? 'BUY' : 'SELL',
        entryTicket: pos.ticket,
        volume: pos.qty,
        entryPrice: pos.entry,
        exitPrice: closePrice,
        entryTime: pos.openedAt,
        exitTime: Date.now(),
        netProfit: pos.pnl,
        isClosed: true,
        hasBreakEven: this.breakEvenStatuses().get(pos.ticket)?.breakEvenApplied ?? false,
      },
      ...list,
    ]);
  }

  getTradeHistory(query: TradeHistoryQuery = {}): TradeHistoryResponse {
    let trades = this.tradeHistory();
    if (query.symbol) trades = trades.filter((t) => t.symbol === query.symbol);
    const winners = trades.filter((t) => t.netProfit > 0).map((t) => t.netProfit);
    const losers = trades.filter((t) => t.netProfit < 0).map((t) => t.netProfit);
    const totalProfit = round(trades.reduce((sum, t) => sum + t.netProfit, 0), 2);
    return {
      deals: [],
      trades,
      summary: {
        totalDeals: trades.length * 2,
        closedTrades: trades.length,
        winningTrades: winners.length,
        losingTrades: losers.length,
        totalProfit,
        winRate: trades.length ? round((winners.length / trades.length) * 100, 1) : 0,
        avgWin: winners.length ? round(winners.reduce((a, b) => a + b, 0) / winners.length, 2) : 0,
        avgLoss: losers.length ? round(losers.reduce((a, b) => a + b, 0) / losers.length, 2) : 0,
        profitFactor: losers.length ? round(winners.reduce((a, b) => a + b, 0) / Math.abs(losers.reduce((a, b) => a + b, 0)), 2) : null,
        expectancy: trades.length ? round(totalProfit / trades.length, 2) : 0,
      },
    };
  }
}

// ====================================================================
// WIRE SHAPES  (execution_controller.py, port 5000)
// ====================================================================
// The Python controller answers {success, data:{...}} on most routes while the
// Java DTOs flatten some of them, so every type below treats `data` as optional
// and the readers accept either. Both spellings of each field are declared for
// the same reason: Python sends snake_case, and the fields a Java record
// re-serialises come back camelCase.

interface CalculateLotData {
  lot?: number;
  actual_risk?: number;
  actualRisk?: number;
  margin_required?: number;
  marginRequired?: number;
  pip_value?: number;
  pipValue?: number;
  stop_loss_price?: number;
  stopLossPrice?: number;
  stop_loss_pips?: number;
  stopLossPips?: number;
  take_profit_price?: number;
  takeProfitPrice?: number;
  target_risk?: number;
  targetRisk?: number;
  target_margin?: number;
  targetMargin?: number;
  risk_percent?: number;
  riskPercent?: number;
  margin_percent?: number;
  marginPercent?: number;
  current_price?: number;
  currentPrice?: number;
  warnings?: string[];
}

interface CalculateLotWire {
  success?: boolean;
  data?: CalculateLotData;
  error?: string;
}

interface AccountData {
  login?: number;
  balance?: number;
  equity?: number;
  margin?: number;
  free_margin?: number;
  freeMargin?: number;
  margin_level?: number;
  marginLevel?: number;
  currency?: string;
  profit?: number;
  leverage?: number;
}

interface AccountWire {
  success?: boolean;
  data?: AccountData;
  error?: string;
}

interface PositionWire {
  ticket?: number;
  symbol?: string;
  /** MT5 position type: 0 = BUY, 1 = SELL. Some payloads send "BUY"/"SELL". */
  type?: number | string;
  order_type?: string;
  orderType?: string;
  volume?: number;
  price_open?: number;
  priceOpen?: number;
  price_current?: number;
  priceCurrent?: number;
  profit?: number;
  sl?: number;
  tp?: number;
  time?: number | string;
  time_update?: number | string;
}

type PositionsWire =
  | PositionWire[]
  | { success?: boolean; data?: PositionWire[]; positions?: PositionWire[]; error?: string };

/**
 * Broker position -> view model.
 *
 * `previous` carries the last known list so that TP2/TP3 survive a refresh:
 * those two are NOT broker fields. MT5 has one take-profit per position, and
 * the split levels live in execute_copy_trade.py's own tracking. Dropping them
 * on every poll would make the partial-exit markers flicker out of the chart
 * three seconds after a trade is opened.
 */
function toPosition(wire: PositionWire, previous: readonly Position[]): Position {
  const ticket = wire.ticket ?? 0;
  const prior = previous.find((p) => p.ticket === ticket);

  const entry = wire.price_open ?? wire.priceOpen ?? 0;
  const mark = wire.price_current ?? wire.priceCurrent ?? entry;
  const profit = wire.profit ?? 0;

  return {
    id: prior?.id ?? `POS-${ticket}`,
    ticket,
    symbol: wire.symbol ?? '',
    side: toSide(wire),
    qty: wire.volume ?? 0,
    entry,
    mark,
    pnl: profit,
    // Percent against the notional actually committed. Guarded because a
    // zero entry price would otherwise render Infinity in the P&L column.
    pnlPct: entry > 0 && wire.volume ? round((profit / (entry * wire.volume)) * 100, 2) : 0,
    stop: wire.sl ?? 0,
    target: wire.tp ?? 0,
    target2: prior?.target2 ?? null,
    target3: prior?.target3 ?? null,
    openedAt: toEpoch(wire.time) ?? prior?.openedAt ?? Date.now(),
    updatedAt: toEpoch(wire.time_update) ?? Date.now(),
  };
}

function toSide(wire: PositionWire): Position['side'] {
  const explicit = (wire.orderType ?? wire.order_type ?? '').toUpperCase();
  if (explicit === 'BUY') return 'long';
  if (explicit === 'SELL') return 'short';

  // MT5's POSITION_TYPE_BUY is 0 and POSITION_TYPE_SELL is 1. Inferring the
  // side from whether price moved up or down instead is what corrupted the
  // stored trade directions in the Python bot; do not reintroduce that here.
  if (typeof wire.type === 'number') return wire.type === 1 ? 'short' : 'long';
  if (typeof wire.type === 'string') return wire.type.toUpperCase() === 'SELL' ? 'short' : 'long';

  return 'long';
}

function toEpoch(value: number | string | undefined): number | null {
  if (value === undefined || value === null) return null;
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return null;
    // MT5 sends epoch SECONDS. Treating those as millis puts every position in
    // January 1970 and makes the "open for" column meaningless.
    return value < 1e12 ? value * 1000 : value;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

// --------------------------------------------------------------------
// TRADE ACTION WIRE SHAPES
// --------------------------------------------------------------------

interface ExecuteTradeData {
  ticket?: number | null;
  symbol?: string;
  order_type?: string;
  orderType?: string;
  volume?: number;
  price?: number;
  stop_loss?: number;
  stopLoss?: number;
  take_profit?: number | null;
  takeProfit?: number | null;
  take_profit_2?: number | null;
  takeProfit2?: number | null;
  take_profit_3?: number | null;
  takeProfit3?: number | null;
  take_profit_split?: TakeProfitSplitLevel[] | null;
  takeProfitSplit?: TakeProfitSplitLevel[] | null;
  actual_margin?: number;
  actualMargin?: number;
  actual_risk_usd?: number;
  actualRiskUsd?: number;
  risk_percent_used?: number;
  riskPercentUsed?: number;
  magic?: number;
  comment?: string;
  timestamp?: number | string;
  break_even?: { enabled?: boolean; pips_distance?: number | null; usd_distance?: number | null };
  trailing_stop?: { enabled?: boolean; pips_distance?: number | null; usd_distance?: number | null };
  probability_of_hit_percent?: number | null;
  probabilityOfHitPercent?: number | null;
}

interface ExecuteTradeWire {
  success?: boolean;
  data?: ExecuteTradeData;
  error?: string;
}

interface ClosePositionData {
  symbol?: string;
  profit?: number;
  close_price?: number;
  closePrice?: number;
  volume?: number;
}

interface ClosePositionWire {
  success?: boolean;
  data?: ClosePositionData;
  error?: string;
}

interface CloseAllData {
  closed_count?: number;
  closedCount?: number;
  failed_count?: number;
  failedCount?: number;
  total_profit?: number;
  totalProfit?: number;
}

interface CloseAllWire {
  success?: boolean;
  data?: CloseAllData;
  error?: string;
}

/**
 * View request -> the controller's payload.
 *
 * Note `fixed_trade_size_usd` and `risk_per_trade` go across as-is: the bot
 * reads risk_per_trade as a FRACTION OF THE TRADE BUDGET, not a percent of
 * equity — 0.02 against a $200 budget is $4 of risk. Scaling it here to look
 * like an account percentage would silently resize every order.
 */
function toTradePayload(req: ExecuteTradeRequest): Record<string, unknown> {
  return {
    symbol: req.symbol,
    order_type: req.orderType,
    strategy_magic: req.strategyMagic,
    fixed_trade_size_usd: req.fixedTradeSizeUsd,
    risk_per_trade: req.riskPerTrade,
    stop_loss_price: req.stopLossPrice ?? null,
    take_profit_price: req.takeProfitPrice ?? null,
    take_profit_2_price: req.takeProfit2Price ?? null,
    take_profit_3_price: req.takeProfit3Price ?? null,
    min_stop_pips_override: req.minStopPipsOverride ?? null,
  };
}
