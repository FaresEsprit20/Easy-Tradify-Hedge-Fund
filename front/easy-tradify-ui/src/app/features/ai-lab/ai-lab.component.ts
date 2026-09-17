import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { PanelComponent } from '../../shared/panel/panel.component';
import { AiResultComponent } from './ai-result/ai-result.component';
import { AiOperationComponent } from './ai-operation/ai-operation.component';
import { ProcessRunnerComponent } from '../../shared/process-runner/process-runner.component';
import { AI_GROUPS } from '../../core/data/ai-endpoints';
import { AiApiService } from '../../core/services/api/ai-api.service';
import { AiGroup, AiOperation, AiParam } from '../../core/models/ai.model';

/**
 * The AI layer console.
 *
 * One screen over every operable endpoint in ai/ai_controller.py and the trade
 * store, driven by the registry in core/data/ai-endpoints.ts. Rendering from
 * data rather than writing a page per group is deliberate: the controller
 * carries 139 routes, and a bespoke template each would drift the first time a
 * route changed.
 *
 * NOT CONNECTED TO A BACKEND YET — every result comes from AiApiService's
 * mocks. The interface is the deliverable here.
 */
@Component({
  selector: 'app-ai-lab',
  standalone: true,
  imports: [
    PanelComponent,
    ProcessRunnerComponent,
    AiOperationComponent,
    AiResultComponent,
  ],
  templateUrl: './ai-lab.component.html',
  styleUrl: './ai-lab.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AiLabComponent {
  protected readonly api = inject(AiApiService);
  protected readonly groups = AI_GROUPS;

  protected readonly groupId = signal<string>(AI_GROUPS[0].id);
  protected readonly operationId = signal<string>(AI_GROUPS[0].operations[0].id);

  /** Editable parameter values, keyed by operation id then param key. */
  private readonly paramState = signal<Record<string, Record<string, unknown>>>({});

  protected readonly group = computed<AiGroup>(
    () => this.groups.find((g) => g.id === this.groupId()) ?? this.groups[0],
  );

  protected readonly operation = computed<AiOperation>(() => {
    const g = this.group();
    return g.operations.find((o) => o.id === this.operationId()) ?? g.operations[0];
  });

  protected readonly params = computed<readonly AiParam[]>(
    () => this.operation().params ?? [],
  );

  protected readonly totalOperations = computed(() =>
    this.groups.reduce((n, g) => n + g.operations.length, 0),
  );

  // ------------------------------------------------------------
  // SELECTION
  // ------------------------------------------------------------

  protected selectGroup(id: string): void {
    const g = this.groups.find((x) => x.id === id);
    if (!g) return;
    this.groupId.set(id);
    this.operationId.set(g.operations[0].id);
  }

  protected selectOperation(id: string): void {
    this.operationId.set(id);
  }

  /** Current parameter values for the selected operation, defaults included. */
  protected readonly currentValues = computed<Record<string, unknown>>(() => {
    const op = this.operation();
    const stored = this.paramState()[op.id] ?? {};
    const out: Record<string, unknown> = {};
    for (const p of op.params ?? []) {
      out[p.key] = stored[p.key] === undefined ? p.value : stored[p.key];
    }
    return out;
  });

  // ------------------------------------------------------------
  // PARAMETERS
  // ------------------------------------------------------------

  protected valueOf(param: AiParam): unknown {
    return this.paramState()[this.operation().id]?.[param.key] ?? param.value;
  }

  protected patchParam(param: AiParam, raw: unknown): void {
    const value =
      param.kind === 'number'
        ? Number(raw)
        : param.kind === 'boolean'
          ? Boolean(raw)
          : raw;

    const opId = this.operation().id;
    this.paramState.update((state) => ({
      ...state,
      [opId]: { ...(state[opId] ?? {}), [param.key]: value },
    }));
  }

  private collectParams(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const p of this.params()) out[p.key] = this.valueOf(p);
    return out;
  }

  /** The URL this operation will eventually call, with params substituted. */
  protected readonly resolvedPath = computed(() => {
    const op = this.operation();
    let path = op.path;
    for (const p of op.params ?? []) {
      const v = this.paramState()[op.id]?.[p.key] ?? p.value;
      path = path.replace(`{${p.key}}`, String(v ?? ''));
    }
    return path;
  });

  // ------------------------------------------------------------
  // RUNNING
  // ------------------------------------------------------------

  protected cancelRun(): void {
    this.api.cancel();
  }

  protected async execute(): Promise<void> {
    await this.api.run(this.operation(), this.collectParams());
  }

  // ------------------------------------------------------------
  // PRESENTATION
  // ------------------------------------------------------------
}
