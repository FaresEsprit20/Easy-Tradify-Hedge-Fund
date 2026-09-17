import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { PanelComponent } from '../../shared/panel/panel.component';
import { OrderTicketPanelComponent } from '../../shared/widgets/order-ticket-panel/order-ticket-panel.component';
import { QuickVerdictCardComponent } from '../../shared/widgets/quick-verdict-card/quick-verdict-card.component';
import { SymbolPickerComponent } from '../../shared/widgets/symbol-picker/symbol-picker.component';
import { CopyTradeApiService } from '../../core/services/api/copy-trade-api.service';
import { AnalysisApiService } from '../../core/services/api/analysis-api.service';
import { ExecuteTradeRequest, ExecuteTradeResponse } from '../../core/models/api/execution-api.model';
import { AnalysisSnapshot } from '../../core/models/analysis.model';

@Component({
  selector: 'app-copy-trade',
  standalone: true,
  imports: [FormsModule, RouterLink, PanelComponent, OrderTicketPanelComponent, QuickVerdictCardComponent, SymbolPickerComponent],
  templateUrl: './copy-trade.component.html',
  styleUrl: './copy-trade.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CopyTradeComponent {
  protected readonly copyTrade = inject(CopyTradeApiService);
  private readonly analysisApi = inject(AnalysisApiService);

  protected readonly analyzeSymbol = signal('EURUSD');
  protected readonly analyzeSide = signal<'BUY' | 'SELL'>('BUY');
  protected readonly analyzing = signal(false);
  protected readonly analysisResult = signal<AnalysisSnapshot | null>(null);

  protected readonly executor = (req: ExecuteTradeRequest): Promise<ExecuteTradeResponse> => this.copyTrade.executeAndRegister(req);

  async runAnalysis(): Promise<void> {
    this.analyzing.set(true);
    try {
      this.analysisResult.set(
        await this.analysisApi.analyse({
          symbol: this.analyzeSymbol(),
          orderType: this.analyzeSide(),
          fixedTradeSizeUsd: 200,
          riskPerTrade: 0.05,
          timeframe: 'M1',
        }),
      );
    } finally {
      this.analyzing.set(false);
    }
  }
}
