import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

/**
 * The second step: a six-digit code, once the password has been accepted.
 *
 * Guarded by the presence of a pending MFA ticket rather than by a route guard.
 * That ticket lives in memory only, so a refresh on this screen sends the user
 * back to the password step — which is correct: the ticket is short-lived, and
 * resuming a half-finished login from stale state is worse than retyping.
 */
@Component({
  selector: 'app-two-factor',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './two-factor.component.html',
  styleUrl: './two-factor.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TwoFactorComponent {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly pending = this.auth.pendingMfa;

  /** What the user should be looking at — an app, or their inbox. */
  protected readonly viaEmail = computed(() => this.pending()?.method === 'EMAIL');

  protected readonly form = this.fb.nonNullable.group({
    code: ['', [Validators.required, Validators.pattern(/^\d{6}$/)]],
  });

  constructor() {
    // Nothing in progress — most likely a refresh or a bookmarked URL.
    if (!this.auth.pendingMfa()) {
      void this.router.navigate(['/auth/login']);
    }
  }

  protected async submit(): Promise<void> {
    if (this.form.invalid || this.submitting()) {
      this.form.markAllAsTouched();
      return;
    }

    this.submitting.set(true);
    this.error.set(null);

    try {
      await this.auth.verifyTwoFactor(this.form.getRawValue().code);
      const returnUrl = new URLSearchParams(window.location.search).get('returnUrl');
      await this.router.navigateByUrl(returnUrl || '/');
    } catch (e) {
      this.error.set(AuthService.describe(e));
      // Clear the field: a wrong code is never worth resubmitting, and a stale
      // TOTP code is wrong by the time the user reads the error.
      this.form.reset();
    } finally {
      this.submitting.set(false);
    }
  }

  protected cancel(): void {
    this.auth.clearSession();
    void this.router.navigate(['/auth/login']);
  }
}
