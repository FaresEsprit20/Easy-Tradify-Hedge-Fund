import { AiGroup } from '../models/ai.model';

/**
 * The AI layer's operable surface, grouped by owning Python module.
 *
 * Mirrors ai/ai_controller.py (port 5002) and api/trades_controller.py
 * (port 5011). Kept as data rather than as one hand-written page per group:
 * the controller carries 139 routes, and a bespoke template per route would
 * drift from the service the first time a route changed.
 *
 * Every `caveat` here is a real constraint from the engine, not UI padding.
 * They are rendered beside results because the failure mode this project keeps
 * hitting is a number that looks like a finding — a 61.5% win rate that a
 * permutation null shows is the median result of noise, or a mean R of +9.4
 * that comes from one trade on a one-pip stop.
 */
export const AI_GROUPS: readonly AiGroup[] = [
  // ----------------------------------------------------------------
  {
    id: 'research',
    label: 'Edge Discovery',
    module: 'ai/edge_discovery.py',
    port: 5002,
    blurb:
      'Searches the rule space by reweighting the probability chain and rescoring against the same real outcomes. Never generates synthetic prices.',
    operations: [
      {
        id: 'research.status',
        label: 'Status',
        method: 'GET',
        path: '/research/status',
        weight: 'read',
        summary: 'Module version and search method.',
      },
      {
        id: 'research.samples',
        label: 'Extract samples',
        method: 'POST',
        path: '/research/samples',
        weight: 'compute',
        summary:
          'One row per trade: ledger deltas in the traded frame, realised R, the price path and the measurement features.',
        caveat:
          'Deltas are signed against best_direction, which differs from the filled direction on ~19% of trades. Read in the wrong frame, a +0.49R component edge looks like a sign error.',
        params: [
          { key: 'include_rows', label: 'Include full rows', kind: 'boolean', value: false },
        ],
      },
      {
        id: 'research.features',
        label: 'Measurement features',
        method: 'POST',
        path: '/research/features',
        weight: 'compute',
        summary:
          'Flattens microstructure_at_entry, strategy_family_scores and component_reads into numeric features.',
        caveat:
          'These carry contribution 0.0 — they are measured alongside the decision and cannot move the probability until validated. A feature present on too few trades is excluded: it would produce a spectacular subset that means nothing, and cost an FDR correction against the ones that might be real.',
        params: [
          {
            key: 'min_present',
            label: 'Min trades per feature',
            kind: 'number',
            value: 10,
            note: 'Floor below which a feature is not testable.',
          },
        ],
      },
      {
        id: 'research.search',
        label: 'Search rule space',
        method: 'POST',
        path: '/research/search',
        weight: 'scan',
        summary:
          'Reweights every component, rescoring against real outcomes across walk-forward folds.',
        caveat:
          'Read the permutation null before the survivors. On 215 trades, the identical search against shuffled outcomes still found a best subset at 61.5% — so any 60% figure found by searching this data is the median result of noise.',
        params: [
          { key: 'max_components', label: 'Max components', kind: 'number', value: 2, note: 'Sparser configurations are likelier to be real.' },
          { key: 'folds', label: 'Walk-forward folds', kind: 'number', value: 4 },
          { key: 'permutations', label: 'Permutations', kind: 'number', value: 60 },
          { key: 'target_win_rate', label: 'Target win rate %', kind: 'number', value: 60 },
          { key: 'alpha', label: 'FDR alpha', kind: 'number', value: 0.1 },
          { key: 'allow_flip', label: 'Allow direction flip', kind: 'boolean', value: true, note: 'Direction entropy measures 1.0000 — an edge here may be an inverse one.' },
        ],
      },
      {
        id: 'research.searchFeatures',
        label: 'Condition on features',
        method: 'POST',
        path: '/research/search/features',
        weight: 'scan',
        summary:
          'Would skipping trades where a measurement opposes the fill have helped?',
        caveat:
          'Thresholds come from the train fold only — deriving them from the whole series is look-ahead, and the easiest way to manufacture an edge. Survivors clear a walk-forward, a permutation null and BH-FDR across every hypothesis tested.',
        params: [
          { key: 'folds', label: 'Folds', kind: 'number', value: 4 },
          { key: 'permutations', label: 'Permutations', kind: 'number', value: 60 },
          { key: 'alpha', label: 'FDR alpha', kind: 'number', value: 0.1 },
        ],
      },
      {
        id: 'research.selfCheck',
        label: 'Self-check',
        method: 'POST',
        path: '/research/self_check',
        weight: 'compute',
        summary: 'Plants a known answer and requires recovery, including the negative case.',
        caveat: 'A check that cannot fail is indistinguishable from a stub returning success.',
      },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'families',
    label: 'Strategy Families',
    module: 'ai/strategy_families.py',
    port: 5002,
    blurb:
      '23 categories over the probability chain, with opposition discovered rather than assumed.',
    operations: [
      { id: 'families.status', label: 'Status', method: 'GET', path: '/families/status', weight: 'read', summary: 'The family table.' },
      {
        id: 'families.classify',
        label: 'Classify a component',
        method: 'GET',
        path: '/families/classify/{name}',
        weight: 'read',
        summary: 'Which family a component belongs to.',
        caveat:
          'Longest token wins. Under first-match-wins, adr_exhaustion was swallowed by MEAN_REVERSION’s "exhaustion" and EXHAUSTION_ADR was unreachable entirely.',
        params: [{ key: 'name', label: 'Component', kind: 'text', value: 'adr_exhaustion' }],
      },
      {
        id: 'families.rows',
        label: 'Build rows',
        method: 'POST',
        path: '/families/rows',
        weight: 'compute',
        summary: 'Per trade: family scores, regime and realised R.',
      },
      {
        id: 'families.analyse',
        label: 'Analyse',
        method: 'POST',
        path: '/families/analyse',
        weight: 'scan',
        summary: 'A handful of pre-registered questions, not a search.',
        caveat:
          'Pre-registration is why this has real power where the 1,251-field audit had none. Returns inconclusive below the minimum group size rather than reporting a result it cannot support.',
        params: [
          { key: 'min_group', label: 'Min group size', kind: 'number', value: 12 },
          { key: 'folds', label: 'Folds', kind: 'number', value: 3 },
          { key: 'permutations', label: 'Permutations', kind: 'number', value: 300 },
        ],
      },
      {
        id: 'families.opposition',
        label: 'Opposition',
        method: 'POST',
        path: '/families/opposition',
        weight: 'compute',
        summary: 'Which families contradict each other on the same trade.',
        caveat:
          'TREND and MEAN_REVERSION conflict on 91.2% of trades — the chain adds a buy signal to a sell signal nine times in ten.',
      },
      { id: 'families.selfCheck', label: 'Self-check', method: 'POST', path: '/families/self_check', weight: 'compute', summary: 'Classification invariants.' },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'repository',
    label: 'Trade Repository',
    module: 'ai/trade_repository.py',
    port: 5002,
    blurb:
      'The bridge every model reads stored trades through. Flattens the analysis envelope and decodes each price point.',
    operations: [
      { id: 'repository.status', label: 'Status', method: 'GET', path: '/repository/status', weight: 'read', summary: 'Store health and trade counts.' },
      {
        id: 'repository.trades',
        label: 'Load trades',
        method: 'GET',
        path: '/repository/trades',
        weight: 'read',
        summary: 'Stored trades in the shape models read.',
        caveat:
          'Never returns raw Mongo documents. Raw documents look fine and yield nothing — build_rows() returns zero rows on them and all of them through the repository.',
        params: [
          { key: 'status', label: 'Status', kind: 'select', value: 'CLOSED', options: ['', 'OPEN', 'CLOSED'] },
          { key: 'symbol', label: 'Symbol', kind: 'text', value: '' },
          { key: 'limit', label: 'Limit', kind: 'number', value: 100 },
        ],
      },
      {
        id: 'repository.trade',
        label: 'Get one trade',
        method: 'GET',
        path: '/repository/trades/{trade_id}',
        weight: 'read',
        summary: 'One canonicalised trade.',
        params: [{ key: 'trade_id', label: 'Trade id', kind: 'text', value: 'trade_1922753302' }],
      },
      {
        id: 'repository.trainingSet',
        label: 'Training set',
        method: 'POST',
        path: '/repository/training_set',
        weight: 'compute',
        summary: 'Features, path and labels — returned separately.',
        caveat:
          'analysis_at_open + entry is what was known at T0; price_evolution is the forward walk; close_data is labels only. Merging them and trusting discipline is how a model ends up predicting the past.',
        params: [
          { key: 'status', label: 'Status', kind: 'select', value: 'CLOSED', options: ['', 'OPEN', 'CLOSED'] },
          { key: 'include_data', label: 'Include full payload', kind: 'boolean', value: false },
        ],
      },
      { id: 'repository.selfCheck', label: 'Self-check', method: 'POST', path: '/repository/self_check', weight: 'compute', summary: 'Decode boundary invariants.' },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'audit',
    label: 'Component Audit',
    module: 'ai/component_audit_360.py',
    port: 5002,
    blurb: 'The wide scan across every discovered field — numeric, categorical, quantile, mutual information, interaction, redundancy, regime, per-symbol.',
    operations: [
      { id: 'audit.status', label: 'Status', method: 'GET', path: '/audit/status', weight: 'read', summary: 'Layers the audit runs.' },
      {
        id: 'audit.run',
        label: 'Run audit',
        method: 'POST',
        path: '/audit/run',
        weight: 'scan',
        summary: 'Scores every scoreable field across eight layers.',
        caveat:
          'A wide scan over ~1,251 fields on a few hundred trades finds spectacular subsets in pure noise. Read this only alongside its own multiple-comparison correction and the permutation null.',
        params: [
          { key: 'folds', label: 'Folds', kind: 'number', value: 3 },
          { key: 'permutations', label: 'Permutations', kind: 'number', value: 200 },
          { key: 'alpha', label: 'FDR alpha', kind: 'number', value: 0.1 },
        ],
      },
      { id: 'audit.selfCheck', label: 'Self-check', method: 'POST', path: '/audit/self_check', weight: 'compute', summary: 'Audit invariants.' },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'history',
    label: 'History & Enrichment',
    module: 'ai/mt5_history.py, ai/history_enrichment.py',
    port: 5002,
    blurb:
      'The research corpus: closed positions from the MT5 account, and the analysis recomputed for them from the bars as they stood at entry.',
    operations: [
      { id: 'history.status', label: 'Status', method: 'GET', path: '/history/status', weight: 'read', summary: 'Connection and what cannot be recovered.' },
      {
        id: 'history.coverage',
        label: 'Coverage',
        method: 'GET',
        path: '/history/coverage',
        weight: 'read',
        summary: 'How much history is available.',
        params: [{ key: 'days', label: 'Days', kind: 'number', value: 365 }],
      },
      {
        id: 'history.positions',
        label: 'Closed positions',
        method: 'GET',
        path: '/history/positions',
        weight: 'read',
        summary: 'Positions paired IN deal to OUT deal on position_id.',
        caveat:
          'Direction comes from the opening deal’s type and profit from the broker’s deals — never inferred from the price move. That inference would have been wrong on 57.2% of these and would have manufactured a 98.8% win rate.',
        params: [{ key: 'days', label: 'Days', kind: 'number', value: 365 }],
      },
      {
        id: 'history.enrich',
        label: 'Enrich',
        method: 'POST',
        path: '/history/enrich',
        weight: 'scan',
        summary: 'Recomputes the analysis for past trades from bars at entry.',
        caveat:
          'Not simulated data — the analysis layer is deterministic over bars, so this is the real analysis recomputed. Any trade whose no-lookahead check finds a violation is refused rather than trusted.',
        params: [
          { key: 'days', label: 'Days', kind: 'number', value: 365 },
          { key: 'limit', label: 'Limit', kind: 'number', value: 25 },
        ],
      },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'gnn',
    label: 'Graph Neural Network',
    module: 'ai/ai_gnn.py',
    port: 5002,
    blurb: 'Cross-asset structure: correlations, divergences, contradiction detection and trade suggestions.',
    operations: [
      { id: 'gnn.status', label: 'Status', method: 'GET', path: '/gnn/status', weight: 'read', summary: 'Graph state and freshness.' },
      { id: 'gnn.insights', label: 'Insights', method: 'GET', path: '/gnn/insights/{symbol}', weight: 'compute', summary: 'Complete trading insights for a symbol.', params: [{ key: 'symbol', label: 'Symbol', kind: 'text', value: 'EURUSD' }] },
      { id: 'gnn.context', label: 'Context', method: 'GET', path: '/gnn/context/{symbol}', weight: 'read', summary: 'Graph context used by the analysis chain.', params: [{ key: 'symbol', label: 'Symbol', kind: 'text', value: 'EURUSD' }] },
      { id: 'gnn.correlations', label: 'Correlations', method: 'GET', path: '/gnn/correlations/{symbol}', weight: 'read', summary: 'Correlated instruments.', params: [{ key: 'symbol', label: 'Symbol', kind: 'text', value: 'EURUSD' }] },
      { id: 'gnn.divergences', label: 'Divergences', method: 'GET', path: '/gnn/divergences/{symbol}', weight: 'read', summary: 'Where the graph disagrees with price.', params: [{ key: 'symbol', label: 'Symbol', kind: 'text', value: 'EURUSD' }] },
      { id: 'gnn.conflict', label: 'Conflict', method: 'GET', path: '/gnn/conflict/{symbol}', weight: 'compute', summary: 'Contradiction detection across the graph.', params: [{ key: 'symbol', label: 'Symbol', kind: 'text', value: 'EURUSD' }] },
      { id: 'gnn.suggestions', label: 'Suggestions', method: 'GET', path: '/gnn/suggestions/{symbol}', weight: 'compute', summary: 'Trade suggestions from cross-asset structure.', params: [{ key: 'symbol', label: 'Symbol', kind: 'text', value: 'EURUSD' }] },
      { id: 'gnn.heatmap', label: 'Heatmap', method: 'GET', path: '/gnn/heatmap', weight: 'compute', summary: 'Correlation heatmap across the watched universe.' },
      { id: 'gnn.abTest', label: 'A/B test', method: 'GET', path: '/gnn/ab_test', weight: 'read', summary: 'Current experiment split and results.' },
      { id: 'gnn.refresh', label: 'Refresh graph', method: 'POST', path: '/gnn/refresh', weight: 'compute', summary: 'Force a graph rebuild.', guarded: true },
      { id: 'gnn.reset', label: 'Reset graph', method: 'POST', path: '/gnn/reset', weight: 'compute', summary: 'Discard learned state.', guarded: true, caveat: 'Destroys accumulated cross-asset learning. There is no undo.' },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'adversarial',
    label: 'Adversarial',
    module: 'ai/ai_adversarial.py',
    port: 5002,
    blurb: 'Robustness probing: is a signal fragile under small perturbations of its own inputs?',
    operations: [
      { id: 'adv.status', label: 'Status', method: 'GET', path: '/adversarial/status', weight: 'read', summary: 'Attack configuration and intensity.' },
      { id: 'adv.metrics', label: 'Metrics', method: 'GET', path: '/adversarial/metrics', weight: 'read', summary: 'Attack success rates by field.' },
      { id: 'adv.generate', label: 'Generate attacks', method: 'POST', path: '/adversarial/generate', weight: 'compute', summary: 'Produce perturbed variants of supplied trades.' },
      { id: 'adv.train', label: 'Apply to training', method: 'POST', path: '/adversarial/train', weight: 'scan', summary: 'Train against adversarial variants.', guarded: true },
      { id: 'adv.intensity', label: 'Set intensity', method: 'POST', path: '/adversarial/intensity', weight: 'read', summary: 'Perturbation magnitude.', guarded: true, params: [{ key: 'intensity', label: 'Intensity', kind: 'number', value: 0.3 }] },
      { id: 'adv.enable', label: 'Enable / disable', method: 'POST', path: '/adversarial/enable', weight: 'read', summary: 'Toggle adversarial evaluation.', guarded: true, params: [{ key: 'enabled', label: 'Enabled', kind: 'boolean', value: true }] },
      { id: 'adv.probe', label: 'Replay probe', method: 'POST', path: '/adversarial/replay/probe', weight: 'scan', summary: 'Probe a replayed decision for fragility.' },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'replay',
    label: 'Replay & Counterfactual',
    module: 'ai/replay_engine.py, ai/counterfactual.py',
    port: 5002,
    blurb: 'Deterministic, lookahead-safe replay of real decisions, and what a different choice would have returned.',
    operations: [
      { id: 'replay.status', label: 'Status', method: 'GET', path: '/replay/status', weight: 'read', summary: 'Replay engine state.' },
      { id: 'replay.run', label: 'Run replay', method: 'POST', path: '/replay/run', weight: 'scan', summary: 'Replay stored decisions against real bars.', caveat: 'Reports calibration and expectancy, never raw win rate.' },
      { id: 'replay.counterfactual', label: 'Counterfactual', method: 'POST', path: '/replay/counterfactual', weight: 'scan', summary: 'What a different entry, exit or size would have returned.' },
      { id: 'replay.consistency', label: 'Consistency', method: 'POST', path: '/replay/consistency', weight: 'compute', summary: 'Does replay reproduce the live decision exactly?' },
      { id: 'replay.stress', label: 'Stress', method: 'POST', path: '/replay/stress', weight: 'scan', summary: 'Replay under perturbed conditions.' },
      { id: 'replay.phase1Extract', label: 'Extract phase 1', method: 'POST', path: '/replay/phase1/extract', weight: 'compute', summary: 'Build the replay corpus.' },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'models',
    label: 'Models',
    module: 'ai/exit_model.py, target_model.py, calibration_model.py, abstention_model.py',
    port: 5002,
    blurb:
      'Decision models trained on stored trades. Each returns a promotion verdict, never a promoted model by default.',
    operations: [
      { id: 'models.exitTrain', label: 'Train exit model', method: 'POST', path: '/exit_model/train', weight: 'scan', summary: 'When to leave a trade.', caveat: 'rejected_because is the useful output when it fails.', guarded: true },
      { id: 'models.targetTrain', label: 'Train target model', method: 'POST', path: '/target_model/train', weight: 'scan', summary: 'Whether to extend a winner.', guarded: true },
      { id: 'models.calibrationTrain', label: 'Train calibration', method: 'POST', path: '/calibration/train', weight: 'scan', summary: 'Does a stated probability match the realised rate?', guarded: true },
      { id: 'models.abstentionTrain', label: 'Train abstention', method: 'POST', path: '/abstention/train', weight: 'scan', summary: 'When to decline to trade at all.', guarded: true },
      { id: 'models.exitStatus', label: 'Exit status', method: 'GET', path: '/exit_model/status', weight: 'read', summary: 'Exit model state.' },
      { id: 'models.calibrationStatus', label: 'Calibration status', method: 'GET', path: '/calibration/status', weight: 'read', summary: 'Calibration state.' },
      { id: 'models.abstentionStatus', label: 'Abstention status', method: 'GET', path: '/abstention/status', weight: 'read', summary: 'Abstention state.' },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'governance',
    label: 'Governance & Performance',
    module: 'ai/model_governance.py, ai/model_performance.py',
    port: 5002,
    blurb:
      'The gate between research and production: A/B assignment, rollout, promotion and rollback, plus drift on live models.',
    operations: [
      { id: 'gov.status', label: 'Status', method: 'GET', path: '/governance/status', weight: 'read', summary: 'Registry state across models.' },
      { id: 'gov.registry', label: 'Registry', method: 'GET', path: '/governance/{model}/registry', weight: 'read', summary: 'Versions and their verdicts.', params: [{ key: 'model', label: 'Model', kind: 'text', value: 'exit_model' }] },
      { id: 'gov.abTest', label: 'A/B results', method: 'GET', path: '/governance/{model}/ab_test', weight: 'read', summary: 'Split and measured difference.', params: [{ key: 'model', label: 'Model', kind: 'text', value: 'exit_model' }] },
      { id: 'gov.rollout', label: 'Set rollout', method: 'POST', path: '/governance/{model}/ab_test/rollout', weight: 'read', summary: 'Traffic share for the candidate.', guarded: true, params: [{ key: 'model', label: 'Model', kind: 'text', value: 'exit_model' }, { key: 'percent', label: 'Rollout %', kind: 'number', value: 10 }] },
      { id: 'gov.promote', label: 'Promote', method: 'POST', path: '/governance/{model}/promote', weight: 'compute', summary: 'Make the candidate the production model.', guarded: true, caveat: 'Experimental models must never become production logic without validation. This is that gate.', params: [{ key: 'model', label: 'Model', kind: 'text', value: 'exit_model' }] },
      { id: 'gov.rollback', label: 'Rollback', method: 'POST', path: '/governance/{model}/rollback', weight: 'compute', summary: 'Return to the previous production model.', guarded: true, params: [{ key: 'model', label: 'Model', kind: 'text', value: 'exit_model' }] },
      { id: 'perf.ranking', label: 'Model ranking', method: 'GET', path: '/performance/ranking', weight: 'read', summary: 'Live models ordered by measured performance.' },
      { id: 'perf.drift', label: 'Drift', method: 'GET', path: '/performance/{model}/drift', weight: 'compute', summary: 'Has the live distribution moved away from training?', params: [{ key: 'model', label: 'Model', kind: 'text', value: 'exit_model' }] },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'store',
    label: 'Trade Store',
    module: 'api/trades_controller.py',
    port: 5011,
    blurb:
      'CRUD over the MongoDB trades collection. A separate service from the AI controller — it owns the collection.',
    operations: [
      { id: 'store.health', label: 'Health', method: 'GET', path: '/api/v1/trades/health', weight: 'read', summary: 'Whether the Mongo server answered.', caveat: 'Not whether a client object exists — holding one proves nothing, pymongo builds it without contacting anything.' },
      { id: 'store.list', label: 'List trades', method: 'GET', path: '/api/v1/trades', weight: 'read', summary: 'A bounded, sorted page.', params: [{ key: 'status', label: 'Status', kind: 'select', value: '', options: ['', 'OPEN', 'CLOSED'] }, { key: 'symbol', label: 'Symbol', kind: 'text', value: '' }, { key: 'page_size', label: 'Page size', kind: 'number', value: 25 }] },
      { id: 'store.stats', label: 'Performance', method: 'GET', path: '/api/v1/trades/stats/performance', weight: 'compute', summary: 'Win rate, expectancy and realised P/L.', caveat: 'Trades collected under loosened data-collection gates do not represent the strategy. With a one-pip risk unit, mean R can sit above +9 while the median is negative.' },
      { id: 'store.bySymbol', label: 'By symbol', method: 'GET', path: '/api/v1/trades/stats/by-symbol', weight: 'compute', summary: 'The same breakdown per instrument.', caveat: 'An edge carried by one instrument is that instrument’s, not the strategy’s.' },
      { id: 'store.shape', label: 'Shape check', method: 'GET', path: '/api/v1/trades/diagnostics/shape', weight: 'compute', summary: 'Are stored trades readable by the AI layer?', caveat: 'A trade missing entry.price, entry.stop_loss or direction is skipped silently by every model. A rising trade count is not evidence that collection is working.' },
      { id: 'store.diagnostics', label: 'Diagnostics', method: 'GET', path: '/api/v1/trades/diagnostics', weight: 'compute', summary: 'Scan stored trades for defects.' },
      { id: 'store.purge', label: 'Purge deleted', method: 'POST', path: '/api/v1/trades/purge', weight: 'compute', summary: 'Permanently remove soft-deleted trades.', guarded: true, caveat: 'Destroys the only record of real trades. Requires explicit confirmation.', params: [{ key: 'older_than_days', label: 'Older than (days)', kind: 'number', value: 30 }] },
    ],
  },

  // ----------------------------------------------------------------
  {
    id: 'verify',
    label: 'Whole-layer Verify',
    module: 'ai/ai_controller.py',
    port: 5002,
    blurb: 'Runs every module’s self-check in one call.',
    operations: [
      {
        id: 'verify.all',
        label: 'Verify everything',
        method: 'POST',
        path: '/verify',
        weight: 'scan',
        summary: 'Every self_check across the AI layer.',
        caveat:
          'A module answering "inconclusive" is not a failure — it usually means too few trades to test. Treating that as either a pass or a failure is how an empty collection reads as a result.',
      },
    ],
  },
];

/** Flat lookup for the console. */
export const AI_OPERATIONS = AI_GROUPS.flatMap((g) =>
  g.operations.map((op) => ({ group: g, op })),
);
