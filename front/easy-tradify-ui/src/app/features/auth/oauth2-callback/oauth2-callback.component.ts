import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

/**
 * Where Google's handshake lands.
 *
 * The backend redirects the BROWSER here with the tokens on the query string
 * (it also sets them as httpOnly cookies, which are the stronger channel — the
 * query string exists because a full page load loses everything else).
 *
 * <h3>The URL is scrubbed immediately</h3>
 * Tokens in `window.location` end up in browser history, in the referrer of
 * the next outbound request, and in any analytics that records URLs.
 * `replaceState` drops them from the address bar before this component
 * navigates on, so the session token is not left lying in history.
 */
@Component({
  selector: 'app-oauth2-callback',
  standalone: true,
  templateUrl: './oauth2-callback.component.html',
  styleUrl: './oauth2-callback.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Oauth2CallbackComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);

  protected readonly error = signal<string | null>(null);

  constructor() {
    void this.complete();
  }

  private async complete(): Promise<void> {
    const params = this.route.snapshot.queryParamMap;

    const failure = params.get('error');
    if (failure) {
      this.error.set(params.get('message') || 'Google sign-in was not completed.');
      return;
    }

    const accessToken = params.get('accessToken');
    const refreshToken = params.get('refreshToken');

    // Scrub before anything else can read them.
    window.history.replaceState({}, document.title, window.location.pathname);

    const ok = await this.auth.completeOAuth2(accessToken, refreshToken);

    if (!ok) {
      this.error.set('Signed in with Google, but the session could not be established.');
      return;
    }

    await this.router.navigateByUrl('/');
  }

  protected backToLogin(): void {
    void this.router.navigate(['/auth/login']);
  }
}
