# ============================================================
# CANONICAL DECISION TRACE
# ============================================================
# FILE: core/decision_trace.py
#
# Roadmap Phase 3 (Decision Integrity) + Phase 6 (Replay).
#
# The invariant this exists to satisfy:
#   "Every final decision can be reconstructed from its DecisionTrace."
#
# That word RECONSTRUCTED is doing real work. A log is not a trace. A
# trace is only useful if you can take the recorded facts, apply the
# decision rules INDEPENDENTLY of the engine, and arrive at the same
# answer the engine gave. When the two disagree, one of three things is
# true and all of them are worth knowing:
#
#   1. the engine has a path the trace does not record (hidden path),
#   2. the trace records a fact the engine did not actually use (dead
#      evidence), or
#   3. the reconstruction's model of the rules is wrong (the rules are
#      not what anyone thought they were).
#
# The existing probability_ledger (_ledger_step in asset_analysis.py) is
# the model for this and is already correct for its scope -- it records
# EVERY movement of best_probability including no-op steps, because
# "this check ran and declined to act" is different from "this check did
# not run". This module extends the same discipline to the rest of the
# decision: vetoes, entry state, micro-structure, R:R and the final
# verdict.
#
# Design rules:
#   - RECORD, DON'T RECOMPUTE. Every stage records the value the engine
#     actually used at the moment it used it. A trace that recomputes is
#     a second engine, and it will drift.
#   - NO SILENT ABSENCE. A stage that did not run is recorded as
#     not-run, distinct from a stage that ran and found nothing.
#   - PURE. This module imports nothing from core.* except risk_reward,
#     and never touches MT5, the network or the clock. It must be
#     replayable.
# ============================================================

from typing import Dict, Any, List, Optional
import json


SCHEMA_VERSION = "1.0"


# Terminal decision states, in the order the engine can reach them.
# Ordering matters for reconstruction: the FIRST gate that rejects is
# the reason, and later gates do not overwrite it. This mirrors the
# engine's monotone-downgrade behaviour, where a floor "never overwrites
# an existing veto/skip reason that already fired earlier for its own
# cause".
GATE_ORDER = (
    "data_integrity",
    "direction_selected",
    "entry_qualification",
    "hard_veto",
    "probability_floor",
    "rr_floor",
)


class DecisionTrace:
    """
    One symbol, one decision, one trace.

    Built incrementally as the analysis runs. `reconstruct()` then
    replays the recorded facts through an independent implementation of
    the decision rules and returns its own verdict, which the caller
    compares against the engine's.
    """

    def __init__(self, symbol: str, timeframe: str, decision_timestamp: Optional[int] = None,
                 bar_index: Optional[int] = None):
        self.schema_version = SCHEMA_VERSION
        self.symbol = symbol
        self.timeframe = timeframe
        # The bar timestamp the decision was made ON. Everything in this
        # trace must derive from data at or before this moment. Phase 6's
        # zero-lookahead guarantee is checked against this field.
        self.decision_timestamp = decision_timestamp
        self.bar_index = bar_index

        self.market: Dict[str, Any] = {}
        self.evidence: Dict[str, Any] = {}
        self.probability_ledger: List[Dict[str, Any]] = []
        self.probability_at_decision: Optional[float] = None
        self.probability_final: Optional[float] = None
        self.vetoes: Dict[str, Any] = {"evaluated": False}
        self.entry: Dict[str, Any] = {"evaluated": False}
        self.micro_structure: Dict[str, Any] = {"evaluated": False}
        self.risk_reward: Dict[str, Any] = {"evaluated": False}
        self.thresholds: Dict[str, Any] = {}
        self.engine_decision: Dict[str, Any] = {}
        self.data_integrity: Dict[str, Any] = {"violations": []}
        self.notes: List[str] = []

    # ---------- recording ----------

    def record_market(self, **kw) -> None:
        """Spread, ATR, regime, session, volume ratio, candle completeness."""
        self.market.update(kw)

    def record_evidence(self, name: str, payload: Any) -> None:
        """
        One evidence producer's output. Stored verbatim -- if the engine
        consumed a dict with available=False, the trace records that,
        not a tidied-up version.
        """
        self.evidence[name] = payload

    def record_thresholds(self, **kw) -> None:
        """
        The EFFECTIVE thresholds in force for this decision, not the
        config defaults. Invariant: "effective thresholds are consistent
        for the same context" -- unverifiable unless recorded per
        decision.
        """
        self.thresholds.update(kw)

    def record_probability_ledger(self, ledger: List[Dict[str, Any]]) -> None:
        self.probability_ledger = list(ledger or [])

    def record_probability_at_decision(self, value: float) -> None:
        self.probability_at_decision = _f(value)

    def record_probability_final(self, value: float) -> None:
        self.probability_final = _f(value)

    def record_vetoes(self, *, fired: bool, reason: Optional[str],
                      directional: Optional[Dict[str, Any]] = None,
                      detail: Optional[Dict[str, Any]] = None) -> None:
        """
        The veto result the FINAL DECISION used -- not a second
        evaluation for reporting. Defect D-05 is that the codebase
        currently has three veto truths; this field is defined to be the
        one at the decision point.
        """
        self.vetoes = {
            "evaluated": True,
            "fired": bool(fired),
            "reason": reason,
            "directional": directional or {},
            "detail": detail or {},
        }

    def record_entry(self, entry_result: Dict[str, Any]) -> None:
        er = entry_result or {}
        self.entry = {
            "evaluated": True,
            "should_enter": bool(er.get("should_enter", False)),
            "entry_status": er.get("entry_status"),
            "simple_action": er.get("simple_action"),
            "execution": er.get("execution"),
            "star_rating": er.get("star_rating"),
            "reason": er.get("reason"),
            "discount_info": er.get("discount_info"),
            "signals": er.get("signals"),
        }
        ms = er.get("micro_structure") or {}
        self.micro_structure = {
            "evaluated": bool(ms),
            "timing_confidence": ms.get("timing_confidence"),
            "timing_ready": ms.get("timing_ready", False),
            "detail": ms,
        }

    def record_risk_reward(self, rr_dict: Dict[str, Any]) -> None:
        """Accepts RiskReward.as_dict() from core/risk_reward.py."""
        d = dict(rr_dict or {})
        d["evaluated"] = True
        self.risk_reward = d

    def record_engine_decision(self, *, final_decision: str, simple_action: str,
                               execution: str, entry_triggered: bool,
                               direction: Optional[str] = None) -> None:
        self.engine_decision = {
            "final_decision": final_decision,
            "simple_action": simple_action,
            "execution": execution,
            "entry_triggered": bool(entry_triggered),
            "direction": direction,
        }

    def record_integrity_violation(self, kind: str, detail: str) -> None:
        """
        Invariant: "missing, invalid or stale data cannot silently become
        positive evidence". Anything that would have been papered over
        with a default is recorded here instead.
        """
        self.data_integrity["violations"].append({"kind": kind, "detail": detail})

    def note(self, text: str) -> None:
        self.notes.append(text)

    # ---------- reconstruction ----------

    def reconstruct(self) -> Dict[str, Any]:
        """
        Independently derive the verdict from recorded facts.

        This deliberately does NOT call the engine, import the entry
        engine, or re-read market data. It applies the documented
        decision hierarchy to the trace and nothing else. If it
        disagrees with engine_decision, that disagreement is the finding.
        """
        gates: List[Dict[str, Any]] = []

        def gate(name, passed, detail):
            gates.append({"gate": name, "passed": bool(passed), "detail": detail})
            return passed

        # 1. Data integrity -- any violation is disqualifying.
        violations = self.data_integrity.get("violations", [])
        if not gate("data_integrity", not violations,
                    f"{len(violations)} violation(s)" if violations else "clean"):
            return _verdict("NO_ENTRY", "data_integrity", gates,
                            f"Data integrity violations: {violations}")

        # 2. Direction must have been selected.
        direction = self.engine_decision.get("direction")
        if not gate("direction_selected", direction in ("BUY", "SELL"),
                    f"direction={direction!r}"):
            return _verdict("NO_ENTRY", "direction_selected", gates,
                            "No tradeable direction was selected")

        # 3. Entry qualification. Micro-structure CONFIRMS a qualified
        #    setup; it cannot create qualification. So the entry engine's
        #    should_enter is necessary, and timing is checked under it,
        #    never instead of it.
        if not gate("entry_qualification", self.entry.get("should_enter") is True,
                    f"status={self.entry.get('entry_status')!r}"):
            return _verdict("NO_ENTRY", "entry_qualification", gates,
                            self.entry.get("reason") or "Entry engine did not qualify the setup")

        # 4. Hard vetoes.
        if not gate("hard_veto", not self.vetoes.get("fired", False),
                    self.vetoes.get("reason") or "none"):
            return _verdict("NO_ENTRY", "hard_veto", gates,
                            f"VETO - {self.vetoes.get('reason')}")

        # 5. Probability floor, applied to the FINAL probability.
        floor_p = _f(self.thresholds.get("trade_probability_minimum"))
        prob = self.probability_final
        if floor_p is not None:
            if prob is None:
                return _verdict("NO_ENTRY", "probability_floor", gates,
                                "Final probability was not recorded")
            if not gate("probability_floor", prob >= floor_p, f"{prob:.1f} vs floor {floor_p:.1f}"):
                return _verdict("NO_ENTRY", "probability_floor", gates,
                                f"Probability {prob:.1f}% below floor {floor_p:.1f}%")
        else:
            gate("probability_floor", True, "no floor recorded")

        # 6. R:R floor. An unmeasurable R:R never passes (defect D-03).
        floor_rr = _f(self.thresholds.get("min_absolute_risk_reward"))
        rr = self.risk_reward
        if floor_rr is not None:
            if not rr.get("evaluated"):
                return _verdict("NO_ENTRY", "rr_floor", gates, "R:R was never evaluated")
            if not rr.get("valid"):
                return _verdict("NO_ENTRY", "rr_floor", gates,
                                f"R:R unmeasurable: {rr.get('reason')}")
            ratio = _f(rr.get("ratio"))
            if not gate("rr_floor", ratio is not None and ratio >= floor_rr,
                        f"{ratio} vs floor {floor_rr}"):
                return _verdict("NO_ENTRY", "rr_floor", gates,
                                f"R:R {ratio} below floor {floor_rr}")
        else:
            gate("rr_floor", True, "no floor recorded")

        return _verdict("ENTER", None, gates, "All gates passed")

    def verify(self) -> Dict[str, Any]:
        """
        Compare the independent reconstruction against what the engine
        actually did. This is the Phase 3 acceptance gate:
        "Independent reconstruction equals the actual engine decision."
        """
        recon = self.reconstruct()
        engine_entered = bool(self.engine_decision.get("entry_triggered", False))
        recon_entered = recon["verdict"] == "ENTER"
        agrees = engine_entered == recon_entered
        return {
            "agrees": agrees,
            "engine_entered": engine_entered,
            "reconstructed_entered": recon_entered,
            "reconstruction": recon,
            "engine_decision": self.engine_decision,
            "discrepancy": None if agrees else (
                "Engine entered but reconstruction rejects -- the engine has a path "
                "the trace does not record, or a gate is not enforced as documented."
                if engine_entered else
                "Reconstruction would enter but engine did not -- the engine applied a "
                "constraint that is not recorded in the trace."
            ),
        }

    # ---------- probability reconciliation ----------

    def reconcile_probability(self, tolerance: float = 0.05) -> Dict[str, Any]:
        """
        The ledger must account for the whole movement from the first
        recorded `before` to probability_final. A gap means something
        moved the number without recording it.
        """
        if not self.probability_ledger:
            return {"reconcilable": False, "reason": "empty ledger"}

        start = _f(self.probability_ledger[0].get("before"))
        end = _f(self.probability_ledger[-1].get("after"))
        if start is None or end is None:
            return {"reconcilable": False, "reason": "ledger endpoints not numeric"}

        # Steps that hit a clamp legitimately break additivity, so the
        # sum of deltas is checked against the endpoints rather than
        # against start + sum.
        walked = start
        for step in self.probability_ledger:
            b, a = _f(step.get("before")), _f(step.get("after"))
            if b is None or a is None:
                return {"reconcilable": False, "reason": f"non-numeric step {step.get('step')!r}"}
            if abs(b - walked) > tolerance:
                return {
                    "reconcilable": False,
                    "reason": (f"discontinuity at step {step.get('step')!r}: "
                               f"expected before={walked:.2f}, recorded {b:.2f}"),
                    "gap": round(b - walked, 2),
                }
            walked = a

        final = self.probability_final
        if final is not None and abs(final - walked) > tolerance:
            return {
                "reconcilable": False,
                "reason": (f"ledger ends at {walked:.2f} but final probability is "
                           f"{final:.2f} -- {abs(final - walked):.2f} points moved unrecorded"),
                "gap": round(final - walked, 2),
            }

        return {"reconcilable": True, "start": start, "end": walked, "steps": len(self.probability_ledger)}

    # ---------- serialisation ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "decision_timestamp": self.decision_timestamp,
            "bar_index": self.bar_index,
            "market": self.market,
            "evidence": self.evidence,
            "probability_ledger": self.probability_ledger,
            "probability_at_decision": self.probability_at_decision,
            "probability_final": self.probability_final,
            "vetoes": self.vetoes,
            "entry": self.entry,
            "micro_structure": self.micro_structure,
            "risk_reward": self.risk_reward,
            "thresholds": self.thresholds,
            "engine_decision": self.engine_decision,
            "data_integrity": self.data_integrity,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, sort_keys=True)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DecisionTrace":
        t = cls(d.get("symbol", ""), d.get("timeframe", ""),
                d.get("decision_timestamp"), d.get("bar_index"))
        t.schema_version = d.get("schema_version", SCHEMA_VERSION)
        t.market = d.get("market", {})
        t.evidence = d.get("evidence", {})
        t.probability_ledger = d.get("probability_ledger", [])
        t.probability_at_decision = d.get("probability_at_decision")
        t.probability_final = d.get("probability_final")
        t.vetoes = d.get("vetoes", {"evaluated": False})
        t.entry = d.get("entry", {"evaluated": False})
        t.micro_structure = d.get("micro_structure", {"evaluated": False})
        t.risk_reward = d.get("risk_reward", {"evaluated": False})
        t.thresholds = d.get("thresholds", {})
        t.engine_decision = d.get("engine_decision", {})
        t.data_integrity = d.get("data_integrity", {"violations": []})
        t.notes = d.get("notes", [])
        return t


def _verdict(verdict: str, blocked_at: Optional[str], gates: List[Dict[str, Any]],
             reason: str) -> Dict[str, Any]:
    return {"verdict": verdict, "blocked_at": blocked_at, "reason": reason, "gates": gates}


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and float("-inf") < v < float("inf") else None


def build_trace_from_result(result: Dict[str, Any], *, symbol: str = "",
                            timeframe: str = "") -> DecisionTrace:
    """
    Adapter: build a trace from the orchestrator's existing result dict.

    This is the LOW-FIDELITY path. It works today without touching
    asset_analysis.py, which makes it useful for replaying history you
    have already recorded -- but it can only see what the result dict
    publishes, so it cannot detect a hidden path by construction. The
    high-fidelity path records at the decision points themselves.
    """
    t = DecisionTrace(symbol or result.get("symbol", ""),
                      timeframe or result.get("timeframe", ""),
                      result.get("decision_timestamp"),
                      result.get("bar_index"))

    t.record_probability_ledger(result.get("probability_ledger", []))
    t.record_probability_at_decision(result.get("probability_percent"))
    t.record_probability_final(result.get("probability_percent_post_chain"))

    trade = result.get("trade_setup", {}) or {}
    rr_detail = trade.get("risk_reward_detail")
    if rr_detail:
        t.record_risk_reward(rr_detail)

    t.record_thresholds(
        trade_probability_minimum=result.get("trade_probability_minimum"),
        min_absolute_risk_reward=result.get("min_absolute_risk_reward"),
    )

    entry = result.get("entry_analysis", {}) or {}
    t.record_entry(entry)

    veto = result.get("veto", {}) or {}
    t.record_vetoes(fired=bool(veto.get("triggered")), reason=veto.get("reason"),
                    directional=result.get("directional_vetoes"))

    t.record_engine_decision(
        final_decision=entry.get("final_decision", ""),
        simple_action=entry.get("simple_action", "HOLD"),
        execution=entry.get("execution", "DO_NOTHING"),
        entry_triggered=bool(entry.get("should_enter", False)),
        direction=result.get("order_type") or result.get("direction"),
    )
    t.note("built via low-fidelity result-dict adapter; hidden paths are not detectable")
    return t