"""MOMENTUM: squeeze release (specs/categories/momentum.md)."""
from __future__ import annotations

import numpy as np

from engine_v2.data.clock import TF_SECONDS
from engine_v2.categories._common import base_context, rollover, secure_half
from engine_v2.market_model.location import room_to_opposing_level_r
from engine_v2.setup import Setup

CATEGORY = "MOMENTUM"
TF = "M15"
TFS = {"setup": "H4", "er": "D1", "context": "D1"}   # v2.1: the scale the rules were measured at
ROOM_MIN_R = 0.38               # v2.1: a release needs room to the next opposing D1 level
EXCLUDED_SESSIONS = ("NEW_YORK",)  # v2.1: late New York releases fail
PARTIAL_AT_R = 0.5               # v3: half off at +0.5R, breakeven, runner to the measured expansion
MOM_SQUEEZE_BARS = 6
ENTRY_VALID_BARS = 3
TIME_STOP_BARS = 48
MAX_STOP_ATR = 3.0


def propose(ctx, tfs: dict | None = None) -> list[Setup]:
    T = {**TFS, **(tfs or {})}
    tf = T["setup"]
    b = ctx.bars(tf)
    n = len(b)
    atr = ctx.atr(tf)
    bb_lo, bb_mid, bb_up = ctx.bollinger(tf)
    kc_lo, _, kc_up = ctx.keltner(tf)
    hist = ctx.macd_hist(tf)
    ema20 = ctx.ema(tf, 20)
    vwap = ctx.vwap_at_close(tf)
    er = ctx.efficiency_ratio(T["er"])
    with np.errstate(invalid="ignore"):
        squeeze = (bb_up < kc_up) & (bb_lo > kc_lo)
    out: list[Setup] = []
    run = 0
    for r in range(n):
        if squeeze[r]:
            run += 1
            continue
        run_len, run = run, 0
        if run_len < MOM_SQUEEZE_BARS:
            continue
        s0 = r - run_len
        a = float(atr[r])
        if not a > 0 or not np.isfinite(hist[r]) or not np.isfinite(ema20[r]):
            continue
        rng = b.high[r] - b.low[r]
        if rng < 1.0 * a:
            continue
        c = b.close[r]
        if hist[r] > 0 and c > ema20[r] and c > vwap[r]:
            d = 1
        elif hist[r] < 0 and c < ema20[r] and c < vwap[r]:
            d = -1
        else:
            continue
        created = int(b.close_time[r])
        if rollover(created, tf):
            continue
        sq_hi, sq_lo = float(b.high[s0:r].max()), float(b.low[s0:r].min())
        spread = float(b.spread[r])
        entry = (b.high[r] + spread) if d > 0 else (b.low[r] - spread)
        stop = (sq_lo - 0.10 * a) if d > 0 else (sq_hi + 0.10 * a)
        if (entry - stop) * d > MAX_STOP_ATR * a:
            stop = (sq_hi + sq_lo) / 2.0
        risk = (entry - stop) * d
        if risk <= 0:
            continue
        room = room_to_opposing_level_r(ctx, created, float(entry), risk, d)
        info = base_context(ctx, created, T["context"])
        if room < ROOM_MIN_R or info["session"] in EXCLUDED_SESSIONS:
            continue
        height = sq_hi - sq_lo
        t1 = entry + d * risk
        t2 = entry + d * max(2 * risk, 2 * height)
        i1 = ctx.last_closed_index(T["er"], created)
        info.update({"room_r": round(room, 3), "squeeze_bars": int(run_len), "er_h1": round(float(er[i1]), 3) if i1 >= 0 and np.isfinite(er[i1]) else None,
                     "risk_atr": round(risk / a, 3)})
        s = Setup(CATEGORY, "squeeze_release", ctx.symbol, tf, "BUY" if d > 0 else "SELL", created,
                  created + ENTRY_VALID_BARS * TF_SECONDS[tf], {"order_type": "STOP", "price": float(entry)},
                  {"price": float(stop), "reason": "beyond squeeze range"},
                  secure_half(float(entry), risk, d, {"price": float(t2), "reason": "measured expansion"}, PARTIAL_AT_R) if PARTIAL_AT_R else
                  [{"price": float(t1), "share": 0.5, "reason": "1R"}, {"price": float(t2), "share": 0.5, "reason": "measured expansion"}],
                  management={"breakeven_after_target": 1, "time_stop_bars": TIME_STOP_BARS, "trail": "bb_mid"},
                  thesis=[{"type": "close_beyond_series", "tf": tf, "series": "bb_mid",
                           "beyond": "below" if d > 0 else "above", "applies_to": "open", "after_target": 1}],
                  context=info,
                  location={"type": "squeeze_range", "high": sq_hi, "low": sq_lo},
                  trigger={"type": "squeeze_release", "bar_time": int(b.time[r])})
        try:
            out.append(s.validate())
        except ValueError:
            pass
    return out
