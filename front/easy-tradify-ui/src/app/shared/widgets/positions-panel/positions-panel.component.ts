import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Position } from '../../../core/models/position.model';
import { DistanceUnit } from '../../../core/models/api/execution-api.model';
import { ExecutionApiService } from '../../../core/services/api/execution-api.service';
import { StatusPillComponent } from '../../status-pill/status-pill.component';
import { FlashOnUpdateDirective } from '../../directives/flash-on-update.directive';
import { InfoHintComponent } from '../../hint/info-hint.component';

function round(value: number, decimals: number): number {
  const f = Math.pow(10, decimals);
  return Math.round(value * f) / f;
}

type SortKey = 'symbol' | 'qty' | 'entry' | 'mark' | 'pnl' | 'stop' | 'target';

const PAGE_SIZE = 15;

@Component({
  selector: 'app-positions-panel',
  standalone: true,
  imports: [DecimalPipe, FormsModule, StatusPillComponent, FlashOnUpdateDirective, InfoHintComponent],
  templateUrl: './positions-panel.component.html',
  styleUrl: './positions-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PositionsPanelComponent {
  private readonly execution = inject(ExecutionApiService);

  readonly positions = input<Position[]>([]);

  protected readonly sortKey = signal<SortKey>('symbol');
  protected readonly sortDir = signal<1 | -1>(1);
  protected readonly search = signal('');
  protected readonly page = signal(0);
  protected readonly pageSize = PAGE_SIZE;

  protected readonly filteredPositions = computed(() => {
    const q = this.search().trim().toUpperCase();
    const key = this.sortKey();
    const dir = this.sortDir();
    const list = q ? this.positions().filter((p) => p.symbol.includes(q)) : this.positions();
    return [...list].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number);
      return cmp * dir;
    });
  });

  protected readonly pageCount = computed(() => Math.max(1, Math.ceil(this.filteredPositions().length / this.pageSize)));

  protected readonly sortedPositions = computed(() => {
    const start = this.page() * this.pageSize;
    return this.filteredPositions().slice(start, start + this.pageSize);
  });

  constructor() {
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

  protected readonly expanded = signal<number | null>(null);
  protected readonly confirmClose = signal<number | null>(null);
  protected readonly busy = signal<number | null>(null);

  protected readonly partialQty = signal(0);
  protected readonly slValue = signal(0);
  protected readonly tp1Value = signal(0);
  protected readonly tp2Value = signal(0);
  protected readonly tp3Value = signal(0);
  protected readonly beUnit = signal<DistanceUnit>('pips');
  protected readonly beValue = signal(10);
  protected readonly trailUnit = signal<DistanceUnit>('pips');
  protected readonly trailValue = signal(10);

  protected breakEvenStatus(ticket: number) {
    return this.execution.breakEvenStatuses().get(ticket);
  }

  protected trailStatus(ticket: number) {
    return this.execution.activeTrails().get(ticket);
  }

  protected toggleExpand(pos: Position): void {
    if (this.expanded() === pos.ticket) {
      this.expanded.set(null);
      return;
    }
    this.expanded.set(pos.ticket);
    this.confirmClose.set(null);
    this.partialQty.set(round(pos.qty / 2, 2));
    this.slValue.set(pos.stop);
    this.tp1Value.set(pos.target);
    this.tp2Value.set(pos.target2 ?? pos.target);
    this.tp3Value.set(pos.target3 ?? pos.target);
  }

  protected requestClose(ticket: number): void {
    if (this.confirmClose() === ticket) {
      void this.doClose(ticket);
      return;
    }
    this.confirmClose.set(ticket);
    setTimeout(() => {
      if (this.confirmClose() === ticket) this.confirmClose.set(null);
    }, 3000);
  }

  private async doClose(ticket: number): Promise<void> {
    this.busy.set(ticket);
    try {
      await this.execution.closePosition(ticket);
    } finally {
      this.busy.set(null);
      this.confirmClose.set(null);
      this.expanded.set(null);
    }
  }

  protected async doPartialClose(pos: Position): Promise<void> {
    if (this.partialQty() <= 0 || this.partialQty() >= pos.qty) return;
    this.busy.set(pos.ticket);
    try {
      await this.execution.partialClosePosition(pos.ticket, this.partialQty());
    } finally {
      this.busy.set(null);
    }
  }

  protected async saveSl(pos: Position): Promise<void> {
    this.busy.set(pos.ticket);
    try {
      await this.execution.modifyStopLoss(pos.ticket, this.slValue());
    } finally {
      this.busy.set(null);
    }
  }

  protected async saveTp1(pos: Position): Promise<void> {
    this.busy.set(pos.ticket);
    try {
      await this.execution.modifyTakeProfit(pos.ticket, this.tp1Value());
    } finally {
      this.busy.set(null);
    }
  }

  protected async saveTp2(pos: Position): Promise<void> {
    this.busy.set(pos.ticket);
    try {
      await this.execution.modifyTakeProfit2(pos.ticket, this.tp2Value());
    } finally {
      this.busy.set(null);
    }
  }

  protected async saveTp3(pos: Position): Promise<void> {
    this.busy.set(pos.ticket);
    try {
      await this.execution.modifyTakeProfit3(pos.ticket, this.tp3Value());
    } finally {
      this.busy.set(null);
    }
  }

  protected async toggleBreakEven(pos: Position): Promise<void> {
    const status = this.breakEvenStatus(pos.ticket);
    this.busy.set(pos.ticket);
    try {
      if (status?.hasBreakEven) {
        await this.execution.disableBreakEven(pos.ticket);
      } else {
        await this.execution.enableBreakEven(pos.ticket, this.beUnit() === 'usd' ? { usdDistance: this.beValue() } : { pipsDistance: this.beValue() });
      }
    } finally {
      this.busy.set(null);
    }
  }

  protected async toggleTrailing(pos: Position): Promise<void> {
    const status = this.trailStatus(pos.ticket);
    this.busy.set(pos.ticket);
    try {
      if (status) {
        await this.execution.disableTrailing(pos.ticket);
      } else {
        await this.execution.enableTrailing(pos.ticket, this.trailUnit() === 'usd' ? { trailingUsdDistance: this.trailValue() } : { trailingPips: this.trailValue() });
      }
    } finally {
      this.busy.set(null);
    }
  }
}
