"""Tick-accurate replay of one Setup on bid/ask M1 bars (rules in specs/setup_contract.md).

BUY fills on the ask and exits on the bid; SELL fills on the bid and exits on the ask. Within one M1
bar the stop is assumed to come before any target. Thesis and time exits happen at the next M1 open.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from engine_v2.data.clock import TF_SECONDS
from engine_v2.data.symbols import facts
from engine_v2.setup import Setup
from engine_v2.thesis import NEVER, earliest_break

MAX_HOLD_SECONDS = 10 * 86400  # safety cap when a spec has no time stop


@dataclass
class Outcome:
    setup_id: str
    status: str                  # FILLED_CLOSED | EXPIRED | CANCELLED | NO_DATA | BAD_FILL
    fill_time: int | None = None
    fill_price: float | None = None
    exit_time: int | None = None
    exit_reason: str | None = None
    targets_hit: int = 0
    gross_r: float = 0.0
    commission_r: float = 0.0
    swap_r: float = 0.0
    nights: int = 0
    net_r: float = 0.0
    mfe_r: float = 0.0
    mae_r: float = 0.0
    risk_distance: float | None = None
    legs: list = field(default_factory=list)

    @property
    def traded(self) -> bool:
        return self.status == "FILLED_CLOSED"

    @property
    def win(self) -> bool:
        return self.traded and self.net_r > 0


def _first(mask: np.ndarray) -> int:
    k = int(np.argmax(mask)) if len(mask) else 0
    return k if len(mask) and mask[k] else -1


def simulate(setup: Setup, ctx) -> Outcome:
    m = ctx.m1
    d = setup.direction
    out = Outcome(setup.id, "NO_DATA")
    n = len(m)
    i0 = int(np.searchsorted(m.time, setup.created_at, side="left"))
    if i0 >= n:
        return out

    # ---------------- pending ----------------
    cancel_t = earliest_break(setup.thesis, ctx, "pending", 0, setup.created_at, setup.valid_until)
    end_t = min(setup.valid_until, cancel_t)
    iv = int(np.searchsorted(m.time, end_t, side="left"))
    if iv <= i0 and setup.entry["order_type"] != "MARKET":
        out.status = "CANCELLED" if cancel_t < setup.valid_until else "EXPIRED"
        return out
    price = float(setup.entry["price"])
    otype = setup.entry["order_type"]
    if d > 0:
        o_, h_, l_ = m.ask_open, m.ask_high, m.ask_low
    else:
        o_, h_, l_ = m.bid_open, m.bid_high, m.bid_low
    if otype == "MARKET":
        j = i0
        fill = float(o_[j])
    else:
        seg = slice(i0, iv)
        if otype == "LIMIT":
            k = _first(l_[seg] <= price) if d > 0 else _first(h_[seg] >= price)
        else:
            k = _first(h_[seg] >= price) if d > 0 else _first(l_[seg] <= price)
        if k < 0:
            out.status = "CANCELLED" if cancel_t < setup.valid_until else "EXPIRED"
            return out
        j = i0 + k
        if otype == "LIMIT":
            fill = min(price, float(o_[j])) if d > 0 else max(price, float(o_[j]))
        else:
            fill = max(price, float(o_[j])) if d > 0 else min(price, float(o_[j]))

    stop0 = float(setup.stop["price"])
    r = (fill - stop0) * d
    if r <= 0:
        out.status = "BAD_FILL"
        return out
    fx = facts(setup.symbol)
    out.fill_time, out.fill_price, out.risk_distance = int(m.time[j]), fill, r
    out.commission_r = fx.commission_r(r)

    # exits happen on the opposite side of the book
    if d > 0:
        xo, xh, xl = m.bid_open, m.bid_high, m.bid_low
    else:
        xo, xh, xl = m.ask_open, m.ask_high, m.ask_low

    tf_sec = TF_SECONDS[setup.timeframe]
    mg = setup.management or {}
    ts_bars = mg.get("time_stop_bars")
    time_stop_t = int(m.time[j]) + (ts_bars * tf_sec if ts_bars else MAX_HOLD_SECONDS)
    its = min(int(np.searchsorted(m.time, time_stop_t, side="left")), n)
    be_after = mg.get("breakeven_after_target")

    targets = [(float(t["price"]), float(t["share"])) for t in setup.targets]
    remaining, k_hit, cur_stop, gross = 1.0, 0, stop0, 0.0
    base_sec = m.tf_seconds
    fill_close_t = int(m.time[j]) + base_sec

    def leg(price_, share, reason, idx):
        nonlocal gross
        gross += share * (price_ - fill) * d / r
        out.legs.append({"time": int(m.time[idx]), "price": price_, "share": share, "reason": reason})

    # the fill bar itself: only the stop can be hit (conservative)
    if (xl[j] <= cur_stop) if d > 0 else (xh[j] >= cur_stop):
        leg(cur_stop, remaining, "stop", j)
        remaining = 0.0
        exit_idx, reason = j, "stop"
    else:
        s = j + 1
        exit_idx, reason = None, None
        while remaining > 1e-9:
            thesis_t = earliest_break(setup.thesis, ctx, "open", k_hit, max(fill_close_t, int(m.time[s - 1]) + base_sec) - 1,
                                      time_stop_t)
            ie = int(np.searchsorted(m.time, thesis_t, side="left")) if thesis_t != NEVER else n
            cap = min(ie, its, n)
            if s >= cap:
                why = "thesis" if ie <= its and ie < n else ("time_stop" if its < n else "data_end")
                idx = min(cap, n - 1)
                if why == "data_end":
                    leg(float(xo[n - 1]), remaining, why, n - 1)
                else:
                    leg(float(xo[idx]), remaining, why, idx)
                remaining, exit_idx, reason = 0.0, idx, why
                break
            seg = slice(s, cap)
            ks = _first(xl[seg] <= cur_stop) if d > 0 else _first(xh[seg] >= cur_stop)
            be_r = mg.get("breakeven_at_r")
            if be_r is not None and (cur_stop - fill) * d < 0:
                trig = fill + d * be_r * r
                kb = _first(xh[seg] >= trig) if d > 0 else _first(xl[seg] <= trig)
                if kb >= 0 and (ks < 0 or kb < ks):
                    kt_b = -1
                    if k_hit < len(targets):
                        tpb = targets[k_hit][0]
                        kt_b = _first(xh[seg] >= tpb) if d > 0 else _first(xl[seg] <= tpb)
                    if kt_b < 0 or kb < kt_b:
                        cur_stop = fill            # protected: the stop moves to entry, checked from the next bar
                        s = s + kb + 1
                        continue
            if k_hit < len(targets):
                tp = targets[k_hit][0]
                kt = _first(xh[seg] >= tp) if d > 0 else _first(xl[seg] <= tp)
            else:
                kt = -1
            if ks < 0 and kt < 0:
                s = cap
                continue
            if ks >= 0 and (kt < 0 or ks <= kt):
                idx = s + ks
                px = min(cur_stop, float(xo[idx])) if d > 0 else max(cur_stop, float(xo[idx]))
                leg(px, remaining, "stop" if k_hit == 0 else "stop_after_target", idx)
                remaining, exit_idx, reason = 0.0, idx, "stop" if k_hit == 0 else "breakeven_or_trail_stop"
                break
            idx = s + kt
            tp, share = targets[k_hit]
            px = max(tp, float(xo[idx])) if d > 0 else min(tp, float(xo[idx]))
            share = min(share, remaining)
            leg(px, share, f"target{k_hit + 1}", idx)
            remaining -= share
            k_hit += 1
            if be_after is not None and k_hit == be_after:
                cur_stop = fill
            if remaining <= 1e-9:
                exit_idx, reason = idx, f"target{k_hit}"
                break
            s = idx + 1

    out.targets_hit = k_hit
    out.exit_time = int(m.time[exit_idx])
    out.exit_reason = reason
    out.gross_r = gross
    # overnight swap: every broker-day change while the position is open; Wednesday night counts triple
    days = m.time[j:exit_idx + 1] // 86400
    change = np.flatnonzero(days[1:] != days[:-1]) + 1
    swap = 0.0
    per_night = fx.swap_r_per_night(d, r)
    for k in change:
        t_new = int(m.time[j + k])
        open_share = 1.0 - sum(lg["share"] for lg in out.legs if lg["time"] < t_new)
        left_weekday = int((int(days[k - 1]) + 3) % 7)
        mult = 3 if left_weekday == 2 else 1
        swap += max(open_share, 0.0) * mult * per_night
        out.nights += mult
    out.swap_r = swap
    out.net_r = gross - out.commission_r + swap
    span = slice(j, exit_idx + 1)
    if d > 0:
        out.mfe_r = float((xh[span].max() - fill) / r)
        out.mae_r = float((fill - xl[span].min()) / r)
    else:
        out.mfe_r = float((fill - xl[span].min()) / r)
        out.mae_r = float((xh[span].max() - fill) / r)
    out.status = "FILLED_CLOSED"
    return out
