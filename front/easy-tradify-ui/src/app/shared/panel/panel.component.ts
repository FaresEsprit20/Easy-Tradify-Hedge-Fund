import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { LiveIndicatorComponent } from '../live-indicator/live-indicator.component';
import { InfoHintComponent } from '../hint/info-hint.component';
import { ConnectionState } from '../../core/models/connection.model';

@Component({
  selector: 'app-panel',
  standalone: true,
  imports: [LiveIndicatorComponent, InfoHintComponent],
  templateUrl: './panel.component.html',
  styleUrl: './panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PanelComponent {
  readonly title = input<string>('');
  /** Explanation shown via a "?" badge next to the title — for panels whose
   * purpose or jargon isn't self-evident from the name alone. */
  readonly titleHint = input<string | undefined>(undefined);
  readonly live = input<boolean>(false);
  readonly state = input<ConnectionState>('live');
  readonly updatedAt = input<number>(Date.now());
  readonly noPadding = input<boolean>(false);
}
