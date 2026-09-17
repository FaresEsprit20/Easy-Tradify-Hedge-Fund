"""Gate 1g (strategic_plan_v4.md): round-number levels at tick precision (order clustering, Osler 2000/2003).

Take-profit orders cluster at round prices (price tends to stop there) and stop orders just beyond them (price tends
to accelerate once through). Pre-registered 2026-09-17, before any result:
  data       MT5 raw ticks (quote changes only), 30 markets, 2026-05-26 -> 2026-09-16, read-only
  levels     multiples of STEP[market] (fixed table below: 50 pips FX, 0.50 JPY crosses, 50 gold, 0.50 silver,
             1.00 oil, 25/50/100 points indices by price size)
  control    identical construction at non-round levels: multiples of STEP shifted by 0.37 * STEP
  unit U     RMS of one-minute mid changes over the previous 60 minutes (>= 10 minutes with quotes)
  touch      a fresh touch: the mid reaches a level it did not reach in the previous 30 minutes (it stayed strictly
             on the approach side) and was at least A * U away from it at some point in those 30 minutes
             (A in {2, 4}); the approach side is where the mid came from
             (amended before any outcome was seen: the first wording also rejected the approaching ticks)
  trades     at the first quote at or after touch + 250 ms: BOUNCE (against the approach) or BREAK (with it);
             stop = target = b * U, b in {1, 2, 4}; time exit H in {300, 900, 3600} s; stop fills at the crossing
             quote, target at its level; commission from symbol facts
  split/PASS best configuration on DISCOVERY (fills before 2026-07-20, >= 300 trades), scored once on HOLDOUT;
             PASS = holdout >= 300 trades, win >= 65%, net >= +0.20R, t >= 2, while the same configuration at the
             non-round control levels fails

    python -m engine_v2.run.gate1g collect
    python -m engine_v2.run.gate1g analyse
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np

from engine_v2.run.gate1f import LATENCY_MS, _Market, _read

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "v4" / "gate1g"
START = int(datetime(2026, 5, 26, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 9, 17, tzinfo=timezone.utc).timestamp())
T_SPLIT_MS = int(datetime(2026, 7, 20, tzinfo=timezone.utc).timestamp()) * 1000
STEP = {
    "EURUSD": 0.005, "GBPUSD": 0.005, "AUDUSD": 0.005, "NZDUSD": 0.005, "USDCAD": 0.005, "USDCHF": 0.005,
    "EURGBP": 0.005, "EURCAD": 0.005, "AUDNZD": 0.005, "AUDCAD": 0.005, "AUDCHF": 0.005, "GBPAUD": 0.005,
    "USDJPY": 0.5, "EURJPY": 0.5, "GBPJPY": 0.5,
    "XAUUSD": 50.0, "XAGUSD": 0.5, "XTIUSD": 1.0, "XBRUSD": 1.0,
    "US500": 50.0, "USTEC": 100.0, "US30": 100.0, "US2000": 25.0, "DE40": 100.0, "STOXX50": 50.0, "F40": 50.0,
    "UK100": 50.0, "JP225": 100.0, "HK50": 100.0, "AUS200": 50.0,
}
AS, BS, HS = (2.0, 4.0), (1.0, 2.0, 4.0), (300, 900, 3600)
MODES = ("BOUNCE", "BREAK")
CONFIGS = list(product(AS, MODES, BS, HS))
AWAY_MS = 1_800_000
WORKERS = 5
TIMEOUT = 5400
ROW = [("cid", np.int16), ("ctrl", np.int8), ("t", np.int64), ("net", np.float32)]


def _touches(mk: _Market, step: float, offset: float, A: float, day_lo: int, day_hi: int):
    """(quote index, approach side) of fresh touches of the levels offset + j * step inside the day."""
    tm, mid = mk.tm, mk.mid
    u = mk.unit_at(tm)
    out = []
    in_day = np.flatnonzero((tm >= day_lo) & (tm < day_hi))
    if len(in_day) < 2:
        return out
    lo_i, hi_i = in_day[0], in_day[-1]
    last_touch = {}
    # a touch happens at quote i when the level between mid[i-1] and mid[i] (inclusive of reaching it)
    prev = mid[lo_i - 1:hi_i] if lo_i > 0 else np.r_[mid[lo_i], mid[lo_i:hi_i]]
    cur = mid[lo_i:hi_i + 1]
    k_prev = np.floor((prev - offset) / step)
    k_cur = np.floor((cur - offset) / step)
    crossed_up = k_cur > k_prev                     # reached or passed a level from below
    crossed_dn = (np.ceil((cur - offset) / step) < np.ceil((prev - offset) / step))  # from above
    cand = np.flatnonzero(crossed_up | crossed_dn) + lo_i
    for i in cand:
        if not (u[i] > 0):
            continue
        side = -1 if mid[i] > mid[i - 1] else 1          # -1: came from below, +1: came from above
        level = (np.floor((mid[i] - offset) / step) * step + offset) if side < 0 else (np.ceil((mid[i] - offset) / step) * step + offset)
        key = round(level / step, 6)
        if tm[i] - last_touch.get(key, -10 ** 15) < AWAY_MS:
            continue
        j0 = int(np.searchsorted(tm, tm[i] - AWAY_MS, side="left"))
        if j0 >= i or tm[j0] > tm[i] - AWAY_MS + 120_000:          # need quotes covering the 30 minutes
            continue
        window = mid[j0:i]
        dist = (level - window) if side < 0 else (window - level)   # distance on the approach side, in price
        if dist.min() <= 0 or dist.max() < A * u[i]:
            continue
        last_touch[key] = tm[i]
        out.append((i, side))
    return out


def _trade_nets(mk: _Market, i, approach, u, comm_px):
    fi = int(np.searchsorted(mk.tm, mk.tm[i] + LATENCY_MS, side="left"))
    if fi >= len(mk.tm) or mk.tm[fi] - mk.tm[i] > 60_000:
        return None, None
    ends = [int(np.searchsorted(mk.tm, mk.tm[fi] + H * 1000, side="right")) for H in HS]
    res = {}
    for mode in MODES:
        # approach -1 = came from below (moving up): BREAK buys, BOUNCE sells
        d = (1 if approach < 0 else -1) * (1 if mode == "BREAK" else -1)
        fill = mk.ask[fi] if d > 0 else mk.bid[fi]
        rel = ((mk.bid if d > 0 else mk.ask)[fi + 1:ends[-1]] - fill) * d
        for b in BS:
            b_px = b * u
            hit = (rel <= -b_px) | (rel >= b_px)
            first = int(np.argmax(hit)) if hit.any() else len(rel)
            for H, eH in zip(HS, ends):
                n_h = eH - (fi + 1)
                if first < n_h:
                    g = b_px if rel[first] >= b_px else rel[first]
                elif n_h > 0:
                    g = rel[n_h - 1]
                else:
                    g = 0.0
                res[(mode, b, H)] = (g - comm_px) / b_px
    return int(mk.tm[fi]), res


def symbol_events(sym: str):
    import MetaTrader5 as mt5
    from engine_v2.data.symbols import facts
    if not mt5.initialize(timeout=20000):
        raise RuntimeError(mt5.last_error())
    fx = facts(sym)
    comm_px = fx.commission_usd_per_lot_round_trip / fx.usd_per_price_unit_per_lot
    step = STEP[sym]
    rows = []
    for day in range(START // 86400, END // 86400):
        rd = _read(mt5, sym, day * 86400 - 2 * 3600, (day + 1) * 86400 + 3700)
        if rd is None:
            continue
        mk = _Market(*rd)
        for ctrl, offset in ((0, 0.0), (1, 0.37 * step)):
            for A in AS:
                for i, approach in _touches(mk, step, offset, A, day * 86_400_000, (day + 1) * 86_400_000):
                    u = float(mk.unit_at(np.array([mk.tm[i]]))[0])
                    tf, res = _trade_nets(mk, i, approach, u, comm_px)
                    if res is None:
                        continue
                    for (mode, b, H), net in res.items():
                        rows.append((CONFIGS.index((A, mode, b, H)), ctrl, tf, net))
    mt5.shutdown()
    return np.array(rows, dtype=ROW)


def one(sym: str):
    t0 = time.time()
    ev = symbol_events(sym)
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    np.save(OUT / "parts" / f"{sym}.npy", ev)
    print(sym, "rows", len(ev), f"{time.time() - t0:.0f}s", flush=True)


def collect():
    parts = OUT / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    todo = [s for s in STEP if not (parts / f"{s}.npy").exists()]
    running = {}
    while todo or running:
        while todo and len(running) < WORKERS:
            s = todo.pop(0)
            running[s] = (subprocess.Popen([sys.executable, "-W", "ignore", "-m", "engine_v2.run.gate1g", "one", s],
                                           cwd=ROOT), time.time())
        for s, (p, t0) in list(running.items()):
            if p.poll() is not None:
                print(s, "exit", p.returncode, f"{time.time() - t0:.0f}s", flush=True)
                del running[s]
            elif time.time() - t0 > TIMEOUT:
                p.kill()
                print(s, "TIMEOUT", flush=True)
                del running[s]
        time.sleep(2)


def analyse():
    from engine_v2.run.gate1b import _cls
    from engine_v2.run.gate1f import _stats
    ev = {s: np.load(OUT / "parts" / f"{s}.npy") for s in STEP if (OUT / "parts" / f"{s}.npy").exists()}
    okf = lambda s: s.get("n", 0) >= 300 and s["win"] >= 0.65 and s["net"] >= 0.20 and s["t"] >= 2
    table = []
    for cid, cfg in enumerate(CONFIGS):
        acc = {k: [] for k in ("d", "h", "dc", "hc")}
        by_cls = {c: [] for c in range(4)}
        for s, e in ev.items():
            m = e["cid"] == cid
            early = e["t"] < T_SPLIT_MS
            acc["d"].append(e["net"][m & (e["ctrl"] == 0) & early])
            acc["h"].append(e["net"][m & (e["ctrl"] == 0) & ~early])
            acc["dc"].append(e["net"][m & (e["ctrl"] == 1) & early])
            acc["hc"].append(e["net"][m & (e["ctrl"] == 1) & ~early])
            by_cls[_cls(s)].append(e["net"][m & (e["ctrl"] == 0) & ~early])
        cat = lambda v: np.concatenate(v).astype(float) if v else np.array([])
        table.append({"cfg": dict(zip(("A", "mode", "b", "H"), cfg)), "discovery": _stats(cat(acc["d"])),
                      "discovery_control": _stats(cat(acc["dc"])), "holdout": _stats(cat(acc["h"])),
                      "holdout_control": _stats(cat(acc["hc"])),
                      "holdout_by_class": {nm: _stats(cat(by_cls[c])) for c, nm in
                                           {0: "FX", 1: "metals", 2: "oil", 3: "indices"}.items()}})
    eligible = [r for r in table if r["discovery"].get("n", 0) >= 300]
    best = max(eligible, key=lambda r: (r["discovery"]["net"], r["discovery"]["win"]))
    passed = bool(okf(best["holdout"]) and not okf(best["holdout_control"]))
    both = [r for r in eligible if r["discovery"]["net"] > 0 and r["holdout"].get("n", 0) >= 300 and r["holdout"]["net"] > 0]
    (OUT / "analysis.json").write_text(json.dumps({"chosen_on_discovery": best, "PASS": passed,
                                                   "positive_in_both": both, "all": table}, indent=1))
    print("CHOSEN", best["cfg"], "disc", best["discovery"], "disc_ctrl", best["discovery_control"], "hold",
          best["holdout"], "hold_ctrl", best["holdout_control"], "PASS", passed)
    print("  by class (holdout):", best["holdout_by_class"])
    for r in sorted(eligible, key=lambda r: -r["discovery"]["net"])[:6]:
        print("  top", r["cfg"], "disc", r["discovery"], "ctrl", r["discovery_control"], "hold", r["holdout"],
              "hold_ctrl", r["holdout_control"])
    print("  configurations positive in discovery and holdout:", len(both))


if __name__ == "__main__":
    if sys.argv[1] == "one":
        one(sys.argv[2])
    else:
        {"collect": collect, "analyse": analyse}[sys.argv[1]]()
