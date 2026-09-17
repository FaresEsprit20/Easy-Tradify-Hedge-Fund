import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MockStreamService } from '../../core/services/mock-stream.service';
import { ConnectionService } from '../../core/services/connection.service';
import { MonitorApiService } from '../../core/services/api/monitor-api.service';
import { PanelComponent } from '../../shared/panel/panel.component';
import { ThreadPoolPanelComponent } from '../../shared/widgets/thread-pool-panel/thread-pool-panel.component';
import { ThreadStatus } from '../../core/models/thread.model';
import { latestTimestamp } from '../../core/utils/latest-timestamp';

@Component({
  selector: 'app-thread-pool',
  standalone: true,
  imports: [PanelComponent, ThreadPoolPanelComponent],
  templateUrl: './thread-pool.component.html',
  styleUrl: './thread-pool.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ThreadPoolComponent {
  protected readonly stream = inject(MockStreamService);
  protected readonly connection = inject(ConnectionService);
  protected readonly monitor = inject(MonitorApiService);

  protected readonly latestChange = computed(() => latestTimestamp(this.stream.threads(), (t) => t.changedAt));

  protected readonly counts = computed(() => {
    const list = this.stream.threads();
    const byStatus = (s: ThreadStatus) => list.filter((t) => t.status === s).length;
    const avgLoad = list.length
      ? Math.round((list.reduce((sum, t) => sum + (t.load.reduce((a, b) => a + b, 0) / (t.load.length || 1)), 0) / list.length) * 100)
      : 0;
    return {
      total: list.length,
      scanning: byStatus('scanning'),
      analyzing: byStatus('analyzing'),
      executing: byStatus('executing'),
      idle: byStatus('idle'),
      avgLoad,
    };
  });
}
