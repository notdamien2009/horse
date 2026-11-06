@echo off
cd /d "%~dp0"
py -3 "%~dp0local_history_runner.py" --stop
pause
