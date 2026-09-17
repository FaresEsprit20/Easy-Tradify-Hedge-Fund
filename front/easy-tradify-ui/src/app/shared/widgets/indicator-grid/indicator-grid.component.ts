import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IndicatorRecommendation, IndicatorResult } from '../../../core/models/api/analysis-api.model';
import { StatusPillComponent, PillVariant } from '../../status-pill/status-pill.component';

const VARIANT: Record<IndicatorRecommendation, PillVariant> = {
  BUY: 'jade',
  BULLISH: 'jade',
  SELL: 'coral',
  BEARISH: 'coral',
  NEUTRAL: 'muted',
};

@Component({
  selector: 'app-indicator-grid',
  standalone: true,
  imports: [StatusPillComponent],
  templateUrl: './indicator-grid.component.html',
  styleUrl: './indicator-grid.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class IndicatorGridComponent {
  readonly indicators = input<IndicatorResult[]>([]);

  protected variant(rec: IndicatorRecommendation): PillVariant {
    return VARIANT[rec];
  }
}
