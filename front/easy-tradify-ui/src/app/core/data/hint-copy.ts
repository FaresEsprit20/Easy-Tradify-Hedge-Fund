// Plain-language explanations for the jargon-heavy terms scattered across
// the app — gate names, SMC/ICT concepts, decision-engine scoring. Centralized
// so the same term reads identically everywhere it appears (gate names show
// up in both the Analysis workbench and the live Gate/Coherence ticker).

export const GATE_HINTS: Record<string, string> = {
  choppy_market: 'Blocks entries when trend strength (ADX) is too low — a choppy, range-bound market has no reliable directional edge.',
  extreme_volatility: 'Blocks entries when volatility (ATR) is abnormally high — fast, erratic price fills worse than quoted and stops get hunted.',
  low_volume: 'Blocks entries when volume is too thin relative to normal — low liquidity means wider slippage and less reliable price discovery.',
  high_spread: "Blocks entries when the bid/ask spread is too wide — it eats into the trade's edge before the position even opens.",
  wick_reversal: 'Blocks entries right after a long rejection wick — a strong wick often means the move is about to reverse against the signal.',
  candle_too_young: "Blocks entries on a candle that just opened — waits for enough of the bar to complete so the signal isn't based on an incomplete read.",
  rsi_divergence_opposing: 'Blocks entries when RSI is diverging against the trade direction — an early warning that momentum is fading.',
  probability_threshold: "Blocks entries below the minimum win-probability the strategy requires before it will risk capital.",
  session_veto: 'Blocks entries outside the trading sessions this strategy is allowed to trade in.',
  news_veto: 'Blocks entries around high-impact news events, when price action becomes unreliable.',
  against_trend: 'Blocks entries that go against the prevailing higher-timeframe trend.',
  against_ema: "Blocks entries on the wrong side of a key moving average.",
  h1_conflict: 'Blocks entries when the H1 timeframe trend conflicts with this signal.',
};

export const OVERLAY_HINTS = {
  entryStopTargets: 'The proposed entry price, stop loss, and take-profit levels (TP1/TP2/TP3) for this setup.',
  supportResistance: 'Support & Resistance — the pivot point plus two resistance (R1/R2) and two support (S1/S2) levels from recent price structure.',
  supplyDemand: 'The nearest supply or demand zone the entry logic is watching, graded A (strongest) to C (weakest) by freshness and clarity.',
  smc: 'Smart Money Concepts — order blocks (jade = bullish, coral = bearish), Fair Value Gaps colored by direction, and the BOS/CHoCH structure breaks with any liquidity sweep, all from the same analysis pass.',
  premiumDiscount: "The current swing range split into thirds (ICT 'OTE'): Discount favors buying, Equilibrium is neutral, Premium favors selling.",
  elliottWave: 'An automated 5-wave impulse count (0-5) — a classical technical-analysis pattern used to anticipate the next leg of a move.',
  patterns: 'Detected candlestick/chart patterns (engulfing, flags, triangles, head & shoulders, etc.) with a confidence score for each.',
};

export const DECISION_HINTS = {
  conviction:
    'A weighted score (0-1) combining internal coherence, confluence between indicator families, and how much margin the weakest gate passed by. Must clear the minimum to count as a valid setup.',
  coherence: "Whether the decision engine's internal logic is self-consistent — e.g. a BUY verdict can't coexist with a bearish override. Violations mean the snapshot shouldn't be trusted.",
  starRating: '1-5 stars summarizing overall setup quality — probability, risk/reward, and conviction combined into one glance.',
  riskReward: 'How much reward is targeted per dollar risked — e.g. 1:1.5 means risking $1 to target $1.50.',
  gateChecks: 'Hard pass/fail filters the setup must clear before the strategy will act on it — a single failed enforced gate vetoes the trade regardless of probability.',
  probabilityLedger: "A running total showing how the win-probability estimate was adjusted step by step — each row is one factor's contribution, clamped ones hit a hard ceiling/floor.",
  scenarioTree: "The primary path if the setup plays out, the invalidation path if the stop is hit first, and an alternate path if price never triggers the entry at all.",
  bullBearCase: 'Every indicator currently arguing for this direction, with its own confidence score and the specific reading behind it.',
  gnnCorrelation: 'A graph neural network cross-references this symbol against correlated instruments to flag when the broader market disagrees with the signal.',
  smartMoneyConcepts: 'Aggregates order-block, liquidity-sweep, and market-structure signals into one directional read, plus a confluence count out of the total possible signals.',
  orderFlow: 'Reads recent tick-level buy/sell imbalance and stop-hunt reclaims to gauge real-time aggression behind the move.',
} as const;
