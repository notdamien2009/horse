@echo off
cd /d "%~dp0"
py src\sl_history.py --self-test
py tests\test_recovery.py
pause
