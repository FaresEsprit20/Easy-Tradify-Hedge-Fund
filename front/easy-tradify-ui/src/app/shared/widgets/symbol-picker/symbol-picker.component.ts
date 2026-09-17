import { ChangeDetectionStrategy, Component, ElementRef, HostListener, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CATEGORY_LABELS, SYMBOL_UNIVERSE, SymbolCategory } from '../../../core/data/symbols';

const MAX_RESULTS = 40;

/** Searchable/filterable replacement for a plain `<select>` — a 500-symbol
 * universe makes a native dropdown unusable, so this renders a capped,
 * ranked slice instead of the full list. */
@Component({
  selector: 'app-symbol-picker',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './symbol-picker.component.html',
  styleUrl: './symbol-picker.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SymbolPickerComponent {
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly value = input.required<string>();
  readonly change = output<string>();

  protected readonly open = signal(false);
  protected readonly query = signal('');
  protected readonly category = signal<SymbolCategory | null>(null);
  // Every panel body in this app scrolls (`overflow: auto`/`hidden`), which
  // would clip a `position: absolute` dropdown the instant it needed to
  // extend past the panel's own bounds — same failure mode the hint
  // tooltips had. Fixed positioning computed from the trigger's own rect
  // sidesteps it entirely, same fix as HintOverlayService.
  protected readonly panelPosition = signal<{ top: number; left: number } | null>(null);

  protected readonly categories = Object.entries(CATEGORY_LABELS) as [SymbolCategory, string][];

  protected readonly results = computed(() => {
    const q = this.query().trim().toUpperCase();
    const cat = this.category();
    let list = SYMBOL_UNIVERSE;
    if (cat) list = list.filter((s) => s.category === cat);
    if (q) list = list.filter((s) => s.symbol.includes(q));
    return list.slice(0, MAX_RESULTS);
  });

  protected readonly totalMatches = computed(() => {
    const q = this.query().trim().toUpperCase();
    const cat = this.category();
    let list = SYMBOL_UNIVERSE;
    if (cat) list = list.filter((s) => s.category === cat);
    if (q) list = list.filter((s) => s.symbol.includes(q));
    return list.length;
  });

  constructor() {
    effect(() => {
      if (!this.open()) this.query.set('');
    });
  }

  @HostListener('document:click', ['$event'])
  protected onDocumentClick(event: MouseEvent): void {
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.open.set(false);
    }
  }

  protected toggle(): void {
    if (this.open()) {
      this.open.set(false);
      return;
    }
    const rect = this.host.nativeElement.getBoundingClientRect();
    const panelWidth = 280;
    let left = rect.left;
    left = Math.max(8, Math.min(left, window.innerWidth - panelWidth - 8));
    let top = rect.bottom + 4;
    const estimatedHeight = 360;
    if (top + estimatedHeight > window.innerHeight - 8) {
      top = Math.max(8, rect.top - estimatedHeight - 4);
    }
    this.panelPosition.set({ top, left });
    this.open.set(true);
  }

  protected pick(symbol: string): void {
    this.change.emit(symbol);
    this.open.set(false);
  }

  protected onEscape(): void {
    this.open.set(false);
  }

  protected setCategory(cat: SymbolCategory | null): void {
    this.category.set(cat);
  }
}
