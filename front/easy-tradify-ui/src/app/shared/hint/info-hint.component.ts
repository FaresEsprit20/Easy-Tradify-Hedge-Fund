import { ChangeDetectionStrategy, Component, ElementRef, HostListener, inject, input } from '@angular/core';
import { HintOverlayService } from './hint-overlay.service';

/**
 * A small "?" badge that explains the term/field it sits next to. Hover or
 * focus (keyboard-reachable) to show; the tooltip renders through a shared
 * body-level overlay so it's never clipped by a panel's own scroll region.
 */
@Component({
  selector: 'app-info-hint',
  standalone: true,
  template: `<span class="hint-badge" tabindex="0" [attr.aria-label]="text()">?</span>`,
  styles: [
    `
      :host {
        display: inline-flex;
        vertical-align: middle;
      }
      .hint-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 13px;
        height: 13px;
        border-radius: 50%;
        border: 1px solid var(--text-dim);
        color: var(--text-dim);
        font-family: var(--font-mono);
        font-size: 8.5px;
        font-weight: 600;
        line-height: 1;
        cursor: help;
        user-select: none;
      }
      .hint-badge:hover,
      .hint-badge:focus-visible {
        border-color: var(--color-amber);
        color: var(--color-amber);
        outline: none;
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InfoHintComponent {
  readonly text = input.required<string>();

  private readonly overlay = inject(HintOverlayService);
  private readonly host = inject(ElementRef<HTMLElement>);

  @HostListener('mouseenter')
  @HostListener('focusin')
  protected onShow(): void {
    this.overlay.show(this.text(), this.host.nativeElement.getBoundingClientRect());
  }

  @HostListener('mouseleave')
  @HostListener('focusout')
  protected onHide(): void {
    this.overlay.hide();
  }
}
