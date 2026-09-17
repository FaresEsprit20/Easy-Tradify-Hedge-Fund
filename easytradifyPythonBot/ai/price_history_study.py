# ai/price_history_study.py
"""
Price-history study: every component's reading on real M1 history, and what
price did next.

The stored trades (about 110) are too few to calibrate thirty components, and
they only show bars the engine already chose. This walks the REAL
analyze_institutional_signal() across MT5 history for every study symbol
(core/engine_replay's no-lookahead shim, all other symbols served as peers so
the cross-asset members see real data), every STEP_MINUTES, and stores for
each snapshot:

  - each strategy-group member's reading, raw (before its repair) and as the
    engine uses it                                  (direction, strength)
  - the numeric leaves of the component payload (RSI value, ADX, ...)
  - the group scores, final probability, side and entry decision
  - the planned bracket

label() then walks the M1 bars that followed and adds the outcome:

  move_5atr / move_2atr   which barrier (+/- k x ATR) price touched first
                          within HORIZON_BARS: +1 up, -1 down, 0 neither
  ret_30 / ret_120        signed return after 30 / 120 minutes, in ATR
  bracket                 the planned stop/target, gross R (stop first on an
                          ambiguous bar)

    python -m ai.price_history_study download
    python -m ai.price_history_study run --workers 14 --step 15
    python -m ai.price_history_study label

This is not a trade replay: it measures readings against the next move, on
every bar, taken or not.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = Path(os.getenv("PRICE_HISTORY_DIR") or ROOT / "reports" / "cache" / "history")
STUDY_DIR = Path(os.getenv("PRICE_STUDY_DIR") or ROOT / "reports" / "cache" / "study")
# PRICE_STUDY_FULL=1 also stores every component's internal fields (`full`),
# for per-component repair (ai/component_repair.py). ~8 KB per record gzipped.
CAPTURE_FULL = str(os.getenv("PRICE_STUDY_FULL", "0")).lower() in ("1", "true", "yes")
MAX_FULL_LEAVES = 4000
FULL_SKIP_KEYS = {"decision_snapshot", "probability_ledger", "ledger", "reasons", "reason", "description",
                  "explanation", "note", "legend", "stop_hunt_legend", "summary", "contributions",
                  "account_info", "position_management", "config"}

SYMBOLS = ("EURUSD GBPUSD USDJPY AUDUSD NZDUSD USDCAD USDCHF EURGBP EURCAD AUDNZD "
           "AUDCAD AUDCHF GBPAUD GBPJPY EURJPY XAUUSD XAGUSD").split()
TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1")
STEP_MINUTES = 15
WARMUP_M1_BARS = 1500
HORIZON_BARS = 480          # 8 hours of M1
LONG_HORIZON_BARS = 1440    # 24 hours of M1, for moves measured in H1 ATR
MAX_NUMERIC_LEAVES = 400
BROKER_OFFSET_SECONDS = 10800   # bar clock minus UTC for the whole study window (US DST)


# ============================================================
# DATA
# ============================================================

def download(start: datetime = datetime(2026, 5, 1, tzinfo=timezone.utc)) -> Dict[str, Dict[str, int]]:
    """Pull chunked history per timeframe (copy_rates_range; the terminal caps
    one request at its max-bars setting, chunks are not capped)."""
    import MetaTrader5 as mt5
    from core.execution import get_pip_info

    mt5.initialize()
    tf_codes = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    end = datetime.now(timezone.utc) + timedelta(days=1)
    specs, counts = {}, {}
    for symbol in SYMBOLS:
        mt5.symbol_select(symbol, True)
        arrays = {}
        for name, code in tf_codes.items():
            a = start - (timedelta(days=400) if name in ("H1", "H4", "D1") else timedelta(0))
            step = timedelta(days=7 if name == "M1" else 60)
            chunks = []
            while a < end:
                r = mt5.copy_rates_range(symbol, code, a, min(a + step, end))
                if r is not None and len(r) > 1:
                    chunks.append(r)
                a += step
            if chunks:
                arrays[name] = np.unique(np.concatenate(chunks))
        np.savez_compressed(HISTORY_DIR / f"{symbol}.npz", **arrays)
        info = mt5.symbol_info(symbol)
        specs[symbol] = {"pip": float(get_pip_info(info)[0]), "info": {
            k: getattr(info, k) for k in ("name", "digits", "point", "spread", "trade_contract_size",
                                          "volume_min", "volume_max", "volume_step", "trade_tick_value",
                                          "trade_tick_size", "trade_stops_level", "currency_profit",
                                          "currency_base", "currency_margin")}}
        counts[symbol] = {k: len(v) for k, v in arrays.items()}
    (HISTORY_DIR / "symbols.json").write_text(json.dumps(specs, indent=1))
    return counts


def load_history(symbol: str) -> Dict[str, np.ndarray]:
    with np.load(HISTORY_DIR / f"{symbol}.npz") as z:
        return {k: z[k] for k in z.files}


def symbol_specs() -> Dict[str, Any]:
    return json.loads((HISTORY_DIR / "symbols.json").read_text())


def _fast_feed_class():
    from core.market_data import HistoricalFeed, TF_SECONDS

    class FastFeed(HistoricalFeed):
        """HistoricalFeed with a binary-search slice (same visibility rule:
        a bar is visible once bar_time + duration <= ts)."""

        def __init__(self, rates_by_tf, **kw):
            super().__init__(rates_by_tf, **kw)
            self._np_times = {tf: np.asarray(arr["time"], dtype=np.int64) for tf, arr in rates_by_tf.items()}

        def _slice(self, tf, ts):
            arr = self.rates_by_tf.get(tf)
            if arr is None:
                return None
            duration = TF_SECONDS.get(tf.upper(), 60)
            end = int(np.searchsorted(self._np_times[tf], ts - duration, side="right"))
            if end == 0:
                return None
            return arr[max(0, end - self.max_bars):end]

        def at(self, ts, **kw):
            md = super().at(ts, **kw)
            if md is not None:
                # the live edge features read 1600 closed M1 bars; the engine
                # itself keeps the 1000 it gets live
                end = int(np.searchsorted(self._np_times["M1"], ts - 60, side="right"))
                md.edge_m1 = self.rates_by_tf["M1"][max(0, end - 1600):end]
            return md

    return FastFeed


def build_feed(symbol: str, histories: Mapping[str, Mapping[str, np.ndarray]], specs: Mapping[str, Any]):
    from core.market_data import MultiSymbolFeed

    FastFeed = _fast_feed_class()

    def one(sym):
        spec = specs[sym]
        return FastFeed({tf: histories[sym][tf] for tf in TIMEFRAMES if tf in histories[sym]},
                        symbol=sym, base_timeframe="M1", spread_pips=None, pip_size=spec["pip"],
                        info_kwargs=dict(spec["info"]), balance=10000.0, leverage=200)

    primary = one(symbol)
    peers = {s: one(s) for s in histories if s != symbol}
    return MultiSymbolFeed(primary, peers)


# ============================================================
# CAPTURE
# ============================================================

def _unwrap(reader):
    """The member's raw reader underneath its repair (trend-confirmed,
    continuation, regime-only), or the reader itself."""
    qual = getattr(reader, "__qualname__", "")
    if qual.startswith(("_trend_confirmed.", "_as_continuation.", "_in_regime.")) and reader.__closure__:
        for cell in reader.__closure__:
            inner = cell.cell_contents
            if callable(inner):
                return _unwrap(inner)
    return reader


def member_readings(payload: Mapping[str, Any]) -> Dict[str, Any]:
    from core.strategy_groups import MEMBERS

    out = {}
    for group, name, reader in MEMBERS:
        entry = {"group": group}
        for key, fn in (("used", reader), ("raw", _unwrap(reader))):
            try:
                r = fn(payload)
            except Exception:
                r = None
            entry[key] = None if r is None else [int(r[0]), round(float(r[1]), 3)]
        out[name] = entry
    return out


def numeric_leaves(node: Any, prefix: str = "", out: Optional[Dict[str, Any]] = None, depth: int = 0):
    """Flat numeric and short-string leaves (lists skipped)."""
    out = {} if out is None else out
    if len(out) >= MAX_NUMERIC_LEAVES or depth > 5:
        return out
    if isinstance(node, Mapping):
        for k, v in node.items():
            numeric_leaves(v, f"{prefix}.{k}" if prefix else str(k), out, depth + 1)
    elif isinstance(node, bool):
        out[prefix] = int(node)
    elif isinstance(node, (int, float, np.integer, np.floating)):
        v = float(node)
        if math.isfinite(v):
            out[prefix] = round(v, 6)
    elif isinstance(node, str) and len(node) <= 40:
        out[prefix] = node
    return out


def full_leaves(node: Any, prefix: str = "", out: Optional[Dict[str, Any]] = None, depth: int = 0):
    """Every internal field (core/result_leaves.full_leaves: the same view the
    live engine scores)."""
    from core.result_leaves import full_leaves as _leaves
    return _leaves(node, prefix, out, depth)


def _g(d, *path):
    for k in path:
        if not isinstance(d, Mapping):
            return None
        d = d.get(k)
    return d


def snapshot_record(symbol: str, ts: float, result: Mapping[str, Any], payload: Optional[Mapping[str, Any]],
                    close: float, pip: float) -> Dict[str, Any]:
    fv = result.get("final_verdict") or {}
    ea = result.get("entry_analysis") or {}
    ed = result.get("entry_details") or {}
    sg = result.get("strategy_groups") or {}
    rec = {
        "symbol": symbol, "ts": int(ts), "close": close, "pip": pip,
        "atr_pips": _g(result, "volatility_protection", "atr_pips"),
        "spread_pips": _g(result, "global_anticheat", "spread_pips"),
        "analysis_direction": _g(result, "direction_decision", "analysis_direction")
        or _g(result, "directional_analysis", "best_direction"),
        "direction": _g(result, "direction_decision", "traded_direction")
        or _g(result, "directional_analysis", "best_direction"),
        "executed_direction": (result.get("config") or {}).get("executed_direction"),
        "calibrated_decision": result.get("calibrated_decision"),
        "probability": fv.get("probability_percent"),
        "should_enter": bool(ea.get("should_enter")),
        "decision": str(ea.get("final_decision") or fv.get("verdict") or "")[:80],
        "sg_final": sg.get("final_probability"),
        "sg_other": _g(sg, "other_side", "final_probability"),
        "sg_winner": sg.get("winner"),
        "sg_opposed": sg.get("most_opposed"),
        "sg_scores": {g: v.get("score") for g, v in (sg.get("groups") or {}).items()
                      if isinstance(v, Mapping) and v.get("scored")},
        "sg_context": sg.get("context_total"),
        "cost": sg.get("cost"),
        "conviction": _g(result, "conviction", "conviction_score"),
        "entry": fv.get("entry_price") or ed.get("entry_price"),
        "stop": fv.get("stop_loss") or ed.get("stop_loss"),
        "target": fv.get("take_profit_1") or ed.get("take_profit_1"),
        "regime": _g(result, "volatility_protection", "trading_regime", "state"),
        # the entry rule table (core/entry_engine.py): every rule's verdict on
        # this decision as [passed, value], blocking or not
        "entry_status": ea.get("entry_status"),
        "entry_rules": {name: [r.get("passed"), r.get("value")]
                        for name, r in (ea.get("rules") or {}).items() if isinstance(r, Mapping)},
        "blocked_by": ea.get("blocked_by"),
        "veto": _g(result, "vetos", "reason") if _g(result, "vetos", "triggered") else None,
        # the strategy that decided and the setup it trades (core/strategy_setups.py)
        "strategy": _g(fv, "strategy", "name"),
        "setup": {k: _g(fv, "strategy_setup", k) for k in ("name", "valid", "has_setups", "net_risk_reward")},
        "stop_source": fv.get("stop_source"),
        "final_decision": str(ea.get("final_decision") or "")[:80],
    }
    if payload is not None:
        rec["members"] = member_readings(payload)
        rec["num"] = numeric_leaves({k: payload.get(k) for k in payload if k not in ("entry_details",)})
    if CAPTURE_FULL:
        rec["full"] = full_leaves(result)
    return rec


def raw_paths(symbol: str, out_dir: Optional[Path] = None) -> List[Path]:
    """Every unlabelled file of a symbol: the main one and any shards.

    out_dir defaults to STUDY_DIR at CALL time: bound at definition it kept
    pointing at the original directory after STUDY_DIR was redirected, so
    ai/decision_replay labelled the full capture instead of its own records."""
    out_dir = out_dir or STUDY_DIR
    return sorted([p for p in [out_dir / f"{symbol}.jsonl.gz"] if p.exists()]
                  + list(out_dir.glob(f"{symbol}.s*of*.jsonl.gz")))


def run_symbol(symbol: str, step_minutes: int = STEP_MINUTES, limit: Optional[int] = None,
               out_dir: Optional[Path] = None, shard: Tuple[int, int] = (0, 1)) -> Dict[str, Any]:
    """Walk one symbol; appends to <out_dir>/<symbol>.jsonl.gz (or a shard file
    <symbol>.s<k>of<n>.jsonl.gz holding every n-th decision time), skipping
    timestamps any file of the symbol already holds."""
    logging.disable(logging.WARNING)
    out_dir = out_dir or STUDY_DIR
    import core.asset_analysis as aa
    from core.mt5_shim import replay_context, ShimStats

    out_dir.mkdir(parents=True, exist_ok=True)
    k, n_shards = shard
    path = out_dir / (f"{symbol}.jsonl.gz" if n_shards == 1 else f"{symbol}.s{k}of{n_shards}.jsonl.gz")
    done = set()
    for existing in raw_paths(symbol, out_dir):
        try:
            with gzip.open(existing, "rt") as fh:
                for line in fh:
                    done.add(json.loads(line)["ts"])
        except (EOFError, OSError, json.JSONDecodeError):
            pass    # a torn last line from a killed run; what parsed is kept

    specs = symbol_specs()
    histories = {s: load_history(s) for s in SYMBOLS}
    feed = build_feed(symbol, histories, specs)
    m1 = histories[symbol]["M1"]
    times = m1["time"].astype(np.int64)

    captured: Dict[str, Any] = {}
    original = aa.score_groups

    def spy(payload, direction, **kwargs):
        # keyword arguments pass through (only=, the strategy selection): a spy
        # that dropped them raised inside the analysis, which then recorded no
        # strategy group at all for every replayed decision
        captured.setdefault("payload", payload)
        return original(payload, direction, **kwargs)

    aa.score_groups = spy
    stats = {"symbol": symbol, "written": 0, "skipped_done": 0, "errors": 0, "no_data": 0}
    started = time.time()
    last_error = None
    with gzip.open(path, "at") as fh:
        for i in range(WARMUP_M1_BARS, len(times) - 1):
            bar_close = int(times[i]) + 60
            if bar_close % (step_minutes * 60) or (bar_close // (step_minutes * 60)) % n_shards != k:
                continue
            if bar_close in done:
                stats["skipped_done"] += 1
                continue
            md = feed.at(bar_close)
            if md is None:
                stats["no_data"] += 1
                continue
            captured.clear()
            try:
                with replay_context(md, stats=ShimStats()):
                    result = aa.analyze_institutional_signal(
                        symbol=symbol, order_type="AUTO", fixed_trade_size_usd=200.0,
                        risk_per_trade=0.02, leverage=200, timeframe="M1", market_data=md)
            except Exception as exc:
                stats["errors"] += 1
                last_error = repr(exc)[:200]
                continue
            rec = snapshot_record(symbol, bar_close, result, captured.get("payload"),
                                  float(m1["close"][i]), specs[symbol]["pip"])
            fh.write(json.dumps(rec, default=str) + "\n")
            stats["written"] += 1
            if limit and stats["written"] >= limit:
                break
    aa.score_groups = original
    stats["seconds"] = round(time.time() - started, 1)
    stats["last_error"] = last_error
    return stats


# ============================================================
# OUTCOMES
# ============================================================

def first_barrier(high: np.ndarray, low: np.ndarray, start: float, distance: float) -> int:
    """+1 if price reached start+distance before start-distance, -1 the other
    way, 0 neither. A bar that spans both is 0 (order unknowable)."""
    if distance <= 0 or high.size == 0:
        return 0
    up = high >= start + distance
    dn = low <= start - distance
    iu = int(np.argmax(up)) if up.any() else None
    idn = int(np.argmax(dn)) if dn.any() else None
    if iu is None and idn is None:
        return 0
    if idn is None:
        return 1
    if iu is None:
        return -1
    return 1 if iu < idn else -1 if idn < iu else 0


def bracket_r(high, low, close_last, entry, stop, target, sign) -> Optional[Dict[str, Any]]:
    risk = abs(entry - stop)
    if risk <= 0 or high.size == 0:
        return None
    if sign > 0:
        hit_stop, hit_tgt = low <= stop, high >= target
    else:
        hit_stop, hit_tgt = high >= stop, low <= target
    i_s = int(np.argmax(hit_stop)) if hit_stop.any() else None
    i_t = int(np.argmax(hit_tgt)) if hit_tgt.any() else None
    if i_s is not None and (i_t is None or i_s <= i_t):
        return {"result": "STOP", "r": -1.0, "bars": i_s}
    if i_t is not None:
        return {"result": "TARGET", "r": round(abs(target - entry) / risk, 3), "bars": i_t}
    return {"result": "TIMEOUT", "r": round(sign * (close_last - entry) / risk, 3), "bars": int(high.size)}


def h1_atr_at(h1: Optional[np.ndarray], ts: int, bars: int = 14) -> Optional[float]:
    """ATR(14) of the H1 bars closed by ts."""
    if h1 is None:
        return None
    end = int(np.searchsorted(h1["time"].astype(np.int64), ts - 3600, side="right"))
    if end < bars + 1:
        return None
    h, l, c = h1["high"][end - bars:end], h1["low"][end - bars:end], h1["close"][end - bars - 1:end - 1]
    tr = np.maximum(h - l, np.maximum(abs(h - c), abs(l - c)))
    v = float(tr.mean())
    return v if v > 0 else None


# MT5 M1 bars are BID only. Around the broker rollover the spread explodes and
# the bid dips, so bid bars show short targets and long stops that real
# execution never touched. When tick-built quote bars exist (tick_bars: bid,
# ask and mid OHLC per minute, broker clock) outcomes use them instead.
QUOTE_DIR = Path(os.getenv("PRICE_QUOTE_DIR") or ROOT / "reports" / "cache" / "quotes")
QUOTE_FIELDS = ("time", "bid_open", "bid_high", "bid_low", "bid_close", "ask_open", "ask_high", "ask_low",
                "ask_close", "mid_high", "mid_low", "mid_close")


def load_quotes(symbol: str) -> Optional[Dict[str, np.ndarray]]:
    path = QUOTE_DIR / f"{symbol}.npz"
    if not path.exists():
        return None
    z = np.load(path)
    return {k: z[k] for k in QUOTE_FIELDS}


def quote_bracket(q: Mapping[str, np.ndarray], i0: int, bars: int, risk: float, reward: float,
                  sign: int) -> Optional[Dict[str, Any]]:
    """A bracket filled the way a broker fills it: BUY enters at the ask and
    its stop/target/timeout exit on the bid; SELL enters at the bid and exits
    on the ask. The spread is therefore inside `r`; commission is not."""
    if risk <= 0 or reward <= 0:
        return None
    sl = slice(i0, i0 + bars)
    if sign > 0:
        entry = float(q["ask_open"][i0])
        b = bracket_r(q["bid_high"][sl], q["bid_low"][sl], q["bid_close"][sl][-1], entry, entry - risk, entry + reward, 1)
    else:
        entry = float(q["bid_open"][i0])
        b = bracket_r(q["ask_high"][sl], q["ask_low"][sl], q["ask_close"][sl][-1], entry, entry + risk, entry - reward, -1)
    if b:
        b["entry"] = entry
    return b


COMMISSION_PER_LOT = 7.03   # USD round trip per FX/metal lot (core/strategy_groups.py)


def usd_per_price_unit_per_lot(symbol: str) -> Optional[float]:
    info = (symbol_specs().get(symbol) or {}).get("info") or {}
    if info.get("trade_tick_size") and info.get("trade_tick_value"):
        return info["trade_tick_value"] / info["trade_tick_size"]
    return None


def label_record_quotes(rec: Dict[str, Any], q: Mapping[str, np.ndarray],
                        h1_atr: Optional[float] = None,
                        usd_per_price_per_lot: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """label_record on tick-built quote bars: direction barriers and returns on
    the MID price (a spread spike moves bid and ask apart, not the mid), and
    brackets filled on the correct side of the book. None when the quotes do
    not cover the record."""
    ts = rec["ts"]
    qt = q["time"]
    i0 = int(np.searchsorted(qt, ts, side="left"))
    if i0 >= qt.size or qt[i0] - ts > 300:
        return None
    hi, lo, cl = q["mid_high"][i0:i0 + HORIZON_BARS], q["mid_low"][i0:i0 + HORIZON_BARS], q["mid_close"][i0:i0 + HORIZON_BARS]
    out: Dict[str, Any] = {"bars_ahead": int(hi.size), "source": "quotes"}
    atr, pip = rec.get("atr_pips"), rec.get("pip")
    mid0 = (float(q["bid_open"][i0]) + float(q["ask_open"][i0])) / 2
    out["quote_spread_pips"] = round(float(q["ask_open"][i0] - q["bid_open"][i0]) / pip, 2) if pip else None
    if hi.size >= HORIZON_BARS // 2 and isinstance(atr, (int, float)) and atr > 0 and pip:
        unit = atr * pip
        out["move_5atr"] = first_barrier(hi, lo, mid0, 5 * unit)
        out["move_2atr"] = first_barrier(hi, lo, mid0, 2 * unit)
        out["ret_30"] = round((cl[min(29, cl.size - 1)] - mid0) / unit, 3)
        out["ret_120"] = round((cl[min(119, cl.size - 1)] - mid0) / unit, 3)
    if h1_atr:
        hi_d, lo_d = q["mid_high"][i0:i0 + LONG_HORIZON_BARS], q["mid_low"][i0:i0 + LONG_HORIZON_BARS]
        if hi_d.size >= LONG_HORIZON_BARS // 2:
            out["h1_atr"] = h1_atr
            for k in (1, 2, 3):
                out[f"move_h1x{k}"] = first_barrier(hi_d, lo_d, mid0, k * h1_atr)
            out["ret_1440_h1atr"] = round(float((q["mid_close"][i0:i0 + LONG_HORIZON_BARS][-1] - mid0) / h1_atr), 3)
    if h1_atr and usd_per_price_per_lot:
        # The live market stop (core/market_stop.py): stop k x H1 ATR, target
        # a fixed R multiple, 24h. y_ms is the side whose trade reached its
        # target (+1 / -1), 0 when neither did -- the tradable direction.
        from core.market_stop import MARKET_STOP_H1_ATR_MULTIPLE, MARKET_TARGET_R
        risk = MARKET_STOP_H1_ATR_MULTIPLE * h1_atr
        spread0 = float(q["ask_open"][i0] - q["bid_open"][i0])
        risk = max(risk, 3.0 * spread0)
        for side, sign in (("buy", 1), ("sell", -1)):
            b = quote_bracket(q, i0, LONG_HORIZON_BARS, risk, MARKET_TARGET_R * risk, sign)
            if b:
                out[f"bracket_ms_{side}"] = b
        wins = [s for s, k in ((1, "bracket_ms_buy"), (-1, "bracket_ms_sell"))
                if (out.get(k) or {}).get("result") == "TARGET"]
        out["y_ms"] = wins[0] if len(wins) == 1 else 0
        out["commission_ms_r"] = round(COMMISSION_PER_LOT / (risk * usd_per_price_per_lot), 4)
    if not all(isinstance(rec.get(k), (int, float)) and rec.get(k) for k in ("entry", "stop", "target")):
        return out
    risk, reward = abs(rec["entry"] - rec["stop"]), abs(rec["target"] - rec["entry"])
    if risk <= 0 or reward <= 0 or hi.size == 0:
        return out
    for side, sign in (("buy", 1), ("sell", -1)):
        b = quote_bracket(q, i0, HORIZON_BARS, risk, reward, sign)
        if b:
            out[f"bracket_{side}"] = b
    d = str(rec.get("direction") or "").upper()
    if d in ("BUY", "SELL") and out.get(f"bracket_{d.lower()}"):
        out["bracket"] = out[f"bracket_{d.lower()}"]
    # commission only: the spread is already paid inside the quote bracket
    cost = (rec.get("cost") or {}).get("cost_r")
    if isinstance(cost, (int, float)) and pip:
        out["commission_r"] = round(max(0.0, cost - (rec.get("spread_pips") or 0.0) * pip / risk), 4)
        if out["quote_spread_pips"] is not None:
            out["cost_r"] = round(out["commission_r"] + out["quote_spread_pips"] * pip / risk, 4)
    return out


def relabel_outcomes(symbols: Iterable[str] = SYMBOLS) -> Dict[str, Any]:
    """Rewrite only `outcome` of already-labelled records from quote bars
    (edges are unchanged). Records the quotes do not cover are dropped, so no
    bid-bar outcome survives next to quote outcomes."""
    counts = {}
    for symbol in symbols:
        q = load_quotes(symbol)
        src = STUDY_DIR / f"{symbol}.labelled.jsonl.gz"
        if q is None or not src.exists():
            counts[symbol] = "no quotes" if q is None else "no labels"
            continue
        h1 = load_history(symbol).get("H1")
        usd = usd_per_price_unit_per_lot(symbol)
        tmp = src.with_suffix(".tmp")
        kept = dropped = 0
        with gzip.open(src, "rt") as fh, gzip.open(tmp, "wt") as out:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    break
                o = label_record_quotes(rec, q, h1_atr_at(h1, rec["ts"]), usd)
                if o is None:
                    dropped += 1
                    continue
                rec["outcome"] = o
                out.write(json.dumps(rec) + "\n")
                kept += 1
        os.replace(tmp, src)
        counts[symbol] = {"kept": kept, "dropped": dropped}
    return counts


def label_record(rec: Dict[str, Any], m1: Mapping[str, np.ndarray], times: np.ndarray,
                 h1_atr: Optional[float] = None) -> Dict[str, Any]:
    ts = rec["ts"]
    i0 = int(np.searchsorted(times, ts, side="left"))   # first bar opening at/after the decision
    hi = m1["high"][i0:i0 + HORIZON_BARS]
    lo = m1["low"][i0:i0 + HORIZON_BARS]
    cl = m1["close"][i0:i0 + HORIZON_BARS]
    out: Dict[str, Any] = {"bars_ahead": int(hi.size)}
    atr, pip, close = rec.get("atr_pips"), rec.get("pip"), rec.get("close")
    if hi.size >= HORIZON_BARS // 2 and isinstance(atr, (int, float)) and atr > 0 and pip:
        unit = atr * pip
        out["move_5atr"] = first_barrier(hi, lo, close, 5 * unit)
        out["move_2atr"] = first_barrier(hi, lo, close, 2 * unit)
        out["ret_30"] = round((cl[min(29, cl.size - 1)] - close) / unit, 3)
        out["ret_120"] = round((cl[min(119, cl.size - 1)] - close) / unit, 3)
    if h1_atr and close:
        hi_d = m1["high"][i0:i0 + LONG_HORIZON_BARS]
        lo_d = m1["low"][i0:i0 + LONG_HORIZON_BARS]
        cl_d = m1["close"][i0:i0 + LONG_HORIZON_BARS]
        if hi_d.size >= LONG_HORIZON_BARS // 2:
            out["h1_atr"] = h1_atr
            for k in (1, 2, 3):
                out[f"move_h1x{k}"] = first_barrier(hi_d, lo_d, close, k * h1_atr)
            out["ret_1440_h1atr"] = round(float((cl_d[-1] - close) / h1_atr), 3)
    d = str(rec.get("direction") or "").upper()
    if d in ("BUY", "SELL") and all(isinstance(rec.get(k), (int, float)) and rec.get(k) for k in ("entry", "stop", "target")):
        b = bracket_r(hi, lo, cl[-1] if cl.size else rec["entry"], rec["entry"], rec["stop"], rec["target"],
                      1 if d == "BUY" else -1)
        if b:
            out["bracket"] = b
        # The same stop and target distances mirrored onto both sides, so a
        # rule that picks the other side can be priced too.
        risk, reward = abs(rec["entry"] - rec["stop"]), abs(rec["target"] - rec["entry"])
        if risk > 0 and reward > 0 and hi.size:
            for side, sign in (("buy", 1), ("sell", -1)):
                b = bracket_r(hi, lo, cl[-1], close, close - sign * risk, close + sign * reward, sign)
                if b:
                    out[f"bracket_{side}"] = b
    return out


def iter_records(symbols: Iterable[str] = SYMBOLS, labelled: bool = True):
    for symbol in symbols:
        paths = [STUDY_DIR / f"{symbol}.labelled.jsonl.gz"] if labelled else raw_paths(symbol)
        for path in paths:
            if not path.exists():
                continue
            try:
                with gzip.open(path, "rt") as fh:
                    for line in fh:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            break
            except (EOFError, OSError):
                continue    # a file still being written ends mid-block


def _visible(m1: np.ndarray, times: np.ndarray, ts: int, bars: int = 1600) -> np.ndarray:
    """M1 bars closed by ts (the last `bars` of them)."""
    end = int(np.searchsorted(times, ts - 60, side="right"))
    return m1[max(0, end - bars):end]


def label(symbols: Iterable[str] = SYMBOLS) -> Dict[str, int]:
    """Outcomes plus the bar-computed edge features (core/edge_features)."""
    from core import edge_features

    all_m1 = {s: load_history(s)["M1"] for s in SYMBOLS}
    all_times = {s: m["time"].astype(np.int64) for s, m in all_m1.items()}
    all_h1 = {s: load_history(s).get("H1") for s in SYMBOLS}
    counts = {}
    for symbol in symbols:
        if not raw_paths(symbol):
            continue
        quotes = load_quotes(symbol)
        m1, times = all_m1[symbol], all_times[symbol]
        n = 0
        seen = set()
        with gzip.open(STUDY_DIR / f"{symbol}.labelled.jsonl.gz", "wt") as out:
            for rec in iter_records([symbol], labelled=False):
                ts = rec["ts"]
                if ts in seen:          # a shard and a plain run can overlap
                    continue
                seen.add(ts)
                h1_atr = h1_atr_at(all_h1[symbol], ts)
                if quotes is not None:
                    rec["outcome"] = label_record_quotes(rec, quotes, h1_atr, usd_per_price_unit_per_lot(symbol))
                    if rec["outcome"] is None:      # never mix bid-bar outcomes with quote outcomes
                        continue
                else:
                    rec["outcome"] = label_record(rec, m1, times, h1_atr)
                peers = {s: _visible(all_m1[s], all_times[s], ts) for s in SYMBOLS if s != symbol}
                rec["edges"] = edge_features.compute(symbol, _visible(m1, times, ts), peers, now_ts=ts,
                                                     clock_offset_seconds=BROKER_OFFSET_SECONDS)
                out.write(json.dumps(rec) + "\n")
                n += 1
        counts[symbol] = n
    return counts


def self_check() -> Dict[str, Any]:
    hi = np.array([1.0, 1.2, 1.6]); lo = np.array([0.9, 0.8, 1.0])
    assert first_barrier(hi, lo, 1.0, 0.5) == 1
    assert first_barrier(np.array([1.1]), np.array([0.4]), 1.0, 0.5) == -1
    assert first_barrier(np.array([1.6]), np.array([0.4]), 1.0, 0.5) == 0
    b = bracket_r(np.array([1.0, 1.3]), np.array([0.95, 1.0]), 1.3, 1.0, 0.9, 1.25, 1)
    assert b["result"] == "TARGET" and b["r"] == 2.5
    b = bracket_r(np.array([1.3]), np.array([0.85]), 1.0, 1.0, 0.9, 1.25, 1)
    assert b["result"] == "STOP"   # ambiguous bar -> stop first
    return {"ok": True}


def get_status() -> Dict[str, Any]:
    return {"component": "price_history_study", "symbols": len(SYMBOLS), "step_minutes": STEP_MINUTES}


def _run_worker(args):
    symbol, step, limit, shard = args
    try:
        return {**run_symbol(symbol, step, limit, shard=shard), "shard": list(shard)}
    except Exception as exc:
        return {"symbol": symbol, "fatal": repr(exc)[:300]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download")
    run = sub.add_parser("run")
    run.add_argument("--workers", type=int, default=8)
    run.add_argument("--step", type=int, default=STEP_MINUTES)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--symbols", nargs="*", default=SYMBOLS)
    run.add_argument("--shards", type=int, default=1, help="split each symbol across this many workers")
    sub.add_parser("label")
    sub.add_parser("relabel", help="rewrite outcomes of labelled records from tick quote bars")
    sub.add_parser("check")
    a = parser.parse_args()
    if a.cmd == "download":
        print(download())
    elif a.cmd == "run":
        from multiprocessing import Pool
        with Pool(a.workers) as pool:
            jobs = [(s, a.step, a.limit, (k, a.shards)) for s in a.symbols for k in range(a.shards)]
            for stats in pool.imap_unordered(_run_worker, jobs):
                print(json.dumps(stats), flush=True)
    elif a.cmd == "label":
        from multiprocessing import Pool
        with Pool(min(len(SYMBOLS), os.cpu_count() or 4)) as pool:
            for counts in pool.imap_unordered(label, [[s] for s in SYMBOLS]):
                print(counts, flush=True)
    elif a.cmd == "relabel":
        from multiprocessing import Pool
        with Pool(min(len(SYMBOLS), os.cpu_count() or 4)) as pool:
            for counts in pool.imap_unordered(relabel_outcomes, [[s] for s in SYMBOLS]):
                print(counts, flush=True)
    else:
        print(self_check())
