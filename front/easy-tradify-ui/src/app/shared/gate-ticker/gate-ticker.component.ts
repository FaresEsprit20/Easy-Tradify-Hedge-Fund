import { AfterViewChecked, ChangeDetectionStrategy, Component, ElementRef, input, viewChild } from '@angular/core';
import { GateEvent } from '../../core/models/gate.model';
import { StatusPillComponent } from '../status-pill/status-pill.component';

@Component({
  selector: 'app-gate-ticker',
  standalone: true,
  imports: [StatusPillComponent],
  templateUrl: './gate-ticker.component.html',
  styleUrl: './gate-ticker.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GateTickerComponent implements AfterViewChecked {
  readonly events = input<GateEvent[]>([]);

  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');
  private lastLength = 0;

  protected formatTime(ts: number): string {
    const d = new Date(ts);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
  }

  protected pillVariant(verdict: GateEvent['verdict']): 'jade' | 'amber' | 'coral' {
    return verdict === 'pass' ? 'jade' : verdict === 'near' ? 'amber' : 'coral';
  }

  ngAfterViewChecked(): void {
    const events = this.events();
    if (events.length === this.lastLength) return;
    this.lastLength = events.length;
    const node = this.scroller()?.nativeElement;
    if (node) node.scrollTop = node.scrollHeight;
  }
}
