"""Broker contract facts per symbol (read from MT5 symbol_info, cached in symbols.json)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).with_name("symbols.json")


@dataclass(frozen=True)
class SymbolFacts:
    symbol: str
    digits: int
    point: float
    usd_per_price_unit_per_lot: float
    volume_min: float
    volume_step: float
    commission_usd_per_lot_round_trip: float
    swap_long_points: float = 0.0
    swap_short_points: float = 0.0
    swap_mode: int = 1

    def commission_r(self, stop_distance: float) -> float:
        """Round-trip commission in R: independent of the lot, since R and commission both scale with it."""
        if stop_distance <= 0:
            raise ValueError("stop distance must be positive")
        return self.commission_usd_per_lot_round_trip / (stop_distance * self.usd_per_price_unit_per_lot)

    def swap_r_per_night(self, side: int, stop_distance: float) -> float:
        """Overnight swap in R for one night (mode 1: points per lot per night; lot-independent in R)."""
        if self.swap_mode != 1 or stop_distance <= 0:
            return 0.0
        pts = self.swap_long_points if side > 0 else self.swap_short_points
        return pts * self.point / stop_distance

    def risk_usd_at_min_lot(self, stop_distance: float) -> float:
        return stop_distance * self.usd_per_price_unit_per_lot * self.volume_min


def _read_json(attempts: int = 10) -> dict:
    import time
    for k in range(attempts):
        try:
            return json.loads(_PATH.read_text())
        except json.JSONDecodeError:      # another process is rewriting the file
            time.sleep(0.5)
    return json.loads(_PATH.read_text())


@lru_cache(maxsize=None)
def facts(symbol: str) -> SymbolFacts:
    data = _read_json()["symbols"][symbol]
    return SymbolFacts(symbol, int(data["digits"]), float(data["point"]),
                       float(data["usd_per_price_unit_per_lot"]), float(data["volume_min"]),
                       float(data["volume_step"]), float(data["commission_usd_per_lot_round_trip"]),
                       float(data.get("swap_long", 0.0)), float(data.get("swap_short", 0.0)), int(data.get("swap_mode", 1)))


def all_symbols() -> list[str]:
    return sorted(json.loads(_PATH.read_text())["symbols"])
