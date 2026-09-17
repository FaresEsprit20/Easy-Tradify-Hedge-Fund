import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import { routes } from './app.routes';
import { correlationInterceptor } from './core/http/correlation.interceptor';
import { recaptchaInterceptor } from './core/http/recaptcha.interceptor';
import { authTokenInterceptor } from './core/http/auth-token.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),

    // withFetch(): the fetch backend, rather than XHR. It is what makes an
    // in-flight request genuinely abortable when a user cancels an AI run or
    // navigates away mid-scan — the XHR backend leaves the socket open and the
    // Python service keeps working on a result nobody will read.
    // Order matters: recaptcha mints its token first, then correlation
    // stamps and logs the request that actually goes out -- so the logged
    // request is the one carrying the header.
    provideHttpClient(withFetch(), withInterceptors([recaptchaInterceptor, authTokenInterceptor, correlationInterceptor])),
  ],
};
