"""
AI_MarketReplay — Standalone RL Entry-Timing Agent
Research/backtest only. No live order execution.
"""

from __future__ import annotations

import copy
import math
import os
import random
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    import numpy as np
except Exception:
    np = None

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except Exception:
    torch = None
    nn = None
    F = None
    TORCH_AVAILABLE = False


RL_VERSION = "5.0-standalone"
WAIT, ENTER, CANCEL = 0, 1, 2
ACTION_NAMES = {WAIT: "WAIT", ENTER: "ENTER", CANCEL: "CANCEL"}
NUM_ACTIONS = 3


@dataclass
class RLConfig:
    seed: int = 42
    max_history: int = 16
    max_features: int = 2048
    categorical_buckets: int = 256
    hidden_size: int = 384
    recurrent: bool = True
    recurrent_layers: int = 1
    dropout: float = 0.05
    temporal_model: str = "gru"
    attention_heads: int = 6
    transformer_layers: int = 2

    dueling: bool = True
    distributional: bool = True
    atoms: int = 51
    v_min: float = -5.0
    v_max: float = 5.0

    gamma: float = 0.995
    learning_rate: float = 2e-4
    min_learning_rate: float = 2e-5
    weight_decay: float = 1e-5
    grad_clip: float = 5.0
    gradient_steps: int = 1

    replay_capacity: int = 250_000
    batch_size: int = 128
    min_replay: int = 2048
    per_alpha: float = 0.6
    per_beta_start: float = 0.4
    per_beta_frames: int = 500_000
    per_epsilon: float = 1e-5

    n_step: int = 3
    target_tau: float = 0.005
    hard_target_every: int = 2000

    noisy_net: bool = True
    noise_std: float = 0.5
    epsilon_start: float = 0.10
    epsilon_final: float = 0.01
    epsilon_decay_frames: int = 100_000

    reward_clip: float = 5.0
    wait_cost: float = 0.002
    opportunity_cost: float = 0.02
    cancel_cost: float = 0.005
    invalidation_penalty: float = 0.75
    time_decay: float = 0.0005
    mae_penalty: float = 0.15
    mfe_bonus: float = 0.10
    slippage_bps: float = 0.5
    commission_bps: float = 0.0

    min_eval_episodes: int = 100
    min_enter_rate: float = 0.02
    max_enter_rate: float = 0.95
    min_profit_factor: float = 1.05
    max_drawdown: float = 0.25
    min_baseline_delta: float = 0.0

    device: str = "cuda" if TORCH_AVAILABLE and torch.cuda.is_available() else "cpu"


def seed_everything(seed: int = 42) -> None:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    if np is not None:
        np.random.seed(seed)
    if TORCH_AVAILABLE:
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def stable_bucket(value: str, buckets: int = 256) -> int:
    h = 2166136261
    for b in str(value).encode("utf-8", errors="replace"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h % max(1, buckets)


_FUTURE_KEYS = {
    "future", "future_data", "future_price", "future_prices",
    "outcome", "result", "label", "target", "mfe", "mae", "pnl",
    "profit", "loss", "tp_hit", "sl_hit", "future_return",
    "realized_return", "time_to_tp", "time_to_sl",
}


def _remove_future(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: _remove_future(v)
            for k, v in value.items()
            if str(k).lower() not in _FUTURE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_remove_future(v) for v in value]
    return value


def flatten_state(
    obj: Any,
    prefix: str = "",
    out: Optional[Dict[str, float]] = None,
    buckets: int = 256,
) -> Dict[str, float]:
    if out is None:
        out = {}
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flatten_state(value, path, out, buckets)
    elif isinstance(obj, bool):
        out[prefix] = 1.0 if obj else 0.0
    elif isinstance(obj, (int, float)):
        out[prefix] = safe_float(obj)
    elif np is not None and isinstance(obj, np.number):
        out[prefix] = safe_float(obj)
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            flatten_state(value, f"{prefix}[{i}]", out, buckets)
    elif obj is not None:
        out[f"__cat__.{prefix}.{stable_bucket(str(obj), buckets)}"] = 1.0
    return out


def sanitize_observation(
    snapshot: Mapping[str, Any],
    buckets: int = 256,
) -> Dict[str, float]:
    return flatten_state(_remove_future(snapshot), buckets=buckets)


class TemporalStateEncoder:
    """Leakage-safe fixed vocabulary + temporal derivatives."""

    def __init__(self, config: RLConfig):
        self.cfg = config
        self.feature_names: List[str] = []
        self.feature_to_idx: Dict[str, int] = {}

    @property
    def base_dim(self) -> int:
        return len(self.feature_names)

    @property
    def state_dim(self) -> int:
        return self.base_dim * 3

    def fit(self, snapshots: Sequence[Mapping[str, Any]]) -> "TemporalStateEncoder":
        counts: Dict[str, int] = {}
        for snapshot in snapshots:
            for name in sanitize_observation(
                snapshot, self.cfg.categorical_buckets
            ):
                counts[name] = counts.get(name, 0) + 1

        names = sorted(counts)
        if len(names) > self.cfg.max_features:
            names = sorted(
                sorted(names, key=lambda n: (-counts[n], n))[:self.cfg.max_features]
            )
        self.feature_names = names
        self.feature_to_idx = {n: i for i, n in enumerate(names)}
        return self

    def _vector(self, snapshot: Mapping[str, Any]) -> List[float]:
        values = sanitize_observation(snapshot, self.cfg.categorical_buckets)
        vec = [0.0] * self.base_dim
        for name, value in values.items():
            idx = self.feature_to_idx.get(name)
            if idx is not None:
                vec[idx] = safe_float(value)
        return vec

    def encode_history(
        self,
        snapshots: Sequence[Mapping[str, Any]],
        end_index: int,
    ) -> Any:
        if not self.feature_names:
            raise RuntimeError("Call fit() before encoding.")

        start = max(0, end_index - self.cfg.max_history + 1)
        rows = [self._vector(snapshots[i]) for i in range(start, end_index + 1)]
        rows = (
            [[0.0] * self.base_dim] *
            max(0, self.cfg.max_history - len(rows))
            + rows
        )

        encoded = []
        prev = [0.0] * self.base_dim
        prev_delta = [0.0] * self.base_dim

        for row in rows:
            delta = [a - b for a, b in zip(row, prev)]
            acceleration = [a - b for a, b in zip(delta, prev_delta)]
            encoded.append(row + delta + acceleration)
            prev, prev_delta = row, delta

        return (
            np.asarray(encoded, dtype=np.float32)
            if np is not None else encoded
        )

    def encode_current(self, snapshots, end_index):
        return self.encode_history(snapshots, end_index)


def _first(snapshot: Mapping[str, Any], keys, default=None):
    for key in keys:
        if key in snapshot and snapshot[key] is not None:
            return snapshot[key]
    return default


def extract_price(snapshot: Mapping[str, Any]) -> Optional[float]:
    x = safe_float(
        _first(
            snapshot,
            ("price", "close", "mid", "entry_price", "market_price", "last_price"),
        ),
        float("nan"),
    )
    return None if not math.isfinite(x) else x


def extract_direction(snapshot: Mapping[str, Any]) -> int:
    value = _first(snapshot, ("direction", "side", "signal_direction", "bias"), 1)
    if isinstance(value, str):
        s = value.upper().strip()
        if s in {"SELL", "SHORT", "BEAR", "BEARISH", "-1"}:
            return -1
        if s in {"BUY", "LONG", "BULL", "BULLISH", "1"}:
            return 1
    return -1 if safe_float(value, 1.0) < 0 else 1


def extract_sl_tp(snapshot: Mapping[str, Any]):
    sl = safe_float(_first(snapshot, ("stop_loss", "sl", "stopLoss")), float("nan"))
    tp = safe_float(_first(snapshot, ("take_profit", "tp", "takeProfit")), float("nan"))
    return (
        None if not math.isfinite(sl) else sl,
        None if not math.isfinite(tp) else tp,
    )


@dataclass
class EntryOutcome:
    entry_index: int
    entry_price: Optional[float]
    exit_index: Optional[int]
    exit_price: Optional[float]
    direction: int
    return_pct: float
    mfe_pct: float
    mae_pct: float
    duration: int
    tp_hit: bool
    sl_hit: bool
    invalidated: bool
    execution_cost_pct: float
    reward: float
    reason: str


class CounterfactualSimulator:
    """Simulates ENTER at one timestamp using only subsequent replay snapshots."""

    def __init__(self, config: Optional[RLConfig] = None):
        self.cfg = config or RLConfig()

    def simulate(
        self,
        snapshots: Sequence[Mapping[str, Any]],
        entry_index: int,
        horizon: Optional[int] = None,
    ) -> EntryOutcome:
        if not snapshots or not 0 <= entry_index < len(snapshots):
            raise ValueError("Invalid entry index.")

        entry = snapshots[entry_index]
        price = extract_price(entry)
        direction = extract_direction(entry)
        sl, tp = extract_sl_tp(entry)
        cost = (self.cfg.slippage_bps + self.cfg.commission_bps) / 100.0

        if price is None or price == 0:
            return EntryOutcome(
                entry_index, price, None, None, direction, 0, 0, 0, 0,
                False, False, True, cost, -self.cfg.invalidation_penalty,
                "missing_entry_price",
            )

        end = len(snapshots)
        if horizon is not None:
            end = min(end, entry_index + 1 + max(1, horizon))

        mfe, mae = 0.0, 0.0
        exit_index = None
        exit_price = None
        tp_hit = sl_hit = invalidated = False
        reason = "horizon_end"

        for i in range(entry_index + 1, end):
            p = extract_price(snapshots[i])
            if p is None:
                continue
            r = direction * (p - price) / abs(price) * 100.0
            mfe, mae = max(mfe, r), min(mae, r)

            if tp is not None and (
                (direction > 0 and p >= tp) or (direction < 0 and p <= tp)
            ):
                tp_hit, exit_index, exit_price, reason = True, i, p, "take_profit"
                break

            if sl is not None and (
                (direction > 0 and p <= sl) or (direction < 0 and p >= sl)
            ):
                sl_hit, exit_index, exit_price, reason = True, i, p, "stop_loss"
                break

            if bool(_first(
                snapshots[i],
                ("invalidated", "setup_invalidated", "signal_invalidated"),
                False,
            )):
                invalidated, exit_index, exit_price, reason = True, i, p, "invalidation"
                break

        if exit_price is None:
            exit_index = max(entry_index, end - 1)
            exit_price = extract_price(snapshots[exit_index]) or price

        final_return = direction * (exit_price - price) / abs(price) * 100.0
        duration = max(0, exit_index - entry_index)
        reward = (
            final_return / 100.0
            - cost / 100.0
            - self.cfg.time_decay * duration
            - abs(mae) * self.cfg.mae_penalty / 100.0
            + mfe * self.cfg.mfe_bonus / 100.0
        )
        if invalidated:
            reward -= self.cfg.invalidation_penalty
        reward = max(-self.cfg.reward_clip, min(self.cfg.reward_clip, reward))

        return EntryOutcome(
            entry_index, price, exit_index, exit_price, direction,
            final_return, mfe, mae, duration, tp_hit, sl_hit,
            invalidated, cost, reward, reason,
        )


@dataclass
class Transition:
    state: Any
    action: int
    reward: float
    next_state: Any
    done: bool
    next_mask: Tuple[bool, bool, bool]


class EntryTimingEnv:
    """WAIT advances one snapshot; ENTER evaluates its counterfactual; CANCEL ends."""

    def __init__(
        self,
        snapshots,
        encoder,
        simulator=None,
        config=None,
        start_index=0,
    ):
        if not snapshots:
            raise ValueError("snapshots cannot be empty")
        self.snapshots = list(snapshots)
        self.encoder = encoder
        self.cfg = config or RLConfig()
        self.simulator = simulator or CounterfactualSimulator(self.cfg)
        self.start_index = max(0, min(start_index, len(self.snapshots) - 1))
        self.index = self.start_index
        self.done = False

    def reset(self, start_index=None):
        if start_index is not None:
            self.start_index = max(
                0, min(int(start_index), len(self.snapshots) - 1)
            )
        self.index, self.done = self.start_index, False
        return self.encoder.encode_current(self.snapshots, self.index)

    def action_mask(self):
        return [self.index < len(self.snapshots) - 1, True, True]

    def step(self, action):
        if self.done:
            raise RuntimeError("Environment is done.")
        info = {"action": ACTION_NAMES[action], "index": self.index}

        if action == ENTER:
            outcome = self.simulator.simulate(self.snapshots, self.index)
            self.done = True
            info["outcome"] = outcome
            return self.encoder.encode_current(self.snapshots, self.index), outcome.reward, True, info

        if action == CANCEL:
            self.done = True
            return self.encoder.encode_current(self.snapshots, self.index), -self.cfg.cancel_cost, True, info

        if self.index >= len(self.snapshots) - 1:
            self.done = True
            return self.encoder.encode_current(self.snapshots, self.index), -self.cfg.wait_cost, True, info

        self.index += 1
        return (
            self.encoder.encode_current(self.snapshots, self.index),
            -self.cfg.wait_cost - self.cfg.opportunity_cost,
            False,
            info,
        )


class PrioritizedReplayBuffer:
    def __init__(self, capacity, alpha=0.6, epsilon=1e-5):
        self.capacity = int(capacity)
        self.alpha = alpha
        self.epsilon = epsilon
        self.buffer = []
        self.priorities = []
        self.position = 0

    def __len__(self):
        return len(self.buffer)

    def add(self, transition, priority=None):
        p = float(priority if priority is not None else (
            max(self.priorities) if self.priorities else 1.0
        ))
        p = max(self.epsilon, p)
        if len(self.buffer) < self.capacity:
            self.buffer.append(transition)
            self.priorities.append(p)
        else:
            self.buffer[self.position] = transition
            self.priorities[self.position] = p
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size, beta):
        if len(self.buffer) < batch_size:
            raise ValueError("Not enough transitions.")
        if np is None:
            weights = [p ** self.alpha for p in self.priorities]
            indices = random.choices(
                range(len(self.buffer)), weights=weights, k=batch_size
            )
            return [self.buffer[i] for i in indices], [1.0] * batch_size, indices

        p = np.asarray(self.priorities, dtype=np.float64) ** self.alpha
        p /= p.sum()
        indices = np.random.choice(
            len(self.buffer), batch_size, replace=len(self.buffer) < batch_size, p=p
        )
        weights = (len(self.buffer) * p[indices]) ** (-beta)
        weights /= max(weights.max(), 1e-12)
        return [self.buffer[int(i)] for i in indices], weights.astype(np.float32), indices.tolist()

    def update_priorities(self, indices, priorities):
        for i, p in zip(indices, priorities):
            self.priorities[i] = max(self.epsilon, float(p))


class NStepAccumulator:
    def __init__(self, n_step, gamma):
        self.n_step = max(1, int(n_step))
        self.gamma = gamma
        self.queue = deque()

    def push(self, transition):
        self.queue.append(transition)
        out = []
        if len(self.queue) >= self.n_step:
            out.append(self._build())
            self.queue.popleft()
        if transition.done:
            while self.queue:
                out.append(self._build())
                self.queue.popleft()
        return out

    def _build(self):
        reward, next_state, done = 0.0, self.queue[0].next_state, False
        for k, item in enumerate(self.queue):
            reward += (self.gamma ** k) * item.reward
            next_state, done = item.next_state, item.done
            if done or k + 1 >= self.n_step:
                break
        last = self.queue[min(len(self.queue), self.n_step) - 1]
        first = self.queue[0]
        return Transition(
            first.state, first.action, reward, next_state, done, last.next_mask
        )

    def clear(self):
        self.queue.clear()


if TORCH_AVAILABLE:
    class NoisyLinear(nn.Module):
        def __init__(self, in_features, out_features, sigma0=0.5):
            super().__init__()
            self.in_features = in_features
            self.out_features = out_features
            self.weight_mu = nn.Parameter(torch.empty(out_features, in_features))
            self.weight_sigma = nn.Parameter(torch.empty(out_features, in_features))
            self.bias_mu = nn.Parameter(torch.empty(out_features))
            self.bias_sigma = nn.Parameter(torch.empty(out_features))
            self.register_buffer("weight_epsilon", torch.empty(out_features, in_features))
            self.register_buffer("bias_epsilon", torch.empty(out_features))
            self.sigma0 = sigma0
            self.reset_parameters()
            self.reset_noise()

        def reset_parameters(self):
            r = 1.0 / math.sqrt(self.in_features)
            self.weight_mu.data.uniform_(-r, r)
            self.bias_mu.data.uniform_(-r, r)
            s = self.sigma0 / math.sqrt(self.in_features)
            self.weight_sigma.data.fill_(s)
            self.bias_sigma.data.fill_(s)

        @staticmethod
        def _scale_noise(size, device):
            x = torch.randn(size, device=device)
            return x.sign() * x.abs().sqrt()

        def reset_noise(self):
            a = self._scale_noise(self.in_features, self.weight_mu.device)
            b = self._scale_noise(self.out_features, self.weight_mu.device)
            self.weight_epsilon.copy_(b.outer(a))
            self.bias_epsilon.copy_(b)

        def forward(self, x):
            if self.training:
                w = self.weight_mu + self.weight_sigma * self.weight_epsilon
                b = self.bias_mu + self.bias_sigma * self.bias_epsilon
            else:
                w, b = self.weight_mu, self.bias_mu
            return F.linear(x, w, b)


    class DuelingQNetwork(nn.Module):
        def __init__(self, input_dim, cfg):
            super().__init__()
            self.cfg = cfg
            h = cfg.hidden_size
            self.encoder = nn.Sequential(
                nn.LayerNorm(input_dim),
                nn.Linear(input_dim, h),
                nn.GELU(),
                nn.Dropout(cfg.dropout),
                nn.Linear(h, h),
                nn.GELU(),
            )

            if cfg.recurrent and cfg.temporal_model.lower() == "gru":
                self.temporal = nn.GRU(
                    h, h, num_layers=cfg.recurrent_layers, batch_first=True,
                    dropout=cfg.dropout if cfg.recurrent_layers > 1 else 0.0,
                )
                self.temporal_kind = "gru"
            elif cfg.recurrent and cfg.temporal_model.lower() == "transformer":
                if h % cfg.attention_heads:
                    raise ValueError("hidden_size must be divisible by attention_heads")
                layer = nn.TransformerEncoderLayer(
                    d_model=h, nhead=cfg.attention_heads, dim_feedforward=h * 4,
                    dropout=cfg.dropout, batch_first=True, activation="gelu",
                    norm_first=True,
                )
                self.temporal = nn.TransformerEncoder(layer, cfg.transformer_layers)
                self.temporal_kind = "transformer"
            else:
                self.temporal = None
                self.temporal_kind = "none"

            atoms = cfg.atoms if cfg.distributional else 1
            Linear = NoisyLinear if cfg.noisy_net else nn.Linear
            kw = {"sigma0": cfg.noise_std} if cfg.noisy_net else {}

            if cfg.dueling:
                self.value = nn.Sequential(
                    Linear(h, h, **kw), nn.GELU(), Linear(h, atoms, **kw)
                )
                self.advantage = nn.Sequential(
                    Linear(h, h, **kw), nn.GELU(),
                    Linear(h, NUM_ACTIONS * atoms, **kw)
                )
            else:
                self.head = nn.Sequential(
                    Linear(h, h, **kw), nn.GELU(),
                    Linear(h, NUM_ACTIONS * atoms, **kw)
                )

        def reset_noise(self):
            if not self.cfg.noisy_net:
                return
            for m in self.modules():
                if isinstance(m, NoisyLinear):
                    m.reset_noise()

        def forward(self, x):
            z = self.encoder(x)
            if self.temporal is not None:
                z = self.temporal(z)[0] if self.temporal_kind == "gru" else self.temporal(z)
            z = z[:, -1, :]
            a = self.cfg.atoms if self.cfg.distributional else 1
            if self.cfg.dueling:
                v = self.value(z).unsqueeze(1)
                adv = self.advantage(z).view(z.size(0), NUM_ACTIONS, a)
                q = v + adv - adv.mean(1, keepdim=True)
            else:
                q = self.head(z).view(z.size(0), NUM_ACTIONS, a)
            return q


@dataclass
class TrainStats:
    train_steps: int = 0
    frame: int = 0
    last_loss: float = 0.0
    loss_ema: float = 0.0


if TORCH_AVAILABLE:
    class RLAgent:
        """Standalone Double-DQN/C51/PER/n-step/NoisyNet entry-timing agent."""

        def __init__(self, state_dim, config=None):
            self.cfg = config or RLConfig()
            seed_everything(self.cfg.seed)
            self.state_dim = int(state_dim)
            self.device = torch.device(self.cfg.device)
            self.online = DuelingQNetwork(self.state_dim, self.cfg).to(self.device)
            self.target = copy.deepcopy(self.online).to(self.device)
            self.target.eval()
            self.optimizer = torch.optim.AdamW(
                self.online.parameters(),
                lr=self.cfg.learning_rate,
                weight_decay=self.cfg.weight_decay,
            )
            self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                self.optimizer,
                T_max=max(1, self.cfg.epsilon_decay_frames),
                eta_min=self.cfg.min_learning_rate,
            )
            self.replay = PrioritizedReplayBuffer(
                self.cfg.replay_capacity, self.cfg.per_alpha, self.cfg.per_epsilon
            )
            self.n_step = NStepAccumulator(self.cfg.n_step, self.cfg.gamma)
            self.stats = TrainStats()
            self.atom_support = torch.linspace(
                self.cfg.v_min, self.cfg.v_max, self.cfg.atoms, device=self.device
            )

        def _epsilon(self):
            f = min(1.0, self.stats.frame / max(1, self.cfg.epsilon_decay_frames))
            return self.cfg.epsilon_start + f * (self.cfg.epsilon_final - self.cfg.epsilon_start)

        def _beta(self):
            f = min(1.0, self.stats.frame / max(1, self.cfg.per_beta_frames))
            return self.cfg.per_beta_start + f * (1.0 - self.cfg.per_beta_start)

        def _q_values(self, states):
            raw = self.online(states)
            if self.cfg.distributional:
                return (F.softmax(raw, -1) * self.atom_support.view(1, 1, -1)).sum(-1)
            return raw

        def act(self, state, action_mask=(True, True, True), explore=True):
            tensor = torch.as_tensor(state, dtype=torch.float32, device=self.device)
            if tensor.ndim == 2:
                tensor = tensor.unsqueeze(0)
            if explore and self.cfg.noisy_net:
                self.online.reset_noise()
            if explore and random.random() < self._epsilon():
                valid = [i for i, ok in enumerate(action_mask) if ok]
                return random.choice(valid)
            self.online.eval()
            with torch.no_grad():
                q = self._q_values(tensor)[0]
            self.online.train()
            mask = torch.as_tensor(action_mask, dtype=torch.bool, device=self.device)
            return int(q.masked_fill(~mask, -torch.inf).argmax().item())

        def remember(self, transition):
            for t in self.n_step.push(transition):
                self.replay.add(t)

        def finish_episode(self):
            self.n_step.clear()

        def _project_c51(self, next_dist, rewards, dones):
            n = self.cfg.atoms
            dz = (self.cfg.v_max - self.cfg.v_min) / (n - 1)
            tz = (
                rewards[:, None]
                + (1.0 - dones[:, None]) * (self.cfg.gamma ** self.cfg.n_step)
                * self.atom_support[None, :]
            ).clamp(self.cfg.v_min, self.cfg.v_max)
            b = (tz - self.cfg.v_min) / dz
            lo, hi = b.floor().long(), b.ceil().long()
            proj = torch.zeros_like(next_dist)
            offset = torch.arange(next_dist.size(0), device=self.device)[:, None] * n
            lo_w = (hi.float() - b)
            hi_w = (b - lo.float())
            same = hi == lo
            lo_w = torch.where(same, torch.ones_like(lo_w), lo_w)
            hi_w = torch.where(same, torch.zeros_like(hi_w), hi_w)
            proj.view(-1).index_add_(0, (lo + offset).reshape(-1), (next_dist * lo_w).reshape(-1))
            proj.view(-1).index_add_(0, (hi + offset).reshape(-1), (next_dist * hi_w).reshape(-1))
            return proj

        def train_step(self):
            if len(self.replay) < self.cfg.min_replay:
                return None

            transitions, weights, indices = self.replay.sample(
                self.cfg.batch_size, self._beta()
            )
            states = torch.as_tensor(
                np.asarray([t.state for t in transitions], dtype=np.float32)
                if np is not None else [t.state for t in transitions],
                dtype=torch.float32, device=self.device
            )
            next_states = torch.as_tensor(
                np.asarray([t.next_state for t in transitions], dtype=np.float32)
                if np is not None else [t.next_state for t in transitions],
                dtype=torch.float32, device=self.device
            )
            actions = torch.as_tensor([t.action for t in transitions], dtype=torch.long, device=self.device)
            rewards = torch.as_tensor([t.reward for t in transitions], dtype=torch.float32, device=self.device)
            dones = torch.as_tensor([t.done for t in transitions], dtype=torch.float32, device=self.device)
            masks = torch.as_tensor([t.next_mask for t in transitions], dtype=torch.bool, device=self.device)
            weights = torch.as_tensor(weights, dtype=torch.float32, device=self.device)

            if self.cfg.noisy_net:
                self.online.reset_noise()
                self.target.reset_noise()

            raw = self.online(states)

            with torch.no_grad():
                next_q = self._q_values(next_states).masked_fill(~masks, -torch.inf)
                next_actions = next_q.argmax(1)
                target_raw = self.target(next_states)

            if self.cfg.distributional:
                log_probs = F.log_softmax(raw, -1)
                chosen = log_probs[torch.arange(states.size(0), device=self.device), actions]
                with torch.no_grad():
                    target_probs = F.softmax(target_raw, -1)
                    next_dist = target_probs[
                        torch.arange(states.size(0), device=self.device), next_actions
                    ]
                    projected = self._project_c51(next_dist, rewards, dones)
                per_loss = -(projected * chosen).sum(1)
            else:
                q = raw.gather(1, actions[:, None]).squeeze(1)
                with torch.no_grad():
                    tq = target_raw.gather(1, next_actions[:, None]).squeeze(1)
                    target = rewards + (1.0 - dones) * (self.cfg.gamma ** self.cfg.n_step) * tq
                per_loss = F.smooth_l1_loss(q, target, reduction="none")

            loss = (per_loss * weights).mean()
            self.optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(self.online.parameters(), self.cfg.grad_clip)
            self.optimizer.step()
            self.scheduler.step()

            self.stats.train_steps += 1
            self.stats.frame += 1
            value = float(loss.detach().cpu())
            self.stats.last_loss = value
            self.stats.loss_ema = value if self.stats.loss_ema == 0 else (
                0.99 * self.stats.loss_ema + 0.01 * value
            )
            self.replay.update_priorities(
                indices,
                (per_loss.detach().cpu().numpy() + self.cfg.per_epsilon).tolist()
                if np is not None else [float(x) + self.cfg.per_epsilon for x in per_loss.detach().cpu()]
            )
            self._update_target()
            return value

        def _update_target(self):
            if self.stats.train_steps % max(1, self.cfg.hard_target_every) == 0:
                self.target.load_state_dict(self.online.state_dict())
                return
            tau = self.cfg.target_tau
            with torch.no_grad():
                for t, o in zip(self.target.parameters(), self.online.parameters()):
                    t.data.mul_(1.0 - tau).add_(tau * o.data)

        def train_environment(self, env, episodes, start_indices=None):
            losses, episode_rewards = [], []
            for ep in range(int(episodes)):
                start = (
                    start_indices[ep % len(start_indices)]
                    if start_indices else random.randrange(max(1, len(env.snapshots) - 1))
                )
                state = env.reset(start)
                done, total = False, 0.0
                while not done:
                    action = self.act(state, env.action_mask(), explore=True)
                    nxt, reward, done, _ = env.step(action)
                    self.remember(Transition(
                        state, action, reward, nxt, done, tuple(env.action_mask())
                    ))
                    state, total = nxt, total + reward
                    for _ in range(max(1, self.cfg.gradient_steps)):
                        loss = self.train_step()
                        if loss is not None:
                            losses.append(loss)
                self.finish_episode()
                episode_rewards.append(total)
            return {
                "episodes": int(episodes),
                "mean_episode_reward": sum(episode_rewards) / max(1, len(episode_rewards)),
                "mean_loss": sum(losses) / len(losses) if losses else None,
                "train_steps": self.stats.train_steps,
                "frame": self.stats.frame,
            }

        def save(self, path, encoder=None):
            payload = {
                "rl_version": RL_VERSION,
                "config": asdict(self.cfg),
                "state_dim": self.state_dim,
                "stats": asdict(self.stats),
                "online": self.online.state_dict(),
                "target": self.target.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "scheduler": self.scheduler.state_dict(),
            }
            if encoder is not None:
                payload["encoder"] = {"feature_names": encoder.feature_names}
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            torch.save(payload, path)

        @classmethod
        def load(cls, path, config_override=None, map_location=None):
            payload = torch.load(
                path, map_location=map_location or "cpu", weights_only=False
            )
            if payload.get("rl_version") != RL_VERSION:
                raise ValueError("Incompatible RL checkpoint version.")
            cfg = config_override or RLConfig(**payload["config"])
            agent = cls(payload["state_dim"], cfg)
            agent.online.load_state_dict(payload["online"])
            agent.target.load_state_dict(payload["target"])
            agent.optimizer.load_state_dict(payload["optimizer"])
            agent.scheduler.load_state_dict(payload["scheduler"])
            agent.stats = TrainStats(**payload.get("stats", {}))
            encoder = None
            if "encoder" in payload:
                encoder = TemporalStateEncoder(cfg)
                encoder.feature_names = list(payload["encoder"]["feature_names"])
                encoder.feature_to_idx = {n: i for i, n in enumerate(encoder.feature_names)}
            return agent, encoder


else:
    class RLAgent:
        def __init__(self, *args, **kwargs):
            raise ImportError("PyTorch is required for RLAgent.")


@dataclass
class EvaluationReport:
    episodes: int
    enters: int
    enter_rate: float
    rewards: List[float]
    returns_pct: List[float]
    mean_reward: float
    mean_return_pct: float
    profit_factor: float
    max_drawdown: float
    invalidated_rate: float
    baseline_mean_return_pct: Optional[float]
    baseline_delta_pct: Optional[float]
    passed: bool
    failure_reasons: List[str] = field(default_factory=list)


def profit_factor(returns_pct):
    gains = sum(x for x in returns_pct if x > 0)
    losses = abs(sum(x for x in returns_pct if x < 0))
    return (float("inf") if gains > 0 else 0.0) if losses <= 1e-12 else gains / losses


def max_drawdown(returns_pct):
    equity, peak, dd = 1.0, 1.0, 0.0
    for r in returns_pct:
        equity *= 1.0 + safe_float(r) / 100.0
        peak = max(peak, equity)
        dd = max(dd, (peak - equity) / peak)
    return dd


def chronological_split(snapshots, train_ratio=0.70, validation_ratio=0.15):
    n = len(snapshots)
    if n < 3:
        raise ValueError("At least 3 snapshots are required.")
    a = max(1, int(n * train_ratio))
    b = min(n - 1, max(a + 1, int(n * (train_ratio + validation_ratio))))
    return list(snapshots[:a]), list(snapshots[a:b]), list(snapshots[b:])


def build_encoder(train_snapshots, config=None):
    return TemporalStateEncoder(config or RLConfig()).fit(train_snapshots)


def build_environment(snapshots, encoder, config=None, start_index=0):
    cfg = config or RLConfig()
    return EntryTimingEnv(
        snapshots, encoder, CounterfactualSimulator(cfg), cfg, start_index
    )


def evaluate_agent(
    agent,
    snapshots,
    encoder,
    config=None,
    starts=None,
    baseline_entries=None,
):
    cfg = config or RLConfig()
    starts = list(starts) if starts is not None else list(range(max(0, len(snapshots) - 1)))
    sim = CounterfactualSimulator(cfg)
    rewards, returns = [], []
    enters = invalidated = 0

    for start in starts:
        env = build_environment(snapshots, encoder, cfg, start)
        state = env.reset()
        total = 0.0
        for _ in range(len(snapshots) + 1):
            action = agent.act(state, env.action_mask(), explore=False)
            nxt, reward, done, info = env.step(action)
            total += reward
            state = nxt
            if done:
                outcome = info.get("outcome")
                if outcome is not None:
                    enters += 1
                    returns.append(outcome.return_pct)
                    invalidated += int(outcome.invalidated)
                break
        rewards.append(total)

    baseline_mean = None
    if baseline_entries:
        vals = [
            sim.simulate(snapshots, int(i)).return_pct
            for i in baseline_entries if 0 <= int(i) < len(snapshots)
        ]
        if vals:
            baseline_mean = sum(vals) / len(vals)

    enter_rate = enters / max(1, len(starts))
    mean_reward = sum(rewards) / max(1, len(rewards))
    mean_return = sum(returns) / max(1, len(returns)) if returns else 0.0
    pf = profit_factor(returns)
    dd = max_drawdown(returns)
    delta = None if baseline_mean is None else mean_return - baseline_mean

    reasons = []
    if len(starts) < cfg.min_eval_episodes:
        reasons.append("not_enough_evaluation_episodes")
    if enter_rate < cfg.min_enter_rate:
        reasons.append("enter_rate_too_low")
    if enter_rate > cfg.max_enter_rate:
        reasons.append("enter_rate_too_high")
    if returns and pf < cfg.min_profit_factor:
        reasons.append("profit_factor_below_gate")
    if dd > cfg.max_drawdown:
        reasons.append("drawdown_above_gate")
    if delta is not None and delta < cfg.min_baseline_delta:
        reasons.append("below_baseline")

    return EvaluationReport(
        len(starts), enters, enter_rate, rewards, returns,
        mean_reward, mean_return, pf, dd,
        invalidated / max(1, enters),
        baseline_mean, delta, not reasons, reasons,
    )


def train_from_replay(train_snapshots, config=None, episodes=1000):
    cfg = config or RLConfig()
    seed_everything(cfg.seed)
    encoder = build_encoder(train_snapshots, cfg)
    if not TORCH_AVAILABLE:
        raise ImportError("PyTorch is required for training.")
    agent = RLAgent(encoder.state_dim, cfg)
    env = build_environment(train_snapshots, encoder, cfg)
    stats = agent.train_environment(env, episodes)
    return agent, encoder, stats


def get_status(agent=None, encoder=None) -> Dict[str, Any]:
    """
    Verification surface for the RL layer.

    Reports what is actually available rather than what is configured, so a
    caller can distinguish "RL is off" from "RL is on but torch is missing and
    nothing has been trained" -- states that otherwise look identical from
    outside.
    """
    cfg = RLConfig()
    return {
        "component": "reinforcement_learning",
        "version": RL_VERSION,
        "torch_available": TORCH_AVAILABLE,
        "device": cfg.device if TORCH_AVAILABLE else None,
        "trainable": TORCH_AVAILABLE,
        "agent_loaded": agent is not None,
        "encoder_fitted": bool(encoder and getattr(encoder, "feature_names", None)),
        "feature_count": len(getattr(encoder, "feature_names", []) or []),
        "state_dim": getattr(encoder, "state_dim", None),
        "actions": list(ACTION_NAMES),
        "promotion_gates": {
            "min_profit_factor": cfg.min_profit_factor,
            "min_baseline_delta": cfg.min_baseline_delta,
            "max_drawdown": cfg.max_drawdown,
        },
        "seed": cfg.seed,
    }


def self_check(trades=None, bridge=None) -> Dict[str, Any]:
    """
    Prove the trade -> snapshot path works on real data, without training.

    Returns `ok` plus the reason it is not, rather than raising: this is meant
    to be safe to call from a health endpoint.
    """
    report = {"component": "reinforcement_learning", "ok": False, "checks": {}}
    try:
        sequences = snapshots_from_trades(trades or [], bridge)
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["sequences_built"] = len(sequences)
        report["checks"]["never_concatenated"] = all(
            len(s) >= 2 for s in sequences
        )
        priced = [
            extract_price(snapshot) is not None
            for sequence in sequences for snapshot in sequence
        ]
        report["checks"]["all_snapshots_priced"] = all(priced) if priced else None
        report["checks"]["snapshots_total"] = len(priced)
        # "No sequences" means these trades carried no usable price path,
        # not that the module is broken. Reported as unknown, with the
        # reason, rather than as a failure.
        if not sequences:
            # Unreadable input is a failure of the data path and must fail the
            # gate; readable input that simply yields no sequence is not
            # exercised. Collapsing the two either hides a broken decode or
            # condemns a healthy module on thin data.
            from .price_evolution_bridge import count_usable_trades
            usable = count_usable_trades(trades or [])
            report["checks"]["usable_trades"] = usable
            if trades and usable == 0:
                report["ok"] = False
                report["reason"] = ("no supplied trade could be decoded; the "
                                    "data path, not the model, is the problem")
            else:
                report["ok"] = None
                report["reason"] = "no trade yielded a usable snapshot sequence"
        else:
            report["ok"] = all(priced)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def snapshots_from_trades(trades, bridge=None):
    """
    Stored Firebase trades -> ONE snapshot sequence PER trade.

    Returns a list of sequences, deliberately NOT a single concatenated list.
    CounterfactualSimulator.simulate() walks forward from an entry index to
    the end of whatever list it is given, so a concatenated feed would let an
    entry in one trade be "resolved" against the price path of the next --
    a different symbol, at a different time, days later. The returns that
    come back from that are fabricated, and nothing downstream could tell,
    because they look like perfectly ordinary numbers.

    Each sequence is T0 (the opening decision) followed by one snapshot per
    price_evolution point, fully decoded -- see PriceEvolutionBridge.
    """
    if bridge is None:
        from .price_evolution_bridge import PriceEvolutionBridge
        bridge = PriceEvolutionBridge()

    sequences = []
    for trade in trades or []:
        try:
            sequence = bridge.to_snapshots(trade)
        except Exception:
            continue
        # An entry with nothing after it cannot be walked forward, so it
        # carries no training signal.
        if len(sequence) >= 2:
            sequences.append(sequence)
    return sequences


def train_from_trades(trades, config=None, episodes_per_trade=50, bridge=None):
    """
    Train the entry-timing agent across many stored trades.

    One environment per trade so no episode crosses a trade boundary. The
    encoder is fitted on the pooled snapshots because it only needs the
    feature vocabulary, which is shared; the environments stay separate
    because the price paths are not.
    """
    cfg = config or RLConfig()
    seed_everything(cfg.seed)

    sequences = snapshots_from_trades(trades, bridge)
    if not sequences:
        raise ValueError("No trade produced a usable snapshot sequence.")
    if not TORCH_AVAILABLE:
        raise ImportError("PyTorch is required for training.")

    pooled = [snapshot for sequence in sequences for snapshot in sequence]
    encoder = build_encoder(pooled, cfg)
    agent = RLAgent(encoder.state_dim, cfg)

    stats = {"trades": len(sequences), "snapshots": len(pooled), "per_trade": []}
    for sequence in sequences:
        env = build_environment(sequence, encoder, cfg)
        stats["per_trade"].append(agent.train_environment(env, episodes_per_trade))

    return agent, encoder, stats


def smoke_test():
    cfg = RLConfig(
        max_history=4, max_features=64, hidden_size=96,
        attention_heads=4, transformer_layers=1,
        replay_capacity=1000, batch_size=4, min_replay=4,
    )
    snapshots = [
        {
            "timestamp": i,
            "price": p,
            "direction": 1,
            "features": {
                "microstructure": {"delta": i * 0.1},
                "vwap": {"distance": i * 0.02},
                "fvg": {"state": "ACTIVE" if i < 5 else "FILLED"},
                "future_return": 9999,
            },
        }
        for i, p in enumerate([100, 100.1, 100.2, 100.6, 100.8, 100.5, 101.0])
    ]
    encoder = build_encoder(snapshots[:5], cfg)
    clean = sanitize_observation(snapshots[0], cfg.categorical_buckets)
    assert not any("future_return" in k for k in clean)
    outcome = CounterfactualSimulator(cfg).simulate(snapshots, 0)
    env = build_environment(snapshots, encoder, cfg, 0)
    state = env.reset()
    result = {
        "rl_version": RL_VERSION,
        "state_shape": list(state.shape) if np is not None else [len(state), len(state[0])],
        "counterfactual_return_pct": outcome.return_pct,
        "torch_available": TORCH_AVAILABLE,
    }
    if TORCH_AVAILABLE:
        agent = RLAgent(encoder.state_dim, cfg)
        result["sample_action"] = ACTION_NAMES[agent.act(state, env.action_mask(), False)]
    return result


__all__ = [
    "RL_VERSION", "WAIT", "ENTER", "CANCEL", "ACTION_NAMES", "RLConfig",
    "TemporalStateEncoder", "EntryOutcome", "CounterfactualSimulator",
    "EntryTimingEnv", "Transition", "PrioritizedReplayBuffer",
    "NStepAccumulator", "NoisyLinear", "DuelingQNetwork", "RLAgent",
    "EvaluationReport", "chronological_split", "build_encoder",
    "build_environment", "evaluate_agent", "train_from_replay",
    "snapshots_from_trades", "train_from_trades",
    "get_status", "self_check",
    "profit_factor", "max_drawdown", "smoke_test",
]
