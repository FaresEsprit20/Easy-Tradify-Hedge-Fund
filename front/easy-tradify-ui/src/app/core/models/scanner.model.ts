export type PingVerdict = 'pass' | 'near' | 'veto';

export interface ScanPing {
  id: string;
  symbol: string;
  verdict: PingVerdict;
  angle: number;
  radius: number;
  createdAt: number;
}

export interface Opportunity {
  symbol: string;
  verdict: PingVerdict;
  conviction: number;
  gatesPassed: number;
  gatesTotal: number;
  note: string;
  updatedAt: number;
}
