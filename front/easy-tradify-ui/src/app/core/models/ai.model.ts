/**
 * Types for the AI layer console.
 *
 * These mirror ai/ai_controller.py (port 5002) — 139 routes across the GNN,
 * adversarial, replay, model, governance and research groups — and
 * api/trades_controller.py (port 5011) for the trade store.
 *
 * Nothing here talks to a backend yet. The console is wired to a mock service
 * so the whole surface can be designed and reviewed before any endpoint is
 * called for real; `AiOperation.method` and `.path` record the eventual target
 * so the swap is mechanical.
 */

/** HTTP verb an operation will eventually use. */
export type AiMethod = 'GET' | 'POST';

/**
 * How heavy an operation is. This drives the process animation: a `scan` runs
 * visibly longer and shows more stages than a `read`, because pretending a
 * 40,000-configuration search returns instantly would misrepresent it.
 */
export type AiWeight = 'read' | 'compute' | 'scan';

/** A single field a caller can supply before running an operation. */
export interface AiParam {
  readonly key: string;
  readonly label: string;
  readonly kind: 'text' | 'number' | 'boolean' | 'select';
  readonly value: string | number | boolean;
  readonly options?: readonly string[];
  /** Shown under the field — why this parameter matters, not what it is. */
  readonly note?: string;
}

/** One callable AI endpoint. */
export interface AiOperation {
  readonly id: string;
  readonly label: string;
  readonly method: AiMethod;
  readonly path: string;
  readonly weight: AiWeight;
  /** What the operation answers, in one line. */
  readonly summary: string;
  /**
   * The caveat a reader needs to interpret the result honestly — a sample-size
   * floor, a multiple-comparison correction, a known trap. Rendered next to
   * the output, not hidden in a tooltip.
   */
  readonly caveat?: string;
  readonly params?: readonly AiParam[];
  /** Destructive or state-changing: the console asks before running. */
  readonly guarded?: boolean;
}

/** A group of related operations, one per owning Python module. */
export interface AiGroup {
  readonly id: string;
  readonly label: string;
  readonly module: string;
  readonly port: number;
  readonly blurb: string;
  readonly operations: readonly AiOperation[];
}

/** One stage of a running operation, as shown in the process animation. */
export interface ProcessStage {
  readonly label: string;
  /** Roughly how long this stage takes relative to the others. */
  readonly weight: number;
}

export type StageState = 'pending' | 'active' | 'done' | 'failed';

export interface StageProgress {
  readonly label: string;
  readonly state: StageState;
}

/** Terminal state of a run. */
export type RunOutcome = 'ok' | 'inconclusive' | 'refused' | 'error';

/**
 * The result of a mocked run.
 *
 * `outcome` is deliberately richer than ok/error. The Python layer routinely
 * answers "inconclusive" — a guard reporting that there are too few trades to
 * test — and collapsing that into a success or a failure is how an empty
 * result reads as a negative finding.
 */
export interface AiRunResult {
  readonly operationId: string;
  readonly outcome: RunOutcome;
  readonly status: number;
  readonly startedAt: number;
  readonly durationMs: number;
  readonly summary: string;
  readonly payload: unknown;
}
