import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { StageProgress } from '../../core/models/ai.model';

/**
 * A staged pipeline with the current stage animated.
 *
 * Used instead of a spinner because the stages carry meaning. A rule-space
 * search spends most of its time in "Permutation null" and "FDR correction",
 * and those steps are the substance of the result rather than overhead —
 * collapsing them into an undifferentiated wait is how a search comes to look
 * like a lookup, which is exactly the misreading this project has paid for.
 */
@Component({
  selector: 'app-process-runner',
  standalone: true,
  templateUrl: './process-runner.component.html',
  styleUrl: './process-runner.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProcessRunnerComponent {
  readonly stages = input.required<readonly StageProgress[]>();
  readonly running = input<boolean>(false);

  protected readonly doneCount = computed(
    () => this.stages().filter((s) => s.state === 'done').length,
  );

  protected readonly percent = computed(() => {
    const total = this.stages().length;
    return total === 0 ? 0 : Math.round((this.doneCount() / total) * 100);
  });

  protected readonly activeLabel = computed(
    () => this.stages().find((s) => s.state === 'active')?.label ?? '',
  );
}
