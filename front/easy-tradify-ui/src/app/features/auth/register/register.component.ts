import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

/**
 * Account creation.
 *
 * The validators here mirror the server's `UserValidator` exactly — same
 * password composition rule, same 8-digit phone, same name bounds. Duplicated
 * deliberately: the server is the authority and rejects anything invalid
 * regardless, but catching it in the browser turns a round trip and a generic
 * failure into an inline message pointing at the field.
 */
@Component({
  selector: 'app-register',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './register.component.html',
  styleUrl: './register.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RegisterComponent {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly done = signal(false);

  /** Matches FieldsValidation.PASSWORD_REGEX on the server, character for character. */
  private static readonly PASSWORD_RE =
    /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&\-]).{8,100}$/;

  protected readonly form = this.fb.nonNullable.group(
    {
      firstName: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(20)]],
      lastName: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(20)]],
      email: ['', [Validators.required, Validators.email]],
      numTel: ['', [Validators.required, Validators.pattern(/^[0-9]{8}$/)]],
      password: ['', [Validators.required, Validators.pattern(RegisterComponent.PASSWORD_RE)]],
      confirmPassword: ['', [Validators.required]],
    },
    { validators: passwordsMatch },
  );

  protected async submit(): Promise<void> {
    if (this.form.invalid || this.submitting()) {
      this.form.markAllAsTouched();
      return;
    }

    this.submitting.set(true);
    this.error.set(null);

    const { confirmPassword: _ignored, ...request } = this.form.getRawValue();

    try {
      await this.auth.register(request);
      this.done.set(true);

      // Straight to sign-in rather than auto-logging them in: registration does
      // not issue a session here, and a brief confirmation is clearer than
      // landing on a dashboard with no explanation of what happened.
      setTimeout(() => void this.router.navigate(['/auth/login']), 1400);
    } catch (e) {
      this.error.set(AuthService.describe(e));
    } finally {
      this.submitting.set(false);
    }
  }
}

/** Cross-field check — lives on the group because it compares two controls. */
function passwordsMatch(group: AbstractControl): { mismatch: true } | null {
  const password = group.get('password')?.value;
  const confirm = group.get('confirmPassword')?.value;
  return password && confirm && password !== confirm ? { mismatch: true } : null;
}
