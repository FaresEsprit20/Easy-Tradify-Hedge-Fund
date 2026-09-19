@echo off
REM Start the Python services, ONE of each, each in its own window.
REM Use after a config change (e.g. USE_MARKET_STOP): running services keep the
REM settings they were started with until they are restarted.
REM Only ONE hybrid_monitor.py may run at a time -- duplicates take the same
REM signals and fill the same trade more than once (see README).
cd /d "%~dp0\..\api"
start "hybrid_monitor (port 5001)" cmd /k python hybrid_monitor.py
start "execution_controller (port 5000)" cmd /k python execution_controller.py
start "execute_copy_trade (port 5003)" cmd /k python execute_copy_trade.py

REM strategic_plan_v5_live_data.md -- neither of these places orders:
REM   engine_v2 shadow  each category proposes its own setup live, journaled
REM   data jobs         results for the decision log, daily MT5 vs Mongo check
cd /d "%~dp0\.."
start "engine_v2 shadow (no orders)" cmd /k python -m engine_v2.run.shadow
start "data jobs (no orders)" cmd /k python -m ai.data_jobs
REM   RSI-extreme divergence  the one M1 setup that beat its own opposite side in
REM                           the trend audit; confirmed or killed on live M1 data
REM                           (report: python -m engine_v2.run.shadow_rsi_div_m1 --report)
start "RSI divergence M1 shadow (no orders)" cmd /k python -m engine_v2.run.shadow_rsi_div_m1
REM   RSI divergence, +-1600 M1 swings  never places orders; the one DEV pass of
REM                           rsi_div_huge_swings.py, not confirmed, watched live
REM                           (report: python -m engine_v2.run.shadow_rsi_div_huge --report)
start "RSI divergence huge swings shadow (never orders)" cmd /k python -m engine_v2.run.shadow_rsi_div_huge
REM   RSI divergence H4  DEMO ORDERS (operator 2026-09-18): the one H1/H4 cell that passed
REM                      development + holdout; stops its own new orders on a STOP verdict
REM                      (40 trades) or at -10R (report: python -m engine_v2.run.rsi_div_h4 --report)
start "RSI divergence H4 (demo orders)" cmd /k python -m engine_v2.run.rsi_div_h4
