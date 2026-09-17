# v2 philosophy: binding rules and how they are enforced

Source: `strategic_plan.md` §4. Each rule names the code or test that enforces it.

| # | rule | enforced by |
|---|---|---|
| 1 | **A trade is a setup, not a score.** Only a category strategy creates a trade, and its setup is complete. | `engine_v2/setup.py` rejects a Setup that is missing its entry, stop, targets or thesis (`Setup.validate`); `tests/engine_v2/test_setup_contract.py` |
| 2 | **Risk belongs to the user.** Risk = `risk_per_trade` × `fixed_trade_size_usd`, capped by `MAX_RISK_PER_TRADE`. The lot comes from the category's stop. A setup that is unaffordable at minimum lot is flagged, never re-stopped. | `engine_v2/risk.py`; `test_risk.py` |
| 3 | **Each category is traded the way it defines itself.** Entry type, stop and targets come from the category spec. | `engine_v2/categories/*.py` follow `specs/categories/*.md`; per-category tests with synthetic golden cases |
| 4 | **Categories are independent.** No category imports another category. Agreement between categories is recorded as a condition, never as a gate. | `test_architecture.py` checks the imports |
| 5 | **Location, then trigger, then entry.** A setup exists only on a closed-bar trigger event at its location. | category code; the Setup's `trigger.bar_time` must be a closed bar |
| 6 | **Every trade carries its thesis.** Thesis conditions are re-checked on each closed bar of the category's timeframe. | `engine_v2/sim/outcome.py` and `engine_v2/manager/manager.py` share `thesis.py` |
| 7 | **Stop at invalidation, targets before opposition.** | category specs; `Setup.validate` (stop on the losing side of entry, targets on the winning side) |
| 8 | **No scores, only real probabilities.** A probability is a measured win frequency with sample size and Wilson range. It reads "unknown" below `MIN_SAMPLE`. | `engine_v2/probability/frequency.py`; `test_architecture.py` scans for score/points constructs |
| 9 | **One market model, one truth.** Swings, liquidity, zones, volume and regime are computed once, from closed mid-price bars. | `engine_v2/market_model/`; categories read only `Context` |
| 10 | **Every constant has a reason on record.** | `engine_v2/config_ledger.py`; `test_config_ledger.py` fails on a parameter without an entry |

## Definitions used everywhere
- **Win:** a closed trade whose net R is above 0, after commission. The success rate is wins ÷ closed
  trades.
- **R:** the distance between entry fill and initial stop, times the lot. Net R includes commission
  of $7.03 per lot round trip, converted with the symbol's USD value per price unit.
- **Holdout:** broker time from 2026-06-15 to the end of the data. Everything earlier is discovery.
  Parameters are fixed in the specs; discovery is used only to pick between variants a spec already
  lists.
