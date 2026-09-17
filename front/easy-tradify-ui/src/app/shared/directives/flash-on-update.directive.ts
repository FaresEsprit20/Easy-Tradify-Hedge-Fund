import { Directive, ElementRef, effect, inject, input } from '@angular/core';

/**
 * Washes the host element amber for under 500ms whenever the bound value
 * changes — a single pulse, never a repeating blink. Value equality is by
 * reference/primitive comparison, so pass the specific field that changed
 * (e.g. a price), not a whole object that's replaced every tick.
 */
@Directive({
  selector: '[appFlashOnUpdate]',
  standalone: true,
})
export class FlashOnUpdateDirective {
  readonly appFlashOnUpdate = input<unknown>();

  private readonly el = inject(ElementRef<HTMLElement>).nativeElement;
  private isFirstRun = true;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    effect(() => {
      this.appFlashOnUpdate();
      if (this.isFirstRun) {
        this.isFirstRun = false;
        return;
      }
      this.el.classList.remove('u-flash-on-update');
      void this.el.offsetWidth;
      this.el.classList.add('u-flash-on-update');
      if (this.timer) clearTimeout(this.timer);
      this.timer = setTimeout(() => this.el.classList.remove('u-flash-on-update'), 500);
    });
  }
}
