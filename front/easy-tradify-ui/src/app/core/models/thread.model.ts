export type ThreadStatus = 'scanning' | 'analyzing' | 'executing' | 'idle';

export interface ThreadWorker {
  id: string;
  status: ThreadStatus;
  symbol: string | null;
  load: number[];
  startedAt: number;
  changedAt: number;
}
