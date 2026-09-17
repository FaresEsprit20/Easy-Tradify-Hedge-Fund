import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiClient } from '../../http/api-client.service';
import { ApiError } from '../../http/api-error';
import { SERVICE } from '../../http/services';
import { environment } from '../../../../environments/environment';
import {
  AiOperation,
  AiRunResult,
  ProcessStage,
  RunOutcome,
  StageProgress,
} from '../../models/ai.model';

/**
 * Mock driver for the AI layer console.
 *
 * NOT WIRED TO A BACKEND. Every result below is fabricated locally so the whole
 * operable surface can be designed and reviewed before any endpoint is called
 * for real. `AiOperation.method` / `.path` record the eventual target, so
 * replacing `run()` with an HttpClient call is the only change needed.
 *
 * WHY THE MOCKS ARE UNFLATTERING
 * ------------------------------
 * The sample results deliberately include inconclusive verdicts, tiny trade
 * counts and a permutation null that beats the survivors. A console demoed on
 * clean, always-successful data teaches the wrong reflexes: the states that
 * actually need to be legible here are "too few trades to test" and "the null
 * found this too", because those are the answers this engine gives most often
 * and the ones most easily misread as findings.
 */
@Injectable({ providedIn: 'root' })
export class AiApiService {
  private readonly api = inject(ApiClient);

  /**
   * True when the last run's payload came from the backend rather than a mock.
   *
   * Displayed beside the result. This console's whole purpose is separating
   * findings from noise, so a fabricated payload that is not labelled as one
   * defeats it entirely.
   */
  readonly lastRunWasLive = signal(false);

  /** Stage list for the currently running operation. */
  readonly stages = signal<readonly StageProgress[]>([]);
  readonly running = signal(false);
  readonly activeOperationId = signal<string | null>(null);
  readonly lastResult = signal<AiRunResult | null>(null);

  /** Every run this session, newest first — the console's audit trail. */
  readonly history = signal<readonly AiRunResult[]>([]);

  private cancelled = false;

  // ------------------------------------------------------------
  // STAGES
  // ------------------------------------------------------------

  /**
   * The stages an operation moves through.
   *
   * A `scan` shows the full pipeline including the controls — folds, the
   * permutation null, FDR — because those steps are the substance of the
   * result, not overhead. Hiding them behind a single spinner is how a search
   * comes to look like a lookup.
   */
  private stagesFor(op: AiOperation): readonly ProcessStage[] {
    if (op.weight === 'read') {
      return [
        { label: 'Connect', weight: 1 },
        { label: 'Read', weight: 1 },
      ];
    }
    if (op.weight === 'compute') {
      return [
        { label: 'Load trades', weight: 1.2 },
        { label: 'Canonicalise', weight: 1 },
        { label: 'Build rows', weight: 1.4 },
        { label: 'Summarise', weight: 0.8 },
      ];
    }
    return [
      { label: 'Load trades', weight: 1.2 },
      { label: 'Canonicalise', weight: 0.9 },
      { label: 'Extract samples', weight: 1.3 },
      { label: 'Walk-forward folds', weight: 2.2 },
      { label: 'Permutation null', weight: 2.6 },
      { label: 'FDR correction', weight: 1.1 },
      { label: 'Rank survivors', weight: 0.9 },
    ];
  }

  // ------------------------------------------------------------
  // RUN
  // ------------------------------------------------------------

  /** Cancels the in-flight run; stages stop where they are. */
  cancel(): void {
    this.cancelled = true;
  }

  /**
   * Run an operation, driving the stage animation from the REAL request.
   *
   * HOW THE ANIMATION SURVIVED GOING LIVE
   * -------------------------------------
   * The stage list is not decoration — it is the only honest depiction of what
   * these endpoints do, because a walk-forward scan genuinely is folds, then a
   * permutation null, then an FDR correction, and collapsing that into one
   * spinner is what makes a search look like a lookup. But the backend reports
   * no per-stage progress, so the stages cannot simply be slaved to it.
   *
   * The compromise: fire the request immediately, then advance the stages on
   * their own timeline while it is in flight. If the response lands early the
   * remaining stages are fast-forwarded rather than cut off, so the pipeline is
   * still read; if it takes longer, the final stage HOLDS in `active` instead
   * of completing on a lie. The animation therefore never claims a step
   * finished before the work did.
   */
  async run(op: AiOperation, params: Record<string, unknown> = {}): Promise<AiRunResult> {
    const plan = this.stagesFor(op);
    this.cancelled = false;
    this.running.set(true);
    this.activeOperationId.set(op.id);
    this.lastResult.set(null);
    this.stages.set(plan.map((s) => ({ label: s.label, state: 'pending' as const })));

    const startedAt = Date.now();
    const unit = op.weight === 'scan' ? 190 : op.weight === 'compute' ? 150 : 120;

    // Start the call BEFORE the animation, so the two overlap and the stage
    // timings are hiding real latency rather than being added to it.
    let settled = false;
    const request = this.callBackend(op, params)
      .then((value) => ({ ok: true as const, value }))
      .catch((error: unknown) => ({ ok: false as const, error }))
      .finally(() => {
        settled = true;
      });

    for (let i = 0; i < plan.length; i++) {
      if (this.cancelled) {
        this.stages.update((list) =>
          list.map((s, idx) => (idx === i ? { ...s, state: 'failed' as const } : s)),
        );
        return this.finish(op, startedAt, 'refused', 499, 'Cancelled before completion.', {
          cancelled_at_stage: plan[i].label,
        });
      }

      this.stages.update((list) =>
        list.map((s, idx) => (idx === i ? { ...s, state: 'active' as const } : s)),
      );

      const isLast = i === plan.length - 1;
      if (isLast) {
        // Hold the last stage open until the answer is actually here.
        await request;
      } else {
        // Once the response is in, the remaining stages are known to be done;
        // run them at a tenth of the time so the pipeline still reads.
        await this.sleep(unit * plan[i].weight * (settled ? 0.1 : 1));
      }

      this.stages.update((list) =>
        list.map((s, idx) => (idx === i ? { ...s, state: 'done' as const } : s)),
      );
    }

    const outcomeOfRequest = await request;

    if (outcomeOfRequest.ok && outcomeOfRequest.value !== null) {
      this.lastRunWasLive.set(true);
      const { status, payload } = outcomeOfRequest.value;
      return this.finish(op, startedAt, outcomeFor(payload), status, summarise(op, payload), payload);
    }

    if (!outcomeOfRequest.ok) {
      const error = outcomeOfRequest.error;
      const message = error instanceof ApiError ? error.message : String(error);
      const status = error instanceof ApiError ? error.status : 0;

      // A route the Java layer has not exposed yet is a gap, not a failure of
      // the run — fall through to the mock so the console stays usable, but say
      // plainly which it was.
      const notImplemented = error instanceof ApiError && error.status === 404;
      if (!notImplemented && !(environment.allowMockFallback && error instanceof ApiError && error.isPlatformFailure)) {
        this.lastRunWasLive.set(true);
        this.stages.update((list) => {
          const active = list.findIndex((s) => s.state !== 'done');
          return list.map((s, idx) => (idx === active ? { ...s, state: 'failed' as const } : s));
        });
        return this.finish(op, startedAt, 'refused', status, message, { error: message });
      }

      this.lastRunWasLive.set(false);
      const mock = this.resultFor(op, params);
      return this.finish(
        op,
        startedAt,
        mock.outcome,
        mock.status,
        notImplemented
          ? `${mock.summary}  [MOCK — ${op.method} ${op.path} is not exposed by the gateway]`
          : `${mock.summary}  [MOCK — backend unreachable: ${message}]`,
        mock.payload,
      );
    }

    this.lastRunWasLive.set(false);
    const mock = this.resultFor(op, params);
    return this.finish(op, startedAt, mock.outcome, mock.status, `${mock.summary}  [MOCK]`, mock.payload);
  }

  /**
   * Issue the operation's actual HTTP call.
   *
   * Returns null when mocks are preferred and nothing has been reached yet, so
   * the caller can decide rather than having a fabricated payload handed to it.
   */
  private async callBackend(
    op: AiOperation,
    params: Record<string, unknown>,
  ): Promise<{ status: number; payload: unknown } | null> {
    const body = toSnakeKeys(params);

    const payload =
      op.method === 'GET'
        ? await firstValueFrom(
            this.api.get<unknown>(SERVICE.ai, op.path, body as Record<string, string | number | boolean>),
          )
        : await firstValueFrom(this.api.post<unknown>(SERVICE.ai, op.path, body));

    return { status: 200, payload };
  }

  private finish(
    op: AiOperation,
    startedAt: number,
    outcome: RunOutcome,
    status: number,
    summary: string,
    payload: unknown,
  ): AiRunResult {
    const result: AiRunResult = {
      operationId: op.id,
      outcome,
      status,
      startedAt,
      durationMs: Date.now() - startedAt,
      summary,
      payload,
    };
    this.lastResult.set(result);
    this.history.update((h) => [result, ...h].slice(0, 40));
    this.running.set(false);
    this.activeOperationId.set(null);
    return result;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // ------------------------------------------------------------
  // MOCK RESULTS
  // ------------------------------------------------------------

  private resultFor(
    op: AiOperation,
    params: Record<string, unknown>,
  ): { outcome: RunOutcome; status: number; summary: string; payload: unknown } {
    switch (op.id) {
      case 'research.status':
        return {
          outcome: 'ok', status: 200, summary: 'edge_discovery 1.0',
          payload: { component: 'edge_discovery', method: 'ledger reweighting on real outcomes', synthetic_prices: false, version: '1.0' },
        };

      case 'research.samples':
        return {
          outcome: 'ok', status: 200, summary: '12 samples from 13 closed trades — 1 dropped.',
          payload: {
            trades_in: 13, samples: 12, dropped: 1,
            components: ['order_flow', 'pattern', 'smc', 'fvg_ifvg', 'rvam', 'trend_cascade', 'vwap_context', 'nested_zone', 'family_vote', 'h1_alignment', 'gap_slippage', 'gnn'],
            features: ['family_scores.ORDER_FLOW', 'component_reads.gnn.confidence', 'component_reads.smc_setup.confluence_count'],
          },
        };

      case 'research.features':
        return {
          outcome: 'inconclusive', status: 200,
          summary: 'Channels present, but none reach the 10-trade floor yet.',
          payload: {
            samples: 12,
            channels: ['microstructure_at_entry', 'microstructure_bias', 'strategy_family_scores', 'component_reads'],
            testable: [],
            min_present: Number(params['min_present'] ?? 10),
            all_present_count: 35,
          },
        };

      case 'research.search':
        return {
          outcome: 'inconclusive', status: 200,
          summary: '40,384 configurations tested — none retained enough trades to score.',
          payload: {
            ok: false, samples: 12, configurations_tested: 40384,
            conclusion: 'no configuration retained enough trades to score',
            baseline: { expectancy: 9.417, trades: 4, win_rate: 25.0 },
            note: 'The baseline expectancy above comes from 4 trades on ~1-pip stops. It is noise, not edge.',
          },
        };

      case 'research.searchFeatures':
        return {
          outcome: 'inconclusive', status: 200,
          summary: 'No hypothesis had enough held-out trades.',
          payload: { tested: 0, survivors: [], reason: 'no hypothesis had enough held-out trades' },
        };

      case 'families.classify':
        return {
          outcome: 'ok', status: 200, summary: `${params['name'] ?? 'adr_exhaustion'} → EXHAUSTION_ADR`,
          payload: { component: params['name'] ?? 'adr_exhaustion', family: 'EXHAUSTION_ADR' },
        };

      case 'families.rows':
        return { outcome: 'ok', status: 200, summary: '12 rows from 13 trades.', payload: { trades_in: 13, rows: 12, dropped: 1 } };

      case 'families.analyse':
        return {
          outcome: 'inconclusive', status: 200, summary: 'Only 12 trades — below the minimum group size.',
          payload: { component: 'strategy_families', ok: null, reason: 'only 12 trades', trades: 12 },
        };

      case 'families.opposition':
        return {
          outcome: 'ok', status: 200, summary: 'TREND vs MEAN_REVERSION conflict on 91.2% of trades.',
          payload: { rows: 12, family_opposition: [{ pair: ['TREND', 'MEAN_REVERSION'], conflict_rate: 0.912 }] },
        };

      case 'repository.status':
        return {
          outcome: 'ok', status: 200, summary: '15 trades — 13 closed, 2 open.',
          payload: { component: 'trade_repository', healthy: true, source: 'mongodb', trades_total: 15, trades_closed: 13, trades_open: 2 },
        };

      case 'repository.trades':
        return { outcome: 'ok', status: 200, summary: '13 trades matched.', payload: { count: 13, query: { status: params['status'] ?? 'CLOSED' } } };

      case 'repository.trainingSet':
        return {
          outcome: 'ok', status: 200, summary: 'Features, path and labels returned separately.',
          payload: { features: 12, path: 12, labels: 12, note: 'Never merged — merging is how a model predicts the past.' },
        };

      case 'audit.run':
        return {
          outcome: 'inconclusive', status: 200, summary: '1,251 fields scanned; nothing survives FDR at this sample size.',
          payload: { fields_scanned: 1251, fields_varying: 921, survivors_after_fdr: 0, permutation_best: 0.615, note: 'The null found a 61.5% subset. Any survivor must beat that.' },
        };

      case 'history.coverage':
        return { outcome: 'ok', status: 200, summary: '250 closed positions available.', payload: { days: Number(params['days'] ?? 365), positions: 250, with_stops: 220 } };

      case 'history.positions':
        return {
          outcome: 'ok', status: 200, summary: '250 positions — direction from the broker’s deal type.',
          payload: { days: Number(params['days'] ?? 365), count: 250, win_rate: 31.6, buys: 127, sells: 123 },
        };

      case 'history.enrich':
        return {
          outcome: 'ok', status: 200, summary: 'Enriched 24 of 25 — 1 refused on a lookahead violation.',
          payload: { positions_in: 25, enriched: 24, refused: 1, refusal_reason: 'no-lookahead check found a violation' },
        };

      case 'store.health':
        return { outcome: 'ok', status: 200, summary: 'Mongo answered.', payload: { ok: true, server_answered: true, database: 'easytradify', collection: 'trades' } };

      case 'store.stats':
        return {
          outcome: 'ok', status: 200, summary: '13 closed — 33% win, mean R +9.49, median R −0.95.',
          payload: { closed: 13, win_rate: 33.3, mean_r: 9.49, median_r: -0.95, net_profit_usd: 8.12, warning: 'Mean and median disagree because the risk unit is ~1 pip on several trades.' },
        };

      case 'store.shape':
        return {
          outcome: 'ok', status: 200, summary: 'All 13 sampled trades are readable by the AI layer.',
          payload: { sampled: 13, with_entry_price: 13, with_entry_stop_loss: 13, with_direction: 13, with_opened_at: 13, scoreable_by_ai_layer: 13, unusable_trade_ids: [] },
        };

      case 'store.purge':
        return { outcome: 'refused', status: 400, summary: 'Refused — purge requires explicit confirmation.', payload: { error: 'purge permanently removes soft-deleted trades and requires confirm=true' } };

      case 'verify.all':
        return {
          outcome: 'inconclusive', status: 200, summary: '15 modules ok, 12 inconclusive (too few trades), 0 failing.',
          payload: { ok: 15, inconclusive: 12, failing: 0, note: 'Inconclusive is not a failure — it means there was not enough data to test.' },
        };

      case 'gnn.status':
        return { outcome: 'ok', status: 200, summary: 'Graph live, 64 symbols.', payload: { available: true, symbols: 64, source: 'MT5', last_refresh_seconds: 42 } };

      case 'gnn.insights':
        return {
          outcome: 'ok', status: 200, summary: `${params['symbol'] ?? 'EURUSD'} — NEUTRAL, score 0.0.`,
          payload: { symbol: params['symbol'] ?? 'EURUSD', recommendation: 'NEUTRAL', score: 0.0, price_dir: 0.01, gnn_dir: 0.03, suggestions: 1 },
        };

      case 'gnn.reset':
        return { outcome: 'ok', status: 200, summary: 'Graph state discarded.', payload: { reset: true } };

      case 'adv.status':
        return { outcome: 'ok', status: 200, summary: 'Enabled, intensity 0.30.', payload: { enabled: true, intensity: 0.3, attacks_tracked: 82 } };

      case 'gov.status':
        return {
          outcome: 'ok', status: 200, summary: '4 registries — none with a promoted candidate.',
          payload: { models: ['exit_model', 'target_model', 'calibration_model', 'abstention_model'], promoted: 0, note: 'A candidate must clear validation before promotion — this is that gate.' },
        };

      case 'gov.promote':
        return { outcome: 'refused', status: 409, summary: 'Refused — candidate has no passing validation record.', payload: { promoted: false, rejected_because: 'no walk-forward result on file for this version' } };

      default:
        break;
    }

    // Generic shapes by weight, so every operation has a plausible result.
    if (op.id.endsWith('.selfCheck') || op.id.endsWith('selfCheck')) {
      return { outcome: 'ok', status: 200, summary: 'Self-check passed, including the negative case.', payload: { ok: true, findings: [] } };
    }
    if (op.id.endsWith('.status') || op.weight === 'read') {
      return { outcome: 'ok', status: 200, summary: 'Read.', payload: { component: op.path, ok: true } };
    }
    return {
      outcome: 'inconclusive', status: 200,
      summary: 'Ran, but the current sample is too small to conclude.',
      payload: { ok: null, reason: 'insufficient trades', trades: 12 },
    };
  }
}

// ====================================================================
// HELPERS
// ====================================================================

/**
 * Parameter keys as the UI names them -> as the Python controller reads them.
 *
 * The param definitions in `ai-endpoints.ts` already use the controller's own
 * snake_case keys (`min_present`, `include_rows`), so this is a no-op for
 * those. It exists for the handful that were written camelCase, and it is
 * cheaper than auditing 139 route definitions for spelling.
 */
function toSnakeKeys(params: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    out[key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`)] = value;
  }
  return out;
}

/**
 * Read the engine's own verdict out of the payload.
 *
 * Deliberately conservative. A 200 does NOT mean a finding: this engine's most
 * common honest answer is "too few trades to test", and mapping that to `ok`
 * would dress a non-result as a result — the exact misreading the console
 * exists to prevent. Anything that does not positively assert a survivor is
 * reported as inconclusive.
 */
function outcomeFor(payload: unknown): RunOutcome {
  if (!payload || typeof payload !== 'object') return 'inconclusive';

  const body = payload as Record<string, unknown>;

  if (body['success'] === false || body['error']) return 'refused';

  const survivors = body['survivors'];
  if (Array.isArray(survivors)) {
    return survivors.length > 0 ? 'ok' : 'inconclusive';
  }

  if (typeof body['inconclusive'] === 'boolean') {
    return body['inconclusive'] ? 'inconclusive' : 'ok';
  }

  // A plain status/health style response with no verdict in it is a fact, not
  // a finding, and `ok` is the right reading for those.
  if (body['status'] || body['version'] || body['component']) return 'ok';

  return 'inconclusive';
}

/** One line describing what came back, preferring the backend's own wording. */
function summarise(op: AiOperation, payload: unknown): string {
  if (payload && typeof payload === 'object') {
    const body = payload as Record<string, unknown>;
    for (const key of ['summary', 'message', 'verdict', 'error'] as const) {
      const value = body[key];
      if (typeof value === 'string' && value.trim()) return value;
    }

    const survivors = body['survivors'];
    if (Array.isArray(survivors)) {
      return survivors.length === 0
        ? 'No rule survived the permutation null and FDR correction.'
        : `${survivors.length} rule(s) survived the null and the FDR correction.`;
    }
  }
  return `${op.label} completed.`;
}
