import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MockStreamService } from '../../core/services/mock-stream.service';
import { ConnectionService } from '../../core/services/connection.service';
import { PanelComponent } from '../../shared/panel/panel.component';
import { RadarSweepComponent } from '../../shared/radar-sweep/radar-sweep.component';
import { GateTickerComponent } from '../../shared/gate-ticker/gate-ticker.component';
import { OpportunitiesPanelComponent } from '../../shared/widgets/opportunities-panel/opportunities-panel.component';
import { latestTimestamp } from '../../core/utils/latest-timestamp';

@Component({
  selector: 'app-scanner',
  standalone: true,
  imports: [PanelComponent, RadarSweepComponent, GateTickerComponent, OpportunitiesPanelComponent],
  templateUrl: './scanner.component.html',
  styleUrl: './scanner.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScannerComponent {
  protected readonly stream = inject(MockStreamService);
  protected readonly connection = inject(ConnectionService);

  protected readonly scannerUpdatedAt = computed(() => latestTimestamp(this.stream.scanPings(), (p) => p.createdAt));
  protected readonly opportunitiesUpdatedAt = computed(() => latestTimestamp(this.stream.opportunities(), (o) => o.updatedAt));
  protected readonly gatesUpdatedAt = computed(() => latestTimestamp(this.stream.gateEvents(), (e) => e.timestamp));
}
