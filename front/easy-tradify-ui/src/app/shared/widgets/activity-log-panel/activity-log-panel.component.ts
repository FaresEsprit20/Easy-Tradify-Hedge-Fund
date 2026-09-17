import { AfterViewChecked, ChangeDetectionStrategy, Component, ElementRef, input, viewChild } from '@angular/core';
import { ActivityLevel, ActivityLogEntry } from '../../../core/models/activity.model';
import { StatusPillComponent, PillVariant } from '../../status-pill/status-pill.component';

const VARIANT: Record<ActivityLevel, PillVariant> = {
  info: 'muted',
  success: 'jade',
  warn: 'amber',
  error: 'coral',
};

@Component({
  selector: 'app-activity-log-panel',
  standalone: true,
  imports: [StatusPillComponent],
  templateUrl: './activity-log-panel.component.html',
  styleUrl: './activity-log-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ActivityLogPanelComponent implements AfterViewChecked {
  readonly entries = input<ActivityLogEntry[]>([]);

  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');
  private lastLength = 0;

  protected variant(level: ActivityLevel): PillVariant {
    return VARIANT[level];
  }

  protected formatTime(ts: number): string {
    const d = new Date(ts);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
  }

  ngAfterViewChecked(): void {
    const entries = this.entries();
    if (entries.length === this.lastLength) return;
    this.lastLength = entries.length;
    const node = this.scroller()?.nativeElement;
    if (node) node.scrollTop = node.scrollHeight;
  }
}
