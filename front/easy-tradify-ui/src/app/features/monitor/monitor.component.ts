import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { PanelComponent } from '../../shared/panel/panel.component';
import { StatusPillComponent } from '../../shared/status-pill/status-pill.component';
import { MonitorApiService } from '../../core/services/api/monitor-api.service';
import { ExecutionApiService } from '../../core/services/api/execution-api.service';

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

@Component({
  selector: 'app-monitor',
  standalone: true,
  imports: [FormsModule, DatePipe, PanelComponent, StatusPillComponent],
  templateUrl: './monitor.component.html',
  styleUrl: './monitor.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MonitorComponent {
  protected readonly api = inject(MonitorApiService);
  protected readonly execution = inject(ExecutionApiService);

  protected readonly busy = signal(false);

  protected readonly mt5Login = signal(50412897);
  protected readonly mt5Password = signal('');
  protected readonly mt5Server = signal('ICMarkets-Demo');
  protected readonly mt5Path = signal('');
  protected readonly mt5Busy = signal(false);
  protected readonly autoRestartEnabled = signal(this.api.restartStatus().enabled);
  protected readonly autoRestartInterval = signal(this.api.restartStatus().intervalSeconds / 60);

  private readonly tick = signal(Date.now());
  protected readonly uptimeDisplay = computed(() => {
    this.tick();
    return formatUptime(this.api.getStatus().uptimeSeconds);
  });

  constructor() {
    const id = setInterval(() => this.tick.set(Date.now()), 1000);
    inject(DestroyRef).onDestroy(() => clearInterval(id));
  }

  protected async start(): Promise<void> {
    this.busy.set(true);
    try {
      await this.api.start();
    } finally {
      this.busy.set(false);
    }
  }

  protected async stop(): Promise<void> {
    this.busy.set(true);
    try {
      await this.api.stop();
    } finally {
      this.busy.set(false);
    }
  }

  protected async restart(): Promise<void> {
    this.busy.set(true);
    try {
      await this.api.restart('manual (ui)');
    } finally {
      this.busy.set(false);
    }
  }

  protected async refresh(): Promise<void> {
    this.busy.set(true);
    try {
      await this.api.refresh();
    } finally {
      this.busy.set(false);
    }
  }

  protected async saveAutoRestart(): Promise<void> {
    await this.api.configureAutoRestart(this.autoRestartEnabled(), this.autoRestartInterval() * 60);
  }

  protected async refreshNews(): Promise<void> {
    await this.api.refreshNews();
  }

  protected async refreshSession(): Promise<void> {
    await this.api.refreshSession();
  }

  protected async connectMt5(): Promise<void> {
    this.mt5Busy.set(true);
    try {
      await this.execution.connectMt5({
        login: this.mt5Login(),
        password: this.mt5Password(),
        server: this.mt5Server(),
        path: this.mt5Path() || undefined,
      });
    } finally {
      this.mt5Busy.set(false);
    }
  }

  protected async disconnectMt5(): Promise<void> {
    this.mt5Busy.set(true);
    try {
      await this.execution.disconnectMt5();
    } finally {
      this.mt5Busy.set(false);
    }
  }
}
