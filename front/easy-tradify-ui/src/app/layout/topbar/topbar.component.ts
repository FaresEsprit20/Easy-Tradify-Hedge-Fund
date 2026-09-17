import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, HostListener, computed, inject, signal } from '@angular/core';
import { ConnectionService } from '../../core/services/connection.service';
import { MockStreamService } from '../../core/services/mock-stream.service';
import { ExecutionApiService } from '../../core/services/api/execution-api.service';
import { PulseDotComponent } from '../../shared/pulse-dot/pulse-dot.component';
import { CommandPaletteService } from '../../shared/command-palette/command-palette.service';
import { AuthService } from '../../core/services/auth.service';

@Component({
  selector: 'app-topbar',
  standalone: true,
  imports: [PulseDotComponent, DecimalPipe],
  templateUrl: './topbar.component.html',
  styleUrl: './topbar.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TopbarComponent {
  protected readonly connection = inject(ConnectionService);
  protected readonly stream = inject(MockStreamService);
  protected readonly palette = inject(CommandPaletteService);
  private readonly execution = inject(ExecutionApiService);
  private readonly host = inject(ElementRef<HTMLElement>);

  protected readonly auth = inject(AuthService);

  protected readonly showAccount = signal(false);
  protected readonly showUser = signal(false);

  /**
   * Initials for the avatar, derived from the signed-in email.
   *
   * The auth service reports the email and nothing else — there is no display
   * name on the session — so this takes the local part rather than inventing a
   * first/last name the backend never sent.
   */
  protected readonly initials = computed(() => {
    const email = this.auth.user()?.email ?? '';
    const local = email.split('@')[0] ?? '';
    const parts = local.split(/[._-]+/).filter(Boolean);

    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return (local.slice(0, 2) || '??').toUpperCase();
  });

  private readonly now = signal(this.formatClock());

  protected readonly clock = this.now.asReadonly();

  constructor() {
    const id = setInterval(() => this.now.set(this.formatClock()), 1000);
    inject(DestroyRef).onDestroy(() => clearInterval(id));
  }

  protected toggleConnection(): void {
    this.connection.toggle();
  }

  protected toggleAccount(): void {
    this.showAccount.update((v) => !v);
    // Only one popover open at a time — they overlap in the same corner.
    this.showUser.set(false);
  }

  protected toggleUser(): void {
    this.showUser.update((v) => !v);
    this.showAccount.set(false);
  }

  protected async signOut(): Promise<void> {
    this.showUser.set(false);
    // AuthService.logout() clears the session and routes to /auth/login even if
    // the server call fails — a failed logout must never leave someone looking
    // signed in on a machine they are walking away from.
    await this.auth.logout();
  }

  protected fullAccount() {
    return this.execution.getAccount();
  }

  @HostListener('document:click', ['$event'])
  protected onDocumentClick(event: MouseEvent): void {
    if (this.host.nativeElement.contains(event.target as Node)) return;
    this.showAccount.set(false);
    this.showUser.set(false);
  }

  private formatClock(): string {
    const d = new Date();
    return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
}
