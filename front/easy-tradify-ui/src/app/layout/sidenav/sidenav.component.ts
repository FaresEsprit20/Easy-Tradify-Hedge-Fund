import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

interface NavLink {
  path: string;
  label: string;
  icon: string;
}

interface NavGroup {
  label: string;
  links: NavLink[];
}

const GROUPS: NavGroup[] = [
  {
    label: 'Trading',
    links: [
      { path: '/', label: 'Dashboard', icon: 'grid' },
      { path: '/scanner', label: 'Scanner', icon: 'radar' },
      { path: '/terminal', label: 'Terminal', icon: 'terminal' },
      { path: '/positions', label: 'Positions', icon: 'stack' },
      { path: '/analysis', label: 'Analysis', icon: 'analysis' },
    ],
  },
  {
    label: 'Intelligence',
    links: [
      { path: '/ai-lab', label: 'AI Lab', icon: 'analysis' },
    ],
  },
  {
    label: 'Operations',
    links: [
      { path: '/threads', label: 'Thread Pool', icon: 'cpu' },
      { path: '/copy-trade', label: 'Copy Trade', icon: 'copy' },
      { path: '/monitor', label: 'Monitor', icon: 'monitor' },
      { path: '/risk', label: 'Risk', icon: 'shield' },
      { path: '/activity', label: 'Activity', icon: 'log' },
    ],
  },
];

@Component({
  selector: 'app-sidenav',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './sidenav.component.html',
  styleUrl: './sidenav.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SidenavComponent {
  protected readonly groups = GROUPS;
}
