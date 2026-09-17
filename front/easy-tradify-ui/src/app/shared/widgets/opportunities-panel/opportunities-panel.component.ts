import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { Opportunity, PingVerdict } from '../../../core/models/scanner.model';
import { StatusPillComponent, PillVariant } from '../../status-pill/status-pill.component';

const VARIANT: Record<PingVerdict, PillVariant> = { pass: 'jade', near: 'amber', veto: 'coral' };

@Component({
  selector: 'app-opportunities-panel',
  standalone: true,
  imports: [StatusPillComponent],
  templateUrl: './opportunities-panel.component.html',
  styleUrl: './opportunities-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpportunitiesPanelComponent {
  readonly opportunities = input<Opportunity[]>([]);

  protected variant(v: PingVerdict): PillVariant {
    return VARIANT[v];
  }
}
