import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ThreadStatus, ThreadWorker } from '../../../core/models/thread.model';
import { StatusPillComponent, PillVariant } from '../../status-pill/status-pill.component';
import { ActivityMeterComponent } from '../../activity-meter/activity-meter.component';
import { HeartbeatDirective } from '../../directives/heartbeat.directive';

const STATUS_VARIANT: Record<ThreadStatus, PillVariant> = {
  scanning: 'amber',
  analyzing: 'info',
  executing: 'jade',
  idle: 'muted',
};

const STATUSES: ThreadStatus[] = ['scanning', 'analyzing', 'executing', 'idle'];

@Component({
  selector: 'app-thread-pool-panel',
  standalone: true,
  imports: [StatusPillComponent, ActivityMeterComponent, HeartbeatDirective, DatePipe],
  templateUrl: './thread-pool-panel.component.html',
  styleUrl: './thread-pool-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ThreadPoolPanelComponent {
  readonly threads = input<ThreadWorker[]>([]);

  protected readonly statuses = STATUSES;
  protected readonly statusFilter = signal<ThreadStatus | null>(null);
  protected readonly expanded = signal<string | null>(null);

  protected readonly filteredThreads = computed(() => {
    const filter = this.statusFilter();
    const list = this.threads();
    return filter ? list.filter((t) => t.status === filter) : list;
  });

  private readonly now = signal(Date.now());

  constructor() {
    const id = setInterval(() => this.now.set(Date.now()), 1000);
    inject(DestroyRef).onDestroy(() => clearInterval(id));
  }

  protected variant(status: ThreadStatus): PillVariant {
    return STATUS_VARIANT[status];
  }

  protected setFilter(status: ThreadStatus | null): void {
    this.statusFilter.set(status);
  }

  protected toggleExpand(id: string): void {
    this.expanded.update((cur) => (cur === id ? null : id));
  }

  protected elapsed(startedAt: number): string {
    const seconds = Math.max(0, Math.floor((this.now() - startedAt) / 1000));
    const m = Math.floor(seconds / 60)
      .toString()
      .padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  }

  protected avgLoad(load: number[]): number {
    if (!load.length) return 0;
    return Math.round((load.reduce((s, v) => s + v, 0) / load.length) * 100);
  }
}
