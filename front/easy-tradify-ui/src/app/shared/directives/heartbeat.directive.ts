import { Directive, ElementRef, effect, inject, input } from '@angular/core';

/**
 * One brief background wash on a worker/monitoring row when its state
 * changes — a heartbeat, not a persistent color change. Bind to a value
 * that changes exactly when the row's state does (e.g. a status string or
 * a changedAt timestamp).
 */
@Directive({
  selector: '[appHeartbeat]',
  standalone: true,
})
export class HeartbeatDirective {
  readonly appHeartbeat = input<unknown>();

  private readonly el = inject(ElementRef<HTMLElement>).nativeElement;
  private isFirstRun = true;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    effect(() => {
      this.appHeartbeat();
      if (this.isFirstRun) {
        this.isFirstRun = false;
        return;
      }
      this.el.classList.remove('u-heartbeat');
      void this.el.offsetWidth;
      this.el.classList.add('u-heartbeat');
      if (this.timer) clearTimeout(this.timer);
      this.timer = setTimeout(() => this.el.classList.remove('u-heartbeat'), 450);
    });
  }
}
