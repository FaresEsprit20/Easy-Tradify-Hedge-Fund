/**
 * Mirrors the semantic palette in styles.scss's @theme block. Duplicated
 * here (not read from the CSS custom properties) because lightweight-charts
 * renders to <canvas>, which has no way to resolve var(--color-jade) —
 * canvas fill/stroke colors must be literal CSS color strings. If the
 * palette in styles.scss ever changes, update these to match.
 */
export const CHART_COLORS = {
  jade: '#2bd98e',
  jadeVolume: 'rgba(43, 217, 142, 0.5)',
  jadeZone: 'rgba(43, 217, 142, 0.14)',
  coral: '#f2495c',
  coralVolume: 'rgba(242, 73, 92, 0.5)',
  coralZone: 'rgba(242, 73, 92, 0.14)',
  amber: '#f0a925',
  amberZone: 'rgba(240, 169, 37, 0.14)',
  info: '#4c8dff',
  infoZone: 'rgba(76, 141, 255, 0.14)',
  panelBg: '#151921',
  panelAltBg: '#1c212b',
  gridLine: '#1c212b',
  border: '#333b4a',
  textDim: '#8b93a7',
} as const;
