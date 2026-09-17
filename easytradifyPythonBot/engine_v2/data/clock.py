"""Broker clock: UTC+3 during US daylight saving, UTC+2 otherwise (IC Markets NY-close server time).

Broker epoch = UTC epoch + offset, so integer division by 86400 gives the broker trading day.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import numpy as np

DAY = 86400
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}

SESSION_HOURS = {"ASIA": (1, 9), "LONDON": (10, 18), "NEW_YORK": (15, 23)}
ROLLOVER_START_MIN = 23 * 60 + 55
ROLLOVER_END_MIN = 65


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


@lru_cache(maxsize=None)
def us_dst_bounds_utc(year: int) -> tuple[int, int]:
    """(start, end) UTC epochs of US daylight saving for `year`."""
    start = _nth_sunday(year, 3, 2).replace(hour=7)
    end = _nth_sunday(year, 11, 1).replace(hour=6)
    return int(start.timestamp()), int(end.timestamp())


def broker_offset_seconds(utc_epoch: int) -> int:
    year = datetime.fromtimestamp(int(utc_epoch), tz=timezone.utc).year
    start, end = us_dst_bounds_utc(year)
    return 3 * 3600 if start <= utc_epoch < end else 2 * 3600


def utc_to_broker(utc: np.ndarray) -> np.ndarray:
    utc = np.asarray(utc, dtype=np.int64)
    if utc.size == 0:
        return utc.copy()
    years = range(datetime.fromtimestamp(int(utc.min()), tz=timezone.utc).year,
                  datetime.fromtimestamp(int(utc.max()), tz=timezone.utc).year + 1)
    offset = np.full(utc.shape, 2 * 3600, dtype=np.int64)
    for y in years:
        s, e = us_dst_bounds_utc(y)
        offset[(utc >= s) & (utc < e)] = 3 * 3600
    return utc + offset


def broker_minute_of_day(broker_epoch: np.ndarray | int):
    return (np.asarray(broker_epoch) % DAY) // 60


def in_rollover(broker_epoch) -> np.ndarray:
    m = broker_minute_of_day(broker_epoch)
    return (m >= ROLLOVER_START_MIN) | (m < ROLLOVER_END_MIN)


def session_of(broker_epoch: int) -> str:
    h = int(broker_epoch % DAY) // 3600
    names = [name for name, (a, b) in SESSION_HOURS.items() if a <= h < b]
    return "+".join(names) if names else "OFF"
