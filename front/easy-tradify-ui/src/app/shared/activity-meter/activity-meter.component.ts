import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'app-activity-meter',
  standalone: true,
  templateUrl: './activity-meter.component.html',
  styleUrl: './activity-meter.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ActivityMeterComponent {
  readonly levels = input<number[]>([]);
}
