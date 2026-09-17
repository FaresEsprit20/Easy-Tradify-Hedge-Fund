import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { MarketCanvasComponent } from '../../../shared/market-canvas/market-canvas.component';

/**
 * The split screen every auth route renders inside.
 *
 * Left: the product's own visual language — a live chart, the platform's
 * capability lines, the stack it runs on. Right: the form, and nothing else.
 *
 * <h3>Why the form side is narrow and plain</h3>
 * The decoration earns attention on the left so the right can be boring. A
 * sign-in form is a task, not an experience: anything competing with the two
 * fields costs the user time on the one screen where they have no patience.
 *
 * On a narrow viewport the chart panel is dropped entirely rather than stacked
 * above the form. Stacking it would push the password field below the fold on
 * a phone, which is a real cost for a decorative panel.
 */
@Component({
  selector: 'app-auth-layout',
  standalone: true,
  imports: [RouterOutlet, MarketCanvasComponent],
  templateUrl: './auth-layout.component.html',
  styleUrl: './auth-layout.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuthLayoutComponent {
  /**
   * What the platform actually does, in its own vocabulary.
   *
   * Written as capabilities with real numbers from this codebase rather than
   * marketing lines — the audience for this screen is the person who built it.
   */
  protected readonly capabilities = [
    { k: 'MARGIN-FIRST SIZING', v: 'Lot solved from the margin target, risk steered by the stop' },
    { k: 'BROKER-TRUE RISK', v: 'Every figure measured through MT5, never derived' },
    { k: 'WALK-FORWARD', v: 'Permutation nulls and FDR before a rule ships' },
    { k: 'OPAQUE SESSIONS', v: 'Revocation takes effect on the next request' },
  ];
}
