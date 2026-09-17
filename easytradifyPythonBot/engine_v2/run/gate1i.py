"""Gate 1i (strategic_plan_v4.md): the Gate 1b open search on markets never used before.

Pre-registered 2026-09-17, before any result:
  markets    every FX and spot-index symbol of the broker not in the Gate 1b set that is already in Market Watch and
             has MT5 ticks from 2026-05-26 (FX minors, FX exotics, minor spot indices); no crypto, no other classes
  data       true bid/ask M1 bars built from MT5 ticks (read-only, no symbol_select) into tradify_study/ticks_m1_v5
  facts      MT5 symbol_info (usd per price unit per lot = tick_value / tick_size); commission 7.03 USD per lot
             round trip for FX (as for the Gate 1b FX pairs), 0 for index CFDs (as for the Gate 1b indices)
  events     exactly the Gate 1b construction (engine_v2/run/gate1b.run_symbol): every M5 close, both sides,
             G1/G2 brackets, same 34 features; related markets = the pair's legs / regional neighbours (RELATED_V5)
  test A     model trained on ALL Gate 1b events before 2026-07-20 (30 old markets), scored on the new markets
             from 2026-07-20 (unseen markets AND unseen weeks); shuffled-label control
  test B     new markets split into 3 groups (seed 11); train on old events before T plus the other new groups
             before T; score the held-out group from T
  PASS       as Gate 1b: a top slice (10/5/2%) with >= 300 trades, win >= 65%, net >= +0.20R, t >= 2, while the
             control's same slice fails; reported per class (FX minors, FX exotics, indices)

    python -m engine_v2.run.gate1i bars
    python -m engine_v2.run.gate1i facts
    python -m engine_v2.run.gate1i collect
    python -m engine_v2.run.gate1i analyse
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "v4" / "gate1i"
BARS = "C:/Users/msi/tradify_study/ticks_m1_v5"
START = datetime(2026, 5, 25)
FX_MINORS = "AUDJPY CHFJPY EURAUD EURCHF EURNZD GBPCHF CADCHF CADJPY GBPCAD GBPNZD NZDCAD NZDCHF NZDJPY".split()
FX_EXOTICS = ("USDSGD AUDSGD CHFSGD EURDKK EURHKD EURNOK EURPLN EURSEK EURSGD EURTRY EURZAR GBPDKK GBPNOK GBPSEK GBPSGD "
              "GBPTRY NOKJPY NOKSEK SEKJPY SGDJPY USDCNH USDCZK USDDKK USDHKD USDHUF USDMXN USDNOK USDPLN USDSEK "
              "USDTHB USDTRY USDZAR USDAED").split()
INDICES = "CHINA50 ES35 IT40 CA60 NETH25 SE30 SWI20 CHINAH SA40 NOR25 TecDE30 MidDE60 MidDE50".split()
NEW = FX_MINORS + FX_EXOTICS + INDICES
RELATED_V5 = {
    "AUDJPY": ["AUDUSD", "USDJPY"], "CHFJPY": ["USDCHF", "USDJPY"], "EURAUD": ["EURUSD", "AUDUSD"],
    "EURCHF": ["EURUSD", "USDCHF"], "EURNZD": ["EURUSD", "NZDUSD"], "GBPCHF": ["GBPUSD", "USDCHF"],
    "CADCHF": ["USDCAD", "USDCHF"], "CADJPY": ["USDCAD", "USDJPY"], "GBPCAD": ["GBPUSD", "USDCAD"],
    "GBPNZD": ["GBPUSD", "NZDUSD"], "NZDCAD": ["NZDUSD", "USDCAD"], "NZDCHF": ["NZDUSD", "USDCHF"],
    "NZDJPY": ["NZDUSD", "USDJPY"],
    "USDSGD": ["USDCNH", "EURUSD"], "AUDSGD": ["AUDUSD", "USDSGD"], "CHFSGD": ["USDCHF", "USDSGD"],
    "EURDKK": ["EURUSD", "USDDKK"], "EURHKD": ["EURUSD", "USDHKD"], "EURNOK": ["EURUSD", "USDNOK"],
    "EURPLN": ["EURUSD", "USDPLN"], "EURSEK": ["EURUSD", "USDSEK"], "EURSGD": ["EURUSD", "USDSGD"],
    "EURTRY": ["EURUSD", "USDTRY"], "EURZAR": ["EURUSD", "USDZAR"], "GBPDKK": ["GBPUSD", "USDDKK"],
    "GBPNOK": ["GBPUSD", "USDNOK"], "GBPSEK": ["GBPUSD", "USDSEK"], "GBPSGD": ["GBPUSD", "USDSGD"],
    "GBPTRY": ["GBPUSD", "USDTRY"], "NOKJPY": ["USDNOK", "USDJPY"], "NOKSEK": ["USDNOK", "USDSEK"],
    "SEKJPY": ["USDSEK", "USDJPY"], "SGDJPY": ["USDSGD", "USDJPY"], "USDCNH": ["USDSGD", "AUDUSD"],
    "USDCZK": ["EURUSD", "USDPLN"], "USDDKK": ["EURUSD", "EURDKK"], "USDHKD": ["EURHKD", "EURUSD"],
    "USDHUF": ["EURUSD", "USDPLN"], "USDMXN": ["USDZAR", "USDCAD"], "USDNOK": ["EURUSD", "EURNOK"],
    "USDPLN": ["EURUSD", "EURPLN"], "USDSEK": ["EURUSD", "EURSEK"], "USDTHB": ["USDSGD", "USDCNH"],
    "USDTRY": ["EURTRY", "EURUSD"], "USDZAR": ["USDMXN", "AUDUSD"], "USDAED": ["EURUSD"],
    "CHINA50": ["HK50", "CHINAH"], "CHINAH": ["HK50", "CHINA50"], "ES35": ["STOXX50", "IT40"],
    "IT40": ["STOXX50", "ES35"], "CA60": ["US500", "XTIUSD"], "NETH25": ["STOXX50", "DE40"],
    "SE30": ["STOXX50", "NOR25"], "SWI20": ["STOXX50", "DE40"], "SA40": ["UK100", "XAUUSD"],
    "NOR25": ["STOXX50", "XBRUSD"], "TecDE30": ["DE40", "USTEC"], "MidDE60": ["DE40", "MidDE50"],
    "MidDE50": ["DE40", "MidDE60"],
}
WORKERS = 5
TIMEOUT = 1800


# ---------------------------------------------------------------- bars (read-only; same method as tick_bars.py)
def _day_bars(mt5, sym, day, last):
    a = mt5.copy_ticks_range(sym, day.replace(tzinfo=timezone.utc), (day + timedelta(days=1)).replace(tzinfo=timezone.utc),
                             mt5.COPY_TICKS_ALL)
    if a is None or len(a) == 0:
        return None, last
    t = a["time_msc"] // 1000
    bid, ask = a["bid"].astype(float), a["ask"].astype(float)
    for arr, k in ((bid, 0), (ask, 1)):
        valid = arr > 0
        if last[k] is not None:
            arr[~valid & (np.cumsum(valid) == 0)] = last[k]
            valid = arr > 0
        if not valid.any():
            return None, last
        idx = np.where(valid, np.arange(arr.size), 0)
        np.maximum.accumulate(idx, out=idx)
        arr[:] = arr[idx]
    keep = (bid > 0) & (ask > 0)
    t, bid, ask = t[keep], bid[keep], ask[keep]
    if t.size == 0:
        return None, last
    last = (bid[-1], ask[-1])
    minute = t - t % 60
    starts = np.flatnonzero(np.r_[True, minute[1:] != minute[:-1]])
    ends = np.r_[starts[1:], t.size]

    def ohlc(x):
        return x[starts], np.maximum.reduceat(x, starts), np.minimum.reduceat(x, starts), x[ends - 1]

    mid = (bid + ask) / 2
    bo, bh, bl, bc = ohlc(bid)
    ao, ah, al, ac = ohlc(ask)
    _, mh, ml, mc = ohlc(mid)
    d = np.r_[0.0, np.diff(mid)]
    up = np.add.reduceat((d > 0).astype(float), starts)
    dn = np.add.reduceat((d < 0).astype(float), starts)
    spr = np.add.reduceat(ask - bid, starts) / (ends - starts)
    return np.column_stack([minute[starts], bo, bh, bl, bc, ao, ah, al, ac, ends - starts, mh, ml, mc, up, dn, spr]), last


def build_one(sym: str):
    import MetaTrader5 as mt5
    path = f"{BARS}/{sym}.npz"
    if os.path.exists(path):
        print(sym, "cached", flush=True)
        return
    if not mt5.initialize(timeout=20000):
        raise RuntimeError(mt5.last_error())
    info = mt5.symbol_info(sym)
    if info is None or not info.select:
        print(sym, "skipped: not in Market Watch", flush=True)
        return
    chunks, last, day = [], (None, None), START
    end = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)
    while day <= end:
        b, last = _day_bars(mt5, sym, day, last)
        if b is not None:
            chunks.append(b)
        day += timedelta(days=1)
    mt5.shutdown()
    if not chunks:
        print(sym, "no ticks", flush=True)
        return
    a = np.vstack(chunks)
    os.makedirs(BARS, exist_ok=True)
    np.savez_compressed(path, time=a[:, 0].astype(np.int64), bid_open=a[:, 1], bid_high=a[:, 2], bid_low=a[:, 3],
                        bid_close=a[:, 4], ask_open=a[:, 5], ask_high=a[:, 6], ask_low=a[:, 7], ask_close=a[:, 8],
                        ticks=a[:, 9].astype(np.int32), mid_high=a[:, 10], mid_low=a[:, 11], mid_close=a[:, 12],
                        up_ticks=a[:, 13].astype(np.int32), down_ticks=a[:, 14].astype(np.int32), mean_spread=a[:, 15])
    print(sym, len(a), "bars, median spread", float(np.median(a[:, 8] - a[:, 4])), flush=True)


def _run_pool(cmd_for, names):
    todo, running = list(names), {}
    while todo or running:
        while todo and len(running) < WORKERS:
            s = todo.pop(0)
            running[s] = (subprocess.Popen(cmd_for(s), cwd=ROOT), time.time())
        for s, (p, t0) in list(running.items()):
            if p.poll() is not None:
                del running[s]
            elif time.time() - t0 > TIMEOUT:
                p.kill()
                print(s, "TIMEOUT", flush=True)
                del running[s]
        time.sleep(1)


def bars():
    _run_pool(lambda s: [sys.executable, "-W", "ignore", "-m", "engine_v2.run.gate1i", "bars_one", s], NEW)


# ---------------------------------------------------------------- facts
def write_facts():
    import MetaTrader5 as mt5
    from engine_v2.data import symbols as symmod
    if not mt5.initialize(timeout=20000):
        raise RuntimeError(mt5.last_error())
    path = symmod._PATH
    data = json.loads(path.read_text())
    added = []
    for s in NEW:
        if s in data["symbols"] or not os.path.exists(f"{BARS}/{s}.npz"):
            continue
        i = mt5.symbol_info(s)
        if i is None or not i.trade_tick_size:
            continue
        data["symbols"][s] = {
            "digits": i.digits, "point": i.point, "tick_value": i.trade_tick_value, "tick_size": i.trade_tick_size,
            "contract_size": i.trade_contract_size, "volume_min": i.volume_min, "volume_step": i.volume_step,
            "volume_max": i.volume_max, "currency_profit": i.currency_profit, "swap_long": i.swap_long,
            "swap_short": i.swap_short, "swap_mode": i.swap_mode,
            "usd_per_price_unit_per_lot": i.trade_tick_value / i.trade_tick_size,
            "commission_usd_per_lot_round_trip": 0.0 if s in INDICES else 7.03,
        }
        added.append(s)
    mt5.shutdown()
    data["source_v5"] = "MT5 symbol_info, read 2026-09-17 (Gate 1i markets)"
    path.write_text(json.dumps(data, indent=1))
    print("facts added:", len(added), added)


# ---------------------------------------------------------------- events
def _events_one(sym):
    from engine_v2.run import gate1b
    gate1b.RELATED.update(RELATED_V5)
    try:
        return sym, gate1b.run_symbol(sym)
    except Exception as e:  # noqa: BLE001 - one bad market must not stop the others
        return sym, repr(e)


def collect():
    from concurrent.futures import ProcessPoolExecutor
    from engine_v2.run.gate1b import FEATURES
    names = [s for s in NEW if os.path.exists(f"{BARS}/{s}.npz")]
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with ProcessPoolExecutor(10) as ex:
        for sym, part in ex.map(_events_one, names):
            if isinstance(part, str):
                print(sym, "FAILED", part, flush=True)
                continue
            rows.extend(part)
            print(sym, "events", len(part), flush=True)
    labels = ["G1L", "G1S", "G2L", "G2S"]
    X = np.array([[np.nan if r[f] is None else r[f] for f in FEATURES] for r in rows], np.float32)
    net = np.array([[r[f"{k}_net"] for k in labels] for r in rows], np.float32)
    np.savez_compressed(OUT / "events.npz", symbol=np.array([r["symbol"] for r in rows]),
                        t=np.array([r["t"] for r in rows], np.int64), X=X, net=net,
                        features=np.array(FEATURES), labels=np.array(labels))
    print("events", len(rows), "markets", len({r['symbol'] for r in rows}))


# ---------------------------------------------------------------- analysis
def analyse():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from engine_v2.run.gate1b import T_SPLIT, _stats
    old = np.load(ROOT / "reports" / "v4" / "gate1b" / "events.npz")
    new = np.load(OUT / "events.npz")
    labels = [str(x) for x in old["labels"]]
    Xo, No, to = old["X"].astype(float), old["net"].astype(float), old["t"]
    Xn, Nn, tn, sn = new["X"].astype(float), new["net"].astype(float), new["t"], new["symbol"]
    cls_new = np.array([0 if s in FX_MINORS else (1 if s in FX_EXOTICS else 2) for s in sn])
    cls_names = {0: "FX minors", 1: "FX exotics", 2: "indices"}
    params = dict(max_depth=4, learning_rate=0.05, max_iter=400, min_samples_leaf=100, l2_regularization=1.0)
    rng = np.random.default_rng(11)
    okf = lambda s: s.get("n", 0) >= 300 and s["win"] >= 0.65 and s["net"] >= 0.20 and s["t"] >= 2
    syms = sorted(set(sn.tolist()))
    order = list(rng.permutation(syms))
    groups = [set(order[k::3]) for k in range(3)]
    report = {"markets": syms, "events": int(len(tn))}
    for key in labels:
        k = labels.index(key)
        y_o, y_n = (No[:, k] > 0).astype(int), (Nn[:, k] > 0).astype(int)
        for test in ("A", "B"):
            ranks, ranks_c, idxs, aucs = [], [], [], []
            splits = [None] if test == "A" else groups
            for grp in splits:
                tr_o = to < T_SPLIT
                if test == "A":
                    X_tr, y_tr = Xo[tr_o], y_o[tr_o]
                    te = tn >= T_SPLIT
                else:
                    in_g = np.isin(sn, list(grp))
                    tr_n = (~in_g) & (tn < T_SPLIT)
                    X_tr, y_tr = np.vstack([Xo[tr_o], Xn[tr_n]]), np.r_[y_o[tr_o], y_n[tr_n]]
                    te = in_g & (tn >= T_SPLIT)
                if te.sum() < 100:
                    continue
                m = HistGradientBoostingClassifier(**params, random_state=0).fit(X_tr, y_tr)
                p = m.predict_proba(Xn[te])[:, 1]
                pc = HistGradientBoostingClassifier(**params, random_state=0).fit(X_tr, rng.permutation(y_tr)).predict_proba(Xn[te])[:, 1]
                aucs.append(roc_auc_score(y_n[te], p))
                ranks.append(np.argsort(np.argsort(-p)) / len(p))
                ranks_c.append(np.argsort(np.argsort(-pc)) / len(pc))
                idxs.append(np.flatnonzero(te))
            rk, rkc, ix = np.concatenate(ranks), np.concatenate(ranks_c), np.concatenate(idxs)
            net = Nn[:, k]
            res = {"auc": round(float(np.mean(aucs)), 3), "all": _stats(net[ix], y_n[ix])}
            passed = False
            for q in (0.10, 0.05, 0.02):
                sel, selc = ix[rk < q], ix[rkc < q]
                st, sc = _stats(net[sel], y_n[sel]), _stats(net[selc], y_n[selc])
                res[f"top{q:.0%}"], res[f"control_top{q:.0%}"] = st, sc
                passed = passed or (okf(st) and not okf(sc))
                res[f"top{q:.0%}_by_class"] = {nm: _stats(net[sel[cls_new[sel] == c]], y_n[sel[cls_new[sel] == c]])
                                               for c, nm in cls_names.items()}
            res["PASS"] = passed
            report[f"{test}|{key}"] = res
            print(f"test {test} {key}: auc={res['auc']} all={res['all']} top10={res['top10%']} top5={res['top5%']} "
                  f"top2={res['top2%']} ctrl_top5={res['control_top5%']} PASS={passed}", flush=True)
            print(f"   top5 by class: {res['top5%_by_class']}", flush=True)
            (OUT / "analysis.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "bars_one":
        build_one(sys.argv[2])
    else:
        {"bars": bars, "facts": write_facts, "collect": collect, "analyse": analyse}[cmd]()
