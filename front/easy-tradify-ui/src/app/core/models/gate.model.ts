export type Verdict = 'pass' | 'near' | 'fail';

export interface GateEvent {
  id: string;
  timestamp: number;
  verdict: Verdict;
  gateName: string;
  margin: string;
  symbol: string;
}
