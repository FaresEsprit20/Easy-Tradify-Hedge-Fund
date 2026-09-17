# Setup contract

A `Setup` is the only object that can become a trade. It is produced by exactly one category.

## Fields

| field | type | set by | rule |
|---|---|---|---|
| `id` | str | category | `<category>:<symbol>:<variant>:<trigger bar time>` |
| `category` | str | category | one of TREND, MOMENTUM, MEAN_REVERSION, STRUCTURE, SMC, ORDER_FLOW, WAVE, CROSS_ASSET |
| `variant` | str | category | named in the category spec |
| `symbol` | str | category | |
| `timeframe` | str | category | the timeframe whose closed bar triggered the setup |
| `side` | `BUY` / `SELL` | category | |
| `created_at` | int (broker epoch s) | category | close time of the trigger bar; never a forming bar |
| `valid_until` | int | category | a pending entry is cancelled after this |
| `context` | dict | category | recorded conditions (HTF trend, regime, session, …); **never a score** |
| `location` | dict | category | `{type, proximal, distal, level, sources}` |
| `trigger` | dict | category | `{type, bar_time, …}` |
| `entry` | dict | category | `{order_type: LIMIT \| STOP \| MARKET, price}` (MARKET: `price` = reference close) |
| `stop` | dict | category | `{price, reason}` |
| `targets` | list | category | `[{price, share, reason}]`; shares sum to 1.0 |
| `management` | dict | category | `{breakeven_after_target: int or None, time_stop_bars: int or None, trail: str or None}` |
| `thesis` | list | category | `[{name, …}]`; evaluated by `engine_v2/thesis.py` on each closed bar of `timeframe` |
| `probability` | dict | probability layer | `{value or None, n, low, high, table}`; `None` means **unknown** |
| `risk` | dict | risk layer | `{usd, lot, affordable, reason}` |
| `status` | str | lifecycle | see below |

## Validation (`Setup.validate`)
- **BUY:** `stop < entry < every target`. **SELL:** the reverse. The stop distance must be positive.
- `targets` is non-empty, and the shares sum to 1 (within 1e-6).
- `valid_until > created_at`.
- `entry.order_type` is one of the three types.
- An invalid setup raises an error. It is never silently repaired.

## Lifecycle
`PROPOSED → PENDING → FILLED → MANAGED → CLOSED`. A setup can also end as `EXPIRED` (entry not
filled by `valid_until`), `CANCELLED` (thesis broken before the fill) or `NOT_TRADEABLE`
(unaffordable, or probability unknown in live mode).

## Fills and exits (replay and live use the same rules)
Price rules:
- **BUY:** fills on the **ask**, and exits (stop or target) on the **bid**.
- **SELL:** fills on the **bid**, and exits on the **ask**.

Entry fills:
- **LIMIT BUY:** fills when ask low ≤ price, at price, or at the bar's ask open when it gaps below.
- **STOP BUY:** fills when ask high ≥ price, at max(price, ask open).
- **MARKET:** fills at the next M1 bar's ask open (BUY) or bid open (SELL).

Exit rules:
- **Stop or target in the same M1 bar:** the **stop** is assumed first.
- **Target and stop:** after target k, the stop moves to the entry price if
  `breakeven_after_target == k`.
- **Time stop and thesis exit:** close at the next M1 open on the exit side.
