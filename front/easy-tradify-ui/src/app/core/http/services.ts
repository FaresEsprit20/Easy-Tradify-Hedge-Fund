/**
 * Gateway route prefixes, matching api-gateway/application.yml exactly.
 *
 * These are the `Path=` predicates the gateway is configured with, not the
 * Spring application names — `portfolio` here routes to a service that
 * registers with Eureka as `portflio_risk_management-service` (the typo is in
 * that module's own properties). The gateway owns that mapping; the client only
 * ever needs the public prefix.
 */
export const SERVICE = {
  execution: 'execution',
  copyTrade: 'copy-trade',
  monitor: 'monitor',
  portfolio: 'portfolio',
  ai: 'ai',
  trades: 'trades',
} as const;

export type ServiceName = (typeof SERVICE)[keyof typeof SERVICE];

/** Human labels for the connection panel, keyed by the prefix above. */
export const SERVICE_LABELS: Readonly<Record<ServiceName, string>> = {
  execution: 'Execution',
  'copy-trade': 'Copy trade',
  monitor: 'Monitor',
  portfolio: 'Portfolio & risk',
  ai: 'AI layer',
  trades: 'Trade store',
};
