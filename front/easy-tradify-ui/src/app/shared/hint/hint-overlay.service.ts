import { Injectable } from '@angular/core';

const MARGIN = 8;
const MAX_WIDTH = 280;

/**
 * Single shared tooltip element appended directly to <body>, positioned with
 * `position: fixed` from the trigger's own bounding rect. Every panel body
 * in this app scrolls (`overflow: auto`), so an ordinary absolutely-
 * positioned tooltip nested inside one would get clipped the moment it
 * needed to escape that panel — this sidesteps that entirely.
 */
@Injectable({ providedIn: 'root' })
export class HintOverlayService {
  private el: HTMLDivElement | null = null;
  private hideTimer: ReturnType<typeof setTimeout> | null = null;

  private ensure(): HTMLDivElement {
    if (this.el) return this.el;
    const el = document.createElement('div');
    el.setAttribute('role', 'tooltip');
    el.style.position = 'fixed';
    el.style.zIndex = '2000';
    el.style.maxWidth = `${MAX_WIDTH}px`;
    el.style.padding = '8px 10px';
    el.style.borderRadius = '3px';
    el.style.background = 'var(--bg-panel-raised)';
    el.style.border = '1px solid var(--color-amber)';
    el.style.boxShadow = '0 8px 24px rgba(0, 0, 0, 0.5)';
    el.style.color = 'var(--text-secondary)';
    el.style.font = '400 11px/1.5 var(--font-mono)';
    el.style.pointerEvents = 'none';
    el.style.opacity = '0';
    el.style.transform = 'translateY(2px)';
    el.style.transition = 'opacity 120ms ease-out, transform 120ms ease-out';
    document.body.appendChild(el);
    this.el = el;
    return el;
  }

  show(text: string, anchor: DOMRect): void {
    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
      this.hideTimer = null;
    }
    const el = this.ensure();
    el.textContent = text;
    el.style.visibility = 'hidden';
    el.style.opacity = '0';
    el.style.left = '0px';
    el.style.top = '0px';

    // Measure first (off-screen via visibility, not display) so we can flip
    // above/clamp horizontally before the user ever sees it placed wrong.
    requestAnimationFrame(() => {
      const rect = el.getBoundingClientRect();
      let left = anchor.left + anchor.width / 2 - rect.width / 2;
      left = Math.max(MARGIN, Math.min(left, window.innerWidth - rect.width - MARGIN));

      let top = anchor.bottom + MARGIN;
      if (top + rect.height > window.innerHeight - MARGIN) {
        top = anchor.top - rect.height - MARGIN;
      }

      el.style.left = `${Math.round(left)}px`;
      el.style.top = `${Math.round(top)}px`;
      el.style.visibility = 'visible';
      requestAnimationFrame(() => {
        el.style.opacity = '1';
        el.style.transform = 'translateY(0)';
      });
    });
  }

  hide(): void {
    if (!this.el) return;
    const el = this.el;
    el.style.opacity = '0';
    el.style.transform = 'translateY(2px)';
    this.hideTimer = setTimeout(() => {
      el.style.visibility = 'hidden';
    }, 140);
  }
}
