import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MockStreamService } from '../../core/services/mock-stream.service';
import { latestTimestamp } from '../../core/utils/latest-timestamp';
import { ConnectionService } from '../../core/services/connection.service';
import { MonitorApiService } from '../../core/services/api/monitor-api.service';
import { CopyTradeApiService } from '../../core/services/api/copy-trade-api.service';
import { PanelComponent } from '../../shared/panel/panel.component';
import { GateTickerComponent } from '../../shared/gate-ticker/gate-ticker.component';
import { RadarSweepComponent } from '../../shared/radar-sweep/radar-sweep.component';
import { StatusPillComponent } from '../../shared/status-pill/status-pill.component';
import { WatchlistPanelComponent } from '../../shared/widgets/watchlist-panel/watchlist-panel.component';
import { PositionsPanelComponent } from '../../shared/widgets/positions-panel/positions-panel.component';
import { ActivityLogPanelComponent } from '../../shared/widgets/activity-log-panel/activity-log-panel.component';
import { OpportunitiesPanelComponent } from '../../shared/widgets/opportunities-panel/opportunities-panel.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    PanelComponent,
    GateTickerComponent,
    RadarSweepComponent,
    StatusPillComponent,
    WatchlistPanelComponent,
    PositionsPanelComponent,
    ActivityLogPanelComponent,
    OpportunitiesPanelComponent,
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent {
  protected readonly stream = inject(MockStreamService);
  protected readonly connection = inject(ConnectionService);
  protected readonly monitor = inject(MonitorApiService);
  protected readonly copyTrade = inject(CopyTradeApiService);

  protected readonly watchlistUpdatedAt = computed(() => latestTimestamp(this.stream.watchlist(), (w) => w.updatedAt));
  protected readonly positionsUpdatedAt = computed(() => latestTimestamp(this.stream.positions(), (p) => p.updatedAt));
  protected readonly scannerUpdatedAt = computed(() => latestTimestamp(this.stream.scanPings(), (p) => p.createdAt));
  protected readonly gatesUpdatedAt = computed(() => latestTimestamp(this.stream.gateEvents(), (e) => e.timestamp));
  protected readonly opportunitiesUpdatedAt = computed(() => latestTimestamp(this.stream.opportunities(), (o) => o.updatedAt));
  protected readonly activityUpdatedAt = computed(() => latestTimestamp(this.stream.activityLog(), (e) => e.timestamp));

  protected async refreshNews(): Promise<void> {
    await this.monitor.refreshNews();
  }

  protected async refreshSession(): Promise<void> {
    await this.monitor.refreshSession();
  }
}
