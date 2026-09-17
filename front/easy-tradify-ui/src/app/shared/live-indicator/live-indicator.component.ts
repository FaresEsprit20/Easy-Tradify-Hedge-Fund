import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, input, signal } from '@angular/core';
import { PulseDotComponent } from '../pulse-dot/pulse-dot.component';
import { ConnectionState } from '../../core/models/connection.model';

@Component({
  selector: 'app-live-indicator',
  standalone: true,
  imports: [PulseDotComponent],
  templateUrl: './live-indicator.component.html',
  styleUrl: './live-indicator.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LiveIndicatorComponent {
  readonly state = input<ConnectionState>('live');
  readonly updatedAt = input<number>(Date.now());

  private readonly now = signal(Date.now());

  protected readonly label = computed(() => {
    if (this.state() === 'disconnected') return 'DISCONNECTED';
    const seconds = Math.max(0, Math.round((this.now() - this.updatedAt()) / 1000));
    if (seconds < 1) return 'LIVE';
    if (seconds < 60) return `${seconds}s ago`;
    return `${Math.round(seconds / 60)}m ago`;
  });

  constructor() {
    // This component is instantiated once per live panel — every route that
    // uses `[live]="true"` on app-panel creates one. Without clearing the
    // interval on destroy, navigating away and back piles up a new ticking
    // timer every time, forever.
    const id = setInterval(() => this.now.set(Date.now()), 1000);
    inject(DestroyRef).onDestroy(() => clearInterval(id));
  }
}
