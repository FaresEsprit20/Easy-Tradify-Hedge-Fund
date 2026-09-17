import { ChangeDetectionStrategy, Component, inject, input, signal } from '@angular/core';
import { ExecutionApiService } from '../../../core/services/api/execution-api.service';

@Component({
  selector: 'app-close-all-button',
  standalone: true,
  templateUrl: './close-all-button.component.html',
  styleUrl: './close-all-button.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CloseAllButtonComponent {
  private readonly execution = inject(ExecutionApiService);

  readonly symbol = input<string | undefined>(undefined);

  protected readonly confirming = signal(false);
  protected readonly busy = signal(false);

  protected async click(): Promise<void> {
    if (!this.confirming()) {
      this.confirming.set(true);
      setTimeout(() => this.confirming.set(false), 3000);
      return;
    }
    this.busy.set(true);
    try {
      await this.execution.closeAllPositions(this.symbol());
    } finally {
      this.busy.set(false);
      this.confirming.set(false);
    }
  }
}
