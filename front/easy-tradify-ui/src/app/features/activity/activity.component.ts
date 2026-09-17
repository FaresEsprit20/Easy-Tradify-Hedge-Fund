import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MockStreamService } from '../../core/services/mock-stream.service';
import { ConnectionService } from '../../core/services/connection.service';
import { MonitorApiService } from '../../core/services/api/monitor-api.service';
import { PanelComponent } from '../../shared/panel/panel.component';
import { ActivityLogPanelComponent } from '../../shared/widgets/activity-log-panel/activity-log-panel.component';
import { StatusPillComponent } from '../../shared/status-pill/status-pill.component';
import { ActivityLevel } from '../../core/models/activity.model';
import { latestTimestamp } from '../../core/utils/latest-timestamp';

function round(value: number, decimals: number): number {
  const f = Math.pow(10, decimals);
  return Math.round(value * f) / f;
}

type Tab = 'log' | 'executions' | 'closed';
type ExecSortKey = 'timestamp' | 'symbol' | 'volume';
type ClosedSortKey = 'timestamp' | 'symbol' | 'profit';

@Component({
  selector: 'app-activity',
  standalone: true,
  imports: [FormsModule, DecimalPipe, PanelComponent, ActivityLogPanelComponent, StatusPillComponent],
  templateUrl: './activity.component.html',
  styleUrl: './activity.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ActivityComponent {
  protected readonly stream = inject(MockStreamService);
  protected readonly connection = inject(ConnectionService);
  private readonly monitor = inject(MonitorApiService);

  protected readonly tab = signal<Tab>('log');
  protected readonly levels: ActivityLevel[] = ['info', 'success', 'warn', 'error'];
  protected readonly levelFilter = signal<ActivityLevel | null>(null);
  protected readonly search = signal('');

  protected readonly filteredLog = computed(() => {
    const level = this.levelFilter();
    const q = this.search().trim().toLowerCase();
    return this.stream.activityLog().filter(
      (e) => (!level || e.level === level) && (!q || e.message.toLowerCase().includes(q) || (e.symbol?.toLowerCase().includes(q) ?? false)),
    );
  });

  protected readonly executions = signal(this.monitor.getExecutions());
  protected readonly closedTrades = signal(this.monitor.getClosedTrades());

  protected readonly execSortKey = signal<ExecSortKey>('timestamp');
  protected readonly execSortDir = signal<1 | -1>(-1);
  protected readonly sortedExecutions = computed(() => {
    const key = this.execSortKey();
    const dir = this.execSortDir();
    return [...this.executions()].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number);
      return cmp * dir;
    });
  });

  protected readonly closedSortKey = signal<ClosedSortKey>('timestamp');
  protected readonly closedSortDir = signal<1 | -1>(-1);
  protected readonly sortedClosedTrades = computed(() => {
    const key = this.closedSortKey();
    const dir = this.closedSortDir();
    return [...this.closedTrades()].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number);
      return cmp * dir;
    });
  });

  protected readonly executionStats = computed(() => {
    const list = this.executions();
    const success = list.filter((e) => e.success).length;
    return { total: list.length, success, failed: list.length - success, successRate: list.length ? round((100 * success) / list.length, 1) : 0 };
  });

  protected readonly closedStats = computed(() => {
    const list = this.closedTrades();
    const wins = list.filter((t) => t.isWinning).length;
    const totalPnl = round(
      list.reduce((s, t) => s + t.profit, 0),
      2,
    );
    return { total: list.length, wins, losses: list.length - wins, winRate: list.length ? round((100 * wins) / list.length, 1) : 0, totalPnl };
  });

  protected readonly latestUpdate = computed(() => latestTimestamp(this.stream.activityLog(), (e) => e.timestamp));

  protected setTab(t: Tab): void {
    this.tab.set(t);
  }

  protected setLevel(l: ActivityLevel | null): void {
    this.levelFilter.set(l);
  }

  protected sortExecBy(key: ExecSortKey): void {
    if (this.execSortKey() === key) this.execSortDir.update((d) => (d === 1 ? -1 : 1));
    else {
      this.execSortKey.set(key);
      this.execSortDir.set(1);
    }
  }

  protected sortClosedBy(key: ClosedSortKey): void {
    if (this.closedSortKey() === key) this.closedSortDir.update((d) => (d === 1 ? -1 : 1));
    else {
      this.closedSortKey.set(key);
      this.closedSortDir.set(1);
    }
  }

  protected formatTime(ts: number): string {
    return new Date(ts).toLocaleString(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  protected clearLogs(): void {
    this.monitor.clearLogs();
    this.stream.activityLog.set([]);
    this.executions.set([]);
    this.closedTrades.set([]);
  }
}
