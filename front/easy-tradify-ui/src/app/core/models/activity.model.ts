export type ActivityLevel = 'info' | 'success' | 'warn' | 'error';

export interface ActivityLogEntry {
  id: string;
  timestamp: number;
  level: ActivityLevel;
  message: string;
  symbol?: string;
}
