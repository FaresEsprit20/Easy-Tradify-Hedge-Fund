import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { AiGroup, AiOperation, AiParam } from '../../../core/models/ai.model';

/**
 * Choosing, parameterising and launching one AI operation.
 *
 * Split from AiLabComponent so each stays inside the project's 4 kB
 * per-component style budget, and because selecting an operation is a
 * genuinely separate concern from presenting its result.
 */
@Component({
  selector: 'app-ai-operation',
  standalone: true,
  templateUrl: './ai-operation.component.html',
  styleUrl: './ai-operation.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AiOperationComponent {
  readonly group = input.required<AiGroup>();
  readonly operation = input.required<AiOperation>();
  readonly resolvedPath = input.required<string>();
  readonly running = input<boolean>(false);
  /** Current parameter values, keyed by param key. */
  readonly values = input<Record<string, unknown>>({});

  readonly selectOperation = output<string>();
  readonly paramChange = output<{ param: AiParam; value: unknown }>();
  readonly run = output<void>();
  readonly cancel = output<void>();

  /** Set while a guarded operation waits for confirmation. */
  protected readonly pendingConfirm = signal<AiOperation | null>(null);

  protected readonly params = computed<readonly AiParam[]>(
    () => this.operation().params ?? [],
  );

  protected valueOf(param: AiParam): unknown {
    const v = this.values()[param.key];
    return v === undefined ? param.value : v;
  }

  protected patch(param: AiParam, raw: unknown): void {
    const value =
      param.kind === 'number' ? Number(raw)
        : param.kind === 'boolean' ? Boolean(raw)
          : raw;
    this.paramChange.emit({ param, value });
  }

  protected requestRun(): void {
    const op = this.operation();
    if (op.guarded) {
      this.pendingConfirm.set(op);
      return;
    }
    this.run.emit();
  }

  protected confirm(): void {
    this.pendingConfirm.set(null);
    this.run.emit();
  }

  protected dismiss(): void {
    this.pendingConfirm.set(null);
  }

  protected pick(id: string): void {
    this.pendingConfirm.set(null);
    this.selectOperation.emit(id);
  }

  protected weightLabel(op: AiOperation): string {
    return op.weight === 'scan' ? 'heavy' : op.weight === 'compute' ? 'compute' : 'read';
  }
}
