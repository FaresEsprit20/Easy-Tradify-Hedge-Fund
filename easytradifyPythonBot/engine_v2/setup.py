"""The Setup contract (specs/setup_contract.md): the only object that can become a trade."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

CATEGORIES = ("TREND", "MOMENTUM", "MEAN_REVERSION", "STRUCTURE", "SMC", "ORDER_FLOW", "WAVE", "CROSS_ASSET")
ORDER_TYPES = ("LIMIT", "STOP", "MARKET")
STATUSES = ("PROPOSED", "PENDING", "FILLED", "MANAGED", "CLOSED", "EXPIRED", "CANCELLED", "NOT_TRADEABLE")


class InvalidSetup(ValueError):
    pass


@dataclass
class Setup:
    category: str
    variant: str
    symbol: str
    timeframe: str
    side: str
    created_at: int
    valid_until: int
    entry: dict
    stop: dict
    targets: list
    management: dict = field(default_factory=dict)
    thesis: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    location: dict = field(default_factory=dict)
    trigger: dict = field(default_factory=dict)
    probability: dict = field(default_factory=lambda: {"value": None, "n": 0, "low": None, "high": None})
    risk: dict = field(default_factory=dict)
    status: str = "PROPOSED"

    @property
    def id(self) -> str:
        return f"{self.category}:{self.symbol}:{self.variant}:{self.side}:{self.created_at}"

    @property
    def direction(self) -> int:
        return 1 if self.side == "BUY" else -1

    def validate(self) -> "Setup":
        if self.category not in CATEGORIES:
            raise InvalidSetup(f"unknown category {self.category}")
        if self.side not in ("BUY", "SELL"):
            raise InvalidSetup(f"bad side {self.side}")
        if self.entry.get("order_type") not in ORDER_TYPES:
            raise InvalidSetup(f"bad order type {self.entry.get('order_type')}")
        e, s = float(self.entry["price"]), float(self.stop["price"])
        d = self.direction
        if (e - s) * d <= 0:
            raise InvalidSetup(f"stop {s} is not on the losing side of entry {e} for {self.side}")
        if not self.targets:
            raise InvalidSetup("no targets")
        for t in self.targets:
            if (float(t["price"]) - e) * d <= 0:
                raise InvalidSetup(f"target {t['price']} is not on the winning side of entry {e}")
        if abs(sum(float(t["share"]) for t in self.targets) - 1.0) > 1e-6:
            raise InvalidSetup("target shares must sum to 1")
        if self.valid_until <= self.created_at:
            raise InvalidSetup("valid_until must be after created_at")
        return self

    def to_dict(self) -> dict:
        out = asdict(self)
        out["id"] = self.id
        return out
