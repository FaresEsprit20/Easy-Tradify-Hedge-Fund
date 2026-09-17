# v1 building map (frozen reference)

**v1 frozen at commit `853243ec18174442f113fca2c991466fa0cb51b8`** (2026-09-16).

- At freeze time the working tree had uncommitted documentation only: `diagnosis.md`,
  `NEXT_SESSION.md`, `edge_candidates.md`, `roadmap.md`, `strategic_plan.md`. No v1 code differed
  from this commit.
- No git tag was created, because commits and tags wait for the operator. This hash is the
  reference.
- v2 must not modify v1's `core/`, `monitor/` or `api/`.

## How v1 makes a trade
The full trace is in `strategic_plan.md` §2:
1. **Side:** chosen by `calculate_real_probability` (`core/calculations.py:1758-2151`), which is
   called from `core/asset_analysis.py:2405, 2441`.
2. **Categories:** they grade that side (`core/strategy_groups.py:617`).
3. **Name:** the winning category's name is written into the report only (`core/asset_analysis.py:1062`).
4. **Entry:** a market order (`core/execution.py:2614`).
5. **Stop and target:** 1.5 × H1 ATR and 1R for every category (`core/market_stop.py:53-54`).
6. **Management:** none (`monitor/monitor_core.py:1887`).

## Defects by layer
See `strategic_plan.md` §3. The config table there (§3.6) is the list of v1 constants that must not
be carried over.

## Where every v1 category member goes in v2

| v1 category | v1 members | v2 strategy (`engine_v2/categories/`) |
|---|---|---|
| TREND | trend indicator, trend cascade M5–H4, H1 trend, price vs EMA200 | `trend.py`: H4/H1 structure trend, H1 fib pullback, M15 CHoCH trigger |
| MOMENTUM | MACD, TTM squeeze, RVAM, VWAP side, stochastic cross, Bollinger band walk | `momentum.py`: squeeze release + MACD histogram + VWAP side, band-walk trail |
| MEAN_REVERSION | OU dislocation, RSI extreme, stochastic extreme | `mean_reversion.py`: balance regime, VWAP σ-stretch, RSI exhaustion, VWAP target, time stop |
| STRUCTURE | supply/demand, support/resistance, Fibonacci confluence | `structure.py`: H1 base + departure zones, first-touch and confirmation variants |
| SMC | SMC overall, market structure, liquidity sweep, premium/discount, ICT FVG, FVG/IFVG | `smc.py`: pool sweep → displacement BOS + FVG → limit at FVG |
| ORDER_FLOW | volume, volume profile, liquidity-sweep bias, order flow | `order_flow.py`: prior-day value area, failed auction, acceptance |
| WAVE | chart patterns, wave lattice, Elliott, Wyckoff, candlestick | `wave.py`: Wyckoff spring, double top/bottom, Elliott wave-2 entry |
| CROSS_ASSET | GNN direction, GNN recommendation | `cross_asset.py`: built last |

## Retired and not ported
- `calculate_real_probability`
- category scores and the auction
- `_trend_confirmed` wrappers and continuation inversions
- context points and the penalty band
- `PROBABILITY_RECENTER_POINTS`
- the orphan flags (`USE_CONVICTION_FILTER`)
