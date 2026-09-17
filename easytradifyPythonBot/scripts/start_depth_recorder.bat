@echo off
REM Order-book depth recorder (strategic plan v4). Read-only: places no orders.
REM Keep this window open (or run it at logon via Task Scheduler) while MT5 is running.
cd /d "%~dp0\.."
:loop
python -m engine_v2.run.depth_recorder
echo Recorder exited, restarting in 30 seconds...
timeout /t 30 /nobreak >nul
goto loop
