import { Verdict } from './gate.model';

/** One entry from decision_snapshot.gates_with_margin. */
export interface GateMarginCheck {
  gate: string;
  passed: boolean;
  enforced: boolean;
  nearMiss: boolean | null;
  value: number | null;
  threshold: number | null;
  margin: number | null;
  unit: string | null;
}

export interface CaseIndicatorSupport {
  indicator: string;
  confidence: number;
  reason: string;
}

/** decision_snapshot.bull_case / bear_case. */
export interface CaseThesis {
  thesis: 'BUY' | 'SELL';
  confidence: number;
  supportingIndicators: CaseIndicatorSupport[];
  invalidationTrigger: string;
}

/** decision_snapshot.scenario_tree.{primary,invalidation,alternate}. */
export interface ScenarioNode {
  scenario: string;
  probabilityPct: number | null;
  trigger: string;
  targets?: number[];
}

export interface ScenarioTree {
  primary: ScenarioNode;
  invalidation: ScenarioNode;
  alternate: ScenarioNode;
}

/** One step of final_verdict.probability_ledger. */
export interface ProbabilityLedgerStep {
  step: string;
  before: number;
  after: number;
  delta: number;
  clamped: boolean;
  note: string;
}

export interface ConvictionComponent {
  detail: string;
  hardFail: boolean;
  score: number;
}

/** conviction block — the last-line selectivity filter. */
export interface Conviction {
  convictionScore: number;
  minRequired: number;
  passed: boolean;
  reason: string;
  hardFails: string[];
  components: Record<string, ConvictionComponent>;
}

/** decision_snapshot.regime_3d. */
export interface Regime3D {
  combinedLabel: string;
  trendStrength: string;
  trendStrengthAdx: number;
  volatility: string;
  volatilityPositionInBand: number;
  liquidity: string;
  spreadHeadroomPct: number;
}

export type DecisionVerdict = 'BUY' | 'SELL' | 'HOLD' | 'VETO';

export interface DecisionBlock {
  verdict: DecisionVerdict;
  verdictLabel: string;
  probabilityPercent: number;
  entry: number;
  stop: number;
  targets: number[];
  lotSize: number;
  riskUsd: number;
  rewardUsd: number;
  riskRewardRatio: string;
  starRating: number;
  execution: 'DO_NOTHING' | 'EXECUTE';
}

export interface AnalysisSnapshot {
  symbol: string;
  regime3d: Regime3D;
  conviction: Conviction;
  gates: GateMarginCheck[];
  bullCase: CaseThesis;
  bearCase: CaseThesis;
  scenarioTree: ScenarioTree;
  probabilityLedger: ProbabilityLedgerStep[];
  decision: DecisionBlock;
  updatedAt: number;
}
