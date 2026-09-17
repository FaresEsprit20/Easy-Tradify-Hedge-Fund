import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MockStreamService } from '../../core/services/mock-stream.service';
import { ConnectionService } from '../../core/services/connection.service';
import { PanelComponent } from '../../shared/panel/panel.component';
import { PositionsPanelComponent } from '../../shared/widgets/positions-panel/positions-panel.component';
import { CloseAllButtonComponent } from '../../shared/widgets/close-all-button/close-all-button.component';
import { TradeHistoryPanelComponent } from '../../shared/widgets/trade-history-panel/trade-history-panel.component';
import { latestTimestamp } from '../../core/utils/latest-timestamp';

@Component({
  selector: 'app-positions',
  standalone: true,
  imports: [PanelComponent, PositionsPanelComponent, CloseAllButtonComponent, TradeHistoryPanelComponent],
  templateUrl: './positions.component.html',
  styleUrl: './positions.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PositionsComponent {
  protected readonly stream = inject(MockStreamService);
  protected readonly connection = inject(ConnectionService);

  protected readonly latestUpdate = computed(() => latestTimestamp(this.stream.positions(), (p) => p.updatedAt));
}
