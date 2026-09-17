import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
  selector: 'app-sparkline',
  standalone: true,
  templateUrl: './sparkline.component.html',
  styleUrl: './sparkline.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SparklineComponent {
  readonly series = input<number[]>([]);

  protected readonly points = computed(() => {
    const data = this.series();
    if (data.length < 2) return '';
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const stepX = 100 / (data.length - 1);
    return data.map((v, i) => `${round(i * stepX)},${round(24 - ((v - min) / range) * 24)}`).join(' ');
  });

  protected readonly isUp = computed(() => {
    const data = this.series();
    return data.length > 1 && data.at(-1)! >= data[0];
  });
}

function round(n: number): number {
  return Math.round(n * 100) / 100;
}
