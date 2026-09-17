"""
The monitor's scan loop (monitor/monitor_core.py), 2026-09-17:

  * a refresh that times out keeps the symbols it did not hear back from,
    instead of emptying the watch list;
  * each 5-second step checks the least recently checked symbols first, so
    the whole watch list is checked for entry, not only the top three;
  * a click in a service's console window cannot freeze the process
    (core/console_safe.disable_quick_edit).
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from core import console_safe
from monitor.monitor_core import MultiSymbolMonitor, SymbolStatus


def _bare_monitor():
    m = MultiSymbolMonitor.__new__(MultiSymbolMonitor)
    m._state_lock = threading.RLock()
    m._refresh_lock = threading.Lock()
    m._fast_entry_lock = threading.Lock()
    m._executed_lock = threading.Lock()
    m._reanalysis_lock = threading.Lock()
    m._refreshing = False
    m.stop_event = threading.Event()
    m.filtered_symbols = set()
    m.open_positions = {}
    m.top_symbols = []
    m.symbol_status_map = {}
    m.stats = {}
    m._fast_entry_symbols = set()
    m._executed_recently = set()
    m._executing_symbols = set()
    m._reanalysis_queue = []
    m._filter_pool = ThreadPoolExecutor(max_workers=4)
    m._monitor_pool = ThreadPoolExecutor(max_workers=3)
    return m


def test_a_timed_out_refresh_keeps_the_symbols_it_did_not_hear_from(monkeypatch):
    m = _bare_monitor()
    m.REFRESH_TIMEOUT_SECONDS = 1
    m.FILTER_THREADS = 4
    m.filtered_symbols = {"EURUSD", "GBPUSD", "USDCAD"}
    m.top_symbols = [SymbolStatus(symbol="EURUSD", confidence=78.0, is_active=True, last_check_time=1.0)]
    release = threading.Event()

    def check(symbol):
        if symbol == "EURUSD":
            release.wait(5)                      # slower than the refresh waits
            return {"symbol": symbol, "overall_confidence": 90.0}
        return {"symbol": symbol, "overall_confidence": {"GBPUSD": 80.0, "USDCAD": 40.0}[symbol]}

    monkeypatch.setattr(m, "_check_confidence", check)
    try:
        top = m._refresh_top_symbols()
    finally:
        release.set()
        m._filter_pool.shutdown(wait=True)
    listed = {s.symbol for s in m.top_symbols}
    assert {s["symbol"] for s in top} == {"GBPUSD"}
    assert listed == {"GBPUSD", "EURUSD"}        # USDCAD reported 40%: dropped; EURUSD did not report: kept


def test_a_symbol_that_left_the_filter_is_not_kept():
    m = _bare_monitor()
    m.REFRESH_TIMEOUT_SECONDS = 1
    m.FILTER_THREADS = 4
    m.filtered_symbols = {"GBPUSD"}
    m.top_symbols = [SymbolStatus(symbol="EURUSD", confidence=78.0, is_active=True)]
    m._check_confidence = lambda symbol: {"symbol": symbol, "overall_confidence": 70.0}
    try:
        m._refresh_top_symbols()
    finally:
        m._filter_pool.shutdown(wait=True)
    assert {s.symbol for s in m.top_symbols} == {"GBPUSD"}


def test_each_step_checks_the_least_recently_checked_symbols_first(monkeypatch):
    m = _bare_monitor()
    m.MONITOR_THREADS = 3
    m.SYMBOL_COOLDOWN = 5
    m.STALE_SYMBOL_THRESHOLD = 10 ** 9
    now = time.time()
    # seconds since the last check; confidence order is A > B > C > D > E, so the
    # old step checked A, B and C every time and never reached D or E
    ages = {"A": 80, "B": 90, "C": 100, "D": 10_000, "E": 5_000}
    m.top_symbols = [SymbolStatus(symbol=k, confidence=90 - i, is_active=True, last_check_time=now - age)
                     for i, (k, age) in enumerate(ages.items())]
    m.symbol_status_map = {s.symbol: s for s in m.top_symbols}
    checked = []
    monkeypatch.setattr(m, "_sync_open_positions", lambda: None)
    monkeypatch.setattr(m, "_monitor_worker", lambda symbol: checked.append(symbol) or {"should_enter": False})
    try:
        m._run_monitor_step()
    finally:
        m._monitor_pool.shutdown(wait=True)
    assert sorted(checked) == ["C", "D", "E"]      # the two waiting longest, then the oldest of A-C


def test_disabling_quick_edit_never_raises_and_needs_a_console(monkeypatch):
    assert isinstance(console_safe.disable_quick_edit(), bool)
    monkeypatch.setattr(console_safe.sys, "platform", "linux")
    assert console_safe.disable_quick_edit() is False
    assert "quick_edit_disabled" in console_safe.install()
