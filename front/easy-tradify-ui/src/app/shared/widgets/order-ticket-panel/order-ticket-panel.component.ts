import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ExecutionApiService } from '../../../core/services/api/execution-api.service';
import { CalculateLotResponse, ExecuteTradeRequest, ExecuteTradeResponse, DistanceUnit } from '../../../core/models/api/execution-api.model';
import { SymbolPickerComponent } from '../symbol-picker/symbol-picker.component';

type Side = 'BUY' | 'SELL';

@Component({
  selector: 'app-order-ticket-panel',
  standalone: true,
  imports: [FormsModule, SymbolPickerComponent],
  templateUrl: './order-ticket-panel.component.html',
  styleUrl: './order-ticket-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrderTicketPanelComponent {
  private readonly execution = inject(ExecutionApiService);

  readonly symbol = input<string>('XAUUSD');
  /** Overrides where the built request is sent — e.g. copy-trade.component.ts
   * passes CopyTradeApiService.executeAndRegister so this same ticket can
   * drive either pipeline. Defaults to plain execution_controller.py-style
   * execution. */
  readonly executor = input<((req: ExecuteTradeRequest) => Promise<ExecuteTradeResponse>) | undefined>(undefined);
  readonly actionLabel = input<string | undefined>(undefined);

  protected readonly selectedSymbol = signal(this.symbol());
  protected readonly side = signal<Side>('BUY');

  constructor() {
    // Keeps the ticket's symbol linked to whatever the parent page has
    // focused (e.g. a watchlist click in Terminal) — same "linked ticket"
    // behavior real terminals use. A manual pick in the dropdown below
    // stays in effect until the next external focus change.
    effect(() => {
      this.selectedSymbol.set(this.symbol());
    });
  }

  protected readonly fixedTradeSizeUsd = signal(200);
  protected readonly riskPerTradePct = signal(5);

  protected readonly stopLossPrice = signal<number | null>(null);
  protected readonly takeProfit1 = signal<number | null>(null);
  protected readonly takeProfit2 = signal<number | null>(null);
  protected readonly takeProfit3 = signal<number | null>(null);

  protected readonly magic = signal(1001);
  protected readonly comment = signal('AI Trade');
  protected readonly deviation = signal(20);
  protected readonly maxSpread = signal(30);
  protected readonly maxTradesPerSymbol = signal(1);
  protected readonly maxSimultaneousTrades = signal(5);

  protected readonly breakEvenEnabled = signal(false);
  protected readonly breakEvenUnit = signal<DistanceUnit>('pips');
  protected readonly breakEvenValue = signal(15);

  protected readonly trailingEnabled = signal(false);
  protected readonly trailingUnit = signal<DistanceUnit>('pips');
  protected readonly trailingValue = signal(10);

  protected readonly previewing = signal(false);
  protected readonly lotPreview = signal<CalculateLotResponse | null>(null);

  protected readonly submitting = signal(false);
  protected readonly lastResult = signal<ExecuteTradeResponse | null>(null);
  protected readonly justSubmitted = signal(false);

  protected setSide(side: Side): void {
    this.side.set(side);
  }

  protected async previewLot(): Promise<void> {
    this.previewing.set(true);
    try {
      this.lotPreview.set(
        await this.execution.calculateLot({
          symbol: this.selectedSymbol(),
          fixedTradeSizeUsd: this.fixedTradeSizeUsd(),
          riskPerTrade: this.riskPerTradePct() / 100,
        }),
      );
    } finally {
      this.previewing.set(false);
    }
  }

  private buildRequest(): ExecuteTradeRequest {
    return {
      symbol: this.selectedSymbol(),
      orderType: this.side(),
      strategyMagic: this.magic(),
      fixedTradeSizeUsd: this.fixedTradeSizeUsd(),
      riskPerTrade: this.riskPerTradePct() / 100,
      maxSpread: this.maxSpread(),
      tradeDeviation: this.deviation(),
      maxTradesPerSymbol: this.maxTradesPerSymbol(),
      maxSimultaneousTrades: this.maxSimultaneousTrades(),
      comment: this.comment(),
      stopLossPrice: this.stopLossPrice() ?? undefined,
      takeProfitPrice: this.takeProfit1() ?? undefined,
      takeProfit2Price: this.takeProfit2() ?? undefined,
      takeProfit3Price: this.takeProfit3() ?? undefined,
      enableBreakEven: this.breakEvenEnabled(),
      breakEvenPipsDistance: this.breakEvenEnabled() && this.breakEvenUnit() === 'pips' ? this.breakEvenValue() : undefined,
      breakEvenUsdDistance: this.breakEvenEnabled() && this.breakEvenUnit() === 'usd' ? this.breakEvenValue() : undefined,
      enableTrailingStop: this.trailingEnabled(),
      trailingPips: this.trailingEnabled() && this.trailingUnit() === 'pips' ? this.trailingValue() : undefined,
      trailingUsdDistance: this.trailingEnabled() && this.trailingUnit() === 'usd' ? this.trailingValue() : undefined,
    };
  }

  protected async execute(): Promise<void> {
    this.submitting.set(true);
    try {
      const send = this.executor() ?? ((req: ExecuteTradeRequest) => this.execution.executeTrade(req));
      const result = await send(this.buildRequest());
      this.lastResult.set(result);
      this.justSubmitted.set(true);
      setTimeout(() => this.justSubmitted.set(false), 900);
    } finally {
      this.submitting.set(false);
    }
  }
}
