# core/ou_mean_reversion.py
"""
Mean reversion built on the Ornstein-Uhlenbeck process, the way it is actually
specified rather than the way it is usually drawn.

What the previous implementation did: price pierced a Bollinger band, so buy,
stop a couple of pips past the band, target the middle. Nothing in it estimated
how fast the series reverts, how long to wait, how far it was expected to
travel, or whether the journey paid for its own costs. Measured on true ticks
it lost 0.10-0.24R per trade, and the reason is visible in that list -- every
quantity that decides a reversion trade was missing.

The OU specification supplies all of them from one fit:

    dX = kappa (theta - X) dt + sigma dW

    half_life  ln(2)/kappa. This single number fixes the expected holding
               period, when a trade is declared broken (three half-lives),
               and how many independent bets the capital gets per year.
    sigma_eq   sigma / sqrt(2 kappa), the equilibrium spread of the series.
               Thresholds are quoted in THIS, not in ATR -- ATR knows nothing
               about reversion speed, so an ATR threshold treats a two-day and
               a two-hundred-day half-life identically, which is exactly the
               mistake the old thresholds made.
    E[gain]    from X_t = theta + (X_0 - theta) exp(-t/tau), a position entered
               at z is expected to recover |z| (1 - exp(-t/tau)) sigma_eq by
               time t -- so HALF of the dislocation over one half-life, and
               that is a number that can be compared against a cost.

Entry at |z| >= ENTRY_Z, exit at |z| <= EXIT_Z rather than at the mean (the
last few tenths of a sigma decay slowly and pay almost nothing), size
proportional to z capped at MAX_Z, and a time stop at three half-lives.

THE TRAP, and why this module publishes `price_share`:

The state variable is a deviation from a rolling baseline, and such a series is
stationary BY CONSTRUCTION -- detrending mechanically forces it to oscillate,
so an OU fit will always report clean reversion, on a random walk as readily as
on a real spread. But the deviation can collapse two ways: price returns to the
baseline, or THE BASELINE CATCHES UP TO PRICE. Only the first pays. Published
OU write-ups fit the deviation and stop there, which is why a strategy can show
a beautiful R-squared and no edge -- and it is consistent with this project's
own measurement that the same family of signals is a 50/50 coin flip on mid
price once costs are removed.

`price_share` measures it directly: across historical episodes that went out
past ENTRY_Z and came back inside EXIT_Z, how much of the deviation's collapse
came from price moving versus the baseline moving. Below MIN_PRICE_SHARE the
series is reverting on paper only and `tradeable` is False no matter how good
the half-life looks.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

ENTRY_Z = 1.0               # enter once the dislocation reaches this many sigma_eq
EXIT_Z = 0.5                # take partial reversion; the last tenths pay little
MAX_Z = 3.0                 # size scales with z up to here, then stops
TIME_STOP_HALF_LIVES = 3.0  # unconverged past this is broken by the model itself
MIN_HALF_LIFE = 2.0         # bars; faster than this is noise, not reversion
MAX_HALF_LIFE_BARS = 500.0  # slower than this cannot be held at these costs
MIN_PRICE_SHARE = 0.55      # price, not the baseline, must do the reverting
MIN_FORWARD_BETA = 0.15     # measured recovery per sigma of dislocation (OU theory: 0.5)
MIN_FORWARD_T = 3.0         # on NON-overlapping windows, so it is not inflated
MIN_NET_EDGE_SIGMA = 0.10   # expected gain minus cost, in sigma_eq, to bother
MIN_OBS = 200


def _fit_ar1(x: Sequence[float]) -> Optional[Dict[str, float]]:
    """AR(1) by least squares: x[t] = c + phi x[t-1] + e, the discrete OU."""
    n = len(x) - 1
    if n < MIN_OBS:
        return None
    lag = list(x[:-1])
    cur = list(x[1:])
    mx = sum(lag) / n
    my = sum(cur) / n
    sxx = sum((v - mx) ** 2 for v in lag)
    if sxx <= 0:
        return None
    sxy = sum((lag[i] - mx) * (cur[i] - my) for i in range(n))
    phi = sxy / sxx
    c = my - phi * mx
    # phi outside (0,1) is not a reverting process: >=1 is a random walk or
    # explosive, <=0 is alternation, and neither has a usable half-life
    if not (0.0 < phi < 1.0):
        return None
    resid = [cur[i] - (c + phi * lag[i]) for i in range(n)]
    var_e = sum(v * v for v in resid) / max(1, n - 2)
    if var_e <= 0:
        return None
    theta = c / (1.0 - phi)
    sigma_eq = math.sqrt(var_e / (1.0 - phi * phi))
    half_life = -math.log(2.0) / math.log(phi)
    if sigma_eq <= 0 or not math.isfinite(half_life) or half_life <= 0:
        return None
    return {"phi": phi, "theta": theta, "sigma_eq": sigma_eq, "half_life": half_life,
            "sigma": math.sqrt(var_e)}


def _forward_reversion(log_price: Sequence[float], dev: Sequence[float],
                       theta: float, sigma_eq: float, horizon: int) -> Optional[Dict[str, float]]:
    """Does the dislocation predict the forward PRICE move? The decisive test.

    Regress the forward log-price change over one half-life, in sigma_eq units,
    on the negated dislocation. For a genuine OU process the theory pins the
    slope at 0.5 -- half the dislocation recovers in one half-life. For a random
    walk that a rolling baseline has detrended, the AR(1) fit still looks
    beautifully reverting, but this slope is zero: the deviation decays because
    the baseline chases price, and no tradeable move occurs.

    Samples are NON-OVERLAPPING (stepped by the horizon). Overlapping forward
    windows share most of their data and inflate the t-statistic by roughly
    sqrt(horizon), which is how this kind of study convinces itself.
    """
    n = len(dev)
    if horizon < 1 or n <= horizon + 10:
        return None
    xs: List[float] = []
    ys: List[float] = []
    for t in range(0, n - horizon, horizon):
        z = (dev[t] - theta) / sigma_eq
        xs.append(-z)
        ys.append((log_price[t + horizon] - log_price[t]) / sigma_eq)
    m = len(xs)
    if m < 30:
        return None
    mx = sum(xs) / m
    my = sum(ys) / m
    sxx = sum((v - mx) ** 2 for v in xs)
    if sxx <= 0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(m))
    beta = sxy / sxx
    resid = [ys[i] - (my + beta * (xs[i] - mx)) for i in range(m)]
    sse = sum(v * v for v in resid)
    if m <= 2 or sse <= 0:
        return None
    se = math.sqrt((sse / (m - 2)) / sxx)
    syy = sum((v - my) ** 2 for v in ys)
    r = sxy / math.sqrt(sxx * syy) if syy > 0 else 0.0
    return {"beta": beta, "t_stat": beta / se if se > 0 else 0.0, "r": r, "samples": m}


def _price_share(log_price: Sequence[float], baseline: Sequence[float],
                 dev: Sequence[float], sigma_eq: float) -> Optional[float]:
    """Of the deviation that decayed, how much was price and how much the baseline.

    An episode is a stretch past ENTRY_Z that later comes back inside EXIT_Z.
    Over that episode the deviation changed by (d_price - d_baseline); this
    returns |d_price| / (|d_price| + |d_baseline|) averaged over episodes.
    """
    moves_p: List[float] = []
    moves_b: List[float] = []
    i, n = 0, len(dev)
    while i < n:
        if abs(dev[i]) < ENTRY_Z * sigma_eq:
            i += 1
            continue
        j = i + 1
        while j < n and abs(dev[j]) > EXIT_Z * sigma_eq:
            j += 1
        if j >= n:
            break
        moves_p.append(abs(log_price[j] - log_price[i]))
        moves_b.append(abs(baseline[j] - baseline[i]))
        i = j + 1
    if len(moves_p) < 5:
        return None
    p = sum(moves_p) / len(moves_p)
    b = sum(moves_b) / len(moves_b)
    return p / (p + b) if (p + b) > 0 else None


def deviation(log_price: Sequence[float], baseline_bars: int) -> Dict[str, List[float]]:
    """State variable: log price minus its own rolling baseline."""
    base: List[float] = []
    dev: List[float] = []
    run = 0.0
    for i, v in enumerate(log_price):
        run += v
        if i >= baseline_bars:
            run -= log_price[i - baseline_bars]
        if i >= baseline_bars - 1:
            m = run / baseline_bars
            base.append(m)
            dev.append(v - m)
    return {"baseline": base, "deviation": dev,
            "log_price": list(log_price[baseline_bars - 1:])}


def analyse(log_price: Sequence[float], baseline_bars: int = 240,
            round_trip_cost_price: Optional[float] = None) -> Dict[str, Any]:
    """Fit the process and say whether the CURRENT dislocation is worth taking."""
    out: Dict[str, Any] = {"available": False}
    if len(log_price) < baseline_bars + MIN_OBS:
        out["reason"] = f"needs {baseline_bars + MIN_OBS} bars, have {len(log_price)}"
        return out
    d = deviation(log_price, baseline_bars)
    fit = _fit_ar1(d["deviation"])
    if fit is None:
        out["reason"] = "no reverting AR(1) fit (phi outside 0..1)"
        return out

    sigma_eq, hl = fit["sigma_eq"], fit["half_life"]
    z = (d["deviation"][-1] - fit["theta"]) / sigma_eq
    share = _price_share(d["log_price"], d["baseline"], d["deviation"], sigma_eq)
    fwd = _forward_reversion(d["log_price"], d["deviation"], fit["theta"], sigma_eq,
                             max(1, int(round(hl))))

    # Expected recovery comes from the MEASURED slope, not from OU theory. The
    # theory says half the dislocation returns in one half-life, but that is
    # true of the deviation, and the deviation also shrinks when the baseline
    # moves. beta is what price actually did.
    beta = fwd["beta"] if fwd else None
    expected_gain = (max(0.0, beta) * max(0.0, abs(z) - EXIT_Z)) if beta is not None else 0.0
    # cost in the same units: a round trip in log-price over sigma_eq
    cost_sigma = None
    if round_trip_cost_price is not None and sigma_eq > 0:
        cost_sigma = float(round_trip_cost_price) / sigma_eq
    net_edge = None if cost_sigma is None else expected_gain - cost_sigma

    reasons: List[str] = []
    if abs(z) < ENTRY_Z:
        reasons.append(f"z {z:+.2f} inside the {ENTRY_Z} sigma entry")
    if hl < MIN_HALF_LIFE:
        reasons.append(f"half-life {hl:.1f} bars is noise")
    if hl > MAX_HALF_LIFE_BARS:
        reasons.append(f"half-life {hl:.0f} bars too slow to hold")
    if share is not None and share < MIN_PRICE_SHARE:
        reasons.append(f"only {share:.0%} of reversion is price; the baseline does the rest")
    if fwd is None:
        reasons.append("too few non-overlapping windows to test forward reversion")
    else:
        if fwd["beta"] < MIN_FORWARD_BETA:
            reasons.append(f"forward price slope {fwd['beta']:+.3f} below {MIN_FORWARD_BETA} "
                           f"-- the deviation reverts, the price does not")
        if fwd["t_stat"] < MIN_FORWARD_T:
            reasons.append(f"forward slope t {fwd['t_stat']:+.2f} below {MIN_FORWARD_T}")
    if net_edge is not None and net_edge < MIN_NET_EDGE_SIGMA:
        reasons.append(f"net edge {net_edge:+.3f} sigma below {MIN_NET_EDGE_SIGMA}")

    out.update({
        "available": True,
        "half_life_bars": round(hl, 2),
        "phi": round(fit["phi"], 6),
        "sigma_eq": fit["sigma_eq"],
        "theta": fit["theta"],
        "z": round(z, 3),
        "side": (-1 if z > 0 else 1) if abs(z) >= ENTRY_Z else 0,
        "size_multiple": round(min(abs(z), MAX_Z) / ENTRY_Z, 3) if abs(z) >= ENTRY_Z else 0.0,
        "exit_z": EXIT_Z,
        "time_stop_bars": int(round(TIME_STOP_HALF_LIVES * hl)),
        "expected_gain_sigma": round(expected_gain, 4),
        "cost_sigma": None if cost_sigma is None else round(cost_sigma, 4),
        "net_edge_sigma": None if net_edge is None else round(net_edge, 4),
        "price_share": None if share is None else round(share, 3),
        "forward_beta": None if fwd is None else round(fwd["beta"], 4),
        "forward_t": None if fwd is None else round(fwd["t_stat"], 2),
        "forward_windows": None if fwd is None else fwd["samples"],
        "tradeable": not reasons,
        "why_not": reasons,
    })
    return out


_LIVE_CACHE: Dict[str, Any] = {}
# The forward test regresses on NON-overlapping windows of one half-life, and
# needs 30 of them. FX half-lives measure 75-110 H1 bars, so 1400 bars yielded
# about twelve and the gate refused for want of windows rather than for want of
# reversion -- a degenerate refusal that hides the number it exists to check.
# 6000 leaves ~5700 deviation bars: roughly sixty windows at a 95-bar half-life.
LIVE_BARS = 6000


def live(symbol: str, spread_price: Optional[float] = None) -> Dict[str, Any]:
    """The reading for `symbol` now, from H1 closes, cached per closed bar.

    The fit window is the same data the gate is judged on, which is in-sample
    and therefore generous -- a series that cannot clear t=3 in-sample will not
    clear it out of sample either, so this is a MINIMUM bar, not a validation.
    """
    import MetaTrader5 as mt5

    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, LIVE_BARS)
        if rates is None or len(rates) < 600:
            return {"available": False, "reason": f"needs 600 H1 bars, got {0 if rates is None else len(rates)}"}
        # drop the forming bar: its close moves under us
        closes = [float(v) for v in rates["close"][:-1] if v and v > 0]
        stamp = int(rates["time"][-2])
        key = f"{symbol}:{stamp}:{round(spread_price or 0, 8)}"
        hit = _LIVE_CACHE.get(key)
        if hit is not None:
            return hit
        cost = (spread_price / closes[-1]) if (spread_price and closes[-1]) else None
        out = analyse([math.log(c) for c in closes], baseline_bars=240,
                      round_trip_cost_price=cost)
        _LIVE_CACHE.clear()          # one entry is enough; this runs per symbol per bar
        _LIVE_CACHE[key] = out
        return out
    except Exception as e:
        return {"available": False, "reason": f"error: {e}"}


def get_status() -> Dict[str, Any]:
    return {"component": "ou_mean_reversion", "entry_z": ENTRY_Z, "exit_z": EXIT_Z,
            "time_stop_half_lives": TIME_STOP_HALF_LIVES,
            "min_price_share": MIN_PRICE_SHARE,
            "reads": "OU half-life, equilibrium sigma, and a pre-trade edge-vs-cost gate"}


def self_check() -> Dict[str, Any]:
    import random

    rnd = random.Random(7)
    # a TRUE OU series with a known half-life must be recovered
    phi, n = 0.97, 4000              # half-life = ln2/-ln(0.97) = 22.76 bars
    x, ou = 0.0, []
    for _ in range(n):
        x = phi * x + rnd.gauss(0, 0.01)
        ou.append(x)
    fit = _fit_ar1(ou)
    known_hl = -math.log(2) / math.log(phi)
    recovered = fit is not None and abs(fit["half_life"] - known_hl) / known_hl < 0.25

    # a RANDOM WALK detrended by a rolling baseline: the fit will look
    # reverting (that is the trap), but price_share must expose it
    walk = [0.0]
    for _ in range(4000):
        walk.append(walk[-1] + rnd.gauss(0, 0.01))
    rw = analyse(walk, baseline_bars=240, round_trip_cost_price=0.0)
    rw_blocked = (not rw["available"]) or (not rw["tradeable"])

    # the cost gate must refuse a dislocation whose journey costs more than it pays
    dear = analyse(walk, baseline_bars=240, round_trip_cost_price=1e9)
    cost_blocks = (not dear["available"]) or (dear["tradeable"] is False)

    # a TRUE OU in PRICE must pass: forward slope near the theoretical 0.5
    true_ou_prices = [0.0]
    lvl = 0.0
    for _ in range(6000):
        lvl = 0.995 * lvl + rnd.gauss(0, 0.004)
        true_ou_prices.append(lvl)
    real = analyse(true_ou_prices, baseline_bars=240, round_trip_cost_price=0.0)
    real_passes = bool(real.get("available")) and (real.get("forward_beta") or 0) > MIN_FORWARD_BETA

    checks = {
        "half_life_recovered_from_known_ou": recovered,
        "random_walk_not_tradeable": rw_blocked,
        "true_reverting_price_is_detected": real_passes,
        "expensive_round_trip_refused": cost_blocks,
        "exit_is_partial_not_the_mean": 0.0 < EXIT_Z < ENTRY_Z,
        "time_stop_is_three_half_lives": TIME_STOP_HALF_LIVES == 3.0,
        "short_series_unavailable": analyse([0.0] * 10)["available"] is False,
    }
    return {"component": "ou_mean_reversion", "ok": all(checks.values()), "checks": checks,
            "known_half_life": round(known_hl, 2),
            "fitted_half_life": None if fit is None else round(fit["half_life"], 2),
            "random_walk_verdict": rw.get("why_not")}


if __name__ == "__main__":
    import json
    print(json.dumps(self_check(), indent=1))
