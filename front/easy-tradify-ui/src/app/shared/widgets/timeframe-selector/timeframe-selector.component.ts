import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TIMEFRAMES, Timeframe } from '../../../core/data/timeframes';

@Component({
  selector: 'app-timeframe-selector',
  standalone: true,
  templateUrl: './timeframe-selector.component.html',
  styleUrl: './timeframe-selector.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TimeframeSelectorComponent {
  readonly value = input.required<Timeframe>();
  readonly change = output<Timeframe>();

  protected readonly timeframes = TIMEFRAMES;
}
