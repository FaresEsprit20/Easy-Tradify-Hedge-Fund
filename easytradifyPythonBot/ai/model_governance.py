# ============================================================
# MODEL GOVERNANCE -- A/B ASSIGNMENT AND VERSIONED ROLLBACK
# ============================================================
#
# WHY THIS EXISTS
# ---------------
# The audit that produced this module found A/B testing in 2 of 8 models and
# rollback in none. Six models could not be rolled out against a control at
# all, and no model could be reverted to a last-known-good version: save()
# and load() existed everywhere, but nothing recorded WHICH saved artifact
# was known to work, so "put it back the way it was" was not an operation
# anyone could actually perform.
#
# Standard 10 says never write a second implementation. ai_adversarial and
# ai_gnn already had working A/B, so this is that pattern extracted, not a
# rival to it: the assignment rule, the rollout-adjustment bands and the
# verdict vocabulary come from ai_adversarial.should_attack_trade and
# _adjust_ab_test_rollout.
#
# THE HASH IS CONFIGURABLE ON PURPOSE
# -----------------------------------
# Adversarial hashes trade_id with SHA-256; GNN uses MD5. That is a real
# duplication, but unifying the hash would REASSIGN every in-flight trade
# between control and test -- silently invalidating any comparison already
# running, which is exactly the corruption A/B exists to prevent. The
# algorithm is therefore a parameter, so both keep their existing assignment
# while sharing one implementation. Unify the choice at a rollout boundary,
# never mid-test.
#
# WHAT THIS DELIBERATELY DOES NOT DO
# ----------------------------------
# It does not decide on a threshold alone. A win-rate delta above a band is
# not evidence; with 30 trades an 8-point difference is routine noise. Every
# verdict carries a two-proportion z test and the sample sizes behind it, and
# `significant` is reported separately from `direction` so a caller cannot
# mistake the sign of a difference for the existence of one.
# ============================================================

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

GOVERNANCE_VERSION = "1.0"

_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(payload: Any) -> str:
    """Stable hash of a JSON-serialisable payload."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# A/B assignment
# ---------------------------------------------------------------------------

_HASHES = {"sha256": hashlib.sha256, "md5": hashlib.md5}


@dataclass
class ABConfig:
    enabled: bool = True
    rollout: float = 0.5

    # Below this many settled units in EITHER arm there is no verdict and no
    # auto-adjustment. Acting on fewer is how a rollout chases noise.
    min_samples: int = 30

    improvement_threshold: float = 0.02
    degradation_threshold: float = -0.02
    min_rollout: float = 0.05
    max_rollout: float = 1.0

    # Auto-adjustment moves the rollout when the measured delta leaves the
    # noise band. OFF by default: a model that silently widens its own
    # exposure is not something to enable without deciding to.
    auto_adjust: bool = False

    # sha256 matches ai_adversarial; md5 matches ai_gnn. See the header.
    hash_algorithm: str = "sha256"

    # Significance level for the z test that backs the verdict.
    alpha: float = 0.05


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_proportion_z_test(successes_a: int, total_a: int,
                          successes_b: int, total_b: int
                          ) -> Dict[str, Optional[float]]:
    """
    Two-sided z test on two win rates.

    Reported alongside every verdict, because a threshold comparison alone
    cannot tell a real three-point edge from the three-point edge two fair
    coins produce constantly. Returns None rather than a number when an arm is
    empty or the pooled variance is degenerate: an unmeasurable p-value is
    reported as unmeasurable, never as 1.0.
    """
    if total_a <= 0 or total_b <= 0:
        return {"z": None, "p_value": None}
    proportion_a = successes_a / total_a
    proportion_b = successes_b / total_b
    pooled = (successes_a + successes_b) / (total_a + total_b)
    variance = pooled * (1.0 - pooled) * (1.0 / total_a + 1.0 / total_b)
    if variance <= 0:
        return {"z": None, "p_value": None}
    z = (proportion_b - proportion_a) / math.sqrt(variance)
    return {"z": round(z, 4),
            "p_value": round(2.0 * (1.0 - _normal_cdf(abs(z))), 6)}


class ABTest:
    """
    One deterministic control/test split, with a verdict that carries its
    own evidence.

    Assignment is a pure function of the unit id: never random, never
    stateful. The same trade lands in the same arm across restarts, retries
    and processes, because an assignment that can change is an assignment
    that puts one trade in both arms and quietly poisons the comparison.
    """

    def __init__(self, name: str, config: Optional[ABConfig] = None,
                 store: Optional["GovernanceStore"] = None):
        self.name = name
        self.config = config or ABConfig()
        self.store = store
        self.state: Dict[str, Any] = self._empty_state()
        if self.store is not None:
            loaded = self.store.load_ab(self.name)
            if loaded:
                self.state.update(
                    {k: v for k, v in loaded.items() if k in self.state})
                saved_config = loaded.get("config")
                if isinstance(saved_config, Mapping):
                    for key, value in saved_config.items():
                        if hasattr(self.config, key):
                            setattr(self.config, key, value)

    @staticmethod
    def _empty_state() -> Dict[str, Any]:
        return {
            "control_wins": 0, "control_losses": 0, "control_profit": 0.0,
            "test_wins": 0, "test_losses": 0, "test_profit": 0.0,
            "total_trades": 0,
            "last_adjustment": None,
            "adjustment_history": [],
        }

    # -- assignment ---------------------------------------------------------

    def bucket(self, unit_id: Any) -> Optional[float]:
        """The unit's stable position in [0, 1), or None if it has no id."""
        if unit_id is None:
            return None
        algorithm = _HASHES.get(self.config.hash_algorithm, hashlib.sha256)
        digest = algorithm(str(unit_id).encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    def in_test(self, unit_id: Any) -> bool:
        """Is this unit in the test arm?"""
        if not self.config.enabled:
            # Disabled means the feature is simply on for everyone, matching
            # the existing behaviour in ai_adversarial: no experiment running,
            # so no control arm is being held back.
            return True
        position = self.bucket(unit_id)
        if position is None:
            return False
        return position < self.config.rollout

    def assign(self, unit_id: Any) -> str:
        return "test" if self.in_test(unit_id) else "control"

    # -- measurement --------------------------------------------------------

    def track(self, unit_id: Any, profit: float, outcome: int,
              arm: Optional[str] = None) -> Dict[str, Any]:
        """
        Record one SETTLED unit into its arm.

        `arm` may be supplied by a caller that knows which branch actually
        ran; otherwise it is recomputed, which is safe precisely because
        assignment is deterministic.
        """
        with _LOCK:
            if not self.config.enabled:
                return {"tracked": False, "reason": "ab_test_disabled"}
            arm = arm or self.assign(unit_id)
            if arm not in ("test", "control"):
                return {"tracked": False, "reason": "unknown_arm"}

            won = 1 if outcome == 1 else 0
            self.state[arm + "_wins"] += won
            self.state[arm + "_losses"] += 1 - won
            self.state[arm + "_profit"] += float(profit or 0.0)
            self.state["total_trades"] += 1

            if self.config.auto_adjust:
                self._adjust_rollout()
            self._persist()
            return {"tracked": True, "arm": arm}

    def _arm_totals(self, arm: str) -> int:
        return self.state[arm + "_wins"] + self.state[arm + "_losses"]

    def _adjust_rollout(self) -> None:
        control_total = self._arm_totals("control")
        test_total = self._arm_totals("test")
        if (control_total < self.config.min_samples
                or test_total < self.config.min_samples):
            return

        control_rate = self.state["control_wins"] / control_total
        test_rate = self.state["test_wins"] / test_total
        improvement = test_rate - control_rate

        if improvement < self.config.degradation_threshold:
            self.config.rollout = max(self.config.min_rollout,
                                      self.config.rollout * 0.5)
            kind = "reduce"
        elif improvement > self.config.improvement_threshold:
            self.config.rollout = min(self.config.max_rollout,
                                      self.config.rollout * 1.2)
            kind = "increase"
        else:
            return   # inside the noise band; no change is a valid conclusion

        adjustment = {
            "type": kind, "timestamp": _utc_now(),
            "new_rollout": self.config.rollout, "improvement": improvement,
            "control_samples": control_total, "test_samples": test_total,
        }
        self.state["last_adjustment"] = adjustment
        self.state["adjustment_history"] = (
            self.state["adjustment_history"] + [adjustment])[-50:]

    def set_rollout(self, rollout: float) -> float:
        with _LOCK:
            self.config.rollout = max(0.0, min(1.0, float(rollout)))
            self._persist()
            return self.config.rollout

    def reset(self) -> None:
        with _LOCK:
            self.state = self._empty_state()
            self._persist()

    def _persist(self) -> None:
        if self.store is not None:
            payload = dict(self.state)
            payload["config"] = asdict(self.config)
            self.store.save_ab(self.name, payload)

    # -- verdict ------------------------------------------------------------

    def results(self) -> Dict[str, Any]:
        """
        Current state plus an explicit verdict.

        `direction` and `significant` are separate fields on purpose. A caller
        that reads only TEST_BETTER and ships it has been told the sign of a
        difference, not whether the difference is real.
        """
        control_total = self._arm_totals("control")
        test_total = self._arm_totals("test")
        control_rate = (self.state["control_wins"] / control_total
                        if control_total else None)
        test_rate = (self.state["test_wins"] / test_total
                     if test_total else None)

        statistics = two_proportion_z_test(
            self.state["control_wins"], control_total,
            self.state["test_wins"], test_total)

        if control_rate is None or test_rate is None:
            direction, improvement, status = None, None, "INSUFFICIENT_DATA"
        else:
            improvement = test_rate - control_rate
            direction = ("TEST_BETTER" if improvement > 0
                         else "CONTROL_BETTER" if improvement < 0 else "EQUAL")
            if (control_total < self.config.min_samples
                    or test_total < self.config.min_samples):
                status = "INSUFFICIENT_DATA"
            elif improvement > self.config.improvement_threshold:
                status = "TEST_BETTER"
            elif improvement < self.config.degradation_threshold:
                status = "TEST_WORSE"
            else:
                status = "NO_DIFFERENCE"

        p_value = statistics["p_value"]
        significant = bool(p_value is not None
                           and p_value < self.config.alpha
                           and status != "INSUFFICIENT_DATA")

        return {
            "name": self.name,
            "enabled": self.config.enabled,
            "rollout": self.config.rollout,
            "hash_algorithm": self.config.hash_algorithm,
            "status": status,
            "direction": direction,
            "improvement": (round(improvement, 6)
                            if improvement is not None else None),
            "significant": significant,
            "p_value": p_value,
            "z": statistics["z"],
            "alpha": self.config.alpha,
            "min_samples": self.config.min_samples,
            "total_trades": self.state["total_trades"],
            "control": {
                "wins": self.state["control_wins"],
                "losses": self.state["control_losses"],
                "samples": control_total, "win_rate": control_rate,
                "profit": round(self.state["control_profit"], 4),
            },
            "test": {
                "wins": self.state["test_wins"],
                "losses": self.state["test_losses"],
                "samples": test_total, "win_rate": test_rate,
                "profit": round(self.state["test_profit"], 4),
            },
            "last_adjustment": self.state["last_adjustment"],
            # The only field an automated caller should act on.
            "verdict_is_actionable": bool(
                significant and status in ("TEST_BETTER", "TEST_WORSE")),
        }


# ---------------------------------------------------------------------------
# Versioned registry and rollback
# ---------------------------------------------------------------------------

@dataclass
class ModelVersion:
    version: str
    created_at: str
    payload_hash: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    promoted_at: Optional[str] = None
    retired_at: Optional[str] = None
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GovernanceStore:
    """
    Durable state for A/B tests and model versions.

    A local directory rather than Firebase. Firestore is the system of record
    for trades, but governance state must survive a Firebase outage: a
    rollback that cannot run because the database is unreachable is not a
    rollback. Writes are atomic (temp file then replace) so an interrupted
    write cannot leave a half-written registry that reads as corrupt.
    """

    def __init__(self, directory: Optional[str] = None):
        self.directory = directory or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ai_governance")
        os.makedirs(self.directory, exist_ok=True)

    def _path(self, kind: str, name: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return os.path.join(self.directory, kind + "_" + safe + ".json")

    def _write(self, path: str, payload: Any) -> None:
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        os.replace(temporary, path)

    def _read(self, path: str) -> Optional[Any]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            # A corrupt file is reported as absent rather than raising, so a
            # bad write cannot take the whole AI layer down on import.
            return None

    def save_ab(self, name: str, payload: Mapping[str, Any]) -> None:
        self._write(self._path("ab", name), dict(payload))

    def load_ab(self, name: str) -> Optional[Dict[str, Any]]:
        return self._read(self._path("ab", name))

    def save_registry(self, name: str, payload: Mapping[str, Any]) -> None:
        self._write(self._path("registry", name), dict(payload))

    def load_registry(self, name: str) -> Optional[Dict[str, Any]]:
        return self._read(self._path("registry", name))


class ModelRegistry:
    """
    Versioned model artifacts with a real rollback.

    Every model already had save() and load(). What was missing is the fact
    that makes rollback possible: which saved artifact was known to be good.
    A registry entry records the payload hash, the metrics it was promoted on
    and when -- so reverting is choosing a previously promoted version, not
    guessing at a filename.

    Rollback is deliberately conservative:
      * it refuses when there is no earlier promoted version to return to,
        rather than silently doing nothing and reporting success;
      * it records the reason, so the history says why the system is where
        it is;
      * it never deletes the version it rolled away from. A version that
        looked bad on 40 trades may be fine on 400, and destroying the
        artifact makes that unanswerable.
    """

    def __init__(self, name: str, store: Optional[GovernanceStore] = None):
        self.name = name
        self.store = store or GovernanceStore()
        data = self.store.load_registry(name) or {}
        self.versions: List[ModelVersion] = [
            ModelVersion(**entry) for entry in data.get("versions", [])
            if isinstance(entry, Mapping)
        ]
        self.active_version: Optional[str] = data.get("active_version")
        self.history: List[Dict[str, Any]] = data.get("history", [])

    # -- registration -------------------------------------------------------

    def register(self, payload: Any, metrics: Optional[Mapping[str, Any]] = None,
                 version: Optional[str] = None, notes: str = "",
                 source: str = "") -> ModelVersion:
        """Record a new artifact. Registering does NOT promote it."""
        with _LOCK:
            entry = ModelVersion(
                version=version or ("v" + str(len(self.versions) + 1)),
                created_at=_utc_now(),
                payload_hash=content_hash(payload),
                metrics=dict(metrics or {}),
                notes=notes,
                source=source,
            )
            self.versions.append(entry)
            self._record("register", entry.version, notes)
            self._persist()
            return entry

    def get(self, version: str) -> Optional[ModelVersion]:
        return next((v for v in self.versions if v.version == version), None)

    def active(self) -> Optional[ModelVersion]:
        return self.get(self.active_version) if self.active_version else None

    def promoted_versions(self) -> List[ModelVersion]:
        return [v for v in self.versions if v.promoted_at]

    # -- promotion and rollback --------------------------------------------

    def promote(self, version: str, reason: str = "") -> Dict[str, Any]:
        with _LOCK:
            entry = self.get(version)
            if entry is None:
                return {"promoted": False, "reason": "unknown_version:" + version}
            entry.promoted_at = _utc_now()
            entry.retired_at = None
            previous = self.active_version
            self.active_version = version
            self._record("promote", version, reason, previous=previous)
            self._persist()
            return {"promoted": True, "version": version, "previous": previous}

    def rollback(self, reason: str = "") -> Dict[str, Any]:
        """
        Return to the most recent previously promoted version.

        Refuses loudly when there is nothing to return to. A rollback that
        reports success while doing nothing is the worst possible outcome
        here: it is invoked precisely when someone believes production is
        broken.
        """
        with _LOCK:
            promoted = [v for v in self.promoted_versions()
                        if v.version != self.active_version]
            if not promoted:
                return {"rolled_back": False,
                        "reason": "no earlier promoted version to roll back to",
                        "active_version": self.active_version}

            promoted.sort(key=lambda v: v.promoted_at or "")
            target = promoted[-1]
            current = self.active()
            if current is not None:
                current.retired_at = _utc_now()
            previous = self.active_version
            self.active_version = target.version
            target.retired_at = None
            self._record("rollback", target.version, reason, previous=previous)
            self._persist()
            return {"rolled_back": True, "version": target.version,
                    "from_version": previous, "reason": reason}

    # -- bookkeeping --------------------------------------------------------

    def _record(self, action: str, version: str, reason: str,
                previous: Optional[str] = None) -> None:
        self.history.append({
            "action": action, "version": version, "previous": previous,
            "reason": reason, "timestamp": _utc_now(),
        })
        self.history = self.history[-200:]

    MAX_UNPROMOTED_VERSIONS = 50

    def _trim(self) -> None:
        """
        Bound the registry without ever discarding a promoted version.

        Every training run registers an attempt, so an unbounded list grows
        forever. Promoted versions are exempt from trimming because they are
        precisely the set rollback can return to -- trimming one would make a
        rollback target vanish, which is the one outcome this class exists to
        prevent.
        """
        unpromoted = [v for v in self.versions if not v.promoted_at]
        excess = len(unpromoted) - self.MAX_UNPROMOTED_VERSIONS
        if excess <= 0:
            return
        drop = {id(v) for v in unpromoted[:excess]}
        self.versions = [v for v in self.versions if id(v) not in drop]

    def _persist(self) -> None:
        self._trim()
        self.store.save_registry(self.name, {
            "name": self.name,
            "active_version": self.active_version,
            "versions": [v.to_dict() for v in self.versions],
            "history": self.history,
        })

    def status(self) -> Dict[str, Any]:
        active = self.active()
        return {
            "name": self.name,
            "governance_version": GOVERNANCE_VERSION,
            "versions": len(self.versions),
            "active_version": self.active_version,
            "active_metrics": active.metrics if active else None,
            "active_promoted_at": active.promoted_at if active else None,
            "promoted_versions": [v.version for v in self.promoted_versions()],
            "can_rollback": len([v for v in self.promoted_versions()
                                 if v.version != self.active_version]) > 0,
            "recent_history": self.history[-5:],
        }


# ---------------------------------------------------------------------------
# Registry of governed models
# ---------------------------------------------------------------------------

_REGISTRIES: Dict[str, ModelRegistry] = {}
_AB_TESTS: Dict[str, ABTest] = {}


def get_registry(name: str, store: Optional[GovernanceStore] = None
                 ) -> ModelRegistry:
    """
    Process-wide registry for a model, created on first use.

    An EXPLICIT store is always honoured and never cached. The earlier version
    returned the cached instance regardless, so passing a store silently got
    you someone else's -- first caller wins, and the argument you supplied was
    discarded without a word. That is a bad enough surprise in a test; in
    production it would mean a caller pointing at one directory and writing to
    another.
    """
    if store is not None:
        return ModelRegistry(name, store)
    with _LOCK:
        if name not in _REGISTRIES:
            _REGISTRIES[name] = ModelRegistry(name)
        return _REGISTRIES[name]


def get_ab_test(name: str, config: Optional[ABConfig] = None,
                store: Optional[GovernanceStore] = None) -> ABTest:
    """
    Process-wide A/B test for a model, created on first use.

    As with get_registry, an explicit store bypasses the cache rather than
    being quietly ignored.
    """
    if store is not None:
        return ABTest(name, config, store)
    with _LOCK:
        if name not in _AB_TESTS:
            _AB_TESTS[name] = ABTest(name, config, GovernanceStore())
        return _AB_TESTS[name]


def record_training(name: str, payload: Any,
                    metrics: Optional[Mapping[str, Any]] = None,
                    promoted: bool = False, notes: str = "",
                    store: Optional[GovernanceStore] = None) -> Dict[str, Any]:
    """
    Register one training attempt, and promote it only if it passed its gates.

    Called from every model's train_and_validate so that a rejected candidate
    is recorded too. Keeping the failures is the point: "this configuration
    was tried on this data and did not clear the noise floor" is exactly the
    fact that stops it being tried again in three months, and a registry of
    successes only cannot answer it.

    Registration never promotes on its own. The gates decide; this records.
    """
    registry = get_registry(name, store)
    version = registry.register(payload, metrics, notes=notes, source=name)
    outcome: Dict[str, Any] = {
        "registered_version": version.version,
        "promoted": False,
        "active_version": registry.active_version,
    }
    if promoted:
        promotion = registry.promote(
            version.version, notes or "passed promotion gates")
        outcome["promoted"] = bool(promotion.get("promoted"))
        outcome["previous_version"] = promotion.get("previous")
        outcome["active_version"] = registry.active_version
    outcome["can_rollback"] = registry.status()["can_rollback"]
    return outcome


# Every model with a version registry, and therefore a rollback.
GOVERNED_MODELS = (
    "exit_model", "target_model", "calibration_model", "abstention_model",
    "ai_reinforcement", "non_rl_intelligence", "ai_adversarial", "ai_gnn",
)

# The subset whose A/B state lives HERE. ai_adversarial and ai_gnn are absent
# on purpose: they carry their own A/B counters, and creating shared ones for
# them would produce a second, empty experiment reporting INSUFFICIENT_DATA
# beside a real one holding the actual arms -- two sources of truth for one
# question, which is worse than the duplication it was meant to remove. Their
# native state is delegated to instead; see the controller endpoints.
SHARED_AB_MODELS = (
    "exit_model", "target_model", "calibration_model", "abstention_model",
    "ai_reinforcement", "non_rl_intelligence",
)

NATIVE_AB_MODELS = ("ai_adversarial", "ai_gnn")


def reset_all(store: Optional[GovernanceStore] = None) -> None:
    """Drop cached instances. For tests and for reloading after a config change."""
    with _LOCK:
        _REGISTRIES.clear()
        _AB_TESTS.clear()


def get_status() -> Dict[str, Any]:
    """Governance state for every governed model."""
    return {
        "component": "model_governance",
        "governance_version": GOVERNANCE_VERSION,
        "governed_models": list(GOVERNED_MODELS),
        "shared_ab_models": list(SHARED_AB_MODELS),
        "native_ab_models": list(NATIVE_AB_MODELS),
        "ab_tests": {name: get_ab_test(name).results()
                     for name in SHARED_AB_MODELS},
        "registries": {name: get_registry(name).status()
                       for name in GOVERNED_MODELS},
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove assignment determinism, verdict honesty and that rollback rolls back.

    Every check here is a negative control as much as a positive one: an A/B
    split that cannot be shown to SPLIT, and a rollback that cannot be shown
    to MOVE the active version, are indistinguishable from stubs.
    """
    report: Dict[str, Any] = {
        "component": "model_governance", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            store = GovernanceStore(directory)

            experiment = ABTest("self_check", ABConfig(rollout=0.5), store)
            ids = ["trade-" + str(i) for i in range(400)]
            first = [experiment.assign(i) for i in ids]
            second = [experiment.assign(i) for i in ids]
            checks["assignment_deterministic"] = first == second
            in_test = sum(1 for arm in first if arm == "test")
            checks["assignment_splits"] = 0 < in_test < len(ids)
            checks["split_near_rollout"] = abs(in_test / len(ids) - 0.5) < 0.1

            # A verdict on a tiny sample must refuse to be actionable.
            for index in range(6):
                experiment.track(ids[index], 1.0, 1)
            thin = experiment.results()
            checks["thin_sample_not_actionable"] = (
                thin["status"] == "INSUFFICIENT_DATA"
                and not thin["verdict_is_actionable"])

            # Identical arms must not produce a significant verdict.
            balanced = ABTest("balanced", ABConfig(min_samples=10), store)
            for index in range(200):
                balanced.track("unit-" + str(index), 1.0, index % 2)
            null = balanced.results()
            checks["identical_arms_not_significant"] = not null["significant"]

            # Persistence must survive a new instance.
            reloaded = ABTest("balanced", ABConfig(min_samples=10), store)
            checks["state_persists"] = (
                reloaded.state["total_trades"] == balanced.state["total_trades"])

            # Rollback must actually move the active version.
            registry = ModelRegistry("self_check", store)
            first_version = registry.register({"w": 1}, {"auc": 0.6})
            registry.promote(first_version.version, "initial")
            second_version = registry.register({"w": 2}, {"auc": 0.4})
            registry.promote(second_version.version, "candidate")
            checks["active_is_latest"] = (
                registry.active_version == second_version.version)

            outcome = registry.rollback("self_check")
            checks["rollback_reports_success"] = bool(outcome["rolled_back"])
            checks["rollback_moves_active"] = (
                registry.active_version == first_version.version)
            checks["rollback_preserves_artifact"] = (
                registry.get(second_version.version) is not None)

            # And must refuse when there is nothing to roll back to.
            empty = ModelRegistry("empty", store)
            refusal = empty.rollback("nothing to do")
            checks["rollback_refuses_when_impossible"] = (
                refusal["rolled_back"] is False)

        report["ok"] = all(bool(value) for value in checks.values())
    except Exception as exc:
        report["error"] = str(type(exc).__name__) + ": " + str(exc)
    return report


__all__ = [
    "GOVERNANCE_VERSION", "GOVERNED_MODELS", "SHARED_AB_MODELS",
    "NATIVE_AB_MODELS",
    "ABConfig", "ABTest", "two_proportion_z_test",
    "GovernanceStore", "ModelRegistry", "ModelVersion",
    "get_ab_test", "get_registry", "reset_all", "record_training",
    "content_hash", "get_status", "self_check",
]
