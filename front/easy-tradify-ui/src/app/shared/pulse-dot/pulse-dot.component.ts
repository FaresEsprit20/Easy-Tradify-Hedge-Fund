import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { ConnectionState } from '../../core/models/connection.model';

@Component({
  selector: 'app-pulse-dot',
  standalone: true,
  templateUrl: './pulse-dot.component.html',
  styleUrl: './pulse-dot.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PulseDotComponent {
  readonly state = input<ConnectionState>('live');

  protected readonly isLive = computed(() => this.state() === 'live');
  protected readonly isDisconnected = computed(() => this.state() === 'disconnected');
}
