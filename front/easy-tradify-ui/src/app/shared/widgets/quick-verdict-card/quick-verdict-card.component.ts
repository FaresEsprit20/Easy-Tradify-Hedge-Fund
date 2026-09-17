import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { AnalysisSnapshot, DecisionVerdict } from '../../../core/models/analysis.model';
import { StatusPillComponent, PillVariant } from '../../status-pill/status-pill.component';

const VERDICT_VARIANT: Record<DecisionVerdict, PillVariant> = {
  BUY: 'jade',
  SELL: 'coral',
  HOLD: 'muted',
  VETO: 'amber',
};

@Component({
  selector: 'app-quick-verdict-card',
  standalone: true,
  imports: [DecimalPipe, StatusPillComponent],
  templateUrl: './quick-verdict-card.component.html',
  styleUrl: './quick-verdict-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class QuickVerdictCardComponent {
  readonly snapshot = input<AnalysisSnapshot | null>(null);
  readonly loading = input(false);

  protected variant(v: DecisionVerdict): PillVariant {
    return VERDICT_VARIANT[v];
  }

  protected stars(rating: number): string {
    return '★'.repeat(rating) + '☆'.repeat(Math.max(0, 5 - rating));
  }
}
