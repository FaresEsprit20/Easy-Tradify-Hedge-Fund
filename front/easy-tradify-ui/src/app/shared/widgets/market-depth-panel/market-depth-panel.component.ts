import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MarketDepth } from '../../../core/models/market.model';

@Component({
  selector: 'app-market-depth-panel',
  standalone: true,
  imports: [DecimalPipe],
  templateUrl: './market-depth-panel.component.html',
  styleUrl: './market-depth-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MarketDepthPanelComponent {
  readonly depth = input<MarketDepth | null>(null);

  protected readonly maxSize = computed(() => {
    const d = this.depth();
    if (!d) return 1;
    return Math.max(1, ...d.bids.map((l) => l.size), ...d.asks.map((l) => l.size));
  });

  protected sizePct(size: number): number {
    return Math.round((size / this.maxSize()) * 100);
  }
}
