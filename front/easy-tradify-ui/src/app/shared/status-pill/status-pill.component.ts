import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export type PillVariant = 'jade' | 'coral' | 'amber' | 'info' | 'muted';

@Component({
  selector: 'app-status-pill',
  standalone: true,
  templateUrl: './status-pill.component.html',
  styleUrl: './status-pill.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StatusPillComponent {
  readonly label = input.required<string>();
  readonly variant = input<PillVariant>('muted');
}
