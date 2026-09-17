# ORDER_FLOW: the auction around value

**v1 members:** volume, volume profile, liquidity-sweep bias, order flow.

**Trades:** how price is accepted or rejected relative to the prior day's value area.

**Timeframes:** prior broker day profile, M15 closes, fills on M1.

## Variant `failed_auction` (SELL after a failed auction above VAH; BUY below VAL is symmetric)
1. **Excursion.** During today (from broker 01:05), price trades above yesterday's VAH.
2. **Failure.** After the excursion, `OF_BACK_INSIDE = 2` consecutive M15 bars close below VAH and
   above VAL.
3. **Entry.** MARKET at the next M1 open after the second close, with `valid_until` = that close + 1
   M15 bar.
4. **Stop.** The highest high of the excursion (since the first trade above VAH today) plus
   `max(0.10 × ATR(M15), 1.5 × spread)`.
5. **Targets.**
   - **T1:** POC, share 0.5. If less than 1R away, T1 = entry − 1R.
   - **T2:** VAL, share 0.5. If VAL is less than 1.5R away, T2 = entry − 1.5R.
6. **Management.**
   - Breakeven after T1.
   - Time stop: 48 M15 bars.
7. **Thesis.** An M15 close back above VAH ends the trade.
8. **Frequency.** One setup per side per day.

## Variant `acceptance` (BUY on acceptance above VAH; SELL below VAL is symmetric)
1. **Acceptance.** Price starts the day inside value. Then `OF_ACCEPT = 3` consecutive M15 bars close
   above VAH.
2. **Entry.** BUY LIMIT at VAH, with `valid_until` = the third close + 8 M15 bars.
3. **Stop.** `VAH − 1.0 × ATR(M15)`, but at least `max(0.10 × ATR(M15), 1.5 × spread)` below the
   entry.
4. **Targets.**
   - **T1:** entry + 1R, share 0.5.
   - **T2:** yesterday's high if it is at least 2R away, otherwise entry + 2R; share 0.5.
5. **Management.**
   - Breakeven after T1.
   - Time stop: 48 M15 bars.
6. **Thesis.** Two consecutive M15 closes back inside value end the trade.
7. **Frequency.** One setup per side per day.

## Recorded conditions
- value-area width in ATR;
- open location (inside, above or below value);
- session;
- H4 structure trend;
- delta sign at the trigger (MT5 source only).
