import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { AnalysisSnapshot, DecisionVerdict } from '../../../core/models/analysis.model';
import { StatusPillComponent, PillVariant } from '../../status-pill/status-pill.component';
import { InfoHintComponent } from '../../hint/info-hint.component';
import { GATE_HINTS, DECISION_HINTS } from '../../../core/data/hint-copy';

const VERDICT_VARIANT: Record<DecisionVerdict, PillVariant> = {
  BUY: 'jade',
  SELL: 'coral',
  HOLD: 'muted',
  VETO: 'amber',
};

@Component({
  selector: 'app-analysis-panel',
  standalone: true,
  imports: [DecimalPipe, StatusPillComponent, InfoHintComponent],
  templateUrl: './analysis-panel.component.html',
  styleUrl: './analysis-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnalysisPanelComponent {
  readonly snapshot = input.required<AnalysisSnapshot>();

  protected readonly hints = DECISION_HINTS;

  protected verdictVariant(v: DecisionVerdict): PillVariant {
    return VERDICT_VARIANT[v];
  }

  protected gateHint(gate: string): string {
    return GATE_HINTS[gate] ?? 'A pass/fail check the entry logic runs before allowing this trade.';
  }

  protected gatePillVariant(passed: boolean, nearMiss: boolean | null): PillVariant {
    if (!passed) return 'coral';
    if (nearMiss) return 'amber';
    return 'jade';
  }

  protected stars(rating: number): string {
    return '★'.repeat(rating) + '☆'.repeat(Math.max(0, 5 - rating));
  }

  protected ledgerColor(delta: number): 'text-jade' | 'text-coral' | '' {
    if (delta > 0) return 'text-jade';
    if (delta < 0) return 'text-coral';
    return '';
  }
}
