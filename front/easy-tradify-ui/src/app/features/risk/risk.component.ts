import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { PanelComponent } from '../../shared/panel/panel.component';
import { StatusPillComponent } from '../../shared/status-pill/status-pill.component';
import { PortfolioApiService } from '../../core/services/api/portfolio-api.service';
import { PortfolioConfig, TradingAllowedCheck } from '../../core/models/portfolio.model';

type Tab = 'status' | 'settings';

@Component({
  selector: 'app-risk',
  standalone: true,
  imports: [FormsModule, DecimalPipe, PanelComponent, StatusPillComponent],
  templateUrl: './risk.component.html',
  styleUrl: './risk.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RiskComponent {
  protected readonly api = inject(PortfolioApiService);

  protected readonly tab = signal<Tab>('status');
  protected readonly draft = signal<PortfolioConfig>({ ...this.api.getConfig() });
  protected readonly saving = signal(false);
  protected readonly justSaved = signal(false);

  protected readonly refreshing = signal(false);

  protected readonly checkRiskPercent = signal(5);
  protected readonly checking = signal(false);
  protected readonly checkResult = signal<TradingAllowedCheck | null>(null);

  protected setTab(tab: Tab): void {
    this.tab.set(tab);
    if (tab === 'settings') this.draft.set({ ...this.api.getConfig() });
  }

  protected async refreshStatus(): Promise<void> {
    this.refreshing.set(true);
    try {
      await this.api.refresh();
    } finally {
      this.refreshing.set(false);
    }
  }

  protected async runCheck(): Promise<void> {
    this.checking.set(true);
    try {
      this.checkResult.set(await this.api.checkTradingAllowed(this.checkRiskPercent()));
    } finally {
      this.checking.set(false);
    }
  }

  protected patch<K extends keyof PortfolioConfig>(key: K, value: PortfolioConfig[K]): void {
    this.draft.update((d) => ({ ...d, [key]: value }));
  }

  protected async save(): Promise<void> {
    this.saving.set(true);
    try {
      await this.api.updateConfig(this.draft());
      this.justSaved.set(true);
      setTimeout(() => this.justSaved.set(false), 1500);
    } finally {
      this.saving.set(false);
    }
  }
}
