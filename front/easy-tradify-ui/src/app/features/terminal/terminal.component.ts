import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MockStreamService } from '../../core/services/mock-stream.service';
import { latestTimestamp } from '../../core/utils/latest-timestamp';
import { ConnectionService } from '../../core/services/connection.service';
import { CandleDataService } from '../../core/services/candle-data.service';
import { PanelComponent } from '../../shared/panel/panel.component';
import { WatchlistPanelComponent } from '../../shared/widgets/watchlist-panel/watchlist-panel.component';
import { PositionsPanelComponent } from '../../shared/widgets/positions-panel/positions-panel.component';
import { MarketDepthPanelComponent } from '../../shared/widgets/market-depth-panel/market-depth-panel.component';
import { OrderTicketPanelComponent } from '../../shared/widgets/order-ticket-panel/order-ticket-panel.component';
import { PriceChartComponent } from '../../shared/widgets/price-chart/price-chart.component';
import { CloseAllButtonComponent } from '../../shared/widgets/close-all-button/close-all-button.component';
import { TimeframeSelectorComponent } from '../../shared/widgets/timeframe-selector/timeframe-selector.component';
import { GateTickerComponent } from '../../shared/gate-ticker/gate-ticker.component';
import { ChartPriceLine } from '../../core/models/candle.model';
import { CHART_COLORS } from '../../core/chart-theme';
import { DEFAULT_TIMEFRAME, TIMEFRAME_SECONDS, Timeframe } from '../../core/data/timeframes';

@Component({
  selector: 'app-terminal',
  standalone: true,
  imports: [
    RouterLink,
    PanelComponent,
    WatchlistPanelComponent,
    PositionsPanelComponent,
    MarketDepthPanelComponent,
    OrderTicketPanelComponent,
    PriceChartComponent,
    CloseAllButtonComponent,
    TimeframeSelectorComponent,
    GateTickerComponent,
  ],
  templateUrl: './terminal.component.html',
  styleUrl: './terminal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TerminalComponent {
  protected readonly stream = inject(MockStreamService);
  protected readonly connection = inject(ConnectionService);
  private readonly candleData = inject(CandleDataService);

  protected readonly focusedSymbol = signal('XAUUSD');
  protected readonly timeframe = signal<Timeframe>(DEFAULT_TIMEFRAME);
  protected readonly candles = computed(() => this.candleData.generate(this.focusedSymbol(), 180, TIMEFRAME_SECONDS[this.timeframe()]));

  protected readonly priceLines = computed<ChartPriceLine[]>(() => {
    const snap = this.stream.analysisSnapshot();
    if (snap.symbol !== this.focusedSymbol()) return [];
    const lines: ChartPriceLine[] = [
      { price: snap.decision.entry, color: CHART_COLORS.amber, title: 'Entry' },
      { price: snap.decision.stop, color: CHART_COLORS.coral, title: 'Stop' },
    ];
    snap.decision.targets.forEach((t, i) => lines.push({ price: t, color: CHART_COLORS.jade, title: `TP${i + 1}` }));
    return lines;
  });

  protected readonly gatesUpdatedAt = computed(() => latestTimestamp(this.stream.gateEvents(), (e) => e.timestamp));

  protected focusSymbol(symbol: string): void {
    this.focusedSymbol.set(symbol);
  }
}
