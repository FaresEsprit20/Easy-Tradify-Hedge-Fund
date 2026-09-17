import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { TopbarComponent } from '../topbar/topbar.component';
import { SidenavComponent } from '../sidenav/sidenav.component';
import { CommandPaletteComponent } from '../../shared/command-palette/command-palette.component';
import { MonitorApiService } from '../../core/services/api/monitor-api.service';
import { ExecutionApiService } from '../../core/services/api/execution-api.service';
import { PortfolioApiService } from '../../core/services/api/portfolio-api.service';
import { CopyTradeApiService } from '../../core/services/api/copy-trade-api.service';

/**
 * The application shell, and the one place backend polling is started.
 *
 * WHY POLLING LIVES HERE RATHER THAN IN EACH PAGE
 * -----------------------------------------------
 * Positions, the account and the risk limits are shown across several screens —
 * the topbar alone renders equity and the connection state on every route. If
 * each page started its own polling, navigating would tear the timers down and
 * rebuild them, and the dashboard would flash empty on every transition. Worse,
 * two pages wanting positions would poll twice.
 *
 * Starting them once at the shell means the data is warm before any page
 * mounts, and the services' `startPolling()` methods are idempotent so a page
 * that wants a faster refresh can still call its own `refresh*()` directly.
 */
@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterOutlet, TopbarComponent, SidenavComponent, CommandPaletteComponent],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ShellComponent implements OnInit, OnDestroy {
  private readonly monitor = inject(MonitorApiService);
  private readonly execution = inject(ExecutionApiService);
  private readonly portfolio = inject(PortfolioApiService);
  private readonly copyTrade = inject(CopyTradeApiService);

  ngOnInit(): void {
    this.monitor.startPolling();
    this.execution.startPolling();
    this.portfolio.startPolling();
    this.copyTrade.startPolling();
  }

  ngOnDestroy(): void {
    // The shell only unmounts when the app does, so this is belt-and-braces —
    // but an interval that outlives its component keeps the whole service graph
    // alive and keeps hitting the gateway, which is worth not leaving to chance.
    this.monitor.stopPolling();
    this.execution.stopPolling();
    this.portfolio.stopPolling();
    this.copyTrade.stopPolling();
  }
}
