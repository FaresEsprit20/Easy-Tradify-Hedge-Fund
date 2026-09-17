import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { ScanPing } from '../../core/models/scanner.model';

interface RadarPoint {
  id: string;
  x: number;
  y: number;
  variant: 'jade' | 'amber' | 'coral';
}

interface RadarTick {
  angle: number;
  major: boolean;
}

const CENTER = 100;
const MAX_R = 88;

@Component({
  selector: 'app-radar-sweep',
  standalone: true,
  templateUrl: './radar-sweep.component.html',
  styleUrl: './radar-sweep.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RadarSweepComponent {
  readonly pings = input<ScanPing[]>([]);

  protected readonly points = computed<RadarPoint[]>(() =>
    this.pings().map((p) => {
      const rad = (p.angle * Math.PI) / 180;
      const r = 10 + p.radius * (MAX_R - 10);
      return {
        id: p.id,
        x: CENTER + r * Math.cos(rad),
        y: CENTER + r * Math.sin(rad),
        variant: p.verdict === 'pass' ? 'jade' : p.verdict === 'near' ? 'amber' : 'coral',
      };
    }),
  );

  // 24 perimeter ticks (every 15°), every 4th one drawn longer/brighter —
  // instrument-panel dressing that reads as "calibrated," not decorative filler.
  protected readonly ticks: RadarTick[] = Array.from({ length: 24 }, (_, i) => ({ angle: i * 15, major: i % 4 === 0 }));
}
