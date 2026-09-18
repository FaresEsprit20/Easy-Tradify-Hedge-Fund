"""
Which costs does the logged-in MT5 account really charge? (2026-09-18)

The operator opened a new demo (login 53059485) and is not sure whether it is a
Raw Spread account (tight spread + ~$7/lot commission) or a Standard one (no
commission, wider spread). symbols.json assumes Raw. This script measures it:

  1. refuses to run unless the account is a DEMO
  2. places ONE 0.01-lot EURUSD market BUY and closes it at once (magic 20260921);
     reads the commission MT5 booked on both deals
  3. samples the live bid/ask of the 15 FX pairs for 10 minutes
  4. writes reports/account_costs_<login>.json
  5. if the booked commission is zero, sets commission_usd_per_lot_round_trip to 0
     in engine_v2/data/symbols.json (the spread then carries the whole cost) and
     restarts the services so every process reads it

Run it during normal hours (not the 21:00 UTC rollover, not the weekend).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCAD",
           "AUDNZD", "AUDCAD", "AUDCHF", "GBPAUD", "GBPJPY", "EURJPY"]
MAGIC = 20260921
SAMPLE_SECONDS = 600


def _filling(mt5, info):
    fm = info.filling_mode
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def test_trade(mt5) -> dict:
    sym = "EURUSD"
    info = mt5.symbol_info(sym)
    tick = mt5.symbol_info_tick(sym)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": 0.01, "type": mt5.ORDER_TYPE_BUY,
           "price": tick.ask, "deviation": 20, "magic": MAGIC, "comment": "cost check",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling(mt5, info)}
    t0 = int(time.time()) - 60
    r = mt5.order_send(req)
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        return {"ok": False, "stage": "open", "retcode": getattr(r, "retcode", None), "comment": getattr(r, "comment", None)}
    time.sleep(2)
    pos = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
    closed = None
    for p in pos:
        tick = mt5.symbol_info_tick(sym)
        closed = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": p.volume,
                                 "type": mt5.ORDER_TYPE_SELL, "position": p.ticket, "price": tick.bid,
                                 "deviation": 20, "magic": MAGIC, "comment": "cost check close",
                                 "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling(mt5, info)})
    time.sleep(3)
    deals = [d for d in (mt5.history_deals_get(t0, int(time.time()) + 3600) or []) if d.magic == MAGIC]
    return {"ok": closed is not None and closed.retcode == mt5.TRADE_RETCODE_DONE,
            "deals": [{"ticket": d.ticket, "entry": d.entry, "price": d.price, "volume": d.volume,
                       "commission": d.commission, "fee": d.fee, "profit": d.profit} for d in deals],
            "commission_usd_round_trip_0.01": round(sum(d.commission + d.fee for d in deals), 4)}


def sample_spreads(mt5, seconds: int) -> dict:
    import numpy as np
    got = {s: [] for s in SYMBOLS}
    end = time.time() + seconds
    while time.time() < end:
        for s in SYMBOLS:
            t = mt5.symbol_info_tick(s)
            if t is not None and t.ask > t.bid:
                got[s].append((t.ask - t.bid) / (0.01 if s.endswith("JPY") else 0.0001))
        time.sleep(2)
    return {s: {"median_pips": round(float(np.median(v)), 3), "samples": len(v)} for s, v in got.items() if v}


def restart_services():
    ps = r"""
$names = 'hybrid_monitor|execution_controller|execute_copy_trade|engine_v2.run.shadow|ai.data_jobs'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match $names } | ForEach-Object {
  $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.ParentProcessId)" -ErrorAction SilentlyContinue
  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
  if ($parent -and $parent.Name -eq 'cmd.exe') { try { Stop-Process -Id $parent.ProcessId -Force -ErrorAction Stop } catch {} }
}
Start-Sleep -Seconds 3
schtasks /run /tn "Tradify\StartServices"
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=20000):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        acc = mt5.account_info()
        if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise SystemExit("not a demo account -- refusing to place the test trade")
        report = {"at": int(time.time()), "login": acc.login, "server": acc.server, "leverage": acc.leverage}
        report["test_trade"] = test_trade(mt5)
        report["spreads"] = sample_spreads(mt5, SAMPLE_SECONDS)
    finally:
        mt5.shutdown()

    comm = report["test_trade"].get("commission_usd_round_trip_0.01")
    if report["test_trade"].get("ok") and comm is not None and abs(comm) < 1e-9:
        report["account_type"] = "STANDARD (no commission)"
        path = ROOT / "engine_v2" / "data" / "symbols.json"
        data = json.loads(path.read_text())
        for s in data["symbols"].values():
            s["commission_usd_per_lot_round_trip"] = 0.0
        data["commission_note"] = (f"account {acc.login} measured {time.strftime('%Y-%m-%d')}: no commission "
                                   f"(Standard); the spread carries the cost")
        path.write_text(json.dumps(data, indent=1))
        report["symbols_json"] = "commission set to 0; services restarted"
        restart_services()
    elif report["test_trade"].get("ok"):
        report["account_type"] = f"RAW (commission {comm} USD per 0.01 lot round trip)"
        report["symbols_json"] = "unchanged"
    else:
        report["account_type"] = "UNKNOWN (the test trade did not complete)"
        report["symbols_json"] = "unchanged"
    out = ROOT / "reports" / f"account_costs_{acc.login}.json"
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("login", "account_type", "symbols_json")}, indent=1))


if __name__ == "__main__":
    main()
