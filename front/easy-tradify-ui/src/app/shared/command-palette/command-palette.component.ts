import { ChangeDetectionStrategy, Component, HostListener, computed, effect, inject, signal, viewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { SYMBOL_UNIVERSE, CATEGORY_LABELS } from '../../core/data/symbols';
import { CommandPaletteService } from './command-palette.service';

interface PaletteResult {
  kind: 'page' | 'symbol';
  key: string;
  label: string;
  sublabel: string;
  action: () => void;
}

const PAGES: { label: string; path: string; sublabel: string }[] = [
  { label: 'Dashboard', path: '/', sublabel: 'Overview · sessions · news · system health' },
  { label: 'Scanner', path: '/scanner', sublabel: 'Live opportunity radar' },
  { label: 'Terminal', path: '/terminal', sublabel: 'Chart, order ticket, market depth' },
  { label: 'Positions', path: '/positions', sublabel: 'Blotter, TP/SL management, trade history' },
  { label: 'Analysis', path: '/analysis', sublabel: 'Full decision snapshot workbench' },
  { label: 'Thread Pool', path: '/threads', sublabel: 'Worker scan status' },
  { label: 'Copy Trade', path: '/copy-trade', sublabel: 'Execute & register copy-trade manager' },
  { label: 'Monitor', path: '/monitor', sublabel: 'Start/stop/restart the scanner loop' },
  { label: 'Risk', path: '/risk', sublabel: 'Portfolio risk status & settings' },
  { label: 'Activity', path: '/activity', sublabel: 'Log, executions, closed trades' },
];

const DEFAULT_SYMBOLS = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD', 'US500'];

const MAX_RESULTS = 24;

/**
 * Ctrl/Cmd+K anywhere in the app — jump straight to a page or a symbol's
 * analysis workbench without touching the sidenav or hunting through the
 * watchlist. Renders as a fixed-position overlay mounted once in the shell,
 * so it works identically no matter which route is active.
 */
@Component({
  selector: 'app-command-palette',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './command-palette.component.html',
  styleUrl: './command-palette.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CommandPaletteComponent implements AfterViewChecked {
  private readonly router = inject(Router);
  private readonly paletteService = inject(CommandPaletteService);

  protected readonly open = this.paletteService.isOpen;
  protected readonly query = signal('');
  protected readonly activeIndex = signal(0);

  private readonly inputRef = viewChild<ElementRef<HTMLInputElement>>('input');
  private focusPending = false;

  protected readonly results = computed<PaletteResult[]>(() => {
    const q = this.query().trim().toUpperCase();

    const pageMatches = (q ? PAGES.filter((p) => p.label.toUpperCase().includes(q)) : PAGES).map((p) => ({
      kind: 'page' as const,
      key: p.path,
      label: p.label,
      sublabel: p.sublabel,
      action: () => this.router.navigate([p.path]),
    }));

    const symbolPool = q ? SYMBOL_UNIVERSE.filter((s) => s.symbol.includes(q)) : SYMBOL_UNIVERSE.filter((s) => DEFAULT_SYMBOLS.includes(s.symbol));
    const symbolMatches = symbolPool.slice(0, MAX_RESULTS).map((s) => ({
      kind: 'symbol' as const,
      key: s.symbol,
      label: s.symbol,
      sublabel: `${CATEGORY_LABELS[s.category]} · open analysis`,
      action: () => this.router.navigate(['/analysis'], { queryParams: { symbol: s.symbol } }),
    }));

    return [...pageMatches, ...symbolMatches].slice(0, MAX_RESULTS);
  });

  constructor() {
    effect(() => {
      this.query();
      this.activeIndex.set(0);
    });

    // Reacts to `open` regardless of who flipped it — the global ⌘K
    // shortcut and the topbar's button both just call the shared service,
    // so the reset-and-focus behavior has to live here, not in a
    // component-local toggle() that only one of those two paths calls.
    let wasOpen = false;
    effect(() => {
      const isOpen = this.open();
      if (isOpen && !wasOpen) {
        this.query.set('');
        this.activeIndex.set(0);
        this.focusPending = true;
      }
      wasOpen = isOpen;
    });
  }

  ngAfterViewChecked(): void {
    if (this.focusPending) {
      this.inputRef()?.nativeElement.focus();
      this.focusPending = false;
    }
  }

  @HostListener('document:keydown', ['$event'])
  protected onGlobalKeydown(e: KeyboardEvent): void {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      this.toggle();
      return;
    }
    if (!this.open()) return;

    if (e.key === 'Escape') {
      e.preventDefault();
      this.close();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      this.activeIndex.update((i) => Math.min(i + 1, this.results().length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      this.activeIndex.update((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const r = this.results()[this.activeIndex()];
      if (r) this.choose(r);
    }
  }

  protected toggle(): void {
    this.paletteService.toggle();
  }

  protected close(): void {
    this.paletteService.close();
  }

  protected choose(r: PaletteResult): void {
    r.action();
    this.close();
  }

  protected onBackdropClick(): void {
    this.close();
  }
}
