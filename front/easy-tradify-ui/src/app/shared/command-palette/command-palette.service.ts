import { Injectable, signal } from '@angular/core';

/** Lets any component (the topbar's ⌘K button, a future help menu, ...)
 * open the command palette without needing a reference to the component
 * instance mounted in the shell. */
@Injectable({ providedIn: 'root' })
export class CommandPaletteService {
  readonly isOpen = signal(false);

  open(): void {
    this.isOpen.set(true);
  }

  close(): void {
    this.isOpen.set(false);
  }

  toggle(): void {
    this.isOpen.update((v) => !v);
  }
}
