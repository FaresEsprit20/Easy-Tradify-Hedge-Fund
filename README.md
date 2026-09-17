# EasyTradify

> **Enterprise Algorithmic Trading & Market Intelligence Platform**

EasyTradify is an algorithmic trading platform designed to combine automated execution, market monitoring, portfolio risk management, advanced market intelligence, replay analysis, counterfactual evaluation, Graph Neural Networks, adversarial robustness, and reinforcement learning.

The platform is designed around one central principle:

> **AI should not blindly predict whether a trade will win. It should learn when a trading decision has positive expectancy, when market conditions invalidate that decision, and how entry, management, and risk decisions can be improved through validated historical evidence.**

---

# Table of Contents

* [Overview](#overview)
* [Core Principles](#core-principles)
* [Platform Architecture](#platform-architecture)
* [Core Services](#core-services)
* [Market Intelligence](#market-intelligence)
* [AI Market Replay](#ai-market-replay)
* [Decision Genome](#decision-genome)
* [Graph Neural Network](#graph-neural-network)
* [Adversarial AI](#adversarial-ai)
* [Non-RL Intelligence](#non-rl-intelligence)
* [Counterfactual Simulation](#counterfactual-simulation)
* [Reinforcement Learning](#reinforcement-learning)
* [Validation Engine](#validation-engine)
* [Experiment Engine](#experiment-engine)
* [Execution Service](#execution-service)
* [Monitor Service](#monitor-service)
* [Portfolio Risk Service](#portfolio-risk-service)
* [Technology Stack](#technology-stack)
* [Project Structure](#project-structure)
* [API Overview](#api-overview)
* [Implemented vs Planned Components](#implemented-vs-planned-components)
* [Development Guidelines](#development-guidelines)
* [Getting Started](#getting-started)
* [Testing and Validation](#testing-and-validation)
* [Deployment](#deployment)
* [Roadmap](#roadmap)

---

# Overview

EasyTradify is a multi-service algorithmic trading platform combining:

* Automated trade execution
* MT5 integration
* Multi-symbol market monitoring
* Market structure analysis
* Smart Money Concepts
* Liquidity analysis
* Fair Value Gap lifecycle analysis
* VWAP analysis
* CLV and absorption analysis
* RVAM
* Technical indicators
* Microstructure confirmation
* Trade quality scoring
* Portfolio-level risk management
* Funded account compliance
* Cross-asset intelligence
* Graph Neural Networks
* Adversarial robustness testing
* Historical market replay
* Decision replay
* Counterfactual simulation
* Non-RL statistical and machine learning intelligence
* Reinforcement learning for decision optimization
* Walk-forward validation
* Out-of-sample testing
* A/B experimentation

The system is not designed as a collection of independent indicators voting equally.

Instead, the architecture progressively transforms raw market data into increasingly higher-level intelligence:

```text
Market Data
    │
    ▼
Market Structure + Features
    │
    ▼
Market Intelligence
    │
    ├── SMC
    ├── Liquidity
    ├── FVG Lifecycle
    ├── VWAP
    ├── CLV / Absorption
    ├── RVAM
    ├── Technical Features
    └── Microstructure
    │
    ▼
Cross-Asset Intelligence
    │
    └── GNN
    │
    ▼
Robustness & Stress Testing
    │
    └── Adversarial AI
    │
    ▼
Decision Genome
    │
    ▼
Decision Intelligence
    │
    ├── Non-RL Models
    ├── Market Replay
    ├── Counterfactual Analysis
    └── Experiment Engine
    │
    ▼
RL Decision Optimization
    │
    ├── Entry Timing
    ├── Position Management
    └── Sizing / Risk
    │
    ▼
Validation Engine
    │
    ├── Walk-Forward
    ├── Out-of-Sample
    ├── Regime Validation
    └── A/B Testing
    │
    ▼
Portfolio Risk Validation
    │
    ▼
Trade Execution
```

---

# Core Principles

## 1. No Single Model Controls Trading

No AI model, indicator, or signal should independently control execution.

Every model is treated as one source of evidence.

The final decision must pass through:

```text
Market Intelligence
        +
Cross-Asset Context
        +
Robustness Testing
        +
Historical Evidence
        +
Counterfactual Evaluation
        +
Portfolio Risk
        =
Validated Trading Decision
```

---

## 2. Indicators Do Not Vote Equally

EasyTradify does not rely on simplistic architectures such as:

```text
RSI = BUY
EMA = BUY
FVG = BUY
VWAP = BUY

3 / 4 indicators agree

=> BUY
```

Instead, evidence is contextual.

For example:

```text
Liquidity Sweep
        +
Market Structure Shift
        +
Valid FVG Lifecycle
        +
VWAP Alignment
        +
Cross-Asset Confirmation
        +
Microstructure Trigger
        +
Low Adversarial Fragility
        +
Positive Historical Expectancy
```

may produce a much stronger decision than several unrelated indicators simply pointing in the same direction.

---

## 3. Prediction Is Not Enough

The system does not focus only on:

> "Will price go up?"

It evaluates:

* Is this setup historically profitable?
* Under which market regime?
* Which features caused similar trades to fail?
* Would waiting improve the entry?
* Would a different stop-loss improve expectancy?
* Would a different management strategy improve the outcome?
* Is the signal fragile under small market perturbations?
* Is the current cross-asset environment contradictory?
* Does the trade improve or worsen portfolio-level risk?

---

## 4. Research and Production Are Separated

Experimental models should never automatically become production trading logic.

The lifecycle is:

```text
Research
    │
    ▼
Historical Validation
    │
    ▼
Walk-Forward Validation
    │
    ▼
Out-of-Sample Validation
    │
    ▼
Shadow / A-B Testing
    │
    ▼
Controlled Rollout
    │
    ▼
Production
```

---

# Platform Architecture

```text
                                ┌──────────────────────┐
                                │     API Gateway      │
                                │      Future Layer    │
                                └──────────┬───────────┘
                                           │
                                           ▼
                                ┌──────────────────────┐
                                │  Eureka Discovery    │
                                │      Port 8761       │
                                └──────────┬───────────┘
                                           │
          ┌────────────────────────────────┼────────────────────────────────┐
          │                                │                                │
          ▼                                ▼                                ▼

┌───────────────────┐          ┌───────────────────┐          ┌───────────────────┐
│ Execution Service │          │  Monitor Service  │          │ Portfolio Service │
│      :8081        │          │      :8082        │          │      :8083        │
└─────────┬─────────┘          └─────────┬─────────┘          └─────────┬─────────┘
          │                              │                              │
          │                              │                              │
          └───────────────┬──────────────┴───────────────┬──────────────┘
                          │                              │
                          ▼                              ▼

                  ┌──────────────────────────────────────────┐
                  │                AI SERVICE                │
                  │                  :8084                   │
                  ├──────────────────────────────────────────┤
                  │                                          │
                  │  Market Intelligence                     │
                  │  ├── Market Structure                   │
                  │  ├── Liquidity                          │
                  │  ├── FVG Lifecycle                      │
                  │  ├── VWAP                               │
                  │  ├── CLV / Absorption                   │
                  │  ├── RVAM                               │
                  │  ├── Technical Features                 │
                  │  └── Microstructure                     │
                  │                                          │
                  │  Cross-Asset Intelligence               │
                  │  └── Graph Neural Network               │
                  │                                          │
                  │  Robustness Intelligence                │
                  │  └── Adversarial AI                     │
                  │                                          │
                  │  AI_MarketReplay                        │
                  │  ├── Decision Genome                    │
                  │  ├── Replay Engine                      │
                  │  ├── Counterfactual Simulator           │
                  │  └── Experiment Engine                  │
                  │                                          │
                  │  Non-RL Intelligence                    │
                  │                                          │
                  │  Reinforcement Learning                 │
                  │  ├── Entry Timing RL                    │
                  │  ├── Management RL                      │
                  │  └── Sizing / Risk RL                   │
                  │                                          │
                  │  Validation Engine                      │
                  └────────────────────┬─────────────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼

              PostgreSQL       MongoDB + Firebase    Python Engines
           Service Databases   trades  /  config         / MT5
```

Storage split, as built: **MongoDB** holds the `trades` collection (the trade
lifecycle and the forward walk — see *Trade storage* below). **Firebase** keeps
`portfolio_config` and `ai_models` only; it no longer stores trades.
**PostgreSQL** backs the Java services.

---

# Core Services

## 1. Discovery Server

**Port:** `8761`

Eureka-based service discovery.

Responsibilities:

* Service registration
* Service discovery
* Internal service lookup
* Health visibility

---

# 2. Execution Service

**Port:** `8081`

The Execution Service is responsible for converting validated decisions into broker actions.

It should not independently generate trading intelligence.

Responsibilities include:

* Market trade execution
* Position retrieval
* Position closure
* Partial closure
* Stop-loss modification
* Take-profit modification
* Trailing stop management
* Account information
* Symbol information
* Market condition retrieval
* Trade history
* Lot calculation
* MT5 communication
* Webhooks
* Copy trading

Architecture:

```text
Validated Decision
        │
        ▼
Execution Service
        │
        ▼
Risk Validation
        │
        ▼
Broker / MT5
        │
        ▼
Execution Result
        │
        ├── Portfolio Update
        ├── Decision Genome
        └── Replay Dataset
```

---

# 3. Monitor Service

**Port:** `8082`

Responsible for market scanning and symbol discovery.

Responsibilities:

* Start and stop monitoring
* Symbol discovery
* Market filtering
* Candidate ranking
* Market condition collection
* Monitoring logs
* Closed trade tracking
* Signal candidate generation

The Monitor Service may rank opportunities, but ranking is not equivalent to final trade approval.

```text
All Symbols
     │
     ▼
Market Availability Filter
     │
     ▼
Spread / Volatility Filter
     │
     ▼
Market Intelligence
     │
     ▼
Candidate Ranking
     │
     ▼
AI Decision Pipeline
```

---

# 4. Portfolio Risk Service

**Port:** `8083`

Responsible for portfolio-level protection.

Responsibilities:

* Portfolio status
* P&L tracking
* Drawdown tracking
* Risk limits
* Maximum risk per trade
* Trading permission
* Portfolio statistics
* Funded account compliance
* Risk configuration
* Exposure management

The Portfolio Service acts as a hard constraint.

Even if the AI strongly favors a trade:

```text
AI Decision = ENTER
```

the portfolio layer can return:

```text
PORTFOLIO DECISION = REJECT
```

Examples:

* Maximum drawdown reached
* Daily loss limit reached
* Maximum exposure exceeded
* Correlated positions too concentrated
* Funded-account rule violation
* Maximum simultaneous trades reached

---

# 5. Common Library

Shared infrastructure for Java services.

Suggested responsibilities:

```text
common/
├── exception/
├── handlers/
├── dto/
├── utils/
├── validation/
├── constants/
├── events/
└── observability/
```

Includes:

* Business exceptions
* Global exception handling
* Shared DTOs
* Validation utilities
* Pagination
* Error codes
* Event contracts
* Shared constants

---

# Market Intelligence

Market Intelligence transforms raw market data into structured features.

It includes the useful existing strategy and market-analysis components, but they are not treated as isolated trading systems.

---

## Market Structure

The system should identify:

* Swing highs
* Swing lows
* Higher highs
* Higher lows
* Lower highs
* Lower lows
* Break of Structure
* Change of Character
* Trend transitions
* Structural invalidation

---

## Liquidity

Liquidity analysis should identify:

* Equal highs
* Equal lows
* Liquidity pools
* Liquidity sweeps
* Stop-run behavior
* Sweep confirmation
* Sweep failure

The previous multiple liquidity implementations should be unified into one lifecycle-oriented engine.

---

## Fair Value Gap Lifecycle

FVG analysis should not stop at detecting a gap.

Each FVG should have a lifecycle:

```text
CREATED
   │
ACTIVE
   │
PARTIALLY_FILLED
   │
FULLY_FILLED
   │
INVALIDATED
   │
RECLAIMED
```

Relevant features:

* Gap size
* Age
* Fill percentage
* Direction
* Structural context
* VWAP relationship
* Liquidity relationship
* Historical behavior

---

## VWAP Engine

VWAP should provide contextual information including:

* Price relative to VWAP
* VWAP slope
* Distance from VWAP
* Reversion probability features
* Trend confirmation
* Session context

VWAP is evidence, not an automatic entry signal.

---

## CLV and Absorption

Close Location Value and absorption features help evaluate:

* Candle acceptance
* Rejection
* Buying pressure
* Selling pressure
* Potential exhaustion
* Absorption zones

---

## RVAM

RVAM is retained as a market activity and volume-related contextual engine.

Its output should be integrated as features rather than treated as an isolated trading strategy.

---

## Technical Features

Existing technical analysis remains useful when contextualized:

* RSI
* RSI divergence
* EMA 20
* EMA 200
* Stochastic
* Bollinger Bands
* ATR
* Volatility features

These features should be part of the Decision Genome rather than independent vote generators.

---

## Microstructure

Microstructure is the final confirmation layer.

It should answer:

```text
The larger context may favor the trade.

But is NOW the correct moment to enter?
```

Possible outcomes:

```text
WAIT
ENTER
CANCEL
```

Microstructure should not replace higher-level market context.

---

# Trade Quality Score

The Trade Quality Score aggregates structured evidence.

It should not be a simple average.

Example conceptual structure:

```text
Trade Quality
    =
Market Context
+
Structure Quality
+
Liquidity Context
+
FVG Quality
+
VWAP Context
+
Cross-Asset Context
+
Microstructure Quality
+
Historical Expectancy
-
Adversarial Fragility
-
Portfolio Risk
```

The score should support:

```text
REJECT
WATCH
WAIT
TRADE_CANDIDATE
HIGH_QUALITY_CANDIDATE
```

The final execution decision still requires risk validation.

---

# Graph Neural Network

GNN is a mandatory part of the advanced architecture.

Traditional models generally analyze one symbol as a mostly independent sequence.

Markets are interconnected.

Example:

```text
EURUSD
   │
   ├── DXY
   ├── GBPUSD
   ├── USDJPY
   ├── Gold
   └── Equity Indices
```

A Graph Neural Network can model:

* Cross-asset relationships
* Dynamic correlations
* Lead-lag relationships
* Divergences
* Cross-market confirmation
* Cross-market conflict
* Regime-dependent relationships
* Graph anomalies

The GNN should produce structured outputs such as:

```json
{
  "symbol": "EURUSD",
  "graph_context": {},
  "correlation_regime": "STABLE",
  "cross_asset_confirmation": 0.72,
  "cross_asset_conflict": 0.18,
  "lead_lag_signals": [],
  "graph_anomalies": []
}
```

The GNN should not directly place trades.

Its role is to improve contextual awareness.

---

# Adversarial AI

Adversarial AI is also mandatory.

Trading models can become dangerously dependent on fragile features.

For example:

```text
Small change in spread
        ↓
Model decision changes completely
```

or:

```text
Slightly different volatility
        ↓
High-confidence prediction becomes low-confidence
```

Adversarial testing evaluates model robustness.

The system may generate controlled perturbations involving:

* Noise
* Volatility shifts
* Spread changes
* Feature perturbations
* Missing data
* Delayed data
* Correlation breakdown
* Regime transitions

Example:

```text
Original Decision

ENTER LONG
Confidence: 0.82


After Controlled Perturbation

CANCEL
Confidence: 0.31
```

This indicates fragility.

The Adversarial Engine should produce metrics such as:

```text
ROBUST
MODERATELY_FRAGILE
FRAGILE
UNSTABLE
```

Adversarial fragility becomes an input into decision quality.

---

# AI_MarketReplay

AI_MarketReplay is the historical intelligence layer.

It is designed to answer:

> What actually happened after the system made a decision?

Instead of storing only:

```text
Trade
Entry
Exit
Profit
Loss
```

the system stores the complete decision context.

---

# Decision Genome

The Decision Genome is the structured representation of a trading decision.

Example:

```json
{
  "decision_id": "uuid",
  "timestamp": "...",
  "symbol": "EURUSD",
  "timeframe": "M5",

  "market_regime": {},

  "market_structure": {},

  "liquidity": {},

  "fvg": {},

  "vwap": {},

  "clv_absorption": {},

  "rvam": {},

  "technical_features": {},

  "microstructure": {},

  "gnn_context": {},

  "adversarial_robustness": {},

  "non_rl_prediction": {},

  "decision": {},

  "risk_context": {},

  "execution_context": {}
}
```

The Decision Genome creates a reproducible representation of why the system acted.

---

# Replay Engine

The Replay Engine reconstructs historical decisions.

```text
Historical Market State
        │
        ▼
Rebuild Features
        │
        ▼
Rebuild Decision Genome
        │
        ▼
Run Decision Logic
        │
        ▼
Compare
        │
        ├── Original Decision
        └── Alternative Decision
```

It can identify patterns such as:

```text
The strategy performs well during trending regimes
but consistently fails during volatility compression.
```

or:

```text
Entries are correct,
but entering two candles later historically improves expectancy.
```

---

# Counterfactual Simulator

The Counterfactual Simulator asks:

> What would have happened if we made a different decision?

Examples:

```text
Original:
ENTER NOW

Counterfactual:
WAIT 1 CANDLE
WAIT 2 CANDLES
CANCEL
```

For management:

```text
Original:
HOLD

Counterfactual:
EXIT
MOVE_STOP
PARTIAL_CLOSE
PROTECT
```

For risk:

```text
Original:
Risk = X

Counterfactual:
Reject
Reduced Size
Normal Size
```

Counterfactual simulation allows the platform to analyze decision alternatives without confusing hypothetical outcomes with real production results.

---

# Non-RL Intelligence

Before reinforcement learning, EasyTradify should use strong non-RL models.

These models can provide:

* Probability estimation
* Expected return estimation
* Failure classification
* Regime classification
* Trade quality prediction
* Entry timing quality
* Management outcome prediction
* Feature importance
* Anomaly detection

Possible model families include:

```text
Gradient Boosting
Random Forest
XGBoost / LightGBM style models
Temporal Models
Sequence Models
Ensemble Models
Anomaly Detection
Regime Classification
Calibration Models
```

The exact implementation should be selected through validation rather than hype.

The purpose is:

```text
Current Market State
        │
        ▼
Feature Extraction
        │
        ▼
Non-RL Models
        │
        ├── Expected Value
        ├── Failure Risk
        ├── Regime
        ├── Trade Quality
        └── Uncertainty
```

These outputs become inputs to the decision architecture.

---

# Reinforcement Learning

RL is used for sequential decision optimization.

It is not intended to replace all trading intelligence.

The RL architecture contains three decision domains.

---

## 1. Entry Timing RL

Actions:

```text
WAIT
ENTER
CANCEL
```

The agent evaluates whether:

* The trade should happen now
* Waiting improves the entry
* Market conditions invalidate the opportunity

---

## 2. Management RL

Actions:

```text
HOLD
EXIT
PROTECT
```

Possible future extensions:

```text
PARTIAL_CLOSE
MOVE_STOP
TRAIL
REDUCE
```

The objective is not simply maximizing one trade's profit.

It should optimize validated risk-adjusted reward.

---

## 3. Sizing / Risk RL

Actions:

```text
REJECT
ACCEPT
REDUCE_SIZE
NORMAL_SIZE
```

The agent must operate inside hard portfolio constraints.

RL cannot override:

* Maximum loss
* Maximum drawdown
* Exposure limits
* Funded-account rules
* Maximum simultaneous positions

---

# RL Training Principle

RL must not be trained only on naive backtesting.

The training environment should use:

```text
Historical Replay
        +
Decision Genome
        +
Counterfactual Evaluation
        +
Transaction Costs
        +
Spread
        +
Slippage Assumptions
        +
Portfolio Constraints
```

The goal is to prevent unrealistic learning.

---

# Validation Engine

The Validation Engine is mandatory before promoting models.

It should include:

## Walk-Forward Validation

```text
Train
│
▼
Validate
│
▼
Move Forward
│
▼
Retrain
│
▼
Validate Again
```

---

## Out-of-Sample Testing

Models must be evaluated on data not used for development.

---

## Regime Validation

Performance should be separated across conditions such as:

* Trending
* Ranging
* High volatility
* Low volatility
* Expansion
* Compression
* Correlation stability
* Correlation breakdown

---

## Robustness Validation

The Adversarial Engine should test whether model decisions remain stable under controlled perturbations.

---

## Portfolio-Level Validation

A model with good individual trade performance can still perform badly when correlated trades accumulate.

Validation should therefore measure:

* Drawdown
* Exposure
* Correlation concentration
* Risk-adjusted return
* Maximum adverse conditions

---

# Experiment Engine

The existing A/B testing concept is retained and expanded.

Experiments may compare:

```text
Model A
vs
Model B
```

or:

```text
Current Entry Policy
vs
New Entry Policy
```

or:

```text
RL Management
vs
Rule-Based Management
```

Experiments should support:

* Experiment IDs
* Dataset versioning
* Model versioning
* Configuration snapshots
* Performance metrics
* Statistical comparison
* Rollout control

---

# Execution Service

The existing Execution Service functionality is retained.

## Trade Execution

```text
POST /api/v1/execution/trade
POST /api/v1/execution/analyse
POST /api/v1/execution/probability
```

Future architecture should progressively route analysis through the unified AI decision pipeline.

---

## Position Management

```text
POST /api/v1/execution/position/close

PUT /api/v1/execution/position/partial-close

POST /api/v1/execution/positions/close/all

GET /api/v1/execution/positions

GET /api/v1/execution/positions/open

GET /api/v1/execution/position/{ticket}
```

---

## Stop Loss and Take Profit

```text
PUT /api/v1/execution/position/stop-loss

PUT /api/v1/execution/position/take-profit
```

---

## Trailing Stop

```text
PUT /api/v1/execution/position/trailing/enable

PUT /api/v1/execution/position/trailing/disable

PUT /api/v1/execution/position/trailing/update

GET /api/v1/execution/trailing/status

GET /api/v1/execution/trailing/stats
```

---

## Account and Symbol

```text
GET /api/v1/execution/account

GET /api/v1/execution/symbol/{symbol}

GET /api/v1/execution/symbols
```

---

## Market Conditions

```text
GET /api/v1/execution/market/status/{symbol}

GET /api/v1/execution/market/volatility/{symbol}

GET /api/v1/execution/market/spread/{symbol}

GET /api/v1/execution/market/conditions/{symbol}
```

---

## MT5

```text
POST /api/v1/execution/mt5/connect

POST /api/v1/execution/mt5/disconnect
```

---

## History and Lot Calculation

```text
GET /api/v1/execution/trades/history

POST /api/v1/execution/calculate-lot
```

---

## Copy Trading and Webhooks

```text
POST /api/v1/copy-trade/execute

POST /api/v1/copy-trade/webhook/trade

POST /api/v1/copy-trade/webhook/trailing

POST /api/v1/copy-trade/webhook/test

GET /api/v1/copy-trade/webhook/health

GET /api/v1/copy-trade/webhook/debug

GET /api/v1/copy-trade/status
```

---

# Monitor Service

Existing monitor functionality is retained.

```text
POST /api/v1/monitor/start

POST /api/v1/monitor/stop

POST /api/v1/monitor/refresh

GET /api/v1/monitor/status

GET /api/v1/monitor/top-symbols

GET /api/v1/monitor/filtered-symbols

GET /api/v1/monitor/logs

GET /api/v1/monitor/executions

GET /api/v1/monitor/closed-trades
```

The monitor discovers and ranks opportunities.

Final trade approval belongs to the unified decision pipeline.

---

# Portfolio Risk Service

Existing portfolio functionality is retained.

```text
GET /api/v1/portfolio/status

GET /api/v1/portfolio/summary

GET /api/v1/portfolio/config

PUT /api/v1/portfolio/config

GET /api/v1/portfolio/config/{field}

PUT /api/v1/portfolio/config/{field}

POST /api/v1/portfolio/check-trading-allowed

GET /api/v1/portfolio/max-risk-per-trade

GET /api/v1/portfolio/stats

GET /api/v1/portfolio/drawdown

GET /api/v1/portfolio/funded-compliance

POST /api/v1/portfolio/refresh
```

---

# AI Service

**Port:** `8084`

**Current implementation:** the Java `ai` module is a thin REST proxy only — `AIController`/`AIServiceImpl` expose GNN and Adversarial endpoints and forward them via `PythonAIServiceClient` to the Python engine. There is no Java-side Decision Genome, Replay, Counterfactual, Non-RL, RL, Validation, or Experiment logic yet.

```text
AI SERVICE (Java, today)
│
├── GNN            → proxies to Python ai.ai_gnn / ai_gnn_lightweight
│
└── Adversarial AI → proxies to Python ai.ai_adversarial
```

The corresponding intelligence exists in Python (`easytradifyPythonBot/ai/`), but with a real live-wiring gap between what's built and what a running trade decision actually uses:

```text
ai_gnn.py / ai_gnn_lightweight.py   — Graph Neural Network cross-asset correlation.
                                       LIVE, and only recently confirmed working: the ai/
                                       package's __init__.py used to hard-import ~15 sibling
                                       modules that don't exist on disk, plus an empty
                                       ai_config.py — so `import ai` raised ImportError
                                       unconditionally. core/asset_analysis_gnn.py's
                                       `from ai.ai_gnn import ...` is wrapped in
                                       try/except ImportError, so this failure was silent:
                                       GNN_AVAILABLE was permanently False and every GNN
                                       contribution to the probability chain was a no-op,
                                       with no error ever surfacing. Fixed by populating
                                       ai_config.py (AIConfig/default_config) and trimming
                                       __init__.py to only import modules that actually
                                       exist — GNN_AVAILABLE is now True.

ai_adversarial.py                   — adversarial robustness / perturbation testing engine.
                                       Real and coherent (~3000 lines, ~23 attack categories),
                                       but reachable only through ai_controller.py, which
                                       nothing in the codebase calls (see below). Currently
                                       dead code with no live execution path.

ai_reinforcement.py                 — was rewritten into standalone offline RL research
                                       scaffolding (RLAgent/RLConfig, Rainbow-DQN-style).
                                       No live trade decision touches it; callable only by
                                       hand (train_from_replay(), smoke_test()).

non_rl_intelligence.py              — a well-built, leakage-conscious sklearn pipeline
                                       (outcome/MFE-MAE prediction, failure classification,
                                       regime modeling, calibration). Not imported by
                                       anything else in the repo.

ai_controller.py                    — a standalone Flask service intended for port 5002
                                       exposing GNN + adversarial endpoints. Orphaned:
                                       nothing in the repo makes an HTTP call to that port,
                                       and it can't even start today — it imports
                                       ai_ab_testing.py and ai_diffusion.py, neither of
                                       which exists in this directory.

ai_asset_analysis.py                — still an empty file (0 bytes); no longer imported
                                       unconditionally (see the GNN fix above), so it no
                                       longer breaks the package, but it implements nothing.

ai_asset_diagnostic.py              — offline/manual diagnostic tool, not reachable from
                                       live code, and has its own bug independent of the
                                       above (calls a `self._get_score()` method that isn't
                                       defined — only `_get_component_score` exists).

root_cause_analyzers.py / root_cause_models.py / root_cause_trackers.py
                                     — a clean, deliberate "evidence-only" redesign of
                                       self-correction (typed dataclasses, no autonomous
                                       weight mutation) — but never instantiated anywhere.
                                       The Firebase methods it would feed
                                       (save_root_cause / save_correction / save_evolution /
                                       save_component_performance / save_rule_evolution in
                                       core/firebase/firebase_service.py) have zero call
                                       sites in the repo, so the ai_root_causes /
                                       ai_corrections / ai_evolutions / ai_rule_evolution
                                       Firebase collections are currently never written.

price_evolution_maps.py / _encoder.py / _decoder.py / _bridge.py
                                     — the encoder is live: monitor/firebase_helpers.py calls
                                       it per timeframe when writing each
                                       trades/{id}/price_evolution point.
                                       PriceEvolutionBridge.to_canonical() is the decode
                                       boundary on the read side — it turns a stored trade
                                       document back into canonical (full field name) form,
                                       handling both storage shapes (see "price_evolution has
                                       two formats" under Firebase). ai_adversarial.py calls
                                       it before attacking a trade. RL and non-RL do not,
                                       because neither has a Firebase-trade entry point yet:
                                       ai_reinforcement.py consumes snapshot sequences and
                                       non_rl_intelligence.py consumes DecisionRecord objects,
                                       and the converter that would build those from a stored
                                       trade does not exist. Any such converter must go
                                       through to_canonical().
```

The target architecture below (Decision Genome, AI_MarketReplay, Counterfactual, Validation, Experiments) describes where this is heading — most of it exists today as standalone Python modules under `easytradifyPythonBot/core/` (see [Project Structure](#project-structure)) rather than as Java-exposed AI Service capabilities:

```text
AI SERVICE (target)
│
├── Market Intelligence
│
├── GNN
│
├── Adversarial AI
│
├── Decision Genome
│
├── AI_MarketReplay
│
├── Counterfactual Simulation
│
├── Non-RL Models
│
├── Reinforcement Learning
│
├── Validation Engine
│
└── Experiment Engine
```

---

# AI API Direction

The old endpoints remain useful as a starting point, but future development should organize AI endpoints around engines rather than dozens of isolated "insight" endpoints.

Suggested groups:

```text
/api/v1/ai/market-intelligence/

/api/v1/ai/gnn/

/api/v1/ai/adversarial/

/api/v1/ai/replay/

/api/v1/ai/decision-genome/

/api/v1/ai/counterfactual/

/api/v1/ai/non-rl/

/api/v1/ai/rl/

/api/v1/ai/validation/

/api/v1/ai/experiments/
```

---

# Data Architecture

## PostgreSQL

PostgreSQL remains the primary structured persistence layer.

Potential datasets include:

```text
trades
positions
execution_events
market_snapshots
decision_genomes
replay_sessions
counterfactual_results
model_versions
experiments
validation_runs
portfolio_snapshots
```

Each microservice may maintain its own database or schema according to the final deployment architecture.

---

## Trade storage — MongoDB

**Current implementation (2026-09-10): trades are stored in MongoDB, not Firestore.**
`TRADES_TO_FIRESTORE = False` in `easytradifyPythonBot/monitor/firebase_helpers.py`.
Firestore remains for `portfolio_config` and `ai_models`; it holds **no trades**,
by design.

| | |
|---|---|
| Database | `easytradify`, collection `trades`, local `mongod` on `27017` |
| Owner | `core/mongo/trades_service.py` — the only module that touches the collection |
| Write path | `monitor/trade_sink.py` — `record_open`, `record_price_point`, `record_close` |
| Read path | `ai/trade_repository.py` — every model reads through this, never raw |
| Health | `trade_sink.get_status()` → `degraded`, `mongo_healthy`, per-op failure counts |

**Why the move:** a Firestore document is capped at 1 MiB, and a trade carrying a
full minute-by-minute forward walk is several megabytes — `price_evolution`
stopped accepting points after two. MongoDB's 16 MB limit holds a whole trade as
one document with `price_evolution` as a plain array, which is the shape every
model already expects.

**The trade-off:** there is no longer a fallback store. If Mongo is down when a
trade opens, that trade has no record anywhere. `trade_sink` counts failures and
reports `degraded` so the gap is visible rather than silent — check it after any
database interruption.

One document per trade at `trade_id = "trade_{ticket}"`, written at open, on each
price update (~60s, `$push` onto `price_evolution`), on trailing-stop changes, and
at close. `upsert_trade()` is keyed on `trade_id` and idempotent: a network
timeout followed by a retry converges on one record, never two contradictory ones.
Indexes: unique on `trade_id`, plus `ticket`, `(symbol, opened_at)`,
`(status, closed_at)`, `opened_at`, and a partial index on `deleted_at`.

**Reading:** always go through `ai/trade_repository.load_trades()`. It applies
`canonicalise()`, which flattens the `analysis_at_open` envelope and decodes every
price point. Passing raw Mongo documents to a model yields zero usable rows —
`strategy_families.build_rows()` returns 0 of 2 on raw documents and 2 of 2
through the repository.

**Historical note:** the previous Firestore-based description in this section was
accurate when written. The trade schema below still applies; the store changed,
not the shape.

```text
easytradify.trades   (_id is Mongo's; trade_id = "trade_{ticket}" is the key)
├── trade_id, ticket, symbol, direction ("BUY"/"SELL"), status ("OPEN"/"CLOSED")
├── opened_at, created_at, updated_at, closed_at, deleted_at
├── entry:            price, volume, stop_loss, take_profit(_2/_3)
├── analysis_at_open:  full raw signal analysis at entry (see analyze_institutional_signal())
│                      also carries the measurement channels: microstructure_at_entry,
│                      strategy_family_scores, component_reads  (all contribution: 0.0)
├── price_evolution:  [ { price, analysis, risk_state, microstructure,
│                         profit_usd/percent, distance_from_entry_pips, ... } ]
├── metrics:          max_profit_reached, max_drawdown, price_updates_count
├── trailing_stop:    activated, action, new_sl, profit_pips
├── close_data:       close_reason, close_price, profit_usd/percent, is_winning, duration_seconds
└── analysis_at_close: result, profit_usd, full raw analysis at close
```

### The shape is a contract — `entry`, `direction` and `opened_at` are load-bearing

`ai/mt5_history.to_trade()` is the canonical shape. Every reader
(`trade_repository._r_multiple`, `edge_discovery`, `strategy_families`,
`component_audit_360`) does:

```python
entry = trade.get("entry") or {}
ep, sl = entry.get("price"), entry.get("stop_loss")
if not all(isinstance(v, (int, float)) for v in (ep, sl, cp)):
    return None          # trade silently skipped — no error, no warning
```

The live writer emitted only flat `price` / `stop_loss` / `order_type` and no
`entry` sub-document, so every trade it recorded returned `R = None` and was
dropped by every model. Measured: R computable on 220/250 history trades and
**0/2** live ones. `opened_at` matters just as much — it is the default sort in
`trades_service`, carries its own index, and every walk-forward split orders on
it — and nothing was writing it either. Both are fixed; both are pinned by tests
in `tests/test_stored_trade_shape.py`.

This is the most expensive kind of missing data: collection *looks* like it is
working — rows accumulate, counts rise — and every model quietly ignores them.

### Direction and profit come from the broker, never from inference

`core/broker_facts.py` is the single source for both, shared by the monitor and
the copy-trade controller so a fix cannot land in one path and miss the other:

* `closing_deal(ticket)` — `history_deals_get(position=...)`, authoritative on
  exit price, slippage, swap, commission and partial fills. Costs are summed
  over **both** legs; price and volume are volume-weighted over the closing
  deals. Retries briefly, because the deal is not always visible the instant
  the position leaves the open list.
* `contract_size(symbol)` — the broker's `trade_contract_size`.
* `profit_from_prices(...)` — last resort, requires a known direction *and*
  contract size.

All three return `None` rather than guess, and a close that cannot be
reconstructed is left **unsaved**. A visible gap beats a fabricated record,
because nothing downstream can tell a fabricated one from a real one.

This replaced two defect families that silently corrupted the label every model
trains on:

| Defect | What it produced |
|---|---|
| `order_type = "BUY"; if price_close < price_open: order_type = "SELL"` — direction inferred from the **outcome** | A losing BUY stored as a SELL, and because direction always agreed with the price move, **every closed trade read back as a winner**. Seven copies existed across three files |
| `profit = move * volume * 100000`, with **both branches positive** | 100000 is the FX contract size — XAUUSD is 100 oz, UKOIL is not FX. A +$4.77 gold trade stored as −$3,960.00; a UKOIL trade recorded $8,500.00 on a fraction of a lot. Five copies |
| Close fell back to `price_close = sl` when the history lookup missed | Assumed every trade closed at its stop — false for any manual or webhook close |

Applied to the 250 real closed positions in the MT5 account, the old direction
inference would have been wrong on **57.2%** of them and would have
manufactured a **98.8%** win rate. The 215-trade research set was never
affected: it comes from `ai/mt5_history.py`, which reads direction from the
opening deal's type and profit from the broker's deals, and never touches the
live save path.

### Operational notes

* `TradesService._lock` must stay an `RLock`. `_ensure_indexes()` holds it and
  then reads `self.client`, which acquires the same lock — with a plain `Lock`
  that is a self-deadlock on the first `collection` access in a process, which
  is exactly what `record_open` does. It hung every trade open while
  `is_healthy()` still reported `mongo_healthy: True`, because that path reaches
  `client` without holding the lock.
* Run **one** `hybrid_monitor.py`. Flask's reloader used to fork a second
  trading process (`use_reloader=False` now prevents it), and two instances
  produce duplicate fills on the same signal — one observation, not two.
* `logs/hybrid_monitor.log` tees stdout/stderr with a 20 MB × 3 rotation, plus
  `sys.excepthook` and `threading.excepthook`, so a crash leaves a trace. The
  monitor once died with no log file anywhere on disk.

### price_evolution has two formats — always branch on `_encoded`

`analysis_at_open` and `analysis_at_close` are stored raw. The per-timeframe analysis inside each `price_evolution` point is **not**, and it exists in two structurally different shapes:

```text
_encoded: true    point["analysis"] = { "m1": <short-key blob>, "m5": ..., "h1": ... }
                  full analysis, compressed by PriceEvolutionEncoder

_encoded: false   point["m1_analysis_raw"] / ["m5_analysis_raw"] / ["h1_analysis_raw"]
                  at the point's TOP level, with no "analysis" key at all —
                  and m5/h1 hold only an _audit_slice(), not the full analysis
```

Which shape a row has depends on whether `ai.price_evolution_encoder` was importable when the row was written: `monitor/firebase_helpers.py` falls back to the raw branch whenever `_get_encoder()` returns `None`. The `ai` package was unimportable for a period (an empty `ai_config.py` broke `ai/__init__.py` — see AI Service), so **rows written before that fix are raw and rows written after it are encoded**. The collection contains both, and the older raw rows carry genuinely less m5/h1 analysis, which cannot be recovered retroactively.

Consumers must therefore never assume a format. Read stored trades through `PriceEvolutionBridge.to_canonical()`, which branches on `_encoded` per row and normalizes both shapes into one canonical `analysis: {m1, m5, h1}` form. Reasoning directly off the stored document means attacking or training on short keys (`c`, `tb`, `sd`) that mean nothing to any downstream model — the same rule the AI_MarketReplay specification states as "must consume the decoded canonical representation, not reason directly from compressed Firebase data."

`core/firebase/firebase_config.py` also already defines ~70 collection-name constants for the AI/self-correction layer (`ai_training`, `ai_models`, `ai_predictions`, `ai_root_causes`, `ai_corrections`, `ai_evolutions`, `ai_rule_evolution`, plus scoring/pattern/drift/risk/causal/cluster families) — some of these are actively written by `easytradifyPythonBot/ai/root_cause_*.py`, others are declared but not yet used everywhere. Firebase is deliberately scoped to live trade state and select AI artifacts, not bulk historical research data (that belongs in the replay/decision-genome files under `core/`, or PostgreSQL for the Java services).

---

# Python Engines

**Current implementation:** `easytradifyPythonBot/` is a real, large Python package (not a placeholder) that does the actual signal analysis, execution, and trade lifecycle work — the Java services orchestrate around it via REST clients rather than reimplementing this logic.

```text
easytradifyPythonBot/
├── core/          — ~75 modules: the market-intelligence and decision engine (see below)
│   ├── mongo/     — trades_service.py: the ONLY module that touches the trades collection
│   └── broker_facts.py — closing_deal() / contract_size() / profit_from_prices():
│                    what the BROKER says a trade did. Shared by both close paths so a
│                    fix cannot land in one and miss the other
├── ai/            — GNN, adversarial testing, RL scaffolding, non-RL models,
│                    root-cause/self-correction, price-evolution compression,
│                    trade_repository.py (the sole read path into stored trades),
│                    edge_discovery.py, strategy_families.py, mt5_history.py
├── api/           — HTTP/webhook layer (execute_copy_trade.py, execution_controller.py,
│                    portfolio_risk_controller.py, hybrid_monitor.py, trades_controller.py)
│                    + firebase-credentials.json
├── monitor/       — position monitoring loop, firebase_helpers.py (trade open/update/close
│                    payload builders), trade_sink.py (the fail-soft Mongo mirror)
├── tests/         — 921 tests, all passing
└── logs/          — hybrid_monitor.log, 20 MB x 3 rotation (stdout/stderr tee'd)
```

`core/` is the central analysis engine. Its entry point, `analyze_institutional_signal()` (in `asset_analysis.py`), pulls MT5 market data, runs it through market-structure/SMC/Wyckoff/indicator/GNN components (split across `asset_analysis_indicators.py`, `asset_analysis_smc.py`, `asset_analysis_gnn.py`), combines a base directional probability with a long, individually-bounded chain of adjustments (trend cascade, exhaustion, DXY confluence, nested-zone confluence, family voting, RVAM, pattern recognition, GNN, SMC, FVG/IFVG, order flow, gap/slippage — each logged so nothing is silently absorbed at the probability floor/ceiling), then runs the result through several defensive layers before a trade is approved:

```text
Probability Chain → Entry Gate → Vetoes → Position Sizing
    → Decision Snapshot → Coherence Check (observer-only)
    → Symbolic Gate (hard arithmetic invariants, can only flip YES→NO)
    → Conviction Filter (does the system agree with itself?)
    → Final Decision
```

Supporting subsystems already implemented in `core/` include: a deterministic, lookahead-safe replay engine (`replay.py`, `mt5_shim.py`, `engine_replay.py`, `market_data.py`) used for calibration and backtesting; a decision-genome-style trace/snapshot system (`decision_snapshot.py`, `decision_trace.py`, `decision_features.py`); statistical/causal diagnostics (`causal_invariance.py`, `entropy_gate.py`, `extreme_value.py`, `kalman_state.py`) currently used for measurement rather than live gating; account/portfolio risk management (`portfolio_risk_service.py`); and forensic replay analysis (`replay_forensics.py`, `phase_report.py`, `run_preregistered.py`) built around expectancy-in-R and calibration rather than raw win rate.

Spring Boot remains responsible for service orchestration, APIs, persistence boundaries, and platform integration; it does not reimplement this analysis logic.

---

# Technology Stack

## Core

| Technology      | Purpose                                     |
| --------------- | ------------------------------------------- |
| Java 17+        | Backend platform                            |
| Spring Boot 3.x | Backend services                            |
| Spring Cloud    | Distributed service infrastructure          |
| Spring Data JPA | Persistence                                 |
| Spring WebFlux  | Reactive communication                      |
| PostgreSQL      | Structured persistence                      |
| Eureka          | Service discovery                           |
| Python          | AI and market research engines              |
| MT5             | Broker execution integration                |
| Firebase        | Real-time synchronization where appropriate |

---

## Testing

| Technology           | Purpose                    |
| -------------------- | -------------------------- |
| JUnit 5              | Unit testing               |
| Mockito              | Mocking                    |
| Testcontainers       | Integration testing        |
| Python testing tools | AI and research validation |

---

## Documentation

| Technology | Purpose                     |
| ---------- | --------------------------- |
| OpenAPI    | API specification           |
| SpringDoc  | API documentation           |
| Swagger UI | Interactive API exploration |

---

# Project Structure

This describes the actual repository layout at the workspace root (`tradify/`), which is three sibling projects, not one Maven tree:

```text
tradify/
│
├── easytradify/                     — Java / Spring Boot microservices (Maven multi-module)
│   ├── discovery-server/            — Eureka service discovery, port 8761
│   ├── execution-service/           — trade execution, port 8081
│   ├── monitor/                     — market monitoring, port 8082
│   ├── porfolio_risk_management/    — portfolio risk, port 8083
│   ├── ai/                          — thin REST proxy to Python AI engine, port 8084
│   │   └── (GNN + Adversarial endpoints only today — see AI Service)
│   ├── common/                      — shared DTOs/exceptions/utils
│   └── pom.xml
│
├── easytradifyPythonBot/            — Python analysis/execution engine (see Python Engines)
│   ├── core/                        — ~75 modules: market intelligence + decision engine
│   │   ├── mongo/                   — trades_service.py: sole owner of easytradify.trades
│   │   ├── broker_facts.py          — what the broker says a trade did (exit, P/L, contract size)
│   │   └── firebase/                — portfolio_config + ai_models only (firebase_service.py,
│   │                                  firebase_config.py). No longer stores trades
│   ├── ai/                          — GNN, adversarial, RL, non-RL, root-cause self-correction,
│   │                                  trade_repository.py = sole read path into stored trades
│   ├── api/                         — HTTP/webhook layer + firebase-credentials.json
│   ├── monitor/                     — position monitoring loop, firebase_helpers.py,
│   │                                  trade_sink.py (fail-soft Mongo mirror)
│   ├── tests/                       — 921 tests
│   └── logs/                        — hybrid_monitor.log (20 MB x 3 rotation)
│
└── front/
    └── easy-tradify-ui/             — Angular frontend, consumes the Java service APIs
```

The Java services communicate with the Python engine over REST (e.g. `PythonAIServiceClient`, `PythonCopyTradeClient`), rather than the Python code living inside the Java module tree as earlier drafts of this document implied.

---

# Development Guidelines

## Controllers

Controllers should remain thin.

Avoid:

```java
try {
    // business logic
} catch (Exception e) {
    // controller error handling
}
```

Use centralized exception handling.

---

## DTOs

Use immutable DTOs where appropriate.

Java records are preferred for simple immutable transfer objects.

---

## Business Logic

Controllers should not contain:

* Trading logic
* Risk calculations
* AI logic
* Database orchestration

These belong in dedicated services or engines.

---

## AI Reproducibility

Every model experiment should capture:

```text
Model Version
Dataset Version
Feature Version
Configuration
Training Period
Validation Period
Metrics
Experiment ID
```

Without reproducibility, AI performance claims are unreliable.

---

# Getting Started

## Prerequisites

```bash
java -version
mvn -version
psql --version
python --version
```

---

## Build

```bash
git clone <repository-url>

cd easytradify

mvn clean install
```

Specific modules may be built independently:

```bash
cd execution-service

mvn clean package
```

---

## Database

Example development databases:

```text
easytradify-execution-service

easytradify-monitor-service

easytradify-portfolio-service

easytradify-ai-service
```

Production deployment should use environment-based configuration.

Credentials should never be committed into the repository.

---

## Run Services

Example development order:

```text
1. PostgreSQL

2. Discovery Server

3. Execution Service

4. Monitor Service

5. Portfolio Risk Service

6. AI Service

7. Python Engines

8. MT5 Integration
```

---

# API Documentation

Swagger UI should be exposed per service.

Example:

```text
Execution Service
/swagger-ui.html

Monitor Service
/swagger-ui.html

Portfolio Service
/swagger-ui.html

AI Service
/swagger-ui.html
```

OpenAPI JSON:

```text
/v3/api-docs
```

---

# Testing and Validation

Traditional software testing is not sufficient for trading intelligence.

The project requires two testing layers.

## Software Testing

* Unit tests
* Integration tests
* API tests
* Database tests
* Broker integration tests
* Failure tests

---

## Intelligence Validation

* Historical replay
* Out-of-sample testing
* Walk-forward testing
* Regime testing
* Adversarial robustness testing
* Counterfactual analysis
* Transaction cost sensitivity
* Spread sensitivity
* Slippage sensitivity
* Portfolio-level evaluation
* A/B testing

A model should not be promoted because of one impressive backtest.

---

# Implemented vs Planned Components

This section reflects the actual repository state as of the last review, not aspiration. Verify against the current code before relying on it, since this system evolves quickly (many `core/` modules carry their own changelog-style comments documenting recent fixes).

## Implemented

**Java platform**
```text
Discovery Server (Eureka, port 8761)
Execution Service (port 8081) — trade execution, position/SL/TP/trailing management,
    account/symbol info, MT5 connect, trade history, lot calc, webhooks, copy trading
Monitor Service (port 8082) — start/stop, symbol discovery/filtering/ranking, logs
Portfolio Risk Management (port 8083) — status, limits, funded-account compliance,
    check-trading-allowed gate
AI Service (port 8084) — REST proxy only, forwards to Python GNN + Adversarial modules
Common library — shared DTOs/exceptions/utils
Angular frontend (front/easy-tradify-ui) — consumes the above service APIs
```

**Python engine (`easytradifyPythonBot/`)** — substantially more built out than the Java layer:
```text
Market structure, SMC (BOS/CHoCH, order blocks, liquidity sweeps, premium/discount),
    Wyckoff phases, ICT/FVG lifecycle, VWAP (session + anchored), RVAM, round-number
    levels, classical chart patterns + Elliott Wave, multi-timeframe trend cascade
Technical indicators (RSI/MACD/Bollinger/Stochastic/ADX/ATR) with divergence-aware,
    regime-adaptive scoring and decorrelated "family voting" across indicator clusters
Microstructure/tape analysis (absorption, momentum bursts, spread collapse) from live
    MT5 ticks
Graph Neural Network cross-asset correlation (ai/ai_gnn.py) wired into the probability
    chain with alignment/confidence weighting. Confirmed live as of the last review —
    was silently disabled for an unknown period by a broken ai/__init__.py (see AI Service
    section) that made the whole ai package fail to import; fixed by populating the
    empty ai_config.py and trimming __init__.py to only import modules that exist.
Deterministic, lookahead-safe historical replay engine with calibration/expectancy
    reporting (not raw win rate) — replay.py, engine_replay.py, phase_report.py,
    replay_forensics.py, run_preregistered.py
Decision-trace/snapshot system for reconstructing why a decision was made
    (decision_snapshot.py, decision_trace.py, decision_features.py)
Defensive decision gates: symbolic gate (hard arithmetic invariants), conviction
    filter (internal agreement check), coherence validator (observer-only) — each
    can only downgrade a YES to a NO, never the reverse
Portfolio/account risk service (drawdown, daily/monthly loss limits, funded-account
    rules) — separate from the Java Portfolio Risk service
MongoDB trade persistence — easytradify.trades with full open/update/close
    lifecycle (see Trade storage section). Firestore keeps portfolio_config and
    ai_models only; TRADES_TO_FIRESTORE = False. ~70 AI-collection names remain
    declared in core/firebase/firebase_config.py
Price-evolution encoder (ai/price_evolution_encoder.py) — live, called from
    monitor/firebase_helpers.py on every price_evolution write
```

## Built but not live (exists, has no execution path from live trading)

```text
Adversarial robustness testing (ai/ai_adversarial.py) — real, coherent, ~3000 lines,
    but reachable only via ai_controller.py, which nothing calls and which cannot
    itself start (imports two sibling modules, ai_ab_testing.py / ai_diffusion.py,
    that do not exist in the repo)
RL scaffolding (ai/ai_reinforcement.py) — rewritten into standalone offline research
    code (RLAgent/RLConfig); no live trade decision touches it
Non-RL statistical layer (ai/non_rl_intelligence.py) — a complete sklearn pipeline
    that nothing in the repo imports
Root-cause self-correction (ai/root_cause_*.py) — a clean "evidence-only" redesign,
    but never instantiated anywhere; the Firebase methods it would feed
    (save_root_cause / save_correction / save_evolution, etc. in
    core/firebase/firebase_service.py) have zero call sites, so the
    ai_root_causes / ai_corrections / ai_evolutions / ai_rule_evolution Firebase
    collections are currently never written despite being declared in
    firebase_config.py
Price-evolution decoder (ai/price_evolution_decoder.py) — reached only through
    PriceEvolutionBridge.to_canonical(), which ai_adversarial.py now calls; nothing
    else decodes stored history yet
PriceEvolutionBridge.extract_learning_data() — the sequence-level learning-signal
    extraction (confidence trajectory, component-failure timeline, first material
    score drop, etc.) is fully implemented but still has no consumer
```

## Planned / Not Yet Built

```text
AI Service exposing anything beyond GNN + Adversarial (Decision Genome, Replay,
    Counterfactual, Non-RL, RL, Validation, Experiments as Java-side endpoints)
Counterfactual Simulator (explicit "what if a different decision had been made" engine)
Formal Decision Genome schema/versioning as a first-class stored artifact
    (the ingredients exist via decision_snapshot.py/decision_trace.py, but not as a
    single versioned schema)
Entry Timing RL / Management RL / Sizing RL as live-trading decision agents
Formal Validation Engine / Experiment Engine as reusable platform components
    (walk-forward, out-of-sample, and A/B-style analysis exist as standalone scripts —
    phase_report.py, run_preregistered.py — not as a service or shared framework)
Wiring the built-but-dead subsystems above (adversarial, RL, non-RL, root-cause,
    price-evolution decoder/bridge) into an actual execution path
Model/dataset versioning
Unified `/api/v1/ai/*` endpoint grouping described under AI API Direction
```

---

# Roadmap

## Phase 1 — Stabilize Existing Platform

* Audit existing services
* Remove broken or duplicate logic
* Standardize contracts
* Verify MT5 integration
* Stabilize execution
* Stabilize monitoring
* Stabilize portfolio risk
* Verify persistence
* Improve test coverage

---

## Phase 2 — Complete Market Intelligence

* Unify market structure
* Unify liquidity detection
* Build FVG lifecycle
* Build VWAP engine
* Add CLV / absorption
* Integrate RVAM
* Improve microstructure
* Finalize Trade Quality Score

---

## Phase 3 — Cross-Asset Intelligence

* Build graph representation
* Define nodes and edges
* Add dynamic relationships
* Add lead-lag features
* Add correlation regime detection
* Integrate GNN context into decisions

---

## Phase 4 — Adversarial Robustness

* Feature perturbation
* Spread perturbation
* Volatility perturbation
* Missing-data scenarios
* Correlation breakdown
* Robustness metrics

---

## Phase 5 — Decision Genome

* Define schema
* Capture all decision context
* Version decision schemas
* Store execution outcomes
* Connect historical decisions to results

---

## Phase 6 — AI_MarketReplay

* Historical replay
* Decision reconstruction
* Outcome analysis
* Failure clustering
* Regime analysis

---

## Phase 7 — Counterfactual Engine

* Alternative entry timing
* Alternative cancellation
* Alternative stop placement
* Alternative management
* Alternative sizing

---

## Phase 8 — Non-RL Intelligence

* Regime classification
* Failure prediction
* Trade quality prediction
* Expected value estimation
* Uncertainty estimation
* Model calibration

---

## Phase 9 — Reinforcement Learning

### Entry Agent

```text
WAIT
ENTER
CANCEL
```

### Management Agent

```text
HOLD
EXIT
PROTECT
```

### Risk Agent

```text
REJECT
REDUCE
ACCEPT
```

---

## Phase 10 — Validation and Controlled Deployment

* Walk-forward validation
* Out-of-sample validation
* Adversarial validation
* A/B testing
* Shadow mode
* Controlled rollout

---

# Final Architecture Philosophy

EasyTradify should not become:

> "A giant collection of indicators, AI buzzwords, and models producing BUY and SELL predictions."

The target architecture is:

```text
OBSERVE
    │
    ▼
UNDERSTAND MARKET STRUCTURE
    │
    ▼
UNDERSTAND CROSS-ASSET CONTEXT
    │
    ▼
TEST DECISION ROBUSTNESS
    │
    ▼
CAPTURE DECISION GENOME
    │
    ▼
REPLAY HISTORY
    │
    ▼
SIMULATE ALTERNATIVES
    │
    ▼
ESTIMATE EXPECTANCY
    │
    ▼
OPTIMIZE SEQUENTIAL DECISIONS
    │
    ▼
VALIDATE OUT OF SAMPLE
    │
    ▼
CHECK PORTFOLIO RISK
    │
    ▼
EXECUTE
    │
    ▼
LEARN FROM RESULT
```

The goal is not to guarantee a specific win rate.

The goal is to build a system that continuously improves its ability to identify:

* Higher-quality opportunities
* Conditions where strategies fail
* Fragile decisions
* Better entry timing
* Better trade management
* Better risk allocation
* Better portfolio behavior

while maintaining strict validation between research results and live trading behavior.

---

# License

This project is licensed under the MIT License unless otherwise specified.

---

**EasyTradify — Market Intelligence, Decision Intelligence, and Validated Algorithmic Execution.**
