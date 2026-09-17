import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { WatchlistItem } from '../../../core/models/market.model';
import { SparklineComponent } from '../sparkline/sparkline.component';
import { FlashOnUpdateDirective } from '../../directives/flash-on-update.directive';
import { ExecutionApiService } from '../../../core/services/api/execution-api.service';

type SortKey = 'symbol' | 'last' | 'changePct' | 'conviction';
type Side = 'BUY' | 'SELL';

const PAGE_SIZE = 20;

@Component({
  selector: 'app-watchlist-panel',
  standalone: true,
  imports: [SparklineComponent, FlashOnUpdateDirective, DecimalPipe, FormsModule],
  templateUrl: './watchlist-panel.component.html',
  styleUrl: './watchlist-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WatchlistPanelComponent {
  private readonly execution = inject(ExecutionApiService);

  readonly items = input<WatchlistItem[]>([]);
  readonly focusedSymbol = input<string | null>(null);
  readonly selected = output<string>();

  protected readonly quickTradeBusy = signal<string | null>(null);
  protected readonly quickTradeFlash = signal<{ symbol: string; side: Side } | null>(null);

  protected readonly sortKey = signal<SortKey>('symbol');
  protected readonly sortDir = signal<1 | -1>(1);
  protected readonly search = signal('');
  protected readonly page = signal(0);
  protected readonly pageSize = PAGE_SIZE;

  protected readonly filteredItems = computed(() => {
    const q = this.search().trim().toUpperCase();
    const key = this.sortKey();
    const dir = this.sortDir();
    const list = q ? this.items().filter((i) => i.symbol.includes(q)) : this.items();
    return [...list].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number);
      return cmp * dir;
    });
  });

  protected readonly pageCount = computed(() => Math.max(1, Math.ceil(this.filteredItems().length / this.pageSize)));

  protected readonly sortedItems = computed(() => {
    const start = this.page() * this.pageSize;
    return this.filteredItems().slice(start, start + this.pageSize);
  });

  constructor() {
    // Reset to page 0 on search/sort changes only — NOT on `items()`, which
    // ticks every ~900ms with live prices and would otherwise yank the user
    // back to page 0 mid-browse.
    effect(() => {
      this.search();
      this.sortKey();
      this.sortDir();
      this.page.set(0);
    });
  }

  protected sortBy(key: SortKey): void {
    if (this.sortKey() === key) {
      this.sortDir.update((d) => (d === 1 ? -1 : 1));
    } else {
      this.sortKey.set(key);
      this.sortDir.set(1);
    }
  }

  protected prevPage(): void {
    this.page.update((p) => Math.max(0, p - 1));
  }

  protected nextPage(): void {
    this.page.update((p) => Math.min(this.pageCount() - 1, p + 1));
  }

  protected sortIndicator(key: SortKey): string {
    if (this.sortKey() !== key) return '';
    return this.sortDir() === 1 ? '▲' : '▼';
  }

  protected convictionClass(v: number): string {
    if (v >= 70) return 'text-jade';
    if (v >= 40) return 'text-amber';
    return 'text-coral';
  }

  // One-click hotkey trade from the watchlist row — small fixed size, no
  // ticket to fill out, matching the "quick buy/sell" hot-button pattern of
  // a real desk terminal. Deliberately fires without a confirm step; that's
  // the point of a shortcut.
  protected async quickTrade(symbol: string, side: Side, event: Event): Promise<void> {
    event.stopPropagation();
    if (this.quickTradeBusy()) return;
    this.quickTradeBusy.set(symbol);
    try {
      await this.execution.executeTrade({
        symbol,
        orderType: side,
        strategyMagic: 9001,
        fixedTradeSizeUsd: 200,
        riskPerTrade: 0.02,
        maxSpread: 30,
        comment: 'Quick Trade',
      });
      this.quickTradeFlash.set({ symbol, side });
      setTimeout(() => {
        if (this.quickTradeFlash()?.symbol === symbol) this.quickTradeFlash.set(null);
      }, 900);
    } finally {
      this.quickTradeBusy.set(null);
    }
  }
}
