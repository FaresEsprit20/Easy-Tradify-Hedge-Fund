# ============================================================
# MARKET DATA INJECTION  /  HISTORICAL FEED
# ============================================================
# FILE: core/market_data.py
#
# analyze_institutional_signal() fetched its own data. It took a symbol
# and called mt5.account_info(), mt5.copy_rates_from_pos(),
# mt5.symbol_info_tick(), mt5.symbol_info(), get_h1_trend() and
# get_multi_timeframe_rates() internally. Hand it a bar from last March
# and it ignored you and pulled whatever the terminal had right now.
#
# That is why replay was impossible: there was no way in.
#
# This module supplies the way in. MarketData is a single container for
# everything the analysis fetches; pass it and the analysis uses it,
# omit it and every call falls through to MT5 exactly as before. Live
# behaviour is byte-identical because nothing passes it.
#
# ------------------------------------------------------------
# THE PART THAT IS EASY TO GET WRONG
# ------------------------------------------------------------
# Replaying an M1 decision correctly means also serving the M5/M15/H1/H4
# bars AS THEY STOOD at that M1 timestamp. Handing the engine a complete
# H1 bar while replaying a moment 12 minutes into that hour lets the H1
# alignment bonus read 48 minutes of future price. The backtest would
# look excellent and mean nothing.
#
# HistoricalFeed.at() therefore slices EVERY timeframe against the
# decision timestamp, and drops any higher-timeframe bar that had not
# yet CLOSED at that moment. That is stricter than slicing on start time
# and it is the correct rule: a live system at 15:12 can see the H1 bar
# that closed at 15:00, not the one that will close at 16:00.
# ============================================================

from typing import Any, Dict, List, Optional
import logging

import numpy as np

logger = logging.getLogger(__name__)


# Bar duration in seconds, used to decide whether a higher-timeframe bar
# had closed by the decision timestamp.
# Minimum closed bars before a higher timeframe is served at all.
MIN_HTF_BARS = 150

# ✅ Per-timeframe override of the minimum above.
#
# A single bar count cannot serve every timeframe. The threshold exists to
# stop a THIN slice producing a frozen default that still feeds a bonus (see
# the get_h1_trend note in HistoricalFeed.at), so the right number is "enough
# for the consumers of THAT timeframe" -- and that differs by an order of
# magnitude between H1 and D1.
#
# 150 D1 bars is roughly seven months of daily history per replayed decision.
# The only D1 consumer in the chain is adr_exhaustion.check_adr_exhaustion,
# which asks for ADR_LOOKBACK_DAYS + 1 = 21 bars and already reports
# available: False below that -- so the flat 150 was not protecting anything,
# it was making D1 unreachable. Measured during enrichment before this
# change: D1 requested 1,212 times, served 0.
#
# Anything not listed keeps MIN_HTF_BARS, so H1/H4/M15 behaviour is unchanged.
MIN_HTF_BARS_BY_TF = {
    "D1": 30,
}

TF_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800,
}


class SimTick:
    """Stand-in for mt5.symbol_info_tick()."""
    __slots__ = ("bid", "ask", "last", "volume", "time")

    def __init__(self, bid, ask, time=None, last=None, volume=0):
        self.bid = float(bid)
        self.ask = float(ask)
        self.last = float(last) if last is not None else float(bid)
        self.volume = volume
        self.time = time


class SimSymbolInfo:
    """
    Stand-in for mt5.symbol_info().

    Defaults are deliberately conservative rather than permissive: a
    replay that silently assumes a tighter spread or a smaller contract
    than reality produces results that are better than reality.
    """
    def __init__(self, **kw):
        self.name = kw.get("name", "")
        self.digits = kw.get("digits", 3)
        self.point = kw.get("point", 0.001)
        self.spread = kw.get("spread", 0)
        self.trade_contract_size = kw.get("trade_contract_size", 5000.0)
        self.volume_min = kw.get("volume_min", 0.01)
        self.volume_max = kw.get("volume_max", 100.0)
        self.volume_step = kw.get("volume_step", 0.01)
        self.trade_tick_value = kw.get("trade_tick_value", 5.0)
        self.trade_tick_size = kw.get("trade_tick_size", 0.001)
        self.trade_stops_level = kw.get("trade_stops_level", 0)
        for k, v in kw.items():
            setattr(self, k, v)


class SimAccountInfo:
    """Stand-in for mt5.account_info()."""
    def __init__(self, balance=10000.0, equity=None, margin_free=None,
                 leverage=200, currency="USD"):
        self.balance = float(balance)
        self.equity = float(equity if equity is not None else balance)
        self.margin_free = float(margin_free if margin_free is not None else balance)
        self.margin = 0.0
        self.leverage = int(leverage)
        self.currency = currency


class TickFeed:
    """
    Historical ticks, served as of a decision timestamp.

    WHY THIS EXISTS

    analyze_micro_structure() (core/indicators.py) is the only reader of
    real order flow in this system, and it drives the timing_confidence
    gate. It fetches with:

        mt5.copy_ticks_from(symbol, datetime.now(), 200, COPY_TICKS_ALL)

    -- wall-clock `now`, which during a replay of the past is either the
    live present (lookahead) or nothing at all. core/mt5_shim.py served
    None to close that hole, which was correct but left the gate
    permanently unmeasurable: timing_confidence pinned at neutral on
    88.4% of decisions and 0 of 65 candidates ever passing it.

    This restores the gate honestly. The shim ignores the caller's
    `now` -- it is meaningless in replay -- and serves the last N ticks
    at or before the decision timestamp instead.

    NO LOOKAHEAD

    The cut is `time <= decision_timestamp`, found by binary search on a
    time-sorted array. A tick one millisecond after the decision is not
    served, because a live system could not have seen it. This is the
    same rule HistoricalFeed applies to higher-timeframe bars, for the
    same reason.

    Ticks are memory-mapped rather than loaded: 30 days of XAGUSD is
    ~4.6M rows, and the replay only ever reads a few hundred of them per
    decision.
    """

    __slots__ = ("ticks", "_times", "symbol", "stats")

    def __init__(self, ticks, symbol: str = ""):
        self.ticks = ticks
        self.symbol = symbol
        # Cached separately: the structured array's field access is slow
        # enough to matter when it is binary-searched once per decision.
        self._times = np.asarray(ticks["time"], dtype="int64") if ticks is not None else None
        self.stats = {"served": 0, "empty": 0, "requests": 0}

    def __len__(self):
        return 0 if self.ticks is None else len(self.ticks)

    def before(self, timestamp: float, count: int = 200):
        """
        The last `count` ticks at or before `timestamp`, or None.

        None -- not an empty array -- when nothing qualifies, because
        that is what MT5 returns on failure and what the consuming code
        already has a documented path for.
        """
        self.stats["requests"] += 1
        if self.ticks is None or self._times is None or len(self._times) == 0:
            self.stats["empty"] += 1
            return None

        end = int(np.searchsorted(self._times, int(timestamp), side="right"))
        if end <= 0:
            self.stats["empty"] += 1
            return None

        start = max(0, end - int(count))
        out = self.ticks[start:end]
        if len(out) == 0:
            self.stats["empty"] += 1
            return None
        self.stats["served"] += 1
        return out

    @classmethod
    def load(cls, path: str, symbol: str = ""):
        """Memory-map a cached tick file, or None if there isn't one."""
        try:
            return cls(np.load(path, mmap_mode="r"), symbol=symbol)
        except FileNotFoundError:
            logger.debug(f"[TICKS] no tick cache at {path} -- micro-structure "
                         f"will report unavailable, as before")
            return None
        except Exception as e:
            logger.warning(f"[TICKS] tick cache at {path} is unusable: {e}")
            return None


class MarketData:
    """
    Everything analyze_institutional_signal() would otherwise fetch.

    Any field left None falls through to the live MT5 call, so this can
    be used to override one input (say, rates) while letting the rest
    come from the terminal. Partial injection is genuinely useful for
    debugging a single bar against live account state.
    """
    __slots__ = ("rates", "tick", "info", "account", "multi_tf_rates",
                 "h1_data", "decision_timestamp", "source", "tick_feed",
                 "symbol", "peers", "base_timeframe", "edge_m1")

    def __init__(self, rates=None, tick=None, info=None, account=None,
                 multi_tf_rates=None, h1_data=None,
                 decision_timestamp=None, source="injected", tick_feed=None,
                 symbol="", peers=None, base_timeframe="M1"):
        self.rates = rates
        # Which timeframe self.rates actually IS.
        #
        # Consumers short-circuit on `market_data.rates` before their own
        # timeframe selection runs (asset_analysis.py does exactly this),
        # so without this attribute a replay of an M15 strategy silently
        # analyses M1 bars while the live path honours the request. The
        # divergence is invisible: same field, same shape, same plausible
        # numbers, wrong timeframe. Callers can now check before they
        # take the short-circuit.
        self.base_timeframe = str(base_timeframe or "M1").upper()
        self.tick = tick
        self.info = info
        self.account = account
        self.multi_tf_rates = multi_tf_rates or {}
        self.h1_data = h1_data
        self.decision_timestamp = decision_timestamp
        self.source = source
        # A TickFeed, when tick history has been cached. Left None
        # otherwise, which keeps the shim serving None for
        # copy_ticks_from exactly as it did before -- micro-structure
        # then reports unavailable rather than guessing.
        self.edge_m1 = None      # optional longer M1 slice for edge features (replay only)
        self.tick_feed = tick_feed
        # Which instrument this data actually describes. core/mt5_shim.py
        # checks every symbol_info / symbol_info_tick call against it and
        # returns None for a foreign symbol, instead of silently handing
        # back this instrument's data -- the GNN requests ticks for
        # CORRELATED symbols, and without this it received the replayed
        # symbol's tick for every one of them.
        self.symbol = str(symbol or "").upper()
        # Other instruments visible at this same timestamp, as
        # {SYMBOL: {"tick": SimTick, "info": SimSymbolInfo, "rates": arr}}.
        #
        # Cross-asset components -- the GNN above all -- ask MT5 about
        # OTHER symbols to build a correlation graph. Without this they
        # get None for every peer (after the symbol-aware shim fix) or,
        # before it, the replayed symbol's own data for every peer, which
        # makes every correlation 1.0 by construction. Neither is a
        # measurement. This is how a replay serves a real peer set.
        self.peers = peers or {}

    def __repr__(self):
        n = len(self.rates) if self.rates is not None else 0
        return (f"<MarketData {self.source} bars={n} "
                f"ts={self.decision_timestamp} tfs={sorted(self.multi_tf_rates)}>")


def _field(row, name, index):
    """Read a bar field from a numpy structured row or a plain sequence."""
    try:
        return float(row[name])
    except (KeyError, ValueError, IndexError, TypeError):
        pass
    try:
        return float(row[index])
    except (IndexError, TypeError, ValueError, KeyError):
        return None


class HistoricalFeed:
    """
    Serves MarketData for any historical timestamp, with no lookahead.

    Construct it once with the full history per timeframe, then call
    at(timestamp) per decision. Every slice is cut at the decision
    timestamp; higher-timeframe bars that had not closed yet are dropped.
    """

    def __init__(self, rates_by_tf: Dict[str, Any], *, symbol: str = "",
                 base_timeframe: str = "M1", spread_pips: float = None,
                 pip_size: float = 0.001, balance: float = 10000.0,
                 leverage: int = 200, info_kwargs: Dict[str, Any] = None,
                 max_bars: int = 1000, tick_feed: "TickFeed" = None):
        if base_timeframe not in rates_by_tf:
            raise ValueError(
                f"base_timeframe {base_timeframe!r} missing from rates_by_tf "
                f"(have: {sorted(rates_by_tf)})"
            )
        self.rates_by_tf = rates_by_tf
        # Normalised so the shim's symbol comparison is case-insensitive.
        self.symbol = str(symbol or "").upper()
        self.tick_feed = tick_feed
        self.base_timeframe = base_timeframe
        self.spread_pips = spread_pips
        self.pip_size = pip_size
        self.max_bars = max_bars
        self.balance = balance
        self.leverage = leverage
        self.info_kwargs = dict(info_kwargs or {})
        self.info_kwargs.setdefault("name", symbol)
        self.info_kwargs.setdefault("point", pip_size)

        self._times = {
            tf: [_field(r, "time", 0) for r in arr]
            for tf, arr in rates_by_tf.items()
        }
        self.stats = {"decisions_served": 0, "htf_bars_dropped": 0}

    # ---------- slicing ----------

    def _slice(self, tf: str, ts: float):
        """
        Bars of `tf` visible at `ts`.

        A bar is visible only if it had CLOSED by ts -- bar_time +
        duration <= ts. Slicing on start time instead would hand the
        engine a completed higher-timeframe bar whose remaining minutes
        are still in the future.
        """
        arr = self.rates_by_tf.get(tf)
        if arr is None:
            return None
        times = self._times[tf]
        duration = TF_SECONDS.get(tf.upper(), 60)

        end = 0
        for i, t in enumerate(times):
            if t is None:
                continue
            if t + duration <= ts:
                end = i + 1
            else:
                self.stats["htf_bars_dropped"] += 1
                break
        if end == 0:
            return None
        start = max(0, end - self.max_bars)
        return arr[start:end]

    # ---------- serving ----------

    def at(self, ts: float, *, h1_data=None) -> Optional[MarketData]:
        """MarketData as it stood at `ts`, or None if there isn't enough."""
        base = self._slice(self.base_timeframe, ts)
        if base is None or len(base) < 200:
            return None

        last = base[-1]
        close = _field(last, "close", 4)
        if close is None:
            return None

        spread_pips = self.spread_pips
        if spread_pips is None:
            raw = _field(last, "spread", 6)
            # MT5 reports a bar's spread in POINTS, not pips. On any 3- or
            # 5-digit instrument 1 pip = 10 points, so reading the field
            # directly overstates the spread TENFOLD.
            #
            # It went unnoticed because the first instrument replayed was
            # XAGUSD, where the live engine's get_pip_info() returns
            # pip_size == point (0.001) and the two units coincide -- so
            # 24 points really was 24 pips and every number checked out.
            # The first EURUSD run then reported a median spread/stop of
            # 1.017 with "spread exceeds stop" on 100% of decisions, on
            # an instrument whose actual bar spread is 0.0.
            #
            # Converting through point/pip_size is exact for both cases
            # and needs no per-symbol special-casing: the ratio is 1 when
            # pips and points coincide and 0.1 when they do not.
            points_per_pip = 1.0
            point = self.info_kwargs.get("point")
            if point and self.pip_size and point > 0:
                points_per_pip = self.pip_size / point
            spread_pips = (raw / points_per_pip) if raw is not None else 0.0
        half = (spread_pips * self.pip_size) / 2.0

        multi = {}
        for tf in self.rates_by_tf:
            if tf == self.base_timeframe:
                multi[tf] = base
                continue
            sliced = self._slice(tf, ts)
            # 150, not 50. get_h1_trend() silently returns
            # {"trend": "NEUTRAL", "adx": 0} when it has fewer than 100 H1
            # bars -- so a thin slice does not fail, it produces a frozen
            # NEUTRAL trend that still feeds the +10 H1 alignment bonus.
            # The first real replay showed h1_trend NEUTRAL on 100/100
            # decisions for exactly this reason. Dropping the timeframe is
            # honest; serving 60 bars is not.
            minimum = MIN_HTF_BARS_BY_TF.get(tf.upper(), MIN_HTF_BARS)
            if sliced is not None and len(sliced) >= minimum:
                multi[tf] = sliced
            elif sliced is not None:
                self.stats.setdefault("thin_timeframes", {})
                self.stats["thin_timeframes"][tf] = len(sliced)

        self.stats["decisions_served"] += 1
        return MarketData(
            rates=base,
            tick=SimTick(bid=close - half, ask=close + half, time=ts),
            info=SimSymbolInfo(**self.info_kwargs),
            account=SimAccountInfo(balance=self.balance, leverage=self.leverage),
            multi_tf_rates=multi,
            h1_data=h1_data,
            decision_timestamp=ts,
            source="historical",
            base_timeframe=self.base_timeframe,
            tick_feed=self.tick_feed,
            symbol=self.symbol,
        )

    def timestamps(self, *, warmup_bars: int = 300, step: int = 1) -> List[float]:
        """
        Decision timestamps to walk, skipping warmup.

        Uses the CLOSE time of each base bar, because that is the moment
        a live system would first see it complete.
        """
        times = self._times[self.base_timeframe]
        duration = TF_SECONDS.get(self.base_timeframe.upper(), 60)
        return [t + duration for t in times[warmup_bars::step] if t is not None]

    def verify_no_lookahead(self, ts: float, md: MarketData) -> List[str]:
        """
        Assert every served bar closed at or before ts.

        Called by the tests rather than the hot loop; a lookahead bug
        that only the tests can see is a lookahead bug that ships.
        """
        problems = []
        for tf, arr in (md.multi_tf_rates or {}).items():
            if arr is None or len(arr) == 0:
                continue
            duration = TF_SECONDS.get(tf.upper(), 60)
            last_close = _field(arr[-1], "time", 0)
            if last_close is None:
                continue
            if last_close + duration > ts:
                problems.append(
                    f"{tf}: last bar opens {last_close}, closes "
                    f"{last_close + duration} -- after decision ts {ts}"
                )
        return problems

class MultiSymbolFeed:
    """
    One primary instrument plus its correlated peers, all sliced to the
    same decision timestamp.

    WHY THIS EXISTS

    The GNN is the only component in this system whose premise is not
    ruled out by the project's own measurements. Direction on a single
    series measures at entropy 1.0000 -- a fair coin at every timeframe
    on both instruments tested -- and every one of nineteen components
    scored |correlation| < 0.05 against outcomes. But every one of those
    tests asked the same question: does this series predict ITSELF?
    Cross-asset structure was never tested, because a single-symbol
    replay cannot test it.

    It could not even fail honestly. mt5.symbol_info_tick() ignored its
    symbol argument, so the GNN's request for each correlated peer
    returned the REPLAYED symbol's tick -- every peer identical to the
    primary, every correlation 1.0 by construction. The component would
    have looked alive while measuring nothing.

    NO LOOKAHEAD, PER SYMBOL

    Each peer is sliced by the same rule as the primary: bars that had
    CLOSED at the decision timestamp, nothing after. A peer with no data
    at that moment is simply absent from the peer set rather than
    back-filled, because a peer that had not printed yet is one a live
    system could not have seen either.
    """

    def __init__(self, primary: "HistoricalFeed",
                 peers: Dict[str, "HistoricalFeed"] = None):
        self.primary = primary
        self.peers = dict(peers or {})
        self.stats = {"decisions": 0, "peers_served": 0, "peers_missing": 0}

    # ---- delegation -------------------------------------------
    # replay_engine reads the feed's bar arrays and pip settings
    # directly, so a MultiSymbolFeed has to look like a HistoricalFeed
    # for those. Forwarding explicitly (rather than via __getattr__)
    # keeps the surface visible: anything the engine needs and this does
    # not forward fails loudly at the attribute rather than silently
    # taking a different code path.

    @property
    def symbol(self) -> str:
        return self.primary.symbol

    @property
    def rates_by_tf(self):
        return self.primary.rates_by_tf

    @property
    def base_timeframe(self) -> str:
        return self.primary.base_timeframe

    @property
    def pip_size(self) -> float:
        return self.primary.pip_size

    @property
    def spread_pips(self):
        return self.primary.spread_pips

    @property
    def tick_feed(self):
        return self.primary.tick_feed

    def verify_no_lookahead(self, ts, md):
        return self.primary.verify_no_lookahead(ts, md)

    def timestamps(self, **kw) -> List[float]:
        return self.primary.timestamps(**kw)

    def at(self, ts: float, *, h1_data=None) -> Optional[MarketData]:
        """MarketData for the primary, carrying every peer visible at ts."""
        md = self.primary.at(ts, h1_data=h1_data)
        if md is None:
            return None

        peer_block: Dict[str, Dict[str, Any]] = {}
        for name, feed in self.peers.items():
            peer_md = feed.at(ts)
            if peer_md is None:
                self.stats["peers_missing"] += 1
                continue
            peer_block[name.upper()] = {
                "tick": peer_md.tick,
                "info": peer_md.info,
                "rates": peer_md.rates,
                # Multi-timeframe too: the GNN pulls H1 and M5 bars per
                # peer (copy_rates_from_pos), not just a tick. Serving
                # only the tick would leave those calls falling back to
                # the PRIMARY symbol's bars -- the same substitution the
                # symbol-aware shim exists to prevent, one function over.
                "multi_tf_rates": peer_md.multi_tf_rates or {},
            }
            self.stats["peers_served"] += 1

        md.peers = peer_block
        self.stats["decisions"] += 1
        return md
