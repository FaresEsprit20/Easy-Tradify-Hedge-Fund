import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { environment } from '../../../../environments/environment';

/**
 * Password sign-in.
 *
 * Routes to the two-factor prompt when the backend asks for one — that is a
 * successful password check, not a failure, and is reported as such.
 */
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginComponent {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);

  /**
   * Warn when sign-in cannot possibly succeed.
   *
   * The auth service enforces reCAPTCHA and fails CLOSED, so if the browser has
   * no site key every attempt returns 400. Without this the user would retype
   * a correct password repeatedly against a bot check they cannot satisfy.
   */
  protected readonly recaptchaMisconfigured =
    !environment.recaptcha.enabled || !environment.recaptcha.siteKey;

  protected readonly form = this.fb.nonNullable.group({
    login: ['', [Validators.required]],
    password: ['', [Validators.required]],
  });

  protected async submit(): Promise<void> {
    if (this.form.invalid || this.submitting()) {
      this.form.markAllAsTouched();
      return;
    }

    this.submitting.set(true);
    this.error.set(null);

    try {
      const outcome = await this.auth.login(this.form.getRawValue());

      if (outcome === 'mfa') {
        await this.router.navigate(['/auth/two-factor'], { queryParamsHandling: 'preserve' });
        return;
      }

      // Honour the deep link the guard preserved, so a user who was sent here
      // from /positions lands back on /positions.
      const returnUrl = new URLSearchParams(window.location.search).get('returnUrl');
      await this.router.navigateByUrl(returnUrl || '/');
    } catch (e) {
      this.error.set(AuthService.describe(e));
    } finally {
      this.submitting.set(false);
    }
  }

  protected google(): void {
    this.auth.loginWithGoogle();
  }
}
