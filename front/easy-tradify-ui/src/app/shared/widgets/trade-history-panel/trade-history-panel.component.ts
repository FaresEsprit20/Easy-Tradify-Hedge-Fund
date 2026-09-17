import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ExecutionApiService } from '../../../core/services/api/execution-api.service';
import { SparklineComponent } from '../sparkline/sparkline.component';
import { GroupedTrade } from '../../../core/models/api/execution-api.model';

@Component({
  selector: 'app-trade-history-panel',
  standalone: true,
  imports: [DecimalPipe, SparklineComponent],
  templateUrl: './trade-history-panel.component.html',
  styleUrl: './trade-history-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TradeHistoryPanelComponent {
  private readonly execution = inject(ExecutionApiService);

  protected history() {
    return this.execution.getTradeHistory();
  }

  // Trades come back newest-first; the equity curve reads chronologically,
  // so walk it in reverse while accumulating net profit.
  protected cumulativePnl(trades: GroupedTrade[]): number[] {
    let running = 0;
    const series: number[] = [];
    for (let i = trades.length - 1; i >= 0; i--) {
      running += trades[i].netProfit;
      series.push(running);
    }
    return series;
  }

  protected formatTime(ts: number): string {
    const d = new Date(ts);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
  }
}
