# ============================================================
# DETERMINISTIC HISTORICAL REPLAY
# ============================================================
# FILE: core/replay.py
#
# Roadmap Phase 6. Acceptance gate: "Replay is deterministic,
# explainable and has zero future-data violations."
#
# The lookahead problem is not solved by being careful. It is solved by
# making future data STRUCTURALLY UNREACHABLE, so that a lookahead bug
# raises instead of quietly inflating the backtest. That is what
# BarWindow does: it hands the engine a numpy view truncated at the
# decision bar, and the future bars are held separately in a private
# attribute that the analysis code never receives.
#
# Two lookahead traps this codebase specifically has:
#
#   1. THE FORMING BAR (defect D-07). Live, the engine reads rates[-1],
#      which is the bar currently forming -- its high/low/close will
#      still change. In replay, rates[-1] is a CLOSED bar whose full
#      range is known. So the identical code sees strictly more
#      information in replay than it had live, and the backtest is
#      optimistic for a reason that has nothing to do with the strategy.
#      `closed_bars_only=True` (the default) drops the forming bar so
#      replay and live see the same thing.
#
#   2. OUTCOME EVALUATION ORDER. When a bar's range spans both stop and
#      target, you cannot tell from OHLC which was hit first. Assuming
#      the target is a silent win-rate inflator. This module assumes the
#      STOP (see AMBIGUOUS_BAR_POLICY) and counts those bars, because a
#      backtest that hides its own ambiguity is worthless.
# ============================================================

from typing import Dict, Any, List, Optional, Callable, Iterator, Tuple
import logging

logger = logging.getLogger(__name__)


# When one bar's range covers both the stop and the target, which was
# hit first is unknowable from OHLC alone. Options: "stop" (pessimistic,
# the default and the only honest choice without tick data), "target"
# (optimistic -- inflates win rate), "skip" (exclude from statistics).
AMBIGUOUS_BAR_POLICY = "stop"


class LookaheadViolation(Exception):
    """Raised when analysis code reaches for data after the decision bar."""


class BarWindow:
    """
    An immutable view of history up to and including the decision bar.

    Future bars are NOT stored on this object in any reachable form --
    they live on the ReplayRunner, which never passes them to analysis
    code. The only way to see the future is to ask the runner for
    outcome evaluation, which happens after the decision is recorded.
    """

    __slots__ = ("rates", "decision_index", "decision_timestamp", "_len")

    def __init__(self, rates, decision_index: int, decision_timestamp):
        self.rates = rates
        self.decision_index = decision_index
        self.decision_timestamp = decision_timestamp
        self._len = len(rates)

    def __len__(self) -> int:
        return self._len

    def assert_no_future(self, timestamps) -> None:
        """
        Verify that nothing in a set of timestamps postdates the
        decision. Used to audit any evidence payload that carries its
        own timestamps.
        """
        if self.decision_timestamp is None:
            return
        for ts in timestamps or ():
            try:
                if float(ts) > float(self.decision_timestamp):
                    raise LookaheadViolation(
                        f"timestamp {ts} is after decision timestamp {self.decision_timestamp}"
                    )
            except (TypeError, ValueError):
                continue


class ReplayRunner:
    """
    Walk historical bars, call an analysis function at each one with
    only past data, record the decision, then evaluate the outcome
    against the bars that followed.

    `analyze_fn` must have the shape:
        analyze_fn(window: BarWindow) -> Dict[str, Any]
    and return at minimum:
        {"entry_triggered": bool, "direction": "BUY"|"SELL",
         "entry_price": float, "stop_loss": float, "take_profit": float,
         "trace": DecisionTrace | None}

    The runner is deliberately agnostic about HOW the decision is made.
    That keeps it usable against the live engine, a stub, or a
    single-component harness, and it is what makes the determinism test
    meaningful.
    """

    def __init__(self, rates, *, timeframe: str = "M1", symbol: str = "",
                 warmup_bars: int = 300, max_holding_bars: int = 500,
                 closed_bars_only: bool = True, pip_size: float = 0.0001,
                 spread_pips: float = 0.0,
                 ambiguous_policy: str = AMBIGUOUS_BAR_POLICY):
        self._rates = rates
        self.timeframe = timeframe
        self.symbol = symbol
        self.warmup_bars = warmup_bars
        self.max_holding_bars = max_holding_bars
        self.closed_bars_only = closed_bars_only
        self.pip_size = pip_size
        self.spread_pips = spread_pips
        self.ambiguous_policy = ambiguous_policy
        self.stats = {
            "bars_scanned": 0, "decisions": 0, "entries": 0,
            "ambiguous_bars": 0, "unresolved": 0,
            "lookahead_violations": 0,
        }

    # ---------- windowing ----------

    def windows(self) -> Iterator[BarWindow]:
        """
        Yield one window per decision bar.

        The slice end is EXCLUSIVE of everything after the decision bar.
        When closed_bars_only is True the decision bar itself is the last
        CLOSED bar, mirroring what the live engine can actually know.
        """
        n = len(self._rates)
        for i in range(self.warmup_bars, n):
            end = i + 1
            if self.closed_bars_only:
                # Live, rates[-1] is still forming. Replay must not hand
                # the engine a completed version of it.
                end = i
                if end <= self.warmup_bars:
                    continue
            sliced = self._rates[:end]
            ts = self._time_at(end - 1)
            self.stats["bars_scanned"] += 1
            yield BarWindow(sliced, end - 1, ts)

    # ---------- outcome ----------

    def evaluate_outcome(self, decision_index: int, direction: str,
                         entry_price: float, stop_loss: float,
                         take_profit: float) -> Dict[str, Any]:
        """
        Walk forward from the bar AFTER the decision and determine what
        actually happened. Uses only bars strictly after decision_index.
        """
        d = (direction or "").upper()
        if d not in ("BUY", "SELL"):
            return {"outcome": "INVALID", "reason": f"bad direction {direction!r}"}

        n = len(self._rates)
        start = decision_index + 1
        end = min(n, start + self.max_holding_bars)

        for i in range(start, end):
            hi = self._high_at(i)
            lo = self._low_at(i)
            if hi is None or lo is None:
                continue

            if d == "BUY":
                hit_stop = lo <= stop_loss
                hit_target = hi >= take_profit
            else:
                hit_stop = hi >= stop_loss
                hit_target = lo <= take_profit

            if hit_stop and hit_target:
                # Unknowable from OHLC. Recorded, not guessed away.
                self.stats["ambiguous_bars"] += 1
                if self.ambiguous_policy == "target":
                    return self._outcome("WIN", i, take_profit, decision_index,
                                         entry_price, stop_loss, take_profit, d,
                                         ambiguous=True)
                if self.ambiguous_policy == "skip":
                    return {"outcome": "AMBIGUOUS", "bars_held": i - decision_index,
                            "reason": "stop and target both inside one bar's range"}
                return self._outcome("LOSS", i, stop_loss, decision_index,
                                     entry_price, stop_loss, take_profit, d,
                                     ambiguous=True)

            if hit_stop:
                return self._outcome("LOSS", i, stop_loss, decision_index,
                                     entry_price, stop_loss, take_profit, d)
            if hit_target:
                return self._outcome("WIN", i, take_profit, decision_index,
                                     entry_price, stop_loss, take_profit, d)

        self.stats["unresolved"] += 1
        return {"outcome": "UNRESOLVED", "bars_held": end - start,
                "reason": f"neither level reached within {self.max_holding_bars} bars"}

    def _outcome(self, kind, exit_index, exit_price, decision_index,
                 entry_price, stop_loss, take_profit, direction, ambiguous=False):
        if direction == "BUY":
            risk = (entry_price - stop_loss) / self.pip_size
            moved = (exit_price - entry_price) / self.pip_size
        else:
            risk = (stop_loss - entry_price) / self.pip_size
            moved = (entry_price - exit_price) / self.pip_size
        r_multiple = (moved / risk) if risk > 0 else None
        return {
            "outcome": kind,
            "exit_index": exit_index,
            "exit_price": exit_price,
            "bars_held": exit_index - decision_index,
            "pips_moved": round(moved, 2),
            "risk_pips": round(risk, 2),
            # Realized R, net of spread. This is the number that matters
            # for a 1:2 programme -- a "win" that only covers the spread
            # is not a 2R win, and reporting hit rate without it is how
            # backtests lie.
            "r_multiple": round(r_multiple, 3) if r_multiple is not None else None,
            "r_multiple_net": (round((moved - self.spread_pips) / risk, 3)
                               if risk > 0 else None),
            "ambiguous": ambiguous,
        }

    # ---------- driver ----------

    def run(self, analyze_fn: Callable[[BarWindow], Dict[str, Any]],
            *, on_decision: Optional[Callable[[Dict[str, Any]], None]] = None,
            stop_after: Optional[int] = None) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for window in self.windows():
            try:
                decision = analyze_fn(window) or {}
            except LookaheadViolation:
                self.stats["lookahead_violations"] += 1
                raise
            except Exception as e:
                logger.debug(f"[REPLAY] analysis failed at index {window.decision_index}: {e}")
                continue

            self.stats["decisions"] += 1
            trace = decision.get("trace")

            rec: Dict[str, Any] = {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "decision_index": window.decision_index,
                "decision_timestamp": window.decision_timestamp,
                "entry_triggered": bool(decision.get("entry_triggered", False)),
                "direction": decision.get("direction"),
                "rejection_reason": decision.get("rejection_reason"),
                "trace": trace.to_dict() if hasattr(trace, "to_dict") else trace,
            }

            if trace is not None and hasattr(trace, "verify"):
                rec["trace_verification"] = trace.verify()
                rec["probability_reconciliation"] = trace.reconcile_probability()

            if rec["entry_triggered"]:
                self.stats["entries"] += 1
                rec["entry_price"] = decision.get("entry_price")
                rec["stop_loss"] = decision.get("stop_loss")
                rec["take_profit"] = decision.get("take_profit")
                rec["planned_rr"] = decision.get("planned_rr")
                rec["outcome"] = self.evaluate_outcome(
                    window.decision_index, decision.get("direction"),
                    decision.get("entry_price"), decision.get("stop_loss"),
                    decision.get("take_profit"),
                )

            records.append(rec)
            if on_decision:
                on_decision(rec)
            if stop_after and len(records) >= stop_after:
                break
        return records

    # ---------- rate accessors ----------
    # Isolated so the runner works with numpy structured arrays (MT5's
    # native shape), plain tuples, or dicts, without the rest of the
    # class caring.

    def _field(self, i: int, name: str, tuple_index: int):
        try:
            row = self._rates[i]
        except (IndexError, TypeError):
            return None
        try:
            return float(row[name])
        except (KeyError, ValueError, IndexError, TypeError):
            pass
        try:
            return float(row[tuple_index])
        except (IndexError, TypeError, ValueError, KeyError):
            return None

    def _time_at(self, i):
        return self._field(i, "time", 0)

    def _high_at(self, i):
        return self._field(i, "high", 2)

    def _low_at(self, i):
        return self._field(i, "low", 3)

    def _close_at(self, i):
        return self._field(i, "close", 4)