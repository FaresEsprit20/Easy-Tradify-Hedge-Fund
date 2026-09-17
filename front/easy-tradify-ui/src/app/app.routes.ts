import { Routes } from '@angular/router';
import { ShellComponent } from './layout/shell/shell.component';
import { authGuard, guestGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  // ------------------------------------------------------------------
  // AUTH — declared BEFORE the shell.
  //
  // The shell's children end with a '**' wildcard, and the router matches in
  // order: if these sat after it, every /auth/* URL would be swallowed by the
  // shell's not-found route and render inside the authenticated layout.
  // ------------------------------------------------------------------
  {
    path: 'auth',
    loadComponent: () =>
      import('./features/auth/auth-layout/auth-layout.component').then((m) => m.AuthLayoutComponent),
    children: [
      { path: '', redirectTo: 'login', pathMatch: 'full' },
      {
        path: 'login',
        canActivate: [guestGuard],
        loadComponent: () =>
          import('./features/auth/login/login.component').then((m) => m.LoginComponent),
      },
      {
        path: 'register',
        canActivate: [guestGuard],
        loadComponent: () =>
          import('./features/auth/register/register.component').then((m) => m.RegisterComponent),
      },
      {
        // No guestGuard: this is reached mid-login, when the user is by
        // definition not yet authenticated but also not a fresh guest.
        path: 'two-factor',
        loadComponent: () =>
          import('./features/auth/two-factor/two-factor.component').then(
            (m) => m.TwoFactorComponent,
          ),
      },
      {
        // Must match app.oauth2.success-url in the auth service's properties.
        // The backend redirects the browser here by absolute URL, so a rename
        // on either side breaks Google sign-in with a 404 and no other clue.
        path: 'oauth2/success',
        loadComponent: () =>
          import('./features/auth/oauth2-callback/oauth2-callback.component').then(
            (m) => m.Oauth2CallbackComponent,
          ),
      },
    ],
  },

  // ------------------------------------------------------------------
  // APPLICATION — everything behind the guard.
  // ------------------------------------------------------------------
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      { path: '', loadComponent: () => import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent) },
      { path: 'scanner', loadComponent: () => import('./features/scanner/scanner.component').then((m) => m.ScannerComponent) },
      { path: 'terminal', loadComponent: () => import('./features/terminal/terminal.component').then((m) => m.TerminalComponent) },
      { path: 'analysis', loadComponent: () => import('./features/analysis/analysis.component').then((m) => m.AnalysisComponent) },
      { path: 'threads', loadComponent: () => import('./features/thread-pool/thread-pool.component').then((m) => m.ThreadPoolComponent) },
      { path: 'copy-trade', loadComponent: () => import('./features/copy-trade/copy-trade.component').then((m) => m.CopyTradeComponent) },
      { path: 'monitor', loadComponent: () => import('./features/monitor/monitor.component').then((m) => m.MonitorComponent) },
      { path: 'risk', loadComponent: () => import('./features/risk/risk.component').then((m) => m.RiskComponent) },
      { path: 'positions', loadComponent: () => import('./features/positions/positions.component').then((m) => m.PositionsComponent) },
      { path: 'ai-lab', loadComponent: () => import('./features/ai-lab/ai-lab.component').then((m) => m.AiLabComponent) },
      { path: 'activity', loadComponent: () => import('./features/activity/activity.component').then((m) => m.ActivityComponent) },
      { path: '**', loadComponent: () => import('./features/not-found/not-found.component').then((m) => m.NotFoundComponent) },
    ],
  },
];
