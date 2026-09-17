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
