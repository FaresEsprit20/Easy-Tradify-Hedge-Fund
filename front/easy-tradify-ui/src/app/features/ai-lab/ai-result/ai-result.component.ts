import { DatePipe, DecimalPipe, JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { PanelComponent } from '../../../shared/panel/panel.component';
import { PillVariant, StatusPillComponent } from '../../../shared/status-pill/status-pill.component';
import { AiRunResult, RunOutcome } from '../../../core/models/ai.model';

/**
 * The result of a run, plus the session's run history.
 *
 * Split out of AiLabComponent so each half stays within the project's 4 kB
 * per-component style budget, and because presenting a result is a genuinely
 * separate concern from choosing and parameterising an operation.
 */
@Component({
  selector: 'app-ai-result',
  standalone: true,
  imports: [JsonPipe, DatePipe, DecimalPipe, PanelComponent, StatusPillComponent],
  templateUrl: './ai-result.component.html',
  styleUrl: './ai-result.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AiResultComponent {
  readonly result = input<AiRunResult | null>(null);
  readonly history = input<readonly AiRunResult[]>([]);

  protected variant(outcome: RunOutcome): PillVariant {
    switch (outcome) {
      case 'ok':
        return 'jade';
      case 'inconclusive':
        return 'amber';
      case 'refused':
        return 'info';
      default:
        return 'coral';
    }
  }

  /**
   * Spelled out rather than shortened. "Inconclusive" is the answer this engine
   * gives most often — too few trades to test — and reading it as either a pass
   * or a failure is how an empty collection comes to look like a finding.
   */
  protected label(outcome: RunOutcome): string {
    switch (outcome) {
      case 'ok':
        return 'OK';
      case 'inconclusive':
        return 'INCONCLUSIVE';
      case 'refused':
        return 'REFUSED';
      default:
        return 'ERROR';
    }
  }
}
